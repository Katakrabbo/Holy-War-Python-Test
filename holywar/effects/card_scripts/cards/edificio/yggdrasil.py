from __future__ import annotations

CARD_NAME = "Yggdrasil"

SEARCH_FILTER = {
    "card_type_in": ["santo"],
    "name_in": ["Thor", "Odino", "Loki"],
}

ARTIFACT_FILTER = {
    "card_type_in": ["artefatto"],
}

SAINT_FILTER = {
    "card_type_in": ["santo"],
}

SCRIPT = {
    "on_play_mode": "noop",
    "on_enter_mode": "scripted",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "none",
    "triggered_effects": [],
    "on_play_actions": [],
    "on_enter_actions": [
        {
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "deck",
                "owner": "me",
                "card_filter": SEARCH_FILTER,
            },
            "effect": {
                "action": "choose_targets",
                "min_targets": 0,
                "max_targets": 1,
            },
        },
        {
            "target": {
                "type": "selected_target",
                "zone": "deck",
                "owner": "me",
                "card_filter": SEARCH_FILTER,
                "min_targets": 0,
                "max_targets": 1,
            },
            "effect": {
                "action": "reveal_selected_target",
            },
        },
        {
            "target": {
                "type": "selected_target",
                "zone": "deck",
                "owner": "me",
                "card_filter": SEARCH_FILTER,
                "min_targets": 0,
                "max_targets": 1,
            },
            "effect": {
                "action": "move_to_hand",
            },
        },
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "shuffle_deck",
                "target_player": "me",
            },
        },
    ],
    "on_activate_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "choose_option",
                "choice_title": "Yggdrasil - Modalità",
                "choice_prompt": "Scegli uno dei seguenti effetti.",
                "choice_options": [
                    {
                        "value": "buff",
                        "label": "Un tuo Santo riceve +2 Forza e +2 Fede",
                        "condition": {"my_saints_gte": 1},
                    },
                    {
                        "value": "artifact",
                        "label": "Riprendi un Artefatto dal cimitero",
                        "condition": {
                            "controller_has_cards": {
                                "zone": "graveyard",
                                "owner": "me",
                                "card_filter": {"card_type_in": ["artefatto"]},
                            }
                        },
                    },
                    {
                        "value": "draw",
                        "label": "Se controlli almeno 3 Santi con nomi diversi, pesca 1",
                        "condition": {"controller_has_distinct_saints_gte": 3},
                    },
                    {
                        "value": "warcry",
                        "label": "Se controlli Thor e Odino, ogni tuo Santo riceve +1 Forza",
                        "condition": {
                            "all_of": [
                                {"controller_has_saint_with_name": "Thor"},
                                {"controller_has_saint_with_name": "Odino"},
                            ]
                        },
                    },
                ],
            },
        },
        {
            "condition": {"selected_option_in": ["buff"]},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": SAINT_FILTER,
            },
            "effect": {
                "action": "choose_targets",
                "min_targets": 1,
                "max_targets": 1,
            },
        },
        {
            "condition": {"selected_option_in": ["buff"]},
            "target": {"type": "selected_target"},
            "effect": {"action": "increase_faith", "amount": 2},
        },
        {
            "condition": {"selected_option_in": ["buff"]},
            "target": {"type": "selected_target"},
            "effect": {"action": "increase_strength", "amount": 2},
        },
        {
            "condition": {"selected_option_in": ["artifact"]},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "graveyard",
                "owner": "me",
                "card_filter": ARTIFACT_FILTER,
            },
            "effect": {
                "action": "choose_targets",
                "min_targets": 1,
                "max_targets": 1,
            },
        },
        {
            "condition": {"selected_option_in": ["artifact"]},
            "target": {"type": "selected_target"},
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"selected_option_in": ["draw"]},
            "target": {"type": "source_card"},
            "effect": {"action": "draw_cards", "amount": 1, "target_player": "me"},
        },
        {
            "condition": {"selected_option_in": ["warcry"]},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": SAINT_FILTER,
            },
            "effect": {"action": "increase_strength", "amount": 1},
        },
    ],
}