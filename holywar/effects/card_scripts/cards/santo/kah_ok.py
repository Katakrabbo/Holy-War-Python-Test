from __future__ import annotations

CARD_NAME = """Kah-ok"""

SCRIPT = {
    "on_play_mode": "noop",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"name_contains": "Kah-ok"},
            },
            "effect": {"action": "kah_ok_tick"}
        }
    ],
    "on_play_actions": [],
}


def kah_ok_tick(self, engine, owner_idx, source_uid, targets, effect):
    inst = engine.state.instances[source_uid]
    inst.current_faith = (inst.current_faith or 0) + 2
    if (inst.current_faith or 0) >= 10:
        gained = max(0, inst.current_faith or 0)
        engine.destroy_saint_by_uid(owner_idx, source_uid, cause="effect")
        engine.gain_sin(owner_idx, gained)
        engine.state.log(
            f"Kah-ok raggiunge 10 Fede e si distrugge: {engine.state.players[owner_idx].name} +{gained} Peccato."
        )
    return True


ACTION_HANDLERS = {
    'kah_ok_tick': kah_ok_tick,
}
