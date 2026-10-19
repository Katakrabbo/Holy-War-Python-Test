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

# This module defines the `RuntimeResolutionMixin` class, which provides methods for resolving card effects during gameplay. It includes methods for checking if a card can be played or activated, resolving the effects of playing or activating a card, and handling triggered effects when a card enters the field. The mixin relies on the structure of card scripts defined in the `CardScript` class and uses the game engine's state and rules API to manage the resolution of effects and triggers. The mixin also includes logic for handling pending effects that require player input or reveal actions, allowing for complex interactions and timing during gameplay.
class RuntimeResolutionMixin:
    if TYPE_CHECKING:
        # Methods from RuntimeRegistryMixin
        def ensure_all_cards_migrated(self, engine: GameEngine) -> None: ...
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
        ) -> bool: ...
        _scripts: dict[str, Any]
        _bindings: dict[int, Any]
        _subscribed_engines: set[int]
        _temp_faith: dict[int, Any]

        # Methods from RuntimeEffectsMixin
        def _eval_condition_node(self, ctx: RuleEventContext, owner_idx: int, node: dict[str, Any]) -> bool: ...
        def _validate_manual_target_actions(
            self,
            engine: GameEngine,
            owner_idx: int,
            source_uid: str,
            actions: list[ActionSpec],
            selected_target: str | None,
            event_name: str,
            empty_pool_message: str,
            missing_selection_message: str,
        ) -> tuple[bool, str | None]: ...
        def _resolve_targets(self, engine: GameEngine, owner_idx: int, target: Any) -> list[str]: ...
        def _apply_effect(self, engine: GameEngine, owner_idx: int, source_uid: str, targets: list[str], effect: Any) -> None: ...
        def _event_matches(self, ctx: RuleEventContext, owner_idx: int, condition: dict[str, Any]) -> bool: ...
        def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool: ...
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
        def _target_owner_indices(self, owner_idx: int, owner_key: str | None) -> list[int]: ...
        def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]: ...
    """Play/enter/activate resolution and trigger binding lifecycle."""

    def _describe_effect_action(self, effect: EffectSpec) -> str:
        action = _norm(effect.action)
        amount = int(effect.amount) if isinstance(effect.amount, int) else effect.amount
        if action == "draw_cards":
            qty = int(amount or 0)
            desc = f"pesca {qty} carta" if qty == 1 else f"pesca {qty} carte"
        elif action == "discard_cards":
            qty = int(amount or 0)
            desc = f"scarta {qty} carta" if qty == 1 else f"scarta {qty} carte"
        elif action == "inflict_damage":
            qty = int(amount or 0)
            desc = f"infligge {qty} danno" if qty == 1 else f"infligge {qty} danni"
        elif action == "restore_faith":
            qty = int(amount or 0)
            desc = f"ripristina {qty} Fede"
        elif action == "increase_faith":
            qty = int(amount or 0)
            desc = f"aumenta la Fede di {qty}"
        elif action == "decrease_faith":
            qty = int(amount or 0)
            desc = f"riduce la Fede di {qty}"
        elif action == "increase_strength":
            qty = int(amount or 0)
            desc = f"aumenta la Forza di {qty}"
        else:
            base_map = {
                "destroy_target": "distrugge il bersaglio",
                "destroy_selected_targets": "distrugge i bersagli selezionati",
                "inflict_damage_and_self_damage": "infligge danno reciproco",
                "inflict_sin": "infligge Peccato",
                "remove_sin": "rimuove Peccato",
                "add_to_hand": "aggiunge una carta alla mano",
                "send_to_graveyard": "manda al cimitero",
                "return_to_reliquiary": "rimanda al reliquiario",
                "shuffle_deck": "mischia il reliquiario",
                "summon_token": "evoca un token",
                "summon_target_to_field": "evoca il bersaglio sul campo",
                "move_source_to_board": "posiziona questa carta sul campo",
                "choose_option": "sceglie un'opzione",
            }
            desc = base_map.get(action, action.replace("_", " "))
        extras: list[str] = []
        if effect.amount not in (None, 0) and action not in {
            "draw_cards",
            "discard_cards",
            "inflict_damage",
            "restore_faith",
            "increase_faith",
            "decrease_faith",
            "increase_strength",
        }:
            extras.append(f"valore {effect.amount}")
        if str(effect.card_name or "").strip():
            extras.append(f"carta {effect.card_name}")
        if str(effect.from_zone or "").strip():
            extras.append(f"da {effect.from_zone}")
        if str(effect.to_zone or "").strip():
            extras.append(f"a {effect.to_zone}")
        if str(effect.target_player or "").strip():
            raw_target = str(effect.target_player).strip().lower()
            target_txt = {"me": "me", "opponent": "avversario", "any": "chiunque"}.get(raw_target, raw_target)
            extras.append(f"su {target_txt}")
        if extras:
            return f"{desc} ({', '.join(extras)})"
        return desc

    def _should_log_effect_action(self, action_name: str) -> bool:
        # Internal bookkeeping actions are too noisy for gameplay logs.
        noisy = {
            "choose_targets",
            "store_target_count",
            "draw_cards_from_flag",
            "draw_cards_equal_to_flag",
            "set_flag",
            "clear_flag",
            "bind_trigger",
            "unbind_trigger",
        }
        return action_name not in noisy

    def _describe_target_names(self, engine: GameEngine, targets: list[str]) -> str:
        if not targets:
            return ""
        out: list[str] = []
        for token in targets:
            inst = engine.state.instances.get(token)
            if inst is not None:
                out.append(inst.definition.name)
            else:
                out.append(str(token))
        return ", ".join(out)

    def _log_script_action(self, engine: GameEngine, source_uid: str, effect: EffectSpec, targets: list[str]) -> None:
        if not bool(engine.state.flags.get("verbose_effect_logs", False)):
            return
        source_inst = engine.state.instances.get(source_uid)
        source_name = source_inst.definition.name if source_inst is not None else source_uid
        action_name = _norm(effect.action)
        if not self._should_log_effect_action(action_name):
            return
        effect_text = self._describe_effect_action(effect)
        engine.state.log(f"{source_name} attiva: {effect_text}.")
        target_text = self._describe_target_names(engine, targets)
        if target_text:
            engine.state.log(f"{source_name} seleziona: {target_text}.")

    def _can_resolve_exclusive_trigger_source(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        trigger: TriggerSpec,
    ) -> bool:
        if not bool(trigger.exclusive_trigger_per_turn):
            return True
        inst = engine.state.instances.get(source_uid)
        if inst is None:
            return False
        group = str(trigger.exclusive_group or "").strip()
        event_name = _norm(trigger.event)
        if not group:
            group = f"{event_name}:{_norm(inst.definition.name)}"
        runtime_state = engine.state.flags.setdefault("runtime_state", {})
        chosen_by_owner = runtime_state.setdefault("exclusive_trigger_source_by_turn", {"0": {}, "1": {}})
        owner_key = str(owner_idx)
        owner_bucket = dict(chosen_by_owner.get(owner_key, {}) or {})
        slot = dict(owner_bucket.get(group, {}) or {})
        turn = int(engine.state.turn_number)
        saved_turn = int(slot.get("turn", -1))
        saved_uid = str(slot.get("uid", "")).strip()
        if saved_turn != turn or not saved_uid:
            owner_bucket[group] = {"turn": turn, "uid": source_uid}
            chosen_by_owner[owner_key] = owner_bucket
            return True
        return saved_uid == source_uid

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def can_play(
        self,
        engine: GameEngine,
        player_idx: int,
        uid: str,
        target: str | None = None,
    ) -> tuple[bool, str | None]:
        self.ensure_all_cards_migrated(engine)
        inst = engine.state.instances[uid]
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))
        if not script.can_play_from_hand:
            return (False, "Questa carta non puo essere giocata dalla mano.")

        # Check play requirements if defined in the card script
        if script.play_requirements:
            ok = self._eval_condition_node(
                RuleEventContext(engine=engine, event="can_play", player_idx=player_idx, payload={"card": uid}),
                player_idx,
                script.play_requirements,
            )
            if not ok:
                return (False, "Non puoi giocare questa carta nelle condizioni attuali.")

        # If the card has on-play actions defined in its script, validate the manual target selection for those actions. This involves checking if there are valid targets available and if the player has selected a valid target if required. The method returns a tuple indicating whether the card can be played and an optional message explaining why it cannot be played if that's the case.
        if script.on_play_actions:
            return self._validate_manual_target_actions(
                engine=engine,
                owner_idx=player_idx,
                source_uid=uid,
                actions=script.on_play_actions,
                selected_target=target,
                event_name="on_play",
                empty_pool_message="Nessun bersaglio valido disponibile per questa carta.",
                missing_selection_message="Devi selezionare almeno un bersaglio valido per giocare questa carta.",
            )
        return (True, None)

    # Similar to `can_play`, this method checks if a card's effect can be activated based on its script and the current game state. It verifies if the card has an activatable effect, checks any conditions for activation, and validates manual target selection if required. The method returns a tuple indicating whether the activation is possible and an optional message explaining why it cannot be activated if that's the case.
    def can_activate(
        self,
        engine: GameEngine,
        player_idx: int,
        uid: str,
        target: str | None = None,
    ) -> tuple[bool, str | None]:
        self.ensure_all_cards_migrated(engine)
        inst = engine.state.instances[uid]
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))

        mode = _norm(script.on_activate_mode)

        # Nessuna abilità attivabile manualmente
        if mode not in {"scripted", "custom"}:
            return (False, "Questa carta non ha un effetto attivabile.")

        # Se è definito un effetto attivabile, ma non ci sono azioni associate, consideriamo che non ci sia un effetto attivabile (per compatibilità con le vecchie carte che potrebbero avere on_activate_mode impostato ma senza azioni).
        if not script.on_activate_actions:
            return (False, "Questa carta non ha un effetto attivabile.")

        activation_context = RuleEventContext(
            engine=engine,
            event="on_activate",
            player_idx=player_idx,
            payload={"card": uid},
        )
        if not any(
            not action.condition or self._eval_condition_node(activation_context, player_idx, action.condition)
            for action in script.on_activate_actions
        ):
            return (False, "Le condizioni per attivare questa abilita non sono soddisfatte.")

        # Check activation requirements if defined in the card script
        return self._validate_manual_target_actions(
            engine=engine,
            owner_idx=player_idx,
            source_uid=uid,
            actions=script.on_activate_actions,
            selected_target=target,
            event_name="on_activate",
            empty_pool_message="Nessun bersaglio valido disponibile per questa abilita.",
            missing_selection_message="Devi selezionare almeno un bersaglio valido per attivare questa abilita.",
        )

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def resolve_play(self, engine: GameEngine, player_idx: int, uid: str, target: str | None) -> object:
        self.ensure_all_cards_migrated(engine)
        inst = engine.state.instances[uid]
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))
        mode = _norm(script.on_play_mode)
        flags = engine.state.flags
        previous_source = flags.get("_runtime_effect_source")
        previous_selected_sequence = flags.get("_runtime_selected_target_sequence")

        flags["_runtime_effect_source"] = uid
        flags["_runtime_source_card"] = uid
        flags["_runtime_selected_target"] = str(target or "")
        if str(target or "").strip().startswith("seq:"):
            flags["_runtime_selected_target_sequence"] = str(target or "").strip()
        else:
            flags.pop("_runtime_selected_target_sequence", None)
        try:
            is_saint = _norm(inst.definition.card_type) in {"santo", "token"}
            if mode in {"noop", "none"}:
                return "Nessun effetto all'ingresso."
            if mode in {"scripted", "custom"} and script.on_play_actions:
                self._run_play_actions(engine, player_idx, uid, script.on_play_actions)
                return "Effetto risolto."
            if mode == "auto" and script.on_play_actions:
                self._run_play_actions(engine, player_idx, uid, script.on_play_actions)
                return "Effetto risolto."
            if mode in {"scripted", "custom", "auto"} and not script.on_play_actions:
                return "Nessun effetto scriptato."
            if is_saint:
                return "Nessun effetto scriptato."
            return self._legacy_removed_message(engine, inst.definition.name, "on_play", mode)
        finally:
            if previous_source is None:
                flags.pop("_runtime_effect_source", None)
            else:
                flags["_runtime_effect_source"] = previous_source

            if not flags.get("_runtime_waiting_for_reveal"):
                flags.pop("_runtime_source_card", None)
                flags.pop("_runtime_selected_target", None)
                if previous_selected_sequence is None:
                    flags.pop("_runtime_selected_target_sequence", None)
                else:
                    flags["_runtime_selected_target_sequence"] = previous_selected_sequence
                flags.pop("_runtime_action_index", None)

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def _run_play_actions(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        actions: list[ActionSpec],
        start_index: int = 0,
    ) -> None:
        flags = engine.state.flags
        flags["_runtime_pending_mode"] = "play"
        
        # If the card being played has defined on-play actions in its script, this method iterates through those actions and executes them in order. It checks for any conditions associated with each action and resolves the targets and effects accordingly. If at any point an action requires a player input or reveal that cannot be immediately resolved, the method sets flags to indicate that it is waiting for a reveal and stores the current state of the resolution so that it can be resumed later when the necessary input is provided. This allows for complex interactions and timing during the resolution of card effects.
        for i in range(start_index, len(actions)):
            if flags.get("_runtime_waiting_for_reveal"):
                flags["_runtime_action_index_resume"] = str(i)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break

            action = actions[i]
            flags["_runtime_action_index"] = str(i)

