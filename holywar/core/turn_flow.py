from __future__ import annotations

import unicodedata
from typing import Any

from holywar.core.state import TURN_INSPIRATION, hand_has_space_for_non_innata, is_innata_card_type
from holywar.effects.runtime import EffectSpec, runtime_cards
from holywar.effects.state_flags import ensure_runtime_state, refresh_player_flags, set_phase

GameEngine = Any

# The turn_flow module contains functions that manage the flow of turns in the game, including starting and ending turns, handling the draw phase, and applying turn-based effects. It also includes helper functions for normalizing text, checking card types, and managing hand limits. These functions work together to ensure that the game progresses smoothly and that all relevant effects and rules are applied correctly during each player's turn.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()

# The _emit_end_turn_events function is responsible for emitting the appropriate events at the end of a player's turn. It emits events for the end of the main phase, the end of the turn, and specific events for the active player and their opponent. This allows other parts of the game engine to react to these events and apply any necessary effects or updates based on the end of the turn.
def _emit_end_turn_events(engine: "GameEngine", current: int) -> None:
    engine._emit_event("on_main_phase_end", current, player=current)
    engine._emit_event("on_turn_end", current, player=current)
    engine._emit_event("on_my_turn_end", current, player=current)
    engine._emit_event("on_opponent_turn_end", current, opponent=current)

# The _is_preparation_context function checks if the game is currently in the preparation phase, which is defined as the first turn of the game (turn number 0) and before both players have completed their preparation turns. This is used to determine if certain effects or rules that only apply during preparation should be active.
def _is_preparation_context(engine: "GameEngine") -> bool:
    return int(engine.state.turn_number) == 0 and int(engine.state.preparation_turns_done) < 2

# The _open_saint_slot_tokens function generates a list of available slot tokens for placing saints in the attack and defense zones for a given player. It checks the player's current attack and defense slots and returns a list of tokens (e.g., "a1", "a2", "d1", "d2") for any slots that are currently empty (None). This is used to determine where a card like "Albero Sacro" can be automatically played from the hand during the draw phase.
def _open_saint_slot_tokens(engine: "GameEngine", player_idx: int) -> list[str]:
    player = engine.state.players[player_idx]
    out: list[str] = []
    for i, uid in enumerate(player.attack):
        if uid is None:
            out.append(f"a{i + 1}")
    for i, uid in enumerate(player.defense):
        if uid is None:
            out.append(f"d{i + 1}")
    return out

# The _try_auto_play_from_hand function attempts to automatically play a card from the player's hand based on certain conditions and effects. It checks if the specified card UID is in the player's hand and if it exists in the game state instances. If the card is "Albero Sacro" and the game is not in the preparation context, it allows the player to choose an available slot token for automatic play. It then applies the effect of moving the card from the hand to the board and checks if the card was successfully played. This function returns True if the card was played from the hand to a valid zone, and False otherwise.
def _try_auto_play_from_hand(engine: "GameEngine", player_idx: int, uid: str) -> bool:
    player = engine.state.players[player_idx]
    if uid not in player.hand:
        return False
    if uid not in engine.state.instances:
        return False

    # The following block manages temporary state flags for the source card and selected target during the auto-play process. It saves the previous values of these flags, sets them to the current card UID and selected target, applies the effect to move the card from the hand to the board, and then restores the previous flag values. This ensures that any effects that rely on these flags can function correctly during the auto-play process without permanently altering the game state.
    flags = engine.state.flags
    previous_source = flags.get("_runtime_source_card")
    previous_selected = flags.get("_runtime_selected_target")

    selected_target = ""
    try:
        card_name = engine.state.instances[uid].definition.name
    except Exception:
        card_name = ""
    if _norm(card_name) == _norm("Albero Sacro") and not _is_preparation_context(engine):
        chooser = getattr(engine, "choose_auto_play_slot_from_draw", None)
        if callable(chooser):
            slots = _open_saint_slot_tokens(engine, player_idx)
            if slots:
                chosen = chooser(player_idx, uid, slots)
                chosen_norm = str(chosen or "").strip().lower()
                if chosen_norm in {s.lower() for s in slots}:
                    selected_target = chosen_norm

    # Set temporary flags for the source card and selected target, apply the effect to move the card from the hand to the board, and then restore the previous flag values. This allows any effects that depend on these flags to function correctly during the auto-play process without permanently altering the game state.
    flags["_runtime_source_card"] = uid
    flags["_runtime_selected_target"] = selected_target
    try:
        runtime_cards._apply_effect(
            engine,
            player_idx,
            uid,
            [uid],
            EffectSpec(action="move_source_to_board"),
        )
    finally:
        if previous_source is None:
            flags.pop("_runtime_source_card", None)
        else:
            flags["_runtime_source_card"] = previous_source
        if previous_selected is None:
            flags.pop("_runtime_selected_target", None)
        else:
            flags["_runtime_selected_target"] = previous_selected

    zone_now = engine._locate_uid_zone(player_idx, uid)
    return uid not in player.hand and zone_now in {"attack", "defense", "artifacts", "artifact", "building"}

