from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


EventHandler = Callable[["RuleEventContext"], None]

# Context passed to event handlers when a rule event is emitted.
@dataclass(slots=True)
class RuleEventContext:
    engine: GameEngine
    player_idx: int
    event: str
    payload: dict[str, Any]

# Simple pub-sub system for rule events. Each event is identified by a string, and handlers are functions that take a RuleEventContext.
class RuleEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = {}

    def subscribe(self, event: str, handler: EventHandler) -> None:
        handlers = self._subs.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    # Unsubscribe a handler from an event. If the handler is not subscribed, do nothing.
    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        handlers = self._subs.get(event)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return
        if not handlers:
            self._subs.pop(event, None)

    # Emit an event, calling all subscribed handlers with the given context. Handlers are called in the order they were subscribed. If a handler is unsubscribed while events are being emitted, it will not be called for the current emission.
    def emit(self, ctx: RuleEventContext) -> None:
        for cb in tuple(self._subs.get(ctx.event, [])):
            cb(ctx)

# List of all possible rule events that can be emitted. This is not strictly necessary, but can be useful for validation and auto-completion.
class RuleEvents:
    ALL = [
        "on_card_played",
        "on_blessing_played",
        "on_curse_played",
        "on_seal_card_played",
        "on_card_drawn",
        "on_opponent_draws",
        "on_card_discarded",
        "on_card_sent_to_graveyard",
        "on_card_sent_to_relicario",
        "on_card_excommunicated",
        "on_card_returned_to_relicario",
        "on_card_shuffled_into_relicario",
        "on_attack_declared",
        "on_this_card_attacks",
        "on_this_card_deals_damage",
        "on_this_card_receives_damage",
        "on_this_card_kills_in_battle",
        "on_saint_defeated_in_battle",
        "on_saint_destroyed_by_effect",
        "on_saint_defeated_or_destroyed",
        "on_enter_field",
        "on_summoned_from_hand",
        "on_summoned_from_relicario",
        "on_summoned_from_graveyard",
        "on_summoned_from_excommunicated",
        "on_summoned_by_effect",
        "on_special_summon_by_effect",
        "on_token_summoned",
        "on_opponent_saint_enters_field",
        "on_this_card_leaves_field",
        "on_this_card_destroyed",
        "on_card_destroyed_on_field",
        "on_all_saints_destroyed",
        "on_turn_start",
        "on_opponent_turn_start",
        "on_my_turn_start",
        "on_turn_end",
        "on_opponent_turn_end",
        "on_my_turn_end",
        "on_draw_phase_start",
        "on_draw_phase_end",
        "on_battle_phase_start",
        "on_battle_phase_end",
        "on_main_phase_start",
        "on_main_phase_end",
        "before_draw_phase",
        "after_card_drawn_from_deck",
        "on_faith_changed",
        "on_strength_changed",
        "on_sin_changed",
        "on_inspiration_changed",
        "on_counter_added",
        "on_counter_removed",
        "on_seal_counter_added",
        "on_seal_counter_removed",
        "on_player_pays_inspiration",
        "on_player_receives_sin",
        "on_player_removes_sin",
        "on_player_discards_hand",
        "on_player_reveals_card",
        "on_player_searches_relicario",
        "on_player_shuffles_relicario",
        "on_player_mills_cards",
        "on_player_returns_from_graveyard_to_relicario",
        "on_player_excommunicates_card",
        "on_player_equips_card",
        "on_player_unequips_card",
        "on_player_sacrifices_saint",
    ]

