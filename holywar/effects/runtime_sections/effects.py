from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
import json
from pathlib import Path

from holywar.core import state
from .effects_targeting import RuntimeEffectsTargetingMixin
from .effects_conditions import RuntimeEffectsConditionsMixin
from .effects_resources import RuntimeEffectsResourcesMixin
from .effects_summoning import RuntimeEffectsSummoningMixin
from .effects_combat import RuntimeEffectsCombatMixin
from .effects_board import RuntimeEffectsBoardMixin
from .effects_decking import RuntimeEffectsDeckingMixin
from .effects_removal import RuntimeEffectsRemovalMixin
from holywar.core.state import MAX_HAND, CardInstance
from holywar.scripting_api import RuleEventContext
from holywar.data.importer import load_cards_json
from holywar.data.models import CardDefinition
from holywar.effects.runtime import (
    _norm,
    _card_name_haystack,
    _card_matches_name,
    EFFECT_ACTION_ALIASES,
    CardFilterSpec,
    TargetSpec,
    EffectSpec,
    ActionSpec,
    CardScript,
)

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine

# This module defines the `RuntimeEffectsMixin` class, which provides helper methods for resolving targets, moving cards between zones, summoning tokens, and applying effects based on the card scripts defined in the game. The mixin includes methods for handling various target specifications, managing equipment links, and applying specific effect actions such as increasing faith or returning cards to hand. The methods interact with the game engine's state and instances to perform the necessary operations while ensuring that the game rules are respected. This mixin can be used by the main game engine class to implement the core mechanics of card effects during gameplay.
class RuntimeEffectsMixin(
    RuntimeEffectsBoardMixin,
    RuntimeEffectsCombatMixin,
    RuntimeEffectsRemovalMixin,
    RuntimeEffectsDeckingMixin,
    RuntimeEffectsSummoningMixin,
    RuntimeEffectsResourcesMixin,
    RuntimeEffectsTargetingMixin,
    RuntimeEffectsConditionsMixin,
):
    """Target resolution, zone moves and low-level effect execution helpers."""
    if TYPE_CHECKING:
        _temp_faith: ClassVar[dict[int, dict[str, list[tuple[str, int, str]]]]]
        _scripts: dict[str, Any]

        def get_script(self, card_name: str) -> CardScript | None: ...
        def resolve_play(
            self,
            engine: GameEngine,
            player_idx: int,
            uid: str,
            target: str | None,
        ) -> object: ...

        # The following are method signatures for helper methods that are used within the `RuntimeEffectsMixin` class. These methods are responsible for various tasks such as resolving targets based on the current game state, moving cards between zones, managing equipment links, and evaluating conditions for effects. The actual implementations of these methods would contain the logic to interact with the game engine's state and perform the necessary operations according to the rules of the game.
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
        def _selected_target_uid_for_current_action(self, engine: GameEngine, owner_idx: int) -> str | None: ...
        def _collect_selectable_targets_for_manual_target(
            self,
            engine: GameEngine,
            owner_idx: int,
            target: TargetSpec,
        ) -> list[str]: ...
        def _filter_target_pool(
            self,
            engine: GameEngine,
            owner_idx: int,
            target: TargetSpec,
            pool: list[str],
        ) -> list[str]: ...
        def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool: ...
        def _eval_condition_node(self, ctx: RuleEventContext, owner_idx: int, node: dict[str, Any]) -> bool: ...
        def resolve_enter(self, engine: GameEngine, player_idx: int, uid: str) -> object: ...
        def _run_play_actions(
            self,
            engine: GameEngine,
            owner_idx: int,
            source_uid: str,
            actions: list[ActionSpec],
            start_index: int = 0,
        ) -> None: ...
        def is_immune_to_action(self, card_name: str, action_name: str) -> bool: ...
        def get_is_altare_sigilli(self, card_name: str) -> bool: ...
        def get_is_pyramid(self, card_name: str) -> bool: ...

    def _apply_effect(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
        effect: EffectSpec,
    ) -> None:
        if engine.state.phase == "preparation":
            # Only the player currently arranging their field can resolve
            # automatic effects.  Effects aimed at, or comparing against, the
            # hidden opponent are intentionally dormant during setup.
            if owner_idx != engine.state.active_player:
                return
            opponent_scopes = {"opponent", "enemy", "other"}
            if _norm(effect.target_player or "me") in opponent_scopes:
                return
            if _norm(effect.compare_target_player or "me") in opponent_scopes:
                return
            if _norm(effect.owner or "me") in opponent_scopes:
                return
            targets = [
                target
                for target in targets
                if target not in engine.state.instances
                or int(engine.state.instances[target].owner) == int(owner_idx)
            ]
        action = _norm(effect.action)
        action = EFFECT_ACTION_ALIASES.get(action, action)
        if action == "return_to_hand_once_per_turn":
            self._apply_return_to_hand_once_per_turn(engine, owner_idx, source_uid, targets)
            return
        if not self._effect_usage_can_use(engine, owner_idx, source_uid, effect):
            return
        if self._apply_effect_resource_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if self._apply_effect_summon_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if self._apply_effect_deck_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if self._apply_effect_removal_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if self._apply_effect_combat_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if self._apply_effect_board_action(engine, owner_idx, source_uid, targets, effect, action):
            return
        if action == "choose_option":
            flags = engine.state.flags
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            valid_options: list[dict[str, str]] = []
            for raw_opt in effect.choice_options:
                value = str(raw_opt.get("value", "")).strip()
                if not value:
                    continue
                label = str(raw_opt.get("label", value)).strip() or value
                cond = raw_opt.get("condition", {}) or {}
                if cond:
                    ok = self._eval_condition_node(
                        RuleEventContext(
                            engine=engine,
                            event="on_activate",
                            player_idx=owner_idx,
                            payload={"card": source_uid},
                        ),
                        owner_idx,
                        dict(cond),
                    )
                    if not ok:
                        continue
                valid_options.append({"value": value, "label": label})

            if choice_ready and choice_source == source_uid:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                allowed = {opt["value"] for opt in valid_options}
                flags["_runtime_selected_option"] = selected_raw if selected_raw in allowed else ""
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_values",
                    "_runtime_choice_labels",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            if not valid_options:
                flags["_runtime_selected_option"] = ""
                return

            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_values"] = ";;".join(opt["value"] for opt in valid_options)
            flags["_runtime_choice_labels"] = json.dumps(
                {opt["value"]: opt["label"] for opt in valid_options},
                ensure_ascii=False,
            )
            flags["_runtime_choice_owner"] = str(owner_idx)
            flags["_runtime_choice_title"] = str(effect.choice_title or "Scegli un'opzione")
            flags["_runtime_choice_prompt"] = str(effect.choice_prompt or "Scegli una modalità.")
            flags["_runtime_choice_min_targets"] = "1"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            pending_mode = str(flags.get("_runtime_pending_mode", "")).strip().lower()
            # Trigger-side choose_option needs an explicit trigger_action resume.
            if pending_mode not in {"play", "enter", "activate"}:
                flags["_runtime_resume_source"] = source_uid
                flags["_runtime_resume_owner"] = str(owner_idx)
                flags["_runtime_pending_mode"] = "trigger_action"
                flags["_runtime_trigger_action"] = "choose_option"
                flags["_runtime_trigger_event_name"] = str(flags.get("_runtime_event_name", "")).strip()
                flags["_runtime_trigger_choice_title"] = str(effect.choice_title or "Scegli un'opzione")
                flags["_runtime_trigger_choice_prompt"] = str(effect.choice_prompt or "Scegli una modalità.")
                flags["_runtime_trigger_choice_options"] = json.dumps(valid_options, ensure_ascii=False)
            return

        if action == "choose_draw_amount_with_self_sin_cost":
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            per_card_sin = max(1, int(effect.amount or 15))
            max_safe_draw = max(0, (99 - int(player.sin)) // per_card_sin)

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            if choice_ready and choice_source == source_uid:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                try:
                    requested = int(selected_raw)
                except ValueError:
                    requested = 0
                requested = max(0, min(requested, max_safe_draw))

                drawn = 0
                if requested > 0:
                    drawn = int(engine.draw_cards(target, requested))
                if drawn > 0:
                    engine.gain_sin(target, drawn * per_card_sin)

                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_values",
                    "_runtime_choice_labels",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            values = [str(n) for n in range(max_safe_draw + 1)]
            labels_map = {str(n): (f"{n} carta" if n == 1 else f"{n} carte") for n in range(max_safe_draw + 1)}
            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_values"] = ";;".join(values)
            flags["_runtime_choice_labels"] = json.dumps(labels_map, ensure_ascii=False)
            flags["_runtime_choice_owner"] = str(owner_idx)
            flags["_runtime_choice_title"] = str(effect.choice_title or "Scegli quante carte pescare")
            flags["_runtime_choice_prompt"] = str(
                effect.choice_prompt
                or f"Puoi pescare da 0 a {max_safe_draw} carte senza perdere per Peccato."
            )
            flags["_runtime_choice_min_targets"] = "1"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "choose_and_activate_effect":
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = f"{source_uid}:choose_and_activate_effect:{target}"

            conf = {}
            if effect.choice_options and isinstance(effect.choice_options[0], dict):
                conf = dict(effect.choice_options[0])
            candidate_source = _norm(str(conf.get("candidate_source", "")).strip())
            zone_list = [
                str(z).strip()
                for z in list(conf.get("zones", []) or [])
                if str(z).strip()
            ]
            if not zone_list:
                fallback_zone = str(effect.zone or effect.from_zone or "deck").strip() or "deck"
                zone_list = [fallback_zone]

            allowed_types = {
                _norm(str(v))
                for v in list(conf.get("card_type_in", []) or ["benedizione", "maledizione"])
                if str(v).strip()
            }
            name_contains = _norm(str(conf.get("name_contains", effect.card_name or "")).strip())

            candidates: list[str] = []
            seen: set[str] = set()
            if candidate_source == "initial_deck":
                for uid, inst in engine.state.instances.items():
                    if uid in seen:
                        continue
                    if int(inst.owner) != int(target):
                        continue
                    if bool(getattr(inst.definition, "is_token", False)):
                        continue
                    ctype = _norm(inst.definition.card_type)
                    if allowed_types and ctype not in allowed_types:
                        continue
                    if name_contains and name_contains not in _norm(inst.definition.name):
                        continue
                    candidates.append(uid)
                    seen.add(uid)
            else:
                for z in zone_list:
                    for uid in self._get_zone_cards(engine, target, z):
                        if uid in seen:
                            continue
                        inst = engine.state.instances.get(uid)
                        if inst is None:
                            continue
                        ctype = _norm(inst.definition.card_type)
                        if allowed_types and ctype not in allowed_types:
                            continue
                        if name_contains and name_contains not in _norm(inst.definition.name):
                            continue
                        candidates.append(uid)
                        seen.add(uid)
            if choice_ready and choice_source == expected_choice_source:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_values",
                    "_runtime_choice_labels",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                if selected_uid in candidates and selected_uid in engine.state.instances:
                    activation_turn = int(engine.state.turn_number)
                    replay_guard_key = f"{expected_choice_source}:{selected_uid}:{activation_turn}"
                    if str(flags.get("_runtime_choose_copy_guard", "")).strip() == replay_guard_key:
                        return
                    flags["_runtime_choose_copy_guard"] = replay_guard_key
                    selected_inst = engine.state.instances[selected_uid]
                    selected_script = self._scripts.get(_norm(selected_inst.definition.name), CardScript(name=selected_inst.definition.name))
                    copied_actions = list(selected_script.on_play_actions or [])
                    if copied_actions:
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
                        previous_selected = str(flags.get("_runtime_selected_target", ""))
                        flags.pop("_runtime_resume_same_action", None)
                        flags["_runtime_selected_target"] = ""
                        flags["_runtime_copied_play_card"] = selected_uid
                        flags["_runtime_force_manual_selected_target"] = True
                        try:
                            # Keep Portatore as source card: copy resolves selected effect block
                            # without moving/materializing the selected template card.
                            self._run_play_actions(engine, owner_idx, source_uid, prepared_actions)
                        finally:
                            flags["_runtime_selected_target"] = previous_selected
                            if not flags.get("_runtime_waiting_for_reveal"):
                                flags.pop("_runtime_copied_play_card", None)
                                flags.pop("_runtime_force_manual_selected_target", None)
                    return
                # stale/invalid selection: fall through and reopen prompt

            if not candidates:
                return

            labels: dict[str, str] = {}
            for uid in candidates:
                inst = engine.state.instances.get(uid)
                if inst is None:
                    continue
                effect_text = str(getattr(inst.definition, "effect_text", "") or "").strip()
                if effect_text:
                    labels[uid] = f"{inst.definition.name} - {effect_text}"
                else:
                    labels[uid] = inst.definition.name
            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_values"] = ";;".join(candidates)
            flags["_runtime_choice_labels"] = json.dumps(labels, ensure_ascii=False)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = str(effect.choice_title or "Scegli effetto da copiare")
            flags["_runtime_choice_prompt"] = str(effect.choice_prompt or "Scegli una carta da cui copiare l'effetto.")
            flags["_runtime_choice_min_targets"] = "1"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return

        if action == "choose_targets":
            flags = engine.state.flags
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            min_targets = max(0, int(effect.min_targets if effect.min_targets is not None else 0))
            max_targets = int(effect.max_targets if effect.max_targets is not None else 1)
            max_targets_from_flag = str(getattr(effect, "flag", "") or "").strip()
            if max_targets_from_flag:
                try:
                    max_targets = int(engine.state.flags.get(max_targets_from_flag, max_targets))
                except Exception:
                    pass
            max_targets = max(min_targets, max_targets)

            if choice_ready and choice_source == source_uid:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]
                if max_targets >= 0:
                    selected_uids = selected_uids[:max_targets]
                if len(selected_uids) < min_targets:
                    selected_uids = []
                flags["_runtime_selected_target"] = ",".join(selected_uids)
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            candidates = list(targets)
            if not candidates:
                flags["_runtime_selected_target"] = ""
                return
            selected_for_action = self._selected_target_raw_for_current_action(engine)
            if selected_for_action:
                selected_uids = [v.strip() for v in selected_for_action.split(",") if v.strip()]
                candidate_set = set(candidates)
                selected_uids = [uid for uid in selected_uids if uid in candidate_set]
                if max_targets >= 0:
                    selected_uids = selected_uids[:max_targets]
                if len(selected_uids) >= min_targets:
                    flags["_runtime_selected_target"] = ",".join(selected_uids)
                    return
            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(owner_idx)
            flags["_runtime_choice_title"] = "Selezione Bersaglio"
            flags["_runtime_choice_prompt"] = "Seleziona i bersagli per l'effetto."
            flags["_runtime_choice_min_targets"] = str(min_targets)
            flags["_runtime_choice_max_targets"] = str(max_targets)
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "choose_up_to_n_from_hand_to_relicario_then_draw_same":
            flags = engine.state.flags
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = f"{source_uid}:choose_up_to_n_from_hand_to_relicario_then_draw_same"
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")

            if choice_ready and choice_source == expected_choice_source:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]

                max_cards = int(flags.get("_runtime_trigger_amount", effect.amount or 0) or 0)
                max_cards = max(0, max_cards)
                if max_cards > 0:
                    selected_uids = selected_uids[:max_cards]
                else:
                    selected_uids = []

                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)

                moved = 0
                target_player = engine.state.players[target]
                for uid in selected_uids:
                    if uid not in target_player.hand:
                        continue
                    target_player.hand.remove(uid)
                    if uid in target_player.deck:
                        target_player.deck.remove(uid)
                    target_player.deck.append(uid)
                    moved += 1
                if moved > 0:
                    engine.rng.shuffle(target_player.deck)
                    engine.draw_cards(target, moved)
                return

            player = engine.state.players[target]
            max_cards = max(0, int(effect.amount or 0))
            # A scripted target can narrow the selectable hand cards (Ptah uses
            # this to expose only cards drawn during the current turn).
            candidates = [uid for uid in targets if uid in player.hand] if targets else list(player.hand)
            if not candidates or max_cards <= 0:
                return

            flags["_runtime_choice_source"] = expected_choice_source
            flags.pop("_runtime_choice_values", None)
            flags.pop("_runtime_choice_labels", None)
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = str(effect.choice_title or "Prigioniero Sacrificale")
            flags["_runtime_choice_prompt"] = str(
                effect.choice_prompt or "Scegli fino a 3 carte dalla tua mano da rimettere nel reliquiario."
            )
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = str(max_cards)
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "choose_up_to_n_from_hand_to_relicario_then_draw_same"
            flags["_runtime_trigger_target_player"] = str(effect.target_player or "me")
            flags["_runtime_trigger_amount"] = str(max_cards)
            return

        if action == "optional_redraw_event_card":
            flags = engine.state.flags
            expected_choice_source = f"{source_uid}:optional_redraw_event_card"
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            if choice_ready and choice_source == expected_choice_source:
                selected = str(flags.get("_runtime_choice_selected", "")).strip().lower()
                event_uid = str(flags.pop("_runtime_redraw_event_card", "")).strip()
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_values",
                    "_runtime_choice_labels",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                if selected != "yes" or event_uid not in engine.state.instances:
                    return
                drawn_owner = int(engine.state.instances[event_uid].owner)
                drawn_player = engine.state.players[drawn_owner]
                if event_uid not in drawn_player.hand:
                    return
                usage = flags.setdefault("effect_usage_per_turn", {})
                usage_key = f"optional_redraw_event_card:{owner_idx}:{source_uid}"
                if int(usage.get(usage_key, 0)) >= 1:
                    return
                # Consume Faro only when its controller accepts. Set the marker
                # before the replacement draw to suppress recursive activation.
                usage[usage_key] = 1
                drawn_player.hand.remove(event_uid)
                drawn_player.deck.append(event_uid)
                engine.rng.shuffle(drawn_player.deck)
                engine.draw_cards(drawn_owner, 1)
                return

            event_uid = str(flags.get("_runtime_event_card", "")).strip()
            if event_uid not in engine.state.instances:
                return
            drawn_owner = int(engine.state.instances[event_uid].owner)
            if event_uid not in engine.state.players[drawn_owner].hand:
                return

            # Once accepted, Faro is unavailable for the rest of this turn.
            usage = flags.setdefault("effect_usage_per_turn", {})
            usage_key = f"optional_redraw_event_card:{owner_idx}:{source_uid}"
            if int(usage.get(usage_key, 0)) >= 1:
                return

            flags["_runtime_redraw_event_card"] = event_uid
            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_values"] = "yes;;no"
            flags["_runtime_choice_labels"] = json.dumps({"yes": "Si", "no": "No"}, ensure_ascii=False)
            flags["_runtime_choice_owner"] = str(owner_idx)
            flags["_runtime_choice_title"] = str(effect.choice_title or "Faro di Alessandria")
            flags["_runtime_choice_prompt"] = str(
                effect.choice_prompt
                or "L'avversario ha pescato una carta. Vuoi rimischiarla nel reliquiario e fargli pescare di nuovo?"
            )
            flags["_runtime_choice_min_targets"] = "1"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "optional_redraw_event_card"
            return

        if action == "choose_targets_and_summon_to_field":
            flags = engine.state.flags
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            min_targets = max(0, int(effect.min_targets if effect.min_targets is not None else 0))
            max_targets = int(effect.max_targets if effect.max_targets is not None else 1)
            max_targets = max(min_targets, max_targets)

            expected_choice_source = f"{source_uid}:choose_targets_and_summon_to_field"
            if choice_ready and choice_source == expected_choice_source:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]
                if max_targets >= 0:
                    selected_uids = selected_uids[:max_targets]
                if len(selected_uids) < min_targets:
                    selected_uids = []
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                if selected_uids:
                    self._apply_effect(
                        engine,
                        owner_idx,
                        source_uid,
                        selected_uids,
                        EffectSpec(action="summon_target_to_field"),
                    )
                return

            candidates = list(targets)
            if not candidates:
                return
            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(owner_idx)
            flags["_runtime_choice_title"] = "Evoca dal Cimitero"
            flags["_runtime_choice_prompt"] = "Seleziona il Santo da evocare."
            flags["_runtime_choice_min_targets"] = str(min_targets)
            flags["_runtime_choice_max_targets"] = str(max_targets)
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "choose_targets_and_summon_to_field"
            return
        if action == "sacrifice_time_resolution":
            flags = engine.state.flags
            owner_player = engine.state.players[owner_idx]
            opponent_idx = 1 - owner_idx
            opponent_player = engine.state.players[opponent_idx]
            state_key = f"_sacrifice_time_state_{source_uid}"
            local_state = dict(flags.get(state_key, {}) or {})
            pending = int(local_state.get("pending", 0))

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            if not local_state:
                discarded_count = 0
                for hand_uid in list(owner_player.hand):
                    owner_player.hand.remove(hand_uid)
                    if hand_uid not in owner_player.graveyard:
                        owner_player.graveyard.append(hand_uid)
                        self._shuffle_graveyard_if_oltretomba_active(engine, owner_idx)
                    discarded_count += 1
                    engine._emit_event(
                        "on_card_discarded",
                        owner_idx,
                        card=hand_uid,
                        from_hand_to_graveyard=True,
                    )
                    engine._emit_event(
                        "on_card_sent_to_graveyard",
                        owner_idx,
                        card=hand_uid,
                        from_zone="hand",
                        owner=owner_idx,
                    )
                    self._maybe_auto_activate_discarded_from_hand_by_effect(engine, owner_idx, hand_uid, source_uid)
                pending = discarded_count

            if pending <= 0:
                flags.pop(state_key, None)
                return

            if choice_ready and choice_source == source_uid:
                mode = str(local_state.get("mode", "")).strip()
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]

                if mode == "field":
                    for t_uid in selected_uids:
                        if t_uid in engine.state.instances:
                            engine.send_to_graveyard(engine.state.instances[t_uid].owner, t_uid)
                    pending = max(0, pending - len(selected_uids))
                elif mode == "hand":
                    for t_uid in selected_uids:
                        if t_uid in opponent_player.hand:
                            opponent_player.hand.remove(t_uid)
                            if t_uid not in opponent_player.graveyard:
                                opponent_player.graveyard.append(t_uid)
                                self._shuffle_graveyard_if_oltretomba_active(engine, opponent_idx)
                            pending = max(0, pending - 1)
                            engine._emit_event(
                                "on_card_discarded",
                                opponent_idx,
                                card=t_uid,
                                from_hand_to_graveyard=True,
                            )
                            engine._emit_event(
                                "on_card_sent_to_graveyard",
                                opponent_idx,
                                card=t_uid,
                                from_zone="hand",
                                owner=opponent_idx,
                            )
                            self._maybe_auto_activate_discarded_from_hand_by_effect(engine, opponent_idx, t_uid, source_uid)

                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)

            enemy_field: list[str] = []
            for uid in opponent_player.attack + opponent_player.defense + opponent_player.artifacts:
                if uid:
                    enemy_field.append(uid)
            if opponent_player.building:
                enemy_field.append(opponent_player.building)

            if pending > 0 and enemy_field:
                max_pick = min(pending, len(enemy_field))
                flags[state_key] = {"pending": pending, "mode": "field"}
                flags["_runtime_choice_source"] = source_uid
                flags["_runtime_choice_candidates"] = ";;".join(enemy_field)
                flags["_runtime_choice_owner"] = str(owner_idx)
                flags["_runtime_choice_title"] = "Sacrificio del Tempo"
                flags["_runtime_choice_prompt"] = "Seleziona le carte avversarie sul terreno da inviare al cimitero."
                flags["_runtime_choice_min_targets"] = str(max_pick)
                flags["_runtime_choice_max_targets"] = str(max_pick)
                flags["_runtime_choice_ready"] = False
                flags["_runtime_resume_same_action"] = True
                flags["_runtime_reveal_card"] = source_uid
                flags["_runtime_waiting_for_reveal"] = True
                return

            if pending > 0 and opponent_player.hand:
                max_pick = min(pending, len(opponent_player.hand))
                flags[state_key] = {"pending": pending, "mode": "hand"}
                flags["_runtime_choice_source"] = source_uid
                flags["_runtime_choice_candidates"] = ";;".join(opponent_player.hand)
                flags["_runtime_choice_owner"] = str(owner_idx)
                flags["_runtime_choice_title"] = "Sacrificio del Tempo"
                flags["_runtime_choice_prompt"] = "Seleziona le carte della mano avversaria da scartare."
                flags["_runtime_choice_min_targets"] = str(max_pick)
                flags["_runtime_choice_max_targets"] = str(max_pick)
                flags["_runtime_choice_ready"] = False
                flags["_runtime_resume_same_action"] = True
                flags["_runtime_reveal_card"] = source_uid
                flags["_runtime_waiting_for_reveal"] = True
                return

            while pending > 0 and opponent_player.deck:
                top_uid = opponent_player.deck.pop()
                if top_uid not in opponent_player.graveyard:
                    opponent_player.graveyard.append(top_uid)
                    self._shuffle_graveyard_if_oltretomba_active(engine, opponent_idx)
                pending -= 1
                engine._emit_event(
                    "on_card_sent_to_graveyard",
                    opponent_idx,
                    card=top_uid,
                    from_zone="relicario",
                    owner=opponent_idx,
                )

            if pending > 0 and not opponent_player.deck:
                flags.pop(state_key, None)
                engine.state.winner = owner_idx
                engine.state.log(f"{owner_player.name} vince per effetto di Sacrificio del Tempo.")
                return

            if pending > 0:
                flags[state_key] = {"pending": pending}
                flags["_runtime_resume_same_action"] = True
                return

            flags.pop(state_key, None)
            return
        if action == "discard_hand_then_pressure_opponent":
            flags = engine.state.flags
            owner_player = engine.state.players[owner_idx]
            target_idx = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            target_player = engine.state.players[target_idx]
            per_card_amount = max(1, int(effect.amount or 1))
            discard_trigger_source = str(flags.get("_runtime_discard_trigger_source", "")).strip()

            state_key = f"_runtime_pressure_state_{source_uid}"
            local_state = dict(flags.get(state_key, {}) or {})
            pending = int(local_state.get("pending", 0))

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            if not local_state:
                discarded_count = 0
                for hand_uid in list(owner_player.hand):
                    # Do not count/discard the card that triggered this discard chain.
                    if discard_trigger_source and hand_uid == discard_trigger_source:
                        continue
                    owner_player.hand.remove(hand_uid)
                    if hand_uid not in owner_player.graveyard:
                        owner_player.graveyard.append(hand_uid)
                        self._shuffle_graveyard_if_oltretomba_active(engine, owner_idx)
                    discarded_count += 1
                    engine._emit_event(
                        "on_card_discarded",
                        owner_idx,
                        card=hand_uid,
                        from_hand_to_graveyard=True,
                    )
                    engine._emit_event(
                        "on_card_sent_to_graveyard",
                        owner_idx,
                        card=hand_uid,
                        from_zone="hand",
                        owner=owner_idx,
                    )
                    self._maybe_auto_activate_discarded_from_hand_by_effect(engine, owner_idx, hand_uid, source_uid)
                pending = discarded_count * per_card_amount

            if pending <= 0:
                flags.pop(state_key, None)
                return

            if choice_ready and (not choice_source or choice_source == source_uid):
                mode = str(local_state.get("mode", "")).strip()
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]

                if mode == "field":
                    for t_uid in selected_uids:
                        if t_uid in engine.state.instances:
                            engine.send_to_graveyard(engine.state.instances[t_uid].owner, t_uid)
                    pending = max(0, pending - len(selected_uids))
                elif mode == "hand":
                    for t_uid in selected_uids:
                        if t_uid in target_player.hand:
                            target_player.hand.remove(t_uid)
                            if t_uid not in target_player.graveyard:
                                target_player.graveyard.append(t_uid)
                                self._shuffle_graveyard_if_oltretomba_active(engine, target_idx)
                            pending = max(0, pending - 1)
                            engine._emit_event(
                                "on_card_discarded",
                                target_idx,
                                card=t_uid,
                                from_hand_to_graveyard=True,
                            )
                            engine._emit_event(
                                "on_card_sent_to_graveyard",
                                target_idx,
                                card=t_uid,
                                from_zone="hand",
                                owner=target_idx,
                            )
                            self._maybe_auto_activate_discarded_from_hand_by_effect(engine, target_idx, t_uid, source_uid)

                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)

            target_field: list[str] = []
            for uid in target_player.attack + target_player.defense + target_player.artifacts:
                if uid:
                    target_field.append(uid)
            if target_player.building:
                target_field.append(target_player.building)

            if pending > 0 and target_field:
                max_pick = min(pending, len(target_field))
                flags[state_key] = {"pending": pending, "mode": "field"}
                flags["_runtime_choice_source"] = source_uid
                flags["_runtime_choice_candidates"] = ";;".join(target_field)
                flags["_runtime_choice_owner"] = str(owner_idx)
                flags["_runtime_choice_title"] = str(effect.choice_title or "Selezione Bersagli")
                flags["_runtime_choice_prompt"] = str(
                    effect.choice_prompt or "Seleziona le carte sul terreno da inviare al cimitero."
                )
                flags["_runtime_choice_min_targets"] = str(max_pick)
                flags["_runtime_choice_max_targets"] = str(max_pick)
                flags["_runtime_choice_ready"] = False
                flags["_runtime_resume_same_action"] = True
                flags["_runtime_reveal_card"] = source_uid
                flags["_runtime_waiting_for_reveal"] = True
                return

            if pending > 0 and target_player.hand:
                max_pick = min(pending, len(target_player.hand))
                flags[state_key] = {"pending": pending, "mode": "hand"}
                flags["_runtime_choice_source"] = source_uid
                flags["_runtime_choice_candidates"] = ";;".join(target_player.hand)
                flags["_runtime_choice_owner"] = str(owner_idx)
                flags["_runtime_choice_title"] = str(effect.choice_title or "Selezione Bersagli")
                flags["_runtime_choice_prompt"] = str(effect.choice_prompt or "Seleziona le carte dalla mano da scartare.")
                flags["_runtime_choice_min_targets"] = str(max_pick)
                flags["_runtime_choice_max_targets"] = str(max_pick)
                flags["_runtime_choice_ready"] = False
                flags["_runtime_resume_same_action"] = True
                flags["_runtime_reveal_card"] = source_uid
                flags["_runtime_waiting_for_reveal"] = True
                return

            while pending > 0 and target_player.deck:
                top_uid = target_player.deck.pop()
                if top_uid not in target_player.graveyard:
                    target_player.graveyard.append(top_uid)
                    self._shuffle_graveyard_if_oltretomba_active(engine, target_idx)
                pending -= 1
                engine._emit_event(
                    "on_card_sent_to_graveyard",
                    target_idx,
                    card=top_uid,
                    from_zone="relicario",
                    owner=target_idx,
                )

            if pending > 0 and not target_player.deck:
                flags.pop(state_key, None)
                engine.state.winner = owner_idx
                source_name = engine.state.instances[source_uid].definition.name if source_uid in engine.state.instances else source_uid
                engine.state.log(f"{owner_player.name} vince per effetto di {source_name}.")
                return

            if pending > 0:
                flags[state_key] = {"pending": pending}
                flags["_runtime_resume_same_action"] = True
                return

            flags.pop(state_key, None)
            return
        if action == "store_target_count":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            engine.state.flags[flag_name] = int(len(targets))
            return
        if action == "store_target_name":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            stored_name = ""
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                stored_name = str(inst.definition.name or "").strip()
                break
            engine.state.flags[f"_runtime_store_{flag_name}"] = stored_name
            return
        if action == "store_target_uid":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            stored_uid = ""
            for t_uid in targets:
                if t_uid in engine.state.instances:
                    stored_uid = str(t_uid).strip()
                    break
            engine.state.flags[f"_runtime_store_{flag_name}"] = stored_uid
            return
        if action == "store_distinct_count":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            req = dict(getattr(effect, "requirement", None) or {})
            matches = self._collect_cards_for_requirement(engine, owner_idx, req)
            seen: set[str] = set()
            for uid in matches:
                inst = engine.state.instances.get(uid)
                if inst is None:
                    continue
                seen.add(_norm(inst.definition.name))
            engine.state.flags[flag_name] = int(len(seen))
            return
        if action == "add_link_tag_to_source_from_selected_target":
            source_inst = engine.state.instances.get(source_uid)
            if source_inst is None:
                return
            tag_prefix = str(effect.flag or "link").strip() or "link"
            for t_uid in targets:
                if t_uid not in engine.state.instances:
                    continue
                link_tag = f"{tag_prefix}:{t_uid}"
                if link_tag not in source_inst.blessed:
                    source_inst.blessed.append(link_tag)
            return
        if action == "destroy_linked_targets_from_source_tags":
            source_inst = engine.state.instances.get(source_uid)
            if source_inst is None:
                return
            tag_prefix = str(effect.flag or "link").strip() or "link"
            to_destroy: list[str] = []
            for tag in list(source_inst.blessed):
                if not isinstance(tag, str) or not tag.startswith(f"{tag_prefix}:"):
                    continue
                linked_uid = tag.split(":", 1)[1].strip()
                if linked_uid and linked_uid in engine.state.instances:
                    to_destroy.append(linked_uid)
            for linked_uid in to_destroy:
                linked_inst = engine.state.instances.get(linked_uid)
                if linked_inst is None:
                    continue
                engine.destroy_any_card(linked_inst.owner, linked_uid)
            source_inst.blessed = [
                tag
                for tag in source_inst.blessed
                if not (isinstance(tag, str) and tag.startswith(f"{tag_prefix}:"))
            ]
            return
        if action == "move_all_from_zone_to_zone":
            from_zone = _norm(effect.from_zone or effect.zone or "")
            to_zone = str(effect.to_zone or "").strip()
            if not from_zone or not to_zone:
                return
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            if from_zone == "graveyard":
                pool = list(player.graveyard)
            elif from_zone in {"deck", "relicario"}:
                pool = list(player.deck)
            elif from_zone == "hand":
                pool = list(player.hand)
            elif from_zone == "excommunicated":
                pool = list(player.excommunicated)
            elif from_zone == "field":
                pool = [uid for uid in (player.attack + player.defense + player.artifacts) if uid]
                if player.building:
                    pool.append(player.building)
            else:
                pool = []
            for uid in pool:
                self._move_uid_to_zone(engine, uid, to_zone, target)
            if bool(effect.shuffle_after):
                engine.rng.shuffle(player.deck)
            return
        if action == "activate_oltretomba_promise":
            flags = engine.state.flags
            promise_state = dict(flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
            promise_state[str(owner_idx)] = True
            flags["oltretomba_promise_active"] = promise_state

            player = engine.state.players[owner_idx]
            for uid in list(player.deck):
                if uid not in player.graveyard:
                    player.graveyard.append(uid)
            player.deck = []
            engine.rng.shuffle(player.graveyard)
            engine.state.log("Promessa dell'oltretomba attiva: reliquiario e cimitero diventano la stessa zona.")
            return
        if action == "floor_divide_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            divisor = max(1, int(effect.amount or 1))
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = 0
            engine.state.flags[flag_name] = max(0, value // divisor)
            return
        if action == "draw_cards_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = max(0, int(raw_value))
            except (TypeError, ValueError):
                amount = 0
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            if amount > 0:
                engine.draw_cards(target, amount)
            engine.state.flags.pop(flag_name, None)
            return
        if action == "optional_draw_from_top_n_then_shuffle":
            top_n = max(1, int(effect.amount or 1))
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            flags = engine.state.flags

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            if choice_ready and choice_source == source_uid:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                if selected_uid and selected_uid in candidates and selected_uid in player.deck:
                    self._move_uid_to_zone(engine, selected_uid, "hand", target)
                engine.rng.shuffle(player.deck)
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            candidates = list(player.deck[-top_n:]) if player.deck else []
            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Scegli Carta"
            flags["_runtime_choice_prompt"] = "Scegli una carta tra le prime del reliquiario oppure Nessuna."
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "draw_matching_from_top_n":
            top_n = max(1, int(effect.amount or 1))
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            wanted = _norm(str(effect.card_name or effect.flag or "").strip())
            if not wanted:
                return

            candidates = list(player.deck[-top_n:]) if player.deck else []
            for uid in list(reversed(candidates)):
                inst = engine.state.instances.get(uid)
                if inst is None:
                    continue
                if wanted in _norm(inst.definition.name):
                    self._move_uid_to_zone(engine, uid, "hand", target)
            return
        if action == "reorder_top_n_of_deck":
            top_n = max(1, int(effect.amount or 1))
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            flags = engine.state.flags

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))

            if choice_ready and choice_source == source_uid:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()

                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]

                if len(selected_uids) == len(candidates) and candidates:
                    base_deck = list(player.deck[:-len(candidates)])
                    # selected_uids = ordine desiderato dall'alto verso il basso
                    player.deck = base_deck + list(reversed(selected_uids))

                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                    "_runtime_choice_preserve_order",
                ):
                    flags.pop(key, None)
                return

            candidates = list(reversed(player.deck[-top_n:])) if player.deck else []
            if not candidates:
                return

            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Riordina le carte"
            flags["_runtime_choice_prompt"] = "Seleziona tutte le carte nell'ordine desiderato, dalla prima che vuoi in cima alla quinta."
            flags["_runtime_choice_min_targets"] = str(len(candidates))
            flags["_runtime_choice_max_targets"] = str(len(candidates))
            flags["_runtime_choice_preserve_order"] = True
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "optional_recover_from_graveyard_then_shuffle":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            flags = engine.state.flags
            condition_name = _norm(effect.controller_has_saint_with_name or "")
            conditional_to = str(effect.to_zone_if_controller_has_saint_with_name or "").strip()
            default_to = str(effect.to_zone or "relicario").strip() or "relicario"
            has_condition_saint = False
            if condition_name:
                has_condition_saint = any(
                    _norm(engine.state.instances[uid].definition.name) == condition_name
                    for uid in engine.all_saints_on_field(target)
                )
            destination_zone = conditional_to if (condition_name and has_condition_saint and conditional_to) else default_to

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            if choice_ready and choice_source == source_uid:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                if selected_uid and selected_uid in candidates and selected_uid in player.graveyard:
                    moved = self._move_uid_to_zone(engine, selected_uid, destination_zone, target)
                    if not moved and _norm(destination_zone) == "hand":
                        self._move_uid_to_zone(engine, selected_uid, "relicario", target)
                engine.rng.shuffle(player.deck)
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            candidates = list(player.graveyard)
            if not candidates:
                engine.rng.shuffle(player.deck)
                return
            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Cimitero"
            if _norm(destination_zone) == "hand":
                flags["_runtime_choice_prompt"] = "Scegli una carta dal tuo cimitero da aggiungere alla mano, oppure Nessuna."
            else:
                flags["_runtime_choice_prompt"] = "Scegli una carta dal tuo cimitero da mettere nel reliquiario, oppure Nessuna."
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "optional_recover_cards":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            flags = engine.state.flags

            from_zone = _norm(effect.from_zone or effect.zone or "graveyard")
            to_zone = str(effect.to_zone or "relicario").strip() or "relicario"
            min_targets = max(0, int(effect.min_targets if effect.min_targets is not None else 0))
            max_targets = int(effect.max_targets if effect.max_targets is not None else 1)
            max_targets = max(min_targets, max_targets)

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            if choice_ready and choice_source == source_uid:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                selected_uids = [uid for uid in selected_uids if uid in candidates]
                if max_targets >= 0:
                    selected_uids = selected_uids[:max_targets]

                actual_to_zone = to_zone
                generic_cond = effect.to_zone_if_condition if isinstance(effect.to_zone_if_condition, dict) else None
                generic_to_zone = str(effect.to_zone_if or "").strip()
                if generic_cond and generic_to_zone:
                    cond_ctx = RuleEventContext(engine=engine, event="on_effect", player_idx=target, payload={"card": source_uid})
                    if self._eval_condition_node(cond_ctx, target, generic_cond):
                        actual_to_zone = generic_to_zone
                else:
                    condition_name = _norm(effect.controller_has_saint_with_name or "")
                    conditional_to = str(effect.to_zone_if_controller_has_saint_with_name or "").strip()
                    if condition_name and conditional_to:
                        has_required = any(
                            _card_matches_name(engine.state.instances[uid].definition, condition_name)
                            for uid in engine.all_saints_on_field(target)
                        )
                        actual_to_zone = conditional_to if has_required else to_zone

                for selected_uid in selected_uids:
                    still_available = selected_uid in self._get_zone_cards(engine, target, from_zone)
                    if not still_available:
                        continue
                    moved = self._move_uid_to_zone(engine, selected_uid, actual_to_zone, target)
                    if not moved and _norm(actual_to_zone) == "hand":
                        self._move_uid_to_zone(engine, selected_uid, "relicario", target)

                if effect.shuffle_after:
                    engine.rng.shuffle(player.deck)
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            candidates = self._get_zone_cards(engine, target, from_zone)
            if not candidates:
                if effect.shuffle_after:
                    engine.rng.shuffle(player.deck)
                return

            default_title = "Scegli Carta"
            if from_zone == "graveyard":
                default_title = "Cimitero"
            flags["_runtime_choice_source"] = source_uid
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = default_title
            flags["_runtime_choice_prompt"] = (
                f"Scegli da {from_zone} una o piu carte (min {min_targets}, max {max_targets}) oppure Nessuna."
            )
            flags["_runtime_choice_min_targets"] = str(min_targets)
            flags["_runtime_choice_max_targets"] = str(max_targets)
            flags["_runtime_choice_ready"] = False
            flags["_runtime_resume_same_action"] = True
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            return
        if action == "destroy_card":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                engine.destroy_any_card(inst.owner, t_uid)
            return
        if action == "destroy_all_saints_except_selected":
            required_opponent_selected = max(0, int(effect.min_targets if effect.min_targets is not None else 0))
            selected_set = {
                uid for uid in targets
                if uid in engine.state.instances and _norm(engine.state.instances[uid].definition.card_type) in {"santo", "token"}
            }
            selected_opponent = sum(
                1 for uid in selected_set
                if int(engine.state.instances[uid].owner) != int(owner_idx)
            )
            if selected_opponent < required_opponent_selected:
                engine.state.log("Tornado: selezione non valida, serve almeno un Santo avversario tra i bersagli.")
                return

            tornado_to_destroy: list[tuple[int, str]] = []
            for p_idx in (0, 1):
                p = engine.state.players[p_idx]
                for uid in list(p.attack + p.defense):
                    if uid is None:
                        continue
                    if uid in selected_set:
                        continue
                    inst = engine.state.instances.get(uid)
                    if inst is None:
                        continue
                    if _norm(inst.definition.card_type) not in {"santo", "token"}:
                        continue
                    tornado_to_destroy.append((inst.owner, uid))

            for real_owner, uid in tornado_to_destroy:
                if uid not in engine.state.instances:
                    continue
                engine.destroy_saint_by_uid(real_owner, uid, cause="effect")
            return
        if action == "excommunicate_card":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                ctype = _norm(inst.definition.card_type)
                if ctype in {"santo", "token"}:
                    engine.destroy_saint_by_uid(inst.owner, t_uid, excommunicate=True, cause="effect")
                else:
                    engine.excommunicate_card(inst.owner, t_uid)
            return
        if action == "excommunicate_card_no_sin":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                engine.excommunicate_card(inst.owner, t_uid)
            return
        if action == "excommunicate_top_cards_from_relicario":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            count = max(1, int(effect.amount or 1))
            promise_state = dict(
                engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False})
                or {"0": False, "1": False}
            )
            merged = bool(promise_state.get(str(target), False))
            for _ in range(count):
                player = engine.state.players[target]
                if merged:
                    # With Promessa dell'oltretomba active, deck and graveyard are one logical zone.
                    # Prefer deck top, then graveyard top if deck is empty.
                    if player.deck:
                        top_uid = player.deck[-1]
                        player.deck.pop()
                        engine.excommunicate_card(target, top_uid, from_zone_override="relicario")
                    elif player.graveyard:
                        top_uid = player.graveyard[-1]
                        player.graveyard.pop()
                        engine.excommunicate_card(target, top_uid, from_zone_override="graveyard")
                    else:
                        break
                else:
                    if not player.deck:
                        break
                    top_uid = player.deck[-1]
                    player.deck.pop()
                    engine.excommunicate_card(target, top_uid, from_zone_override="relicario")
            return
        if action in {"draw_by_excommunicated_count_comparison", "draw_by_zone_count_comparison"}:
            first_idx = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            second_idx = self._resolve_player_scope(owner_idx, effect.compare_target_player or "opponent")

            zone_name = effect.compare_zone or "excommunicated"
            if action == "draw_by_excommunicated_count_comparison" and not effect.compare_zone:
                zone_name = "excommunicated"

            first_count = len(self._get_zone_cards(engine, first_idx, zone_name))
            second_count = len(self._get_zone_cards(engine, second_idx, zone_name))

            draw_amount = max(0, int(effect.amount or 0))
            tie_amount = draw_amount if effect.tie_amount is None else max(0, int(effect.tie_amount))
            tie_policy = _norm(effect.tie_policy or "both")
            if draw_amount <= 0 and tie_amount <= 0:
                return

            if first_count > second_count:
                if draw_amount > 0:
                    engine.draw_cards(first_idx, draw_amount)
                return
            if second_count > first_count:
                if draw_amount > 0:
                    engine.draw_cards(second_idx, draw_amount)
                return

            if tie_policy == "none":
                return
            if tie_policy in {"first", "me", "owner"}:
                if tie_amount > 0:
                    engine.draw_cards(first_idx, tie_amount)
                return
            if tie_policy in {"second", "opponent", "other"}:
                if tie_amount > 0:
                    engine.draw_cards(second_idx, tie_amount)
                return

            if tie_amount > 0:
                engine.draw_cards(first_idx, tie_amount)
                if second_idx != first_idx:
                    engine.draw_cards(second_idx, tie_amount)
            return
        if action == "remove_from_board_no_sin":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                engine.remove_from_board_no_sin(inst.owner, t_uid)
            return
        if action == "move_to_hand":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                owner = inst.owner
                moved = self._move_uid_to_zone(engine, t_uid, "hand", owner)
                if moved:
                    engine.state.log(f"{inst.definition.name} viene aggiunta alla mano.")
            return
        if action == "move_first_to_hand":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                owner = inst.owner
                moved = self._move_uid_to_zone(engine, t_uid, "hand", owner)
                if moved:
                    engine.state.log(f"{inst.definition.name} viene aggiunta alla mano.")
                break
            return
        if action == "choose_artifact_from_relicario_then_shuffle":
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = f"{source_uid}:choose_artifact_from_relicario_then_shuffle:{target}"

            if choice_ready and choice_source == expected_choice_source:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                candidates = [v for v in candidates_raw.split(";;") if v]
                if selected_uid in candidates and selected_uid in player.deck:
                    self._move_uid_to_zone(engine, selected_uid, "hand", target)
                engine.rng.shuffle(player.deck)
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)
                return

            candidates = [
                uid for uid in player.deck
                if uid in engine.state.instances and _norm(engine.state.instances[uid].definition.card_type) == _norm("artefatto")
            ]
            if not candidates:
                engine.rng.shuffle(player.deck)
                return

            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Pietra Focaia"
            flags["_runtime_choice_prompt"] = "Scegli un Artefatto dal reliquiario da aggiungere alla mano."
            flags["_runtime_choice_min_targets"] = "1"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "choose_artifact_from_relicario_then_shuffle"
            flags["_runtime_trigger_target_player"] = str(effect.target_player or "me")
            return
        if action in {"optional_recover_all_matching_then_shuffle", "optional_recover_matching_then_shuffle"}:
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            source_inst = engine.state.instances.get(source_uid)
            source_name = source_inst.definition.name if source_inst is not None else "Questa carta"
            needle = _norm(effect.card_name or "")
            from_zone = _norm(effect.from_zone or effect.zone or "graveyard")
            to_zone = str(effect.to_zone or "relicario").strip() or "relicario"
            source_to_zone_on_yes = str(effect.to_zone_if or "").strip()
            should_shuffle = bool(effect.shuffle_after)
            max_to_move = int(effect.amount or 0)

            if from_zone == "graveyard":
                source_pool = list(player.graveyard)
            elif from_zone in {"deck", "relicario"}:
                source_pool = list(player.deck)
            elif from_zone == "excommunicated":
                source_pool = list(player.excommunicated)
            elif from_zone == "hand":
                source_pool = list(player.hand)
            else:
                source_pool = []

            candidates = [
                uid for uid in source_pool
                if uid in engine.state.instances
                and (not needle or needle in _norm(engine.state.instances[uid].definition.name))
                and uid != source_uid
            ]
            candidate_names = [engine.state.instances[uid].definition.name for uid in candidates]
            listed = ", ".join(candidate_names) if candidate_names else "Nessuna carta."

            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = (
                f"{source_uid}:optional_recover_matching_then_shuffle:{target}:{from_zone}:{to_zone}:{needle}:{max_to_move}"
            )

            if choice_ready and choice_source == expected_choice_source:
                selected_raw = str(flags.get("_runtime_choice_selected", "")).strip()
                selected_uids = [v.strip() for v in selected_raw.split(",") if v.strip()]
                allowed = set(candidates)
                selected_uids = [uid for uid in selected_uids if uid in allowed]
                for key in (
                    "_runtime_choice_source",
                    "_runtime_choice_ready",
                    "_runtime_choice_selected",
                    "_runtime_choice_candidates",
                    "_runtime_choice_owner",
                    "_runtime_choice_title",
                    "_runtime_choice_prompt",
                    "_runtime_choice_min_targets",
                    "_runtime_choice_max_targets",
                ):
                    flags.pop(key, None)

                if not selected_uids:
                    return

                moved = 0
                for uid in selected_uids:
                    if self._move_uid_to_zone(engine, uid, to_zone, target):
                        moved += 1
                if should_shuffle:
                    engine.rng.shuffle(player.deck)
                if moved > 0 and source_to_zone_on_yes:
                    source_inst = engine.state.instances.get(source_uid)
                    if source_inst is not None:
                        self._move_uid_to_zone(engine, source_uid, source_to_zone_on_yes, source_inst.owner)
                engine.state.log(f"Effetto opzionale risolto: {moved} carte spostate in {to_zone}.")
                return

            if not candidates:
                return

            max_select = len(candidates)
            if action == "optional_recover_matching_then_shuffle" and max_to_move > 0:
                max_select = min(max_select, max_to_move)
            max_select = max(0, int(max_select))

            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = source_name
            flags["_runtime_choice_prompt"] = (
                f"Attivare l'effetto di {source_name}?\n\n"
                f"Seleziona quali carte spostare da {from_zone} a {to_zone}: {listed}"
            )
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = str(max_select)
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "optional_recover_matching_then_shuffle"
            flags["_runtime_trigger_target_player"] = str(effect.target_player or "me")
            flags["_runtime_trigger_card_name"] = str(effect.card_name or "")
            flags["_runtime_trigger_from_zone"] = str(effect.from_zone or effect.zone or "graveyard")
            flags["_runtime_trigger_to_zone"] = str(effect.to_zone or "relicario")
            flags["_runtime_trigger_amount"] = str(effect.amount or 0)
            flags["_runtime_trigger_shuffle_after"] = "1" if bool(effect.shuffle_after) else "0"
            flags["_runtime_trigger_to_zone_if"] = str(effect.to_zone_if or "")
            return
    #endregion
    #region Utility methods for effects
    def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int:
        key = _norm(scope or "me")
        if key in {"me", "owner", "controller", "self"}:
            return owner_idx
        if key in {"opponent", "enemy", "other"}:
            return 1 - owner_idx
        if key in {"player0", "p0", "0"}:
            return 0
        if key in {"player1", "p1", "1"}:
            return 1
        return owner_idx

    # This method is not currently used but can be helpful for future effects that need to count specific cards on the field.
    def _count_named_cards_on_field(self, engine: GameEngine, card_name: str) -> int:
        key = _norm(card_name)
        total = 0
        for idx in (0, 1):
            p = engine.state.players[idx]
            for uid in p.attack + p.defense + p.artifacts:
                if uid and _norm(engine.state.instances[uid].definition.name) == key:
                    total += 1
            if p.building and _norm(engine.state.instances[p.building].definition.name) == key:
                total += 1
        return total

    # This method is not currently used but can be helpful for future effects that need to count specific cards in a player's hand.
    def _effect_usage_state(self, engine: GameEngine) -> dict[str, int]:
        return engine.state.flags.setdefault("effect_usage_per_turn", {})

    # This method generates a unique key for tracking the usage of an effect based on the engine state, owner index, source UID, and effect details. This allows the system to enforce usage limits on effects that can only be used a certain number of times per turn.
    def _effect_usage_key(self, engine: GameEngine, owner_idx: int, source_uid: str, effect: EffectSpec) -> str:
        group = _norm(effect.action or "effect")
        return f"{group}:{owner_idx}:{source_uid}:{engine.state.turn_number}"

    # This method determines the usage limit for an effect based on its specification. If the effect has a defined usage limit per turn, it returns that limit (ensuring it's at least 1). If there is no usage limit specified, it returns 0, indicating that the effect can be used unlimited times.
    def _effect_usage_limit(self, effect: EffectSpec) -> int:
        if effect.usage_limit_per_turn is not None:
            return max(1, int(effect.usage_limit_per_turn))
        return 0

    # This method checks how many times a specific effect has been used by a player in the current turn. It retrieves the usage count from the engine's state using a unique key generated for that effect. If the effect has not been used yet, it defaults to 0.
    def _effect_usage_used(self, engine: GameEngine, owner_idx: int, source_uid: str, effect: EffectSpec) -> int:
        return int(self._effect_usage_state(engine).get(self._effect_usage_key(engine, owner_idx, source_uid, effect), 0))

    # This method checks if a specific effect can be used by a player based on its usage limit. If the effect has a usage limit of 0 or less, it can be used unlimited times, so the method returns True. Otherwise, it compares the number of times the effect has already been used with the defined limit and returns True if the effect can still be used, or False if the limit has been reached.
    def _effect_usage_can_use(self, engine: GameEngine, owner_idx: int, source_uid: str, effect: EffectSpec) -> bool:
        limit = self._effect_usage_limit(effect)
        if limit <= 0:
            return True
        return self._effect_usage_used(engine, owner_idx, source_uid, effect) < limit

    # This method should be called whenever an effect is successfully used to increment the usage count for that effect in the engine's state. It first checks the usage limit for the effect, and if there is a limit, it generates the unique key for that effect and increments the count in the state. If there is no limit, it does nothing.
    def _effect_usage_consume(self, engine: GameEngine, owner_idx: int, source_uid: str, effect: EffectSpec) -> None:
        limit = self._effect_usage_limit(effect)
        if limit <= 0:
            return
        key = self._effect_usage_key(engine, owner_idx, source_uid, effect)
        usage = self._effect_usage_state(engine)
        usage[key] = int(usage.get(key, 0)) + 1

    # This method implements the logic for an effect that allows a player to return a card to their hand once per turn. It checks if the effect has already been used this turn by looking for a specific marker in the source instance's blessed list. If the effect has not been used, it iterates through the target UIDs, attempts to move each card back to its owner's hand, and if successful, adds the marker to prevent further use of the effect this turn. It also emits an event for each card that leaves the field and returns to the hand.
    def _apply_return_to_hand_once_per_turn(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
    ) -> None:
        source_inst = engine.state.instances.get(source_uid)
        marker = f"once_per_turn:return_to_hand_once_per_turn:{engine.state.turn_number}"
        if source_inst is not None and marker in source_inst.blessed:
            return
        for uid in targets:
            inst = engine.state.instances.get(uid)
            if inst is None:
                continue
            owner = inst.owner
            if not engine.move_board_card_to_hand(owner, uid):
                continue
            if source_inst is not None and marker not in source_inst.blessed:
                source_inst.blessed.append(marker)

    # This method checks if a given event context matches the specified conditions for an effect. It evaluates the conditions recursively, allowing for complex logical structures using "all_of", "any_of", and "not". If the conditions are met, it returns True; otherwise, it returns False.
