from __future__ import annotations

CARD_NAME = "Sesto Sigillo: Ritorno"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "condition": {"controller_counter_gte": {"key": "sigilli", "amount": 6}},
            "target": {
                "type": "selected_target",
                "zone": "graveyard",
                "owner": "me",
                "card_filter": {
                    "card_type_in": ["santo", "benedizione", "maledizione", "artefatto", "edificio"],
                    "exclude_event_card": True,
                },
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"not": {"controller_counter_gte": {"key": "sigilli", "amount": 6}}},
            "target": {
                "type": "selected_target",
                "zone": "graveyard",
                "owner": "me",
                "card_filter": {
                    "card_type_in": ["santo"],
                    "exclude_event_card": True,
                },
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
    ],
}