# List of all functions that can be called from card scripts. This is used for validation and auto-completion, and also to prevent calling undefined functions.
DECLARED_FUNCTIONS = {
    # Condizioni / query / target / azioni: full surface requested.
    "controller_has",
    "opponent_has",
    "field_has_saint_with_name",
    "field_has_token",
    "controller_has_altar_with_seal_count",
    "opponent_has_no_saints_in_defense",
    "opponent_has_exactly_n_saints",
    "both_players_control_at_least_one_building",
    "my_building_zone_is_occupied",
    "I_control_less_saints_than_opponent",
    "in_hand",
    "in_graveyard",
    "in_relicario",
    "in_excommunicated",
    "hand_contains_building",
    "graveyard_contains_card_name",
    "relicario_contains_card_name",
    "excommunicated_count",
    "can_excommunicate_from_graveyard",
    "has_discarded_this_turn",
    "has_sent_to_graveyard_from_hand_or_field_this_turn",
    "this_card_has_seal_count",
    "target_has_croci",
    "target_has_faith",
    "target_has_strength",
    "target_has_initial_faith",
    "target_is_damaged",
    "target_is_in_attack_position",
    "target_is_in_defense_position",
    "target_is_equipped_with_blessing",
    "target_has_expansion",
    "card_is_tree",
    "card_is_saint",
    "card_is_blessing",
    "card_is_curse",
    "card_is_artifact",
    "card_is_building",
    "card_is_token",
    "my_remaining_inspiration",
    "opponent_sin",
    "both_players_sin_less_than",
    "both_players_sin_more_than",
    "I_have_spent_more_than_inspiration_this_turn",
    "I_have_no_saints",
    "I_have_not_attacked_this_turn",
    "this_card_was_drawn_by_effect",
    "this_card_was_sent_from_hand_to_graveyard_by_effect",
    "three_or_more_my_saints_sent_from_hand_or_field_to_graveyard_this_turn",
    "this_turn_phase_is",
    "it_is_my_first_turn",
    "can_play_without_inspiration_cost_if",
    "can_play_by_spending_all_remaining_inspiration",
    "can_play_only_if",
    "can_play_only_if_altar_has_seal_count",
    "can_play_only_if_opponent_controls_n_saints",
    "can_play_only_if_three_saints_sent_this_turn",
    "can_play_only_if_discard_n_cards_from_hand",
    "can_play_only_if_I_control_less_saints_than_opponent",
    "can_play_only_if_opponent_sin_less_or_equal",
    "can_play_only_if_this_card_was_sent_from_hand_to_graveyard_by_effect",
    "can_play_by_sacrificing_specific_card_from_field",
    "can_play_only_if_both_players_sin_less_than",
    "can_play_only_if_both_players_sin_more_than",
    "can_be_summoned_only_by_effect_of",
    "can_be_included_only_in_relicario_all_with_expansion",
    "max_copies_in_relicario",
    "add_seal_counter",
    "remove_seal_counter",
    "add_generic_counter",
    "remove_generic_counter",
    "set_seal_counter",
    "increase_faith",
    "decrease_faith",
    "set_faith_to",
    "reset_faith_to_initial",
    "double_faith",
    "increase_strength",
    "decrease_strength",
    "set_strength",
    "half_strength_round_down",
    "inflict_sin",
    "remove_sin",
    "add_inspiration",
    "pay_inspiration",
    "set_inspiration",
    "double_sin_inflicted",
    "draw_cards",
    "draw_card_and_if_saint_excommunicate_it",
    "draw_card_if_not_saint_put_in_graveyard_bottom",
    "mill_cards",
    "discard_from_hand",
    "discard_entire_hand",
    "search_relicario",
    "search_graveyard",
    "search_excommunicated",
    "shuffle_relicario",
    "look_at_top_cards",
    "look_at_bottom_card",
    "return_card_from_graveyard_to_relicario",
    "return_card_from_excommunicated_to_relicario",
    "return_all_cards_from_graveyard_to_relicario",
    "return_all_cards_from_excommunicated_to_relicario",
    "move_card_from_graveyard_to_hand",
    "move_card_from_excommunicated_to_hand",
    "move_card_from_graveyard_to_field",
    "move_card_from_excommunicated_to_field",
    "summon_from_hand",
    "summon_from_relicario",
    "summon_from_graveyard",
    "summon_from_excommunicated",
    "summon_token",
    "summon_token_with_effects",
    "summon_multiple_tokens",
    "special_summon_by_effect",
    "destroy_card",
    "destroy_all_saints_on_field",
    "destroy_all_saints_except_targets",
    "destroy_all_artifacts_and_buildings_on_field",
    "excommunicate_card",
    "excommunicate_top_cards_from_relicario",
    "send_from_field_to_graveyard",
    "send_from_hand_to_graveyard",
    "send_from_relicario_to_graveyard",
    "take_control_of_saint",
    "return_control_to_owner",
    "change_position",
    "swap_positions",
    "equip_card",
    "unequip_card",
    "destroy_equipment",
    "prevent_first_attack_on_target",
    "negate_effect_activation",
    "negate_card_destruction",
    "negate_first_attack_received_this_turn",
    "negate_blessing_or_curse_activation",
    "make_card_immune_to_card_type",
    "prevent_damage_below_threshold",
    "skip_next_draw_phase",
    "add_extra_draw_on_draw_phase",
    "allow_extra_attack_this_turn",
    "prevent_attacks_this_turn",
    "prevent_specific_card_from_attacking",
    "prevent_all_attacks_until_any_player_draws",
    "reduce_inspiration_cost_for_building_by",
    "double_inspiration_cost_for_opponent_next_turn",
    "make_one_artifact_slot_unusable",
    "win_the_game",
    "target_saint_on_field",
    "target_saint_in_graveyard",
    "target_saint_in_relicario",
    "target_saint_in_excommunicated",
    "target_saint_opponent_field",
    "target_artifact_on_field",
    "target_building_on_field",
    "target_blessing_or_curse_in_relicario",
    "target_token_on_field",
    "target_equipment_on_field",
    "target_up_to_n_cards",
    "target_card_with_croci",
    "target_card_that_would_destroy_this_card",
    "get_current_faith",
    "get_initial_faith",
    "get_current_strength",
    "get_croci",
    "get_seal_count",
    "get_remaining_inspiration",
    "get_current_sin",
    "count_saints_on_field",
    "count_tokens_on_field",
    "count_cards_in_hand",
    "count_cards_in_graveyard",
    "count_cards_in_relicario",
    "count_cards_in_excommunicated",
    "count_cards_sent_from_hand_or_field_to_graveyard_this_turn",
    "is_card_type",
    "at_end_of_turn_if",
    "before_draw_phase_forced_effect",
    "next_opponent_turn_effect",
    "after_resolution_compare_and_reward",
    "after_effect_self_excommunicate",
    "if_both_on_field",
    "if_all_three_on_field",
    "cumulative_effect_based_on_count",
    "memory_stack_per_target",
    "linked_destruction",
    "counter_per_successful_attack_this_turn",
    "on_about_to_be_destroyed_by_effect",
    "negate_effect_on_stack",
    "spell_speed_4",
    "redirect_from_graveyard_to_hand",
    "on_destroy_by_this_effect",
    "override_sin_generation",
    "merge_zones",
    "redirect_zone_operations",
    "peek_and_return_order_preserved",
    "peek_top_and_bottom",
    "chain_self_from_topdeck_condition",
    "dynamic_inspiration_cost",
    "faith_set_by_inspiration_paid",
    "draw_x_take_sin_per_card",
    "can_attack_only_if",
    "prevent_all_attacks_this_turn",
    "deck_building_restriction",
    "add_card_type",
    "buff_by_expansion",
    "check_win_condition_on_empty_relicario",
    "return_all_excommunicated_to_relicario",
}

