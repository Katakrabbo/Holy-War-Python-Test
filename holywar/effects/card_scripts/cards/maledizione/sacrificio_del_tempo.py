from __future__ import annotations

CARD_NAME = 'Sacrificio del Tempo'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "can_play_from_hand": False,
    "play_targeting": "none",
    "play_requirements": {
        "auto_activate_when_discarded_from_hand_by_effect": True,
    },
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "discard_hand_then_pressure_opponent",
                "amount": 1,
                "target_player": "opponent",
                "choice_title": "Sacrificio del Tempo",
                "choice_prompt": "Seleziona i bersagli avversari da inviare al cimitero.",
            },
        },
    ],
}


def discard_hand_then_pressure_opponent(self, engine, owner_idx, source_uid, targets, effect):
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
                self._shuffle_merged_zone_if_active(engine, owner_idx)
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
                        self._shuffle_merged_zone_if_active(engine, target_idx)
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
            self._shuffle_merged_zone_if_active(engine, target_idx)
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


ACTION_HANDLERS = {
    'discard_hand_then_pressure_opponent': discard_hand_then_pressure_opponent,
}
