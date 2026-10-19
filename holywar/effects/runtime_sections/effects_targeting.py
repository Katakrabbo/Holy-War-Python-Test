from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from holywar.core.state import MAX_HAND, CardInstance
from holywar.data.importer import load_cards_json
from holywar.data.models import CardDefinition
from holywar.effects.runtime import _norm, TargetSpec, CardScript

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsTargetingMixin:
    if TYPE_CHECKING:
        def get_script(self, card_name: str) -> CardScript | None: ...
        def resolve_play(
            self,
            engine: GameEngine,
            player_idx: int,
            uid: str,
            target: str | None,
        ) -> object: ...
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
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
        def resolve_enter(self, engine: GameEngine, player_idx: int, uid: str) -> object: ...
        def _target_owner_indices(self, owner_idx: int, owner_key: str | None) -> list[int]: ...
        def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]: ...

    def _has_invert_saint_summon_aura(self, engine: GameEngine) -> bool:
        for p_idx in (0, 1):
            player = engine.state.players[p_idx]
            field_uids = [uid for uid in (player.attack + player.defense + player.artifacts) if uid]
            if player.building:
                field_uids.append(player.building)
            for uid in field_uids:
                inst = engine.state.instances.get(uid)
                if inst is None:
                    continue
                script = self.get_script(inst.definition.name)
                if script and bool(script.inverts_saint_summon_controller):
                    return True
        return False

    def _maybe_auto_activate_discarded_from_hand_by_effect(
        self,
        engine: GameEngine,
        discarded_owner_idx: int,
        discarded_uid: str,
        source_uid: str,
    ) -> None:
        if not source_uid or source_uid == discarded_uid:
            return
        inst = engine.state.instances.get(discarded_uid)
        if inst is None:
            return
        script = self.get_script(inst.definition.name)
        if script is None:
            return
        if not bool(script.play_requirements.get("auto_activate_when_discarded_from_hand_by_effect", False)):
            return
        flags = engine.state.flags
        previous_trigger_source = flags.get("_runtime_discard_trigger_source")
        flags["_runtime_discard_trigger_source"] = str(source_uid or "")
        try:
            self.resolve_play(engine, discarded_owner_idx, discarded_uid, None)
        finally:
            if previous_trigger_source is None:
                flags.pop("_runtime_discard_trigger_source", None)
            else:
                flags["_runtime_discard_trigger_source"] = previous_trigger_source

    # This method resolves the targets specified by a `TargetSpec` based on the current game state and the owner of the effect. It handles various types of target specifications, such as cards controlled by the owner, event cards, source cards, equipped targets, and selected targets. The method collects potential targets into a pool and then filters them according to the criteria defined in the `TargetSpec`. Finally, it returns a list of resolved target UIDs, limited by the `max_targets` property if specified.
    def _resolve_targets(self, engine: GameEngine, owner_idx: int, target: TargetSpec) -> list[str]:
        pool: list[str] = []
        ttype = _norm(target.type)
        if ttype == "cards_controlled_by_owner":
            zones = [z for z in target.zones if str(z).strip()]
            if not zones:
                zones = [target.zone]
            for scoped_owner in self._target_owner_indices_for_effect(engine, owner_idx, target.owner):
                p = engine.state.players[scoped_owner]
                for zone_name in zones:
                    zone = _norm(zone_name)
                    if zone == "field":
                        for uid in p.attack + p.defense + p.artifacts:
                            if uid:
                                pool.append(uid)
                        if p.building:
                            pool.append(p.building)
                    elif zone == "hand":
                        pool.extend(p.hand)
                    elif zone in {"deck", "relicario"}:
                        promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
                        merged = bool(promise_state.get(str(scoped_owner), False))
                        if merged:
                            # when merged, include both deck and graveyard
                            pool.extend(p.deck)
                            pool.extend([uid for uid in p.graveyard if uid not in p.deck])
                        else:
                            pool.extend(p.deck)
                    elif zone == "graveyard":
                        promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
                        merged = bool(promise_state.get(str(scoped_owner), False))
                        if merged:
                            pool.extend(p.graveyard)
                            pool.extend([uid for uid in p.deck if uid not in p.graveyard])
                        else:
                            pool.extend(p.graveyard)
                    elif zone == "excommunicated":
                        pool.extend(p.excommunicated)
        elif ttype == "event_card":
            event_uid = str(engine.state.flags.get("_runtime_event_card", ""))
            if event_uid:
                pool.append(event_uid)
        elif ttype == "source_card":
            source_uid = str(engine.state.flags.get("_runtime_source_card", ""))
            if source_uid:
                pool.append(source_uid)
        elif ttype == "event_source_card":
            source_uid = str(engine.state.flags.get("_runtime_event_source", ""))
            if source_uid:
                pool.append(source_uid)
        elif ttype == "equipped_target_of_source":
            source_uid = str(engine.state.flags.get("_runtime_source_card", "")).strip()
            if source_uid:
                equipped_uid = self._equipment_target_uid(engine, source_uid)
                if equipped_uid:
                    pool.append(equipped_uid)
        elif ttype == "selected_target":
            raw_selected = self._selected_target_raw_for_current_action(engine)
            if raw_selected:
                selected = raw_selected.split(",", 1)[0].strip()

                if selected.startswith("buff:"):
                    selected = selected.split(":", 1)[1]

                # If the selected target is directly a UID of an instance, add it to the pool. Otherwise, attempt to resolve it based on the specified syntax and the current game state.
                if selected in engine.state.instances:
                    pool.append(selected)
                else:
                    source_uid = str(engine.state.flags.get("_runtime_source_card", "")).strip()
                    owner_key = _norm(target.owner)
                    allow_any_owner = owner_key in {"any", "both", "all", "either"}
                    owner_candidates = self._target_owner_indices_for_effect(engine, owner_idx, target.owner)

                    # The following block checks if the selected target includes a side prefix (e.g., "opp:", "self:") and adjusts the owner candidates and the selected token accordingly. This allows for more flexible target specifications where the player can indicate whether they are referring to their own cards or their opponent's cards.
                    if ":" in selected:
                        side, token = selected.split(":", 1)
                        side_key = _norm(side)
                        if side_key in {"o", "opp", "enemy", "opponent", "other"}:
                            owner_candidates = [1 - owner_idx]
                            selected = token.strip()
                        elif side_key in {"s", "self", "me", "own", "owner", "controller"}:
                            owner_candidates = [owner_idx]
                            selected = token.strip()

                    # The following block attempts to resolve the selected target by checking various zones (attack, defense, artifacts, building) for each of the owner candidates. If a matching UID is found in the specified zone, it is added to the pool. If the selected target cannot be resolved through these means, it falls back to checking if the selected token matches any selectable targets based on the current game state and the criteria defined in the `TargetSpec`.
                    resolved = False
                    fallback_uid: str | None = None
                    for real_owner in owner_candidates:
                        p = engine.state.players[real_owner]
                        zone, slot = engine._parse_zone_target(selected)
                        if zone is not None:
                            if zone == "attack" and 0 <= slot < len(p.attack):
                                uid = p.attack[slot]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                            elif zone == "defense" and 0 <= slot < len(p.defense):
                                uid = p.defense[slot]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                        elif selected.startswith("r") and len(selected) == 2 and selected[1].isdigit():
                            art_idx = int(selected[1]) - 1
                            if 0 <= art_idx < len(p.artifacts):
                                uid = p.artifacts[art_idx]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                        elif selected == "b":
                            if p.building:
                                if allow_any_owner and p.building == source_uid and len(owner_candidates) > 1:
                                    fallback_uid = p.building
                                    continue
                                pool.append(p.building)
                                resolved = True
                                break

                    # If the target was not resolved through the specified syntax and zones, but a fallback UID was identified (e.g., when the selected target matches the source card and the specification allows for any owner), add the fallback UID to the pool.
                    if not resolved and fallback_uid:
                        pool.append(fallback_uid)
                        resolved = True

                    # If the target was still not resolved, attempt to match the selected token against selectable targets based on the current game state and the criteria defined in the `TargetSpec`. This allows for more flexible targeting where the player can specify a token that matches certain characteristics of potential targets, rather than relying solely on specific syntax or UIDs.
                    if not resolved:
                        lookup = selected
                        if ":" in lookup:
                            pref, val = lookup.split(":", 1)
                            pref_key = _norm(pref)
                            if pref_key in {"deck", "relicario", "grave", "graveyard", "excom", "excommunicated"}:
                                lookup = val.strip()
                        selectable = self._collect_selectable_targets_for_manual_target(engine, owner_idx, target)
                        for candidate_uid in selectable:
                            if _norm(engine.state.instances[candidate_uid].definition.name) == _norm(lookup):
                                pool.append(candidate_uid)
                                break
            else:
                if bool(engine.state.flags.get("_runtime_force_manual_selected_target")):
                    return []
                # Fallback for copied/auto-resolved effects: build candidates from zones/filters
                # and auto-pick enough targets to satisfy the action.
                min_targets = max(0, int(target.min_targets if target.min_targets is not None else 0))
                max_targets = int(target.max_targets if target.max_targets is not None else 1)
                zones = [z for z in target.zones if str(z).strip()]
                if not zones:
                    zones = [target.zone]
                fallback_pool: list[str] = []
                for scoped_owner in self._target_owner_indices_for_effect(engine, owner_idx, target.owner):
                    for zone_name in zones:
                        fallback_pool.extend(self._get_zone_cards(engine, scoped_owner, zone_name))
                filtered = self._filter_target_pool(engine, owner_idx, target, fallback_pool)
                pick_count = max(1, min_targets) if max_targets != 0 else 0
                if max_targets > 0:
                    pick_count = min(pick_count, max_targets)
                if filtered and pick_count > 0:
                    pool.extend(filtered[:pick_count])

        # The following block handles the case where the target type is "selected_targets", which allows for multiple targets to be specified in a comma-separated format. It processes each selected target in the same way as the single "selected_target" case, allowing for flexible targeting based on the current game state and the criteria defined in the `TargetSpec`.
        elif ttype == "selected_targets":
            raw_selected = self._selected_target_raw_for_current_action(engine)
            if raw_selected:
                parts = [part.strip() for part in raw_selected.split(",") if part.strip()]
                source_uid = str(engine.state.flags.get("_runtime_source_card", "")).strip()
                owner_key = _norm(target.owner)
                allow_any_owner = owner_key in {"any", "both", "all", "either"}

                # Process each selected target in the comma-separated list, applying the same resolution logic as for a single selected target. This allows for multiple targets to be specified and resolved in a single action, providing greater flexibility for effects that can affect multiple cards or instances based on player selection.
                for selected in parts:
                    if selected.startswith("buff:"):
                        selected = selected.split(":", 1)[1]

                    if selected in engine.state.instances:
                        pool.append(selected)
                        continue

                    # Check for side prefixes (e.g., "opp:", "self:") to determine owner candidates and adjust the selected token accordingly. This allows for more flexible targeting specifications where the player can indicate whether they are referring to their own cards or their opponent's cards for each selected target.
                    owner_candidates = self._target_owner_indices_for_effect(engine, owner_idx, target.owner)
                    if ":" in selected:
                        side, token = selected.split(":", 1)
                        side_key = _norm(side)
                        if side_key in {"o", "opp", "enemy", "opponent", "other"}:
                            owner_candidates = [1 - owner_idx]
                            selected = token.strip()
                        elif side_key in {"s", "self", "me", "own", "owner", "controller"}:
                            owner_candidates = [owner_idx]
                            selected = token.strip()

                    # The following block attempts to resolve the selected target by checking various zones (attack, defense, artifacts, building) for each of the owner candidates. If a matching UID is found in the specified zone, it is added to the pool. If the selected target cannot be resolved through these means, it falls back to checking if the selected token matches any selectable targets based on the current game state and the criteria defined in the `TargetSpec`.
                    resolved = False
                    fallback_uid: str | None = None
                    for real_owner in owner_candidates:
                        p = engine.state.players[real_owner]
                        zone, slot = engine._parse_zone_target(selected)
                        if zone is not None:
                            if zone == "attack" and 0 <= slot < len(p.attack):
                                uid = p.attack[slot]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                            elif zone == "defense" and 0 <= slot < len(p.defense):
                                uid = p.defense[slot]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                        elif selected.startswith("r") and len(selected) == 2 and selected[1].isdigit():
                            art_idx = int(selected[1]) - 1
                            if 0 <= art_idx < len(p.artifacts):
                                uid = p.artifacts[art_idx]
                                if uid:
                                    if allow_any_owner and uid == source_uid and len(owner_candidates) > 1:
                                        fallback_uid = uid
                                        continue
                                    pool.append(uid)
                                    resolved = True
                                    break
                        elif selected == "b" and p.building:
                            if allow_any_owner and p.building == source_uid and len(owner_candidates) > 1:
                                fallback_uid = p.building
                                continue
                            pool.append(p.building)
                            resolved = True
                            break

                    # If the target was not resolved through the specified syntax and zones, but a fallback UID was identified (e.g., when the selected target matches the source card and the specification allows for any owner), add the fallback UID to the pool.
                    if not resolved and fallback_uid:
                        pool.append(fallback_uid)
                        resolved = True

                    # If the target was still not resolved, attempt to match the selected token against selectable targets based on the current game state and the criteria defined in the `TargetSpec`. This allows for more flexible targeting where the player can specify a token that matches certain characteristics of potential targets, rather than relying solely on specific syntax or UIDs.
                    if not resolved and selected not in engine.state.instances:
                        selectable = self._collect_selectable_targets_for_manual_target(engine, owner_idx, target)
                        for candidate_uid in selectable:
                            if _norm(engine.state.instances[candidate_uid].definition.name) == _norm(selected):
                                pool.append(candidate_uid)
                                break
            else:
                if bool(engine.state.flags.get("_runtime_force_manual_selected_target")):
                    return []
                zones = [z for z in target.zones if str(z).strip()]
                if not zones:
                    zones = [target.zone]
                fallback_pool: list[str] = []
                for scoped_owner in self._target_owner_indices_for_effect(engine, owner_idx, target.owner):
                    for zone_name in zones:
                        fallback_pool.extend(self._get_zone_cards(engine, scoped_owner, zone_name))
                filtered = self._filter_target_pool(engine, owner_idx, target, fallback_pool)
                min_targets = max(0, int(target.min_targets if target.min_targets is not None else 0))
                max_targets = int(target.max_targets if target.max_targets is not None else len(filtered))
                if max_targets < 0:
                    max_targets = len(filtered)
                pick_count = max(1, min_targets)
                pick_count = min(pick_count, max_targets, len(filtered))
                if pick_count > 0:
                    pool.extend(filtered[:pick_count])
        elif ttype == "all_saints_on_field":
            pool.extend(engine.all_saints_on_field(0))
            pool.extend(engine.all_saints_on_field(1))
        elif ttype == "empty_saint_slots_controlled_by_owner":
            for scoped_owner in self._target_owner_indices_for_effect(engine, owner_idx, target.owner):
                player = engine.state.players[scoped_owner]
                for i, slot_uid in enumerate(player.attack):
                    if slot_uid is None:
                        pool.append(f"a{i + 1}")
                for i, slot_uid in enumerate(player.defense):
                    if slot_uid is None:
                        pool.append(f"d{i + 1}")
            if target.max_targets is not None and target.max_targets >= 0:
                return pool[: int(target.max_targets)]
            return pool
        else:
            return []

        # After collecting potential targets into the pool based on the target type and specifications, filter the pool according to the criteria defined in the `TargetSpec` using the `_filter_target_pool` method. This allows for further refinement of the targets based on additional conditions or attributes specified in the `TargetSpec`. Finally, if a `max_targets` limit is specified in the `TargetSpec`, return only up to that number of targets from the filtered pool.
        out = self._filter_target_pool(engine, owner_idx, target, pool)
        if target.max_targets is not None and target.max_targets >= 0:
            return out[: int(target.max_targets)]
        return out

    # This helper function provides a template for initializing player-specific flags in the runtime state. It returns a dictionary with default values for various flags related to the player's turn ownership, current phase of the game, and other state information that will be used to determine what actions the player can take and the status of their saints on the field. This template is used when ensuring that the runtime state is properly initialized for each player in the game engine's state flags.
    def _resolve_owner_scope(self, owner_idx: int, owner_key: str | None) -> int:
        key = _norm(owner_key or "me")
        return owner_idx if key in {"me", "owner", "controller"} else 1 - owner_idx

    # This helper function determines the relevant player indices based on the owner index and the owner key specified in the target. It normalizes the owner key and checks if it indicates that the targets should be from the opponent, any player, or just the owner. Based on this, it returns a list of player indices that should be considered when resolving targets for effects. This allows for flexible targeting specifications where effects can apply to the owner's cards, the opponent's cards, or both players' cards depending on the context of the effect.
    def _target_owner_indices(self, owner_idx: int, owner_key: str | None) -> list[int]:
        key = _norm(owner_key or "me")
        if key in {"opponent", "enemy", "other"}:
            return [1 - owner_idx]
        if key in {"any", "both", "all", "either"}:
            return [owner_idx, 1 - owner_idx]
        return [owner_idx]

    def _target_owner_indices_for_effect(
        self,
        engine: GameEngine,
        owner_idx: int,
        owner_key: str | None,
    ) -> list[int]:
        """Resolve a target scope without crossing a hidden setup boundary."""
        if engine.state.phase == "preparation":
            key = _norm(owner_key or "me")
            if key in {"opponent", "enemy", "other"}:
                return []
            return [owner_idx]
        return self._target_owner_indices(owner_idx, owner_key)

    def _shuffle_graveyard_if_oltretomba_active(self, engine: GameEngine, player_idx: int) -> None:
        promise_state = dict(
            engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False}
        )
        if bool(promise_state.get(str(player_idx), False)):
            engine.rng.shuffle(engine.state.players[player_idx].graveyard)

    # This method retrieves the list of card UIDs in a specified zone for a given player. It normalizes the zone name and checks which zone is being requested (e.g., deck, hand, graveyard, field) and returns the corresponding list of card UIDs from the player's state. For the field zone, it combines the attack, defense, artifacts, and building zones to return all cards currently on the field for that player. This method is used to access the cards in different zones when resolving effects that target specific zones or when applying effects that move cards between zones.
    def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]:
        player = engine.state.players[owner_idx]
        zone = _norm(zone_name)
        promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
        promise_active = bool(promise_state.get(str(owner_idx), False))

        # The following block checks the specified zone and returns the corresponding list of card UIDs for that zone. It handles various zones such as deck, hand, graveyard, excommunicated, and field. For the field zone, it combines the attack, defense, artifacts, and building zones to return all cards currently on the field for that player. This allows for easy access to the cards in different zones when resolving effects that target specific zones or when applying effects that move cards between zones.
        if zone in {"deck", "relicario", "graveyard"}:
            if promise_active:
                # When Promessa dell'oltretomba is active, deck and graveyard are the same logical zone.
                # Return cards from both graveyard and deck so queries counting either zone include both pools.
                # Preserve graveyard order first and avoid duplicates.
                merged = list(player.graveyard) + [uid for uid in player.deck if uid not in player.graveyard]
                return merged
            if zone in {"deck", "relicario"}:
                return list(player.deck)
            return list(player.graveyard)
        if zone == "hand":
            return list(player.hand)
        if zone == "excommunicated":
            return list(player.excommunicated)

        # For the field zone, combine the attack, defense, artifacts, and building zones to return all cards currently on the field for that player. This allows for easy access to all cards on the field when resolving effects that target the field or when applying effects that interact with cards on the field.
        out: list[str] = []
        if zone == "field":
            for uid in player.attack + player.defense + player.artifacts:
                if uid:
                    out.append(uid)
            if player.building:
                out.append(player.building)
            return out
        if zone == "attack":
            return [uid for uid in player.attack if uid]
        if zone == "defense":
            return [uid for uid in player.defense if uid]
        if zone in {"artifact", "artifacts"}:
            return [uid for uid in player.artifacts if uid]
        if zone == "building":
            return [player.building] if player.building else []
        return out

    # This method removes a specified card UID from all zones of a given player. It checks each zone (hand, deck, graveyard, excommunicated, attack, defense, artifacts, building) for the presence of the UID and removes it if found. For cards on the field (attack, defense, artifacts), if a card is removed from the attack zone and there is a corresponding card in the defense zone, it promotes the defense card to the attack zone. This method is used to ensure that when a card is moved or removed from play, it is properly taken out of all zones where it might be present for that player.
    def _remove_uid_from_all_player_zones(self, engine: GameEngine, owner_idx: int, uid: str) -> bool:
        player = engine.state.players[owner_idx]

        if uid in player.hand:
            player.hand.remove(uid)
            return True
        if uid in player.deck:
            player.deck.remove(uid)
            return True
        if uid in player.graveyard:
            player.graveyard.remove(uid)
            return True
        if uid in player.excommunicated:
            player.excommunicated.remove(uid)
            return True

        # The following block iterates through the attack, defense, and artifacts zones to find and remove the specified UID. If the UID is found in the attack zone, it checks if there is a corresponding card in the defense zone at the same slot. If there is a card in the defense zone and the attack slot becomes empty after removal, it promotes the defense card to the attack zone and clears the defense slot. This ensures that the game state remains consistent when cards are removed from play, especially when they are on the field.
        for zone_list in (player.attack, player.defense, player.artifacts):
            for i, slot_uid in enumerate(zone_list):
                if slot_uid == uid:
                    zone_list[i] = None
                    if zone_list is player.attack:
                        back_uid = player.defense[i]
                        if back_uid is not None and player.attack[i] is None:
                            player.attack[i] = back_uid
                            player.defense[i] = None
                            engine.state.log(
                                f"{engine.state.instances[back_uid].definition.name} avanza dalla difesa all'attacco."
                            )
                    return True

        if player.building == uid:
            player.building = None
            return True

        return False

    # This method moves a specified card UID to a target zone for a given player. It first checks if the card instance exists and retrieves the real owner of the card. It then determines the current zone of the card and whether it is leaving the field. Depending on the target zone, it performs the necessary operations to move the card, such as adding it to the player's hand, deck, graveyard, or field. If the card is moving from the field, it resets its runtime state. The method returns True if the move was successful and False if it was not possible (e.g., if trying to move a card to hand when the hand is full).
    def _move_uid_to_zone(self, engine: GameEngine, uid: str, to_zone: str, owner_idx: int) -> bool:
        inst = engine.state.instances.get(uid)
        if inst is None:
            return False

        real_owner = inst.owner
        player = engine.state.players[real_owner]
        zone = _norm(to_zone)
        from_zone = engine._locate_uid_zone(real_owner, uid)
        leaving_field = from_zone in {"attack", "defense", "artifact", "building"}

        # The following block handles moving the card to the hand zone. It checks if the card is already in the player's hand, and if not, it checks if there is space in the hand (not exceeding MAX_HAND). If there is space, it removes the card from all other zones and adds it to the player's hand. If the card is leaving the field, it also resets its runtime state. This ensures that the card is properly moved to the hand while respecting game rules such as hand size limits.
        if zone == "hand":
            if uid in player.hand:
                return True
            if len(player.hand) >= MAX_HAND:
                return False
            self._remove_uid_from_all_player_zones(engine, real_owner, uid)
            if leaving_field:
                engine._reset_card_runtime_state(uid)
            player.hand.append(uid)
            return True

        # For other zones (deck, graveyard, excommunicated, field), the method removes the card from all other zones and adds it to the target zone. If the card is leaving the field, it resets its runtime state. The method returns True if the move was successful and False if it was not possible (e.g., if trying to move a card to an unsupported zone).
        self._remove_uid_from_all_player_zones(engine, real_owner, uid)
        if leaving_field:
            engine._reset_card_runtime_state(uid)

        def _shuffle_graveyard_if_promise_active() -> None:
            promise_state = dict(
                engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False})
                or {"0": False, "1": False}
            )
            if bool(promise_state.get(str(real_owner), False)):
                engine.rng.shuffle(player.graveyard)

        # The following block handles moving the card to the deck. If the card is not already in the deck, it adds it to the bottom of the deck. If the card is already in the deck, it moves it to the bottom. This ensures that the card is properly placed in the deck according to game rules.
        if zone in {"deck_bottom", "bottom_of_deck"}:
            promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
            promise_active = bool(promise_state.get(str(real_owner), False))
            if promise_active:
                if uid not in player.graveyard:
                    player.graveyard.insert(0, uid)
                else:
                    player.graveyard.insert(0, player.graveyard.pop(player.graveyard.index(uid)))
                _shuffle_graveyard_if_promise_active()
                return True
            if uid not in player.deck:
                player.deck.insert(0, uid)
            else:
                player.deck.insert(0, player.deck.pop(player.deck.index(uid)))
            return True

        # For the relicario zone, it treats it the same as the deck, adding the card to the bottom if it's not already there. This allows for effects that move cards to the relicario to function similarly to moving cards to the deck, while still keeping them in a separate zone for game mechanics purposes.
        if zone in {"deck", "relicario"}:
            promise_state = dict(engine.state.flags.get("oltretomba_promise_active", {"0": False, "1": False}) or {"0": False, "1": False})
            promise_active = bool(promise_state.get(str(real_owner), False))
            if promise_active:
                if uid not in player.graveyard:
                    player.graveyard.append(uid)
                _shuffle_graveyard_if_promise_active()
                return True
            if uid not in player.deck:
                player.deck.append(uid)
            return True

        # The following block handles moving the card to the graveyard. If the card is not already in the graveyard, it adds it to the graveyard. This allows for effects that move cards to the graveyard to function properly, ensuring that the card is placed in the correct zone for game mechanics purposes.
        if zone == "graveyard":
            if uid not in player.graveyard:
                player.graveyard.append(uid)
            _shuffle_graveyard_if_promise_active()
            return True

        # The following block handles moving the card to the excommunicated zone. If the card is not already in the excommunicated zone, it adds it to that zone. This allows for effects that move cards to the excommunicated zone to function properly, ensuring that the card is placed in the correct zone for game mechanics purposes.
        if zone == "excommunicated":
            if uid not in player.excommunicated:
                player.excommunicated.append(uid)
            return True

        return False

    # This method retrieves the UID of the card that is currently equipped to a given equipment UID. It checks the blessed tags of the equipment instance for a tag that indicates which card it is equipped to (in the format "equipped_to:target_uid"). If such a tag is found, it returns the target UID. If no such tag is found or if the equipment instance does not exist, it returns None. This method is used to determine which card is currently benefiting from an equipment's effects.
    def _equipment_target_uid(self, engine: GameEngine, equipment_uid: str) -> str | None:
        inst = engine.state.instances.get(equipment_uid)
        if inst is None:
            return None
        for tag in inst.blessed:
            if not isinstance(tag, str) or not tag.startswith("equipped_to:"):
                continue
            target_uid = tag.split(":", 1)[1].strip()
            if target_uid:
                return target_uid
        return None

    # This method clears the equipment link for a given equipment UID. It retrieves the equipment instance and checks its blessed tags for any tag that indicates which card it is equipped to. If such a tag is found, it removes that tag from the equipment's blessed list and also removes the corresponding "equipped_by:equipment_uid" tag from the target card's blessed list. This effectively breaks the link between the equipment and the card it was equipped to. The method returns the target UID that was previously equipped, or None if there was no valid equipment instance or no equipped target.
    def _clear_equipment_link(self, engine: GameEngine, equipment_uid: str) -> str | None:
        equipment = engine.state.instances.get(equipment_uid)
        if equipment is None:
            return None
        target_uid = self._equipment_target_uid(engine, equipment_uid)
        equipment.blessed = [
            tag for tag in equipment.blessed if not (isinstance(tag, str) and tag.startswith("equipped_to:"))
        ]
        if target_uid and target_uid in engine.state.instances:
            target_inst = engine.state.instances[target_uid]
            target_inst.blessed = [
                tag for tag in target_inst.blessed if str(tag) != f"equipped_by:{equipment_uid}"
            ]
        return target_uid

    # This method places a specified equipment UID onto the field for a given player. It first checks if the equipment is already in the player's artifacts zone, and if so, it returns True. If not, it looks for an empty slot in the artifacts zone. If there are no empty slots, it takes the last slot and sends any existing equipment in that slot to the graveyard. It then removes the equipment UID from all other zones of the player and places it in the determined slot in the artifacts zone. The method returns True if the equipment was successfully placed on the field.
    def _place_equipment_on_field(self, engine: GameEngine, owner_idx: int, uid: str) -> bool:
        player = engine.state.players[owner_idx]
        if uid in player.artifacts:
            return True

        slot = next((i for i, slot_uid in enumerate(player.artifacts) if slot_uid is None), None)
        if slot is None:
            slot = len(player.artifacts) - 1
            replaced_uid = player.artifacts[slot]
            if replaced_uid:
                engine.send_to_graveyard(engine.state.instances[replaced_uid].owner, replaced_uid)
        self._remove_uid_from_all_player_zones(engine, owner_idx, uid)
        player.artifacts[slot] = uid
        return True

    # This method summons a token onto the field for a given player. It takes the token name and an optional preferred zone (attack or defense) as parameters. It looks up the token definition in the cards.json file, creates a new card instance for the token, and places it in the appropriate zone based on the preferred zone and available space. If the preferred zone is full, it tries to place the token in the other zone. If there is no space in either zone, it logs a message and returns None. If the token is successfully summoned, it emits relevant events and resolves any "enter field" effects associated with the token.
    def _summon_generated_token(
        self,
        engine: GameEngine,
        owner_idx: int,
        token_name: str,
        preferred_zone: str | None = None,
        preferred_slot_token: str | None = None,
    ) -> str | None:
        token_key = _norm(token_name)
        # runtime_sections/* lives under holywar/effects/runtime_sections;
        # cards.json is in holywar/data.
        cards_path = Path(__file__).resolve().parents[2] / "data" / "cards.json"
        card_defs = load_cards_json(cards_path)

        token_def = next((c for c in card_defs if _norm(c.name) == token_key), None)
        if token_def is None:
            engine.state.log(f"Token non trovato in cards.json: {token_name}.")
            return None

        player = engine.state.players[owner_idx]

        preferred = _norm(preferred_zone or "")
        slot = None
        zone = ""
        requested_slot = str(preferred_slot_token or "").strip().lower()
        parsed_zone, parsed_slot = engine._parse_zone_target(requested_slot)
        if parsed_zone in {"attack", "defense"}:
            requested_slots = player.attack if parsed_zone == "attack" else player.defense
            if 0 <= parsed_slot < len(requested_slots) and requested_slots[parsed_slot] is None:
                zone = parsed_zone
                slot = parsed_slot

        # The following block determines where to place the summoned token based on the preferred zone and available space. If the preferred zone is defense, it first tries to find an open slot in the defense zone, and if none are available, it tries the attack zone. If the preferred zone is attack, it first tries the attack zone, and if none are available, it tries the defense zone. If no preferred zone is specified, it defaults to trying the attack zone first and then the defense zone. If there is no space in either zone, it logs a message indicating that there is no space to summon the token and returns None.
        if slot is None and preferred == "defense":
            slot = engine._first_open(player.defense)
            zone = "defense"
            if slot is None:
                slot = engine._first_open(player.attack)
                zone = "attack"
        elif slot is None and preferred == "attack":
            slot = engine._first_open(player.attack)
            zone = "attack"
            if slot is None:
                slot = engine._first_open(player.defense)
                zone = "defense"
        elif slot is None:
            slot = engine._first_open(player.attack)
            zone = "attack"
            if slot is None:
                slot = engine._first_open(player.defense)
                zone = "defense"
        if slot is None:
            engine.state.log(f"{player.name} non ha spazio per evocare {token_name}.")
            return None

        # To generate a unique UID for the new token instance, the method looks through all existing instances in the game state to find the maximum numeric suffix used in UIDs that start with "c". It then creates a new UID by incrementing this maximum number and formatting it as "cXXXXX" where XXXXX is a zero-padded number. This ensures that the new token instance has a unique identifier that does not conflict with existing instances.
        max_num = 0
        for uid in engine.state.instances:
            if uid.startswith("c"):
                try:
                    max_num = max(max_num, int(uid[1:]))
                except ValueError:
                    pass
        new_uid = f"c{max_num + 1:05d}"

        # The method creates a new card instance for the token using the token definition. It copies the token definition to ensure that the new instance has its own separate definition data. It then adds the new instance to the game state with the generated UID, setting its owner, current faith, and other relevant attributes. Finally, it places the new token in the appropriate zone on the field and emits events related to the token entering the field and being summoned.
        token_copy = CardDefinition.from_dict(token_def.to_dict())
        engine.state.instances[new_uid] = CardInstance(
            uid=new_uid,
            definition=token_copy,
            owner=owner_idx,
            current_faith=token_copy.faith,
        )

        # Depending on the determined zone (attack or defense), the method places the new token in the appropriate slot for that zone. It then emits events to indicate that the token has entered the field and has been summoned, allowing other effects and game mechanics to respond to these events as needed.
        if zone == "attack":
            player.attack[slot] = new_uid
        else:
            player.defense[slot] = new_uid

        inst = engine.state.instances[new_uid]
        inst.exhausted = False

        engine.state.log(f"{player.name} evoca il token {inst.definition.name} in {zone} {slot + 1}.")
        engine._emit_event("on_enter_field", owner_idx, card=new_uid, from_zone="generated")
        engine._emit_event("on_token_summoned", owner_idx, token=new_uid, summoner=owner_idx)

        enter_msg = self.resolve_enter(engine, owner_idx, new_uid)
        if enter_msg:
            engine.state.log(str(enter_msg))

        return new_uid

# pyright: reportGeneralTypeIssues=false
    # This method applies a specified effect to a list of target UIDs. It first normalizes the action specified in the effect and checks if it matches any known effect actions or aliases. Depending on the action, it performs the corresponding operations to apply the effect to the target instances. For example, it can increase faith, increase strength, grant attack barriers, prevent attacks, negate activations, grant extra attacks, equip or unequip cards, and destroy equipment. The method also checks if the effect usage can be applied based on the game state and ensures that any necessary conditions are met before applying the effect.
