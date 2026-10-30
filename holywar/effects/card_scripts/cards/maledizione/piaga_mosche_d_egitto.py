from __future__ import annotations

CARD_NAME = "Piaga: Mosche d'Egitto"

SCRIPT = {
    "activate_once_per_turn": True,
    "play_requirements": {"play_once_per_turn_by_name": True, "play_usage_state_key": "piaga_effect_used_turn"},
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
                "owner": "opponent",
                "card_filter": {"card_type_in": ["artefatto", "edificio"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "send_to_graveyard"},
        },
        {
            "target": {
                "type": "selected_target",
                "zone": "deck",
                "owner": "me",
                "card_filter": {"name_contains": "Piaga"},
                "min_targets": 0,
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "shuffle_deck", "target_player": "me"},
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "inflict_sin", "amount": 2, "target_player": "me"},
        },
    ],
}
