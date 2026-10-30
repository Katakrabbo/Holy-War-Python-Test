from __future__ import annotations

CARD_NAME = """Av'drna"""

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
            "target": {"type": "cards_controlled_by_owner", "zone": "field", "owner": "me"},
            "effect": {"action": "av_drna_on_opponent_draw"}
        }
    ],
    "on_play_actions": [],
}


def av_drna_on_opponent_draw(self, engine, owner_idx, source_uid, targets, effect):
    inst = engine.state.instances[source_uid]
    inst.current_faith = max(0, (inst.current_faith or 0) - 1)
    engine.reduce_sin(owner_idx, 2)
    if (inst.current_faith or 0) <= 0:
        engine.send_to_graveyard(owner_idx, source_uid)
    return True


ACTION_HANDLERS = {
    'av_drna_on_opponent_draw': av_drna_on_opponent_draw,
}
