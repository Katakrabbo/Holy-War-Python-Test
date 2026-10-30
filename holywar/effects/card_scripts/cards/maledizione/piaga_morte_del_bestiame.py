from __future__ import annotations

CARD_NAME = "Piaga: Morte del Bestiame"

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
                "owner": "any",
                "card_filter": {"card_type_in": ["santo"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "send_to_graveyard"},
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "inflict_sin", "amount": 3, "target_player": "opponent"},
        },
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "optional_recover_matching_then_shuffle",
                "from_zone": "graveyard",
                "to_zone": "hand",
                "card_name": "Piaga",
                "amount": 1,
                "shuffle_after": False,
            },
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "inflict_sin", "amount": 2, "target_player": "me"},
        },
    ],
}
