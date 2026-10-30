from __future__ import annotations

CARD_NAME = 'Secondo Sigillo: Guerra'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "condition": {"controller_counter_gte": {"key": "sigilli", "amount": 3}},
            "target": {
                "type": "selected_targets",
                "zone": "field",
                "owner": "any",
                "card_filter": {"card_type_in": ["santo", "token"]},
                "min_targets": 2,
                "max_targets": 2,
            },
            "effect": {"action": "destroy_card"},
        },
        {
            "condition": {"not": {"controller_counter_gte": {"key": "sigilli", "amount": 3}}},
            "target": {
                "type": "selected_target",
                "zone": "field",
                "owner": "any",
                "card_filter": {
                    "card_type_in": ["santo", "token"],
                    "strength_gte": 4,
                },
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "destroy_card"},
        },
    ],
}