# The _resolve_deferred_auto_play_on_turn_start function checks for any cards that were drawn in a previous turn and had the "auto_play_on_draw" effect, but were not automatically played because they were drawn during the opponent's turn. It looks for these cards in the player's hand at the start of their turn and attempts to auto-play them if they are still present. If any of these cards have the "end_turn_on_draw" effect and are successfully auto-played, the function returns True to indicate that the turn should end immediately. Otherwise, it returns False to allow the turn to proceed as normal.
def _resolve_deferred_auto_play_on_turn_start(engine: "GameEngine", current: int) -> bool:
    runtime_state = ensure_runtime_state(engine)
    deferred = runtime_state.setdefault("deferred_auto_play_on_turn_start", {"0": [], "1": []})
    pending_uids = list(deferred.get(str(current), []) or [])
    if not pending_uids:
        return False

    player = engine.state.players[current]

    # Iterate through the pending UIDs for auto-play on turn start. For each UID, check if it is still in the player's hand and if it has the "auto_play_on_draw" effect. If so, attempt to auto-play it from the hand. If any card has the "end_turn_on_draw" effect and is successfully auto-played, return True to indicate that the turn should end immediately. Otherwise, return False to allow the turn to proceed as normal.
    for uid in pending_uids:
        if uid not in engine.state.instances:
            continue
        if uid not in player.hand:
            continue

        card_name = engine.state.instances[uid].definition.name
        if not runtime_cards.get_auto_play_on_draw(card_name):
            continue

        played = _try_auto_play_from_hand(engine, current, uid)

        deferred[str(current)] = [x for x in deferred.get(str(current), []) if x != uid]

        if not played:
            return False

        if runtime_cards.get_end_turn_on_draw(card_name):
            return True

    return False


def _max_auto_play_drawn_faith_threshold(engine: "GameEngine", player_idx: int) -> int | None:
    player = engine.state.players[player_idx]
    field_uids = [uid for uid in (player.attack + player.defense + player.artifacts) if uid]
    if player.building:
        field_uids.append(player.building)
    best: int | None = None
    for uid in field_uids:
        inst = engine.state.instances.get(uid)
        if inst is None:
            continue
        value = runtime_cards.get_auto_play_drawn_cards_with_faith_lte(inst.definition.name)
        if value is None:
            continue
        val = int(value)
        best = val if best is None else max(best, val)
    return best


def _try_auto_play_drawn_card_free(engine: "GameEngine", player_idx: int, uid: str) -> bool:
    player = engine.state.players[player_idx]
    if uid not in player.hand:
        return False
    inst = engine.state.instances.get(uid)
    if inst is None:
        return False

    chooser_confirm = getattr(engine, "choose_auto_play_drawn_card", None)
    if callable(chooser_confirm):
        try:
            wants_to_play = bool(chooser_confirm(player_idx, uid))
        except Exception:
            wants_to_play = False
        if not wants_to_play:
            return False

    ctype = _norm(inst.definition.card_type)
    target: str | None = None
    if ctype in {"santo", "token"}:
        slots = _open_saint_slot_tokens(engine, player_idx)
        if not slots:
            return False
        target = slots[0].lower()
        chooser = getattr(engine, "choose_auto_play_slot_from_draw", None)
        if callable(chooser):
            chosen = str(chooser(player_idx, uid, slots) or "").strip().lower()
            if chosen in {s.lower() for s in slots}:
                target = chosen
    free_flags = engine.state.flags.setdefault("free_play_uids", {"0": [], "1": []})
    key = str(player_idx)
    marked = list(free_flags.get(key, []) or [])
    if uid not in marked:
        marked.append(uid)
    free_flags[key] = marked
    try:
        hand_index = player.hand.index(uid)
        out = engine.play_card(player_idx, hand_index, target)
    finally:
        still_marked = [v for v in list(free_flags.get(key, []) or []) if v != uid]
        free_flags[key] = still_marked
    return bool(out.ok)

