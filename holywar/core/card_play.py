from __future__ import annotations

import unicodedata
from typing import Any

from holywar.core.results import ActionResult
from holywar.core.state import ARTIFACT_SLOTS
from holywar.core import query_helpers as query_ops
from holywar.effects.library import resolve_card_effect, resolve_enter_effect
from holywar.effects.runtime import runtime_cards

from holywar.core.state import CardInstance

GameEngine = Any


SAINT_TYPES = {"santo", "token"}
QUICK_TYPES = {"benedizione", "maledizione"}

# Normalizes text for comparison by removing accents, converting to lowercase, and stripping whitespace. This is used for flexible matching of card names and types, allowing for variations in input while still correctly identifying the intended card or type.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()

# A more ASCII-focused normalization that also removes accents and converts to lowercase, but is specifically designed for card type comparisons where non-ASCII characters might be present. This can help ensure consistent matching of card types regardless of the presence of accents or other diacritics.
def _aliases_of(inst: "CardInstance") -> list[str]:
    raw_aliases = getattr(inst.definition, "aliases", []) or []
    if isinstance(raw_aliases, str):
        return [part.strip() for part in raw_aliases.split(",") if part.strip()]
    return [str(alias).strip() for alias in raw_aliases if str(alias).strip()]

# Generates a set of normalized name variants for a card instance, including the main name and any aliases. This is used for flexible matching of card names in various contexts, allowing for recognition of the card even if different naming conventions or aliases are used.
def _name_variants(inst: "CardInstance") -> set[str]:
    variants = {_norm(inst.definition.name)}
    variants.update(_norm(alias) for alias in _aliases_of(inst))
    return {v for v in variants if v}

# Creates a single normalized string containing the card's name and aliases, which can be used for "contains" style matching. This allows for checking if a certain substring is present in any of the card's names or aliases, providing a more flexible way to identify cards based on partial name matches.
def _name_haystack(inst: "CardInstance") -> str:
    parts = [inst.definition.name, *_aliases_of(inst)]
    return " ".join(_norm(part) for part in parts if str(part).strip())


def _consume_named_play_limit(
    engine: "GameEngine",
    player_idx: int,
    inst: "CardInstance",
) -> ActionResult | None:
    script = runtime_cards.get_script(inst.effect_name)
    if script is None or not script.play_requirements.get("play_once_per_turn_by_name", False):
        return None
    usage_key = str(script.play_requirements.get("play_usage_state_key", "named_effect_used_turn"))
    used = engine.state.flags.setdefault(usage_key, {})
    key = f"{player_idx}:{_norm(inst.definition.name)}"
    if int(used.get(key, -1)) == int(engine.state.turn_number):
        return ActionResult(False, f"{inst.definition.name}: effetto non puo essere attivato piu di una volta per turno.")
    used[key] = int(engine.state.turn_number)
    return None


def _all_field_uids_for_player(engine: "GameEngine", player_idx: int) -> list[str]:
    player = engine.state.players[player_idx]
    out = [uid for uid in (player.attack + player.defense + player.artifacts) if uid]
    if player.building:
        out.append(player.building)
    return out


def _has_invert_saint_summon_aura(engine: "GameEngine") -> bool:
    for p_idx in (0, 1):
        player = engine.state.players[p_idx]
        field_uids = [uid for uid in (player.attack + player.defense + player.artifacts) if uid]
        if player.building:
            field_uids.append(player.building)
        for uid in field_uids:
            inst = engine.state.instances.get(uid)
            if inst is None:
                continue
            script = runtime_cards.get_script(inst.effect_name)
            if script and bool(script.inverts_saint_summon_controller):
                return True
    return False

# Checks if the player has any unplayed Innate cards in hand, which can affect the ability to play other cards during the preparation phase. This is used to enforce the rule that if a player has an unplayed Innate card in hand during the preparation phase, they cannot play other cards until they either play or remove the Innate card.
def _has_unplayed_innate_in_hand(engine: "GameEngine", player_idx: int) -> bool:
    player = engine.state.players[player_idx]
    active_innate = set(engine.state.flags.setdefault("innate_active_uids", {"0": [], "1": []}).get(str(player_idx), []) or [])
    for uid in player.hand:
        inst = engine.state.instances.get(uid)
        if inst is None:
            continue
        if _norm(inst.definition.card_type) == "innata" and uid not in active_innate:
            return True
    return False

