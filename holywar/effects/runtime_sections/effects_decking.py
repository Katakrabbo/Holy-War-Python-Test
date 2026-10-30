from __future__ import annotations

import json
from typing import TYPE_CHECKING

from holywar.core import state
from holywar.effects.runtime import _norm, EffectSpec

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsDeckingMixin:
    if TYPE_CHECKING:
        def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int: ...
        def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]: ...
        def _move_uid_to_zone(self, engine: GameEngine, uid: str, to_zone: str, owner_idx: int) -> bool: ...
        def _shuffle_merged_zone_if_active(self, engine: GameEngine, player_idx: int) -> None: ...
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
        def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool: ...

    def _apply_effect_deck_action(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
        effect: EffectSpec,
        action: str,
    ) -> bool:
        if action == "mill_cards":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            player = engine.state.players[target]
            for _ in range(max(0, int(effect.amount))):
                if not player.deck:
                    break
                uid = player.deck.pop()
                player.graveyard.append(uid)
                self._shuffle_merged_zone_if_active(engine, target)
            return True
        if action == "mill_top_and_store_card_type":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            player = engine.state.players[target]
            store_name = str(effect.store_as or "milled_type").strip()
            if not player.deck:
                engine.state.flags[f"_runtime_store_{store_name}"] = ""
                return True
            uid = player.deck.pop()
            player.graveyard.append(uid)
            self._shuffle_merged_zone_if_active(engine, target)
            inst = engine.state.instances.get(uid)
            engine.state.flags[f"_runtime_store_{store_name}"] = _norm(inst.definition.card_type) if inst is not None else ""
            return True
        if action == "draw_if_stored_values_not_equal":
            left_name = str(effect.flag or "").strip()
            right_name = str(effect.stored or "").strip()
            if not left_name or not right_name:
                return True
            left = _norm(str(engine.state.flags.get(f"_runtime_store_{left_name}", "")))
            right = _norm(str(engine.state.flags.get(f"_runtime_store_{right_name}", "")))
            if left and right and left != right:
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                amount = max(0, int(effect.amount or 1))
                if amount > 0:
                    engine.draw_cards(target, amount)
            return True
        if action == "draw_cards_and_store_last_drawn":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            amount = max(0, int(effect.amount or 1))
            store_name = str(effect.store_as or "last_drawn").strip()
            drawn_map = engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})
            before = list(drawn_map.get(str(target), []) or [])
            if amount <= 0:
                engine.state.flags[f"_runtime_store_{store_name}"] = ""
                return True
            engine.draw_cards(target, amount)
            after = list(drawn_map.get(str(target), []) or [])
            new_uids = [uid for uid in after if uid not in before]
            engine.state.flags[f"_runtime_store_{store_name}"] = str(new_uids[-1]) if new_uids else ""
            return True
        if action == "draw_cards":
            target = self._resolve_player_scope(owner_idx, effect.target_player)
            amount = 1 if effect.amount is None else int(effect.amount)
            engine.draw_cards(target, max(0, amount))
            return True
        if action == "draw_cards_and_set_play_cost_for_drawn_until_turn_end":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            draw_amount = max(0, int(effect.amount or 0))
            fixed_cost = max(0, int(effect.override_cost or 0))
            if draw_amount <= 0:
                return True
            drawn_map = engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})
            before = list(drawn_map.get(str(target), []) or [])
            engine.draw_cards(target, draw_amount)
            after = list(drawn_map.get(str(target), []) or [])
            new_uids = [uid for uid in after if uid not in before]
            if not new_uids:
                return True
            cost_map_all = engine.state.flags.setdefault("drawn_play_cost_override_until_turn_end", {"0": {}, "1": {}})
            target_map = dict(cost_map_all.get(str(target), {}) or {})
            for uid in new_uids:
                target_map[str(uid)] = fixed_cost
            cost_map_all[str(target)] = target_map
            return True
        if action == "process_deck_edges_by_type":
            player = engine.state.players[owner_idx]
            deck_now = list(player.deck)
            if not deck_now:
                return True
            top_count = max(0, int(effect.top_count if effect.top_count is not None else 0))
            bottom_count = max(0, int(effect.bottom_count if effect.bottom_count is not None else 0))
            unique_only = bool(effect.unique_edges_only)
            picked: list[str] = []
            for uid in reversed(deck_now[-top_count:]) if top_count > 0 else []:
                if (not unique_only) or uid not in picked:
                    picked.append(uid)
            for uid in (deck_now[:bottom_count] if bottom_count > 0 else []):
                if (not unique_only) or uid not in picked:
                    picked.append(uid)
            saint_token_to = _norm(effect.saint_token_to_zone or "excommunicated")
            blessing_curse_to = _norm(effect.blessing_curse_to_zone or "graveyard")
            artifact_to = _norm(effect.artifact_to_zone or "artifacts")
            building_to = _norm(effect.building_to_zone or "building")
            fallback_to = _norm(effect.fallback_to_zone or "graveyard")
            for uid in picked:
                inst = engine.state.instances.get(uid)
                if inst is None:
                    continue
                if uid in player.deck:
                    player.deck.remove(uid)
                ctype = _norm(inst.definition.card_type)
                if ctype in {"santo", "token"}:
                    if saint_token_to == "excommunicated":
                        engine.excommunicate_card(owner_idx, uid)
                    else:
                        self._move_uid_to_zone(engine, uid, saint_token_to, owner_idx)
                    continue
                if ctype in {"benedizione", "maledizione"}:
                    self._move_uid_to_zone(engine, uid, blessing_curse_to, owner_idx)
                    continue
                if ctype == "artefatto":
                    if artifact_to in {"artifact", "artifacts", "field"}:
                        slot = engine._first_open(player.artifacts)
                        if slot is None and bool(effect.replace_occupied_artifact):
                            slot = len(player.artifacts) - 1
                            replaced_uid = player.artifacts[slot]
                            if replaced_uid:
                                engine.send_to_graveyard(engine.state.instances[replaced_uid].owner, replaced_uid)
                        if slot is not None:
                            player.artifacts[slot] = uid
                        else:
                            self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
                    else:
                        self._move_uid_to_zone(engine, uid, artifact_to, owner_idx)
                    continue
                if ctype == "edificio":
                    if building_to in {"building", "field"}:
                        if player.building and bool(effect.replace_occupied_building):
                            engine.send_to_graveyard(engine.state.instances[player.building].owner, player.building)
                            player.building = uid
                        elif player.building is None:
                            player.building = uid
                        else:
                            self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
                    else:
                        self._move_uid_to_zone(engine, uid, building_to, owner_idx)
                    continue
                self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
            return True
        if action == "draw_cards_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = max(0, int(raw_value))
            except (TypeError, ValueError):
                amount = 0
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            if amount > 0:
                engine.draw_cards(target, amount)
            engine.state.flags.pop(flag_name, None)
            return True
        if action == "optional_draw_from_top_n_then_shuffle":
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            top_n = max(0, int(effect.amount or 0))
            candidates = list(reversed(player.deck[-top_n:])) if top_n > 0 else []
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = f"{source_uid}:optional_draw_from_top_n_then_shuffle:{target}:{top_n}"
            if choice_ready and choice_source == expected_choice_source:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                if selected_uid in candidates:
                    self._move_uid_to_zone(engine, selected_uid, "hand", target)
                engine.rng.shuffle(player.deck)
                for key in ("_runtime_choice_source","_runtime_choice_ready","_runtime_choice_selected","_runtime_choice_candidates","_runtime_choice_owner","_runtime_choice_title","_runtime_choice_prompt","_runtime_choice_min_targets","_runtime_choice_max_targets"):
                    flags.pop(key, None)
                return True
            if not candidates:
                engine.rng.shuffle(player.deck)
                return True
            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Scelta dal reliquiario"
            flags["_runtime_choice_prompt"] = "Scegli una carta da aggiungere alla mano, poi mischia il reliquiario."
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "optional_draw_from_top_n_then_shuffle"
            return True
        if action == "draw_matching_from_top_n":
            top_n = max(0, int(effect.amount or 0))
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            needle = _norm(effect.card_name or "")
            for uid in reversed(player.deck[-top_n:]) if top_n > 0 else []:
                if uid in engine.state.instances and (not needle or needle in _norm(engine.state.instances[uid].definition.name)):
                    self._move_uid_to_zone(engine, uid, "hand", target)
                    break
            return True
        if action == "reorder_top_n_of_deck":
            count = max(0, int(effect.amount or 0))
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            if count <= 1 or len(player.deck) < count:
                return True
            top = list(player.deck[-count:])
            player.deck[-count:] = list(reversed(top))
            return True
        if action == "optional_recover_from_graveyard_then_shuffle":
            flags = engine.state.flags
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            candidates = list(player.graveyard)
            choice_source = str(flags.get("_runtime_choice_source", "")).strip()
            choice_ready = bool(flags.get("_runtime_choice_ready"))
            expected_choice_source = f"{source_uid}:optional_recover_from_graveyard_then_shuffle:{target}"
            if choice_ready and choice_source == expected_choice_source:
                selected_uid = str(flags.get("_runtime_choice_selected", "")).strip()
                if selected_uid in candidates:
                    self._move_uid_to_zone(engine, selected_uid, str(effect.to_zone or "relicario"), target)
                if bool(effect.shuffle_after):
                    engine.rng.shuffle(player.deck)
                for key in ("_runtime_choice_source","_runtime_choice_ready","_runtime_choice_selected","_runtime_choice_candidates","_runtime_choice_owner","_runtime_choice_title","_runtime_choice_prompt","_runtime_choice_min_targets","_runtime_choice_max_targets"):
                    flags.pop(key, None)
                return True
            if not candidates:
                return True
            flags["_runtime_choice_source"] = expected_choice_source
            flags["_runtime_choice_candidates"] = ";;".join(candidates)
            flags["_runtime_choice_owner"] = str(target)
            flags["_runtime_choice_title"] = "Recupera dal cimitero"
            flags["_runtime_choice_prompt"] = "Scegli una carta da recuperare."
            flags["_runtime_choice_min_targets"] = "0"
            flags["_runtime_choice_max_targets"] = "1"
            flags["_runtime_choice_ready"] = False
            flags["_runtime_reveal_card"] = source_uid
            flags["_runtime_waiting_for_reveal"] = True
            flags["_runtime_resume_source"] = source_uid
            flags["_runtime_resume_owner"] = str(owner_idx)
            flags["_runtime_pending_mode"] = "trigger_action"
            flags["_runtime_trigger_action"] = "optional_recover_from_graveyard_then_shuffle"
            return True
        if action == "optional_recover_cards":
            for uid in list(targets)[: max(0, int(effect.amount or len(targets) or 0))]:
                if uid in engine.state.instances:
                    self._move_uid_to_zone(engine, uid, str(effect.to_zone or "hand"), engine.state.instances[uid].owner)
            return True
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
                return True
            if first_count > second_count:
                if draw_amount > 0:
                    engine.draw_cards(first_idx, draw_amount)
                return True
            if second_count > first_count:
                if draw_amount > 0:
                    engine.draw_cards(second_idx, draw_amount)
                return True
            if tie_policy == "none":
                return True
            if tie_policy in {"first", "me", "owner"}:
                if tie_amount > 0:
                    engine.draw_cards(first_idx, tie_amount)
                return True
            if tie_policy in {"second", "opponent", "other"}:
                if tie_amount > 0:
                    engine.draw_cards(second_idx, tie_amount)
                return True
            if tie_amount > 0:
                engine.draw_cards(first_idx, tie_amount)
                if second_idx != first_idx:
                    engine.draw_cards(second_idx, tie_amount)
            return True
        return False