# Performs the initial setup draw for both players at match start.
def initial_setup_draw(engine: "GameEngine") -> None:
    for idx in (0, 1):
        draw_cards(engine, idx, 5)
        pending = list(
            engine.state.flags.setdefault("innate_pending_setup", {"0": [], "1": []}).get(str(idx), []) or []
        )
        player = engine.state.players[idx]
        for uid in pending:
            if uid not in engine.state.instances:
                continue
            for pool_name in ("deck", "white_deck", "graveyard", "excommunicated"):
                pool = getattr(player, pool_name)
                if uid in pool:
                    pool.remove(uid)
            if uid not in player.hand:
                player.hand.append(uid)
        engine.state.flags.setdefault("innate_pending_setup", {"0": [], "1": []})[str(idx)] = []
    engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})["0"] = []
    engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})["1"] = []
    engine.state.flags.setdefault("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})["0"] = 0
    engine.state.flags.setdefault("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})["1"] = 0
    engine.state.log("Setup iniziale completato: entrambi i giocatori hanno pescato 5 carte.")


# Draws cards while applying draw-triggered effects and bookkeeping.
def draw_cards(engine: "GameEngine", player_idx: int, amount: int) -> int:
    player = engine.state.players[player_idx]
    promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
    promise_active = bool(promise_state.get(str(player_idx), False))
    drawn = 0
    for _ in range(amount):
        if not hand_has_space_for_non_innata(player, engine.state.instances):
            break
        source_pool = player.graveyard if promise_active else player.deck
        if not source_pool:
            break
        drawn_uid = source_pool.pop()
        player.hand.append(drawn_uid)
        drawn += 1
        engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []}).setdefault(str(player_idx), []).append(drawn_uid)

        # If there are any sources that have locked attacks until a draw, unlock them now that the player has drawn a card.
        runtime_state = engine.state.flags.setdefault("runtime_state", {})
        locked_sources = list(runtime_state.get("no_attacks_until_draw_sources", []) or [])
        if locked_sources:
            runtime_state["no_attacks_until_draw_sources"] = []
            engine.state.log("Giorno Festivo: il blocco agli attacchi termina per una pescata.")

        engine._emit_event("on_card_drawn", player_idx, card=drawn_uid, from_zone=("graveyard" if promise_active else "relicario"))
        card_name = engine.state.instances[drawn_uid].definition.name
        drawn_faith = engine.state.instances[drawn_uid].definition.faith
        drawn_faith_int: int | None = None
        if drawn_faith is not None:
            try:
                drawn_faith_int = int(float(str(drawn_faith)))
            except (TypeError, ValueError):
                drawn_faith_int = None

        auto_play_succeeded = False

        # Generic aura-driven free auto-play for freshly drawn cards with low Faith (e.g. Nun).
        if int(player_idx) == int(engine.state.active_player):
            threshold = _max_auto_play_drawn_faith_threshold(engine, player_idx)
            if (
                threshold is not None
                and drawn_faith_int is not None
                and drawn_faith_int <= int(threshold)
                and drawn_uid in player.hand
            ):
                auto_play_succeeded = _try_auto_play_drawn_card_free(engine, player_idx, drawn_uid)

        # If the drawn card has the "auto_play_on_draw" effect, attempt to auto-play it from the hand. If the card was drawn during the opponent's turn, defer the auto-play attempt until the start of the player's next turn. If the card also has the "end_turn_on_draw" effect and was successfully auto-played, mark that the turn should end immediately after drawing.
        if runtime_cards.get_auto_play_on_draw(card_name) and drawn_uid in player.hand:
            is_controller_turn = int(player_idx) == int(engine.state.active_player)

            if is_controller_turn:
                auto_play_succeeded = _try_auto_play_from_hand(engine, player_idx, drawn_uid)
            else:
                runtime_state = engine.state.flags.setdefault("runtime_state", {})
                deferred = runtime_state.setdefault("deferred_auto_play_on_turn_start", {"0": [], "1": []})
                if drawn_uid in player.hand and drawn_uid not in deferred[str(player_idx)]:
                    deferred[str(player_idx)].append(drawn_uid)

        # If the card has the "end_turn_on_draw" effect and was successfully auto-played, set a flag to indicate that the turn should end immediately after drawing. This will be checked at the end of the draw phase to determine if the turn should end or proceed to the main phase.
        if runtime_cards.get_end_turn_on_draw(card_name) and auto_play_succeeded:
            runtime_state = engine.state.flags.setdefault("runtime_state", {})

            if _is_preparation_context(engine):
                pending = runtime_state.setdefault("preparation_end_turn_pending", [])
                if player_idx not in pending:
                    pending.append(player_idx)

                prep_auto_end = runtime_state.setdefault("request_end_preparation_players", [])
                if player_idx not in prep_auto_end:
                    prep_auto_end.append(player_idx)

            elif int(player_idx) == int(engine.state.active_player):
                runtime_state["request_end_turn_player"] = player_idx

        engine._emit_event("after_card_drawn_from_deck", player_idx, card=drawn_uid)
        engine._emit_event("on_opponent_draws", 1 - player_idx, card=drawn_uid, opponent=player_idx)
    refresh_player_flags(engine)
    return drawn