# Removes any unplayed Innate cards from the player's hand and logs the reason. This is used when a player attempts to play a non-Innate card during the preparation phase while having an unplayed Innate card in hand, enforcing the rule that they must first deal with the Innate card before playing other cards.
def _remove_unplayed_innate_from_hand(engine: "GameEngine", player_idx: int) -> None:
    player = engine.state.players[player_idx]
    active_innate = set(engine.state.flags.setdefault("innate_active_uids", {"0": [], "1": []}).get(str(player_idx), []) or [])
    removed = engine.state.flags.setdefault("innate_removed_uids", {"0": [], "1": []}).setdefault(str(player_idx), [])
    kept_hand: list[str] = []
    for uid in player.hand:
        inst = engine.state.instances.get(uid)
        if inst is None or _norm(inst.definition.card_type) != "innata" or uid in active_innate:
            kept_hand.append(uid)
            continue
        if uid not in removed:
            removed.append(uid)
        engine.state.log(f"{player.name}: {inst.definition.name} (Innata) eliminata perche e stata giocata prima un'altra carta.")
    player.hand = kept_hand


# Validates whether the card can be played in the requested zone and context.
def validate_play_constraints(
    engine: "GameEngine",
    player_idx: int,
    card: "CardInstance",
    target: str | None,
) -> tuple[bool, str, int, str | None, int]:
    player = engine.state.players[player_idx]
    ctype = _norm(card.definition.card_type)
    place_owner_idx = player_idx
    zone: str | None = None
    slot = -1

    # Validate placement rules based on card type and target directives, ensuring that the card can be played in the intended location and context. This includes checking for valid zones for Saints/Tokens, ensuring that only one Building is present, and handling any specific placement rules for Artifacts.
    if ctype in SAINT_TYPES:
        if _norm(runtime_cards.get_play_owner(card.effect_name)) in {"opponent", "enemy", "other"}:
            place_owner_idx = 1 - player_idx
        if ctype == "santo" and _has_invert_saint_summon_aura(engine):
            place_owner_idx = 1 - place_owner_idx
        zone, slot = engine._parse_zone_target(target)
        if zone not in {"attack", "defense"}:
            return False, "Per un Santo/Token indica zona: a1..a3 o d1..d3", place_owner_idx, zone, slot
        current = getattr(engine.state.players[place_owner_idx], zone)[slot]
        if current is not None:
            return False, "Slot occupato.", place_owner_idx, zone, slot
    elif ctype == "artefatto":
        pass
    elif ctype == "edificio":
        if player.building:
            return False, "Hai gia un Edificio. Va distrutto prima di giocarne un altro.", place_owner_idx, zone, slot

    return True, "", place_owner_idx, zone, slot

# Finds a card on the player's field by name, which is used for legacy scripted play requirements that specify sacrificing a card by name. This allows for matching the required sacrifice card even if the player has multiple cards on the field, as long as one of them matches the specified name.
def _find_owned_field_uid_by_name(engine: "GameEngine", owner_idx: int, card_name: str) -> str | None:
    wanted = _norm(card_name)
    player = engine.state.players[owner_idx]
    for uid in player.attack + player.defense + player.artifacts:
        if uid and wanted in _name_variants(engine.state.instances[uid]):
            return uid
    if player.building and wanted in _name_variants(engine.state.instances[player.building]):
        return player.building
    return None

# Retrieves the list of card UIDs in the specified zone(s) for the given owner, which is used for collecting candidate cards that can be sacrificed or otherwise interacted with based on play requirements. This function abstracts away the details of how cards are stored in different zones and provides a unified way to access them based on the owner's perspective and the specified zone.
def _zone_uids_for_owner(engine: "GameEngine", owner_idx: int, zone_name: str) -> list[str]:
    player = engine.state.players[owner_idx]
    zone = _norm(zone_name)
    if zone == "field":
        out = [uid for uid in player.attack + player.defense + player.artifacts if uid]
        if player.building:
            out.append(player.building)
        return out
    if zone == "attack":
        return [uid for uid in player.attack if uid]
    if zone == "defense":
        return [uid for uid in player.defense if uid]
    if zone in {"artifact", "artifacts"}:
        return [uid for uid in player.artifacts if uid]
    if zone == "building":
        return [player.building] if player.building else []
    if zone == "hand":
        return list(player.hand)
    if zone in {"deck", "relicario"}:
        return list(player.deck)
    if zone == "graveyard":
        return list(player.graveyard)
    if zone == "excommunicated":
        return list(player.excommunicated)
    return []

