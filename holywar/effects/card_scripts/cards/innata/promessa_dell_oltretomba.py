from __future__ import annotations

CARD_NAME = """Promessa dell'oltretomba"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {"action": "activate_oltretomba_promise"},
        }
    ],
}


def activate_oltretomba_promise(self, engine, owner_idx, source_uid, targets, effect):
    flags = engine.state.flags
    promise_state = dict(flags.get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
    promise_state[str(owner_idx)] = True
    flags["deck_graveyard_merge_active"] = promise_state

    player = engine.state.players[owner_idx]
    for uid in list(player.deck):
        if uid not in player.graveyard:
            player.graveyard.append(uid)
    player.deck = []
    engine.rng.shuffle(player.graveyard)
    engine.state.log("Promessa dell'oltretomba attiva: reliquiario e cimitero diventano la stessa zona.")
    return


ACTION_HANDLERS = {
    'activate_oltretomba_promise': activate_oltretomba_promise,
}


def restore_saved_state(runtime, engine, value):
    legacy = engine.state.flags.pop("oltretomba_promise_active", None)
    if isinstance(legacy, dict):
        active = engine.state.flags.setdefault("deck_graveyard_merge_active", {})
        for owner, enabled in legacy.items():
            active[owner] = bool(active.get(owner) or enabled)
    return value


RULE_HOOKS = {"state_loaded": restore_saved_state}
