from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from holywar.core.state import ARTIFACT_SLOTS, CardInstance
from holywar.effects.runtime import runtime_cards

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


SAINT_TYPES = {"santo", "token"}


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


# Returns every saint or token owned by the player currently present on any board row.
def all_saints_on_field(engine: "GameEngine", player_idx: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for board_idx in (0, 1):
        player = engine.state.players[board_idx]
        for uid in player.attack + player.defense:
            if uid is None or uid in seen:
                continue
            inst = engine.state.instances.get(uid)
            if inst is None:
                continue
            if int(inst.owner) != int(player_idx):
                continue
            ctype = _norm(inst.definition.card_type)
            if ctype in SAINT_TYPES:
                out.append(uid)
                seen.add(uid)
    return out


# Returns only the saints or tokens currently occupying the player's attack row.
def all_attack_saints(engine: "GameEngine", player_idx: int) -> list[str]:
    player = engine.state.players[player_idx]
    out: list[str] = []
    for uid in player.attack:
        if uid is None:
            continue
        ctype = _norm(engine.state.instances[uid].definition.card_type)
        if ctype in SAINT_TYPES:
            out.append(uid)
    return out


# Checks whether the player currently controls a specific artifact by name.
def has_artifact(engine: "GameEngine", player_idx: int, name: str) -> bool:
    return any(
        uid and _norm(engine.state.instances[uid].definition.name) == _norm(name)
        for uid in engine.state.players[player_idx].artifacts
    )


# Counts how many copies of the named artifact are currently on the player's field.
def count_artifact(engine: "GameEngine", player_idx: int, name: str) -> int:
    return sum(
        1
        for uid in engine.state.players[player_idx].artifacts
        if uid and _norm(engine.state.instances[uid].definition.name) == _norm(name)
    )


# Checks whether the player currently controls the named building.
def has_building(engine: "GameEngine", player_idx: int, name: str) -> bool:
    uid = engine.state.players[player_idx].building
    if uid is None:
        return False
    return _norm(engine.state.instances[uid].definition.name) == _norm(name)


# Counts how many pyramid artifacts the player currently has in play.
def count_pyramids(engine: "GameEngine", player_idx: int) -> int:
    return sum(
        1
        for uid in engine.state.players[player_idx].artifacts
        if uid and runtime_cards.get_is_pyramid(engine.state.instances[uid].effect_name)
    )


# Converts a compact target like a1 or d2 into a board zone and zero-based slot index.
def parse_zone_target(target: str | None) -> tuple[str | None, int]:
    if not target:
        return None, -1
    value = target.strip().lower()
    if len(value) != 2:
        return None, -1
    zone_char, slot_char = value[0], value[1]
    if not slot_char.isdigit():
        return None, -1
    slot = int(slot_char) - 1
    if slot < 0 or slot >= 3:
        return None, -1
    if zone_char == "a":
        return "attack", slot
    if zone_char == "d":
        return "defense", slot
    return None, -1


# Returns the first empty index in a list of slots, or None if every slot is occupied.
def first_open(slots: list[str | None]) -> int | None:
    for idx, val in enumerate(slots):
        if val is None:
            return idx
    return None


# Consumes a one-shot barrier blessing if the defender has one active.
def consume_barrier(engine: "GameEngine", defender: CardInstance) -> str | None:
    for i, tag in enumerate(list(defender.blessed)):
        if isinstance(tag, str) and tag.startswith("barrier_once:"):
            source_uid = ""
            parts = tag.split(":")
            if len(parts) >= 3:
                source_uid = parts[2].strip()
            try:
                defender.blessed.pop(i)
            except Exception:
                defender.blessed.remove(tag)
            if source_uid and source_uid in engine.state.instances:
                source_owner = int(engine.state.instances[source_uid].owner)
                source_player = engine.state.players[source_owner]
                source_in_grave = source_uid in source_player.graveyard
                if not source_in_grave:
                    engine.send_to_graveyard(source_owner, source_uid)
            return "Barriera"
    return None


# Applies static damage-prevention effects that reduce or cancel incoming damage.
def apply_damage_mitigation(
    engine: "GameEngine",
    target_owner_idx: int,
    damage: int,
    target_uid: str | None = None,
) -> int:
    if damage <= 0:
        return 0

    # Determine the card type of the target if a specific target uid is provided, as some damage prevention effects may only apply to certain card types. This checks if the target uid corresponds to a valid instance on the field and retrieves its card type, which can then be used to filter applicable damage prevention effects based on their allowed target types.
    target_type = ""
    if target_uid and target_uid in engine.state.instances:
        target_type = _norm(engine.state.instances[target_uid].definition.card_type)

    # Check for any damage prevention effects from the player's artifacts or building that can reduce or negate the incoming damage, taking into account any specific conditions or allowed target types defined by those effects. This iterates through all potential sources of damage prevention on the player's field, checking for any that have defined thresholds for preventing incoming damage and applying those effects if the conditions are met, allowing for dynamic mitigation of damage based on the current state of the player's board and the specific target being damaged.
    player = engine.state.players[target_owner_idx]
    aura_sources: list[str] = []
    aura_sources.extend([uid for uid in player.artifacts if uid is not None])
    if player.building is not None:
        aura_sources.append(player.building)

    # Apply any damage prevention effects from the player's artifacts or building that can reduce or negate the incoming damage, taking into account any specific conditions or allowed target types defined by those effects. This iterates through all potential sources of damage prevention on the player's field, checking for any that have defined thresholds for preventing incoming damage and applying those effects if the conditions are met, allowing for dynamic mitigation of damage based on the current state of the player's board and the specific target being damaged.
    for source_uid in aura_sources:
        if source_uid not in engine.state.instances:
            continue
        source_name = engine.state.instances[source_uid].definition.name
        threshold = runtime_cards.get_prevent_incoming_damage_if_less_than(source_name)
        if threshold is None:
            continue
        allowed_types = {
            _norm(v) for v in runtime_cards.get_prevent_incoming_damage_to_card_types(source_name)
        }
        if allowed_types and target_type and target_type not in allowed_types:
            continue
        if damage < int(threshold):
            return 0
    return damage


# Checks and preserves turn-based no-attack curses that still apply to the attacker.
def is_attacker_blocked_this_turn(engine: "GameEngine", attacker: CardInstance) -> bool:
    keep: list[str] = []
    blocked = False
    for tag in attacker.cursed:
        if not tag.startswith("no_attack_until:"):
            keep.append(tag)
            continue
        try:
            until_turn = int(tag.split(":", 1)[1])
        except ValueError:
            continue
        if engine.state.turn_number <= until_turn:
            blocked = True
            keep.append(tag)
    attacker.cursed = keep
    return blocked


# Consumes the defender's one-per-turn attack shield when it is still active.
def consume_attack_shield(engine: "GameEngine", defender_idx: int) -> bool:
    shield = engine.state.flags.setdefault("attack_shield_turn", {})
    key = str(defender_idx)
    if int(shield.get(key, -1)) != int(engine.state.turn_number):
        return False
    shield.pop(key, None)
    return True


# Consumes a stored counter-spell charge from the opposing player.
def consume_counter_spell(engine: "GameEngine", caster_idx: int) -> bool:
    flags = engine.state.flags.setdefault("counter_spell_ready", {"0": 0, "1": 0})
    opp_key = str(1 - caster_idx)
    count = int(flags.get(opp_key, 0))
    if count <= 0:
        return False
    flags[opp_key] = count - 1
    return True


# Resolves a target string to a saint instance on the chosen player's board.
def resolve_target_saint(engine: "GameEngine", player_idx: int, target: str | None) -> CardInstance | None:
    if not target:
        return None
    value = target.strip().lower()
    if len(value) != 2:
        return None
    zone, slot = parse_zone_target(value)
    if zone not in {"attack", "defense"}:
        return None
    player = engine.state.players[player_idx]
    uid = getattr(player, zone)[slot]
    if uid is None:
        return None
    inst = engine.state.instances[uid]
    if "untargetable_effects" in inst.blessed:
        return None
    return inst


# Resolves a target string to an artifact or building uid on the chosen player's board.
def resolve_target_artifact_or_building(engine: "GameEngine", player_idx: int, target: str | None) -> str | None:
    if not target:
        return None
    value = target.strip().lower()
    player = engine.state.players[player_idx]
    if value.startswith("r") and len(value) == 2 and value[1].isdigit():
        idx = int(value[1]) - 1
        if 0 <= idx < ARTIFACT_SLOTS:
            return player.artifacts[idx]
    if value == "b":
        return player.building
    return None


# Resolves a generic board source string to the corresponding uid on the field.
def resolve_board_uid(engine: "GameEngine", player_idx: int, source: str | None) -> str | None:
    if not source:
        return None
    value = source.strip().lower()
    target_player_idx = player_idx
    if ":" in value:
        side, token = value.split(":", 1)
        side = side.strip().lower()
        token = token.strip().lower()
        if side in {"opp", "opponent", "enemy", "other", "o"}:
            target_player_idx = 1 - player_idx
            value = token
        elif side in {"self", "me", "own", "controller", "s"}:
            target_player_idx = player_idx
            value = token
    zone, slot = parse_zone_target(value)
    player = engine.state.players[target_player_idx]
    if zone in {"attack", "defense"}:
        return getattr(player, zone)[slot]
    return resolve_target_artifact_or_building(engine, target_player_idx, value)


# Finds the first matching card name inside the player's deck and returns its uid.
def find_card_uid_in_deck(engine: "GameEngine", player_idx: int, name: str) -> str | None:
    player = engine.state.players[player_idx]
    key = _norm(name)
    for uid in player.deck:
        if _norm(engine.state.instances[uid].definition.name) == key:
            return uid
    return None


def get_blocked_artifact_slots_for_player(engine: "GameEngine", player_idx: int) -> set[int]:
    """Return artifact slot indexes blocked for player_idx by enemy continuous effects."""
    opponent = engine.state.players[1 - player_idx]
    enemy_field_uids = [cand for cand in (opponent.attack + opponent.defense + opponent.artifacts) if cand]
    if opponent.building:
        enemy_field_uids.append(opponent.building)

    blocked_slots: set[int] = set()
    generic_block_count = 0
    for enemy_uid in enemy_field_uids:
        inst = engine.state.instances.get(enemy_uid)
        if inst is None:
            continue
        generic_block_count += int(runtime_cards.get_blocks_enemy_artifact_slots(inst.effect_name))
        for tag in list(inst.blessed):
            if not isinstance(tag, str) or not tag.startswith("block_enemy_artifact_slot:"):
                continue
            raw_idx = tag.split(":", 1)[1].strip()
            try:
                idx = int(raw_idx)
            except ValueError:
                continue
            if 0 <= idx < ARTIFACT_SLOTS:
                blocked_slots.add(idx)

    # Backward-compatible generic blocking: reserve rightmost slots.
    generic_block_count = max(0, min(ARTIFACT_SLOTS - 1, generic_block_count))
    for idx in range(ARTIFACT_SLOTS - 1, -1, -1):
        if len(blocked_slots) >= generic_block_count:
            break
        blocked_slots.add(idx)
    return blocked_slots


# Finds the first matching card name inside the player's graveyard and returns its uid.
def find_card_uid_in_graveyard(engine: "GameEngine", player_idx: int, name: str) -> str | None:
    player = engine.state.players[player_idx]
    key = _norm(name)
    for uid in player.graveyard:
        if _norm(engine.state.instances[uid].definition.name) == key:
            return uid
    return None


# Returns the sorted list of expansions currently present in the loaded match state.
def available_expansions(engine: "GameEngine") -> list[str]:
    names = set()
    for inst in engine.state.instances.values():
        if inst.definition.expansion:
            names.add(inst.definition.expansion)
    return sorted(names)