# Checks if a card instance matches the specified filter criteria, which is used for validating whether candidate cards meet the requirements for sacrifices or other interactions based on play requirements. This includes checking for name equality, name containment, and card type matching according to the provided filter configuration.
def _match_requirement_filter(engine: "GameEngine", uid: str, card_filter: dict) -> bool:
    inst = engine.state.instances.get(uid)
    if inst is None:
        return False
    name_eq = _norm(str(card_filter.get("name_equals", "")))
    name_variants = _name_variants(inst)
    name_haystack = _name_haystack(inst)
    if name_eq and name_eq not in name_variants:
        return False
    name_contains = _norm(str(card_filter.get("name_contains", "")))
    if name_contains and name_contains not in name_haystack:
        return False
    name_not_contains = _norm(str(card_filter.get("name_not_contains", "")))
    if name_not_contains and name_not_contains in name_haystack:
        return False
    type_filter = {_norm(str(v)) for v in list(card_filter.get("card_type_in", []) or [])}
    if type_filter and _norm(inst.definition.card_type) not in type_filter:
        return False
    return True

# Collects card UIDs that meet the specified requirement criteria, which is used for gathering potential sacrifice candidates or other relevant cards based on play requirements. This function combines the logic of determining the relevant owners and zones with the filtering of cards based on the provided criteria to return a list of matching card UIDs.
def _collect_requirement_cards(engine: "GameEngine", owner_idx: int, requirement: dict) -> list[str]:
    owner_key = _norm(str(requirement.get("owner", "me")))
    if owner_key in {"opponent", "enemy", "other"}:
        owners = [1 - owner_idx]
    elif owner_key in {"any", "both", "all", "either"}:
        owners = [owner_idx, 1 - owner_idx]
    else:
        owners = [owner_idx]

    zones = list(requirement.get("zones", []) or [])
    if not zones:
        zones = [str(requirement.get("zone", "field"))]
    card_filter = dict(requirement.get("card_filter", {}) or {})

    out: list[str] = []
    for real_owner in owners:
        for zone_name in zones:
            for uid in _zone_uids_for_owner(engine, real_owner, str(zone_name)):
                if _match_requirement_filter(engine, uid, card_filter):
                    out.append(uid)
    return list(dict.fromkeys(out))


def _free_play_condition_met(engine: "GameEngine", owner_idx: int, condition: dict | None) -> bool:
    if not isinstance(condition, dict) or not condition:
        return False
    all_of = condition.get("all_of")
    if isinstance(all_of, list):
        return all(_free_play_condition_met(engine, owner_idx, dict(sub or {})) for sub in all_of if isinstance(sub, dict))
    any_of = condition.get("any_of")
    if isinstance(any_of, list) and any_of:
        return any(_free_play_condition_met(engine, owner_idx, dict(sub or {})) for sub in any_of if isinstance(sub, dict))
    not_node = condition.get("not")
    if isinstance(not_node, dict):
        return not _free_play_condition_met(engine, owner_idx, not_node)
    controller_has_cards = condition.get("controller_has_cards")
    if isinstance(controller_has_cards, dict):
        min_count = max(0, int(controller_has_cards.get("min_count", 1) or 1))
        return len(_collect_requirement_cards(engine, owner_idx, controller_has_cards)) >= min_count
    return False

# Parses the play target string to extract the main placement target and any additional directives, which is used for handling complex play requirements that may involve specific targeting or selection of cards. This allows for a flexible way to encode both the intended placement of the card being played and any additional instructions for how to handle sacrifices or other interactions.
def _split_play_target_with_directives(target: str | None) -> tuple[str | None, dict[str, str]]:
    raw = str(target or "").strip()
    if not raw:
        return None, {}
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        return None, {}
    placement = parts[0]
    directives: dict[str, str] = {}
    for part in parts[1:]:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = _norm(key)
        if not key:
            continue
        directives[key] = value.strip()
    return placement, directives

