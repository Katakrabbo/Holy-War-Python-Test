from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from holywar.core import query_helpers as query_ops
from holywar.core import zones as zone_ops
from holywar.effects.runtime import runtime_cards

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def _apply_sin_reduction_auras(engine: "GameEngine", receiver_idx: int, amount: int) -> int:
    out = max(0, int(amount))
    if out <= 0:
        return 0
    return int(runtime_cards.apply_rule(engine, "combat_sin_gain", out, player_idx=receiver_idx))


def _equipped_card_types(engine: "GameEngine", saint_uid: str) -> list[str]:
    inst = engine.state.instances.get(saint_uid)
    if inst is None:
        return []
    out: list[str] = []
    for tag in list(inst.blessed):
        if not isinstance(tag, str) or not tag.startswith("equipped_by:"):
            continue
        equip_uid = tag.split(":", 1)[1].strip()
        equip_inst = engine.state.instances.get(equip_uid)
        if equip_inst is None:
            continue
        out.append(_norm(equip_inst.definition.card_type))
    return out


def _matches_owner_scope(scope: str, source_owner: int, target_owner: int) -> bool:
    key = _norm(scope)
    if key in {"", "any"}:
        return True
    if key == "enemy":
        return int(source_owner) != int(target_owner)
    if key in {"friendly", "self", "owner", "controller"}:
        return int(source_owner) == int(target_owner)
    return False


def _apply_equipped_destroy_protection(
    engine: "GameEngine",
    target_uid: str,
    target_inst,
) -> bool:
    source_uid = str(engine.state.flags.get("_runtime_effect_source", "")).strip()
    if not source_uid or source_uid not in engine.state.instances:
        return False
    source_inst = engine.state.instances[source_uid]
    target_owner = int(target_inst.owner)
    target_type = _norm(target_inst.definition.card_type)

    for tag in list(target_inst.blessed):
        if not isinstance(tag, str) or not tag.startswith("equipped_by:"):
            continue
        equip_uid = tag.split(":", 1)[1].strip()
        equip_inst = engine.state.instances.get(equip_uid)
        if equip_inst is None:
            continue
        rules = runtime_cards.get_protection_rules(equip_inst.effect_name)
        for rule in rules:
            if _norm(str(rule.get("event", ""))) != "destroy_by_effect":
                continue
            if bool(rule.get("requires_source_to_be_equipped", False)) and equip_uid != source_uid:
                continue
            if not _matches_owner_scope(str(rule.get("source_owner", "any")), int(source_inst.owner), int(equip_inst.owner)):
                continue
            if not _matches_owner_scope(str(rule.get("target_owner", "any")), target_owner, int(equip_inst.owner)):
                continue
            target_types = {_norm(str(v)) for v in list(rule.get("target_card_types", []) or []) if str(v).strip()}
            if target_types and target_type not in target_types:
                continue

            faith_cfg = rule.get("set_target_faith")
            if isinstance(faith_cfg, str) and _norm(faith_cfg) in {"base", "initial", "printed"}:
                base = int(target_inst.definition.faith or 0)
                target_inst.current_faith = max(0, base)
            elif faith_cfg is not None:
                try:
                    target_inst.current_faith = max(0, int(faith_cfg))
                except (TypeError, ValueError):
                    pass

            if bool(rule.get("excommunicate_source", False)):
                engine.excommunicate_card(equip_inst.owner, equip_uid)

            log_msg = str(rule.get("log", "")).strip()
            if log_msg:
                engine.state.log(log_msg)
            else:
                engine.state.log(
                    f"{equip_inst.definition.name} protegge {target_inst.definition.name}: distruzione annullata."
                )
            return True
    return False


# Destroys all saints whose current Faith has reached zero or less.
def cleanup_zero_faith_saints(engine: "GameEngine") -> None:
    saint_types = {"santo", "token"}
    seen: set[str] = set()
    for board_owner in (0, 1):
        player = engine.state.players[board_owner]
        for uid in list(player.attack + player.defense):
            if uid is None or uid in seen or uid not in engine.state.instances:
                continue
            seen.add(uid)
            inst = engine.state.instances[uid]
            if _norm(inst.definition.card_type) not in saint_types:
                continue
            faith = inst.current_faith if inst.current_faith is not None else (inst.definition.faith or 0)
            if faith <= 0:
                destroy_saint_by_uid(engine, inst.owner, uid, cause="effect")


