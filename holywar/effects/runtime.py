from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from holywar.core import state
from holywar.core.state import MAX_HAND
from holywar.effects.card_scripts_loader import iter_card_scripts
from holywar.scripting_api import RuleEventContext
from holywar.core.state import CardInstance
from holywar.data.importer import load_cards_json
from holywar.data.models import CardDefinition

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine
    from holywar.scripting_api import RuleEventContext

# This module defines functions for managing runtime state flags in the game engine. The runtime state includes information about the current phase of the game, which player's turn it is, and various flags that indicate what actions are currently allowed for each player. The `ensure_runtime_state` function initializes the runtime state if it doesn't already exist, while the `refresh_player_flags` function updates the player-specific flags based on the current game state. The `set_phase` function is used to update the current phase of the game and refresh the player flags accordingly.
SUPPORTED_CONDITION_KEYS = {
    "all_of",
    "any_of",
    "not",
    "payload_from_zone_in",
    "payload_to_zone_in",
    "payload_target_slot_is_set",
    "payload_target_player",
    "payload_target_owner",
    "controller_hand_size_equals_opponent",
    "stored_values_not_equal",
    "event_card_owner",
    "event_card_type_in",
    "turn_scope",
    "phase_is",
    "source_on_field",
    "my_saints_gte",
    "my_saints_lte",
    "my_saints_lt_opponent",
    "opponent_saints_gte",
    "opponent_saints_lte",
    "my_inspiration_gte",
    "my_inspiration_lte",
    "my_spent_inspiration_turn_gte",
    "my_attack_count_lte",
    "opponent_inspiration_gte",
    "my_sin_gte",
    "my_sin_lte",
    "opponent_sin_gte",
    "opponent_sin_lte",
    "payload_reason_in",
    "target_current_faith_gte",
    "target_current_faith_lte",
    "controller_has_saint_with_name",
    "controller_has_artifact_with_name",
    "can_play_by_sacrificing_specific_card_from_field",
    "controller_has_cards",
    "can_play_by_sacrificing",
    "controller_has_card_in_hand_with_name",
    "controller_has_card_in_deck_with_name",
    "controller_has_building_with_name",
    "controller_has_building_matching",
    "controller_altare_sigilli_gte",
    "controller_drawn_cards_this_turn_gte",
    "controller_has_distinct_saints_gte",
    "controller_has_distinct_cards_gte",
    "selected_option_in",
    "selected_target_in",
    "selected_target_exists",
    "selected_target_card_type_in",
    "selected_target_startswith",
    "event_card_name_is",
    "event_card_name_contains",
    "target_is_damaged",
    "controller_hand_size_lte",
    "controller_free_artifact_slots_gte",
    "stored_card_matches",
    "source_counter_gte",
    "controller_saints_sent_to_graveyard_this_turn_gte",
    "event_card_owner_attack_count_gte",
}

# This dictionary defines aliases for effect actions. It maps various action names that might be used in card scripts or effect definitions to a standardized set of action names that the runtime will recognize and handle. For example, "add_faith" and "buff_faith" are both mapped to "increase_faith", while "remove_faith" and "damage_faith" are mapped to "decrease_faith". This allows for more flexibility in how actions are defined in card scripts while still maintaining a consistent set of actions that the runtime can process.
EFFECT_ACTION_ALIASES = {
    "add_faith": "increase_faith",
    "buff_faith": "increase_faith",
    "remove_faith": "decrease_faith",
    "damage_faith": "decrease_faith",
    "buff_strength": "increase_strength",
    "add_strength": "increase_strength",
    "remove_strength": "decrease_strength",
    "draw_extra_card": "draw_cards",
    "add_draw": "draw_cards",
    "deal_sin": "inflict_sin",
    "add_sin": "inflict_sin",
    "reduce_sin": "remove_sin",
    "gain_inspiration": "add_inspiration",
    "pay_inspiration": "pay_inspiration",
    "move_to_graveyard": "send_to_graveyard",
    "prevent_specific_card_from_activating": "negate_next_activation",
    "choose_and_activate_piaga_effect": "choose_and_activate_effect",
    "remove_sin_equal_to_last_inflicted_to_opponent": "remove_sin_equal_to_stored_value",
}

