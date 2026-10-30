from __future__ import annotations

CARD_NAME = """Campana"""

SCRIPT = {
    "counter_tag": "campana_counter",
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {"action": "add_source_counter", "flag": "campana_counter"}
        }
    ],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 1}},
            "target": {"type": "source_card"},
            "effect": {
                "action": "campana_spend_counters_grant_faith",
                "choice_title": "Campana",
                "choice_prompt": "Quanti Segnalini vuoi rimuovere? Ogni tuo Santo sul campo riceverà +1 Fede per ciascun Segnalino rimosso."
            }
        }
    ],
}


def campana_spend_counters_grant_faith(self, engine, owner_idx, source_uid, targets, effect):
    import json
    inst = engine.state.instances.get(source_uid)
    if inst is None:
        return True
    counter = 0
    counter_tag = ""
    for tag in list(inst.blessed):
        if not isinstance(tag, str) or not tag.startswith("campana_counter:"):
            continue
        counter_tag = tag
        try:
            counter = max(0, int(tag.split(":", 1)[1]))
        except ValueError:
            counter = 0
        break
    if counter <= 0:
        return True

    flags = engine.state.flags
    expected_choice_source = f"{source_uid}:campana_spend_counters_grant_faith"
    choice_source = str(flags.get("_runtime_choice_source", "")).strip()
    choice_ready = bool(flags.get("_runtime_choice_ready"))
    if choice_ready and choice_source == expected_choice_source:
        try:
            amount = int(str(flags.get("_runtime_choice_selected", "0")).strip())
        except ValueError:
            amount = 0
        amount = max(1, min(amount, counter))
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
        if counter_tag:
            inst.blessed.remove(counter_tag)
        inst.blessed.append(f"campana_counter:{counter - amount}")
        for saint_uid in engine.all_saints_on_field(owner_idx):
            saint = engine.state.instances.get(saint_uid)
            if saint is not None:
                saint.current_faith = int(saint.current_faith or 0) + amount
        return True

    values = [str(amount) for amount in range(1, counter + 1)]
    labels = {
        value: (f"Rimuovi {value} Segnalino" if value == "1" else f"Rimuovi {value} Segnalini")
        for value in values
    }
    flags["_runtime_choice_source"] = expected_choice_source
    flags["_runtime_choice_values"] = ";;".join(values)
    flags["_runtime_choice_labels"] = json.dumps(labels, ensure_ascii=False)
    flags["_runtime_choice_owner"] = str(owner_idx)
    flags["_runtime_choice_title"] = str(effect.choice_title or "Campana")
    flags["_runtime_choice_prompt"] = str(
        effect.choice_prompt or "Quanti Segnalini vuoi rimuovere?"
    )
    flags["_runtime_choice_min_targets"] = "1"
    flags["_runtime_choice_max_targets"] = "1"
    flags["_runtime_choice_ready"] = False
    flags["_runtime_resume_same_action"] = True
    flags["_runtime_reveal_card"] = source_uid
    flags["_runtime_waiting_for_reveal"] = True
    return True


ACTION_HANDLERS = {
    'campana_spend_counters_grant_faith': campana_spend_counters_grant_faith,
}