# Handles the full saint-destruction pipeline, including prevention, survival, and aftermath.
def destroy_saint_by_uid(
    engine: "GameEngine",
    owner_idx: int,
    uid: str,
    excommunicate: bool = False,
    cause: str = "effect",
    by_whom: str | None = None,
) -> None:
    if uid not in engine.state.instances:
        return
    inst = engine.state.instances[uid]
    source_uid_dbg = str(engine.state.flags.get("_runtime_effect_source", "")).strip()
    source_name_dbg = ""
    if source_uid_dbg and source_uid_dbg in engine.state.instances:
        source_name_dbg = str(engine.state.instances[source_uid_dbg].definition.name or "").strip()
    field_before_dbg = [
        engine.state.instances[c_uid].definition.name
        for c_uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
        if c_uid and c_uid in engine.state.instances
    ]
    engine.state.log(
        "[DESTROY_TRACE][BEFORE] "
        f"target_uid={uid} target_name={inst.definition.name} owner={owner_idx} cause={cause} by_whom={by_whom} "
        f"source_uid={source_uid_dbg} source_name={source_name_dbg} field_owner_before={field_before_dbg}"
    )
    board_owner_idx = engine._find_board_owner_of_uid(uid)
    if board_owner_idx is None:
        board_owner_idx = owner_idx
    board_player = engine.state.players[board_owner_idx]
    if runtime_cards.apply_rule(engine, "prevent_saint_destruction", False, uid=uid, cause=cause):
        return
    if cause == "effect":
        source_uid = str(engine.state.flags.get("_runtime_effect_source", ""))
        if source_uid and source_uid in engine.state.instances:
            source = engine.state.instances[source_uid]
            if int(source.owner) != int(owner_idx):
                source_type = _norm(source.definition.card_type)
                defender = engine.state.players[owner_idx]
                defensive_sources = [uid for uid in defender.artifacts if uid]
                if defender.building:
                    defensive_sources.append(defender.building)
                for def_uid in defensive_sources:
                    def_inst = engine.state.instances.get(def_uid)
                    if def_inst is None:
                        continue
                    if runtime_cards.blocks_interaction(
                        def_inst.effect_name,
                        event="destroy_by_effect",
                        source_owner="enemy",
                        target_owner="friendly",
                        source_card_type=source_type,
                        target_card_type=_norm(inst.definition.card_type),
                        target_card_name=inst.definition.name,
                    ):
                        engine.state.log(
                            f"{def_inst.definition.name} impedisce a {source.definition.name} di distruggere {inst.definition.name}."
                        )
                        return
    # Check if the card is currently in an attack or defense slot and clear that slot, keeping track of which slot it was in for later. If the card is not found in either slot, treat it as being on the field without a specific slot. This allows the destruction process to correctly handle the card's position on the board and apply any relevant effects based on whether it was in attack, defense, or just on the field.
    attack_slot = None
    defense_slot = None
    for i, slot_uid in enumerate(board_player.attack):
        if slot_uid == uid:
            attack_slot = i
            break
    if attack_slot is None:
        for i, slot_uid in enumerate(board_player.defense):
            if slot_uid == uid:
                defense_slot = i
                break
    from_zone = "attack" if attack_slot is not None else ("defense" if defense_slot is not None else "field")
    if attack_slot is not None:
        board_player.attack[attack_slot] = None
    if defense_slot is not None:
        board_player.defense[defense_slot] = None

    # Handle any battle survival mechanics if the cause of destruction is a battle, which can allow the card to avoid destruction by sacrificing a token from the field or excommunicating a card from the graveyard, depending on the card's definition and the current game state. This includes checking for any battle survival modes defined for the card, and if applicable, performing the necessary actions to prevent destruction while applying any relevant effects such as restoring faith or promoting defense slots.
    if cause == "battle":
        survival_mode = runtime_cards.get_battle_survival_mode(inst.effect_name)
        if survival_mode == "sacrifice_token_from_field":
            token_name = runtime_cards.get_battle_survival_token_name(inst.effect_name)
            token_uid = None
            if token_name:
                for s_uid in board_player.attack + board_player.defense:
                    if not s_uid:
                        continue
                    if _norm(engine.state.instances[s_uid].definition.name) == _norm(token_name):
                        token_uid = s_uid
                        break
            # If a valid token is found, sacrifice it to prevent the destruction of the saint, restore the saint's faith as needed, and promote any defense slots if applicable. This allows the card to survive the battle by sacrificing a specific token from the field, while also applying any relevant effects such as restoring faith or adjusting the board state based on the sacrifice.
            if token_uid is not None:
                destroy_saint_by_uid(engine, engine.state.instances[token_uid].owner, token_uid, cause="effect")
                inst.current_faith = max(
                    0,
                    runtime_cards.get_battle_survival_restore_faith(inst.effect_name) or (inst.definition.faith or 0),
                )
                if attack_slot is not None:
                    board_player.attack[attack_slot] = uid
                elif defense_slot is not None:
                    board_player.defense[defense_slot] = uid
                zone_ops.promote_defense_frontline(engine, board_owner_idx)
                engine.state.log(f"{inst.definition.name} evita la distruzione sacrificando {token_name}.")
                return
        # Note: the "excommunicate_card_from_graveyard" mode is intentionally checked after the token sacrifice mode, so that if a card has both modes it will try to sacrifice a token first before excommunicating from the graveyard.
        if survival_mode == "excommunicate_card_from_graveyard":
            rescue_names = {_norm(name) for name in runtime_cards.get_battle_survival_names(inst.effect_name)}
            rescue_uid = None
            for g_uid in list(board_player.graveyard):
                g_name = _norm(engine.state.instances[g_uid].definition.name)
                if g_name in rescue_names:
                    rescue_uid = g_uid
                    break
            # If a valid card is found in the graveyard, excommunicate it to prevent the destruction of the saint, restore the saint's faith as needed, and promote any defense slots if applicable. This allows the card to survive the battle by excommunicating a specific card from the graveyard, while also applying any relevant effects such as restoring faith or adjusting the board state based on the excommunication.
            if rescue_uid is not None:
                board_player.graveyard.remove(rescue_uid)
                board_player.excommunicated.append(rescue_uid)
                if attack_slot is not None:
                    board_player.attack[attack_slot] = uid
                elif defense_slot is not None:
                    board_player.defense[defense_slot] = uid
                zone_ops.promote_defense_frontline(engine, board_owner_idx)
                inst.current_faith = max(
                    0,
                    runtime_cards.get_battle_survival_restore_faith(inst.effect_name) or (inst.definition.faith or 0),
                )
                engine.state.log(
                    f"{inst.definition.name} evita la distruzione: scomunica {engine.state.instances[rescue_uid].definition.name} "
                    "e annulla la distruzione."
                )
                return

    # Handle the gain of Sin for the controller of the card if it's not a token, applying any relevant effects or prevention based on the card's blessed tags and the current game state. This includes calculating the Sin gain based on the card's definition and any relevant blessed tags, determining who should receive the Sin, and applying any prevention effects from artifacts or blessed tags before granting the Sin and logging it in the game state.
    if _norm(inst.definition.card_type) != "token":
        sin_gain = max(0, inst.definition.faith or 0)
        if sin_gain <= 0:
            for tag in list(inst.blessed):
                if not isinstance(tag, str) or not tag.startswith("paid_inspiration_on_summon:"):
                    continue
                try:
                    sin_gain = max(0, int(tag.split(":", 1)[1]))
                except (TypeError, ValueError):
                    sin_gain = 0
                break

        # Determine who should receive the Sin gain, which is usually the controller of the card but can be the owner if the card is on the field without a specific slot, and apply any prevention effects from blessed tags or artifacts before granting the Sin. This ensures that the correct player receives the Sin gain based on the card's position and any relevant effects, while also applying any prevention from blessed tags or artifacts that can negate Sin gain on death.
        sin_receiver_idx = int(board_owner_idx) if board_owner_idx in (0, 1) else int(owner_idx)
        if "sin_to_controller_on_death" in inst.blessed and board_owner_idx in (0, 1):
            sin_receiver_idx = int(board_owner_idx)

        # Apply any prevention of Sin gain from blessed tags or artifacts, then grant the Sin to the appropriate player and log it in the game state. This includes checking for any relevant blessed tags that can prevent Sin gain on death, as well as any artifacts that can negate Sin gain, before applying the Sin gain to the determined receiver and logging the event in the game state for transparency.
        if "no_sin_on_death" in inst.blessed:
            sin_gain = 0
        if _norm(inst.definition.card_type) in {"santo", "token"}:
            receiver_player = engine.state.players[sin_receiver_idx]
            defensive_sources = [uid for uid in receiver_player.artifacts if uid]
            if receiver_player.building:
                defensive_sources.append(receiver_player.building)
            equipped_types = _equipped_card_types(engine, uid)
            for def_uid in defensive_sources:
                def_inst = engine.state.instances.get(def_uid)
                if def_inst is None:
                    continue
                if runtime_cards.blocks_interaction(
                    def_inst.effect_name,
                    event="sin_on_death",
                    source_owner="any",
                    target_owner="friendly",
                    source_card_type="any",
                    target_card_type=_norm(inst.definition.card_type),
                    target_card_name=inst.definition.name,
                    target_equipped_by_card_types=equipped_types,
                ):
                    sin_gain = 0
                    break
        sin_gain = _apply_sin_reduction_auras(engine, sin_receiver_idx, sin_gain)
        engine.gain_sin(sin_receiver_idx, sin_gain)
        engine.state.log(
            f"{inst.definition.name} viene distrutto: {engine.state.players[sin_receiver_idx].name} guadagna {sin_gain} Peccato."
        )
    else:
        engine.state.log(f"{inst.definition.name} (Token) viene distrutto.")

    # Emit all relevant events for the destruction of the card, including specific events for battle destruction or effect destruction, as well as general events for any saint being defeated or destroyed, and then handle the actual removal of the card from the board and sending it to the graveyard or excommunicating it as needed. This ensures that all relevant events are emitted for the destruction of the card, allowing other effects to trigger in response, while also correctly handling the removal of the card from the board and its placement in the graveyard or excommunication zone based on the context of its destruction.
    engine._emit_event(
        "on_this_card_destroyed",
        owner_idx,
        card=uid,
        controller=board_owner_idx,
        by_whom=by_whom,
        source=by_whom,
        reason=cause,
    )
    engine._emit_event(
        "on_card_destroyed_on_field",
        owner_idx,
        card=uid,
        controller=board_owner_idx,
        by_whom=by_whom,
        source=by_whom,
        reason=cause,
    )
    # Note: the "on_card_destroyed_on_field" event is intentionally emitted for all cards destroyed on the field, including tokens, while the more specific "on_this_card_destroyed" event is emitted for all cards but can be used to filter for specific cards or types in response. This allows for more flexible event handling where effects can respond to any card being destroyed on the field, or specifically to certain cards being destroyed, depending on the needs of the effect.
    if excommunicate:
        zone_ops.excommunicate_card(engine, owner_idx, uid, from_zone_override=from_zone, defer_equipment_cleanup=True)
    else:
        zone_ops.send_to_graveyard(engine, owner_idx, uid, token_to_white=True, from_zone_override=from_zone, defer_equipment_cleanup=True)
    if attack_slot is not None:
        back_uid = board_player.defense[attack_slot]
        if back_uid is not None:
            board_player.attack[attack_slot] = back_uid
            board_player.defense[attack_slot] = None
            engine.state.log(
                f"{engine.state.instances[back_uid].definition.name} avanza dalla difesa all'attacco."
            )
    # Note: the "on_saint_defeated_in_battle" event is intentionally emitted only for battle destruction, while the "on_saint_destroyed_by_effect" event is emitted for effect destruction, allowing effects to specifically respond to the context of the saint's destruction if needed.
    if cause == "battle":
        engine._emit_event(
            "on_saint_defeated_in_battle",
            owner_idx,
            saint=uid,
            controller=board_owner_idx,
            by_whom=by_whom,
            source=by_whom,
        )
    else:
        engine._emit_event(
            "on_saint_destroyed_by_effect",
            owner_idx,
            saint=uid,
            controller=board_owner_idx,
            by_whom=by_whom,
            source=by_whom,
        )
    engine._emit_event("on_saint_defeated_or_destroyed", owner_idx, saint=uid, controller=board_owner_idx, reason=cause)
    zone_ops.cleanup_equipment_links_on_leave_field(engine, uid)
    field_after_dbg = [
        engine.state.instances[c_uid].definition.name
        for c_uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
        if c_uid and c_uid in engine.state.instances
    ]
    engine.state.log(
        "[DESTROY_TRACE][AFTER] "
        f"target_uid={uid} target_name={inst.definition.name} owner={owner_idx} cause={cause} "
        f"field_owner_after={field_after_dbg}"
    )