# The _remove_unplayed_innate_cards function is called at the end of the preparation phase to remove any innata cards that were not played during the preparation turns. It checks the player's hand, deck, white deck, graveyard, excommunicated zone, attack, defense, artifacts, and building for any innata cards that are still present and removes them from the game state. This ensures that players cannot keep innata cards that were meant to be played during preparation if they were not used, maintaining the integrity of the preparation phase.
def _remove_unplayed_innate_cards(engine: "GameEngine", player_idx: int) -> None:
    player = engine.state.players[player_idx]
    active = set(engine.state.flags.setdefault("innate_active_uids", {"0": [], "1": []}).get(str(player_idx), []) or [])
    removed = engine.state.flags.setdefault("innate_removed_uids", {"0": [], "1": []}).setdefault(str(player_idx), [])
    for uid, inst in engine.state.instances.items():
        if int(inst.owner) != int(player_idx):
            continue
        if not is_innata_card_type(inst.definition.card_type):
            continue
        if uid in active:
            continue
        removed_any = False
        for pool_name in ("hand", "deck", "white_deck", "graveyard", "excommunicated"):
            pool = getattr(player, pool_name)
            if uid in pool:
                pool.remove(uid)
                removed_any = True
        for zone in (player.attack, player.defense, player.artifacts):
            for i, z_uid in enumerate(zone):
                if z_uid == uid:
                    zone[i] = None
                    removed_any = True
        if player.building == uid:
            player.building = None
            removed_any = True
        if removed_any and uid not in removed:
            removed.append(uid)
            engine.state.log(f"{player.name}: {inst.definition.name} (Innata) non giocata in preparazione e stata eliminata.")


# Resets resources and per-turn board state for the active player.
def _reset_start_turn_resources(engine: "GameEngine", current: int) -> None:
    player = engine.state.players[current]
    player.inspiration = TURN_INSPIRATION
    bonus_next = engine.state.flags.setdefault("bonus_inspiration_next_turn", {"0": 0, "1": 0})
    key = str(engine.state.active_player)
    player.inspiration += int(bonus_next.get(key, 0))
    bonus_next[key] = 0
    for uid in player.attack:
        if uid:
            engine.state.instances[uid].exhausted = False


# Summons start-of-turn support tokens behind saints when their scripts require it.
def _summon_turn_start_tokens(engine: "GameEngine", current: int) -> None:
    player = engine.state.players[current]
    for i, a_uid in enumerate(player.attack):
        if not a_uid:
            continue
        token_name = runtime_cards.get_turn_start_summon_token_name(engine.state.instances[a_uid].definition.name)
        if not token_name:
            continue
        def_uid = player.defense[i]
        if def_uid and _norm(engine.state.instances[def_uid].definition.name) == _norm(token_name):
            continue
        token_uid = None
        for pool_name in ("white_deck", "deck", "graveyard", "excommunicated"):
            pool = getattr(player, pool_name)
            for c_uid in list(pool):
                if _norm(engine.state.instances[c_uid].definition.name) != _norm(token_name):
                    continue
                pool.remove(c_uid)
                token_uid = c_uid
                break
            if token_uid:
                break
        if token_uid is None and player.defense[i] is None:
            token_uid = runtime_cards._summon_generated_token(  # noqa: SLF001 - intentional runtime integration
                engine,
                current,
                token_name,
                preferred_zone="defense",
            )

        if token_uid is not None and player.defense[i] is None:
            if engine.place_card_from_uid(current, token_uid, "defense", i):
                final_zone = engine._locate_uid_zone(current, token_uid)
                if final_zone == "defense":
                    engine.state.log(f"{player.name} evoca {token_name} dietro {engine.state.instances[a_uid].definition.name}.")
                else:
                    engine.state.log(f"{player.name} evoca {token_name} in attacco.")