# This set defines the supported effect actions that the runtime can process. It includes a wide range of actions that can be performed as part of card effects, such as increasing or decreasing faith and strength, adding or removing counters, inflicting sin, drawing cards, moving cards between zones, and many more. This set is used to validate that any effect action specified in card scripts or effect definitions is recognized and can be handled by the runtime.
SUPPORTED_EFFECT_ACTIONS = {
    "increase_faith",
    "increase_faith_equal_to_base",
    "decrease_faith",
    "increase_strength",
    "increase_source_stats_from_zone_count_div",
    "double_strength",
    "increase_strength_equal_to_target_base_faith",
    "calice_upkeep",
    "calice_endturn",
    "add_seal_counter",
    "remove_seal_counter",
    "campana_add_counter",
    "campana_remove_counter",
    "campana_spend_counters_grant_faith",
    "cataclisma_ciclico",
    "kah_ok_tick",
    "trombe_del_giudizio_tick",
    "av_drna_on_opponent_draw",
    "pay_sin_or_destroy_self",
    "mill_cards",
    "draw_cards",
    "draw_matching_from_top_n",
    "resolve_monsone_payload",
    "draw_cards_and_set_play_cost_for_drawn_until_turn_end",
    "draw_by_zone_count_comparison",
    "draw_by_excommunicated_count_comparison",
    "set_blocked_enemy_artifact_slot_from_selected_option",
    "process_deck_edges_by_type",
    "inflict_sin",
    "inflict_sin_to_target_owners",
    "remove_sin",
    "add_inspiration",
    "pay_inspiration",
    "pay_inspiration_per_target",
    "set_faith_to",
    "set_attack_shield_this_turn",
    "set_attack_shield_next_opponent_turn",
    "reorder_top_n_of_deck",
    "remove_sin_from_flag",
    "win_the_game",
    "grant_extra_attack_this_turn",
    "excommunicate_top_cards_from_relicario",
    "remove_from_board_no_sin",
    "summon_card_from_hand",
    "summon_named_card",
    "summon_named_card_from_flag",
    "move_source_to_board",
    "move_to_hand",
    "send_to_graveyard",
    "move_to_deck_bottom",
    "move_to_relicario",
    "request_end_turn",
    "set_next_turn_draw_override",
    "set_double_cost_next_turn",
    "set_no_attacks_until_card_draw",
    "set_no_attacks_this_turn",
    "swap_attack_defense_rows",
    "transfer_target_control_until_turn_end",
    "negate_next_activation",
    "grant_counter_spell",
    "shuffle_deck",
    "shuffle_target_owner_decks",
    "summon_generated_token",
    "summon_generated_token_in_each_free_saint_slot",
    "return_to_hand_once_per_turn",
    "swap_attack_defense",
    "swap_selected_attack_defense",
    "increase_faith_per_opponent_saints",
    "increase_faith_if_damaged",
    "add_temporary_inspiration",
    "store_target_strength",
    "add_temporary_inspiration_from_flag",
    "summon_target_to_field",
    "summon_target_to_field_pay_half_inspiration",
    "choose_targets_and_summon_to_field",
    "destroy_equipped_target_and_excommunicate_source",
    "remove_sin_equal_to_target_strength",
    "remove_sin_equal_to_target_faith_and_strength",
    "remove_sin_equal_to_last_inflicted_to_opponent",
    "remove_sin_equal_to_stored_value",
    "reset_faith_to_base",
    "inflict_sin_to_event_controller",
    "store_top_card_of_zone",
    "reveal_selected_target",
    "reveal_stored_card",
    "move_stored_card_to_zone",
    "destroy_stored_card",
    "summon_stored_card_to_field",
    "move_source_to_zone",
    "optional_draw_from_top_n_then_shuffle",
    "optional_recover_from_graveyard_then_shuffle",
    "optional_recover_cards",
    "store_target_count",
    "store_distinct_count",
    "store_target_uid",
    "store_target_name",
    "floor_divide_flag",
    "draw_cards_from_flag",
    "choose_targets",
    "choose_up_to_n_from_hand_to_relicario_then_draw_same",
    "optional_redraw_event_card",
    "choose_option",
    "inflict_sin_from_flag",
    "store_target_faith",
    "increase_faith_from_flag",
    "decrease_faith_from_flag",
    "excommunicate_card_no_sin",
    "store_target_faith_and_excommunicate_no_sin",
    "move_first_to_hand",
    "absorb_target_stats_and_link",
    "destroy_source_if_linked_to_event_card",
    "destroy_source_if_equipped_target_is_event_card",
    "move_source_to_zone_if_equipped_target_is_event_card",
    "inflict_sin_to_event_owner_equal_base_faith_if_equipped_target",
    "phdrna_activate_destroy_target_then_self",
    "choose_artifact_from_relicario_then_shuffle",
    "inflict_sin_from_source_paid_inspiration",
    "optional_recover_all_matching_then_shuffle",
    "optional_recover_matching_then_shuffle",
    "destroy_all_saints_except_selected",
    "retaliate_damage_to_event_source_if_enemy_saint",
    "retaliate_event_damage_to_event_source_if_enemy_saint",
    "retaliate_event_damage_divided_to_event_source_if_enemy_saint",
    "mill_top_and_store_card_type",
    "draw_if_stored_values_not_equal",
    "draw_cards_and_store_last_drawn",
    "destroy_source_if_effective_strength_lte",
    "inflict_sin_from_flag_scaled",
    "remove_sin_from_flag_scaled",
    "set_pending_sin_mirror_once",
    "grant_attack_barrier",
    "grant_blessed_tag_from_source",
    "prevent_specific_card_from_attacking",
    "halve_target_base_faith_rounded_down",
    "halve_strength_rounded_down",
    "equip_card",
    "unequip_card",
    "destroy_equipment",
    "sacrifice_time_resolution",
    "add_link_tag_to_source_from_selected_target",
    "destroy_linked_targets_from_source_tags",
    "move_all_from_zone_to_zone",
    "activate_oltretomba_promise",
    "discard_hand_then_pressure_opponent",
    "choose_draw_amount_with_self_sin_cost",
    "choose_and_activate_effect",
}

