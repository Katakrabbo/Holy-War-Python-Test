from __future__ import annotations

CARD_NAME = 'Primo Sigillo'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "condition": {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
            "target": {"type": "source_card"},
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 2},
        },
        {
            "condition": {"not": {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}}},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "deck",
                "owner": "me",
                "card_filter": {
                    "name_equals": "Altare dei Sette Sigilli",
                    "card_type_in": ["edificio"],
                },
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"not": {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}}},
            "target": {"type": "source_card"},
            "effect": {"action": "shuffle_deck", "target_player": "me"},
        },
    ],
}