# Resolves the active player's draw phase, including special draw modifiers.
def _run_draw_phase(engine: "GameEngine", current: int) -> int:
    skip_next = engine.state.flags.setdefault("skip_next_draw_phase", {"0": False, "1": False})
    if bool(skip_next.get(str(current), False)):
        skip_next[str(current)] = False
        engine.state.log(f"{engine.state.players[current].name} salta la pescata iniziale del test.")
        return 0
    next_draw_override = engine.state.flags.setdefault("next_turn_draw_override", {"0": 0, "1": 0})
    override_amount = int(next_draw_override.get(str(engine.state.active_player), 0) or 0)
    if override_amount > 0:
        next_draw_override[str(engine.state.active_player)] = 0
        return draw_cards(engine, engine.state.active_player, override_amount)

    # Check for any pending "Albero Sacro" draws that need to be resolved before the normal draw. If there is a pending "Albero Sacro" draw, resolve it and return the number of cards drawn (which may be more than 1 if there are multiple pending draws).
    spore_pending = engine.state.flags.setdefault("spore_pending", {"0": False, "1": False})
    if spore_pending.get(str(engine.state.active_player), False):
        drawn = draw_cards(engine, engine.state.active_player, 8)
        spore_pending[str(engine.state.active_player)] = False
        return drawn

    # Calculate the number of cards to draw, including any flat bonuses from card effects or other sources. Then perform the draw and return the number of cards drawn.
    bonus_draw = runtime_cards.get_context_bonus_amount(
        engine,
        engine.state.active_player,
        context="turn_draw",
        amount_mode="flat",
    )
    return draw_cards(engine, engine.state.active_player, 3 + bonus_draw)


