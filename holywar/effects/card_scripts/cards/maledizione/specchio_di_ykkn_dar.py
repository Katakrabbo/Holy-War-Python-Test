from __future__ import annotations

CARD_NAME = "Specchio di Ykknødar"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "play_requirements": {
        "all_of": [
            {"my_sin_gte": 51},
            {"opponent_sin_gte": 51},
        ]
    },
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {
                "type": "cards_controlled_by_owner",
                "owner": "any",
                "zones": ["field", "hand", "graveyard"],
            },
            "effect": {"action": "excommunicate_card_no_sin"},
        },
        {
            "target": {
                "type": "cards_controlled_by_owner",
                "owner": "me",
                "zones": ["hand", "relicario", "excommunicated"],
                "card_filter": {"name_equals": "Ykknødar"},
            },
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "target": {
                "type": "selected_target",
                "owner": "me",
                "zones": ["hand", "relicario", "excommunicated"],
                "card_filter": {"name_equals": "Ykknødar"},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "summon_named_card"},
        },
        {"effect": {"action": "move_source_to_zone", "to_zone": "excommunicated"}},
    ],
}
