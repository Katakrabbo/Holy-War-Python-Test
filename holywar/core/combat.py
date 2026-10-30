from __future__ import annotations

import unicodedata
from typing import Any

from holywar.core import query_helpers as query_ops
from holywar.core.results import ActionResult
from holywar.core.state import ATTACK_SLOTS, CardInstance
from holywar.effects.runtime import runtime_cards
from holywar.effects.state_flags import ensure_runtime_state, refresh_player_flags, set_phase

GameEngine = Any

# Utility function to normalize text for consistent comparisons, removing accents and converting to lowercase. This is used for comparing card types and other string attributes in a way that is insensitive to formatting differences.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def _apply_sin_reduction_auras(engine: "GameEngine", receiver_idx: int, amount: int) -> int:
    out = max(0, int(amount))
    if out <= 0:
        return 0
    return int(runtime_cards.apply_rule(engine, "combat_sin_gain", out, player_idx=receiver_idx))

# Checks if there is an active "no attacks until draw" effect in the current game state, which can block all attacks until a player draws a card. This is used to enforce effects that prevent attacking for a turn or until a specific condition is met, and it cleans up any invalid sources of this effect from the runtime state.
def _has_active_no_attack_until_draw(engine: "GameEngine") -> bool:
    runtime_state = engine.state.flags.setdefault("runtime_state", {})
    raw_sources = list(runtime_state.get("no_attacks_until_draw_sources", []) or [])
    if not raw_sources:
        return False
    runtime_state["no_attacks_until_draw_sources"] = [uid for uid in raw_sources if str(uid).strip()]
    return bool(runtime_state["no_attacks_until_draw_sources"])

# Checks if the attacker has an extra attack available for the current turn, which can allow it to attack again even if it is exhausted. This is used to support effects that grant additional attacks to a card for a specific turn, and it looks for a specific tag in the card's blessed list to determine if the extra attack is available.
def _has_extra_attack_for_turn(attacker: CardInstance, turn_number: int) -> bool:
    wanted = f"extra_attack_turn:{int(turn_number)}"
    return any(str(tag) == wanted for tag in list(attacker.blessed))

# Consumes an extra attack for the turn if available, removing the corresponding tag from the attacker's blessed list. This is called when an attack is declared with an extra attack available, and it ensures that the extra attack is only used once per turn by removing the tag that grants it.
def _consume_extra_attack_for_turn(attacker: CardInstance, turn_number: int) -> bool:
    wanted = f"extra_attack_turn:{int(turn_number)}"
    if wanted not in attacker.blessed:
        return False
    attacker.blessed = [tag for tag in attacker.blessed if str(tag) != wanted]
    return True


# Starts battle-phase bookkeeping when the first attack of the turn is declared.
def start_battle_phase_if_needed(engine: "GameEngine", player_idx: int) -> None:
    runtime_state = ensure_runtime_state(engine)
    if not bool(runtime_state.get("battle_phase_started", False)):
        runtime_state["battle_phase_started"] = True
        set_phase(engine, "battle")
        engine._emit_event("on_battle_phase_start", player_idx, player=player_idx)
        refresh_player_flags(engine)


