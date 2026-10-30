from __future__ import annotations

CARD_NAME = "Veggente dell'Apocalisse"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "scripted",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "none",
    "triggered_effects": [],
    "on_play_actions": [],
    "on_enter_actions": [
        {
            "condition": {
                "controller_has_cards": {
                    "owner": "me",
                    "zone": "deck",
                    "card_filter": {"name_contains": "Sigillo"},
                    "min_count": 1,
                }
            },
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "deck",
                "owner": "me",
                "card_filter": {"name_contains": "Sigillo"},
            },
            "effect": {"action": "choose_targets", "min_targets": 0, "max_targets": 1},
        },
        {
            "condition": {
                "all_of": [
                    {
                        "controller_has_cards": {
                            "owner": "me",
                            "zone": "deck",
                            "card_filter": {"name_contains": "Sigillo"},
                            "min_count": 1,
                        }
                    },
                    {"selected_target_exists": True},
                ]
            },
            "target": {
                "type": "selected_target",
                "zone": "deck",
                "owner": "me",
                "card_filter": {"name_contains": "Sigillo"},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"selected_target_exists": True},
            "target": {"type": "source_card"},
            "effect": {"action": "shuffle_deck", "target_player": "me"},
        },
    ],
    "on_activate_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "choose_option",
                "choice_title": "Veggente dell'Apocalisse",
                "choice_prompt": "Scegli la modalità di attivazione.",
                "choice_options": [
                    {
                        "value": "add",
                        "label": "Aggiungi 1 Segnalino Sigillo",
                        "condition": {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
                    },
                    {
                        "value": "draw",
                        "label": "Rimuovi 3 Segnalini e pesca 1 carta",
                        "condition": {
                            "all_of": [
                                {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
                                {"controller_counter_gte": {"key": "sigilli", "amount": 3}},
                            ]
                        },
                    },
                ],
            },
        },
        {
            "condition": {
                "all_of": [
                    {"selected_option_in": ["add"]},
                    {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
                ]
            },
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"script_provides_player_counter": True},
                "max_targets": 1,
            },
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 1},
        },
        {
            "condition": {
                "all_of": [
                    {"selected_option_in": ["draw"]},
                    {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
                    {"controller_counter_gte": {"key": "sigilli", "amount": 3}},
                ]
            },
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"script_provides_player_counter": True},
                "max_targets": 1,
            },
            "effect": {"action": "remove_player_counter", "flag": "sigilli", "amount": 3},
        },
        {
            "condition": {
                "all_of": [
                    {"selected_option_in": ["draw"]},
                    {"controller_has_building_matching": {"card_filter": {"script_provides_player_counter": True}}},
                    {"controller_counter_gte": {"key": "sigilli", "amount": 3}},
                ]
            },
            "target": {"type": "source_card"},
            "effect": {"action": "draw_cards", "amount": 1, "target_player": "me"},
        },
    ],
}
