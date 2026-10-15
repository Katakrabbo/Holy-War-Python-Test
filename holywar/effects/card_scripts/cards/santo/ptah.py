from __future__ import annotations

CARD_NAME = 'Ptah'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "triggered_effects": [
        {
            "trigger": {"event": "on_main_phase_start", "frequency": "each_turn"},
            "condition": {
                "all_of": [
                    {"turn_scope": "my"},
                    {"controller_drawn_cards_this_turn_gte": 1},
                ]
            },
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "hand",
                "owner": "me",
                "card_filter": {"drawn_this_turn_only": True},
            },
            "effect": {
                "action": "choose_up_to_n_from_hand_to_relicario_then_draw_same",
                "amount": 1,
                "target_player": "me",
                "choice_title": "Ptah",
                "choice_prompt": "Scegli una delle carte pescate in questo turno da rimettere nel reliquiario, oppure annulla.",
            },
        },
    ],
    "on_play_actions": [
        {"effect": {"action": "draw_cards", "amount": 0, "target_player": "me"}},
    ],
}