# Validates the attacker-side rules that can stop combat before damage is assigned.
def validate_attack_preconditions(
    engine: "GameEngine",
    player_idx: int,
    defender_idx: int,
    attacker_uid: str,
    attacker: CardInstance,
    target_slot: int | None,
) -> ActionResult | None:
    defender_player = engine.state.players[defender_idx]

    cv = attacker.definition.crosses
    try:
        attacker_crosses = int(float(cv)) if cv is not None else None
    except ValueError:
        attacker_crosses = None
    if attacker_crosses is not None:
        defender_field = [uid for uid in (defender_player.attack + defender_player.defense + defender_player.artifacts) if uid]
        if defender_player.building:
            defender_field.append(defender_player.building)
        for aura_uid in defender_field:
            aura_inst = engine.state.instances.get(aura_uid)
            if aura_inst is None:
                continue
            threshold = runtime_cards.get_blocks_enemy_attackers_with_crosses_lte(aura_inst.effect_name)
            if threshold is None:
                continue
            if attacker_crosses <= int(threshold):
                return ActionResult(False, f"{aura_inst.definition.name} impedisce questo attacco.")

    # Check the generic can_attack conditions from the runtime card scripts, which may include various custom rules and restrictions for whether the card can attack in the current context. This allows for a flexible system of attack requirements that can be defined on a per-card basis in the runtime scripts.
    if not runtime_cards.get_can_attack(attacker.effect_name):
        return ActionResult(False, f"{attacker.definition.name} non puo attaccare.")
    can_attack_now, blocked_msg = runtime_cards.can_attack_now(engine, player_idx, attacker_uid)
    if not can_attack_now:
        return ActionResult(False, blocked_msg or f"{attacker.definition.name} non puo attaccare.")
    if engine._is_attacker_blocked_this_turn(attacker):
        return ActionResult(False, f"{attacker.definition.name} non puo attaccare in questo turno.")
    can_multi_targets = runtime_cards.get_can_attack_multiple_targets_in_attack_per_turn(attacker.effect_name)
    has_extra_attack = _has_extra_attack_for_turn(attacker, engine.state.turn_number)
    if attacker.exhausted:
        if not can_multi_targets and not has_extra_attack:
            return ActionResult(False, "Questo Santo ha gia attaccato nel turno corrente.")
        if has_extra_attack:
            return None
        if target_slot is None or not (0 <= target_slot < ATTACK_SLOTS):
            return ActionResult(
                False,
                f"{attacker.definition.name} puo effettuare attacchi extra solo contro Santi avversari in attacco.",
            )
        defender_uid = engine.state.players[defender_idx].attack[target_slot]
        if defender_uid is None:
            return ActionResult(
                False,
                f"{attacker.definition.name} puo effettuare attacchi extra solo contro Santi avversari in attacco.",
            )
        attacked_targets = engine.state.flags.setdefault("attacked_targets_this_turn", {})
        already_attacked = attacked_targets.get(attacker.uid, [])
        if defender_uid in already_attacked:
            return ActionResult(False, f"{attacker.definition.name} ha gia attaccato questo bersaglio nel turno corrente.")
    return None


# Marks the attacker as committed and updates the per-turn attack counter.
def mark_attack_committed(
    engine: "GameEngine",
    player_idx: int,
    attacker: CardInstance,
    defender_uid: str | None = None,
) -> None:
    if attacker.exhausted:
        _consume_extra_attack_for_turn(attacker, engine.state.turn_number)
    attacker.exhausted = True
    if defender_uid:
        attacked_targets = engine.state.flags.setdefault("attacked_targets_this_turn", {})
        by_attacker = list(attacked_targets.get(attacker.uid, []))
        if defender_uid not in by_attacker:
            by_attacker.append(defender_uid)
        attacked_targets[attacker.uid] = by_attacker
    attack_count = engine.state.flags.setdefault("attack_count", {"0": 0, "1": 0})
    attack_count[str(player_idx)] = int(attack_count.get(str(player_idx), 0)) + 1


