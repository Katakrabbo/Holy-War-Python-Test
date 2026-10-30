from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
import json
from pathlib import Path

from holywar.core import state
from holywar.core.state import MAX_HAND, CardInstance
from holywar.effects.card_scripts_loader import iter_card_scripts
from holywar.scripting_api import RuleEventContext
from holywar.data.importer import load_cards_json
from holywar.data.models import CardDefinition
from holywar.effects.runtime import (
    _norm,
    _card_name_haystack,
    _card_name_variants,
    _card_matches_name,
    SUPPORTED_EFFECT_ACTIONS,
    EFFECT_ACTION_ALIASES,
    SUPPORTED_CONDITION_KEYS,
    TriggerSpec,
    CardFilterSpec,
    TargetSpec,
    EffectSpec,
    TriggeredEffectSpec,
    ActionSpec,
    CardScript,
)

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine

# This module defines the `RuntimeRegistryMixin` class, which serves as a registry for card scripts and their associated properties in the game engine. The mixin provides methods for bootstrapping card scripts from JSON data and script files, as well as methods for accessing specific properties of card scripts, such as targeting modes and play costs. The registry is designed to facilitate the migration of card scripts from older formats to a new structured format, allowing for more complex and flexible card behaviors in the game.
class RuntimeRegistryMixin:
    if TYPE_CHECKING:
        # Methods from RuntimeEffectsMixin
        def _eval_condition_node(self, ctx: RuleEventContext, owner_idx: int, node: dict[str, Any]) -> bool: ...
        def _collect_cards_for_requirement(self, engine: GameEngine, owner_idx: int, requirement: dict[str, Any]) -> list[str]: ...
    """Script registry bootstrap, migration and static card property accessors."""

    # The constructor initializes the runtime registry by setting up empty dictionaries for storing card scripts, bindings, subscribed engines, and temporary faith values. It then calls two bootstrap methods: one to load card scripts from a JSON file (if it exists) and another to load card scripts from individual script files. This setup allows the registry to be populated with card scripts that define the behavior of cards in the game, which can then be accessed and utilized during gameplay.
    def __init__(self) -> None:
        self._scripts: dict[str, CardScript] = {}
        self._bindings: dict[int, dict[str, list[tuple[str, Callable[[RuleEventContext], None]]]]] = {}
        self._subscribed_engines: set[int] = set()
        self._temp_faith: dict[int, dict[str, list[tuple[str, int, str]]]] = {}
        self._bootstrap_from_cards_json()
        self._bootstrap_from_script_files()

    # This method clears the registry of all card scripts, bindings, subscribed engines, and temporary faith values. It is intended for use in testing scenarios where a clean state is required before each test case. By calling this method, you can ensure that the registry does not retain any state from previous tests, allowing for accurate and isolated testing of card scripts and their interactions within the game engine.
    def clear_for_tests(self) -> None:
        self._scripts.clear()
        self._bindings.clear()
        self._subscribed_engines.clear()
        self._temp_faith.clear()

    # This method bootstraps the card scripts from a JSON file named "cards.json" located in the "data" directory of the project. It reads the JSON file, parses it, and iterates through the list of card definitions. For each card definition, it extracts the card name and registers a corresponding `CardScript` in the registry if it does not already exist. This allows for a bulk import of card scripts based on the data defined in the JSON file, which can be useful for initializing the game with a predefined set of cards and their associated behaviors.
    def _bootstrap_from_cards_json(self) -> None:
        # runtime_sections/* lives under holywar/effects/runtime_sections;
        # cards.json is in holywar/data.
        cards_path = Path(__file__).resolve().parents[2] / "data" / "cards.json"
        if not cards_path.exists():
            return
        try:
            rows = json.loads(cards_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            key = _norm(name)
            if key not in self._scripts:
                self._scripts[key] = CardScript(name=name)

    # This method registers a card script in the registry under a normalized version of the card name. The normalization process typically involves converting the name to lowercase and removing any non-alphanumeric characters to create a consistent key for lookup. By calling this method, you can add a new `CardScript` to the registry, which can then be accessed and utilized during gameplay to define the behavior of the corresponding card.
    def register_script(self, script: CardScript) -> None:
        self._scripts[_norm(script.name)] = script

    def apply_rule(self, engine, rule: str, value=None, **context):
        """Apply rule extensions defined in card files, in registration order."""
        for script in tuple(self._scripts.values()):
            hook = script.rule_hooks.get(rule)
            if hook is not None:
                value = hook(self, engine, value, **context)
        return value

    def get_player_counter(self, engine, player_idx: int, key: str) -> int:
        return int(self.apply_rule(engine, "player_counter", 0, player_idx=player_idx, key=key, operation="get"))

    def allows_quick_play(self, card_name: str, card_type: str) -> bool:
        script = self.get_script(card_name)
        return _norm(card_type) in {"benedizione", "maledizione"} or bool(
            script and script.play_requirements.get("allow_quick_play_out_of_turn", False)
        )

    def quick_target_owner(self, card_name: str, card_type: str) -> str:
        script = self.get_script(card_name)
        default = "me" if _norm(card_type) == "benedizione" else "opponent"
        return str(script.play_requirements.get("quick_target_owner", default)) if script else default

    def set_player_counter(self, engine, player_idx: int, key: str, value: int) -> None:
        self.apply_rule(engine, "player_counter", value, player_idx=player_idx, key=key, operation="set")
        self.apply_rule(engine, "refresh_continuous_effects", player_idx=player_idx)

    # This method checks if a given card name corresponds to a card script that has the "activate_once_per_turn" property set to True. It retrieves the card script from the registry using the normalized card name and returns the value of the "activate_once_per_turn" property. If the card script does not exist in the registry, it returns False by default. This method can be used to determine if a card's activation effect is limited to once per turn, which can affect how players choose to use that card during gameplay.
    def is_activate_once_per_turn(self, card_name: str) -> bool:
        script = self._scripts.get(_norm(card_name))
        return bool(script and script.activate_once_per_turn)

    # This method registers a card script in the registry based on a dictionary specification. It parses the provided dictionary to extract various properties of the card script, such as triggered effects, on-play actions, on-enter actions, and on-activate actions. The method also handles the parsing of nested structures for triggers, targets, and effects, converting them into the appropriate data classes defined in the scripting API. Once the `CardScript` is constructed from the dictionary specification, it is registered in the registry under the normalized card name. This allows for flexible and dynamic creation of card scripts based on structured data inputs.
    def register_script_from_dict(self, card_name: str, spec: dict[str, Any]) -> None:
        def _to_int_or_none(value: Any) -> int | None:
            if value is None:
                return None
            return int(value)

        # This function returns a template dictionary for player-specific flags in the runtime state. The template includes default values for various flags that indicate the player's current state in the game, such as whether they can play cards, activate effects, attack, reposition saints, and counts of saints on the field and in attack/defense positions. This template is used to initialize the player-specific state in the runtime state dictionary when ensuring that it exists in the game engine's state flags.
        def _parse_effect(raw: dict[str, Any]) -> EffectSpec:
            usage_limit_raw = raw.get("usage_limit_per_turn")
            min_targets_raw = raw.get("min_targets")
            max_targets_raw = raw.get("max_targets")
            return EffectSpec(
                action=str(raw.get("action", "")),
                amount=int(raw.get("amount", 0)),
                duration=str(raw.get("duration", "permanent")),
                amount_multiplier_card_name=str(raw.get("amount_multiplier_card_name"))
                if raw.get("amount_multiplier_card_name") is not None
                else None,
                usage_limit_per_turn=_to_int_or_none(usage_limit_raw),
                target_player=str(raw.get("target_player")) if raw.get("target_player") is not None else None,
                card_name=str(raw.get("card_name")) if raw.get("card_name") is not None else None,
                flag=raw.get("flag"),
                owner=str(raw.get("owner")) if raw.get("owner") is not None else None,
                from_zone=str(raw.get("from_zone")) if raw.get("from_zone") is not None else None,
                zone=str(raw.get("zone")) if raw.get("zone") is not None else None,
                position=str(raw.get("position")) if raw.get("position") is not None else None,
                store_as=str(raw.get("store_as")) if raw.get("store_as") is not None else None,
                stored=str(raw.get("stored")) if raw.get("stored") is not None else None,
                to_zone=str(raw.get("to_zone")) if raw.get("to_zone") is not None else None,
                threshold=_to_int_or_none(raw.get("threshold")),
                divisor=_to_int_or_none(raw.get("divisor")),
                min_targets=_to_int_or_none(min_targets_raw),
                max_targets=_to_int_or_none(max_targets_raw),
                controller_has_saint_with_name=(
                    str(raw.get("controller_has_saint_with_name"))
                    if raw.get("controller_has_saint_with_name") is not None
                    else None
                ),
                to_zone_if_controller_has_saint_with_name=(
                    str(raw.get("to_zone_if_controller_has_saint_with_name"))
                    if raw.get("to_zone_if_controller_has_saint_with_name") is not None
                    else None
                ),
                to_zone_if_condition=(
                    dict(raw.get("to_zone_if_condition", {}) or {})
                    if raw.get("to_zone_if_condition") is not None
                    else None
                ),
                to_zone_if=(str(raw.get("to_zone_if")) if raw.get("to_zone_if") is not None else None),
                shuffle_after=bool(raw.get("shuffle_after", False)),
                choice_title=str(raw.get("choice_title")) if raw.get("choice_title") is not None else None,
                choice_prompt=str(raw.get("choice_prompt")) if raw.get("choice_prompt") is not None else None,
                choice_options=[
                    dict(v) for v in list(raw.get("choice_options", []) or []) if isinstance(v, dict)
                ],
                compare_zone=str(raw.get("compare_zone")) if raw.get("compare_zone") is not None else None,
                compare_target_player=(
                    str(raw.get("compare_target_player")) if raw.get("compare_target_player") is not None else None
                ),
                tie_policy=str(raw.get("tie_policy")) if raw.get("tie_policy") is not None else None,
                tie_amount=_to_int_or_none(raw.get("tie_amount")),
                override_cost=_to_int_or_none(raw.get("override_cost")),
                top_count=_to_int_or_none(raw.get("top_count")),
                bottom_count=_to_int_or_none(raw.get("bottom_count")),
                unique_edges_only=bool(raw.get("unique_edges_only", True)),
                saint_token_to_zone=(
                    str(raw.get("saint_token_to_zone")) if raw.get("saint_token_to_zone") is not None else None
                ),
                blessing_curse_to_zone=(
                    str(raw.get("blessing_curse_to_zone")) if raw.get("blessing_curse_to_zone") is not None else None
                ),
                artifact_to_zone=(
                    str(raw.get("artifact_to_zone")) if raw.get("artifact_to_zone") is not None else None
                ),
                building_to_zone=(
                    str(raw.get("building_to_zone")) if raw.get("building_to_zone") is not None else None
                ),
                fallback_to_zone=(
                    str(raw.get("fallback_to_zone")) if raw.get("fallback_to_zone") is not None else None
                ),
                replace_occupied_artifact=bool(raw.get("replace_occupied_artifact", False)),
                replace_occupied_building=bool(raw.get("replace_occupied_building", False)),
            )

        # This function parses a raw target specification from a dictionary and converts it into a `TargetSpec` data class instance. It handles various fields that may be present in the raw target specification, such as card filters, zone specifications, owner specifications, and target limits. The function also processes nested structures for card filters and ensures that all relevant fields are properly converted to the expected types. The resulting `TargetSpec` instance can then be used in the construction of card scripts to define the targeting behavior of effects and actions.
        def _parse_target(raw: dict[str, Any]) -> TargetSpec:
            filt = raw.get("card_filter", {}) or {}
            crosses_gte_raw = filt.get("crosses_gte")
            crosses_lte_raw = filt.get("crosses_lte")
            strength_gte_raw = filt.get("strength_gte")
            strength_lte_raw = filt.get("strength_lte")
            top_n_raw = filt.get("top_n_from_zone")
            target_min_raw = raw.get("min_targets")
            target_max_raw = raw.get("max_targets")
            return TargetSpec(
                type=str(raw.get("type", "cards_controlled_by_owner")),
                card_filter=CardFilterSpec(
                    name_in=[str(v) for v in list(filt.get("name_in", []) or [])],
                    name_equals=filt.get("name_equals"),
                    name_contains=filt.get("name_contains"),
                    name_not_contains=filt.get("name_not_contains"),
                    name_not_equals_stored=filt.get("name_not_equals_stored"),
                    card_type_in=list(filt.get("card_type_in", []) or []),
                    exclude_event_card=bool(filt.get("exclude_event_card", False)),
                    exclude_buildings_if_my_building_zone_occupied=bool(
                        filt.get("exclude_buildings_if_my_building_zone_occupied", False)
                    ),
                    crosses_gte=_to_int_or_none(crosses_gte_raw),
                    crosses_lte=_to_int_or_none(crosses_lte_raw),
                    strength_gte=_to_int_or_none(strength_gte_raw),
                    strength_lte=_to_int_or_none(strength_lte_raw),
                    drawn_this_turn_only=bool(filt.get("drawn_this_turn_only", False)),
                    top_n_from_zone=_to_int_or_none(top_n_raw),
                    half_cost_lte_my_inspiration=bool(filt.get("half_cost_lte_my_inspiration", False)),
                ),
                zone=str(raw.get("zone", "field")),
                zones=list(raw.get("zones", []) or []),
                owner=str(raw.get("owner", "me")),
                min_targets=_to_int_or_none(target_min_raw),
                max_targets=_to_int_or_none(target_max_raw),
                max_targets_from=(dict(raw["max_targets_from"]) if raw.get("max_targets_from") is not None else None),
            )

        # This block of code parses the card script specification from the provided dictionary and constructs a `CardScript` instance with all the relevant properties. It handles the parsing of triggered effects, on-play actions, on-enter actions, and on-activate actions, converting them into their respective data class instances. The method then registers the constructed `CardScript` in the registry under the normalized card name, allowing it to be accessed and utilized during gameplay.
        trig_specs: list[TriggeredEffectSpec] = []
        for t in spec.get("triggered_effects", []):
            trigger_raw = dict(t.get("trigger", {}) or {})
            trigger_condition = dict(trigger_raw.get("condition", {}) or {})
            entry_condition = dict(t.get("condition", {}) or {})
            if trigger_condition and entry_condition:
                merged_condition: dict[str, Any] = {"all_of": [trigger_condition, entry_condition]}
            elif entry_condition:
                merged_condition = entry_condition
            else:
                merged_condition = trigger_condition

            # The code above merges the trigger condition and entry condition for a triggered effect. If both conditions are present, it combines them using an "all_of" logical operator, meaning that both conditions must be satisfied for the trigger to activate. If only one of the conditions is present, it uses that condition as the merged condition. If neither condition is present, the merged condition will be an empty dictionary. This merged condition is then used in the construction of the `TriggerSpec` for the triggered effect.
            trig = TriggerSpec(
                event=str(trigger_raw.get("event", "")),
                frequency=str(trigger_raw.get("frequency", "each_turn")),
                condition=merged_condition,
                exclusive_trigger_per_turn=bool(trigger_raw.get("exclusive_trigger_per_turn", False)),
                exclusive_group=str(trigger_raw.get("exclusive_group", "") or ""),
            )
            target = _parse_target(t.get("target", {}) or {})
            effect = _parse_effect(t.get("effect", {}) or {})
            trig_specs.append(TriggeredEffectSpec(trigger=trig, target=target, effect=effect))
        on_play_actions: list[ActionSpec] = []
        for a in spec.get("on_play_actions", []):
            target = _parse_target(a.get("target", {}) or {})
            effect = _parse_effect(a.get("effect", {}) or {})
            on_play_actions.append(ActionSpec(target=target, effect=effect, condition=dict(a.get("condition", {}) or {})))
        on_enter_actions: list[ActionSpec] = []
        for a in spec.get("on_enter_actions", []):
            target = _parse_target(a.get("target", {}) or {})
            effect = _parse_effect(a.get("effect", {}) or {})
            on_enter_actions.append(ActionSpec(target=target, effect=effect, condition=dict(a.get("condition", {}) or {})))
        on_activate_actions: list[ActionSpec] = []
        for a in spec.get("on_activate_actions", []):
            target = _parse_target(a.get("target", {}) or {})
            effect = _parse_effect(a.get("effect", {}) or {})
            on_activate_actions.append(
                ActionSpec(target=target, effect=effect, condition=dict(a.get("condition", {}) or {}))
            )

        # After parsing all the relevant properties from the specification dictionary, the method constructs a `CardScript` instance with the parsed triggered effects and actions. It also sets various properties of the `CardScript` based on the values in the specification, such as play modes, targeting modes, attack properties, and cost modifications. Finally, it registers the constructed `CardScript` in the registry under the normalized card name, making it available for use during gameplay.
        self.register_script(
            CardScript(
                name=card_name,
                action_handlers=dict(spec.get("action_handlers", {}) or {}),
                rule_hooks=dict(spec.get("rule_hooks", {}) or {}),
                targeting_handlers=dict(spec.get("targeting_handlers", {}) or {}),
                target_payload_prefix=str(spec.get("target_payload_prefix", "")),
                counter_tag=spec.get("counter_tag"),
                on_play_mode=str(spec.get("on_play_mode", "auto")),
                on_enter_mode=str(spec.get("on_enter_mode", "auto")),
                on_activate_mode=str(spec.get("on_activate_mode", "auto")),
                activate_once_per_turn=bool(spec.get("activate_once_per_turn", False)),
                play_owner=str(spec.get("play_owner", "me")),
                can_play_from_hand=bool(spec.get("can_play_from_hand", True)),
                play_targeting=str(spec.get("play_targeting", "auto")),
                activate_targeting=str(spec.get("activate_targeting", "auto")),
                attack_targeting=str(spec.get("attack_targeting", "auto")),
                can_activate_by_any_player=bool(spec.get("can_activate_by_any_player", False)),
                can_attack=bool(spec.get("can_attack", True)),
                attack_requirements=dict(spec.get("attack_requirements", {}) or {}),
                attack_blocked_message=(
                    str(spec.get("attack_blocked_message"))
                    if spec.get("attack_blocked_message") is not None
                    else None
                ),
                can_attack_from_defense=bool(spec.get("can_attack_from_defense", False)),
                can_attack_multiple_targets_in_attack_per_turn=bool(
                    spec.get("can_attack_multiple_targets_in_attack_per_turn", False)
                ),
                blocks_enemy_attackers_with_crosses_lte=(
                    int(spec["blocks_enemy_attackers_with_crosses_lte"])
                    if spec.get("blocks_enemy_attackers_with_crosses_lte") is not None
                    else None
                ),
                prevent_incoming_damage_if_less_than=(
                    int(spec["prevent_incoming_damage_if_less_than"])
                    if spec.get("prevent_incoming_damage_if_less_than") is not None
                    else None
                ),
                prevent_incoming_damage_to_card_types=[
                    str(v) for v in list(spec.get("prevent_incoming_damage_to_card_types", []) or [])
                ],
                battle_survival_mode=str(spec.get("battle_survival_mode", "none")),
                battle_survival_names=list(spec.get("battle_survival_names", []) or []),
                battle_survival_token_name=(
                    str(spec.get("battle_survival_token_name")) if spec.get("battle_survival_token_name") is not None else None
                ),
                battle_survival_restore_faith=(
                    int(spec.get("battle_survival_restore_faith", 0))
                    if spec.get("battle_survival_restore_faith") is not None
                    else None
                ),
                battle_excommunicate_on_lethal=bool(spec.get("battle_excommunicate_on_lethal", False)),
                post_battle_forced_destroy=bool(spec.get("post_battle_forced_destroy", False)),
                turn_start_summon_token_name=(
                    str(spec.get("turn_start_summon_token_name")) if spec.get("turn_start_summon_token_name") is not None else None
                ),
                auto_play_on_draw=bool(spec.get("auto_play_on_draw", False)),
                end_turn_on_draw=bool(spec.get("end_turn_on_draw", False)),
                strength_bonus_rules=[dict(rule) for rule in spec.get("strength_bonus_rules", []) if isinstance(rule, dict)],
                incoming_damage_from_enemy_saints_divisor=max(
                    1,
                    int(spec.get("incoming_damage_from_enemy_saints_divisor", 1) or 1),
                ),
                strength_gain_on_damage_to_enemy_saint=int(spec.get("strength_gain_on_damage_to_enemy_saint", 0) or 0),
                strength_gain_on_lethal_to_enemy_saint=int(spec.get("strength_gain_on_lethal_to_enemy_saint", 0) or 0),
                grants_strength_to_friendly_saints=int(spec.get("grants_strength_to_friendly_saints", 0) or 0),
                grants_strength_to_friendly_saints_except_names=[
                    str(v) for v in list(spec.get("grants_strength_to_friendly_saints_except_names", []) or [])
                ],
                modifies_enemy_saints_strength=int(spec.get("modifies_enemy_saints_strength", 0) or 0),
                blocks_enemy_artifact_slots=max(0, int(spec.get("blocks_enemy_artifact_slots", 0) or 0)),
                prevent_effect_destruction_of_friendly_saints_from_source_card_types=[
                    str(v)
                    for v in list(
                        spec.get("prevent_effect_destruction_of_friendly_saints_from_source_card_types", []) or []
                    )
                ],
                prevent_targeting_of_friendly_saints_from_enemy_card_types=[
                    str(v)
                    for v in list(
                        spec.get("prevent_targeting_of_friendly_saints_from_enemy_card_types", []) or []
                    )
                ],
                protection_rules=[
                    dict(v) for v in list(spec.get("protection_rules", []) or []) if isinstance(v, dict)
                ],
                retaliation_damage_to_enemy_attacker=int(spec.get("retaliation_damage_to_enemy_attacker", 0) or 0),
                retaliation_reduce_sin_on_kill=int(spec.get("retaliation_reduce_sin_on_kill", 0) or 0),
                retaliation_multiplier_for_friendly_building_name=(
                    str(spec.get("retaliation_multiplier_for_friendly_building_name"))
                    if spec.get("retaliation_multiplier_for_friendly_building_name") is not None
                    else None
                ),
                play_requirements=dict(spec.get("play_requirements", {}) or {}),
                play_cost_fixed=(int(spec["play_cost_fixed"]) if spec.get("play_cost_fixed") is not None else None),
                play_cost_reduction_if_controller_has_card_type_in_hand=[
                    str(v) for v in list(spec.get("play_cost_reduction_if_controller_has_card_type_in_hand", []) or [])
                ],
                play_cost_zero_if_controller_has_saint_with_name=(
                    str(spec.get("play_cost_zero_if_controller_has_saint_with_name"))
                    if spec.get("play_cost_zero_if_controller_has_saint_with_name") is not None
                    else None
                ),
                play_cost_zero_if_controller_has_no_saints=bool(
                    spec.get("play_cost_zero_if_controller_has_no_saints", False)
                ),
                auto_play_drawn_cards_with_faith_lte=(
                    int(spec["auto_play_drawn_cards_with_faith_lte"])
                    if spec.get("auto_play_drawn_cards_with_faith_lte") is not None
                    else None
                ),
                halves_friendly_saint_play_cost=bool(spec.get("halves_friendly_saint_play_cost", False)),
                halve_friendly_saint_play_cost_excludes_self=bool(
                    spec.get("halve_friendly_saint_play_cost_excludes_self", True)
                ),
                doubles_enemy_play_cost=bool(spec.get("doubles_enemy_play_cost", False)),
                is_pyramid=bool(spec.get("is_pyramid", False)),
                pyramid_strength_bonus_threshold=(
                    int(spec["pyramid_strength_bonus_threshold"])
                    if spec.get("pyramid_strength_bonus_threshold") is not None
                    else None
                ),
                pyramid_strength_bonus_amount=(
                    int(spec["pyramid_strength_bonus_amount"])
                    if spec.get("pyramid_strength_bonus_amount") is not None
                    else None
                ),
                pyramid_summon_extra_base_faith_threshold=(
                    int(spec["pyramid_summon_extra_base_faith_threshold"])
                    if spec.get("pyramid_summon_extra_base_faith_threshold") is not None
                    else None
                ),
                pyramid_summon_extra_base_faith_multiplier=(
                    int(spec["pyramid_summon_extra_base_faith_multiplier"])
                    if spec.get("pyramid_summon_extra_base_faith_multiplier") is not None
                    else None
                ),
                pyramid_turn_draw_bonus_threshold=(
                    int(spec["pyramid_turn_draw_bonus_threshold"])
                    if spec.get("pyramid_turn_draw_bonus_threshold") is not None
                    else None
                ),
                pyramid_turn_draw_bonus_amount=(
                    int(spec["pyramid_turn_draw_bonus_amount"])
                    if spec.get("pyramid_turn_draw_bonus_amount") is not None
                    else None
                ),
                provides_player_counter=bool(spec.get("provides_player_counter", False)),
                inverts_saint_summon_controller=bool(spec.get("inverts_saint_summon_controller", False)),
                destroy_requires_building_or_artifacts_and_inspiration=dict(
                    spec.get("destroy_requires_building_or_artifacts_and_inspiration", {}) or {}
                ),
                indestructible_except_own_activation=bool(spec.get("indestructible_except_own_activation", False)),
                immune_to_actions=[str(v) for v in list(spec.get("immune_to_actions", []) or []) if str(v).strip()],
                triggered_effects=trig_specs,
                on_play_actions=on_play_actions,
                on_enter_actions=on_enter_actions,
                on_activate_actions=on_activate_actions,
                faith_bonus_rules=[dict(v) for v in list(spec.get("faith_bonus_rules", []) or []) if isinstance(v, dict)],
                counted_bonuses=[dict(v) for v in list(spec.get("counted_bonuses", []) or []) if isinstance(v, dict)],
            )
        )

    # This method bootstraps the card scripts from individual script files. It iterates through the card scripts provided by the `iter_card_scripts` function, which typically reads from a designated directory of script files. For each card name and its corresponding specification, it registers the card script in the registry using the `register_script_from_dict` method. This allows for a modular approach to defining card scripts, where each card's behavior can be specified in its own file, making it easier to manage and update individual card scripts without affecting others.
    def _bootstrap_from_script_files(self) -> None:
        for card_name, spec in iter_card_scripts():
            self.register_script_from_dict(card_name, spec)

    # This method ensures that all cards present in the game engine's state have corresponding card scripts registered in the registry. It first checks if the registry is already populated with scripts, and if not, it bootstraps the scripts from the JSON file and script files. Then, it iterates through all card instances in the game engine's state and checks if each card's name has a corresponding script in the registry. If a card does not have a registered script, it creates a new `CardScript` with just the name and registers it. Finally, it ensures that the game engine is subscribed to the necessary events for tracking card scripts. This method is crucial for maintaining consistency between the cards in play and their associated scripts, especially during migration from older formats.
    def ensure_all_cards_migrated(self, engine: GameEngine) -> None:
        if not self._scripts:
            self._bootstrap_from_cards_json()
            self._bootstrap_from_script_files()
        for inst in engine.state.instances.values():
            key = _norm(inst.definition.name)
            if key not in self._scripts:
                self._scripts[key] = CardScript(name=inst.definition.name)
        self._ensure_leave_subscription(engine)

    # This method tracks the subscription of the game engine to prevent duplicate bindings for card scripts. It uses a set to keep track of the IDs of engines that have already been subscribed. If the engine's ID is already in the set, it means that the engine has already been subscribed, and the method returns without doing anything. If the engine's ID is not in the set, it adds the ID to the set, indicating that the engine is now subscribed. This mechanism helps to ensure that event handlers for card scripts are not registered multiple times for the same engine, which could lead to unintended behavior during gameplay.
    def _ensure_leave_subscription(self, engine: "GameEngine") -> None:
        """Subscribe once to the lifecycle event that removes field effects."""
        engine_id = id(engine)
        if engine_id in self._subscribed_engines:
            return
        self._subscribed_engines.add(engine_id)
        engine.rules_api(0).subscribe("on_this_card_leaves_field", self._on_source_leaves_field)

    # This method checks if a given card name has a corresponding card script that has been migrated to the registry. It normalizes the card name and checks if it exists in the `_scripts` dictionary. If the normalized card name is found in the registry, it returns True, indicating that the card has been migrated; otherwise, it returns False. This method can be used to verify whether a card's script has been properly registered in the new format during the migration process.
    def is_migrated(self, card_name: str) -> bool:
        return _norm(card_name) in self._scripts

    # This method retrieves the `CardScript` associated with a given card name from the registry. It normalizes the card name and looks it up in the `_scripts` dictionary. If a corresponding `CardScript` is found, it is returned; otherwise, the method returns None. This allows other parts of the game engine to access the properties and behaviors defined in the `CardScript` for a specific card during gameplay.
    def get_script(self, card_name: str) -> CardScript | None:
        return self._scripts.get(_norm(card_name))

    # The following methods are accessors for specific properties of card scripts. They retrieve the `CardScript` for a given card name and return the relevant property, providing default values if the script is not found or if the property is not set. These accessors allow other parts of the game engine to easily query important information about how a card should behave during play, such as its targeting mode, play cost, and attack capabilities.
    def get_play_targeting_mode(self, card_name: str) -> str:
        script = self.get_script(card_name)
        if script is None:
            return "auto"
        return str(script.play_targeting or "auto").strip().lower() or "auto"

    # This method retrieves the owner of the play action for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `play_owner` property. If the script is not found or if the `play_owner` property is not set, it defaults to "me". The returned value is normalized to be lowercase and stripped of any leading or trailing whitespace. This information can be used to determine which player is considered the owner of the play action for that card during gameplay.
    def get_play_owner(self, card_name: str) -> str:
        script = self.get_script(card_name)
        if script is None:
            return "me"
        return str(script.play_owner or "me").strip().lower() or "me"

    # This method retrieves the fixed play cost for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `play_cost_fixed` property. If the script is not found or if the `play_cost_fixed` property is not set, it returns None. This information can be used to determine if a card has a specific fixed cost to play, which can affect how players manage their resources during gameplay.
    def get_play_cost_fixed(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.play_cost_fixed

    # This method retrieves a list of card types that, if present in the controller's hand, would reduce the play cost of a given card. It looks up the `CardScript` for the specified card name and returns the value of the `play_cost_reduction_if_controller_has_card_type_in_hand` property as a list of strings. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card's play cost can be reduced based on the presence of certain card types in the player's hand, which can influence strategic decisions during gameplay.
    def get_play_cost_reduction_if_controller_has_card_type_in_hand(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [str(v) for v in script.play_cost_reduction_if_controller_has_card_type_in_hand if str(v).strip()]

    # This method retrieves the name of a saint that, if controlled by the player, would allow the play cost of a given card to be reduced to zero. It looks up the `CardScript` for the specified card name and returns the value of the `play_cost_zero_if_controller_has_saint_with_name` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card can be played for free based on the presence of a specific saint under the player's control, which can affect strategic decisions during gameplay.
    def get_play_cost_zero_if_controller_has_saint_with_name(self, card_name: str) -> str | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        value = str(script.play_cost_zero_if_controller_has_saint_with_name or "").strip()
        return value or None

    # This method checks if the play cost of a given card should be reduced to zero if the controller has no saints under their control. It looks up the `CardScript` for the specified card name and returns the value of the `play_cost_zero_if_controller_has_no_saints` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card can be played for free when the player has no saints in play, which can influence strategic decisions during gameplay, especially in situations where the player is at a disadvantage.
    def get_play_cost_zero_if_controller_has_no_saints(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.play_cost_zero_if_controller_has_no_saints)

    def get_auto_play_drawn_cards_with_faith_lte(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None or script.auto_play_drawn_cards_with_faith_lte is None:
            return None
        return int(script.auto_play_drawn_cards_with_faith_lte)

    # This method checks if the play cost of a given card should be halved for friendly saints. It looks up the `CardScript` for the specified card name and returns the value of the `halves_friendly_saint_play_cost` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card's play cost is reduced for friendly saints, which can affect how players choose to play that card in relation to their existing saints on the field.
    def get_halves_friendly_saint_play_cost(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.halves_friendly_saint_play_cost)

    # This method checks if the halving of play cost for friendly saints should exclude the card itself. It looks up the `CardScript` for the specified card name and returns the value of the `halve_friendly_saint_play_cost_excludes_self` property as a boolean. If the script is not found, it defaults to True. This information can be used to determine if a card that halves the play cost for friendly saints should also apply that halving effect to itself when being played, which can influence strategic decisions during gameplay.
    def get_halve_friendly_saint_play_cost_excludes_self(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return True
        return bool(script.halve_friendly_saint_play_cost_excludes_self)

    # This method checks if the play cost of a given card should be doubled for enemy players. It looks up the `CardScript` for the specified card name and returns the value of the `doubles_enemy_play_cost` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card's play cost is increased for enemy players, which can affect how opponents choose to interact with that card during gameplay.
    def get_doubles_enemy_play_cost(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.doubles_enemy_play_cost)

    # This method checks if a given card is considered a pyramid. It looks up the `CardScript` for the specified card name and returns the value of the `is_pyramid` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has special interactions or properties associated with being a pyramid, which can influence strategic decisions during gameplay.
    def get_activate_targeting_mode(self, card_name: str) -> str:
        script = self.get_script(card_name)
        if script is None:
            return "auto"
        return str(script.activate_targeting or "auto").strip().lower() or "auto"

    # This method retrieves the attack targeting mode for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `attack_targeting` property. If the script is not found or if the `attack_targeting` property is not set, it defaults to "auto". The returned value is normalized to be lowercase and stripped of any leading or trailing whitespace. This information can be used to determine how a card should select its attack targets during combat in gameplay.
    def get_attack_targeting_mode(self, card_name: str) -> str:
        script = self.get_script(card_name)
        if script is None:
            return "auto"
        return str(script.attack_targeting or "auto").strip().lower() or "auto"

    # This method checks if a given card is allowed to attack based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `can_attack` property as a boolean. If the script is not found, it defaults to True, meaning that if there is no specific script for the card, it is assumed that the card can attack. This information can be used to determine if a card has any restrictions on attacking during combat in gameplay.
    def get_can_attack(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return True
        return bool(script.can_attack)

    # This method evaluates whether a given card can attack at the current moment based on its attack requirements defined in the card script. It retrieves the `CardScript` for the specified card instance and checks if there are any attack requirements specified. If there are no requirements, it returns True, indicating that the card can attack. If there are requirements, it evaluates them using the `_eval_condition_node` method, passing in the appropriate context for the "can_attack" event. If the evaluation returns True, it means the card can attack; otherwise, it constructs an appropriate message to indicate why the card cannot attack and returns False along with that message. This method is crucial for enforcing any special conditions or restrictions on attacking that may be defined in a card's script during gameplay.
    def can_attack_now(self, engine: GameEngine, player_idx: int, uid: str) -> tuple[bool, str | None]:
        inst = engine.state.instances.get(uid)
        if inst is None:
            return False, "Carta attaccante non valida."
        script = self.get_script(inst.effect_name)
        if script is None or not script.attack_requirements:
            return True, None
        ok = self._eval_condition_node(
            RuleEventContext(engine=engine, event="can_attack", player_idx=player_idx, payload={"card": uid}),
            player_idx,
            script.attack_requirements,
        )
        if ok:
            return True, None
        msg = (script.attack_blocked_message or "").strip() or f"{inst.definition.name} non puo attaccare."
        return False, msg

    # This method checks if a given card can attack from the defense position based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `can_attack_from_defense` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has the ability to attack while in a defensive stance during combat in gameplay.
    def get_can_attack_from_defense(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.can_attack_from_defense)

    # This method checks if a given card can attack multiple targets in a single attack per turn based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `can_attack_multiple_targets_in_attack_per_turn` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has the capability to target multiple opponents during an attack in gameplay, which can influence strategic decisions during combat.
    def get_can_attack_multiple_targets_in_attack_per_turn(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.can_attack_multiple_targets_in_attack_per_turn)

    # This method retrieves the maximum number of crosses that an enemy attacker can have for a given card to be able to block it, based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `blocks_enemy_attackers_with_crosses_lte` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has specific blocking capabilities against enemy attackers with a certain number of crosses during combat in gameplay.
    def get_blocks_enemy_attackers_with_crosses_lte(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        raw = script.blocks_enemy_attackers_with_crosses_lte
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    # This method retrieves the threshold for preventing incoming damage based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `prevent_incoming_damage_if_less_than` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a defensive mechanism that prevents it from taking damage if its strength is below a certain threshold during gameplay.
    def get_prevent_incoming_damage_if_less_than(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.prevent_incoming_damage_if_less_than

    # This method retrieves a list of card types that are protected from incoming damage based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `prevent_incoming_damage_to_card_types` property as a list of strings. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific immunities to damage from certain types of cards during gameplay.
    def get_prevent_incoming_damage_to_card_types(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [str(v) for v in script.prevent_incoming_damage_to_card_types if str(v).strip()]

    # This method retrieves the battle survival mode for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `battle_survival_mode` property. If the script is not found or if the `battle_survival_mode` property is not set, it defaults to "none". The returned value is normalized to be lowercase and stripped of any leading or trailing whitespace. This information can be used to determine how a card behaves in terms of survival during battles in gameplay.
    def get_battle_survival_mode(self, card_name: str) -> str:
        script = self.get_script(card_name)
        if script is None:
            return "none"
        return str(script.battle_survival_mode or "none").strip().lower() or "none"

    # This method retrieves a list of names associated with battle survival for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `battle_survival_names` property as a list of strings. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific names that are relevant to its survival during battles in gameplay, which can influence how players strategize around that card.
    def get_battle_survival_names(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [str(name) for name in script.battle_survival_names if str(name).strip()]

    # This method retrieves the name of the token associated with battle survival for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `battle_survival_token_name` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a specific token that is relevant to its survival during battles in gameplay, which can influence how players manage their resources and strategies around that card.
    def get_battle_survival_token_name(self, card_name: str) -> str | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        value = str(script.battle_survival_token_name or "").strip()
        return value or None

    # This method retrieves the amount of faith that should be restored for battle survival for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `battle_survival_restore_faith` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a mechanism for restoring faith as part of its survival during battles in gameplay, which can influence how players manage their resources and strategies around that card.
    def get_battle_survival_restore_faith(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.battle_survival_restore_faith

    # This method checks if a given card should be excommunicated upon receiving lethal damage based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `battle_excommunicate_on_lethal` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has a specific consequence of being excommunicated when it receives lethal damage during battles in gameplay, which can influence how players approach combat with that card.
    def get_battle_excommunicate_on_lethal(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.battle_excommunicate_on_lethal)

    # This method checks if a given card should be forced to be destroyed after battle based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `post_battle_forced_destroy` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has a specific consequence of being destroyed after battle during gameplay, which can influence how players approach combat with that card.
    def get_post_battle_forced_destroy(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.post_battle_forced_destroy)

    # This method retrieves the name of the token that should be summoned at the start of the turn for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `turn_start_summon_token_name` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a specific token that it summons at the start of the turn during gameplay, which can influence how players manage their resources and strategies around that card.
    def get_turn_start_summon_token_name(self, card_name: str) -> str | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        value = str(script.turn_start_summon_token_name or "").strip()
        return value or None

    # This method checks if a given card should be automatically played when drawn based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `auto_play_on_draw` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has a specific behavior of being played immediately upon being drawn during gameplay, which can influence how players manage their decks and strategies around that card.
    def get_auto_play_on_draw(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.auto_play_on_draw)

    # This method checks if a given card should end the turn when drawn based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `end_turn_on_draw` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has a specific behavior of ending the player's turn immediately upon being drawn during gameplay, which can influence how players manage their decks and strategies around that card.
    def get_end_turn_on_draw(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.end_turn_on_draw)

    # This method retrieves a list of strength bonus rules for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `strength_bonus_rules` property as a list of dictionaries. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific rules for gaining strength bonuses during gameplay, which can influence how players strategize around that card.
    def get_strength_bonus_rules(self, card_name: str) -> list[dict[str, Any]]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [dict(rule) for rule in script.strength_bonus_rules]

    # This method retrieves a list of faith bonus rules for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `faith_bonus_rules` property as a list of dictionaries. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific rules for gaining faith bonuses during gameplay, which can influence how players strategize around that card.
    def get_faith_bonus_rules(self, card_name: str) -> list[dict]:
        script = self.get_script(card_name)
        if script is None:
            return []
        raw = getattr(script, "faith_bonus_rules", None)
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        return []

    # This method recalculates and refreshes the conditional faith bonuses for all cards on the field that are owned by a specific player. It iterates through all cards in the player's attack and defense zones, checks for any existing conditional faith bonuses, and removes them. Then, it evaluates the faith bonus rules defined in the card scripts for each card and applies any new conditional faith bonuses based on the current game state. This ensures that the faith bonuses for cards are always up to date with the current conditions of the game, which can affect gameplay strategies and outcomes.
    def refresh_conditional_faith_bonuses(self, engine: "GameEngine", owner_idx: int) -> None:
        player = engine.state.players[owner_idx]
        field_uids = [uid for uid in (player.attack + player.defense) if uid]

        for uid in field_uids:
            inst = engine.state.instances[uid]
            base_faith = inst.definition.faith if inst.definition.faith is not None else 0

            old_bonus = 0
            kept_tags: list[str] = []
            for tag in inst.blessed:
                if isinstance(tag, str) and tag.startswith("conditional_faith_bonus:"):
                    try:
                        old_bonus += int(tag.split(":", 1)[1])
                    except ValueError:
                        pass
                else:
                    kept_tags.append(tag)
            inst.blessed = kept_tags

            # Recalculate bonuses
            new_bonus = 0
            for rule in self.get_faith_bonus_rules(inst.effect_name):
                amount_mode_key = _norm(str(rule.get("amount_mode", "flat")))
                if amount_mode_key == "per_count_div_floor":
                    req = dict(rule.get("requirement", {}) or {})
                    candidates = self._collect_cards_for_requirement(engine, owner_idx, req)
                    threshold = max(0, int(rule.get("threshold", 1) or 1))
                    if len(candidates) < threshold:
                        continue
                    divisor = max(1, int(rule.get("divisor", 1) or 1))
                    per_amount = int(rule.get("amount", 0) or 0)
                    new_bonus += (len(candidates) // divisor) * per_amount
                    continue

                required_name = str(rule.get("controller_has_card_with_name", "")).strip()
                required_zone = str(rule.get("controller_has_card_zone", "field")).strip().lower() or "field"
                required_self_name = str(rule.get("if_card_name", "")).strip()

                if required_self_name and _norm(inst.definition.name) != _norm(required_self_name):
                    continue
                
                # Check if the required card is in the specified zone
                in_zone = False
                if required_name:
                    if required_zone == "field":
                        in_zone = any(
                            _norm(engine.state.instances[f_uid].definition.name) == _norm(required_name)
                            for f_uid in field_uids
                        )
                    elif required_zone == "hand":
                        in_zone = any(
                            _norm(engine.state.instances[h_uid].definition.name) == _norm(required_name)
                            for h_uid in player.hand
                        )
                    elif required_zone in {"deck", "relicario"}:
                        in_zone = any(
                            _norm(engine.state.instances[d_uid].definition.name) == _norm(required_name)
                            for d_uid in player.deck
                        )
                    elif required_zone == "graveyard":
                        in_zone = any(
                            _norm(engine.state.instances[g_uid].definition.name) == _norm(required_name)
                            for g_uid in player.graveyard
                        )
                    elif required_zone == "excommunicated":
                        in_zone = any(
                            _norm(engine.state.instances[e_uid].definition.name) == _norm(required_name)
                            for e_uid in player.excommunicated
                        )

                    if not in_zone:
                        continue

                new_bonus += int(rule.get("self_bonus", 0) or 0)

            # Add contextual faith auras sourced from cards on the field (e.g. dynamic building effects).
            new_bonus += self.get_context_bonus_amount(
                engine,
                owner_idx,
                context="faith",
                amount_mode="flat",
                target_uid=uid,
            )
            new_bonus += self.get_context_bonus_amount(
                engine,
                owner_idx,
                context="faith",
                amount_mode="per_count_div_floor",
                target_uid=uid,
            )

            # Apply the new bonus if it has changed
            current_faith = inst.current_faith if inst.current_faith is not None else base_faith
            delta = new_bonus - old_bonus
            if delta != 0:
                inst.current_faith = max(0, current_faith + delta)

            if new_bonus:
                inst.blessed.append(f"conditional_faith_bonus:{new_bonus}")

    # This method checks if a given card is considered a pyramid based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `is_pyramid` property as a boolean. If the script is not found, it defaults to False. This information can be used to determine if a card has special interactions or properties associated with being a pyramid, which can influence strategic decisions during gameplay.
    def get_is_pyramid(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.is_pyramid)

    # This method retrieves the threshold for gaining a strength bonus for a pyramid card based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_strength_bonus_threshold` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific threshold that, when met, grants it a strength bonus during gameplay, which can influence how players strategize around that card.
    def get_pyramid_strength_bonus_threshold(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_strength_bonus_threshold

    # This method retrieves the amount of strength bonus that a pyramid card should receive based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_strength_bonus_amount` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific strength bonus that it gains under certain conditions during gameplay, which can influence how players strategize around that card.
    def get_pyramid_strength_bonus_amount(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_strength_bonus_amount

    # This method retrieves the threshold for gaining an extra base faith bonus for a pyramid card based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_summon_extra_base_faith_threshold` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific threshold that, when met, grants it an extra base faith bonus during gameplay, which can influence how players strategize around that card.
    def get_pyramid_summon_extra_base_faith_threshold(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_summon_extra_base_faith_threshold

    # This method retrieves the amount of extra base faith bonus that a pyramid card should receive when summoned based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_summon_extra_base_faith_multiplier` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific extra base faith bonus that it gains when summoned under certain conditions during gameplay, which can influence how players strategize around that card.
    def get_pyramid_summon_extra_base_faith_multiplier(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_summon_extra_base_faith_multiplier

    # This method retrieves the threshold for gaining a draw bonus for a pyramid card based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_turn_draw_bonus_threshold` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific threshold that, when met, grants it a draw bonus during the turn in gameplay, which can influence how players strategize around that card.
    def get_pyramid_turn_draw_bonus_threshold(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_turn_draw_bonus_threshold

    # This method retrieves the amount of draw bonus that a pyramid card should receive during the turn based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `pyramid_turn_draw_bonus_amount` property. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a pyramid card has a specific draw bonus that it gains during the turn under certain conditions during gameplay, which can influence how players strategize around that card.
    def get_pyramid_turn_draw_bonus_amount(self, card_name: str) -> int | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        return script.pyramid_turn_draw_bonus_amount

    def get_provides_player_counter(self, card_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        return bool(script.provides_player_counter)

    # This method checks if a given card is immune to a specific action based on its card script. It looks up the `CardScript` for the specified card name and checks if the normalized action name is present in the list of immune actions defined in the script. If the script is not found, it defaults to False, meaning that if there is no specific script for the card, it is assumed that the card is not immune to any actions. This information can be used to determine if a card has specific immunities to certain actions during gameplay, which can influence strategic decisions around that card.
    def is_immune_to_action(self, card_name: str, action_name: str) -> bool:
        script = self.get_script(card_name)
        if script is None:
            return False
        wanted = _norm(action_name)
        return any(_norm(v) == wanted for v in script.immune_to_actions)

    # This method retrieves a list of counted bonuses for a given card name and an optional context from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `counted_bonuses` property as a list of dictionaries. If the script is not found or if the property is not set, it returns an empty list. If a context is provided, it filters the bonuses to include only those that match the specified context. This information can be used to determine if a card has specific bonuses that are counted under certain conditions during gameplay, which can influence how players strategize around that card.
    def get_counted_bonuses(self, card_name: str, context: str | None = None) -> list[dict[str, Any]]:
        script = self.get_script(card_name)
        if script is None:
            return []
        items = [dict(v) for v in script.counted_bonuses if isinstance(v, dict)]
        if context is None:
            return items
        wanted = _norm(context)
        return [it for it in items if _norm(str(it.get("context", ""))) == wanted]

    # This method calculates the total amount of context bonuses for a given player based on the counted bonuses defined in the card scripts of the cards they have on the field. It iterates through all the cards in the player's attack and defense zones, as well as their building if they have one, and collects any counted bonuses that match the specified context and amount mode. It then groups these bonuses according to their defined grouping and stacking rules, and sums them up to return the total bonus amount. This information can be used to determine how much of a certain bonus a player should receive based on the current state of their cards on the field during gameplay.
    def get_context_bonus_amount(
        self,
        engine: GameEngine,
        owner_idx: int,
        context: str,
        amount_mode: str = "flat",
        target_uid: str | None = None,
    ) -> int:
        player = engine.state.players[owner_idx]
        field_uids = [uid for uid in player.attack + player.defense + player.artifacts if uid]
        if player.building:
            field_uids.append(player.building)

        # Calculate bonuses
        grouped: dict[str, int] = {}
        for source_uid in field_uids:
            source_inst = engine.state.instances.get(source_uid)
            if source_inst is None:
                continue
            rules = self.get_counted_bonuses(source_inst.effect_name, context=context)
            for idx, rule in enumerate(rules):
                if _norm(str(rule.get("amount_mode", "flat"))) != _norm(amount_mode):
                    continue
                applies_to = _norm(str(rule.get("applies_to", "all")))
                if applies_to == "self" and target_uid and source_uid != target_uid:
                    continue
                if target_uid:
                    target_inst = engine.state.instances.get(target_uid)
                    allowed_target_types = {_norm(str(v)) for v in list(rule.get("target_card_type_in", []) or [])}
                    if allowed_target_types:
                        if target_inst is None or _norm(target_inst.definition.card_type) not in allowed_target_types:
                            continue
                req = dict(rule.get("requirement", {}) or {})
                candidates = self._collect_cards_for_requirement(engine, owner_idx, req)
                if bool(rule.get("distinct_by_name", False)):
                    seen: set[str] = set()
                    distinct: list[str] = []
                    for uid in candidates:
                        inst = engine.state.instances.get(uid)
                        if inst is None:
                            continue
                        name_key = _norm(inst.definition.name)
                        if name_key in seen:
                            continue
                        seen.add(name_key)
                        distinct.append(uid)
                    candidates = distinct
                threshold = max(0, int(rule.get("threshold", 1) or 1))
                if len(candidates) < threshold:
                    continue
                amount_mode_key = _norm(str(rule.get("amount_mode", "flat")))
                if amount_mode_key == "per_count_div_floor":
                    divisor = max(1, int(rule.get("divisor", 1) or 1))
                    per_amount = int(rule.get("amount", 0) or 0)
                    amount = (len(candidates) // divisor) * per_amount
                else:
                    amount = int(rule.get("amount", 0) or 0)
                if amount == 0:
                    continue
                group = str(rule.get("group", "")).strip() or f"{source_uid}:{idx}"
                stacking = _norm(str(rule.get("stacking", "max")))
                if stacking == "sum":
                    grouped[group] = int(grouped.get(group, 0)) + amount
                else:
                    grouped[group] = max(int(grouped.get(group, 0)), amount)
        return int(sum(grouped.values()))

    # This method retrieves the divisor for incoming damage from enemy saints for a given card name from the card script. It looks up the `CardScript` for the specified card name and returns the value of the `incoming_damage_from_enemy_saints_divisor` property as an integer. If the script is not found or if the property is not set, it defaults to 1. This information can be used to determine if a card has a specific mechanic that reduces incoming damage from enemy saints by dividing it by a certain amount during gameplay, which can influence how players strategize around that card.
    def get_incoming_damage_from_enemy_saints_divisor(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 1
        return max(1, int(script.incoming_damage_from_enemy_saints_divisor or 1))

    # This method retrieves the amount of strength that should be gained when a card damages an enemy saint based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `strength_gain_on_damage_to_enemy_saint` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that grants it strength when it damages an enemy saint during gameplay, which can influence how players strategize around that card.
    def get_strength_gain_on_damage_to_enemy_saint(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.strength_gain_on_damage_to_enemy_saint or 0)

    # This method retrieves the amount of strength that should be gained when a card delivers a lethal blow to an enemy saint based on its card script. It looks up the `CardScript` for the specified card name and returns the value of the `strength_gain_on_lethal_to_enemy_saint` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that grants it strength when it delivers a lethal blow to an enemy saint during gameplay, which can influence how players strategize around that card.
    def get_strength_gain_on_lethal_to_enemy_saint(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.strength_gain_on_lethal_to_enemy_saint or 0)

    # This method retrieves the amount of strength that should be granted to friendly saints based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `grants_strength_to_friendly_saints` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that grants strength to friendly saints during gameplay, which can influence how players strategize around that card.
    def get_grants_strength_to_friendly_saints(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.grants_strength_to_friendly_saints or 0)

    # This method retrieves a list of names of friendly saints that should be excluded from receiving strength bonuses based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `grants_strength_to_friendly_saints_except_names` property as a list of strings. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific mechanics that grant strength to friendly saints while excluding certain named saints during gameplay, which can influence how players strategize around that card.
    def get_grants_strength_to_friendly_saints_except_names(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [str(v) for v in script.grants_strength_to_friendly_saints_except_names if str(v).strip()]

    # This method retrieves the amount of strength that should be reduced for enemy saints based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `modifies_enemy_saints_strength` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that reduces the strength of enemy saints during gameplay, which can influence how players strategize around that card.
    def get_modifies_enemy_saints_strength(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.modifies_enemy_saints_strength or 0)

    def get_blocks_enemy_artifact_slots(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return max(0, int(script.blocks_enemy_artifact_slots or 0))

    # This method retrieves a list of names of friendly saints that should be prevented from being destroyed by effects based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `prevent_effect_destruction_of_friendly_saints_from_source_card_types` property as a list of strings. If the script is not found or if the property is not set, it returns an empty list. This information can be used to determine if a card has specific mechanics that prevent certain friendly saints from being destroyed by effects during gameplay, which can influence how players strategize around that card.
    def get_prevent_effect_destruction_of_friendly_saints_from_source_card_types(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [
            str(v).strip().lower()
            for v in script.prevent_effect_destruction_of_friendly_saints_from_source_card_types
            if str(v).strip()
        ]

    def get_prevent_targeting_of_friendly_saints_from_enemy_card_types(self, card_name: str) -> list[str]:
        script = self.get_script(card_name)
        if script is None:
            return []
        return [
            str(v).strip().lower()
            for v in script.prevent_targeting_of_friendly_saints_from_enemy_card_types
            if str(v).strip()
        ]

    def get_protection_rules(self, card_name: str) -> list[dict[str, Any]]:
        script = self.get_script(card_name)
        if script is None:
            return []
        rules = [dict(v) for v in script.protection_rules if isinstance(v, dict)]
        legacy_destroy_types = [
            str(v).strip().lower()
            for v in script.prevent_effect_destruction_of_friendly_saints_from_source_card_types
            if str(v).strip()
        ]
        if legacy_destroy_types:
            rules.append(
                {
                    "event": "destroy_by_effect",
                    "source_owner": "enemy",
                    "target_owner": "friendly",
                    "source_card_types": legacy_destroy_types,
                    "target_card_types": ["santo", "token"],
                }
            )
        legacy_target_types = [
            str(v).strip().lower()
            for v in script.prevent_targeting_of_friendly_saints_from_enemy_card_types
            if str(v).strip()
        ]
        if legacy_target_types:
            rules.append(
                {
                    "event": "target_by_effect",
                    "source_owner": "enemy",
                    "target_owner": "friendly",
                    "source_card_types": legacy_target_types,
                    "target_card_types": ["santo", "token"],
                }
            )
        return rules

    def blocks_interaction(
        self,
        card_name: str,
        *,
        event: str,
        source_owner: str,
        target_owner: str,
        source_card_type: str,
        target_card_type: str,
        target_card_name: str | None = None,
        target_equipped_by_card_types: list[str] | None = None,
    ) -> bool:
        event_key = _norm(event)
        src_owner_key = _norm(source_owner)
        tgt_owner_key = _norm(target_owner)
        src_type_key = _norm(source_card_type)
        tgt_type_key = _norm(target_card_type)
        for rule in self.get_protection_rules(card_name):
            if _norm(str(rule.get("event", ""))) != event_key:
                continue
            rule_src_owner = _norm(str(rule.get("source_owner", "any")))
            if rule_src_owner not in {"", "any", src_owner_key}:
                continue
            rule_tgt_owner = _norm(str(rule.get("target_owner", "any")))
            if rule_tgt_owner not in {"", "any", tgt_owner_key}:
                continue
            src_types = {_norm(str(v)) for v in list(rule.get("source_card_types", []) or []) if str(v).strip()}
            if src_types and src_type_key not in src_types:
                continue
            tgt_types = {_norm(str(v)) for v in list(rule.get("target_card_types", []) or []) if str(v).strip()}
            if tgt_types and tgt_type_key not in tgt_types:
                continue
            target_names = {_norm(str(v)) for v in list(rule.get("target_names", []) or []) if str(v).strip()}
            if target_names and _norm(target_card_name or "") not in target_names:
                continue
            target_name_contains = _norm(str(rule.get("target_name_contains", "")))
            if target_name_contains and target_name_contains not in _norm(target_card_name or ""):
                continue
            required_equips = {
                _norm(str(v))
                for v in list(rule.get("target_equipped_by_card_types", []) or [])
                if str(v).strip()
            }
            if required_equips:
                equipped_types = {_norm(v) for v in list(target_equipped_by_card_types or []) if str(v).strip()}
                if required_equips.isdisjoint(equipped_types):
                    continue
            return True
        return False

    # This method retrieves the amount of retaliation damage that should be dealt to an enemy attacker when a card is attacked based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `retaliation_damage_to_enemy_attacker` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that deals retaliation damage to an enemy attacker when it is attacked during gameplay, which can influence how players strategize around that card.
    def get_retaliation_damage_to_enemy_attacker(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.retaliation_damage_to_enemy_attacker or 0)

    # This method retrieves the amount of sin that should be reduced for the card when it kills an enemy based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `retaliation_reduce_sin_on_kill` property as an integer. If the script is not found or if the property is not set, it returns 0. This information can be used to determine if a card has a specific mechanic that reduces its sin when it kills an enemy during gameplay, which can influence how players strategize around that card.
    def get_retaliation_reduce_sin_on_kill(self, card_name: str) -> int:
        script = self.get_script(card_name)
        if script is None:
            return 0
        return int(script.retaliation_reduce_sin_on_kill or 0)

    # This method retrieves the multiplier for retaliation damage that should be applied when a friendly building is attacked based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `retaliation_multiplier_for_friendly_building_name` property as a string. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a specific mechanic that modifies retaliation damage for friendly buildings during gameplay, which can influence how players strategize around that card.
    def get_retaliation_multiplier_for_friendly_building_name(self, card_name: str) -> str | None:
        script = self.get_script(card_name)
        if script is None:
            return None
        value = str(script.retaliation_multiplier_for_friendly_building_name or "").strip()
        return value or None

    # This method retrieves the multiplier for retaliation damage that should be applied when a friendly building is attacked based on the card script. It looks up the `CardScript` for the specified card name and returns the value of the `retaliation_multiplier_for_friendly_building_multiplier` property as a float. If the script is not found or if the property is not set, it returns None. This information can be used to determine if a card has a specific mechanic that modifies retaliation damage for friendly buildings during gameplay, which can influence how players strategize around that card.
    def migrated_count(self) -> int:
        return len(self._scripts)