# Utility functions for normalizing text and parsing cross values. These are used internally by the API methods to allow for more flexible input formats (e.g., "Croce Bianca" or "White" both count as 11 crosses).
def _norm(txt: str) -> str:
    return (txt or "").strip().lower()

# Normalize a string by removing accents and converting to lowercase. This is used for more flexible matching of card names and types.
def _norm_ascii(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()

# Parse a cross value from a string. If the string is "white" or "croce bianca" (case-insensitive, accents ignored), return 11. Otherwise, try to parse it as a number and return the integer value. If parsing fails or the string is empty, return None.
def _cross_value(crosses: str | None) -> int | None:
    txt = _norm_ascii(crosses or "")
    if not txt:
        return None
    if txt in {"white", "croce bianca"}:
        return 11
    try:
        return int(float(txt))
    except ValueError:
        return None

# The main API class that will be passed to card scripts. It provides methods for subscribing to events, emitting events, querying the game state, and performing actions. Each method corresponds to a possible function that can be called from card scripts, and they interact with the game engine and state to implement the desired behavior.
class RuleAPI:
    def __init__(self, engine: GameEngine, controller_idx: int) -> None:
        self.engine = engine
        self.state = engine.state
        self.controller_idx = controller_idx
        if not hasattr(engine, "_rule_event_bus"):
            engine._rule_event_bus = RuleEventBus()  # type: ignore[attr-defined]
        if not hasattr(engine, "_script_call_stats"):
            engine._script_call_stats = {}  # type: ignore[attr-defined]
        self.bus: RuleEventBus = engine._rule_event_bus  # type: ignore[attr-defined]
        self._stats: dict[str, int] = engine._script_call_stats  # type: ignore[attr-defined]

    # Methods for event subscription and emission. These allow card scripts to react to game events and also to emit custom events that other scripts can listen to.
    def subscribe(self, event: str, handler: EventHandler) -> None:
        self.bus.subscribe(event, handler)

    # Unsubscribe a handler from an event. If the handler is not subscribed, do nothing.
    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        self.bus.unsubscribe(event, handler)

    # Emit an event with the given name and payload. The payload is passed as keyword arguments and will be included in the RuleEventContext that handlers receive. Handlers subscribed to this event will be called with the context.
    def emit(self, event: str, **payload: Any) -> None:
        self.bus.emit(RuleEventContext(self.engine, self.controller_idx, event, payload))

    # Check if a function name is declared in the API. This can be used for validation before attempting to call a function from a card script.
    def has_function(self, name: str) -> bool:
        return name in DECLARED_FUNCTIONS

    # Internal helper methods for iterating over card UIDs in different zones and finding the controller of a card by its UID. These are used by the public API methods to implement their functionality.
    def _iter_uids(self, player_idx: int, zone: str) -> list[str]:
        p = self.state.players[player_idx]
        z = _norm(zone)
        # If Promessa dell'oltretomba is active for this player, deck and graveyard are the same logical zone
        promise_state = dict(getattr(self.engine.state, "flags", {}).get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
        merged = bool(promise_state.get(str(player_idx), False))
        if z in {"relicario", "deck"}:
            if merged:
                # include both deck and graveyard when merged (deck first)
                return list(p.deck) + [uid for uid in p.graveyard if uid not in p.deck]
            return list(p.deck)
        if z == "graveyard":
            if merged:
                # include both graveyard and deck when merged (graveyard first)
                return list(p.graveyard) + [uid for uid in p.deck if uid not in p.graveyard]
            return list(p.graveyard)
        if z == "excommunicated":
            return list(p.excommunicated)
        if z == "hand":
            return list(p.hand)
        if z == "field":
            out: list[str] = []
            for uid in p.attack + p.defense + p.artifacts:
                if uid:
                    out.append(uid)
            if p.building:
                out.append(p.building)
            return out
        return []

    # Find the controller and zone of a card by its UID. This is used for operations that need to know who controls a card and where it is located (e.g., sending a card from the field to the graveyard).
    def _find_controller_of_uid(self, uid: str) -> tuple[int, str] | None:
        for idx in (0, 1):
            p = self.state.players[idx]
            if uid in p.hand:
                return idx, "hand"
            # If Promessa dell'oltretomba is active for this player, consider deck cards as graveyard for queries
            promise_state = dict(getattr(self.engine.state, "flags", {}).get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
            merged = bool(promise_state.get(str(idx), False))
            if uid in p.deck:
                if merged:
                    return idx, "graveyard"
                return idx, "relicario"
            if uid in p.graveyard:
                return idx, "graveyard"
            if uid in p.excommunicated:
                return idx, "excommunicated"
            if uid in p.attack:
                return idx, "attack"
            if uid in p.defense:
                return idx, "defense"
            if uid in p.artifacts:
                return idx, "artifact"
            if p.building == uid:
                return idx, "building"
        return None

    # Queries/conditions used by migrated cards and runtime logic.
    def controller_has(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        for uid in self._iter_uids(self.controller_idx, "field"):
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Similar to controller_has, but checks the opponent's field instead. This is used for conditions that depend on the opponent controlling a specific card.
    def opponent_has(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        opp = 1 - self.controller_idx
        for uid in self._iter_uids(opp, "field"):
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Check if there's a saint with the given name on the field, controlled by either player. This is used for conditions that depend on the presence of a specific saint on the field.
    def in_hand(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        for uid in self.state.players[self.controller_idx].hand:
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Check if there's a card with the given name in the controller's graveyard. This is used for conditions that depend on having a specific card in the graveyard.
    def in_graveyard(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        p = self.state.players[self.controller_idx]
        promise_state = dict(getattr(self.engine.state, "flags", {}).get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
        merged = bool(promise_state.get(str(self.controller_idx), False))
        uids = list(p.graveyard) + ([uid for uid in p.deck if uid not in p.graveyard] if merged else [])
        for uid in uids:
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Check if there's a card with the given name in the controller's relicario (deck). This is used for conditions that depend on having a specific card in the deck.
    def in_relicario(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        for uid in self.state.players[self.controller_idx].deck:
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Check if there's a card with the given name in the controller's excommunicated zone. This is used for conditions that depend on having a specific card in the excommunicated zone.
    def in_excommunicated(self, card_name: str) -> bool:
        key = _norm_ascii(card_name)
        for uid in self.state.players[self.controller_idx].excommunicated:
            if _norm_ascii(self.state.instances[uid].definition.name) == key:
                return True
        return False

    # Action methods for performing game actions. These methods interact with the game engine and state to implement the desired effects of card scripts. They also emit events when appropriate to allow other scripts to react to these actions.
    def draw_cards(self, player: int, amount: int, from_zone: str = "relicario") -> int:
        if _norm(from_zone) not in {"relicario", "deck"}:
            return 0
        return self.engine.draw_cards(int(player), int(amount))

    # Shuffle the controller's relicario (deck) and emit an event. This can be used for card effects that involve shuffling the deck, and allows other scripts to react to the shuffle if needed.
    def shuffle_relicario(self, player: int) -> None:
        idx = int(player)
        self.engine.rng.shuffle(self.state.players[idx].deck)
        self.emit("on_player_shuffles_relicario", player=idx)

    # Mill cards from the top of the specified player's relicario (deck) to their graveyard. This is used for card effects that involve milling cards, and emits events for each card sent to the graveyard as well as a summary event with the total amount milled.
    def mill_cards(self, player: int, amount: int) -> int:
        idx = int(player)
        p = self.state.players[idx]
        moved = 0
        for _ in range(max(0, int(amount))):
            if not p.deck:
                break
            uid = p.deck.pop()
            p.graveyard.append(uid)
            moved += 1
            self.emit("on_card_sent_to_graveyard", card=uid, from_zone="relicario", owner=idx)
        if moved > 0:
            self.emit("on_player_mills_cards", player=idx, amount=moved)
        return moved

    # Discard a card from the controller's hand to the graveyard. This is used for card effects that involve discarding cards, and emits events for the discard action as well as a summary event with the total amount discarded.
    def send_from_hand_to_graveyard(self, card_uid: str) -> bool:
        p = self.state.players[self.controller_idx]
        if card_uid not in p.hand:
            return False
        p.hand.remove(card_uid)
        p.graveyard.append(card_uid)
        self.emit("on_card_discarded", card=card_uid, from_hand_to_graveyard=True)
        self.emit("on_card_sent_to_graveyard", card=card_uid, from_zone="hand", owner=self.controller_idx)
        return True

    # Send a card from the controller's relicario (deck) to the graveyard. This is used for card effects that involve sending cards from the deck to the graveyard, and emits an event for the action.
    def send_from_relicario_to_graveyard(self, card_uid: str) -> bool:
        p = self.state.players[self.controller_idx]
        if card_uid not in p.deck:
            return False
        p.deck.remove(card_uid)
        p.graveyard.append(card_uid)
        self.emit("on_card_sent_to_graveyard", card=card_uid, from_zone="relicario", owner=self.controller_idx)
        return True

    # Send a card from the field to the graveyard. This is used for card effects that involve destroying or sacrificing cards on the field, and emits an event for the action. If generate_sin is True (the default), also reduce the controller's sin by the amount of faith the card had, if any.
    def send_from_field_to_graveyard(self, card_uid: str, generate_sin: bool = True) -> bool:
        where = self._find_controller_of_uid(card_uid)
        if where is None:
            return False
        owner_idx, zone = where
        if zone not in {"attack", "defense", "artifact", "building"}:
            return False
        self.engine.send_to_graveyard(owner_idx, card_uid)
        if not generate_sin:
            self.state.players[owner_idx].sin = max(0, self.state.players[owner_idx].sin - max(0, self.state.instances[card_uid].definition.faith or 0))
        return True

    # Targeting methods for selecting cards based on various criteria. These methods return lists of card UIDs that match the specified filters, and can be used by card scripts to implement effects that target specific cards on the field, in the graveyard, etc.
    def target_saint_on_field(self, filter_function: Callable[[Any], bool] | None = None) -> list[str]:
        out: list[str] = []
        for idx in (0, 1):
            for uid in self.engine.all_saints_on_field(idx):
                inst = self.state.instances[uid]
                if filter_function is None or bool(filter_function(inst)):
                    out.append(uid)
        return out

    # Similar to target_saint_on_field, but only checks the opponent's field. This is used for effects that need to target saints controlled by the opponent.
    def target_saint_opponent_field(self, filter_function: Callable[[Any], bool] | None = None) -> list[str]:
        out: list[str] = []
        opp = 1 - self.controller_idx
        for uid in self.engine.all_saints_on_field(opp):
            inst = self.state.instances[uid]
            if filter_function is None or bool(filter_function(inst)):
                out.append(uid)
        return out

    # General method for targeting up to n cards across specified zones, with an optional filter function. This is a flexible method that can be used for a wide variety of targeting needs, allowing card scripts to specify exactly which zones to search and what criteria to apply when selecting targets.
    def target_up_to_n_cards(self, n: int, filter_function: Callable[[Any], bool] | None = None, zones: list[str] | None = None) -> list[str]:
        zones = zones or ["field"]
        out: list[str] = []
        for z in zones:
            if _norm(z) == "field":
                for idx in (0, 1):
                    for uid in self._iter_uids(idx, "field"):
                        inst = self.state.instances[uid]
                        if filter_function is None or bool(filter_function(inst)):
                            out.append(uid)
                            if len(out) >= n:
                                return out
            else:
                for uid in self._iter_uids(self.controller_idx, z):
                    inst = self.state.instances[uid]
                    if filter_function is None or bool(filter_function(inst)):
                        out.append(uid)
                        if len(out) >= n:
                            return out
        return out

    # Target cards that have a certain number of croci, using the _cross_value function to parse the croci from the card definition. This allows for targeting cards based on their cross value, which can be an important attribute for certain card effects.
    def target_card_with_croci(self, operator: str, value: int, zones: list[str] | None = None) -> list[str]:
        zones = zones or ["field"]
        value = int(value)
        out: list[str] = []
        for uid in self.target_up_to_n_cards(999, zones=zones):
            cv = _cross_value(self.state.instances[uid].definition.crosses)
            if cv is None:
                continue
            ok = False
            if operator == "<=":
                ok = cv <= value
            elif operator == ">=":
                ok = cv >= value
            elif operator == "==":
                ok = cv == value
            if ok:
                out.append(uid)
        return out

    # Methods for modifying card attributes like faith and strength. These methods update the card's attributes in the game state and emit events to notify other scripts of the changes. They also ensure that values do not go below zero, and can optionally make faith changes permanent (i.e., affecting both current and initial faith).
    def increase_faith(self, card_uid: str, amount: int, is_permanent: bool = True) -> None:
        inst = self.state.instances[card_uid]
        old = inst.current_faith or 0
        inst.current_faith = max(0, old + int(amount))
        self.emit("on_faith_changed", card=card_uid, old_value=old, new_value=inst.current_faith)

    # Decrease faith by calling increase_faith with a negative amount. This ensures that the same logic for updating faith and emitting events is used for both increasing and decreasing faith, and also allows for the is_permanent flag to be applied consistently.
    def decrease_faith(self, card_uid: str, amount: int) -> None:
        self.increase_faith(card_uid, -int(amount))

    # Set faith to a specific value, optionally making it permanent. This is used for effects that need to set a card's faith to a specific number, rather than just increasing or decreasing it by a certain amount.
    def increase_strength(self, card_uid: str, amount: int) -> None:
        inst = self.state.instances[card_uid]
        old = int(inst.definition.strength or 0)
        inst.definition.strength = max(0, old + int(amount))
        self.emit("on_strength_changed", card=card_uid, old_value=old, new_value=inst.definition.strength)

    # Decrease strength by calling increase_strength with a negative amount. This ensures that the same logic for updating strength and emitting events is used for both increasing and decreasing strength.
    def decrease_strength(self, card_uid: str, amount: int) -> None:
        self.increase_strength(card_uid, -int(amount))

    # Set strength to a specific value. This is used for effects that need to set a card's strength to a specific number, rather than just increasing or decreasing it by a certain amount.
    def inflict_sin(self, player: int, amount: int) -> None:
        idx = int(player)
        old = int(self.state.players[idx].sin)
        self.engine.gain_sin(idx, int(amount))
        self.emit("on_sin_changed", player=idx, old_value=old, new_value=self.state.players[idx].sin)
        self.emit("on_player_receives_sin", player=idx, amount=int(amount))

    # Remove sin from a player, ensuring it does not go below zero. This is used for effects that reduce a player's sin, and emits events to notify other scripts of the change.
    def remove_sin(self, player: int, amount: int) -> None:
        idx = int(player)
        old = int(self.state.players[idx].sin)
        self.engine.reduce_sin(idx, int(amount))
        self.emit("on_sin_changed", player=idx, old_value=old, new_value=self.state.players[idx].sin)
        self.emit("on_player_removes_sin", player=idx, amount=int(amount))

    # Add inspiration to a player, ensuring it does not go below zero. This is used for effects that grant inspiration to a player, and emits events to notify other scripts of the change. The duration parameter can be used to indicate how long the inspiration should last (e.g., "this_turn", "permanent", etc.), which can be useful for effects that have temporary inspiration bonuses.
    def add_inspiration(self, player: int, amount: int, duration: str = "this_turn") -> None:
        idx = int(player)
        old = int(self.state.players[idx].inspiration)
        self.state.players[idx].inspiration = max(0, old + int(amount))
        self.emit(
            "on_inspiration_changed",
            player=idx,
            old_value=old,
            new_value=self.state.players[idx].inspiration,
            duration=duration,
        )

    # Pay inspiration by reducing the player's inspiration by the specified amount. If the player does not have enough inspiration, return False (or True if optional is True). If the payment is successful, emit events to notify other scripts of the change and the payment action.
    def pay_inspiration(self, player: int, amount: int, optional: bool = False) -> bool:
        idx = int(player)
        p = self.state.players[idx]
        amt = max(0, int(amount))
        if p.inspiration < amt:
            return bool(optional)
        old = int(p.inspiration)
        p.inspiration -= amt
        self.emit("on_inspiration_changed", player=idx, old_value=old, new_value=p.inspiration)
        self.emit("on_player_pays_inspiration", player=idx, amount=amt)
        return True

    # Query methods for retrieving current values of card attributes and player stats. These methods access the game state to return the current faith, strength, croci, inspiration, and sin values for cards and players. They are used by card scripts to make decisions based on the current game state.
    def get_current_faith(self, card_uid: str) -> int:
        return int(self.state.instances[card_uid].current_faith or 0)

    # Get the initial faith of a card, which is defined in the card definition and does not change during the game. This is used for effects that need to reference the card's original faith value, regardless of any modifications that may have occurred during the game.
    def get_initial_faith(self, card_uid: str) -> int:
        return int(self.state.instances[card_uid].definition.faith or 0)

    # Get the current strength of a card, which may be modified by effects during the game. This is used for effects that need to reference the card's current strength value, which can change due to various effects.
    def get_current_strength(self, card_uid: str) -> int:
        return int(self.engine.get_effective_strength(card_uid))

    # Get the number of croci on a card by parsing the crosses attribute from the card definition. This allows for effects that depend on the card's cross value, which can be an important attribute for certain cards.
    def get_croci(self, card_uid: str) -> int:
        return int(_cross_value(self.state.instances[card_uid].definition.crosses) or 0)

    # Get the number of seal counters on a card. This is used for effects that depend on the number of seal counters, which can be added or removed during the game.
    def get_remaining_inspiration(self, player: int) -> int:
        return int(self.state.players[int(player)].inspiration)

    # Get the current sin of a player. This is used for effects that depend on the player's sin level, which can change during the game due to various actions and effects.
    def get_current_sin(self, player: int) -> int:
        return int(self.state.players[int(player)].sin)

    # Count the number of saints on the field for a given player, optionally filtering by position (attack or defense). This is used for effects that depend on the number of saints a player has on the field, and allows for more specific queries based on the position of the saints.
    def count_saints_on_field(self, player: int, position_filter: str | None = None) -> int:
        idx = int(player)
        p = self.state.players[idx]
        z = _norm(position_filter or "")
        if z == "attack":
            return sum(1 for uid in p.attack if uid is not None and _norm_ascii(self.state.instances[uid].definition.card_type) in {"santo", "token"})
        if z == "defense":
            return sum(1 for uid in p.defense if uid is not None and _norm_ascii(self.state.instances[uid].definition.card_type) in {"santo", "token"})
        return len(self.engine.all_saints_on_field(idx))

    # Count the number of tokens on the field for a given player. This is used for effects that depend on the number of tokens a player has on the field, which can be important for certain strategies and card effects.
    def count_cards_in_hand(self, player: int) -> int:
        return len(self.state.players[int(player)].hand)

    # Count the number of cards in the player's graveyard. This is used for effects that depend on the number of cards in the graveyard, which can be important for certain strategies and card effects that interact with the graveyard.
    def count_cards_in_graveyard(self, player: int) -> int:
        idx = int(player)
        p = self.state.players[idx]
        promise_state = dict(getattr(self.engine.state, "flags", {}).get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
        if bool(promise_state.get(str(idx), False)):
            # merged zone: count unique cards in graveyard + deck
            return len(list(dict.fromkeys(p.graveyard + p.deck)))
        return len(p.graveyard)

    # Count the number of cards in the player's relicario (deck). This is used for effects that depend on the number of cards remaining in the deck, which can be important for certain strategies and card effects that interact with the deck.
    def count_cards_in_relicario(self, player: int) -> int:
        return len(self.state.players[int(player)].deck)

    # Count the number of cards in the player's excommunicated zone. This is used for effects that depend on the number of cards in the excommunicated zone, which can be important for certain strategies and card effects that interact with this zone.
    def count_cards_in_excommunicated(self, player: int) -> int:
        return len(self.state.players[int(player)].excommunicated)

    # Count the number of cards sent from hand or field to graveyard this turn for a player. This is used for effects that depend on how many cards a player has lost during the turn, which can be important for certain strategies and card effects that trigger based on card loss.
    def is_card_type(self, card_uid: str, type: str) -> bool:
        return _norm_ascii(self.state.instances[card_uid].definition.card_type) == _norm_ascii(type)

    # Method for declaring a player as the winner of the game, with an optional reason. This can be used for card effects that have a win condition, allowing them to end the game immediately when the condition is met. The reason can be included in the game log for clarity.
    def win_the_game(self, player: int, reason: str = "") -> None:
        self.state.winner = int(player)
        if reason:
            self.state.log(f"Vittoria per effetto: {reason}.")

__all__ = ["RuleAPI", "RuleEvents", "RuleEventBus", "RuleEventContext", "DECLARED_FUNCTIONS"]