# Applies post-combat retaliation coming from the defender's building script.
def apply_fiamma_primordiale_after_attack(
    engine: "GameEngine",
    attacker_idx: int,
    defender_idx: int,
    attacker_uid: str,
) -> None:
    defender_player = engine.state.players[defender_idx]
    building_uid = defender_player.building
    if not building_uid or building_uid not in engine.state.instances:
        return
    building_inst = engine.state.instances[building_uid]
    burn = runtime_cards.get_retaliation_damage_to_enemy_attacker(building_inst.effect_name)
    if burn <= 0:
        return

    # Check for retaliation multipliers from friendly artifacts, which can increase the burn damage if the defender has certain artifacts equipped that are linked to the building. This allows for synergies between buildings and artifacts that can enhance retaliation effects after combat.
    multiplier_count = 0
    for a_uid in defender_player.artifacts:
        if not a_uid:
            continue
        a_inst = engine.state.instances.get(a_uid)
        if a_inst is None:
            continue
        linked_building = runtime_cards.get_retaliation_multiplier_for_friendly_building_name(
            a_inst.effect_name
        )
        if linked_building and _norm(linked_building) == _norm(building_inst.definition.name):
            multiplier_count += 1
    if multiplier_count > 0:
        burn = burn * (2 ** multiplier_count)

    # Check if the attacker is still on the board and is a valid target for retaliation damage, which can prevent the retaliation from applying if the attacker has been removed from the field or is no longer a valid target due to changes in the game state after combat. This ensures that retaliation effects are only applied to valid targets that are still present after combat.
    if attacker_uid not in engine.state.instances:
        return
    attacker_player = engine.state.players[attacker_idx]
    if attacker_uid not in (attacker_player.attack + attacker_player.defense):
        return
    attacker = engine.state.instances[attacker_uid]
    burn = engine._apply_damage_mitigation(attacker_idx, burn, target_uid=attacker_uid)
    if burn <= 0 or (attacker.current_faith or 0) <= 0:
        return
    before = attacker.current_faith or 0
    attacker.current_faith = max(0, (attacker.current_faith or 0) - burn)
    after = attacker.current_faith or 0
    engine.state.log(
        f"{attacker.definition.name} subisce {burn} danni da {building_inst.definition.name} (post-combattimento) (Fede {before}->{after})."
    )
    if (attacker.current_faith or 0) <= 0:
        engine.destroy_saint_by_uid(engine.state.instances[attacker_uid].owner, attacker_uid, cause="effect")
        remove_sin = runtime_cards.get_retaliation_reduce_sin_on_kill(building_inst.effect_name)
        if remove_sin > 0:
            engine.reduce_sin(defender_idx, int(remove_sin))


# Resolves the direct-attack case when the defender has no saints on the board.
def resolve_direct_attack(
    engine: "GameEngine",
    player_idx: int,
    defender_idx: int,
    attacker_uid: str,
    attacker: CardInstance,
) -> ActionResult:
    attacker_player = engine.state.players[player_idx]
    defender_player = engine.state.players[defender_idx]

    # Check if the attacker can attack based on its current state and any active effects.
    mark_attack_committed(engine, player_idx, attacker, defender_uid=None)
    if engine._consume_attack_shield(defender_idx):
        engine.state.log(f"{defender_player.name} annulla il primo attacco ricevuto in questo turno.")
        return ActionResult(True, "Attacco annullato da effetto di scudo.")
    base_strength = max(0, attacker.definition.strength or 0)
    damage = engine.get_effective_strength(attacker_uid)
    sin_gain = _apply_sin_reduction_auras(engine, defender_idx, damage)
    engine.gain_sin(defender_idx, sin_gain)
    engine._emit_event(
        "on_this_card_deals_damage",
        player_idx,
        card=attacker_uid,
        target_player=defender_idx,
        amount=damage,
    )
    engine.state.log(
        f"{attacker_player.name} attacca con {attacker.definition.name} direttamente {defender_player.name} "
        f"(Forza base {base_strength}, effettiva {damage}) (+{sin_gain} Peccato)."
    )
    apply_fiamma_primordiale_after_attack(engine, player_idx, defender_idx, attacker_uid)
    engine.check_win_conditions()
    return ActionResult(True, f"Attacco diretto riuscito: +{sin_gain} Peccato all'avversario.")


