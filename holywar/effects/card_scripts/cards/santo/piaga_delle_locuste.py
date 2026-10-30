from __future__ import annotations

CARD_NAME = "Piaga delle Locuste"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_this_card_attacks",
                "frequency": "each_turn",
                "condition": {
                    "payload_target_slot_is_set": True
                },
            },
            "target": {"type": "source_card"},
            "effect": {
                "action": "optional_recover_matching_then_shuffle",
                "from_zone": "graveyard",
                "to_zone": "hand",
                "card_name": "Piaga",
                "amount": 1,
                "shuffle_after": False,
                "usage_limit_per_turn": 1,
            },
        }
    ],
    "on_play_actions": [],
}
