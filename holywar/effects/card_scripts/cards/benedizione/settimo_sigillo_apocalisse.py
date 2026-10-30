from __future__ import annotations

CARD_NAME = 'Settimo Sigillo: Apocalisse'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "play_requirements": {
        "all_of": [
            {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
            {"controller_counter_gte": {"key": "sigilli", "amount": 7}},
        ]
    },
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "opponent",
                "card_filter": {"card_type_in": ["santo", "token"]},
            },
            "effect": {"action": "destroy_card"},
        },
    ],
}
