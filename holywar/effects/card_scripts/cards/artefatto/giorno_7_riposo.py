from __future__ import annotations

CARD_NAME = 'Giorno 7: Riposo'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_card_played",
                "frequency": "each_time",
                "condition": {"event_card_name_contains": "Giorno"},
            },
            "target": {"type": "source_card"},
            "effect": {"action": "remove_sin", "amount": 1, "target_player": "me"},
        },
        {
            "trigger": {
                "event": "on_card_played",
                "frequency": "each_time",
                "condition": {"event_card_name_contains": "Giorno"},
            },
            "target": {"type": "source_card"},
            "effect": {"action": "inflict_sin", "amount": 2, "target_player": "opponent"},
        }
    ],
    "on_play_actions": [],
}
