from __future__ import annotations

import random
import re
import unicodedata
from pathlib import Path
from typing import Callable, Optional

from holywar.core import card_play as card_play_ops
from holywar.core import combat as combat_ops
from holywar.core import destruction as destruction_ops
from holywar.core import query_helpers as query_ops
from holywar.core import turn_flow as turn_flow_ops
from holywar.core import zones as zone_ops
from holywar.core.results import ActionResult
from holywar.core.state import ATTACK_SLOTS, CardInstance, GameState, PlayerState
from holywar.data.deck_builder import build_premade_deck
from holywar.data.models import CardDefinition
from holywar.effects.library import resolve_activated_effect
from holywar.effects.runtime import runtime_cards
from holywar.effects.state_flags import ensure_runtime_state, refresh_player_flags
from holywar.scripting_api import RuleAPI


# Normalizes text so card comparisons stay accent-insensitive and consistent.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


class GameEngine:
    # Initializes the engine with a game state and runtime bookkeeping.
    def __init__(self, state: GameState, seed: int | None = None):
        self.state = state
        self.rng = random.Random(seed)
        self.choose_battle_survival_from_graveyard: Optional[
            Callable[[int, str, list[str]], Optional[str]]
        ] = None
        self.choose_auto_play_slot_from_draw: Optional[
            Callable[[int, str, list[str]], Optional[str]]
        ] = None
        self.choose_summon_slot: Optional[
            Callable[[int, str, list[str]], Optional[str]]
        ] = None
        self.choose_auto_play_drawn_card: Optional[
            Callable[[int, str], bool]
        ] = None
        self._bootstrap_runtime_bindings()
        ensure_runtime_state(self)
        refresh_player_flags(self)

    # Rebinds runtime triggers for every permanent already present in the match state.
    def _bootstrap_runtime_bindings(self) -> None:
        runtime_cards.ensure_all_cards_migrated(self)
        for controller_idx in (0, 1):
            player = self.state.players[controller_idx]
            for uid in player.attack + player.defense + player.artifacts:
                if uid is not None:
                    runtime_cards.on_enter_bind_triggers(self, controller_idx, uid)
            if player.building is not None:
                runtime_cards.on_enter_bind_triggers(self, controller_idx, player.building)
        active_innate = self.state.flags.get("innate_active_uids", {})
        for controller_idx in (0, 1):
            for uid in list(active_innate.get(str(controller_idx), []) or []):
                if uid in self.state.instances:
                    runtime_cards.on_enter_bind_triggers(self, controller_idx, uid)

    # Builds the scripting API wrapper for the selected controller.
    def rules_api(self, controller_idx: int) -> RuleAPI:
        return RuleAPI(self, controller_idx)

    # Clears temporary runtime state when a card leaves the field.
    def _reset_card_runtime_state(self, uid: str) -> None:
        if uid not in self.state.instances:
            return
        inst = self.state.instances[uid]

        # Restore the printed Faith value when the card leaves the field.
        inst.current_faith = inst.definition.faith if inst.definition.faith is not None else None

        # Clear temporary buffs, debuffs, and runtime-only markers.
        inst.blessed = []
        inst.cursed = []

        # Cards outside the field should not keep per-turn usage state.
        inst.exhausted = False

    # Dispatches a gameplay event to the scripting runtime and aliases.
    def _emit_event(self, event: str, actor_idx: int, **payload) -> None:
        
        if event == "on_card_sent_to_graveyard":
            card_uid = str(payload.get("card", "")).strip()
            from_zone = str(payload.get("from_zone", "")).strip().lower()
            if card_uid in self.state.instances and from_zone in {"hand", "attack", "defense", "field"}:
                inst = self.state.instances[card_uid]
                if _norm(inst.definition.card_type) in {"santo", "token"}:
                    counts = self.state.flags.setdefault("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})
                    owner_key = str(inst.owner)
                    counts[owner_key] = int(counts.get(owner_key, 0)) + 1
        self.rules_api(actor_idx).emit(event, actor_idx=actor_idx, **payload)
        # Alias English/Italian spellings used by scripted effects.
        if "relicario" in event:
            self.rules_api(actor_idx).emit(event.replace("relicario", "reliquiary"), actor_idx=actor_idx, **payload)
        elif "reliquiary" in event:
            self.rules_api(actor_idx).emit(event.replace("reliquiary", "relicario"), actor_idx=actor_idx, **payload)
        if event in {
            "on_enter_field",
            "on_summoned_from_hand",
            "on_token_summoned",
            "on_card_sent_to_graveyard",
            "on_card_excommunicated",
            "on_card_drawn",
        }:
            runtime_cards.refresh_conditional_faith_bonuses(self, 0)
            runtime_cards.refresh_conditional_faith_bonuses(self, 1)

    # Returns the current zone string for a card uid owned by a player.
    def _locate_uid_zone(self, owner_idx: int, uid: str) -> str:
        return zone_ops.locate_uid_zone(self, owner_idx, uid)

    def _describe_selected_target(self, target: str | None) -> str:
        raw = str(target or "").strip()
        if not raw:
            return ""
        # Skip noise for ordinary board placement tokens.
        if raw.lower() in {"a1", "a2", "a3", "d1", "d2", "d3", "r1", "r2", "r3", "r4", "b"}:
            return ""
        uid_hits = re.findall(r"c\d{5}", raw)
        if not uid_hits:
            return raw
        names: list[str] = []
        for uid in uid_hits:
            inst = self.state.instances.get(uid)
            if inst is None:
                continue
            names.append(inst.definition.name)
        if not names:
            return raw
        return f"{raw} ({', '.join(dict.fromkeys(names))})"

    def _clean_effect_outcome(self, source_name: str, message: str | None) -> str:
        text = str(message or "").strip()
        if not text:
            return ""
        prefix = f"{source_name}:"
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
        text = text.replace("effetto risolto via script.", "Effetto risolto.")
        text = text.replace("effetto di ingresso risolto via script.", "Effetto di ingresso risolto.")
        text = text.replace("effetto attivato via script.", "Effetto attivato.")
        text = text.replace("Carta giocata.", "").strip()
        text = text.strip(" .")
        low = text.lower()
        if low in {
            "effetto risolto",
            "effetto attivato",
            "effetto di ingresso risolto",
            "nessun effetto scriptato",
            "nessun effetto all'ingresso",
            "nessun effetto attivabile",
        }:
            return ""
        return text

    # Builds a brand-new game state, decks, and initial hands.
    @staticmethod
    def create_new(
        cards: list[CardDefinition],
        p1_name: str,
        p2_name: str,
        p1_expansion: str,
        p2_expansion: str,
        p1_premade_deck_id: str | None = None,
        p2_premade_deck_id: str | None = None,
        seed: int | None = None,
    ) -> "GameEngine":
        rng = random.Random(seed)
        instance_counter = 0
        instances: dict[str, CardInstance] = {}

        # Generates unique runtime ids for every card instance created for the match.
        def make_uid() -> str:
            nonlocal instance_counter
            instance_counter += 1
            return f"c{instance_counter:05d}"

        # Clones a card definition into a mutable in-match card instance.
        def copy_card(card_def: CardDefinition, owner: int) -> str:
            uid = make_uid()
            card_copy = CardDefinition.from_dict(card_def.to_dict())
            faith_value = card_copy.faith if card_copy.faith is not None else None
            instances[uid] = CardInstance(
                uid=uid,
                definition=card_copy,
                owner=owner,
                current_faith=faith_value,
            )
            return uid

        deck_warnings: list[str] = []

        # Builds and shuffles the main deck and white deck for one player.
        def build_decks(owner: int, expansion: str, premade_deck_id: str | None) -> tuple[list[str], list[str], list[str]]:
            if not premade_deck_id:
                raise ValueError(f"Nessun premade deck selezionato per {expansion}.")
            premade = build_premade_deck(cards, premade_deck_id)
            built = premade.deck
            deck_warnings.extend(premade.warnings)
            deck: list[str] = []
            white: list[str] = []
            innate: list[str] = []
            for cdef in built.main_deck:
                deck.append(copy_card(cdef, owner))
            for cdef in built.white_deck:
                white.append(copy_card(cdef, owner))
            for cdef in built.innate_deck:
                innate.append(copy_card(cdef, owner))
            rng.shuffle(deck)
            rng.shuffle(white)
            return deck, white, innate

        p1_deck, p1_white, p1_innate = build_decks(0, p1_expansion, p1_premade_deck_id)
        p2_deck, p2_white, p2_innate = build_decks(1, p2_expansion, p2_premade_deck_id)

        # Initializes the player states with their names, decks, and empty fields.
        p1 = PlayerState.empty(p1_name)
        p1.deck = p1_deck
        p1.white_deck = p1_white
        p2 = PlayerState.empty(p2_name)
        p2.deck = p2_deck
        p2.white_deck = p2_white
        state = GameState(
            players=[p1, p2],
            instances=instances,
            active_player=0,
            turn_number=0,
            phase="preparation",
            preparation_turns_done=0,
            flags={
                "attack_count": {"0": 0, "1": 0},
                "spore_pending": {"0": False, "1": False},
                "double_cost_turns": {"0": 0, "1": 0},
                "saga_bonus": {"0": 0, "1": 0},
                "activated_turn": {},
                "attack_shield_turn": {},
                "spent_inspiration_turn": {"0": 0, "1": 0},
                "bonus_inspiration_next_turn": {"0": 0, "1": 0},
                "counter_spell_ready": {"0": 0, "1": 0},
                "cards_drawn_this_turn": {"0": [], "1": []},
                "innate_pending_setup": {"0": list(p1_innate), "1": list(p2_innate)},
                "innate_active_uids": {"0": [], "1": []},
                "innate_removed_uids": {"0": [], "1": []},
                "preparation_non_innate_played": {"0": False, "1": False},
            },
        )
        engine = GameEngine(state, seed=seed)
        runtime_cards.ensure_all_cards_migrated(engine)
        engine.initial_setup_draw()
        for w in deck_warnings:
            engine.state.log(f"[WARN DECK] {w}")
        return engine

    # Draws the starting hands at the beginning of a new match.
    def initial_setup_draw(self) -> None:
        turn_flow_ops.initial_setup_draw(self)

    # Draws up to the requested number of cards for the selected player.
    def draw_cards(self, player_idx: int, amount: int) -> int:
        return turn_flow_ops.draw_cards(self, player_idx, amount)

    # Continues a multi-card draw that was paused by a mandatory runtime choice.
    def resume_pending_draws(self) -> None:
        turn_flow_ops.resume_pending_draws(self)

    # Plays a card from hand through the main gameplay entry point.
    def play_card(self, player_idx: int, hand_index: int, target: str | None = None) -> ActionResult:
        player = self.state.players[player_idx]
        card_name = "Carta sconosciuta"
        if 0 <= hand_index < len(player.hand):
            uid = player.hand[hand_index]
            inst = self.state.instances.get(uid)
            if inst is not None:
                card_name = inst.definition.name
        self.state.log(f"{player.name} gioca {card_name}.")
        selected_target = self._describe_selected_target(target)
        if selected_target:
            self.state.log(f"{card_name}: bersaglio selezionato -> {selected_target}.")
        result = card_play_ops.play_card(self, player_idx, hand_index, target)
        if result.ok:
            outcome = self._clean_effect_outcome(card_name, result.message)
            if outcome:
                self.state.log(f"{card_name}: effetto risolto -> {outcome}.")
        else:
            reason = str(result.message or "").strip() or "Azione non valida."
            self.state.log(f"{card_name}: giocata fallita. {reason}")
        return result

    # Returns every saint or token the player currently controls on the field.
    def all_saints_on_field(self, player_idx: int) -> list[str]:
        return query_ops.all_saints_on_field(self, player_idx)

    # Returns only the saints or tokens currently in the player's attack row.
    def all_attack_saints(self, player_idx: int) -> list[str]:
        return query_ops.all_attack_saints(self, player_idx)

    # Checks whether the player controls a named artifact.
    def _has_artifact(self, player_idx: int, name: str) -> bool:
        return query_ops.has_artifact(self, player_idx, name)

    # Counts how many copies of a named artifact the player controls.
    def _count_artifact(self, player_idx: int, name: str) -> int:
        return query_ops.count_artifact(self, player_idx, name)

    # Checks whether the player controls a named building.
    def _has_building(self, player_idx: int, name: str) -> bool:
        return query_ops.has_building(self, player_idx, name)

    # Counts the pyramid artifacts currently on the player's field.
    def _count_pyramids(self, player_idx: int) -> int:
        return query_ops.count_pyramids(self, player_idx)

    # Removes any saints that have reached zero Faith after an effect resolves.
    def _cleanup_zero_faith_saints(self) -> None:
        destruction_ops.cleanup_zero_faith_saints(self)

    # Finds which player currently owns the board slot containing a uid.
    def _find_board_owner_of_uid(self, uid: str) -> int | None:
        return zone_ops.find_board_owner_of_uid(self, uid)

    # Reads the seal count currently stored on Altare dei Sette Sigilli.
    def _get_altare_sigilli(self, player_idx: int) -> int:
        return query_ops.get_altare_sigilli(self, player_idx)

    # Updates the seal count stored on Altare dei Sette Sigilli.
    def _set_altare_sigilli(self, player_idx: int, value: int) -> None:
        query_ops.set_altare_sigilli(self, player_idx, value)

    # Recomputes the Custode dei Sigilli bonus from the current seal count.
    def _refresh_custode_sigilli_bonus(self, player_idx: int) -> None:
        query_ops.refresh_custode_sigilli_bonus(self, player_idx)

    # Computes the final combat strength of a card after all bonuses and penalties.
    def get_effective_strength(self, uid: str) -> int:
        inst = self.state.instances[uid]
        owner = int(inst.owner)
        board_owner = self._find_board_owner_of_uid(uid)
        if board_owner is not None:
            owner = int(board_owner)
        opponent = 1 - owner
        strength = max(0, inst.definition.strength or 0)
        for tag in inst.blessed:
            if tag.startswith("buff_str:"):
                try:
                    strength += int(tag.split(":", 1)[1])
                except ValueError:
                    pass
        zone = self._locate_uid_zone(owner, uid)
        # Apply any auras from friendly artifacts that grant strength to saints, if the card is currently on the field as a saint or token. This iterates through the owner's artifacts and checks for any that grant strength to friendly saints, applying the bonus if the current card is not excluded by the artifact's specific rules. This allows for dynamic strength bonuses from artifacts that can affect multiple saints on the field, while also respecting any exclusions defined by the artifact.
        if _norm(inst.definition.card_type) in {"santo", "token"} and zone in {"attack", "defense"}:
            for a_uid in self.state.players[owner].artifacts:
                if not a_uid:
                    continue
                aura = runtime_cards.get_grants_strength_to_friendly_saints(
                    self.state.instances[a_uid].definition.name
                )
                if aura:
                    excluded = {
                        _norm(name)
                        for name in runtime_cards.get_grants_strength_to_friendly_saints_except_names(
                            self.state.instances[a_uid].definition.name
                        )
                    }
                    if _norm(inst.definition.name) not in excluded:
                        strength += int(aura)
        # Apply any card-specific rules that grant strength bonuses based on the current game state, such as controlling certain artifacts or having specific cards in certain zones, if the card is on the field as a saint or token. This iterates through any defined strength bonus rules for the card and checks the conditions of each rule against the current game state, applying the bonus if the conditions are met. This allows for complex conditional strength bonuses that can depend on various factors in the game state, providing depth and strategic considerations for card interactions.
        for rule in runtime_cards.get_strength_bonus_rules(inst.definition.name):
            artifact_name = str(rule.get("artifact_name", "")).strip()
            if not artifact_name or not self._has_artifact(owner, artifact_name):
                if artifact_name:
                    continue
            required_controller_name = str(rule.get("controller_has_card_with_name", "")).strip()
            if required_controller_name:
                controller_zone = str(rule.get("controller_has_card_zone", "field")).strip().lower() or "field"
                if controller_zone == "field":
                    in_zone = (
                        _norm(required_controller_name)
                        in {
                            _norm(self.state.instances[z_uid].definition.name)
                            for z_uid in (self.state.players[owner].attack + self.state.players[owner].defense + self.state.players[owner].artifacts)
                            if z_uid is not None
                        }
                    ) or (
                        self.state.players[owner].building is not None
                        and _norm(
                            self.state.instances[
                                str(self.state.players[owner].building)
                            ].definition.name
                        )
                        == _norm(required_controller_name)
                    )
                elif controller_zone in {"hand"}:
                    in_zone = any(
                        _norm(self.state.instances[h_uid].definition.name) == _norm(required_controller_name)
                        for h_uid in self.state.players[owner].hand
                    )
                elif controller_zone in {"deck", "relicario"}:
                    in_zone = any(
                        _norm(self.state.instances[d_uid].definition.name) == _norm(required_controller_name)
                        for d_uid in self.state.players[owner].deck
                    )
                elif controller_zone == "graveyard":
                    in_zone = any(
                        _norm(self.state.instances[g_uid].definition.name) == _norm(required_controller_name)
                        for g_uid in self.state.players[owner].graveyard
                    )
                elif controller_zone == "excommunicated":
                    in_zone = any(
                        _norm(self.state.instances[e_uid].definition.name) == _norm(required_controller_name)
                        for e_uid in self.state.players[owner].excommunicated
                    )
                else:
                    in_zone = False
                if not in_zone:
                    continue
            required_name = str(rule.get("if_card_name", "")).strip()
            if required_name and _norm(inst.definition.name) != _norm(required_name):
                continue
            strength += int(rule.get("self_bonus", 0) or 0)
        # Context strength bonuses (e.g. Hun-Came counted bonuses) apply only to saints/tokens on the field.
        if _norm(inst.definition.card_type) in {"santo", "token"} and zone in {"attack", "defense"}:
            strength += runtime_cards.get_context_bonus_amount(
                self,
                owner,
                context="strength",
                amount_mode="flat",
                target_uid=uid,
            )
            strength += runtime_cards.get_context_bonus_amount(
                self,
                owner,
                context="strength",
                amount_mode="per_count_div_floor",
                target_uid=uid,
            )
        sigilli_threshold = runtime_cards.get_sigilli_strength_bonus_threshold(inst.definition.name)
        sigilli_amount = runtime_cards.get_sigilli_strength_bonus_amount(inst.definition.name)
        if sigilli_threshold is not None and sigilli_amount is not None and self._get_altare_sigilli(owner) >= int(sigilli_threshold):
            strength += int(sigilli_amount)
        if _norm(inst.definition.card_type) in {"santo", "token"} and zone in {"attack", "defense"}:
            for a_uid in self.state.players[opponent].artifacts:
                if not a_uid:
                    continue
                enemy_mod = runtime_cards.get_modifies_enemy_saints_strength(
                    self.state.instances[a_uid].definition.name
                )
                if enemy_mod:
                    strength += int(enemy_mod)
        return max(0, strength)

    # Adds Sin to a player and refreshes any derived runtime flags.
    def gain_sin(self, player_idx: int, amount: int) -> None:
        if amount <= 0:
            return
        self.state.players[player_idx].sin += amount
        self._emit_event(
            "on_sin_gained",
            player_idx,
            target_player=int(player_idx),
            amount=int(amount),
        )
        mirror = self.state.flags.setdefault("sin_mirror_once", {"0": 0, "1": 0})
        pending = int(mirror.get(str(player_idx), 0))
        if pending > 0:
            mirror[str(player_idx)] = max(0, pending - 1)
            opp = 1 - int(player_idx)
            self.state.players[opp].sin += int(amount)
            self._emit_event(
                "on_sin_gained",
                opp,
                target_player=int(opp),
                amount=int(amount),
            )
        refresh_player_flags(self)

    # Removes Sin from a player without letting the total go below zero.
    def reduce_sin(self, player_idx: int, amount: int) -> None:
        if amount <= 0:
            return
        p = self.state.players[player_idx]
        before = int(p.sin)
        p.sin = max(0, p.sin - amount)
        removed = max(0, before - int(p.sin))
        if removed > 0:
            self._emit_event(
                "on_sin_removed",
                player_idx,
                target_player=int(player_idx),
                amount=removed,
            )
        refresh_player_flags(self)

    # Destroys a saint or token by uid using the shared destruction flow.
    def destroy_saint_by_uid(
        self,
        owner_idx: int,
        uid: str,
        excommunicate: bool = False,
        cause: str = "effect",
        by_whom: str | None = None,
    ) -> None:
        destruction_ops.destroy_saint_by_uid(
            self,
            owner_idx,
            uid,
            excommunicate=excommunicate,
            cause=cause,
            by_whom=by_whom,
        )

    # Starts the active player's turn and applies all start-of-turn effects.
    def start_turn(self) -> None:
        turn_flow_ops.start_turn(self)

    # Ends the current turn and advances control to the next player.
    def end_turn(self) -> None:
        turn_flow_ops.end_turn(self)

    # Returns the card instance currently stored in a hand slot.
    def card_from_hand(self, player_idx: int, hand_index: int) -> CardInstance | None:
        player = self.state.players[player_idx]
        if hand_index < 0 or hand_index >= len(player.hand):
            return None
        return self.state.instances[player.hand[hand_index]]

    # Validates whether the card can be played in the requested zone and context.
    # Kept on the engine as a delegation layer while the logic now lives in the card-play module.
    def _validate_play_constraints(
        self,
        player_idx: int,
        card: CardInstance,
        target: str | None,
    ) -> tuple[bool, str, int, str | None, int]:
        return card_play_ops.validate_play_constraints(self, player_idx, card, target)

    # Computes the final Inspiration cost after all card-specific modifiers.
    # Kept on the engine to preserve the public API while the logic is delegated.
    def _calculate_play_cost(self, player_idx: int, hand_index: int, card: CardInstance) -> int:
        return card_play_ops.calculate_play_cost(self, player_idx, hand_index, card)

    # Applies the computed cost using temporary Inspiration before the regular pool.
    # Kept on the engine as a thin wrapper around the dedicated card-play module.
    def _spend_inspiration_for_cost(self, player_idx: int, cost: int) -> ActionResult | None:
        return card_play_ops.spend_inspiration_for_cost(self, player_idx, cost)

    # Emits the shared play events that every card uses when leaving the hand.
    # Kept on the engine so existing callers can continue using the same method name.
    def _emit_play_events(self, player_idx: int, uid: str, ctype: str, target: str | None) -> None:
        card_play_ops.emit_play_events(self, player_idx, uid, ctype, target)

    # Handles saint placement, summon side effects, and enter-the-field bonuses.
    # Kept on the engine as a delegation layer while the detailed logic lives elsewhere.
    def _handle_saint_play(
        self,
        player_idx: int,
        place_owner_idx: int,
        uid: str,
        zone: str | None,
        slot: int,
    ) -> ActionResult:
        return card_play_ops.handle_saint_play(self, player_idx, place_owner_idx, uid, zone, slot)

    # Handles artifact placement, replacement rules, and enter effects.
    # Kept on the engine to preserve compatibility while delegating the implementation.
    def _handle_artifact_play(self, player_idx: int, uid: str) -> ActionResult:
        return card_play_ops.handle_artifact_play(self, player_idx, uid)

    # Handles building placement and its immediate enter effect resolution.
    # Kept on the engine as a stable entry point with delegated logic.
    def _handle_building_play(self, player_idx: int, uid: str) -> ActionResult:
        return card_play_ops.handle_building_play(self, player_idx, uid)

    # Resolves quick cards from hand, including counter-spell cancellation and cleanup.
    # Kept on the engine so reactive-play callers do not need to change.
    def _resolve_quick_play_from_hand(self, player_idx: int, uid: str, target: str | None) -> ActionResult:
        return card_play_ops.resolve_quick_play_from_hand(self, player_idx, uid, target)

    # Activates the ability of a card already present on the board.
    def activate_ability(self, player_idx: int, source: str, target: str | None = None) -> ActionResult:
        player = self.state.players[player_idx]
        src_name = str(source)
        if player_idx != self.state.active_player:
            return ActionResult(False, "Puoi attivare abilita solo nel tuo turno.")
        uid = self.resolve_board_uid(player_idx, source)
        if uid is None:
            other_uid = self.resolve_board_uid(1 - player_idx, source)
            if other_uid is not None:
                other_inst = self.state.instances[other_uid]
                other_script = runtime_cards.get_script(other_inst.definition.name)
                if other_script and bool(other_script.can_activate_by_any_player):
                    uid = other_uid
        if uid is None:
            return ActionResult(False, "Sorgente non valida. Usa a1..a3, d1..d3, r1..r4 o b.")
        inst = self.state.instances[uid]
        src_name = inst.definition.name
        self.state.log(f"{player.name} attiva l'effetto di {src_name}.")
        selected_target = self._describe_selected_target(target)
        if selected_target:
            self.state.log(f"{src_name}: bersaglio selezionato -> {selected_target}.")
        if "silenced" in inst.cursed:
            return ActionResult(False, "Questa carta ha i suoi effetti annullati.")
        keep_curses: list[str] = []
        activation_negated = False
        for tag in list(inst.cursed):
            if not isinstance(tag, str) or not tag.startswith("no_activate_until:"):
                keep_curses.append(tag)
                continue
            try:
                until_turn = int(tag.split(":", 1)[1])
            except ValueError:
                continue
            if int(self.state.turn_number) <= until_turn and not activation_negated:
                activation_negated = True
                continue
            if int(self.state.turn_number) <= until_turn:
                keep_curses.append(tag)
        inst.cursed = keep_curses
        if activation_negated:
            return ActionResult(True, f"L'attivazione di {inst.definition.name} e stata annullata.")
        card_type = _norm(inst.definition.card_type)
        is_piaga_blessing_or_curse = card_type in {"benedizione", "maledizione"} and "piaga" in _norm(inst.definition.name)
        if is_piaga_blessing_or_curse and not self.can_activate_once_per_turn(uid):
            return ActionResult(False, f"{inst.definition.name}: effetto non puo essere attivato piu di una volta per turno.")
        if runtime_cards.is_activate_once_per_turn(inst.definition.name) and not self.can_activate_once_per_turn(uid):
            return ActionResult(True, f"{inst.definition.name}: abilita gia usata in questo turno.")
        can_activate, reason = runtime_cards.can_activate(self, player_idx, uid, target=target)
        if not can_activate:
            self.state.log(f"{src_name}: attivazione fallita. {reason or 'Nessun bersaglio valido disponibile per questa abilita.'}")
            return ActionResult(False, reason or "Nessun bersaglio valido disponibile per questa abilita.")
        msg = resolve_activated_effect(self, player_idx, uid, target)
        if is_piaga_blessing_or_curse:
            self.mark_activated_this_turn(uid)
        self._cleanup_zero_faith_saints()
        self.check_win_conditions()
        outcome = self._clean_effect_outcome(src_name, str(msg))
        if outcome:
            self.state.log(f"{src_name}: effetto risolto -> {outcome}.")
        return ActionResult(True, msg)

    # Checks whether a card has already used its once-per-turn activation.
    def can_activate_once_per_turn(self, uid: str) -> bool:
        used = self.state.flags.setdefault("activated_turn", {})
        return int(used.get(uid, -1)) != int(self.state.turn_number)

    # Marks a card as having consumed its activation for the current turn.
    def mark_activated_this_turn(self, uid: str) -> None:
        used = self.state.flags.setdefault("activated_turn", {})
        used[uid] = int(self.state.turn_number)

    # Resolves a reactive blessing, curse, or special quick-play card.
    def quick_play(self, player_idx: int, hand_index: int, target: str | None = None) -> ActionResult:
        return card_play_ops.quick_play(self, player_idx, hand_index, target)

    # Swaps two saints within the active player's attack row.
    def move_attack_positions(self, player_idx: int, from_slot: int, to_slot: int) -> ActionResult:
        if player_idx != self.state.active_player:
            return ActionResult(False, "Movimento disponibile solo nel tuo turno.")
        player = self.state.players[player_idx]
        if not (0 <= from_slot < ATTACK_SLOTS and 0 <= to_slot < ATTACK_SLOTS):
            return ActionResult(False, "Slot non valido.")
        player.attack[from_slot], player.attack[to_slot] = player.attack[to_slot], player.attack[from_slot]
        return ActionResult(True, "Santi in attacco scambiati.")

    # Starts battle-phase bookkeeping when the first attack of the turn is declared.
    def _start_battle_phase_if_needed(self, player_idx: int) -> None:
        combat_ops.start_battle_phase_if_needed(self, player_idx)

    # Validates the attacker-side rules that can stop combat before damage is assigned.
    def _validate_attack_preconditions(
        self,
        player_idx: int,
        defender_idx: int,
        attacker_uid: str,
        attacker: CardInstance,
        target_slot: int | None,
    ) -> ActionResult | None:
        return combat_ops.validate_attack_preconditions(
            self,
            player_idx,
            defender_idx,
            attacker_uid,
            attacker,
            target_slot,
        )

    # Marks the attacker as committed and updates the per-turn attack counter.
    def _mark_attack_committed(self, player_idx: int, attacker: CardInstance, defender_uid: str | None = None) -> None:
        combat_ops.mark_attack_committed(self, player_idx, attacker, defender_uid=defender_uid)

    # Resolves the direct-attack case when the defender has no saints on the board.
    def _resolve_direct_attack(self, player_idx: int, defender_idx: int, attacker_uid: str, attacker: CardInstance) -> ActionResult:
        return combat_ops.resolve_direct_attack(self, player_idx, defender_idx, attacker_uid, attacker)

    # Resolves a targeted combat, including barriers, lethal damage, and retaliation rules.
    def _resolve_targeted_attack(
        self,
        player_idx: int,
        defender_idx: int,
        attacker_uid: str,
        attacker: CardInstance,
        target_slot: int | None = None,
    ) -> ActionResult:
        return combat_ops.resolve_targeted_attack(
            self,
            player_idx,
            defender_idx,
            attacker_uid,
            attacker,
            target_slot,
        )

    # Declares and resolves an attack through the combat module.
    def attack(self, player_idx: int, from_slot: int, target_slot: int | None) -> ActionResult:
        attacker_name = "Carta sconosciuta"
        player = self.state.players[player_idx]
        if 0 <= from_slot < len(player.attack):
            uid = player.attack[from_slot]
            if uid in self.state.instances:
                attacker_name = self.state.instances[uid].definition.name
        if target_slot is None:
            target_desc = "attacco diretto"
        else:
            target_desc = f"bersaglio {target_slot + 1}"
        self.state.log(f"{player.name} dichiara attacco con {attacker_name} ({target_desc}).")
        result = combat_ops.attack(self, player_idx, from_slot, target_slot)
        if result.ok:
            self.state.log(f"Attacco di {attacker_name}: {result.message}")
        else:
            self.state.log(f"Attacco di {attacker_name} fallito: {result.message}")
        return result

    # Destroys the saint occupying a specific attack slot.
    def _kill_saint(self, owner_idx: int, attack_slot: int) -> None:
        player = self.state.players[owner_idx]
        uid = player.attack[attack_slot]
        if uid is None:
            return
        self.destroy_saint_by_uid(self.state.instances[uid].owner, uid, cause="battle")

    # Moves a card into the graveyard using the shared zone-transition rules.
    def send_to_graveyard(
        self,
        owner_idx: int,
        uid: str,
        token_to_white: bool = False,
        from_zone_override: str | None = None,
    ) -> None:
        zone_ops.send_to_graveyard(
            self,
            owner_idx,
            uid,
            token_to_white=token_to_white,
            from_zone_override=from_zone_override,
        )

    # Moves a card into the excommunication zone through the zone module.
    def excommunicate_card(self, owner_idx: int, uid: str, from_zone_override: str | None = None) -> None:
        zone_ops.excommunicate_card(self, owner_idx, uid, from_zone_override=from_zone_override)

    # Moves an absolved card from excommunication back into the graveyard.
    def absolve_card_to_graveyard(self, owner_idx: int, uid: str) -> None:
        zone_ops.absolve_card_to_graveyard(self, owner_idx, uid)

    # Removes a uid from every board slot owned by the given player.
    def _remove_from_board(self, player: PlayerState, uid: str) -> None:
        zone_ops.remove_from_board(self, player, uid)

    # Parses a compact board target like a2 or d1 into zone and slot data.
    def _parse_zone_target(self, target: str | None) -> tuple[str | None, int]:
        return query_ops.parse_zone_target(target)

    # Returns the first available empty slot from a board row.
    def _first_open(self, slots: list[str | None]) -> int | None:
        return query_ops.first_open(slots)

    # Consumes a one-shot barrier blessing when the defender has one.
    def _consume_barrier(self, defender: CardInstance) -> str | None:
        return query_ops.consume_barrier(self, defender)

    # Applies static damage prevention rules before damage is committed.
    def _apply_damage_mitigation(self, target_owner_idx: int, damage: int, target_uid: str | None = None) -> int:
        return query_ops.apply_damage_mitigation(self, target_owner_idx, damage, target_uid=target_uid)

    # Checks whether a temporary attack lock still prevents this attacker from acting.
    def _is_attacker_blocked_this_turn(self, attacker: CardInstance) -> bool:
        return query_ops.is_attacker_blocked_this_turn(self, attacker)

    # Consumes the defender's once-per-turn attack shield if it is active.
    def _consume_attack_shield(self, defender_idx: int) -> bool:
        return query_ops.consume_attack_shield(self, defender_idx)

    # Consumes a stored counter-spell charge from the opposing player.
    def _consume_counter_spell(self, caster_idx: int) -> bool:
        return query_ops.consume_counter_spell(self, caster_idx)

    # Resolves a board target string into a saint instance.
    def resolve_target_saint(self, player_idx: int, target: str | None) -> CardInstance | None:
        return query_ops.resolve_target_saint(self, player_idx, target)

    # Resolves a board target string into an artifact or building uid.
    def resolve_target_artifact_or_building(self, player_idx: int, target: str | None) -> str | None:
        return query_ops.resolve_target_artifact_or_building(self, player_idx, target)

    # Resolves any supported board source string into the corresponding uid.
    def resolve_board_uid(self, player_idx: int, source: str | None) -> str | None:
        return query_ops.resolve_board_uid(self, player_idx, source)

    # Removes a card from the board without applying any Sin consequences.
    def remove_from_board_no_sin(self, owner_idx: int, uid: str) -> None:
        zone_ops.remove_from_board_no_sin(self, owner_idx, uid)

    # Applies the post-combat burn effect from Fiamma Primordiale.
    def _apply_fiamma_primordiale_after_attack(self, attacker_idx: int, defender_idx: int, attacker_uid: str) -> None:
        combat_ops.apply_fiamma_primordiale_after_attack(self, attacker_idx, defender_idx, attacker_uid)

    # Destroys any card type using the shared destruction logic.
    def destroy_any_card(self, owner_idx: int, uid: str) -> None:
        destruction_ops.destroy_any_card(self, owner_idx, uid)

    # Finds a matching card by name inside the player's deck.
    def find_card_uid_in_deck(self, player_idx: int, name: str) -> str | None:
        return query_ops.find_card_uid_in_deck(self, player_idx, name)

    # Finds a matching card by name inside the player's graveyard.
    def find_card_uid_in_graveyard(self, player_idx: int, name: str) -> str | None:
        return query_ops.find_card_uid_in_graveyard(self, player_idx, name)

    # Moves a specific deck card into the player's hand if possible.
    def move_deck_card_to_hand(self, player_idx: int, uid: str) -> bool:
        return zone_ops.move_deck_card_to_hand(self, player_idx, uid)

    # Moves a specific graveyard card back into the player's hand.
    def move_graveyard_card_to_hand(self, player_idx: int, uid: str) -> bool:
        return zone_ops.move_graveyard_card_to_hand(self, player_idx, uid)

    # Returns a card from the board to hand while preserving ownership rules.
    def move_board_card_to_hand(self, owner_idx: int, uid: str) -> bool:
        return zone_ops.move_board_card_to_hand(self, owner_idx, uid)

    # Places a graveyard card on the bottom of the deck.
    def move_graveyard_card_to_deck_bottom(self, player_idx: int, uid: str) -> bool:
        return zone_ops.move_graveyard_card_to_deck_bottom(self, player_idx, uid)

    # Clears the per-turn activated-effect usage registry.
    def _reset_effect_usage_this_turn(self) -> None:
        self.state.flags["effect_usage_per_turn"] = {}

    # Removes all once-per-turn markers so the next turn starts cleanly.
    def _reset_turn_once_markers_this_turn(self) -> None:
        marker_prefix = "once_per_turn:"
        for inst in self.state.instances.values():
            keep = [tag for tag in inst.blessed if not tag.startswith(marker_prefix)]
            if len(keep) != len(inst.blessed):
                inst.blessed = keep

    # Places a card uid directly into a specific board zone and slot.
    def place_card_from_uid(self, player_idx: int, uid: str, zone: str, slot: int) -> bool:
        return zone_ops.place_card_from_uid(self, player_idx, uid, zone, slot)

    # Returns the currently empty slot indexes for a board zone.
    def empty_slots(self, player_idx: int, zone: str) -> list[int]:
        return zone_ops.empty_slots(self, player_idx, zone)

    # Lists the expansions represented in the current match state.
    def available_expansions(self) -> list[str]:
        return query_ops.available_expansions(self)

    # Checks whether a player has met one of the match-ending conditions.
    def check_win_conditions(self) -> None:
        for idx, player in enumerate(self.state.players):
            if player.sin >= 100:
                self.state.winner = 1 - idx
                self.state.log(f"{player.name} ha raggiunto 100 Peccato. Vince {self.state.players[self.state.winner].name}.")
                return
            if not player.deck and not player.hand and all(slot is None for slot in player.attack + player.defense):
                self.state.winner = 1 - idx
                self.state.log(f"{player.name} ha esaurito tutte le carte giocabili. Vince {self.state.players[self.state.winner].name}.")
                return

    # Exports the accumulated match log to a text file.
    def export_logs(self, path: str | Path) -> Path:
        out = Path(path)
        out.write_text("\n".join(self.state.logs), encoding="utf-8")
        return out
