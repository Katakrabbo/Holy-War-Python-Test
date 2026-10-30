from __future__ import annotations

CARD_NAME = 'Piaga Ignota'

SCRIPT = {
    "activate_once_per_turn": True,
    "play_requirements": {"play_once_per_turn_by_name": True, "play_usage_state_key": "piaga_effect_used_turn"},
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "summon_generated_token_in_each_free_saint_slot",
                "card_name": "Token Piaga",
                "owner": "opponent",
            },
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "inflict_sin", "amount": 1, "target_player": "me"},
        },
    ],
}
