from __future__ import annotations

CARD_NAME = """Trombe del Giudizio"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "cards_controlled_by_owner", "zone": "field", "owner": "me"},
            "effect": {"action": "trombe_del_giudizio_tick"}
        }
    ],
    "on_play_actions": [],
}


def trombe_del_giudizio_tick(self, engine, owner_idx, source_uid, targets, effect):
    b_uid = engine.state.players[owner_idx].building
    if b_uid is None:
        return True
    if not bool(self.get_script(engine.state.instances[b_uid].effect_name) and self.get_script(engine.state.instances[b_uid].effect_name).provides_player_counter):
        return True
    seals = self.get_player_counter(engine, owner_idx, "sigilli")
    if seals >= 7:
        amount = 10
    elif seals >= 5:
        amount = 6
    elif seals >= 3:
        amount = 3
    else:
        amount = 0
    if amount > 0:
        engine.gain_sin(1 - owner_idx, amount)
    return True


ACTION_HANDLERS = {
    'trombe_del_giudizio_tick': trombe_del_giudizio_tick,
}
