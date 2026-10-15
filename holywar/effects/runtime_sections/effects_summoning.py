from __future__ import annotations

from typing import TYPE_CHECKING

from holywar.core import state
from holywar.core import query_helpers as query_ops
from holywar.effects.runtime import _norm, EffectSpec

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsSummoningMixin:
    if TYPE_CHECKING:
        def _resolve_owner_scope(self, owner_idx: int, owner_key: str | None) -> int: ...
        def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int: ...
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
        def _apply_effect(
            self,
            engine: GameEngine,
            owner_idx: int,
            source_uid: str,
            targets: list[str],
            effect: EffectSpec,
        ) -> None: ...
        def _move_uid_to_zone(self, engine: GameEngine, uid: str, to_zone: str, owner_idx: int) -> bool: ...
        def _summon_generated_token(
            self,
            engine: GameEngine,
            owner_idx: int,
            token_name: str,
            preferred_zone: str | None = None,
            preferred_slot_token: str | None = None,
        ) -> str | None: ...
        def _has_invert_saint_summon_aura(self, engine: GameEngine) -> bool: ...
        def resolve_enter(self, engine: GameEngine, player_idx: int, uid: str) -> object: ...
        def get_context_bonus_amount(
            self,
            engine: GameEngine,
            owner_idx: int,
            context: str,
            amount_mode: str = "flat",
            target_uid: str | None = None,
        ) -> int: ...

    def _apply_effect_summon_action(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
        effect: EffectSpec,
        action: str,
    ) -> bool:
        if action == "summon_card_from_hand":
            selected = str(engine.state.flags.get("_runtime_selected_target", "")).strip()
            player = engine.state.players[owner_idx]
            selected_uid = selected if selected in engine.state.instances else None
            chosen_uid = selected_uid if selected_uid in player.hand else None
            if chosen_uid is None:
                card_name = _norm(effect.card_name or selected)
                if not card_name:
                    return True
                for h_uid in list(player.hand):
                    if _norm(engine.state.instances[h_uid].definition.name) == card_name:
                        chosen_uid = h_uid
                        break
            if chosen_uid is None:
                return True
            chosen_inst = engine.state.instances.get(chosen_uid)
            if chosen_inst is None:
                return True
            board_owner = owner_idx
            if _norm(chosen_inst.definition.card_type) == _norm("santo") and self._has_invert_saint_summon_aura(engine):
                board_owner = 1 - board_owner
            board_player = engine.state.players[board_owner]
            slot = engine._first_open(board_player.attack)
            zone = "attack"
            if slot is None:
                slot = engine._first_open(board_player.defense)
                zone = "defense"
            if slot is None:
                return True
            player.hand.remove(chosen_uid)
            if not engine.place_card_from_uid(board_owner, chosen_uid, zone, slot):
                player.hand.append(chosen_uid)
                return True
            engine.state.flags.setdefault("activated_turn", {}).pop(chosen_uid, None)
            inst = engine.state.instances[chosen_uid]
            inst.exhausted = False
            if _norm(inst.definition.card_type) in {_norm("santo"), _norm("token")}:
                bonus_multiplier = self.get_context_bonus_amount(
                    engine,
                    owner_idx,
                    context="summon_faith",
                    amount_mode="base_faith_multiplier",
                )
                if bonus_multiplier > 0:
                    inst.current_faith = (inst.current_faith or 0) + max(0, int(inst.definition.faith or 0)) * bonus_multiplier
                bonus_flat = self.get_context_bonus_amount(
                    engine,
                    owner_idx,
                    context="summon_faith",
                    amount_mode="flat",
                )
                if bonus_flat > 0:
                    inst.current_faith = (inst.current_faith or 0) + int(bonus_flat)
            engine.state.log(f"{player.name} evoca {inst.definition.name} dalla mano.")
            engine._emit_event("on_enter_field", owner_idx, card=chosen_uid, from_zone="hand")
            engine._emit_event("on_summoned_from_hand", owner_idx, card=chosen_uid)
            ctype = _norm(inst.definition.card_type)
            if ctype == _norm("token"):
                engine._emit_event("on_token_summoned", owner_idx, token=chosen_uid, summoner=owner_idx)
            elif ctype == _norm("santo"):
                engine._emit_event("on_opponent_saint_enters_field", 1 - owner_idx, saint=chosen_uid)
            enter_msg = self.resolve_enter(engine, owner_idx, chosen_uid)
            if enter_msg:
                engine.state.log(str(enter_msg))
            return True
        if action == "summon_named_card":
            selected = str(engine.state.flags.get("_runtime_selected_target", "")).strip()
            selected_uid = selected if selected in engine.state.instances else None
            card_name = _norm(effect.card_name or selected)

            if not card_name and selected_uid is None:
                return True

            player = engine.state.players[owner_idx]
            chosen_uid = None
            chosen_from_zone = None

            for pool_name in ("hand", "deck", "graveyard", "white_deck", "excommunicated"):
                pool = getattr(player, pool_name)
                for uid in list(pool):
                    if selected_uid is not None:
                        if uid != selected_uid:
                            continue
                    else:
                        if _norm(engine.state.instances[uid].definition.name) != card_name:
                            continue

                    chosen_uid = uid
                    chosen_from_zone = pool_name
                    pool.remove(uid)
                    break
                if chosen_uid:
                    break
            if chosen_uid is None:
                return True
            chosen_inst = engine.state.instances[chosen_uid]
            chosen_type = _norm(chosen_inst.definition.card_type)
            board_owner = owner_idx
            board_player = player
            if chosen_type == "santo" and self._has_invert_saint_summon_aura(engine):
                board_owner = 1 - board_owner
                board_player = engine.state.players[board_owner]
            slot = None
            zone = ""
            if chosen_type in {"santo", "token"}:
                attack_slots = [f"a{i + 1}" for i, uid in enumerate(board_player.attack) if uid is None]
                defense_slots = [f"d{i + 1}" for i, uid in enumerate(board_player.defense) if uid is None]
                open_slots = attack_slots + defense_slots
                chosen_token = ""
                chooser = getattr(engine, "choose_summon_slot", None)
                if callable(chooser) and open_slots:
                    try:
                        chosen_token = str(chooser(board_owner, chosen_uid, open_slots) or "").strip().lower()
                    except Exception:
                        chosen_token = ""
                if chosen_token in {token.lower() for token in open_slots}:
                    zone = "attack" if chosen_token.startswith("a") else "defense"
                    slot = int(chosen_token[1:]) - 1
                if slot is None:
                    slot = engine._first_open(board_player.attack)
                    zone = "attack"
                    if slot is None:
                        slot = engine._first_open(board_player.defense)
                        zone = "defense"
            elif chosen_type == "artefatto":
                blocked_slots = query_ops.get_blocked_artifact_slots_for_player(engine, owner_idx)
                usable_slots = [idx for idx in range(state.ARTIFACT_SLOTS) if idx not in blocked_slots]
                slot = next((i for i in usable_slots if player.artifacts[i] is None), None)
                if slot is None and usable_slots:
                    slot = usable_slots[-1]
                    replaced = player.artifacts[slot]
                    if replaced:
                        engine.send_to_graveyard(owner_idx, replaced)
                zone = "artifact" if slot is not None else ""
            elif chosen_type == "edificio":
                if player.building is None:
                    slot = 0
                    zone = "building"
            else:
                slot = engine._first_open(player.attack)
                zone = "attack"
                if slot is None:
                    slot = engine._first_open(player.defense)
                    zone = "defense"
            if slot is None or not zone:
                return True
            if not engine.place_card_from_uid(board_owner, chosen_uid, zone, slot):
                return True
            engine.state.flags.setdefault("activated_turn", {}).pop(chosen_uid, None)
            inst = engine.state.instances[chosen_uid]
            inst.exhausted = False
            if chosen_type in {"santo", "token"}:
                bonus_multiplier = self.get_context_bonus_amount(
                    engine,
                    owner_idx,
                    context="summon_faith",
                    amount_mode="base_faith_multiplier",
                )
                if bonus_multiplier > 0:
                    inst.current_faith = (inst.current_faith or 0) + max(0, int(inst.definition.faith or 0)) * bonus_multiplier
                bonus_flat = self.get_context_bonus_amount(
                    engine,
                    owner_idx,
                    context="summon_faith",
                    amount_mode="flat",
                )
                if bonus_flat > 0:
                    inst.current_faith = (inst.current_faith or 0) + int(bonus_flat)
            engine.state.log(f"{player.name} evoca {inst.definition.name}.")
            actual_from_zone = chosen_from_zone or "summon"
            engine._emit_event("on_enter_field", owner_idx, card=chosen_uid, from_zone=actual_from_zone)

            if actual_from_zone == "graveyard":
                engine._emit_event("on_summoned_from_graveyard", owner_idx, card=chosen_uid)
            elif actual_from_zone == "hand":
                engine._emit_event("on_summoned_from_hand", owner_idx, card=chosen_uid)
            ctype = _norm(inst.definition.card_type)
            if ctype == _norm("token"):
                engine._emit_event("on_token_summoned", owner_idx, token=chosen_uid, summoner=owner_idx)
            elif ctype == _norm("santo"):
                engine._emit_event("on_opponent_saint_enters_field", 1 - owner_idx, saint=chosen_uid)
            enter_msg = self.resolve_enter(engine, owner_idx, chosen_uid)
            if enter_msg:
                engine.state.log(str(enter_msg))
            return True
        if action == "summon_named_card_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                copies = int(raw_value)
            except (TypeError, ValueError):
                copies = 0
            if copies <= 0:
                engine.state.flags.pop(flag_name, None)
                return True

            card_name = _norm(effect.card_name or "")
            if not card_name:
                engine.state.flags.pop(flag_name, None)
                return True

            player = engine.state.players[owner_idx]
            for _ in range(copies):
                chosen_uid = None
                chosen_from_zone = None
                for pool_name in ("hand", "deck"):
                    pool = getattr(player, pool_name)
                    for uid in list(pool):
                        if _norm(engine.state.instances[uid].definition.name) != card_name:
                            continue
                        chosen_uid = uid
                        chosen_from_zone = pool_name
                        pool.remove(uid)
                        break
                    if chosen_uid:
                        break
                if chosen_uid is None:
                    break

                chosen_inst = engine.state.instances[chosen_uid]
                chosen_type = _norm(chosen_inst.definition.card_type)
                board_owner = owner_idx
                board_player = player
                if chosen_type == "santo" and self._has_invert_saint_summon_aura(engine):
                    board_owner = 1 - board_owner
                    board_player = engine.state.players[board_owner]
                slot = None
                zone = ""
                if chosen_type in {"santo", "token"}:
                    slot = engine._first_open(board_player.attack)
                    zone = "attack"
                    if slot is None:
                        slot = engine._first_open(board_player.defense)
                        zone = "defense"
                elif chosen_type == "artefatto":
                    blocked_slots = query_ops.get_blocked_artifact_slots_for_player(engine, owner_idx)
                    usable_slots = [idx for idx in range(state.ARTIFACT_SLOTS) if idx not in blocked_slots]
                    slot = next((i for i in usable_slots if player.artifacts[i] is None), None)
                    if slot is None and usable_slots:
                        slot = usable_slots[-1]
                        replaced = player.artifacts[slot]
                        if replaced:
                            engine.send_to_graveyard(owner_idx, replaced)
                    zone = "artifact" if slot is not None else ""
                elif chosen_type == "edificio":
                    if player.building is None:
                        slot = 0
                        zone = "building"
                else:
                    slot = engine._first_open(player.attack)
                    zone = "attack"
                    if slot is None:
                        slot = engine._first_open(player.defense)
                        zone = "defense"
                if slot is None or not zone:
                    if chosen_from_zone:
                        getattr(player, chosen_from_zone).insert(0, chosen_uid)
                    break
                if not engine.place_card_from_uid(board_owner, chosen_uid, zone, slot):
                    if chosen_from_zone:
                        getattr(player, chosen_from_zone).insert(0, chosen_uid)
                    break

                engine.state.flags.setdefault("activated_turn", {}).pop(chosen_uid, None)
                inst = engine.state.instances[chosen_uid]
                inst.exhausted = False
                if chosen_type in {"santo", "token"}:
                    bonus_multiplier = self.get_context_bonus_amount(
                        engine,
                        owner_idx,
                        context="summon_faith",
                        amount_mode="base_faith_multiplier",
                    )
                    if bonus_multiplier > 0:
                        inst.current_faith = (inst.current_faith or 0) + max(0, int(inst.definition.faith or 0)) * bonus_multiplier
                    bonus_flat = self.get_context_bonus_amount(
                        engine,
                        owner_idx,
                        context="summon_faith",
                        amount_mode="flat",
                    )
                    if bonus_flat > 0:
                        inst.current_faith = (inst.current_faith or 0) + int(bonus_flat)
                engine.state.log(f"{player.name} evoca {inst.definition.name}.")
                actual_from_zone = chosen_from_zone or "summon"
                engine._emit_event("on_enter_field", owner_idx, card=chosen_uid, from_zone=actual_from_zone)

                if actual_from_zone == "graveyard":
                    engine._emit_event("on_summoned_from_graveyard", owner_idx, card=chosen_uid)
                elif actual_from_zone == "hand":
                    engine._emit_event("on_summoned_from_hand", owner_idx, card=chosen_uid)
                ctype = _norm(inst.definition.card_type)
                if ctype == _norm("token"):
                    engine._emit_event("on_token_summoned", owner_idx, token=chosen_uid, summoner=owner_idx)
                elif ctype == _norm("santo"):
                    engine._emit_event("on_opponent_saint_enters_field", 1 - owner_idx, saint=chosen_uid)
                enter_msg = self.resolve_enter(engine, owner_idx, chosen_uid)
                if enter_msg:
                    engine.state.log(str(enter_msg))

            engine.state.flags.pop(flag_name, None)
            return True
        if action == "summon_generated_token":
            token_name = str(effect.card_name or "").strip()
            if not token_name:
                return True
            summon_owner = self._resolve_owner_scope(owner_idx, effect.owner or "me")
            copies = max(1, int(effect.amount or 1))
            preferred_zone = str(effect.zone or "").strip() or None
            preferred_slot_token = None
            if _norm(str(effect.position or "")) == "selected_target_slot":
                preferred_slot_token = self._selected_target_raw_for_current_action(engine)
            for _ in range(copies):
                self._summon_generated_token(
                    engine,
                    summon_owner,
                    token_name,
                    preferred_zone=preferred_zone,
                    preferred_slot_token=preferred_slot_token,
                )
            return True
        if action == "summon_target_to_field_pay_half_inspiration":
            payer_idx = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            payer = engine.state.players[payer_idx]
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                base_cost = max(0, int(inst.definition.faith or 0))
                half_cost = (base_cost + 1) // 2
                total_inspiration = int(payer.inspiration) + int(getattr(payer, "temporary_inspiration", 0))
                if total_inspiration < half_cost:
                    engine.state.log(
                        f"{inst.definition.name}: Ispirazione insufficiente ({total_inspiration}/{half_cost}) per evocare pagando meta costo."
                    )
                    continue

                temp = max(0, int(getattr(payer, "temporary_inspiration", 0)))
                use_temp = min(temp, half_cost)
                payer.temporary_inspiration = temp - use_temp
                payer.inspiration = max(0, int(payer.inspiration) - (half_cost - use_temp))

                self._apply_effect(
                    engine,
                    owner_idx,
                    source_uid,
                    [t_uid],
                    EffectSpec(action="summon_target_to_field"),
                )
            return True
        if action == "summon_generated_token_in_each_free_saint_slot":
            token_name = str(effect.card_name or "").strip()
            if not token_name:
                return True
            summon_owner = self._resolve_owner_scope(owner_idx, effect.owner or "me")
            player = engine.state.players[summon_owner]
            free_slots = sum(1 for uid in player.attack if uid is None) + sum(1 for uid in player.defense if uid is None)
            for _ in range(max(0, int(free_slots))):
                self._summon_generated_token(engine, summon_owner, token_name)
            return True
        if action == "summon_token":
            token_name = str(effect.card_name or "").strip()
            if not token_name:
                engine.state.log("summon_token: card_name vuoto.")
                return True

            source_inst = engine.state.instances.get(source_uid)
            source_name = source_inst.definition.name if source_inst is not None else source_uid

            per_turn_key = f"spirito_esercito_dorato_used:{owner_idx}:{source_uid}:{engine.state.turn_number}"
            if engine.state.flags.get(per_turn_key):
                engine.state.log(f"{source_name}: effetto già usato in questo turno.")
                return True

            summoned_uid = self._summon_generated_token(engine, owner_idx, token_name)
            if summoned_uid is None:
                engine.state.log(f"{source_name}: evocazione del token fallita.")
                return True

            engine.state.flags[per_turn_key] = True
            engine.state.log(f"{source_name}: token evocato con successo ({token_name}).")
            return True
        if action == "move_to_deck_bottom":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                owner = inst.owner
                if engine.move_graveyard_card_to_deck_bottom(owner, t_uid):
                    engine.state.log(f"{inst.definition.name} torna nel reliquiario.")
            return True
        if action == "move_to_relicario":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                owner = inst.owner
                if self._move_uid_to_zone(engine, t_uid, "deck_bottom", owner):
                    engine.state.log(f"{inst.definition.name} torna nel reliquiario.")
            return True
        if action == "shuffle_deck":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            engine.rng.shuffle(engine.state.players[target].deck)
            return True
        if action == "shuffle_target_owner_decks":
            owners = {engine.state.instances[t_uid].owner for t_uid in targets if t_uid in engine.state.instances}
            for owner in owners:
                engine.rng.shuffle(engine.state.players[owner].deck)
            return True
        if action == "move_source_to_board":
            source = str(engine.state.flags.get("_runtime_source_card", ""))
            if not source or source not in engine.state.instances:
                return True
            player = engine.state.players[owner_idx]
            if source not in player.hand:
                return True
            requested = str(engine.state.flags.get("_runtime_selected_target", "")).strip().lower()
            slot = None
            zone = ""
            if requested:
                parsed_zone, parsed_slot = engine._parse_zone_target(requested)
                if parsed_zone in {"attack", "defense"} and parsed_slot >= 0:
                    slots = player.attack if parsed_zone == "attack" else player.defense
                    if parsed_slot < len(slots) and slots[parsed_slot] is None:
                        zone = parsed_zone
                        slot = parsed_slot
            if slot is None:
                slot = engine._first_open(player.attack)
                zone = "attack"
                if slot is None:
                    slot = engine._first_open(player.defense)
                    zone = "defense"
                if slot is None:
                    return True
            player.hand.remove(source)
            if not engine.place_card_from_uid(owner_idx, source, zone, slot):
                player.hand.append(source)
                return True
            engine.state.flags.setdefault("activated_turn", {}).pop(source, None)
            inst = engine.state.instances[source]
            inst.exhausted = False
            engine.state.log(f"{player.name} posiziona {inst.definition.name}.")
            engine._emit_event("on_enter_field", owner_idx, card=source, from_zone="hand")
            engine._emit_event("on_summoned_from_hand", owner_idx, card=source)
            ctype = _norm(inst.definition.card_type)
            if ctype == _norm("token"):
                engine._emit_event("on_token_summoned", owner_idx, token=source, summoner=owner_idx)
            elif ctype == _norm("santo"):
                engine._emit_event("on_opponent_saint_enters_field", 1 - owner_idx, saint=source)
            enter_msg = self.resolve_enter(engine, owner_idx, source)
            if enter_msg:
                engine.state.log(str(enter_msg))
            return True
        return False
