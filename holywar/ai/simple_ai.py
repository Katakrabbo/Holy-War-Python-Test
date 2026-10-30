from __future__ import annotations

import copy
import random
import unicodedata
from dataclasses import dataclass

from holywar.core.engine import ActionResult, GameEngine


SAINT_TYPES = {"santo", "token"}
QUICK_TYPES = {"benedizione", "maledizione"}


@dataclass(frozen=True)
class Move:
    kind: str
    hand_index: int | None = None
    target: str | None = None
    from_slot: int | None = None
    target_slot: int | None = None
    score: int = 0


def _norm(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def _safe_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _card_type(engine: GameEngine, uid: str) -> str:
    return _norm(engine.state.instances[uid].definition.card_type)


def _card_name(engine: GameEngine, uid: str) -> str:
    return _norm(engine.state.instances[uid].definition.name)


def _card_text(engine: GameEngine, uid: str) -> str:
    return _norm(engine.state.instances[uid].definition.effect_text)


def _faith(engine: GameEngine, uid: str) -> int:
    inst = engine.state.instances[uid]
    return max(0, _safe_int(inst.current_faith, _safe_int(inst.definition.faith)))


def _strength(engine: GameEngine, uid: str) -> int:
    try:
        return max(0, engine.get_effective_strength(uid))
    except Exception:
        return max(0, _safe_int(engine.state.instances[uid].definition.strength))


def _is_affordable(engine: GameEngine, player_idx: int, hand_index: int) -> bool:
    card = engine.card_from_hand(player_idx, hand_index)
    if card is None:
        return False

    ctype = _norm(card.definition.card_type)

    if ctype in QUICK_TYPES:
        return True

    try:
        cost = int(engine._calculate_play_cost(player_idx, hand_index, card))
    except Exception:
        cost = _safe_int(card.definition.faith)

    player = engine.state.players[player_idx]
    available = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
    return cost <= available


def _permanent_value(engine: GameEngine, uid: str) -> int:
    inst = engine.state.instances[uid]
    ctype = _norm(inst.definition.card_type)
    name = _norm(inst.definition.name)
    text = _norm(inst.definition.effect_text)

    value = 0

    if ctype in SAINT_TYPES:
        value += _faith(engine, uid) * 5
        value += _strength(engine, uid) * 7

        if "non puo attaccare" in text:
            value -= 8
        if "pesca" in text:
            value += 10
        if "evoca" in text or "token" in text:
            value += 12
        if "distrugg" in text or "scomunic" in text:
            value += 12
        if "ogni fine turno" in text or "fine turno" in text:
            value += 10

    elif ctype == "artefatto":
        value += 28 + _safe_int(inst.definition.faith) * 3
        if "forza" in text or "+" in text:
            value += 14
        if "pesca" in text:
            value += 12
        if "annulla" in text or "barriera" in text:
            value += 12

    elif ctype == "edificio":
        value += 38 + _safe_int(inst.definition.faith) * 3
        if "ogni" in text or "fine turno" in text or "inizio turno" in text:
            value += 16
        if "evoca" in text or "token" in text:
            value += 16

    elif ctype == "innata":
        value += 45

    value = runtime_cards.apply_rule(engine, "ai_score", value, uid=uid, stage="permanent")

    return value


def _board_value(engine: GameEngine, player_idx: int) -> int:
    player = engine.state.players[player_idx]
    opponent = engine.state.players[1 - player_idx]

    score = 0

    score += (opponent.sin - player.sin) * 4
    score += player.inspiration
    score += player.temporary_inspiration
    score += len(player.hand) * 7
    score -= len(opponent.hand) * 5

    for uid in player.attack:
        if uid is not None:
            score += _permanent_value(engine, uid)
            score += _strength(engine, uid) * 3

    for uid in player.defense:
        if uid is not None:
            score += int(_permanent_value(engine, uid) * 0.85)
            score += _faith(engine, uid) * 2

    for uid in player.artifacts:
        if uid is not None:
            score += _permanent_value(engine, uid)

    if player.building is not None:
        score += _permanent_value(engine, player.building)

    for uid in opponent.attack:
        if uid is not None:
            score -= int(_permanent_value(engine, uid) * 1.15)
            score -= _strength(engine, uid) * 4

    for uid in opponent.defense:
        if uid is not None:
            score -= int(_permanent_value(engine, uid) * 0.85)

    for uid in opponent.artifacts:
        if uid is not None:
            score -= int(_permanent_value(engine, uid) * 0.9)

    if opponent.building is not None:
        score -= int(_permanent_value(engine, opponent.building) * 1.1)

    if opponent.sin >= 100:
        score += 100000

    if player.sin >= 100:
        score -= 100000

    if engine.state.winner == player_idx:
        score += 1000000
    elif engine.state.winner == 1 - player_idx:
        score -= 1000000

    return score


def _best_own_target(engine: GameEngine, player_idx: int) -> str | None:
    player = engine.state.players[player_idx]
    candidates: list[tuple[int, str]] = []

    for prefix, slots in (("a", player.attack), ("d", player.defense)):
        for slot, uid in enumerate(slots):
            if uid is not None:
                candidates.append((_permanent_value(engine, uid), f"{prefix}{slot + 1}"))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def _best_enemy_target(engine: GameEngine, player_idx: int) -> str | None:
    opponent = engine.state.players[1 - player_idx]
    candidates: list[tuple[int, str]] = []

    for prefix, slots in (("a", opponent.attack), ("d", opponent.defense)):
        for slot, uid in enumerate(slots):
            if uid is not None:
                candidates.append((_permanent_value(engine, uid), f"{prefix}{slot + 1}"))

    for slot, uid in enumerate(opponent.artifacts):
        if uid is not None:
            candidates.append((_permanent_value(engine, uid), f"r{slot + 1}"))

    if opponent.building is not None:
        candidates.append((_permanent_value(engine, opponent.building), "b"))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def _saint_targets(engine: GameEngine, player_idx: int, uid: str) -> list[str]:
    player = engine.state.players[player_idx]
    targets: list[str] = []

    strength = _strength(engine, uid)
    text = _card_text(engine, uid)

    if strength > 0 and "non puo attaccare" not in text:
        for slot, value in enumerate(player.attack):
            if value is None:
                targets.append(f"a{slot + 1}")

    for slot, value in enumerate(player.defense):
        if value is None:
            targets.append(f"d{slot + 1}")

    for slot, value in enumerate(player.attack):
        if value is None and f"a{slot + 1}" not in targets:
            targets.append(f"a{slot + 1}")

    return targets


def _candidate_play_moves(engine: GameEngine, player_idx: int) -> list[Move]:
    player = engine.state.players[player_idx]
    moves: list[Move] = []

    for hand_index, uid in enumerate(list(player.hand)):
        if uid not in engine.state.instances:
            continue

        if not _is_affordable(engine, player_idx, hand_index):
            continue

        ctype = _card_type(engine, uid)

        if ctype in SAINT_TYPES:
            for target in _saint_targets(engine, player_idx, uid):
                moves.append(Move("play", hand_index=hand_index, target=target))

        elif ctype == "edificio":
            if player.building is None:
                moves.append(Move("play", hand_index=hand_index, target=None))

        elif ctype == "artefatto":
            moves.append(Move("play", hand_index=hand_index, target=None))

        elif ctype == "benedizione":
            target = _best_own_target(engine, player_idx)
            if target is not None:
                moves.append(Move("play", hand_index=hand_index, target=target))
            moves.append(Move("play", hand_index=hand_index, target=None))

        elif ctype == "maledizione":
            target = _best_enemy_target(engine, player_idx)
            if target is not None:
                moves.append(Move("play", hand_index=hand_index, target=target))
            moves.append(Move("play", hand_index=hand_index, target=None))

        elif ctype == "innata":
            moves.append(Move("play", hand_index=hand_index, target=None))

    return moves


def _candidate_attack_moves(engine: GameEngine, player_idx: int) -> list[Move]:
    player = engine.state.players[player_idx]
    opponent = engine.state.players[1 - player_idx]
    moves: list[Move] = []

    enemy_has_saints = any(uid is not None for uid in opponent.attack + opponent.defense)

    for slot, uid in enumerate(player.attack):
        if uid is None:
            continue
        if engine.state.instances[uid].exhausted:
            continue

        if not enemy_has_saints:
            moves.append(Move("attack", from_slot=slot, target_slot=None))
            continue

        for target_slot, target_uid in enumerate(opponent.attack):
            if target_uid is not None:
                moves.append(Move("attack", from_slot=slot, target_slot=target_slot))

    return moves


def _simulate(engine: GameEngine, player_idx: int, move: Move) -> int | None:
    # IMPORTANTE:
    # Non simulare chiamando play_card() o attack().
    # Il motore degli effetti può registrare trigger globali/callback anche se lo state è copiato.
    # Qui facciamo solo una stima statica, senza effetti collaterali.
    score = _board_value(engine, player_idx)

    if move.kind == "play" and move.hand_index is not None:
        card = engine.card_from_hand(player_idx, move.hand_index)
        if card is None:
            return None

        ctype = _norm(card.definition.card_type)
        text = _norm(card.definition.effect_text)
        name = _norm(card.definition.name)

        faith = _safe_int(card.definition.faith)
        strength = _safe_int(card.definition.strength)

        if ctype in SAINT_TYPES:
            score += 30 + faith * 5 + strength * 8

            if move.target and move.target.startswith("a"):
                score += 12

            if move.target and move.target.startswith("d"):
                score += 6

            if "non può attaccare" in text and move.target and move.target.startswith("d"):
                score += 12

        elif ctype == "edificio":
            score += 50 + faith * 4

            score = runtime_cards.apply_rule(engine, "ai_score", score, uid=card.uid, stage="building_play")

            if "token" in text or "evoca" in text:
                score += 25

            if "fine turno" in text or "inizio turno" in text:
                score += 20

        elif ctype == "artefatto":
            score += 35 + faith * 4

            if "forza" in text or "+" in text:
                score += 15

            if "pesca" in text:
                score += 12

        elif ctype == "maledizione":
            score += 35

            if "distrugg" in text or "scomunic" in text:
                score += 25

            if move.target is not None:
                score += 20

        elif ctype == "benedizione":
            score += 25

            if move.target is not None:
                score += 15

            if "forza" in text or "+" in text:
                score += 12

            if "pesca" in text:
                score += 12

        elif ctype == "innata":
            score += 45

    elif move.kind == "attack":
        score += _tactical_bonus(engine, player_idx, move)

    return score


def _tactical_bonus(engine: GameEngine, player_idx: int, move: Move) -> int:
    bonus = 0

    if move.kind == "play" and move.hand_index is not None:
        card = engine.card_from_hand(player_idx, move.hand_index)
        if card is None:
            return 0

        ctype = _norm(card.definition.card_type)
        name = _norm(card.definition.name)
        text = _norm(card.definition.effect_text)

        if ctype in SAINT_TYPES:
            bonus += max(0, _safe_int(card.definition.strength)) * 4
            bonus += max(0, _safe_int(card.definition.faith)) * 2

            if move.target and move.target.startswith("a"):
                bonus += 10

            if "non puo attaccare" in text and move.target and move.target.startswith("d"):
                bonus += 12

        elif ctype == "edificio":
            bonus += 18
            bonus = runtime_cards.apply_rule(engine, "ai_score", bonus, uid=card.uid, stage="building_tactical")

        elif ctype == "artefatto":
            bonus += 14

        elif ctype == "maledizione":
            bonus += 16
            if "distrugg" in text or "scomunic" in text:
                bonus += 20

        elif ctype == "benedizione":
            bonus += 10
            if "pesca" in text or "forza" in text:
                bonus += 8

    elif move.kind == "attack":
        player = engine.state.players[player_idx]
        opponent = engine.state.players[1 - player_idx]

        if move.from_slot is not None:
            attacker_uid = player.attack[move.from_slot]
            if attacker_uid is not None:
                damage = _strength(engine, attacker_uid)
                bonus += damage * 6

                if move.target_slot is None:
                    bonus += 35 + damage * 4
                else:
                    defender_uid = opponent.attack[move.target_slot]
                    if defender_uid is not None:
                        if damage >= _faith(engine, defender_uid):
                            bonus += 40
                        bonus += int(_permanent_value(engine, defender_uid) * 0.35)

    return bonus


def _choose_best_move(engine: GameEngine, player_idx: int, rng: random.Random) -> Move | None:
    base_score = _board_value(engine, player_idx)
    candidates = _candidate_attack_moves(engine, player_idx) + _candidate_play_moves(engine, player_idx)

    scored: list[Move] = []

    for move in candidates:
        simulated_score = _simulate(engine, player_idx, move)
        if simulated_score is None:
            continue

        final_score = simulated_score - base_score
        final_score += _tactical_bonus(engine, player_idx, move)
        final_score += rng.randint(0, 4)

        scored.append(
            Move(
                kind=move.kind,
                hand_index=move.hand_index,
                target=move.target,
                from_slot=move.from_slot,
                target_slot=move.target_slot,
                score=final_score,
            )
        )

    if not scored:
        return None

    scored.sort(key=lambda m: m.score, reverse=True)

    best = scored[0]

    # Non passare solo perché la valutazione immediata è bassa:
    # l'AI deve comunque sviluppare il campo.
    return best


def _ranked_moves(engine: GameEngine, player_idx: int, rng: random.Random) -> list[Move]:
    base_score = _board_value(engine, player_idx)
    candidates = _candidate_attack_moves(engine, player_idx) + _candidate_play_moves(engine, player_idx)
    scored: list[Move] = []
    for move in candidates:
        simulated_score = _simulate(engine, player_idx, move)
        if simulated_score is None:
            continue
        final_score = simulated_score - base_score
        final_score += _tactical_bonus(engine, player_idx, move)
        final_score += rng.randint(0, 4)
        scored.append(
            Move(
                kind=move.kind,
                hand_index=move.hand_index,
                target=move.target,
                from_slot=move.from_slot,
                target_slot=move.target_slot,
                score=final_score,
            )
        )
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored


def choose_action(engine: GameEngine, player_idx: int, rng: random.Random) -> ActionResult:
    if engine.state.winner is not None:
        return ActionResult(True, "AI passa.")

    if player_idx != engine.state.active_player:
        return ActionResult(True, "AI passa.")

    ranked = _ranked_moves(engine, player_idx, rng)
    if not ranked:
        return ActionResult(True, "AI passa.")

    for move in ranked:
        if move.kind == "play" and move.hand_index is not None:
            result = engine.play_card(player_idx, move.hand_index, move.target)
            if result.ok:
                return result
        elif move.kind == "attack" and move.from_slot is not None:
            result = engine.attack(player_idx, move.from_slot, move.target_slot)
            if result.ok:
                return result

    return ActionResult(True, "AI passa.")
