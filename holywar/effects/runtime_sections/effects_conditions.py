from __future__ import annotations

from typing import TYPE_CHECKING, Any

from holywar.core import state
from holywar.core import query_helpers as query_ops
from holywar.effects.runtime import _norm, _card_name_haystack, _card_matches_name, CardFilterSpec, TargetSpec

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine
    from holywar.scripting_api import RuleEventContext


class RuntimeEffectsConditionsMixin:
    if TYPE_CHECKING:
        def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool: ...
        def _target_owner_indices(self, owner_idx: int, owner_key: str | None) -> list[int]: ...
        def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]: ...
        def _filter_target_pool(self, engine: GameEngine, owner_idx: int, target: TargetSpec, pool: list[str]) -> list[str]: ...
        def get_is_pyramid(self, card_name: str) -> bool: ...
        def get_provides_player_counter(self, card_name: str) -> bool: ...

    def _event_matches(self, ctx: "RuleEventContext", owner_idx: int, condition: dict[str, Any]) -> bool:
        if not condition:
            return True
        return self._eval_condition_node(ctx, owner_idx, condition)

    def _condition_reads_opponent(self, value: Any) -> bool:
        """Return whether a scripted condition depends on the hidden side."""
        if isinstance(value, dict):
            for key, nested in value.items():
                key_norm = _norm(str(key))
                if "opponent" in key_norm or "enemy" in key_norm or key_norm.startswith("both_players"):
                    return True
                if self._condition_reads_opponent(nested):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            return any(self._condition_reads_opponent(item) for item in value)
        return _norm(str(value)) in {"opponent", "enemy", "other"}

    # This method evaluates a condition node, which can contain logical operators ("all_of", "any_of", "not") and leaf conditions. It processes the logical structure accordingly and ultimately evaluates the leaf conditions to determine if the overall condition is satisfied.
    def _eval_condition_node(self, ctx: "RuleEventContext", owner_idx: int, node: dict[str, Any]) -> bool:
        if not node:
            return True
        if ctx.engine.state.phase == "preparation" and self._condition_reads_opponent(node):
            return False
        all_of = node.get("all_of")
        if isinstance(all_of, list):
            for sub in all_of:
                if isinstance(sub, dict) and not self._eval_condition_node(ctx, owner_idx, sub):
                    return False
        any_of = node.get("any_of")
        if isinstance(any_of, list) and any_of:
            ok = False
            for sub in any_of:
                if isinstance(sub, dict) and self._eval_condition_node(ctx, owner_idx, sub):
                    ok = True
                    break
            if not ok:
                return False
        not_of = node.get("not")
        if isinstance(not_of, dict) and self._eval_condition_node(ctx, owner_idx, not_of):
            return False
        return self._eval_condition_leaf(ctx, owner_idx, node)

    # This method evaluates a leaf condition by checking various properties of the event context against the specified criteria. It checks for conditions related to the event's payload, such as zones, card ownership, card types, turn scope, phase, source card status, and target card properties. If any of the conditions are not met, it returns False; if all conditions are satisfied, it returns True.
    def _eval_condition_leaf(self, ctx: "RuleEventContext", owner_idx: int, condition: dict[str, Any]) -> bool:
        payload = ctx.payload
        event_card_uid = str(payload.get("card", payload.get("saint", payload.get("token", ""))))

        from_zone_in = condition.get("payload_from_zone_in")
        if from_zone_in:
            from_zone = _norm(str(payload.get("from_zone", "")))
            allowed = {_norm(z) for z in from_zone_in}
            if from_zone not in allowed:
                return False

        to_zone_in = condition.get("payload_to_zone_in")
        if to_zone_in:
            to_zone = _norm(str(payload.get("to_zone", payload.get("destination", ""))))
            allowed_to = {_norm(z) for z in to_zone_in}
            if to_zone not in allowed_to:
                return False
        target_slot_is_set = condition.get("payload_target_slot_is_set")
        if target_slot_is_set is not None:
            has_target_slot = payload.get("target_slot") is not None
            if bool(target_slot_is_set) != has_target_slot:
                return False
        payload_target_player = condition.get("payload_target_player")
        if payload_target_player is not None:
            raw_target = payload.get("target_player")
            if raw_target is None:
                return False
            try:
                target_idx = int(raw_target)
            except (TypeError, ValueError):
                return False
            wanted = _norm(str(payload_target_player))
            if wanted == "me" and target_idx != int(owner_idx):
                return False
            elif wanted == "opponent" and target_idx != (1 - int(owner_idx)):
                return False
            elif wanted not in {"me", "opponent"}:
                try:
                    if target_idx != int(payload_target_player):
                        return False
                except (TypeError, ValueError):
                    return False
        payload_target_owner = condition.get("payload_target_owner")
        if payload_target_owner is not None:
            target_uid = str(payload.get("target", "")).strip()
            if not target_uid or target_uid not in ctx.engine.state.instances:
                return False
            target_owner = int(ctx.engine.state.instances[target_uid].owner)
            wanted = _norm(str(payload_target_owner))
            if wanted == "me" and target_owner != int(owner_idx):
                return False
            elif wanted == "opponent" and target_owner != (1 - int(owner_idx)):
                return False
            elif wanted not in {"me", "opponent"}:
                try:
                    if target_owner != int(payload_target_owner):
                        return False
                except (TypeError, ValueError):
                    return False

        owner_rule = _norm(str(condition.get("event_card_owner", "")))
        if owner_rule:
            if not event_card_uid:
                return False
            inst = ctx.engine.state.instances.get(event_card_uid)
            if inst is None:
                return False
            expected_owner = owner_idx if owner_rule in {"me", "owner", "controller"} else (1 - owner_idx)
            if int(inst.owner) != int(expected_owner):
                return False
        owner_attack_count_gte = condition.get("event_card_owner_attack_count_gte")
        if owner_attack_count_gte is not None:
            if not event_card_uid:
                return False
            inst = ctx.engine.state.instances.get(event_card_uid)
            if inst is None:
                return False
            attack_count = ctx.engine.state.flags.setdefault("attack_count", {"0": 0, "1": 0})
            if int(attack_count.get(str(inst.owner), 0)) < int(owner_attack_count_gte):
                return False

        ctype_in = condition.get("event_card_type_in")
        if ctype_in:
            if not event_card_uid:
                return False
            inst = ctx.engine.state.instances.get(event_card_uid)
            if inst is None:
                return False
            allowed_types = {_norm(v) for v in ctype_in}
            event_type = _norm(inst.definition.card_type)
            if event_type not in allowed_types and not (event_type == "token" and "santo" in allowed_types):
                return False

        turn_scope = _norm(str(condition.get("turn_scope", "")))
        if turn_scope:
            if turn_scope in {"my", "owner", "controller"} and int(ctx.engine.state.active_player) != int(owner_idx):
                return False
            if turn_scope in {"opponent", "enemy"} and int(ctx.engine.state.active_player) == int(owner_idx):
                return False

        phase_is = _norm(str(condition.get("phase_is", "")))
        if phase_is:
            runtime_state = ctx.engine.state.flags.setdefault("runtime_state", {})
            current_phase = _norm(str(runtime_state.get("phase", "")))
            if phase_is != current_phase:
                return False

        if condition.get("source_on_field") is True:
            source_uid = str(payload.get("source", "")).strip()
            if not source_uid:
                source_uid = str(ctx.engine.state.flags.get("_runtime_source_card", "")).strip()
            if not source_uid or not self._is_uid_on_field(ctx.engine, source_uid):
                return False
        source_counter_gte = condition.get("source_counter_gte")
        if source_counter_gte is not None:
            source_uid = str(payload.get("source", "")).strip()
            if not source_uid:
                source_uid = str(ctx.engine.state.flags.get("_runtime_source_card", "")).strip()
            if not source_uid:
                source_uid = str(payload.get("card", "")).strip()
            if not source_uid or source_uid not in ctx.engine.state.instances:
                return False
            source_inst = ctx.engine.state.instances[source_uid]
            counter = 0
            for tag in list(source_inst.blessed):
                if not isinstance(tag, str) or not tag.startswith(f"{source_counter_gte['key']}:"):
                    continue
                try:
                    counter = int(tag.split(":", 1)[1])
                except ValueError:
                    counter = 0
                break
            if counter < int(source_counter_gte["amount"]):
                return False
        selected_target_exists = condition.get("selected_target_exists")
        if selected_target_exists is not None:
            selected_raw = str(ctx.engine.state.flags.get("_runtime_selected_target", "")).strip()
            selected_uid = selected_raw.split(",", 1)[0].strip() if selected_raw else ""
            has_selected_target = bool(selected_uid and selected_uid in ctx.engine.state.instances)
            if bool(selected_target_exists) != has_selected_target:
                return False

        target_uid = str(payload.get("card", ""))
        if target_uid and target_uid in ctx.engine.state.instances:
            target_inst = ctx.engine.state.instances[target_uid]
            current_faith = target_inst.current_faith if target_inst.current_faith is not None else (target_inst.definition.faith or 0)
        else:
            target_inst = None
            current_faith = None

        target_current_faith_gte = condition.get("target_current_faith_gte")
        if target_current_faith_gte is not None:
            if current_faith is None or current_faith < int(target_current_faith_gte):
                return False
        target_current_faith_lte = condition.get("target_current_faith_lte")
        if target_current_faith_lte is not None:
            if current_faith is None or current_faith > int(target_current_faith_lte):
                return False

        controller_has_name = condition.get("controller_has_saint_with_name")
        if controller_has_name:
            wanted = _norm(str(controller_has_name))
            if not any(
                _card_matches_name(ctx.engine.state.instances[uid].definition, wanted)
                for uid in ctx.engine.all_saints_on_field(owner_idx)
            ):
                return False
        artifact_name = condition.get("controller_has_artifact_with_name")
        if artifact_name:
            wanted = _norm(str(artifact_name))
            if not any(
                a_uid and _card_matches_name(ctx.engine.state.instances[a_uid].definition, wanted)
                for a_uid in ctx.engine.state.players[owner_idx].artifacts
            ):
                return False
        controller_has_cards = condition.get("controller_has_cards")
        if isinstance(controller_has_cards, dict):
            min_count = max(0, int(controller_has_cards.get("min_count", 1) or 1))
            if len(self._collect_cards_for_requirement(ctx.engine, owner_idx, controller_has_cards)) < min_count:
                return False
        sacrifice_name = condition.get("can_play_by_sacrificing_specific_card_from_field")
        if sacrifice_name:
            wanted = _norm(str(sacrifice_name))
            p = ctx.engine.state.players[owner_idx]
            found = False
            for zone_uid in p.attack + p.defense + p.artifacts:
                if zone_uid and _card_matches_name(ctx.engine.state.instances[zone_uid].definition, wanted):
                    found = True
                    break
            if not found and p.building:
                found = _card_matches_name(ctx.engine.state.instances[p.building].definition, wanted)
            if not found:
                return False
        can_play_by_sacrificing = condition.get("can_play_by_sacrificing")
        if isinstance(can_play_by_sacrificing, dict):
            count = max(1, int(can_play_by_sacrificing.get("count", 1) or 1))
            if len(self._collect_cards_for_requirement(ctx.engine, owner_idx, can_play_by_sacrificing)) < count:
                return False

        hand_name = condition.get("controller_has_card_in_hand_with_name")
        if hand_name:
            wanted = _norm(str(hand_name))
            if not any(
                _card_matches_name(ctx.engine.state.instances[uid].definition, wanted)
                for uid in ctx.engine.state.players[owner_idx].hand
            ):
                return False
        building_name = condition.get("controller_has_building_with_name")
        if building_name:
            wanted = _norm(str(building_name))
            b_uid = ctx.engine.state.players[owner_idx].building
            if b_uid is None or not _card_matches_name(ctx.engine.state.instances[b_uid].definition, wanted):
                return False
        building_match = condition.get("controller_has_building_matching")
        if isinstance(building_match, dict):
            b_uid = ctx.engine.state.players[owner_idx].building
            if b_uid is None:
                return False
            req: dict[str, Any] = {"owner": "me", "zone": "field"}
            if "card_filter" in building_match and isinstance(building_match.get("card_filter"), dict):
                req["card_filter"] = dict(building_match.get("card_filter") or {})
            else:
                req["card_filter"] = dict(building_match)
            matches = self._collect_cards_for_requirement(ctx.engine, owner_idx, req)
            if b_uid not in matches:
                return False
        event_name_is = condition.get("event_card_name_is")
        if event_name_is:
            if not event_card_uid:
                return False
            wanted = _norm(str(event_name_is))
            inst = ctx.engine.state.instances.get(event_card_uid)
            if inst is None or not _card_matches_name(inst.definition, wanted):
                return False
        event_name_contains = condition.get("event_card_name_contains")
        if event_name_contains:
            if not event_card_uid:
                return False
            wanted = _norm(str(event_name_contains))
            inst = ctx.engine.state.instances.get(event_card_uid)
            if inst is None:
                return False
            if wanted not in _card_name_haystack(inst.definition):
                return False
        target_is_damaged = condition.get("target_is_damaged")
        if target_is_damaged:
            if target_inst is None:
                return False
            if (current_faith or 0) >= (target_inst.definition.faith or 0):
                return False
        deck_name = condition.get("controller_has_card_in_deck_with_name")
        if deck_name:
            wanted = _norm(str(deck_name))
            if not any(
                _card_matches_name(ctx.engine.state.instances[uid].definition, wanted)
                for uid in ctx.engine.state.players[owner_idx].deck
            ):
                return False
        drawn_this_turn_gte = condition.get("controller_drawn_cards_this_turn_gte")
        if drawn_this_turn_gte is not None:
            drawn = ctx.engine.state.flags.get("cards_drawn_this_turn", {})
            if len(drawn.get(str(owner_idx), [])) < int(drawn_this_turn_gte):
                return False
        hand_size_lte = condition.get("controller_hand_size_lte")
        if hand_size_lte is not None:
            if len(ctx.engine.state.players[owner_idx].hand) > int(hand_size_lte):
                return False
        hand_size_equals_opponent = condition.get("controller_hand_size_equals_opponent")
        if hand_size_equals_opponent:
            if len(ctx.engine.state.players[owner_idx].hand) != len(ctx.engine.state.players[1 - owner_idx].hand):
                return False
        free_artifact_slots_gte = condition.get("controller_free_artifact_slots_gte")
        if free_artifact_slots_gte is not None:
            player = ctx.engine.state.players[owner_idx]
            blocked_slots = query_ops.get_blocked_artifact_slots_for_player(ctx.engine, owner_idx)
            usable_slots = [idx for idx in range(state.ARTIFACT_SLOTS) if idx not in blocked_slots]
            free_slots = sum(1 for idx in usable_slots if player.artifacts[idx] is None)
            if free_slots < int(free_artifact_slots_gte):
                return False
        saints_to_graveyard_gte = condition.get("controller_saints_sent_to_graveyard_this_turn_gte")
        if saints_to_graveyard_gte is not None:
            counts = ctx.engine.state.flags.get("saints_sent_to_graveyard_this_turn", {"0": 0, "1": 0})
            if int(counts.get(str(owner_idx), 0)) < int(saints_to_graveyard_gte):
                return False
        counter_condition = condition.get("controller_counter_gte")
        if counter_condition is not None:
            if self.get_player_counter(ctx.engine, owner_idx, counter_condition["key"]) < int(counter_condition["amount"]):
                return False
        distinct_saints_gte = condition.get("controller_has_distinct_saints_gte")
        if distinct_saints_gte is not None:
            names = {
                _norm(ctx.engine.state.instances[uid].definition.name)
                for uid in ctx.engine.all_saints_on_field(owner_idx)
            }
            if len(names) < int(distinct_saints_gte):
                return False
        distinct_cards_cfg = condition.get("controller_has_distinct_cards_gte")
        if isinstance(distinct_cards_cfg, dict):
            min_count = int(distinct_cards_cfg.get("min_count", 1) or 1)
            matches = self._collect_cards_for_requirement(ctx.engine, owner_idx, dict(distinct_cards_cfg))
            names = {
                _norm(ctx.engine.state.instances[uid].definition.name)
                for uid in matches
                if uid in ctx.engine.state.instances
            }
            if len(names) < min_count:
                return False
        selected_option = _norm(str(ctx.engine.state.flags.get("_runtime_selected_option", "")))
        selected_option_in = condition.get("selected_option_in")
        if selected_option_in:
            allowed = {_norm(v) for v in selected_option_in}
            if selected_option not in allowed:
                return False

        selected_target = _norm(str(ctx.engine.state.flags.get("_runtime_selected_target", "")))
        selected_target_in = condition.get("selected_target_in")
        if selected_target_in:
            allowed = {_norm(v) for v in selected_target_in}
            if selected_target not in allowed:
                return False
        selected_target_card_type_in = condition.get("selected_target_card_type_in")
        if selected_target_card_type_in:
            selected_uid_raw = str(ctx.engine.state.flags.get("_runtime_selected_target", "")).strip()
            selected_uid = selected_uid_raw.split(",", 1)[0].strip() if selected_uid_raw else ""
            if not selected_uid or selected_uid not in ctx.engine.state.instances:
                return False
            selected_inst = ctx.engine.state.instances[selected_uid]
            allowed_types = {_norm(str(v)) for v in list(selected_target_card_type_in or [])}
            selected_type = _norm(selected_inst.definition.card_type)
            if allowed_types and selected_type not in allowed_types and not (
                selected_type == "token" and "santo" in allowed_types
            ):
                return False
        selected_target_startswith = condition.get("selected_target_startswith")
        if selected_target_startswith:
            prefix = _norm(str(selected_target_startswith))
            if not selected_target.startswith(prefix):
                return False
        stored_card_matches = condition.get("stored_card_matches")
        if stored_card_matches:
            store_name = str(stored_card_matches.get("stored", "")).strip()
            if not store_name:
                return False

            stored_uid = str(ctx.engine.state.flags.get(f"_runtime_store_{store_name}", "")).strip()
            if not stored_uid:
                return False

            inst = ctx.engine.state.instances.get(stored_uid)
            if inst is None:
                return False

            filt = stored_card_matches.get("card_filter", {}) or {}

            name_haystack = _card_name_haystack(inst.definition)
            name_contains = _norm(str(filt.get("name_contains", "")))
            if name_contains and name_contains not in name_haystack:
                return False

            name_not_contains = _norm(str(filt.get("name_not_contains", "")))
            if name_not_contains and name_not_contains in name_haystack:
                return False

            type_filter = {_norm(v) for v in list(filt.get("card_type_in", []) or [])}
            stored_type = _norm(inst.definition.card_type)
            if type_filter and stored_type not in type_filter and not (
                stored_type == "token" and "santo" in type_filter
            ):
                return False

        opp = 1 - owner_idx
        my_saints_gte = condition.get("my_saints_gte")
        if my_saints_gte is not None and len(ctx.engine.all_saints_on_field(owner_idx)) < int(my_saints_gte):
            return False
        my_saints_lte = condition.get("my_saints_lte")
        if my_saints_lte is not None and len(ctx.engine.all_saints_on_field(owner_idx)) > int(my_saints_lte):
            return False
        my_saints_lt_opponent = condition.get("my_saints_lt_opponent")
        if my_saints_lt_opponent:
            if len(ctx.engine.all_saints_on_field(owner_idx)) >= len(ctx.engine.all_saints_on_field(opp)):
                return False
        opp_saints_gte = condition.get("opponent_saints_gte")
        if opp_saints_gte is not None and len(ctx.engine.all_saints_on_field(opp)) < int(opp_saints_gte):
            return False
        opp_saints_lte = condition.get("opponent_saints_lte")
        if opp_saints_lte is not None and len(ctx.engine.all_saints_on_field(opp)) > int(opp_saints_lte):
            return False

        my_player = ctx.engine.state.players[owner_idx]
        opp_player = ctx.engine.state.players[opp]

        my_total_inspiration = int(my_player.inspiration) + int(getattr(my_player, "temporary_inspiration", 0))
        opp_total_inspiration = int(opp_player.inspiration) + int(getattr(opp_player, "temporary_inspiration", 0))

        my_insp_gte = condition.get("my_inspiration_gte")
        if my_insp_gte is not None and my_total_inspiration < int(my_insp_gte):
            return False

        my_insp_lte = condition.get("my_inspiration_lte")
        if my_insp_lte is not None and my_total_inspiration > int(my_insp_lte):
            return False

        my_spent_insp_gte = condition.get("my_spent_inspiration_turn_gte")
        if my_spent_insp_gte is not None:
            spent = ctx.engine.state.flags.get("spent_inspiration_turn", {"0": 0, "1": 0})
            if int(spent.get(str(owner_idx), 0)) < int(my_spent_insp_gte):
                return False

        my_attack_count_lte = condition.get("my_attack_count_lte")
        if my_attack_count_lte is not None:
            attack_count = ctx.engine.state.flags.get("attack_count", {"0": 0, "1": 0})
            if int(attack_count.get(str(owner_idx), 0)) > int(my_attack_count_lte):
                return False

        opp_insp_gte = condition.get("opponent_inspiration_gte")
        if opp_insp_gte is not None and opp_total_inspiration < int(opp_insp_gte):
            return False
        my_sin_gte = condition.get("my_sin_gte")
        if my_sin_gte is not None and int(ctx.engine.state.players[owner_idx].sin) < int(my_sin_gte):
            return False
        my_sin_lte = condition.get("my_sin_lte")
        if my_sin_lte is not None and int(ctx.engine.state.players[owner_idx].sin) > int(my_sin_lte):
            return False
        opp_sin_gte = condition.get("opponent_sin_gte")
        if opp_sin_gte is not None and int(ctx.engine.state.players[opp].sin) < int(opp_sin_gte):
            return False
        opp_sin_lte = condition.get("opponent_sin_lte")
        if opp_sin_lte is not None and int(ctx.engine.state.players[opp].sin) > int(opp_sin_lte):
            return False

        reason_in = condition.get("payload_reason_in")
        if reason_in:
            reason = _norm(str(payload.get("reason", "")))
            allowed_reason = {_norm(v) for v in reason_in}
            if reason not in allowed_reason:
                return False
        return True

    # This method collects card UIDs that match the specified requirement criteria for a given player. It considers the zones to search, applies card filters, and returns a list of matching card UIDs. The method also handles special script-based filters for specific card types.
    def _collect_cards_for_requirement(self, engine: GameEngine, owner_idx: int, requirement: dict[str, Any]) -> list[str]:
        owner_key = str(requirement.get("owner", "me"))
        zones = list(requirement.get("zones", []) or [])
        if not zones:
            zones = [str(requirement.get("zone", "field"))]

        card_filter = dict(requirement.get("card_filter", {}) or {})
        script_is_pyramid = card_filter.pop("script_is_pyramid", None)
        script_provides_player_counter = card_filter.pop("script_provides_player_counter", None)
        raw_crosses_gte = card_filter.get("crosses_gte")
        raw_crosses_lte = card_filter.get("crosses_lte")
        raw_strength_gte = card_filter.get("strength_gte")
        raw_strength_lte = card_filter.get("strength_lte")
        crosses_gte: int | None = None
        crosses_lte: int | None = None
        strength_gte: int | None = None
        strength_lte: int | None = None
        if raw_crosses_gte is not None:
            crosses_gte = int(raw_crosses_gte)
        if raw_crosses_lte is not None:
            crosses_lte = int(raw_crosses_lte)
        if raw_strength_gte is not None:
            strength_gte = int(raw_strength_gte)
        if raw_strength_lte is not None:
            strength_lte = int(raw_strength_lte)
        target = TargetSpec(
            type="cards_controlled_by_owner",
            owner=owner_key,
            zone=str(zones[0]) if zones else "field",
            zones=[str(z) for z in zones],
            card_filter=CardFilterSpec(
                name_in=[str(v) for v in list(card_filter.get("name_in", []) or [])],
                name_equals=str(card_filter.get("name_equals")) if card_filter.get("name_equals") is not None else None,
                name_contains=str(card_filter.get("name_contains")) if card_filter.get("name_contains") is not None else None,
                name_not_contains=(
                    str(card_filter.get("name_not_contains")) if card_filter.get("name_not_contains") is not None else None
                ),
                name_not_equals_stored=(
                    str(card_filter.get("name_not_equals_stored"))
                    if card_filter.get("name_not_equals_stored") is not None
                    else None
                ),
                card_type_in=[str(v) for v in list(card_filter.get("card_type_in", []) or [])],
                crosses_gte=crosses_gte,
                crosses_lte=crosses_lte,
                strength_gte=strength_gte,
                strength_lte=strength_lte,
            ),
        )

        pool: list[str] = []
        for scoped_owner in self._target_owner_indices(owner_idx, owner_key):
            for zone_name in target.zones if target.zones else [target.zone]:
                pool.extend(self._get_zone_cards(engine, scoped_owner, zone_name))
        deduped_pool = list(dict.fromkeys(pool))
        filtered = self._filter_target_pool(engine, owner_idx, target, deduped_pool)
        if script_is_pyramid is not None:
            wanted = bool(script_is_pyramid)
            filtered = [
                uid
                for uid in filtered
                if self.get_is_pyramid(engine.state.instances[uid].effect_name) is wanted
            ]
        if script_provides_player_counter is not None:
            wanted = bool(script_provides_player_counter)
            filtered = [
                uid
                for uid in filtered
                if self.get_provides_player_counter(engine.state.instances[uid].effect_name) is wanted
            ]
        return filtered

    # This method is responsible for resolving any pending temporary control returns at the end of a player's turn. It checks the engine's state for any records of cards that need to be returned to their original controllers, verifies if the conditions for return are met (such as the current turn and the presence of the card on the field), and then moves the card back to its original position if necessary. If the card cannot be returned to its original position, it attempts to place it in an open slot on the field. The method also ensures that any "sin_to_controller_on_death" blessings are removed from the card when it is returned.
    def resolve_end_turn_runtime_hooks(self, engine: GameEngine, current_player_idx: int) -> None:
        runtime_state = engine.state.flags.setdefault("runtime_state", {})
        pending_returns = list(runtime_state.get("temporary_control_returns", []) or [])
        if not pending_returns:
            return

        keep: list[dict[str, Any]] = []
        current_turn = int(engine.state.turn_number)

        for rec in pending_returns:
            uid = str(rec.get("uid", "")).strip()
            expires_turn = int(rec.get("expires_turn", -1))
            if not uid or expires_turn != current_turn:
                keep.append(rec)
                continue
            if uid not in engine.state.instances:
                continue

            from_owner = int(rec.get("from_owner", -1))
            to_owner = int(rec.get("to_owner", -1))
            from_zone = _norm(str(rec.get("from_zone", "attack")))
            from_slot = int(rec.get("from_slot", -1))
            if from_owner not in (0, 1) or to_owner not in (0, 1):
                continue

            inst = engine.state.instances[uid]
            board_owner = engine._find_board_owner_of_uid(uid)
            if board_owner is None:
                inst.blessed = [tag for tag in inst.blessed if str(tag) != "sin_to_controller_on_death"]
                continue

            if int(board_owner) != int(to_owner):
                inst.blessed = [tag for tag in inst.blessed if str(tag) != "sin_to_controller_on_death"]
                continue

            to_player = engine.state.players[to_owner]
            moved_from_attack = False
            moved_slot = -1
            if uid in to_player.attack:
                moved_slot = int(to_player.attack.index(uid))
                to_player.attack[moved_slot] = None
                moved_from_attack = True
                back_uid = to_player.defense[moved_slot]
                if back_uid is not None and to_player.attack[moved_slot] is None:
                    to_player.attack[moved_slot] = back_uid
                    to_player.defense[moved_slot] = None
            elif uid in to_player.defense:
                moved_slot = int(to_player.defense.index(uid))
                to_player.defense[moved_slot] = None
            else:
                inst.blessed = [tag for tag in inst.blessed if str(tag) != "sin_to_controller_on_death"]
                continue

            from_player = engine.state.players[from_owner]
            placed = False
            if from_zone == "attack" and 0 <= from_slot < len(from_player.attack) and from_player.attack[from_slot] is None:
                from_player.attack[from_slot] = uid
                placed = True
            elif from_zone == "defense" and 0 <= from_slot < len(from_player.defense) and from_player.defense[from_slot] is None:
                from_player.defense[from_slot] = uid
                placed = True
            else:
                slot = engine._first_open(from_player.attack)
                if slot is not None:
                    from_player.attack[slot] = uid
                    placed = True
                else:
                    slot = engine._first_open(from_player.defense)
                    if slot is not None:
                        from_player.defense[slot] = uid
                        placed = True

            if not placed:
                if moved_from_attack and 0 <= moved_slot < len(to_player.attack) and to_player.attack[moved_slot] is None:
                    to_player.attack[moved_slot] = uid
                elif (not moved_from_attack) and 0 <= moved_slot < len(to_player.defense) and to_player.defense[moved_slot] is None:
                    to_player.defense[moved_slot] = uid
                else:
                    slot = engine._first_open(to_player.attack)
                    if slot is not None:
                        to_player.attack[slot] = uid
                    else:
                        slot = engine._first_open(to_player.defense)
                        if slot is not None:
                            to_player.defense[slot] = uid
                keep.append(rec)
                continue

            inst.blessed = [tag for tag in inst.blessed if str(tag) != "sin_to_controller_on_death"]

        runtime_state["temporary_control_returns"] = keep
