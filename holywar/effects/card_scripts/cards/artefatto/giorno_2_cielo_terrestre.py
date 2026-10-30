from __future__ import annotations

CARD_NAME = 'Giorno 2: Cielo Terrestre'

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "triggered_effects": [],
    "on_play_actions": [],
}


def reduce_combat_sin(runtime, engine, amount, *, player_idx):
    if any(uid and engine.state.instances[uid].effect_name == CARD_NAME
           for uid in engine.state.players[player_idx].artifacts):
        return max(0, int(amount)) // 2
    return amount


RULE_HOOKS = {"combat_sin_gain": reduce_combat_sin}
