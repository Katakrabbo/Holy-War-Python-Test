from __future__ import annotations

CARD_NAME = 'Offerta ai Sigilli'

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
            "effect": {"action": "destroy_card"},
        },
        {
            "condition": {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
            "target": {"type": "source_card"},
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 3},
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "draw_cards", "amount": 1, "target_player": "me"},
        },
    ],
}