# Routes card destruction based on its type so callers can use one entry point.
def destroy_any_card(engine: "GameEngine", owner_idx: int, uid: str) -> None:
    if uid is None:
        return
    inst = engine.state.instances.get(uid)
    if inst is None:
        return
    script = runtime_cards.get_script(inst.effect_name)
    if script and bool(script.indestructible_except_own_activation):
        allowed_uid = str(engine.state.flags.get("_allow_indestructible_uid", "")).strip()
        if allowed_uid != uid:
            return

    if _apply_equipped_destroy_protection(engine, uid, inst):
        return

    if runtime_cards.apply_rule(engine, "prevent_card_destruction", False, uid=uid):
        return

    # Optional script-driven destroy tax: enemy must pay inspiration and sacrifice board cards.
    tax_cfg = dict(script.destroy_requires_building_or_artifacts_and_inspiration or {}) if script else {}
    if tax_cfg:
        source_uid = str(engine.state.flags.get("_runtime_effect_source", "")).strip()
        if source_uid and source_uid in engine.state.instances and source_uid != uid:
            source_owner = int(engine.state.instances[source_uid].owner)
            target_board_owner = engine._find_board_owner_of_uid(uid)
            target_owner = int(target_board_owner) if target_board_owner in (0, 1) else int(inst.owner)
            if source_owner != target_owner:
                pay_insp = max(0, int(tax_cfg.get("inspiration", 0) or 0))
                sacrifice_buildings = max(0, int(tax_cfg.get("sacrifice_buildings", 0) or 0))
                sacrifice_artifacts = max(0, int(tax_cfg.get("sacrifice_artifacts", 0) or 0))
                player = engine.state.players[source_owner]
                total_insp = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
                has_building_cost = sacrifice_buildings > 0 and player.building is not None
                has_artifact_cost = sacrifice_artifacts > 0 and len([a for a in player.artifacts if a]) >= sacrifice_artifacts
                can_pay_board_cost = has_building_cost or has_artifact_cost
                if total_insp < pay_insp or not can_pay_board_cost:
                    engine.state.log(
                        f"{inst.definition.name} annulla la distruzione: costo non pagato da {engine.state.players[source_owner].name}."
                    )
                    return

                if has_building_cost:
                    building_uid = player.building
                    if building_uid:
                        engine.send_to_graveyard(source_owner, building_uid)
                else:
                    sacrificed = 0
                    for art_uid in list(player.artifacts):
                        if not art_uid:
                            continue
                        engine.send_to_graveyard(source_owner, art_uid)
                        sacrificed += 1
                        if sacrificed >= sacrifice_artifacts:
                            break

                cost = pay_insp
                temp = max(0, int(getattr(player, "temporary_inspiration", 0)))
                use_temp = min(temp, cost)
                player.temporary_inspiration = temp - use_temp
                player.inspiration = max(0, int(player.inspiration) - (cost - use_temp))

    ctype = _norm(inst.definition.card_type)
    if ctype in {"santo", "token"}:
        destroy_saint_by_uid(engine, inst.owner, uid, cause="effect")
    else:
        engine.send_to_graveyard(owner_idx, uid)
