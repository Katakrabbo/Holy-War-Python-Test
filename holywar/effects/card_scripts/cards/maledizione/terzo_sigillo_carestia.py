from __future__ import annotations

CARD_NAME = 'Terzo Sigillo: Carestia'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {"action": "set_next_turn_draw_override", "amount": 1, "target_player": "opponent"},
        },
        {
            "condition": {"controller_counter_gte": {"key": "sigilli", "amount": 4}},
            "target": {
                "type": "all_saints_on_field",
                "owner": "opponent",
                "card_filter": {"card_type_in": ["santo", "token"]},
            },
            "effect": {"action": "decrease_faith", "amount": 2},
        },
    ],
}
