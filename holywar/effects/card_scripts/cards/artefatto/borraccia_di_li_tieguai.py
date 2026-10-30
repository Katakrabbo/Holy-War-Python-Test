from __future__ import annotations

CARD_NAME = "Borraccia di Li Tieguai"

BAXIAN_DESTROYED = {
    "all_of": [
        {"event_card_owner": "me"},
        {"event_card_type_in": ["santo", "token"]},
        {"event_card_name_contains": "ba xian"},
        {"payload_from_zone_in": ["attack", "defense", "field"]},
    ]
}

SCRIPT = {
    "counter_tag": "campana_counter",
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "none",
    "triggered_effects": [
        {
            "trigger": {"event": "on_card_sent_to_graveyard", "frequency": "each_time", "condition": BAXIAN_DESTROYED},
            "target": {"type": "source_card"},
            "effect": {"action": "add_source_counter", "flag": "campana_counter"},
        }
    ],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "effect": {
                "action": "choose_option",
                "choice_title": "Borraccia",
                "choice_prompt": "Scegli l'effetto.",
                "choice_options": [
                    {
                        "label": "Rimuovi 2: aggiungi alla mano",
                        "value": "hand",
                        "condition": {
                            "all_of": [
                                {"source_counter_gte": {"key": "campana_counter", "amount": 2}},
                                {
                                    "controller_has_cards": {
                                        "zone": "graveyard",
                                        "owner": "me",
                                        "card_filter": {"name_contains": "ba xian", "card_type_in": ["santo", "token"]},
                                        "min_count": 1,
                                    }
                                },
                            ]
                        },
                    },
                    {
                        "label": "Rimuovi 5: evoca",
                        "value": "summon",
                        "condition": {
                            "all_of": [
                                {"source_counter_gte": {"key": "campana_counter", "amount": 5}},
                                {
                                    "controller_has_cards": {
                                        "zone": "graveyard",
                                        "owner": "me",
                                        "card_filter": {"name_contains": "ba xian", "card_type_in": ["santo", "token"]},
                                        "min_count": 1,
                                    }
                                },
                            ]
                        },
                    },
                ],
            }
        },
        {
            "condition": {"all_of": [{"selected_option_in": ["hand"]}, {"source_counter_gte": {"key": "campana_counter", "amount": 2}}]},
            "target": {"type": "source_card"},
            "effect": {"action": "remove_source_counter", "flag": "campana_counter", "amount": 2},
        },
        {
            "condition": {"all_of": [{"selected_option_in": ["hand"]}, {"source_counter_gte": {"key": "campana_counter", "amount": 2}}]},
            "target": {"type": "selected_target", "zone": "graveyard", "owner": "me", "card_filter": {"name_contains": "ba xian", "card_type_in": ["santo", "token"]}, "min_targets": 1, "max_targets": 1},
            "effect": {"action": "move_to_hand"},
        },
        {
            "condition": {"all_of": [{"selected_option_in": ["summon"]}, {"source_counter_gte": {"key": "campana_counter", "amount": 5}}]},
            "target": {"type": "source_card"},
            "effect": {"action": "remove_source_counter", "flag": "campana_counter", "amount": 5},
        },
        {
            "condition": {"all_of": [{"selected_option_in": ["summon"]}, {"source_counter_gte": {"key": "campana_counter", "amount": 5}}]},
            "target": {"type": "selected_target", "zone": "graveyard", "owner": "me", "card_filter": {"name_contains": "ba xian", "card_type_in": ["santo", "token"]}, "min_targets": 1, "max_targets": 1},
            "effect": {"action": "summon_target_to_field"},
        },
    ],
}
