from __future__ import annotations

CARD_NAME = "Biblioteca Apostolica"

SEARCH_FILTER = {
    "card_type_in": ["benedizione", "maledizione"],
}

SCRIPT = {
    "counter_tag": "campana_counter",
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "play_targeting": "none",
    "activate_targeting": "guided",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_card_played",
                "frequency": "each_time",
                "condition": {"event_card_type_in": ["benedizione", "maledizione"]},
            },
            "target": {"type": "source_card"},
            "effect": {"action": "add_source_counter", "flag": "campana_counter"},
        },
    ],
    "on_play_actions": [
        {"effect": {"action": "draw_cards", "amount": 0, "target_player": "me"}},
    ],
    "on_activate_actions": [
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 3}},
            "target": {
                "type": "selected_target",
                "zone": "deck",
                "owner": "me",
                "card_filter": SEARCH_FILTER,
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 3}},
            "target": {"type": "source_card"},
            "effect": {"action": "remove_source_counter", "flag": "campana_counter", "amount": 3},
        },
        {
            "condition": {"source_counter_gte": {"key": "campana_counter", "amount": 3}},
            "target": {"type": "source_card"},
            "effect": {"action": "shuffle_deck", "target_player": "me"},
        },
    ],
}