# Starts the active player's turn and advances the game into the main phase when appropriate.
def start_turn(engine: "GameEngine") -> None:
    current = engine.state.active_player
    player = engine.state.players[current]
    runtime_state = ensure_runtime_state(engine)
    if _resolve_deferred_auto_play_on_turn_start(engine, current):
        if _is_preparation_context(engine):
            prep_auto_end = runtime_state.setdefault("request_end_preparation_players", [])
            if current not in prep_auto_end:
                prep_auto_end.append(current)
            engine.state.log(f"{player.name} termina immediatamente la preparazione.")
            end_turn(engine)
            return
        # If the turn should end immediately after drawing due to an "end_turn_on_draw" effect, set the appropriate flag and end the turn. This will skip the main phase and go directly to the end phase, allowing any end-of-turn effects to resolve properly.
        engine.state.log(f"{player.name} termina immediatamente il turno.")
        end_turn(engine)
        return
    # Reset the battle phase flag at the start of the turn. This ensures that any effects or conditions that depend on whether the battle phase has started will be correctly reset at the beginning of each player's turn.
    runtime_state["battle_phase_started"] = False
    stale_player = runtime_state.get("request_end_turn_player", None)
    if stale_player is not None and stale_player not in {0, 1}:
        runtime_state.pop("request_end_turn_player", None)

    double_next = engine.state.flags.setdefault("double_cost_next_turn", {"0": 0, "1": 0})
    pending_double = int(double_next.get(str(current), 0) or 0)
    # "Next turn" cost taxes must start only on real active turns, never during preparation.
    if pending_double > 0 and engine.state.phase != "preparation":
        double_turns = engine.state.flags.setdefault("double_cost_turns", {"0": 0, "1": 0})
        double_turns[str(current)] = int(double_turns.get(str(current), 0)) + pending_double
        double_next[str(current)] = 0

    engine.state.flags.setdefault("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})["0"] = 0
    engine.state.flags.setdefault("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})["1"] = 0

    set_phase(engine, "turn_start")
    engine._emit_event("on_turn_start", current, player=current)
    engine._emit_event("on_my_turn_start", current, player=current)
    engine._emit_event("on_opponent_turn_start", current, opponent=current)

    set_phase(engine, "draw")
    engine._emit_event("before_draw_phase", current, player=current)
    engine._emit_event("on_draw_phase_start", current, player=current)

    _reset_start_turn_resources(engine, current)
    _summon_turn_start_tokens(engine, current)
    engine.state.flags.setdefault("attack_count", {"0": 0, "1": 0})[str(engine.state.active_player)] = 0
    engine.state.flags["attacked_targets_this_turn"] = {}
    engine.state.flags.setdefault("spent_inspiration_turn", {"0": 0, "1": 0})[str(engine.state.active_player)] = 0
    engine._cleanup_zero_faith_saints()

    if engine.state.phase == "preparation":
        prep_auto_end = runtime_state.setdefault("request_end_preparation_players", [])

        if current in prep_auto_end:
            prep_auto_end.remove(current)
            engine.state.log(f"{player.name} termina immediatamente la preparazione.")
            end_turn(engine)
            return

        engine.state.log(
            f"Preparazione: {player.name} dispone di 10 Ispirazione e non puo attaccare."
        )
        return

    drawn = _run_draw_phase(engine, current)
    engine._emit_event("on_draw_phase_end", current, player=current, drawn=drawn)

    if runtime_state.get("request_end_turn_player", None) == current:
        runtime_state.pop("request_end_turn_player", None)
        engine.state.log(f"{player.name} termina immediatamente il turno.")
        end_turn(engine)
        return

    set_phase(engine, "main")
    engine._emit_event("on_main_phase_start", current, player=current)
    engine.state.log(f"Turno {engine.state.turn_number}: {player.name} pesca {drawn} carte e ottiene 10 Ispirazione.")
    refresh_player_flags(engine)


# Completes end-of-turn effects and hands control to the next player or phase.
def end_turn(engine: "GameEngine") -> None:
    current = engine.state.active_player
    runtime_state = ensure_runtime_state(engine)
    was_preparation = str(engine.state.phase).strip().lower() == "preparation"

    if bool(runtime_state.get("battle_phase_started", False)):
        set_phase(engine, "battle")
        engine._emit_event("on_battle_phase_end", current, player=current)
        runtime_state["battle_phase_started"] = False

    set_phase(engine, "end")

    if not was_preparation:
        _emit_end_turn_events(engine, current)
    runtime_cards.resolve_end_turn_runtime_hooks(engine, current)

    engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})[str(current)] = []
    cost_override = engine.state.flags.setdefault("drawn_play_cost_override_until_turn_end", {"0": {}, "1": {}})
    cost_override[str(current)] = {}
    engine._cleanup_zero_faith_saints()
    engine.check_win_conditions()
    if engine.state.winner is not None:
        return

    if was_preparation:
        _remove_unplayed_innate_cards(engine, current)
        engine.state.preparation_turns_done += 1

        pending = runtime_state.setdefault("preparation_end_turn_pending", [])
        if current not in pending:
            pending.append(current)

        if engine.state.preparation_turns_done >= 2:
            runtime_state.pop("preparation_end_turn_pending", None)

            engine._emit_event("on_preparation_complete", current, player=current)

            engine.state.phase = "active"
            engine.state.coin_toss_winner = engine.rng.randint(0, 1)
            engine.state.active_player = engine.state.coin_toss_winner
            engine.state.turn_number = 1
            engine.state.log(
                f"Fine preparazione: lancio moneta -> inizia {engine.state.players[engine.state.active_player].name}."
            )
            set_phase(engine, "setup")
            refresh_player_flags(engine)
            engine._reset_effect_usage_this_turn()
            engine._reset_turn_once_markers_this_turn()
            return

        engine.state.active_player = 1 - engine.state.active_player
        set_phase(engine, "setup")
        refresh_player_flags(engine)
        engine._reset_effect_usage_this_turn()
        engine._reset_turn_once_markers_this_turn()
        return

    double_turns = engine.state.flags.setdefault("double_cost_turns", {"0": 0, "1": 0})
    key = str(engine.state.active_player)
    if int(double_turns.get(key, 0)) > 0:
        double_turns[key] = int(double_turns[key]) - 1

    engine.state.active_player = 1 - engine.state.active_player
    engine.state.turn_number += 1
    set_phase(engine, "setup")
    refresh_player_flags(engine)
    engine._reset_effect_usage_this_turn()
    engine._reset_turn_once_markers_this_turn()
