from __future__ import annotations

CARD_NAME = """Campana"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {"action": "campana_add_counter"}
        }
    ],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "condition": {"source_counter_gte": 1},
            "target": {"type": "source_card"},
            "effect": {
                "action": "campana_spend_counters_grant_faith",
                "choice_title": "Campana",
                "choice_prompt": "Quanti Segnalini vuoi rimuovere? Ogni tuo Santo sul campo riceverà +1 Fede per ciascun Segnalino rimosso."
            }
        }
    ],
}

