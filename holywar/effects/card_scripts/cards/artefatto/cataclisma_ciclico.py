from __future__ import annotations

CARD_NAME = """Cataclisma Ciclico"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "cards_controlled_by_owner", "zone": "field", "owner": "me"},
            "effect": {"action": "cataclisma_ciclico"}
        }
    ],
    "on_play_actions": [],
}


def cataclisma_ciclico(self, engine, owner_idx, source_uid, targets, effect):
    flags = engine.state.flags
    expected_choice_source = f"{source_uid}:cataclisma_ciclico"
    own_saints = engine.all_saints_on_field(owner_idx)
    opp_idx = 1 - owner_idx
    opp_saints = engine.all_saints_on_field(opp_idx)
    candidates = list(dict.fromkeys(own_saints + opp_saints))
    if not candidates:
        # The printed effect destroys Cataclisma itself when there
        # are no Saints on the field.
        engine.destroy_any_card(owner_idx, source_uid)
        return True

    choice_source = str(flags.get("_runtime_choice_source", "")).strip()
    choice_ready = bool(flags.get("_runtime_choice_ready"))
    if choice_ready and choice_source == expected_choice_source:
        selected_uid = str(flags.get("_runtime_choice_selected", "")).strip().split(",", 1)[0]
        target_uid = selected_uid if selected_uid in candidates else ""
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
        if not target_uid:
            return True
    else:
        flags["_runtime_choice_source"] = expected_choice_source
        flags["_runtime_choice_candidates"] = ";;".join(candidates)
        flags["_runtime_choice_owner"] = str(owner_idx)
        flags["_runtime_choice_title"] = "Cataclisma Ciclico"
        flags["_runtime_choice_prompt"] = "Scegli il Santo che Cataclisma Ciclico deve distruggere."
        flags["_runtime_choice_min_targets"] = "1"
        flags["_runtime_choice_max_targets"] = "1"
        flags["_runtime_choice_ready"] = False
        flags["_runtime_reveal_card"] = source_uid
        flags["_runtime_waiting_for_reveal"] = True
        flags["_runtime_resume_source"] = source_uid
        flags["_runtime_resume_owner"] = str(owner_idx)
        flags["_runtime_pending_mode"] = "trigger_action"
        flags["_runtime_trigger_action"] = "cataclisma_ciclico"
        flags["_runtime_trigger_event_name"] = str(flags.get("_runtime_event_name", "on_my_turn_start"))
        return True

    target_owner = engine.state.instances[target_uid].owner
    target_name = engine.state.instances[target_uid].definition.name
    engine.destroy_saint_by_uid(target_owner, target_uid, cause="effect")
    if target_owner == owner_idx:
        engine.gain_sin(opp_idx, 2)
        engine.state.log(
            f"Cataclisma Ciclico distrugge {target_name}: +2 Peccato a {engine.state.players[opp_idx].name}."
        )
    else:
        engine.reduce_sin(owner_idx, 1)
        engine.state.log(
            f"Cataclisma Ciclico distrugge {target_name}: {engine.state.players[owner_idx].name} perde 1 Peccato."
        )
    return True


ACTION_HANDLERS = {
    'cataclisma_ciclico': cataclisma_ciclico,
}