# Consumes the costs associated with scripted play requirements, such as sacrifices, and returns any relevant information such as total sacrificed faith. This function handles the logic for processing the "can_play_by_sacrificing" requirement, including selecting the appropriate cards to sacrifice based on the requirement configuration and applying any necessary effects or flags to those cards.
def _consume_scripted_play_costs(
    engine: "GameEngine",
    player_idx: int,
    card: "CardInstance",
    play_target: str | None = None,
) -> tuple[ActionResult | None, int]:
    script = runtime_cards.get_script(card.effect_name)
    if script is None:
        return None, 0
    sacrificed_total_faith = 0
    mark_sacrifices_no_sin = bool(script.play_requirements.get("play_sacrifices_no_sin_on_death", False))
    sacrifice_to_zone = _norm(str(script.play_requirements.get("play_sacrifices_to_zone", "graveyard")))
    requirement_cfg = script.play_requirements.get("can_play_by_sacrificing")
    if isinstance(requirement_cfg, dict):
        count = max(1, int(requirement_cfg.get("count", 1) or 1))
        candidates = _collect_requirement_cards(engine, player_idx, requirement_cfg)
        if len(candidates) < count:
            return ActionResult(False, f"Per giocare {card.definition.name} non ci sono abbastanza carte da sacrificare."), 0
        selected_uids: list[str] = []
        if bool(script.play_requirements.get("choose_play_sacrifices_from_target", False)):
            _, directives = _split_play_target_with_directives(play_target)
            raw_selected = str(directives.get("sac", "")).strip()
            requested = [v.strip() for v in raw_selected.split(",") if v.strip()]
            allowed = set(candidates)
            selected_uids = [uid for uid in requested if uid in allowed]
            if len(selected_uids) < count:
                return (
                    ActionResult(False, f"Per giocare {card.definition.name} devi selezionare {count} carta/e da sacrificare."),
                    0,
                )
            selected_uids = selected_uids[:count]
        else:
            selected_uids = candidates[:count]
        for uid in selected_uids:
            sacr_inst = engine.state.instances[uid]
            owner = sacr_inst.owner
            sacrificed_total_faith += max(0, int(sacr_inst.definition.faith or 0))
            if mark_sacrifices_no_sin and "no_sin_on_death" not in sacr_inst.blessed:
                sacr_inst.blessed.append("no_sin_on_death")
            if sacrifice_to_zone == "excommunicated":
                from_zone = engine._locate_uid_zone(owner, uid)
                if from_zone in {"attack", "defense", "artifact", "building"}:
                    from_zone_override = from_zone if from_zone != "unknown" else None
                    engine.excommunicate_card(owner, uid, from_zone_override=from_zone_override)
                else:
                    owner_player = engine.state.players[owner]
                    if uid in owner_player.hand:
                        owner_player.hand.remove(uid)
                    if uid in owner_player.deck:
                        owner_player.deck.remove(uid)
                    if uid in owner_player.graveyard:
                        owner_player.graveyard.remove(uid)
                    if uid in owner_player.white_deck:
                        owner_player.white_deck.remove(uid)
                    if uid not in owner_player.excommunicated:
                        owner_player.excommunicated.append(uid)
            else:
                engine.send_to_graveyard(owner, uid)
        return None, sacrificed_total_faith

    # Legacy single-card sacrifice by name requirement for backward compatibility with older scripts. This checks for the "can_play_by_sacrificing_specific_card_from_field" requirement and processes it by finding a card with the specified name on the player's field and sacrificing it. This allows older card scripts that use this specific requirement to still function without needing to be updated to the new format.
    legacy_requirement = str(script.play_requirements.get("can_play_by_sacrificing_specific_card_from_field", "")).strip()
    if legacy_requirement:
        sacrifice_uid = _find_owned_field_uid_by_name(engine, player_idx, legacy_requirement)
        if not sacrifice_uid:
            return ActionResult(False, f"Per giocare {card.definition.name} devi sacrificare {legacy_requirement} dal tuo campo."), 0
        sacr_inst = engine.state.instances[sacrifice_uid]
        sacrificed_total_faith += max(0, int(sacr_inst.definition.faith or 0))
        if mark_sacrifices_no_sin and "no_sin_on_death" not in sacr_inst.blessed:
            sacr_inst.blessed.append("no_sin_on_death")
        engine.send_to_graveyard(player_idx, sacrifice_uid)
    return None, sacrificed_total_faith


