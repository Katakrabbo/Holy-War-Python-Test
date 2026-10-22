from __future__ import annotations

CARD_NAME = """Calice Insanguinato"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "cards_controlled_by_owner", "zone": "field", "owner": "me"},
            "effect": {"action": "pay_sin_or_destroy_self", "amount": 5}
        },
        {
            "trigger": {"event": "on_my_turn_end", "frequency": "each_turn"},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"name_equals": "Spirito Vacuo", "card_type_in": ["token"]},
            },
            "effect": {"action": "calice_endturn"}
        }
    ],
    "on_play_actions": [],
}

