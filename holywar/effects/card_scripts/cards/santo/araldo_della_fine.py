from __future__ import annotations

CARD_NAME = """Araldo della Fine"""

SCRIPT = {
    "on_play_mode": "noop",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_this_card_destroyed", "frequency": "each_turn"},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"script_provides_player_counter": True},
            },
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 3},
        }
    ],
    "on_play_actions": [],
}
