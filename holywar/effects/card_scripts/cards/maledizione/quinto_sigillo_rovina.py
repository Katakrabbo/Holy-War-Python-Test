from __future__ import annotations

CARD_NAME = "Quinto Sigillo: Rovina"

TARGET_FILTER = {"card_type_in": ["artefatto", "edificio"]}

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "condition": {"controller_counter_gte": {"key": "sigilli", "amount": 6}},
            "target": {
                "type": "selected_targets",
                "zone": "field",
                "owner": "opponent",
                "card_filter": TARGET_FILTER,
                "min_targets": 1,
                "max_targets": 2,
            },
            "effect": {"action": "destroy_card"},
        },
        {
            "condition": {"not": {"controller_counter_gte": {"key": "sigilli", "amount": 6}}},
            "target": {
                "type": "selected_target",
                "zone": "field",
                "owner": "opponent",
                "card_filter": TARGET_FILTER,
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "destroy_card"},
        },
    ],
}