# This set defines the supported effect conditions that can be used in card scripts or effect definitions. These conditions are used to determine whether certain effects should be applied based on the current game state, the event context, or other factors. The runtime will evaluate these conditions when processing effects to ensure that they are only applied when the specified conditions are met.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
def _card_aliases(definition: CardDefinition) -> list[str]:
    raw_aliases = getattr(definition, "aliases", []) or []
    if isinstance(raw_aliases, str):
        return [part.strip() for part in raw_aliases.split(",") if part.strip()]
    return [str(alias).strip() for alias in raw_aliases if str(alias).strip()]

# These functions are utility functions for working with card definitions and their names. The `_norm` function normalizes a string by removing diacritical marks and converting it to lowercase, which is useful for comparing card names in a case-insensitive and accent-insensitive way. The `_card_aliases` function retrieves the list of aliases for a given card definition, which can be specified as a comma-separated string or as a list of strings. The `_card_name_variants` function generates a set of normalized name variants for a card definition, including its main name and any aliases. The `_card_name_haystack` function creates a single normalized string that contains the card's name and all its aliases, which can be used for substring searches. The `_card_matches_name` function checks if a given name matches any of the card's name variants.
def _card_name_variants(definition: CardDefinition) -> set[str]:
    variants = {_norm(definition.name)}
    variants.update(_norm(alias) for alias in _card_aliases(definition))
    return {v for v in variants if v}

# This function generates a set of normalized name variants for a given card definition. It takes the card's main name and any aliases, normalizes them using the `_norm` function, and returns a set of unique normalized names. This is useful for comparing card names in a way that is case-insensitive and accent-insensitive, allowing for more flexible matching of card names in various contexts (e.g., when checking if a card matches a specified name in an effect condition).
def _card_name_haystack(definition: CardDefinition) -> str:
    parts = [definition.name, *_card_aliases(definition)]
    return " ".join(_norm(part) for part in parts if str(part).strip())