# Resolves a targeted combat, including barriers, lethal damage, and retaliation rules.
def resolve_targeted_attack(
    engine: "GameEngine",
    player_idx: int,
    defender_idx: int,
    attacker_uid: str,
    attacker: CardInstance,
    target_slot: int | None,
) -> ActionResult:
    attacker_player = engine.state.players[player_idx]
    defender_player = engine.state.players[defender_idx]

    # Validate the target slot and check for any forced attack targets that must be attacked if present, ensuring that the player selects a valid target for the attack and adheres to any restrictions on which targets can be attacked based on the defender's current board state and active effects.
    if target_slot is None or not (0 <= target_slot < ATTACK_SLOTS):
        return ActionResult(False, "Indica bersaglio valido t1..t3.")
    forced_slots = [
        i
        for i, s_uid in enumerate(defender_player.attack)
        if s_uid
        and runtime_cards.get_attack_targeting_mode(engine.state.instances[s_uid].effect_name)
        == "must_be_attack_target"
    ]
    if forced_slots and target_slot not in forced_slots:
        forced_names = ", ".join(
            engine.state.instances[s_uid].definition.name
            for i in forced_slots
            for s_uid in [defender_player.attack[i]]
            if s_uid is not None and s_uid in engine.state.instances
        )
        label = forced_names or "un bersaglio obbligatorio"
        return ActionResult(False, f"Devi attaccare {label}.")
    defender_uid = defender_player.attack[target_slot]
    if defender_uid is None:
        return ActionResult(False, "Nessun Santo avversario nel bersaglio scelto.")
    defender_name = engine.state.instances[defender_uid].definition.name
    if runtime_cards.get_attack_targeting_mode(engine.state.instances[defender_uid].effect_name) == "untargetable":
        return ActionResult(False, f"{defender_name} non puo essere bersagliato dagli attacchi.")
    if runtime_cards.get_attack_targeting_mode(engine.state.instances[defender_uid].effect_name) == "only_if_no_other_attackers":
        others = [u for i, u in enumerate(defender_player.attack) if i != target_slot and u is not None]
        if others:
            return ActionResult(False, f"{defender_name} puo essere bersagliato solo se non ci sono altri santi in attacco.")

    # Check if the attacker can attack based on its current state and any active effects.
    mark_attack_committed(engine, player_idx, attacker, defender_uid=defender_uid)
    if engine._consume_attack_shield(defender_idx):
        engine.state.log(f"{defender_player.name} annulla il primo attacco ricevuto in questo turno.")
        return ActionResult(True, "Attacco annullato da effetto di scudo.")
    defender = engine.state.instances[defender_uid]
    barrier = engine._consume_barrier(defender)
    if barrier:
        engine.state.log(f"{defender.definition.name} blocca l'attacco grazie a {barrier}.")
        apply_fiamma_primordiale_after_attack(engine, player_idx, defender_idx, attacker_uid)
        return ActionResult(True, "Attacco annullato da barriera.")

    # Calculate the damage, applying any relevant mitigation from defender auras or other effects, and then apply the damage to the defender's current faith. This includes checking for any special damage mitigation rules based on the attacker's type and the defender's auras, as well as applying any generic damage mitigation from the engine before finalizing the damage dealt.
    base_strength = max(0, attacker.definition.strength or 0)
    damage = engine.get_effective_strength(attacker_uid)
    attacker_type_key = _norm(attacker.definition.card_type)
    defender_damage_divisor = 1
    if attacker_type_key in {"santo", "token"}:
        for uid in defender_player.attack + defender_player.defense:
            if not uid:
                continue
            aura_divisor = runtime_cards.get_incoming_damage_from_enemy_saints_divisor(
                engine.state.instances[uid].effect_name
            )
            if aura_divisor > defender_damage_divisor:
                defender_damage_divisor = aura_divisor
    if defender_damage_divisor > 1:
        before_damage = damage
        damage = max(0, damage // defender_damage_divisor)
        engine.state.log(
            f"Mitigazione runtime del danno da Santi: {before_damage}->{damage} (divisore {defender_damage_divisor})."
        )
    if attacker_type_key in {"santo", "token"}:
        reduction = runtime_cards.get_context_bonus_amount(
            engine,
            defender_idx,
            context="incoming_damage_reduction_from_enemy_saints",
            amount_mode="per_count_div_floor",
            target_uid=defender_uid,
        )
        if reduction > 0:
            before_damage = damage
            damage = max(0, int(damage) - int(reduction))
            engine.state.log(
                f"Riduzione danni runtime contro Santi nemici: {before_damage}->{damage} (-{int(reduction)})."
            )
    damage = engine._apply_damage_mitigation(defender_idx, damage, target_uid=defender_uid)
    def_faith = defender.current_faith or 0
    if damage <= 0:
        engine.state.log(
            f"{attacker_player.name} attacca con {attacker.definition.name} contro {defender.definition.name}, ma non infligge danni."
        )
        return ActionResult(True, "Nessun danno inflitto.")

    # Apply the damage to the defender's current faith, ensuring that it does not go below zero, and emit the appropriate events for dealing and receiving damage. This updates the defender's current faith based on the damage dealt, and also logs the attack and its effects in the game state for transparency and record-keeping.
    before_def = def_faith
    defender.current_faith = max(0, def_faith - damage)
    engine._emit_event(
        "on_this_card_deals_damage",
        player_idx,
        card=attacker_uid,
        target=defender_uid,
        amount=damage,
    )
    engine._emit_event(
        "on_this_card_receives_damage",
        defender_idx,
        card=defender_uid,
        source=attacker_uid,
        amount=damage,
    )
    after_def = defender.current_faith or 0
    engine.state.log(
        f"{attacker_player.name} attacca con {attacker.definition.name} contro {defender.definition.name} "
        f"(Forza base {base_strength}, effettiva {damage}) e infligge {damage} danni (Fede {before_def}->{after_def})."
    )
    lethal = (defender.current_faith or 0) <= 0
    if lethal:
        excommunicate = runtime_cards.get_battle_excommunicate_on_lethal(attacker.effect_name)
        engine.destroy_saint_by_uid(
            engine.state.instances[defender_uid].owner,
            defender_uid,
            excommunicate=excommunicate,
            cause="battle",
            by_whom=attacker_uid,
        )
        engine._emit_event("on_this_card_kills_in_battle", player_idx, card=attacker_uid, victim=defender_uid)
        gain = runtime_cards.get_strength_gain_on_lethal_to_enemy_saint(attacker.effect_name)
        if gain:
            attacker.definition.strength = (attacker.definition.strength or 0) + int(gain)
    else:
        gain = runtime_cards.get_strength_gain_on_damage_to_enemy_saint(attacker.effect_name)
        if gain:
            attacker.definition.strength = (attacker.definition.strength or 0) + int(gain)

    apply_fiamma_primordiale_after_attack(engine, player_idx, defender_idx, attacker_uid)

    # Resolve post-battle forced destruction strictly at the end of combat
    # so other attack-related effects complete first.
    forced_destroy: list[tuple[int, str]] = []
    attacker_on_board = attacker_uid in (attacker_player.attack + attacker_player.defense)
    defender_on_board = defender_uid in (defender_player.attack + defender_player.defense)
    if runtime_cards.get_post_battle_forced_destroy(attacker.effect_name) and defender_on_board:
        forced_destroy.append((defender_idx, defender_uid))
    if runtime_cards.get_post_battle_forced_destroy(defender.effect_name) and attacker_on_board:
        forced_destroy.append((player_idx, attacker_uid))
    for owner_idx, forced_uid in forced_destroy:
        if forced_uid not in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense):
            continue
        faith_val = max(0, engine.state.instances[forced_uid].definition.faith or 0)
        engine.destroy_saint_by_uid(engine.state.instances[forced_uid].owner, forced_uid, cause="effect")
        engine.gain_sin(0, faith_val)
        engine.gain_sin(1, faith_val)

    engine.check_win_conditions()
    return ActionResult(True, f"Danno inflitto: {damage}.")