# Check the condition for the action if it exists. If the condition is not met, skip this action and move to the next one. The condition is evaluated in the context of the current game state, the player activating the effect, and the card that is the source of the effect.
            if action.condition and not self._eval_condition_node(
                RuleEventContext(engine=engine, event="on_play", player_idx=owner_idx, payload={"card": source_uid}),
                owner_idx,
                action.condition,
            ):
                continue

            effect_action = _norm(action.effect.action)
            target_type = _norm(action.target.type)
            if effect_action == "choose_targets" and target_type in {"selected_target", "selected_targets"}:
                targets = self._collect_selectable_targets_for_manual_target(engine, owner_idx, action.target)
            else:
                targets = self._resolve_targets(engine, owner_idx, action.target)
            self._log_script_action(engine, source_uid, action.effect, targets)
            self._apply_effect(engine, owner_idx, source_uid, targets, action.effect)

            # If the effect application resulted in a state where the resolution is waiting for a reveal (e.g., waiting for the player to reveal a card or make a choice), set the appropriate flags to allow the resolution to be resumed later. This includes storing the index of the next action to execute, the source of the effect, and the owner of the effect. The method then breaks out of the loop, pausing further resolution until the necessary input is provided.
            if flags.get("_runtime_waiting_for_reveal"):
                if bool(flags.pop("_runtime_resume_same_action", False)):
                    flags["_runtime_action_index_resume"] = str(i)
                else:
                    flags["_runtime_action_index_resume"] = str(i + 1)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break

        flags.pop("_runtime_action_index", None)
        if not flags.get("_runtime_waiting_for_reveal"):
            flags.pop("_runtime_pending_mode", None)

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def resolve_enter(self, engine: GameEngine, player_idx: int, uid: str) -> object:
        self.ensure_all_cards_migrated(engine)
        self.on_enter_bind_triggers(engine, player_idx, uid)
        inst = engine.state.instances[uid]
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))
        mode = _norm(script.on_enter_mode)
        flags = engine.state.flags
        enter_stack = flags.setdefault("_runtime_enter_stack", [])
        if isinstance(enter_stack, list) and uid in enter_stack:
            return None
        if isinstance(enter_stack, list):
            enter_stack.append(uid)
        previous_source = flags.get("_runtime_effect_source")
        previous_runtime_source_card = flags.get("_runtime_source_card")
        previous_selected_target = flags.get("_runtime_selected_target")
        flags["_runtime_effect_source"] = uid
        flags["_runtime_source_card"] = uid
        flags["_runtime_selected_target"] = ""

        # The method resolves the effects that occur when a card enters the field. It checks the card's script for any defined on-enter actions and executes them according to the specified mode (e.g., scripted, auto). If there are no on-enter actions or if the mode indicates that there should be no effect, it returns an appropriate message. The method also handles setting and clearing runtime flags to manage the state of effect resolution, especially in cases where player input or reveals are required to continue the resolution process.
        try:
            is_saint = _norm(inst.definition.card_type) in {"santo", "token"}
            if mode in {"noop", "none"}:
                return None
            if mode in {"scripted", "custom"} and script.on_enter_actions:
                self._run_enter_actions(engine, player_idx, uid, script.on_enter_actions)
                return "Effetto di ingresso risolto."
            if mode == "auto" and script.on_enter_actions:
                self._run_enter_actions(engine, player_idx, uid, script.on_enter_actions)
                return "Effetto di ingresso risolto."
            if mode in {"scripted", "custom", "auto"} and not script.on_enter_actions:
                return None
            if is_saint:
                return None
            return self._legacy_removed_message(engine, inst.definition.name, "on_enter", mode)
        finally:
            if isinstance(enter_stack, list):
                for i in range(len(enter_stack) - 1, -1, -1):
                    if enter_stack[i] == uid:
                        del enter_stack[i]
                        break
                if not enter_stack:
                    flags.pop("_runtime_enter_stack", None)
            if previous_source is None:
                flags.pop("_runtime_effect_source", None)
            else:
                flags["_runtime_effect_source"] = previous_source
            if not flags.get("_runtime_waiting_for_reveal"):
                if previous_runtime_source_card is None:
                    flags.pop("_runtime_source_card", None)
                else:
                    flags["_runtime_source_card"] = previous_runtime_source_card
                if previous_selected_target is None:
                    flags.pop("_runtime_selected_target", None)
                else:
                    flags["_runtime_selected_target"] = previous_selected_target

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def resolve_activate(self, engine: GameEngine, player_idx: int, uid: str, target: str | None) -> object:
        self.ensure_all_cards_migrated(engine)
        inst = engine.state.instances[uid]
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))
        mode = _norm(script.on_activate_mode)
        flags = engine.state.flags
        previous_source = flags.get("_runtime_effect_source")
        previous_selected_sequence = flags.get("_runtime_selected_target_sequence")

        flags["_runtime_effect_source"] = uid
        flags["_runtime_source_card"] = uid
        flags["_runtime_selected_target"] = str(target or "")
        if str(target or "").strip().startswith("seq:"):
            flags["_runtime_selected_target_sequence"] = str(target or "").strip()
        else:
            flags.pop("_runtime_selected_target_sequence", None)
        try:
            is_saint = _norm(inst.definition.card_type) in {"santo", "token"}
            if mode in {"scripted", "custom"} and script.on_activate_actions:
                self._run_activate_actions(engine, player_idx, uid, script.on_activate_actions)
                if script.activate_once_per_turn and not flags.get("_runtime_waiting_for_reveal"):
                    engine.mark_activated_this_turn(uid)
                return "Effetto attivato."
            if mode in {"scripted", "custom"} and not script.on_activate_actions:
                return "Nessun effetto attivabile."
            if mode in {"auto", "noop", "none"}:
                return "Nessun effetto attivabile."
            if is_saint:
                return "Nessun effetto scriptato."
            return self._legacy_removed_message(engine, inst.definition.name, "on_activate", mode)
        finally:
            if previous_source is None:
                flags.pop("_runtime_effect_source", None)
            else:
                flags["_runtime_effect_source"] = previous_source
            flags.pop("_runtime_source_card", None)
            flags.pop("_runtime_selected_target", None)
            if previous_selected_sequence is None:
                flags.pop("_runtime_selected_target_sequence", None)
            else:
                flags["_runtime_selected_target_sequence"] = previous_selected_sequence
            flags.pop("_runtime_selected_option", None)

    # The following methods implement the logic for resolving card effects and managing triggers during gameplay. They interact with the game engine's state and rules API to determine when effects can be activated, to execute the effects of playing or activating cards, and to handle triggered effects based on game events. The methods also manage pending effects that require player input, allowing for complex interactions and timing during the resolution of card effects.
    def _legacy_removed_message(self, engine: GameEngine, card_name: str, event: str, mode: str) -> str:
        _ = engine
        _ = event
        _ = mode
        return "Nessun effetto scriptato."

    # This method executes the on-activate actions defined in a card's script when the card's effect is activated. It iterates through the list of actions, checks any conditions for each action, resolves targets, and applies effects accordingly. If at any point an action requires a player input or reveal that cannot be immediately resolved, it sets flags to indicate that it is waiting for a reveal and stores the current state of the resolution so that it can be resumed later when the necessary input is provided. This allows for complex interactions and timing during the activation of card effects.
    def _run_activate_actions(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        actions: list[ActionSpec],
        start_index: int = 0,
    ) -> None:
        flags = engine.state.flags
        flags["_runtime_pending_mode"] = "activate"
        for i in range(start_index, len(actions)):
            if flags.get("_runtime_waiting_for_reveal"):
                flags["_runtime_action_index_resume"] = str(i)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break
            action = actions[i]
            if action.condition and not self._eval_condition_node(
                RuleEventContext(engine=engine, event="on_activate", player_idx=owner_idx, payload={"card": source_uid}),
                owner_idx,
                action.condition,
            ):
                continue
            targets = self._resolve_targets(engine, owner_idx, action.target)
            self._log_script_action(engine, source_uid, action.effect, targets)
            self._apply_effect(engine, owner_idx, source_uid, targets, action.effect)
            if flags.get("_runtime_waiting_for_reveal"):
                if bool(flags.pop("_runtime_resume_same_action", False)):
                    flags["_runtime_action_index_resume"] = str(i)
                else:
                    flags["_runtime_action_index_resume"] = str(i + 1)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break

        if not flags.get("_runtime_waiting_for_reveal"):
            flags.pop("_runtime_pending_mode", None)

    # This method is responsible for resuming the resolution of a pending effect that was previously paused due to waiting for player input or a reveal action. It retrieves the necessary information from the runtime flags, such as the source of the effect, the owner of the effect, and the index of the next action to execute. It then continues executing the remaining actions for the appropriate mode (play, enter, activate, or trigger_action) until all actions are resolved or until it encounters another point where it needs to wait for player input or a reveal.
    def resume_pending_effect(self, engine: GameEngine) -> None:
        flags = engine.state.flags
        source_uid = str(flags.get("_runtime_resume_source", "")).strip()
        owner_idx_raw = flags.get("_runtime_resume_owner")
        if not source_uid or owner_idx_raw is None:
            return

        # Verify that the source instance still exists in the game state. If it doesn't, clear the relevant runtime flags and return without attempting to resume the effect, as the source of the effect is no longer valid.
        inst = engine.state.instances.get(source_uid)
        if inst is None:
            flags.pop("_runtime_resume_source", None)
            flags.pop("_runtime_resume_owner", None)
            flags.pop("_runtime_action_index_resume", None)
            flags.pop("_runtime_pending_mode", None)
            return

        # Convert the owner index from the raw string format stored in the flags to an integer. This is necessary because runtime flags are typically stored as strings, but the owner index needs to be an integer for further processing. If the conversion fails, it would raise a ValueError, but in this context we assume that the data in the flags is well-formed.
        owner_idx = int(owner_idx_raw)
        script = self._scripts.get(_norm(inst.definition.name), CardScript(name=inst.definition.name))
        card_type = _norm(inst.definition.card_type)
        normalized_name = _norm(inst.definition.name)
        is_piaga_blessing_or_curse = card_type in {"benedizione", "maledizione"} and "piaga" in normalized_name
        start_index = int(flags.get("_runtime_action_index_resume", 0))
        mode = str(flags.get("_runtime_pending_mode", "")).strip().lower()
        previous_source = flags.get("_runtime_effect_source")

        flags["_runtime_effect_source"] = source_uid
        flags["_runtime_source_card"] = source_uid
        # The method then checks the mode of the pending effect (e.g., play, enter, activate, trigger_action) and calls the appropriate method to continue executing the remaining actions for that mode. If the mode is "play", it calls `_run_play_actions`; if it's "enter", it calls `_run_enter_actions`; if it's "activate", it calls `_run_activate_actions`. If the mode is "trigger_action", it retrieves the specific action to trigger from the flags and applies that effect directly. After attempting to resume the effect, it clears the relevant runtime flags to clean up the state.
        try:
            if mode == "play":
                copied_uid = str(flags.get("_runtime_copied_play_card", "")).strip()
                if copied_uid and copied_uid in engine.state.instances:
                    copied_inst = engine.state.instances[copied_uid]
                    copied_script = self._scripts.get(_norm(copied_inst.definition.name), CardScript(name=copied_inst.definition.name))
                    copied_actions = list(copied_script.on_play_actions or [])
                    prepared_actions: list[ActionSpec] = []
                    for action_spec in copied_actions:
                        ttype = _norm(action_spec.target.type)
                        should_force_picker = ttype in {"selected_target", "selected_targets"}
                        if should_force_picker:
                            prepared_actions.append(
                                ActionSpec(
                                    target=action_spec.target,
                                    effect=EffectSpec(
                                        action="choose_targets",
                                        min_targets=action_spec.target.min_targets,
                                        max_targets=action_spec.target.max_targets,
                                    ),
                                    condition=action_spec.condition,
                                )
                            )
                        prepared_actions.append(action_spec)
                    flags["_runtime_force_manual_selected_target"] = True
                    self._run_play_actions(engine, owner_idx, source_uid, prepared_actions, start_index=start_index)
                else:
                    self._run_play_actions(engine, owner_idx, source_uid, script.on_play_actions, start_index=start_index)
            elif mode == "enter":
                self._run_enter_actions(engine, owner_idx, source_uid, script.on_enter_actions, start_index=start_index)
            elif mode == "activate":
                self._run_activate_actions(engine, owner_idx, source_uid, script.on_activate_actions, start_index=start_index)
            elif mode == "trigger_action":
                action_name = str(flags.get("_runtime_trigger_action", "")).strip()
                target_player = str(flags.get("_runtime_trigger_target_player", "me")).strip() or "me"
                trigger_card_name = str(flags.get("_runtime_trigger_card_name", "")).strip() or None
                trigger_from_zone = str(flags.get("_runtime_trigger_from_zone", "")).strip() or None
                trigger_to_zone = str(flags.get("_runtime_trigger_to_zone", "")).strip() or None
                trigger_to_zone_if = str(flags.get("_runtime_trigger_to_zone_if", "")).strip() or None
                trigger_amount_raw = str(flags.get("_runtime_trigger_amount", "")).strip()
                trigger_shuffle_after_raw = str(flags.get("_runtime_trigger_shuffle_after", "")).strip().lower()
                trigger_event_name = str(flags.get("_runtime_trigger_event_name", "")).strip()
                trigger_choice_title = str(flags.get("_runtime_trigger_choice_title", "")).strip() or None
                trigger_choice_prompt = str(flags.get("_runtime_trigger_choice_prompt", "")).strip() or None
                trigger_choice_options_raw = str(flags.get("_runtime_trigger_choice_options", "")).strip()
                trigger_min_targets_raw = str(flags.get("_runtime_trigger_min_targets", "")).strip()
                trigger_max_targets_raw = str(flags.get("_runtime_trigger_max_targets", "")).strip()
                trigger_event_player_raw = str(flags.get("_runtime_trigger_event_player", "")).strip()
                trigger_amount = int(trigger_amount_raw) if trigger_amount_raw else 0
                trigger_min_targets = int(trigger_min_targets_raw) if trigger_min_targets_raw else None
                trigger_max_targets = int(trigger_max_targets_raw) if trigger_max_targets_raw else None
                trigger_event_player = int(trigger_event_player_raw) if trigger_event_player_raw else owner_idx
                trigger_shuffle_after = trigger_shuffle_after_raw in {"1", "true", "yes", "y"}
                trigger_choice_options: list[dict[str, Any]] = []
                if trigger_choice_options_raw:
                    try:
                        parsed = json.loads(trigger_choice_options_raw)
                        if isinstance(parsed, list):
                            trigger_choice_options = [dict(v) for v in parsed if isinstance(v, dict)]
                    except Exception:
                        trigger_choice_options = []
                if action_name:
                    self._apply_effect(
                        engine,
                        owner_idx,
                        source_uid,
                        [],
                        EffectSpec(
                            action=action_name,
                            target_player=target_player,
                            card_name=trigger_card_name,
                            from_zone=trigger_from_zone,
                            to_zone=trigger_to_zone,
                            to_zone_if=trigger_to_zone_if,
                            amount=trigger_amount,
                            shuffle_after=trigger_shuffle_after,
                            choice_title=trigger_choice_title,
                            choice_prompt=trigger_choice_prompt,
                            choice_options=trigger_choice_options,
                            min_targets=trigger_min_targets,
                            max_targets=trigger_max_targets,
                        ),
                    )
                    # After a trigger-side choice, execute sibling effects only
                    # once the controller has supplied the required decision.
                    if _norm(action_name) in {"choose_option", "choose_targets"}:
                        selected_option = str(flags.get("_runtime_selected_option", "")).strip()
                        selected_target = str(flags.get("_runtime_selected_target", "")).strip()
                        choice_completed = selected_option if _norm(action_name) == "choose_option" else selected_target
                        if choice_completed and trigger_event_name:
                            follow_ctx = RuleEventContext(
                                engine=engine,
                                event=trigger_event_name,
                                player_idx=trigger_event_player,
                                payload={"card": source_uid},
                            )
                            for follow_te in script.triggered_effects:
                                if _norm(follow_te.trigger.event) != _norm(trigger_event_name):
                                    continue
                                if _norm(follow_te.effect.action) == _norm(action_name):
                                    continue
                                if not self._event_matches(follow_ctx, owner_idx, follow_te.trigger.condition):
                                    continue
                                follow_targets = self._resolve_targets(engine, owner_idx, follow_te.target)
                                self._log_script_action(engine, source_uid, follow_te.effect, follow_targets)
                                if not follow_targets:
                                    self._apply_effect(engine, owner_idx, source_uid, [], follow_te.effect)
                                else:
                                    self._apply_effect(engine, owner_idx, source_uid, follow_targets, follow_te.effect)
        finally:
            if previous_source is None:
                flags.pop("_runtime_effect_source", None)
            else:
                flags["_runtime_effect_source"] = previous_source

            # If after attempting to resume the effect we are not waiting for another reveal, clear all the runtime flags related to effect resolution to clean up the state. This includes flags for the source card, selected target, action index, pending mode, and any trigger-related flags. This ensures that the runtime state is reset and ready for the next effect resolution.
            if not flags.get("_runtime_waiting_for_reveal"):
                if mode == "activate" and script.activate_once_per_turn:
                    engine.mark_activated_this_turn(source_uid)
                flags.pop("_runtime_source_card", None)
                flags.pop("_runtime_selected_option", None)
                flags.pop("_runtime_resume_source", None)
                flags.pop("_runtime_resume_owner", None)
                flags.pop("_runtime_action_index_resume", None)
                flags.pop("_runtime_pending_mode", None)
                flags.pop("_runtime_trigger_action", None)
                flags.pop("_runtime_trigger_target_player", None)
                flags.pop("_runtime_trigger_card_name", None)
                flags.pop("_runtime_trigger_amount", None)
                flags.pop("_runtime_trigger_from_zone", None)
                flags.pop("_runtime_trigger_to_zone", None)
                flags.pop("_runtime_trigger_to_zone_if", None)
                flags.pop("_runtime_trigger_shuffle_after", None)
                flags.pop("_runtime_trigger_event_name", None)
                flags.pop("_runtime_trigger_choice_title", None)
                flags.pop("_runtime_trigger_choice_prompt", None)
                flags.pop("_runtime_trigger_choice_options", None)
                flags.pop("_runtime_trigger_choice_source", None)
                flags.pop("_runtime_trigger_event_player", None)
                flags.pop("_runtime_trigger_min_targets", None)
                flags.pop("_runtime_trigger_max_targets", None)
                if mode == "trigger_action":
                    flags.pop("_runtime_selected_target", None)
                flags.pop("_runtime_copied_play_card", None)
                flags.pop("_runtime_force_manual_selected_target", None)

    # This method executes the on-enter actions defined in a card's script when the card enters the field. It iterates through the list of actions, checks any conditions for each action, resolves targets, and applies effects accordingly. If at any point an action requires a player input or reveal that cannot be immediately resolved, it sets flags to indicate that it is waiting for a reveal and stores the current state of the resolution so that it can be resumed later when the necessary input is provided. This allows for complex interactions and timing during the resolution of card effects when a card enters the field.
    def _run_enter_actions(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        actions: list[ActionSpec],
        start_index: int = 0,
    ) -> None:
        flags = engine.state.flags
        flags["_runtime_pending_mode"] = "enter"
        for i in range(start_index, len(actions)):
            if flags.get("_runtime_waiting_for_reveal"):
                flags["_runtime_action_index_resume"] = str(i)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break
            action = actions[i]
            flags["_runtime_action_index"] = str(i)
            if action.condition and not self._eval_condition_node(
                RuleEventContext(engine=engine, event="on_enter", player_idx=owner_idx, payload={"card": source_uid}),
                owner_idx,
                action.condition,
            ):
                continue
            targets = self._resolve_targets(engine, owner_idx, action.target)
            self._log_script_action(engine, source_uid, action.effect, targets)
            self._apply_effect(engine, owner_idx, source_uid, targets, action.effect)
            if flags.get("_runtime_waiting_for_reveal"):
                if bool(flags.pop("_runtime_resume_same_action", False)):
                    flags["_runtime_action_index_resume"] = str(i)
                else:
                    flags["_runtime_action_index_resume"] = str(i + 1)
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                break
        flags.pop("_runtime_action_index", None)
        if not flags.get("_runtime_waiting_for_reveal"):
            flags.pop("_runtime_pending_mode", None)

    # This method is responsible for binding the appropriate triggers for a card when it enters the field. It checks the card's script for any defined triggered effects and subscribes to the relevant game events based on those effects. The method also manages the bindings to ensure that they are properly unsubscribed when the card leaves the field, preventing any lingering triggers that could cause unintended interactions. The triggers are set up to check their conditions and resolve their effects when the specified events occur during gameplay.
    def on_enter_bind_triggers(self, engine: GameEngine, owner_idx: int, source_uid: str) -> None:
        self.ensure_all_cards_migrated(engine)
        script = self._scripts.get(_norm(engine.state.instances[source_uid].definition.name))
        if not script or not script.triggered_effects:
            return
        eng_key = id(engine)
        by_source = self._bindings.setdefault(eng_key, {})
        previous_bindings = by_source.pop(source_uid, [])
        if previous_bindings:
            api = engine.rules_api(owner_idx)
            for event_name, handler in previous_bindings:
                try:
                    api.unsubscribe(event_name, handler)
                except Exception:
                    pass
        by_source[source_uid] = []

        api = engine.rules_api(owner_idx)

        for te in script.triggered_effects:
            event_name = te.trigger.event
            allow_source_off_field = {
                "on_this_card_destroyed",
                "on_card_destroyed_on_field",
                "on_saint_destroyed_by_effect",
                "on_saint_defeated_in_battle",
                "on_saint_defeated_or_destroyed",
                "on_card_drawn",
                "on_this_card_leaves_field",
                "on_card_sent_to_graveyard",
                "on_card_excommunicated",
                "on_card_returned_to_reliquario",
                "on_card_shuffled_into_reliquario",
            }

            # The handler function defined here is responsible for checking if the trigger conditions are met when the specified event occurs. It verifies if the source of the event is still on the field (if required by the trigger), checks if the event is happening during the correct player's turn, and evaluates any additional conditions specified in the trigger. If all conditions are met, it resolves the effect associated with the trigger. The handler also logs the trigger activation and manages runtime flags to keep track of the event context during resolution.
            def _handler(ctx: RuleEventContext, _te=te, _owner=owner_idx, _source=source_uid, _event_name=event_name):
                # During hidden preparation each side is an isolated setup
                # area.  A permanent already placed by the other player must
                # not react to, or reveal information about, the field that is
                # currently being prepared.
                if ctx.engine.state.phase == "preparation" and _owner != ctx.engine.state.active_player:
                    return
                if _event_name not in allow_source_off_field and not self._is_uid_on_field(ctx.engine, _source):
                    source_inst = ctx.engine.state.instances.get(_source)
                    is_equipped = bool(
                        source_inst
                        and any(str(tag).startswith("equipped_to:") for tag in source_inst.blessed)
                    )
                    if not is_equipped:
                        return
                if _te.trigger.event in {"on_my_turn_start", "on_my_turn_end"} and ctx.player_idx != _owner:
                    return
                if _te.trigger.event in {"on_opponent_turn_start", "on_opponent_turn_end"} and ctx.player_idx != (1 - _owner):
                    return
                if _te.trigger.event == "on_opponent_draws" and ctx.player_idx != _owner:
                    return
                if _te.trigger.event.startswith("on_this_card_"):
                    event_uid = str(ctx.payload.get("card", ctx.payload.get("saint", ctx.payload.get("token", ""))))
                    if event_uid != _source:
                        return
                if _te.trigger.event == "on_opponent_saint_enters_field":
                    saint_uid = str(ctx.payload.get("saint", ctx.payload.get("card", ""))).strip()
                    source_inst = ctx.engine.state.instances.get(_source)
                    saint_inst = ctx.engine.state.instances.get(saint_uid)
                    if source_inst is None or saint_inst is None:
                        return
                    if int(saint_inst.owner) == int(source_inst.owner):
                        return
                if not self._can_resolve_exclusive_trigger_source(ctx.engine, _owner, _source, _te.trigger):
                    return
                if not self._event_matches(ctx, _owner, _te.trigger.condition):
                    return
                pending_source = str(ctx.engine.state.flags.get("_runtime_trigger_choice_source", "")).strip()
                pending_event = str(ctx.engine.state.flags.get("_runtime_trigger_event_name", "")).strip()
                if (
                    bool(ctx.engine.state.flags.get("_runtime_waiting_for_reveal"))
                    and pending_source == _source
                    and _norm(pending_event) == _norm(_event_name)
                    and _norm(_te.effect.action) != "choose_targets"
                ):
                    # Resolve the controller's mandatory choice before applying
                    # sibling effects from this same trigger event.
                    return
                source_inst = ctx.engine.state.instances.get(_source)
                source_name = source_inst.definition.name if source_inst is not None else _source
                ctx.engine.state.log(f"{source_name} attiva il suo effetto.")
                ctx.engine.state.flags["_runtime_event_card"] = str(
                    ctx.payload.get("card", ctx.payload.get("saint", ctx.payload.get("token", "")))
                )
                ctx.engine.state.flags["_runtime_event_source"] = str(ctx.payload.get("source", ""))
                ctx.engine.state.flags["_runtime_event_amount"] = str(ctx.payload.get("amount", ""))
                ctx.engine.state.flags["_runtime_event_controller"] = str(
                    ctx.payload.get("controller", ctx.player_idx)
                )
                ctx.engine.state.flags["_runtime_event_name"] = str(ctx.event)
                ctx.engine.state.flags["_runtime_source_card"] = _source
                try:
                    effect_action = _norm(_te.effect.action)
                    choice_ready_before = bool(ctx.engine.state.flags.get("_runtime_choice_ready"))
                    targets = self._resolve_targets(ctx.engine, _owner, _te.target)
                    self._log_script_action(ctx.engine, _source, _te.effect, targets)
                    if not targets:
                        self._apply_effect(ctx.engine, _owner, _source, [], _te.effect)
                    else:
                        self._apply_effect(ctx.engine, _owner, _source, targets, _te.effect)

                    if effect_action == "choose_targets" and ctx.engine.state.flags.get("_runtime_waiting_for_reveal"):
                        ctx.engine.state.flags["_runtime_resume_source"] = _source
                        ctx.engine.state.flags["_runtime_resume_owner"] = str(_owner)
                        ctx.engine.state.flags["_runtime_pending_mode"] = "trigger_action"
                        ctx.engine.state.flags["_runtime_trigger_action"] = "choose_targets"
                        ctx.engine.state.flags["_runtime_trigger_choice_source"] = _source
                        ctx.engine.state.flags["_runtime_trigger_event_name"] = _event_name
                        ctx.engine.state.flags["_runtime_trigger_event_player"] = str(ctx.player_idx)
                        ctx.engine.state.flags["_runtime_trigger_min_targets"] = str(
                            _te.effect.min_targets if _te.effect.min_targets is not None else 0
                        )
                        ctx.engine.state.flags["_runtime_trigger_max_targets"] = str(
                            _te.effect.max_targets if _te.effect.max_targets is not None else 1
                        )

                    # Trigger-side choose_option needs an explicit follow-up pass:
                    # once the choice is confirmed, apply sibling triggers on the
                    # same source/event whose conditions depend on selected_option_in.
                    if effect_action == "choose_option" and choice_ready_before:
                        selected_option = str(ctx.engine.state.flags.get("_runtime_selected_option", "")).strip()
                        if selected_option:
                            for follow_te in script.triggered_effects:
                                if follow_te is _te:
                                    continue
                                if follow_te.trigger.event != _event_name:
                                    continue
                                if _norm(follow_te.effect.action) == "choose_option":
                                    continue
                                if not self._event_matches(ctx, _owner, follow_te.trigger.condition):
                                    continue
                                follow_targets = self._resolve_targets(ctx.engine, _owner, follow_te.target)
                                self._log_script_action(ctx.engine, _source, follow_te.effect, follow_targets)
                                if not follow_targets:
                                    self._apply_effect(ctx.engine, _owner, _source, [], follow_te.effect)
                                else:
                                    self._apply_effect(ctx.engine, _owner, _source, follow_targets, follow_te.effect)
                finally:
                    ctx.engine.state.flags.pop("_runtime_event_card", None)
                    ctx.engine.state.flags.pop("_runtime_event_source", None)
                    ctx.engine.state.flags.pop("_runtime_event_amount", None)
                    ctx.engine.state.flags.pop("_runtime_event_controller", None)
                    ctx.engine.state.flags.pop("_runtime_event_name", None)
                    ctx.engine.state.flags.pop("_runtime_source_card", None)

            api.subscribe(event_name, _handler)
            by_source[source_uid].append((event_name, _handler))

    # This method is responsible for unbinding the triggers associated with a card when it leaves the field. It retrieves the bindings for the specified source UID and unsubscribes from all the events that were previously subscribed to for that card. This ensures that once a card is no longer on the field, its triggers will not activate and cause unintended interactions during gameplay. The method also handles any exceptions that may occur during unsubscription to ensure that the game continues to function smoothly even if there are issues with the bindings.
    def on_leave_unbind_triggers(self, engine: GameEngine, owner_idx: int, source_uid: str) -> None:
        eng_key = id(engine)
        by_source = self._bindings.get(eng_key, {})
        bindings = by_source.pop(source_uid, [])
        if not bindings:
            return

        api = engine.rules_api(owner_idx)
        for event_name, handler in bindings:
            try:
                api.unsubscribe(event_name, handler)
            except Exception:
                pass

    # This method ensures that the engine is subscribed to the "on_this_card_leaves_field" event for the specified engine instance. It uses a set to keep track of which engines it has already subscribed to, preventing multiple subscriptions for the same engine. When the "on_this_card_leaves_field" event is triggered, it calls the `_on_source_leaves_field` method to handle any necessary cleanup and unbinding of triggers for the card that is leaving the field.
    def _ensure_leave_subscription(self, engine: GameEngine) -> None:
        key = id(engine)
        if key in self._subscribed_engines:
            return
        self._subscribed_engines.add(key)
        engine.rules_api(0).subscribe("on_this_card_leaves_field", self._on_source_leaves_field)

    # This method is called when a card that has triggers bound to it leaves the field. It retrieves the source UID from the event context and checks if the source instance still exists in the game state. If it does, it unbinds the triggers associated with that source UID for both players (owner index 0 and 1). It also manages any temporary buffs or effects that were applied by the source card, ensuring that they are properly removed when the card leaves the field. This method is crucial for maintaining the integrity of the game state and preventing any lingering effects from cards that are no longer active on the field.
    def _on_source_leaves_field(self, ctx: RuleEventContext) -> None:
        source_uid = str(ctx.payload.get("card", ""))
        owner_idx = -1
        inst = ctx.engine.state.instances.get(source_uid)
        if inst is not None:
            owner_idx = inst.owner

        if owner_idx in (0, 1):
            self.on_leave_unbind_triggers(ctx.engine, owner_idx, source_uid)
            if not source_uid:
                    return

        owner_idx = -1
        inst = ctx.engine.state.instances.get(source_uid)
        if inst is not None:
            owner_idx = inst.owner

        if owner_idx in (0, 1):
            self.on_leave_unbind_triggers(ctx.engine, owner_idx, source_uid)

        # Remove any temporary buffs applied by this source card. This is necessary to ensure that when a card leaves the field, any effects it granted to other cards are properly removed, maintaining the integrity of the game state and preventing unintended interactions from lingering buffs.
        eng_key = id(ctx.engine)
        source_buffs = self._temp_faith.get(eng_key, {}).pop(source_uid, [])
        for target_uid, amount, marker in source_buffs:
            if target_uid not in ctx.engine.state.instances:
                continue
            inst = ctx.engine.state.instances[target_uid]
            if marker in inst.blessed:
                inst.blessed.remove(marker)
            inst.current_faith = max(0, (inst.current_faith or 0) - amount)

    # This method checks if a given UID corresponds to a card that is currently on the field for either player. It iterates through the attack, defense, artifacts, and building zones of both players to see if the UID is present. If it finds the UID in any of those zones, it returns True, indicating that the card is on the field. If it does not find the UID after checking all relevant zones for both players, it returns False.
    def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool:
        for idx in (0, 1):
            p = engine.state.players[idx]
            if uid in (p.attack + p.defense + p.artifacts) or p.building == uid:
                return True
        return False

    # This method retrieves the raw selected target for the current action from the runtime flags. It checks if the raw value starts with "seq:", which indicates that it is a sequence of targets indexed by action index. If it is a sequence, it extracts the relevant target for the current action index. If it is not a sequence, it simply returns the raw value as the selected target. This method is used to determine which target has been selected by the player for the current action being resolved.
    def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str:
        raw = str(engine.state.flags.get("_runtime_selected_target_sequence", "")).strip()
        if not raw:
            raw = str(engine.state.flags.get("_runtime_selected_target", "")).strip()
        if not raw.startswith("seq:"):
            return raw

        action_idx = str(engine.state.flags.get("_runtime_action_index", "")).strip()
        if not action_idx:
            return ""
        try:
            current_idx = int(action_idx)
        except (TypeError, ValueError):
            return ""

        # If the raw selected target is a sequence, it is expected to be in the format "seq:0=target1;;1=target2;;...". The method splits the sequence into chunks and looks for the chunk that corresponds to the current action index. If it finds a matching index, it returns the associated target value. If it does not find a match, it returns an empty string.
        body = raw[len("seq:"):]
        selected_by_idx: dict[int, str] = {}
        for chunk in body.split(";;"):
            if "=" not in chunk:
                continue
            idx, value = chunk.split("=", 1)
            try:
                parsed_idx = int(idx.strip())
            except (TypeError, ValueError):
                continue
            selected_by_idx[parsed_idx] = value.strip()
        if current_idx in selected_by_idx:
            return selected_by_idx[current_idx]
        # Fallback: reuse the latest previous selected target in the same
        # scripted sequence (useful for "select once, apply in next action").
        prev_indices = [i for i in selected_by_idx.keys() if i < current_idx]
        if prev_indices:
            return selected_by_idx[max(prev_indices)]
        return ""

    # This method processes the raw selected target for the current action and attempts to resolve it to a valid target UID that exists in the game state. It handles various formats for the selected target, such as direct UIDs, references to buffs, and indexed targets from specific zones. The method checks if the resolved target exists in the game state and returns the corresponding UID if it does. If it cannot resolve a valid target UID, it returns None.
    def _selected_target_uid_for_current_action(self, engine: GameEngine, owner_idx: int) -> str | None:
        raw_selected = self._selected_target_raw_for_current_action(engine)
        if not raw_selected:
            return None
        selected = raw_selected.split(",", 1)[0].strip()
        if selected.startswith("buff:"):
            selected = selected.split(":", 1)[1]
        if selected in engine.state.instances:
            return selected
        if ":" in selected:
            zone, name = selected.split(":", 1)
            zone = _norm(zone)
            name = name.strip()
            if zone in {"deck", "relicario"}:
                player = engine.state.players[owner_idx]
                for uid in player.deck:
                    if _norm(engine.state.instances[uid].definition.name) == _norm(name):
                        return uid
        zone, slot = engine._parse_zone_target(selected)
        if zone is None:
            return None
        player = engine.state.players[owner_idx]
        if zone == "attack" and 0 <= slot < len(player.attack):
            return player.attack[slot]
        if zone == "defense" and 0 <= slot < len(player.defense):
            return player.defense[slot]
        return None

    # This method determines the number of targets required for a manually selected target based on the configuration of the target specification. It checks if the target specification has a defined minimum number of targets and returns that value, ensuring that it is at least 0. If there is no defined minimum, it defaults to 1 target. This method is used to enforce the requirements for manual target selection during effect resolution.
    def _required_min_targets_for_manual_target(self, target: TargetSpec) -> int:
        configured = int(target.min_targets) if target.min_targets is not None else 1
        return max(0, configured)

    # This method checks if a given target specification requires manual selection by the player. It evaluates various aspects of the target specification, such as the type of target, whether it has explicit zones defined, if it has any filters that would require player input to resolve, and if it has limits on the number of targets. If any of these conditions indicate that the target cannot be automatically resolved and requires player input, the method returns True. Otherwise, it returns False, indicating that the target can be resolved without manual selection.
    def _target_requires_manual_selection(self, target: TargetSpec) -> bool:
        ttype = _norm(target.type)
        if ttype not in {"selected_target", "selected_targets"}:
            return False
        has_explicit_zone = bool(target.zones) or _norm(target.zone) != "field"
        has_filter = bool(
            target.card_filter.name_in
            or (target.card_filter.name_equals or "").strip()
            or (target.card_filter.name_contains or "").strip()
            or (target.card_filter.name_not_contains or "").strip()
            or (target.card_filter.name_not_equals_stored or "").strip()
            or target.card_filter.card_type_in
            or target.card_filter.exclude_event_card
            or target.card_filter.exclude_buildings_if_my_building_zone_occupied
            or target.card_filter.crosses_gte is not None
            or target.card_filter.crosses_lte is not None
            or target.card_filter.strength_gte is not None
            or target.card_filter.strength_lte is not None
            or target.card_filter.drawn_this_turn_only
            or target.card_filter.top_n_from_zone is not None
        )
        has_limits = (
            target.min_targets is not None
            or target.max_targets is not None
            or target.max_targets_from is not None
        )
        owner_key = _norm(target.owner or "me")
        has_non_default_owner = owner_key not in {"", "me", "owner", "controller"}
        return has_explicit_zone or has_filter or has_limits or has_non_default_owner

    # This method collects the list of selectable target UIDs for a given manual target specification. It determines the relevant zones to search based on the target specification, gathers all potential target UIDs from those zones for the specified owner(s), and then filters that pool of potential targets according to any filters defined in the target specification. The resulting list of selectable targets is returned, which can then be presented to the player for manual selection.
    def _collect_selectable_targets_for_manual_target(
        self,
        engine: GameEngine,
        owner_idx: int,
        target: TargetSpec,
    ) -> list[str]:
        zones = [z for z in target.zones if str(z).strip()]
        if not zones:
            zones = [target.zone]

        pool: list[str] = []
        if engine.state.phase == "preparation":
            target_owner_key = _norm(target.owner or "me")
            target_owners = [] if target_owner_key in {"opponent", "enemy", "other"} else [owner_idx]
        else:
            target_owners = self._target_owner_indices(owner_idx, target.owner)
        for scoped_owner in target_owners:
            for zone_name in zones:
                pool.extend(self._get_zone_cards(engine, scoped_owner, zone_name))
        # Preserve order but avoid duplicates.
        deduped_pool = list(dict.fromkeys(pool))
        return self._filter_target_pool(engine, owner_idx, target, deduped_pool)

    # This method takes a pool of potential target UIDs and filters it according to the criteria defined in the target specification. It checks for name-based filters, type filters, cross value filters, strength filters, and other conditions that may be specified in the target's card filter. The method iterates through the pool of potential targets, applies all relevant filters, and returns a list of UIDs that match the criteria defined in the target specification. This filtered list represents the valid targets that can be selected by the player for manual selection.
    def _filter_target_pool(
        self,
        engine: GameEngine,
        owner_idx: int,
        target: TargetSpec,
        pool: list[str],
    ) -> list[str]:
        needle_in = {_norm(v) for v in target.card_filter.name_in}
        needle = _norm(target.card_filter.name_contains or "")
        type_filter = {_norm(v) for v in target.card_filter.card_type_in}
        event_uid = str(engine.state.flags.get("_runtime_event_card", ""))
        source_uid = str(engine.state.flags.get("_runtime_source_card", ""))
        scoped_zones = [str(z).strip() for z in (target.zones if target.zones else [target.zone])]
        scoped_zone_keys = {_norm(z) for z in scoped_zones if z}
        non_field_move_zones = {"hand", "deck", "relicario", "reliquiary", "graveyard", "grave", "excommunicated", "excom"}
        top_n = target.card_filter.top_n_from_zone
        top_n_allowed: set[str] | None = None
        if top_n is not None and int(top_n) > 0:
            top_n_allowed = set(pool[-int(top_n):])
        out: list[str] = []
        for uid in pool:
            if uid not in engine.state.instances:
                continue
            # Never allow self-targeting when selecting cards from movable non-field zones.
            if source_uid and uid == source_uid and bool(scoped_zone_keys.intersection(non_field_move_zones)):
                continue
            if top_n_allowed is not None and uid not in top_n_allowed:
                continue
            if target.card_filter.exclude_event_card:
                if event_uid and uid == event_uid:
                    continue
                if not event_uid and source_uid and uid == source_uid:
                    continue
            inst = engine.state.instances[uid]
            needle_eq = _norm(target.card_filter.name_equals or "")
            name_variants = _card_name_variants(inst.definition)
            name_haystack = _card_name_haystack(inst.definition)
            if needle_eq and needle_eq not in name_variants:
                continue
            if needle_in and needle_in.isdisjoint(name_variants):
                continue
            if needle and needle not in name_haystack:
                continue
            needle_not = _norm(target.card_filter.name_not_contains or "")
            if needle_not and needle_not in name_haystack:
                continue
            name_not_equals_stored = str(target.card_filter.name_not_equals_stored or "").strip()
            if name_not_equals_stored:
                raw_stored = engine.state.flags.get(f"_runtime_store_{name_not_equals_stored}", "")
                if isinstance(raw_stored, str) and raw_stored.strip() in engine.state.instances:
                    stored_uid = raw_stored.strip()
                    stored_inst = engine.state.instances.get(stored_uid)
                    stored_name = _norm(stored_inst.definition.name) if stored_inst is not None else ""
                else:
                    stored_name = _norm(str(raw_stored))
                if stored_name and stored_name in name_variants:
                    continue
            if type_filter and _norm(inst.definition.card_type) not in type_filter:
                continue
            if (
                target.card_filter.exclude_buildings_if_my_building_zone_occupied
                and engine.state.players[owner_idx].building is not None
                and _norm(inst.definition.card_type) == _norm("edificio")
            ):
                continue
            cross_txt = _norm(str(inst.definition.crosses or ""))
            if cross_txt in {"white", "croce bianca"}:
                cross_val = 11
            else:
                try:
                    cross_val = int(float(cross_txt)) if cross_txt else None
                except ValueError:
                    cross_val = None
            if target.card_filter.crosses_gte is not None:
                if cross_val is None or cross_val < int(target.card_filter.crosses_gte):
                    continue
            if target.card_filter.crosses_lte is not None:
                if cross_val is None or cross_val > int(target.card_filter.crosses_lte):
                    continue
            if target.card_filter.strength_gte is not None:
                if int(engine.get_effective_strength(uid)) < int(target.card_filter.strength_gte):
                    continue
            if target.card_filter.strength_lte is not None:
                if int(engine.get_effective_strength(uid)) > int(target.card_filter.strength_lte):
                    continue
            if target.card_filter.drawn_this_turn_only:
                drawn = engine.state.flags.get("cards_drawn_this_turn", {})
                if uid not in set(drawn.get(str(owner_idx), [])):
                    continue
            if target.card_filter.half_cost_lte_my_inspiration:
                total_inspiration = int(engine.state.players[owner_idx].inspiration) + int(
                    getattr(engine.state.players[owner_idx], "temporary_inspiration", 0)
                )
                half_cost = (max(0, int(inst.definition.faith or 0)) + 1) // 2
                if total_inspiration < half_cost:
                    continue
            source_inst = engine.state.instances.get(source_uid) if source_uid else None
            source_type = _norm(source_inst.definition.card_type) if source_inst is not None else ""
            if source_type:
                target_owner = int(inst.owner)
                source_owner = int(source_inst.owner) if source_inst is not None else owner_idx
                target_card_type = _norm(inst.definition.card_type)
                if source_owner != target_owner and target_card_type in {"santo", "token"}:
                    p = engine.state.players[target_owner]
                    protector_uids = [cand for cand in (p.attack + p.defense + p.artifacts) if cand]
                    if p.building:
                        protector_uids.append(p.building)
                    blocked = False
                    for protector_uid in protector_uids:
                        protector_name = engine.state.instances[protector_uid].definition.name
                        if self.blocks_interaction(
                            protector_name,
                            event="target_by_effect",
                            source_owner="enemy",
                            target_owner="friendly",
                            source_card_type=source_type,
                            target_card_type=target_card_type,
                            target_card_name=inst.definition.name,
                        ):
                            blocked = True
                            break
                    if blocked:
                        continue
            out.append(uid)
        return out

    # This method validates the manual target selection for a list of actions that require manual selection. It checks if the selected target meets the requirements for each action, such as having a sufficient pool of selectable targets and ensuring that the selected target is valid for the current action. If any of the actions fail validation, it returns False along with an appropriate error message. If all actions pass validation, it returns True and None for the error message.
    def _validate_manual_target_actions(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        actions: list[ActionSpec],
        selected_target: str | None,
        event_name: str,
        empty_pool_message: str,
        missing_selection_message: str,
    ) -> tuple[bool, str | None]:
        flags = engine.state.flags
        previous_source = flags.get("_runtime_source_card")
        previous_selected = flags.get("_runtime_selected_target")
        previous_action_idx = flags.get("_runtime_action_index")
        manual_actions_present = False
        manual_actions_applicable = False
        has_choose_option_step = False

        flags["_runtime_source_card"] = source_uid
        flags["_runtime_selected_target"] = str(selected_target or "")
        try:
            for action in actions:
                if _norm(action.effect.action) == "choose_option":
                    has_choose_option_step = True
                    break
            for i, action in enumerate(actions):
                if not self._target_requires_manual_selection(action.target):
                    continue
                manual_actions_present = True
                flags["_runtime_action_index"] = str(i)
                if action.condition and not self._eval_condition_node(
                    RuleEventContext(engine=engine, event=event_name, player_idx=owner_idx, payload={"card": source_uid}),
                    owner_idx,
                    action.condition,
                ):
                    continue
                manual_actions_applicable = True
                
                # For each action that requires manual selection, the method first checks if the action's condition is met. If the condition is not met, it skips to the next action. If the condition is met, it then determines how many targets are required for this action and collects the list of selectable targets based on the target specification. If the number of selectable targets is less than the required minimum, it returns False along with a message indicating that there are no valid targets to select. If there are enough selectable targets but the currently selected target does not meet the requirements for this action, it returns False along with a message indicating that a valid target selection is missing. If all actions pass these checks, it returns True and None for the error message.
                required_min = self._required_min_targets_for_manual_target(action.target)
                selectable = self._collect_selectable_targets_for_manual_target(engine, owner_idx, action.target)
                if len(selectable) < required_min:
                    return (False, empty_pool_message)

                raw_for_action = self._selected_target_raw_for_current_action(engine)
                if required_min > 0 and not raw_for_action:
                    return (False, missing_selection_message)

                resolved = self._resolve_targets(engine, owner_idx, action.target)
                if len(resolved) < required_min:
                    return (False, missing_selection_message)
            # Manual-target actions can be fully conditional. If none of them is
            # applicable after condition evaluation, the play/activation must still
            # be considered valid and continue with the remaining actions.
            if manual_actions_present and not manual_actions_applicable and not has_choose_option_step:
                return (True, None)
            return (True, None)
        finally:
            if previous_source is None:
                flags.pop("_runtime_source_card", None)
            else:
                flags["_runtime_source_card"] = previous_source
            if previous_selected is None:
                flags.pop("_runtime_selected_target", None)
            else:
                flags["_runtime_selected_target"] = previous_selected
            if previous_action_idx is None:
                flags.pop("_runtime_action_index", None)
            else:
                flags["_runtime_action_index"] = previous_action_idx
