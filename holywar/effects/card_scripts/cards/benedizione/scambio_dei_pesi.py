from __future__ import annotations

CARD_NAME = "Scambio dei Pesi"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {
                "type": "selected_target",
                "zone": "field",
                "owner": "me",
                "card_filter": {"card_type_in": ["santo", "token"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "increase_faith", "amount": 2},
        },
        {
            "target": {"type": "selected_target"},
            "effect": {"action": "increase_strength", "amount": 2},
        },
        {
            "target": {
                "type": "selected_target",
                "zone": "field",
                "owner": "opponent",
                "card_filter": {"card_type_in": ["santo", "token"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "decrease_faith", "amount": 2},
        },
        {
            "target": {"type": "selected_target"},
            "effect": {"action": "decrease_strength", "amount": 2},
        },
    ],
}