# This function checks if a given name matches any of the card's name variants. It normalizes the input name and checks if it is present in the set of normalized name variants for the card definition. This allows for flexible matching of card names, taking into account case insensitivity and ignoring diacritical marks, as well as considering any aliases that the card may have.
def _card_matches_name(definition: CardDefinition, wanted: str) -> bool:
    wanted_norm = _norm(wanted)
    if not wanted_norm:
        return False
    return wanted_norm in _card_name_variants(definition)

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class TriggerSpec:
    event: str
    frequency: str = "each_turn"
    condition: dict[str, Any] = field(default_factory=dict)
    exclusive_trigger_per_turn: bool = False
    exclusive_group: str = ""

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class CardFilterSpec:
    name_in: list[str] = field(default_factory=list)
    name_equals: str | None = None
    name_contains: str | None = None
    name_not_contains: str | None = None
    name_not_equals_stored: str | None = None
    card_type_in: list[str] = field(default_factory=list)
    exclude_event_card: bool = False
    exclude_buildings_if_my_building_zone_occupied: bool = False
    crosses_gte: int | None = None
    crosses_lte: int | None = None
    strength_gte: int | None = None
    strength_lte: int | None = None
    drawn_this_turn_only: bool = False
    top_n_from_zone: int | None = None
    half_cost_lte_my_inspiration: bool = False

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class TargetSpec:
    type: str
    card_filter: CardFilterSpec = field(default_factory=CardFilterSpec)
    zone: str = "field"
    zones: list[str] = field(default_factory=list)
    owner: str = "me"
    min_targets: int | None = None
    max_targets: int | None = None
    max_targets_from: dict[str, Any] | None = None

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class EffectSpec:
    action: str
    amount: int = 0
    duration: str = "permanent"
    amount_multiplier_card_name: str | None = None
    usage_limit_per_turn: int | None = None
    target_player: str | None = None
    card_name: str | None = None
    flag: str | None = None
    owner: str | None = None
    from_zone: str | None = None
    zone: str | None = None
    position: str | None = None
    store_as: str | None = None
    stored: str | None = None
    to_zone: str | None = None
    threshold: int | None = None
    divisor: int | None = None
    min_targets: int | None = None
    max_targets: int | None = None
    controller_has_saint_with_name: str | None = None
    to_zone_if_controller_has_saint_with_name: str | None = None
    to_zone_if_condition: dict[str, Any] | None = None
    to_zone_if: str | None = None
    shuffle_after: bool = False
    choice_title: str | None = None
    choice_prompt: str | None = None
    choice_options: list[dict[str, Any]] = field(default_factory=list)
    compare_zone: str | None = None
    compare_target_player: str | None = None
    tie_policy: str | None = None
    tie_amount: int | None = None
    override_cost: int | None = None
    top_count: int | None = None
    bottom_count: int | None = None
    unique_edges_only: bool = True
    saint_token_to_zone: str | None = None
    blessing_curse_to_zone: str | None = None
    artifact_to_zone: str | None = None
    building_to_zone: str | None = None
    fallback_to_zone: str | None = None
    replace_occupied_artifact: bool = False
    replace_occupied_building: bool = False

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class TriggeredEffectSpec:
    trigger: TriggerSpec
    target: TargetSpec
    effect: EffectSpec

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class ActionSpec:
    target: TargetSpec
    effect: EffectSpec
    condition: dict[str, Any] = field(default_factory=dict)

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
@dataclass(slots=True)
class CardScript:
    name: str
    on_play_mode: str = "auto"
    on_enter_mode: str = "auto"
    on_activate_mode: str = "auto"
    activate_once_per_turn: bool = False
    play_owner: str = "me"
    can_play_from_hand: bool = True
    play_targeting: str = "auto"
    play_requirements: dict[str, Any] = field(default_factory=dict)
    play_cost_fixed: int | None = None
    play_cost_reduction_if_controller_has_card_type_in_hand: list[str] = field(default_factory=list)
    play_cost_zero_if_controller_has_saint_with_name: str | None = None
    play_cost_zero_if_controller_has_no_saints: bool = False
    auto_play_drawn_cards_with_faith_lte: int | None = None
    halves_friendly_saint_play_cost: bool = False
    halve_friendly_saint_play_cost_excludes_self: bool = True
    doubles_enemy_play_cost: bool = False
    activate_targeting: str = "auto"
    can_activate_by_any_player: bool = False
    attack_targeting: str = "auto"
    can_attack: bool = True
    attack_requirements: dict[str, Any] = field(default_factory=dict)
    attack_blocked_message: str | None = None
    can_attack_from_defense: bool = False
    can_attack_multiple_targets_in_attack_per_turn: bool = False
    blocks_enemy_attackers_with_crosses_lte: int | None = None
    prevent_incoming_damage_if_less_than: int | None = None
    prevent_incoming_damage_to_card_types: list[str] = field(default_factory=list)
    battle_survival_mode: str = "none"
    battle_survival_names: list[str] = field(default_factory=list)
    battle_survival_token_name: str | None = None
    battle_survival_restore_faith: int | None = None
    battle_excommunicate_on_lethal: bool = False
    post_battle_forced_destroy: bool = False
    turn_start_summon_token_name: str | None = None
    auto_play_on_draw: bool = False
    end_turn_on_draw: bool = False
    strength_bonus_rules: list[dict[str, Any]] = field(default_factory=list)
    sigilli_strength_bonus_threshold: int | None = None
    sigilli_strength_bonus_amount: int | None = None
    is_pyramid: bool = False
    pyramid_strength_bonus_threshold: int | None = None
    pyramid_strength_bonus_amount: int | None = None
    pyramid_summon_extra_base_faith_threshold: int | None = None
    pyramid_summon_extra_base_faith_multiplier: int | None = None
    pyramid_turn_draw_bonus_threshold: int | None = None
    pyramid_turn_draw_bonus_amount: int | None = None
    is_altare_sigilli: bool = False
    altare_seal_shield_from_source_crosses: bool = False
    inverts_saint_summon_controller: bool = False
    destroy_requires_building_or_artifacts_and_inspiration: dict[str, Any] = field(default_factory=dict)
    indestructible_except_own_activation: bool = False
    seals_level_size: int | None = None
    seals_faith_per_level: int | None = None
    seals_strength_per_level: int | None = None
    immune_to_actions: list[str] = field(default_factory=list)
    incoming_damage_from_enemy_saints_divisor: int = 1
    strength_gain_on_damage_to_enemy_saint: int = 0
    strength_gain_on_lethal_to_enemy_saint: int = 0
    grants_strength_to_friendly_saints: int = 0
    grants_strength_to_friendly_saints_except_names: list[str] = field(default_factory=list)
    modifies_enemy_saints_strength: int = 0
    blocks_enemy_artifact_slots: int = 0
    prevent_effect_destruction_of_friendly_saints_from_source_card_types: list[str] = field(default_factory=list)
    prevent_targeting_of_friendly_saints_from_enemy_card_types: list[str] = field(default_factory=list)
    protection_rules: list[dict[str, Any]] = field(default_factory=list)
    retaliation_damage_to_enemy_attacker: int = 0
    retaliation_reduce_sin_on_kill: int = 0
    retaliation_multiplier_for_friendly_building_name: str | None = None
    triggered_effects: list[TriggeredEffectSpec] = field(default_factory=list)
    on_play_actions: list[ActionSpec] = field(default_factory=list)
    on_enter_actions: list[ActionSpec] = field(default_factory=list)
    on_activate_actions: list[ActionSpec] = field(default_factory=list)
    faith_bonus_rules: list[dict[str, Any]] = field(default_factory=list)
    counted_bonuses: list[dict[str, Any]] = field(default_factory=list)


from holywar.effects.runtime_sections import RuntimeRegistryMixin, RuntimeResolutionMixin, RuntimeEffectsMixin

# The following classes define data structures for representing card scripts, triggered effects, action specifications, and other related concepts in the game. These classes use the `@dataclass` decorator to automatically generate initialization methods and other boilerplate code. They are used to represent the various properties and behaviors of cards and effects in a structured way that can be easily manipulated by the runtime when processing card effects and game events.
class RuntimeCardManager(RuntimeRegistryMixin, RuntimeResolutionMixin, RuntimeEffectsMixin):
    """Facade class: concrete behavior is composed via runtime mixins."""
    pass


runtime_cards = RuntimeCardManager()


__all__ = [
    "TriggerSpec",
    "CardFilterSpec",
    "TargetSpec",
    "EffectSpec",
    "TriggeredEffectSpec",
    "ActionSpec",
    "CardScript",
    "RuntimeCardManager",
    "runtime_cards",
]