# Declares an attack, routes it to the correct combat branch, and preserves all battle checks.
def attack(engine: "GameEngine", player_idx: int, from_slot: int, target_slot: int | None) -> ActionResult:
    if engine.state.phase == "preparation":
        return ActionResult(False, "Durante il turno di preparazione non si puo attaccare.")
    if int(engine.state.flags.get("no_attacks_turn", -1)) == int(engine.state.turn_number):
        return ActionResult(False, "In questo turno gli attacchi sono bloccati da un effetto.")
    if _has_active_no_attack_until_draw(engine):
        return ActionResult(False, "Gli attacchi sono bloccati finche un giocatore non pesca una carta.")
    if player_idx != engine.state.active_player:
        return ActionResult(False, "Puoi attaccare solo nel tuo turno.")

    # Check if the battle phase is needed and start it if required.
    start_battle_phase_if_needed(engine, player_idx)
    attacker_player = engine.state.players[player_idx]
    defender_idx = 1 - player_idx
    defender_player = engine.state.players[defender_idx]
    requested_defense = from_slot < 0
    slot_idx = (-from_slot - 1) if requested_defense else from_slot
    if not (0 <= slot_idx < ATTACK_SLOTS):
        return ActionResult(False, "Slot attacco non valido.")

    # Determine the attacker based on the requested slot, checking both attack and defense slots as needed, and validate that there is a valid attacker in the chosen slot. This allows for attacks to be declared from either the attack or defense rows, depending on the player's choice and the current board state, while ensuring that a valid attacker is selected for the combat.
    attacker_uid = None
    if requested_defense:
        defense_uid = attacker_player.defense[slot_idx]
        if defense_uid is None:
            return ActionResult(False, "Nessun Santo in quello slot.")
        defense_inst = engine.state.instances[defense_uid]
        if not runtime_cards.get_can_attack_from_defense(defense_inst.effect_name):
            return ActionResult(False, "Nessun Santo in quello slot.")
        attacker_uid = defense_uid
    else:
        attacker_uid = attacker_player.attack[slot_idx]
        if attacker_uid is None:
            defense_uid = attacker_player.defense[slot_idx]
            if defense_uid is None:
                return ActionResult(False, "Nessun Santo in quello slot.")
            defense_inst = engine.state.instances[defense_uid]
            if not runtime_cards.get_can_attack_from_defense(defense_inst.effect_name):
                return ActionResult(False, "Nessun Santo in quello slot.")
            attacker_uid = defense_uid

    # Validate that the attacker exists in the game state and is a valid card instance, ensuring that the selected attacker is still present on the board and has a valid instance in the game state before proceeding with the attack. This prevents issues with invalid or missing attackers during combat resolution.
    attacker = engine.state.instances[attacker_uid]
    engine._emit_event(
        "on_attack_declared",
        player_idx,
        attacker=attacker_uid,
        card=attacker_uid,
        target_slot=target_slot,
    )
    engine._emit_event("on_this_card_attacks", player_idx, card=attacker_uid, target_slot=target_slot)

    # Perform all pre-attack validations that can block the attack before damage calculation, including checking for any special targeting rules, attack restrictions, or other conditions that can prevent the attack from being declared based on the current game state and the specific cards involved in the combat.
    validation_error = validate_attack_preconditions(engine, player_idx, defender_idx, attacker_uid, attacker, target_slot)
    if validation_error is not None:
        return validation_error

    # Route to the correct combat resolution branch based on whether the defender has any saints on the board, ensuring that direct attacks are resolved differently from targeted attacks with a defender, while still applying all relevant checks and effects for both cases.
    if all(slot is None for slot in defender_player.attack + defender_player.defense):
        return resolve_direct_attack(engine, player_idx, defender_idx, attacker_uid, attacker)
    return resolve_targeted_attack(engine, player_idx, defender_idx, attacker_uid, attacker, target_slot)
