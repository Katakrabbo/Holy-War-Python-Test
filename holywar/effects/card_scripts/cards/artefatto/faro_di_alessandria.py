from __future__ import annotations

CARD_NAME = "Faro di Alessandria"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_card_drawn",
                "frequency": "each_turn",
                "condition": {"event_card_owner": "opponent"},
            },
            "target": {"type": "source_card"},
            "effect": {
                "action": "optional_redraw_event_card",
                "choice_title": "Faro di Alessandria",
                "choice_prompt": "L'avversario ha pescato una carta. Vuoi rimischiarla nel reliquiario e fargli pescare di nuovo?",
            },
        },
    ],
    "on_play_actions": [],
}
