from __future__ import annotations

CARD_NAME = "Pietra Focaia"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_this_card_attacks",
                "condition": {"payload_target_slot_is_set": True},
            },
            "target": {
                "type": "source_card",
            },
            "effect": {
                "action": "choose_artifact_from_relicario_then_shuffle",
                "target_player": "me",
            },
        },
    ],
    "on_play_actions": [],
}


def choose_artifact_from_relicario_then_shuffle(self, engine, owner_idx, source_uid, targets, effect):
    from holywar.effects.runtime import _norm
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
        for key in ("_runtime_choice_source","_runtime_choice_ready","_runtime_choice_selected","_runtime_choice_candidates","_runtime_choice_owner","_runtime_choice_title","_runtime_choice_prompt","_runtime_choice_min_targets","_runtime_choice_max_targets"):
            flags.pop(key, None)
        return True
    candidates = [uid for uid in player.deck if uid in engine.state.instances and _norm(engine.state.instances[uid].definition.card_type) == _norm("artefatto")]
    if not candidates:
        engine.rng.shuffle(player.deck)
        return True
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
    return True


ACTION_HANDLERS = {
    'choose_artifact_from_relicario_then_shuffle': choose_artifact_from_relicario_then_shuffle,
}