# Computes the final Inspiration cost after all card-specific modifiers.
def calculate_play_cost(engine: "GameEngine", player_idx: int, hand_index: int, card: "CardInstance") -> int:
    player = engine.state.players[player_idx]
    ctype = _norm(card.definition.card_type)
    free_play_flags = engine.state.flags.setdefault("free_play_uids", {"0": [], "1": []})
    free_uids = set(free_play_flags.get(str(player_idx), []) or [])
    if hand_index >= 0 and hand_index < len(player.hand):
        if player.hand[hand_index] in free_uids:
            return 0
    script = runtime_cards.get_script(card.effect_name)
    if script is not None:
        free_if = script.play_requirements.get("can_play_without_inspiration_cost_if")
        if _free_play_condition_met(engine, player_idx, free_if):
            return 0
    cost = card.definition.faith or 0

    if ctype in SAINT_TYPES:
        fixed = runtime_cards.get_play_cost_fixed(card.effect_name)
        if fixed is not None:
            cost = max(0, int(fixed))
        required_saint = runtime_cards.get_play_cost_zero_if_controller_has_saint_with_name(card.effect_name)
        if required_saint:
            wanted = _norm(required_saint)
            has_required = any(
                wanted in _name_variants(engine.state.instances[f_uid])
                for f_uid in _all_field_uids_for_player(engine, player_idx)
            )
            if has_required:
                cost = 0
        if runtime_cards.get_play_cost_zero_if_controller_has_no_saints(card.effect_name):
            if not engine.all_saints_on_field(player_idx):
                cost = 0
        reduction_types = {
            _norm(v)
            for v in runtime_cards.get_play_cost_reduction_if_controller_has_card_type_in_hand(card.effect_name)
            if str(v).strip()
        }
        if reduction_types:
            has_type_in_hand = any(
                _norm(engine.state.instances[h_uid].definition.card_type) in reduction_types
                for i, h_uid in enumerate(player.hand)
                if i != hand_index
            )
            if has_type_in_hand:
                cost = max(0, cost - 1)
        for s_uid in engine.all_saints_on_field(player_idx):
            aura_name = engine.state.instances[s_uid].definition.name
            if not runtime_cards.get_halves_friendly_saint_play_cost(aura_name):
                continue
            if (
                runtime_cards.get_halve_friendly_saint_play_cost_excludes_self(aura_name)
                and _norm(aura_name) == _norm(card.definition.name)
            ):
                continue
            cost = max(0, (cost + 1) // 2)
            break

    double_turns = engine.state.flags.setdefault("double_cost_turns", {"0": 0, "1": 0})
    if int(double_turns.get(str(player_idx), 0)) > 0:
        cost *= 2
    opponent = engine.state.players[1 - player_idx]
    enemy_field_uids = [uid for uid in opponent.attack + opponent.defense + opponent.artifacts if uid]
    if opponent.building:
        enemy_field_uids.append(opponent.building)
    for enemy_uid in enemy_field_uids:
        enemy_name = engine.state.instances[enemy_uid].definition.name
        if runtime_cards.get_doubles_enemy_play_cost(enemy_name):
            cost *= 2
    return cost


# Applies the computed cost using temporary Inspiration before the regular pool.
def spend_inspiration_for_cost(engine: "GameEngine", player_idx: int, cost: int) -> ActionResult | None:
    player = engine.state.players[player_idx]
    available_inspiration = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
    if available_inspiration < cost:
        return ActionResult(False, "Ispirazione insufficiente.")

    temp = int(getattr(player, "temporary_inspiration", 0))
    use_temp = min(temp, cost)
    player.temporary_inspiration = temp - use_temp
    remaining_cost = cost - use_temp
    player.inspiration -= remaining_cost

    spent = engine.state.flags.setdefault("spent_inspiration_turn", {"0": 0, "1": 0})
    spent[str(player_idx)] = int(spent.get(str(player_idx), 0)) + cost
    return None


# Emits the shared play events used by all cards when leaving the hand.
def emit_play_events(engine: "GameEngine", player_idx: int, uid: str, ctype: str, target: str | None) -> None:
    engine._emit_event("on_card_played", player_idx, card=uid, card_type=ctype, target=target)
    if ctype == "benedizione":
        engine._emit_event("on_blessing_played", player_idx, card=uid, target=target)
    elif ctype == "maledizione":
        engine._emit_event("on_curse_played", player_idx, card=uid, target=target)


# Handles saint placement, summon side effects, and enter-the-field bonuses.
def handle_saint_play(
    engine: "GameEngine",
    player_idx: int,
    place_owner_idx: int,
    uid: str,
    zone: str | None,
    slot: int,
) -> ActionResult:
    player = engine.state.players[player_idx]
    card = engine.state.instances[uid]

    if zone not in {"attack", "defense"}:
        player.hand.append(uid)
        return ActionResult(False, "Zona non valida per il posizionamento del santo.")
    if not engine.place_card_from_uid(place_owner_idx, uid, zone, slot):
        player.hand.append(uid)
        return ActionResult(False, "Slot occupato.")

    card.exhausted = False
    bonus_multiplier = runtime_cards.get_context_bonus_amount(
        engine,
        player_idx,
        context="summon_faith",
        amount_mode="base_faith_multiplier",
    )
    if bonus_multiplier > 0:
        card.current_faith = (card.current_faith or 0) + max(0, card.definition.faith or 0) * bonus_multiplier
    bonus_flat = runtime_cards.get_context_bonus_amount(
        engine,
        player_idx,
        context="summon_faith",
        amount_mode="flat",
    )
    if bonus_flat > 0:
        card.current_faith = (card.current_faith or 0) + int(bonus_flat)

    zone_label = "Attacco" if zone == "attack" else "Difesa"
    engine.state.log(f"{player.name} posiziona {card.definition.name} in {zone_label} {slot + 1}.")

    play_msg = resolve_card_effect(engine, player_idx, uid, None)
    if play_msg and "nessun effetto" not in str(play_msg).lower():
        engine.state.log(str(play_msg))

    engine._emit_event("on_enter_field", player_idx, card=uid, from_zone="hand")
    engine._emit_event("on_summoned_from_hand", player_idx, card=uid)
    if _norm(card.definition.card_type) == "token":
        engine._emit_event("on_token_summoned", player_idx, token=uid, summoner=player_idx)
    else:
        engine._emit_event("on_opponent_saint_enters_field", 1 - player_idx, saint=uid)

    enter_msg = resolve_enter_effect(engine, player_idx, uid)
    if enter_msg:
        engine.state.log(enter_msg)
    runtime_cards.apply_rule(engine, "refresh_continuous_effects", player_idx=player_idx)
    return ActionResult(True, "Carta giocata.")


# Handles artifact placement, replacement rules, and enter effects.
def handle_artifact_play(engine: "GameEngine", player_idx: int, uid: str) -> ActionResult:
    player = engine.state.players[player_idx]
    card = engine.state.instances[uid]
    blocked_slots = query_ops.get_blocked_artifact_slots_for_player(engine, player_idx)
    usable_slots = [idx for idx in range(ARTIFACT_SLOTS) if idx not in blocked_slots]
    if not usable_slots:
        return ActionResult(False, "Tutte le zone Artefatto sono bloccate da effetti avversari.")
    slot = next((i for i in usable_slots if player.artifacts[i] is None), None)
    if slot is None:
        slot = usable_slots[-1]
        replaced = player.artifacts[slot]
        if replaced:
            engine.send_to_graveyard(player_idx, replaced)
    player.artifacts[slot] = uid

    engine.state.log(f"{player.name} posiziona Artefatto {card.definition.name}.")

    play_msg = resolve_card_effect(engine, player_idx, uid, None)
    if play_msg and "nessun effetto" not in str(play_msg).lower():
        engine.state.log(str(play_msg))

    engine._emit_event("on_enter_field", player_idx, card=uid, from_zone="hand")
    enter_msg = resolve_enter_effect(engine, player_idx, uid)
    if enter_msg:
        engine.state.log(enter_msg)
    return ActionResult(True, "Carta giocata.")


# Handles building placement and its immediate enter effect resolution.
def handle_building_play(engine: "GameEngine", player_idx: int, uid: str) -> ActionResult:
    player = engine.state.players[player_idx]
    card = engine.state.instances[uid]
    player.building = uid
    engine.state.log(f"{player.name} posiziona Edificio {card.definition.name}.")

    play_msg = resolve_card_effect(engine, player_idx, uid, None)
    if play_msg and "nessun effetto" not in str(play_msg).lower():
        engine.state.log(str(play_msg))

    engine._emit_event("on_enter_field", player_idx, card=uid, from_zone="hand")
    enter_msg = resolve_enter_effect(engine, player_idx, uid)
    if enter_msg:
        engine.state.log(enter_msg)
    return ActionResult(True, "Carta giocata.")


# Resolves quick cards from hand, including counter-spell cancellation and cleanup.
def resolve_quick_play_from_hand(engine: "GameEngine", player_idx: int, uid: str, target: str | None) -> ActionResult:
    player = engine.state.players[player_idx]
    card = engine.state.instances[uid]
    if engine._consume_counter_spell(player_idx):
        engine.send_to_graveyard(player_idx, uid)
        engine.state.log(f"{player.name} prova a usare {card.definition.name}, ma viene annullata da un effetto di protezione.")
        return ActionResult(True, "Attivazione annullata da un effetto di protezione.")
    resolved = resolve_card_effect(engine, player_idx, uid, target)
    moved_elsewhere = False
    is_equipped_overlay = any(
        isinstance(tag, str) and tag.startswith("equipped_to:")
        for tag in list(card.blessed)
    )
    for owner_idx in (0, 1):
        p = engine.state.players[owner_idx]
        if (
            uid in p.hand
            or uid in p.deck
            or uid in p.white_deck
            or uid in p.graveyard
            or uid in p.excommunicated
            or uid in p.attack
            or uid in p.defense
            or uid in p.artifacts
            or p.building == uid
        ):
            moved_elsewhere = True
            break
    if is_equipped_overlay:
        moved_elsewhere = True
    if not moved_elsewhere:
        engine.send_to_graveyard(player_idx, uid)
    engine._cleanup_zero_faith_saints()
    engine.check_win_conditions()
    return ActionResult(True, resolved)


# Plays a card from hand by validating, paying, and dispatching to the correct resolver branch.
def play_card(engine: "GameEngine", player_idx: int, hand_index: int, target: str | None = None) -> ActionResult:
    player = engine.state.players[player_idx]
    if player_idx != engine.state.active_player:
        return ActionResult(False, "Puoi giocare solo nel tuo turno (tranne Benedizioni/Maledizioni in risposta).")

    card = engine.card_from_hand(player_idx, hand_index)
    if card is None:
        return ActionResult(False, "Indice mano non valido.")
    selected_uid = player.hand[hand_index]
    script = runtime_cards.get_script(card.effect_name)

    # Determine the card type and handle preparation phase restrictions for Innate cards, including the requirement to play or remove unplayed Innate cards before playing other cards during the preparation phase. This ensures that the rules regarding Innate cards are enforced correctly based on the current game phase and the player's hand.
    ctype = _norm(card.definition.card_type)
    if ctype == "innata":
        if engine.state.phase != "preparation":
            return ActionResult(False, "Le carte Innata si possono giocare solo nel turno di preparazione.")
    elif engine.state.phase == "preparation" and _has_unplayed_innate_in_hand(engine, player_idx):
        _remove_unplayed_innate_from_hand(engine, player_idx)
        player = engine.state.players[player_idx]
        if selected_uid not in player.hand:
            return ActionResult(False, "La carta selezionata non e piu valida dopo l'eliminazione della carta Innata.")
        hand_index = player.hand.index(selected_uid)
        card = engine.card_from_hand(player_idx, hand_index)
        if card is None:
            return ActionResult(False, "Indice mano non valido.")
        script = runtime_cards.get_script(card.effect_name)
        ctype = _norm(card.definition.card_type)

    placement_target, _directives = _split_play_target_with_directives(target)

    # Check the generic can_play conditions from the runtime card scripts, which may include various custom rules and restrictions for whether the card can be played in the current context. This allows for a flexible system of play requirements that can be defined on a per-card basis in the runtime scripts.
    can_play, reason = runtime_cards.can_play(
        engine,
        player_idx,
        player.hand[hand_index],
        target=placement_target,
    )
    if not can_play:
        return ActionResult(False, reason or "Non puoi giocare questa carta.")

    if ctype in QUICK_TYPES:
        play_limit = _consume_named_play_limit(engine, player_idx, card)
        if play_limit is not None:
            return play_limit

    # Validate placement constraints based on card type and target, ensuring that the card can be played in the intended location and context according to the game rules and any specific requirements for that card type.
    is_valid, error_message, place_owner_idx, zone, slot = validate_play_constraints(engine, player_idx, card, placement_target)
    if not is_valid:
        return ActionResult(False, error_message)

    # Calculate the cost of playing the card, including any modifiers from other cards or game state, and attempt to spend the required Inspiration. This handles the payment of costs for playing the card and ensures that the player has sufficient resources to play it, while also applying any relevant cost modifications based on the current game context.
    paid_inspiration = 0
    if ctype not in QUICK_TYPES:
        use_all_remaining = bool(
            script is not None and bool(script.play_requirements.get("consume_all_remaining_inspiration", False))
        )
        if use_all_remaining:
            paid_inspiration = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
            spend_error = spend_inspiration_for_cost(engine, player_idx, paid_inspiration)
            if spend_error is not None:
                return spend_error
        else:
            override_by_player = dict(
                engine.state.flags.setdefault("drawn_play_cost_override_until_turn_end", {"0": {}, "1": {}}).get(
                    str(player_idx), {}
                )
                or {}
            )
            override_cost_raw = override_by_player.get(str(selected_uid))
            if override_cost_raw is not None:
                cost = max(0, int(override_cost_raw))
            else:
                cost = calculate_play_cost(engine, player_idx, hand_index, card)
            paid_inspiration = int(cost)
            spend_error = spend_inspiration_for_cost(engine, player_idx, cost)
            if spend_error is not None:
                return spend_error

    # Remove the card from hand and handle any special logic for Saints/Tokens that depends on the paid Inspiration, such as setting current faith or storing the paid inspiration as a tag on the card. This ensures that the card is properly removed from the player's hand and that any relevant effects based on the cost payment are applied to the card before it is placed on the field or resolved.
    uid = player.hand.pop(hand_index)
    if script is not None and ctype in SAINT_TYPES:
        faith_mult_raw = script.play_requirements.get("set_source_faith_from_paid_inspiration_multiplier")
        if faith_mult_raw is not None:
            try:
                faith_mult = int(faith_mult_raw)
            except (TypeError, ValueError):
                faith_mult = 1
            card.current_faith = max(0, int(paid_inspiration) * max(0, faith_mult))
        if bool(script.play_requirements.get("store_paid_inspiration_on_source", False)):
            card.blessed = [tag for tag in card.blessed if not str(tag).startswith("paid_inspiration_on_summon:")]
            card.blessed.append(f"paid_inspiration_on_summon:{int(paid_inspiration)}")
    scripted_cost_error, sacrificed_total_faith = _consume_scripted_play_costs(
        engine,
        player_idx,
        card,
        play_target=target,
    )
    if scripted_cost_error is not None:
        player.hand.insert(hand_index, uid)
        return scripted_cost_error
    if script is not None and ctype in SAINT_TYPES:
        if bool(script.play_requirements.get("gain_faith_from_play_sacrifices", False)) and sacrificed_total_faith > 0:
            card.current_faith = (card.current_faith or 0) + int(sacrificed_total_faith)
            if bool(script.play_requirements.get("grant_no_sin_on_death_if_gained_faith_from_sacrifices", False)):
                if "no_sin_on_death" not in card.blessed:
                    card.blessed.append("no_sin_on_death")
    emit_play_events(engine, player_idx, uid, ctype, placement_target)

    # Dispatch to the correct resolver branch based on card type, handling the specific logic for placing Saints/Tokens, Artifacts, Buildings, and resolving Innate effects, while also providing a fallback for unimplemented card types. This ensures that each card type is processed according to its specific rules and effects when played from hand.
    if ctype in SAINT_TYPES:
        result = handle_saint_play(engine, player_idx, place_owner_idx, uid, zone, slot)
    elif ctype == "artefatto":
        result = handle_artifact_play(engine, player_idx, uid)
    elif ctype == "edificio":
        result = handle_building_play(engine, player_idx, uid)
    elif ctype == "innata":
        resolved = resolve_card_effect(engine, player_idx, uid, target)
        active_innate = engine.state.flags.setdefault("innate_active_uids", {"0": [], "1": []}).setdefault(str(player_idx), [])
        if uid not in active_innate:
            active_innate.append(uid)
        runtime_cards.on_enter_bind_triggers(engine, player_idx, uid)
        engine.state.log(f"{player.name} attiva Innata {card.definition.name}. L'effetto resta perenne.")
        result = ActionResult(True, resolved)
    elif ctype in QUICK_TYPES:
        return resolve_quick_play_from_hand(engine, player_idx, uid, target)
    else:
        engine.send_to_graveyard(player_idx, uid)
        engine.state.log(f"{player.name} usa {card.definition.name} senza effetto implementato.")
        result = ActionResult(True, "Carta giocata.")

    # After resolving the play, perform cleanup of any zero-faith saints and check for win conditions, ensuring that the game state is updated correctly after the card is played and that any relevant end-of-turn checks are performed.
    if not result.ok:
        return result

    engine._cleanup_zero_faith_saints()
    engine.check_win_conditions()
    return result


def quick_play(engine: "GameEngine", player_idx: int, hand_index: int, target: str | None = None) -> ActionResult:
    player = engine.state.players[player_idx]
    card = engine.card_from_hand(player_idx, hand_index)
    if card is None:
        return ActionResult(False, "Indice mano non valido.")
    ctype = _norm(card.definition.card_type)
    script = runtime_cards.get_script(card.effect_name)
    quick_cfg = dict(script.play_requirements) if script is not None else {}
    is_quick_override = bool(quick_cfg.get("allow_quick_play_out_of_turn", False))
    if ctype not in QUICK_TYPES and not is_quick_override:
        return ActionResult(False, "Solo Benedizione/Maledizione (o carte con Quick Play dedicato) sono giocabili fuori turno.")
    if ctype in QUICK_TYPES:
        play_limit = _consume_named_play_limit(engine, player_idx, card)
        if play_limit is not None:
            return play_limit
    uid = player.hand.pop(hand_index)
    emit_play_events(engine, player_idx, uid, ctype, target)

    if is_quick_override:
        target_card = engine.resolve_target_saint(player_idx, target)
        if target_card is None:
            own = engine.all_saints_on_field(player_idx)
            target_card = engine.state.instances[own[0]] if own else None
        if target_card is None:
            player.hand.insert(hand_index, uid)
            return ActionResult(False, "Nessun santo valido bersaglio per il Quick Play.")
        if bool(quick_cfg.get("quick_play_excommunicate_self", True)):
            player.excommunicated.append(uid)
        else:
            engine.send_to_graveyard(player_idx, uid, from_zone_override="hand")
        bless_tag = str(quick_cfg.get("quick_play_grant_blessed_tag", "")).strip()
        if bless_tag and bless_tag not in target_card.blessed:
            target_card.blessed.append(bless_tag)
        engine._cleanup_zero_faith_saints()
        engine.check_win_conditions()
        return ActionResult(True, f"{player.name} attiva {card.definition.name} su {target_card.definition.name}.")
    result = resolve_quick_play_from_hand(engine, player_idx, uid, target)
    return result

