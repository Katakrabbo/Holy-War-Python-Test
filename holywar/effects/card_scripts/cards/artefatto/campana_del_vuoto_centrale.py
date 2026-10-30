from __future__ import annotations

CARD_NAME = "Campana del Vuoto Centrale"

SCRIPT = {
    "counter_tag": "campana_counter",
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "none",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {"action": "add_source_counter", "flag": "campana_counter"},
        }
    ],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 2}},
            "target": {"type": "source_card"},
            "effect": {"action": "remove_source_counter", "flag": "campana_counter", "amount": 2},
        },
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 2}},
            "effect": {"action": "draw_cards", "amount": 1, "target_player": "me"},
        },
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 2}},
            "effect": {"action": "mill_cards", "amount": 1, "target_player": "opponent"},
        },
    ],
}
