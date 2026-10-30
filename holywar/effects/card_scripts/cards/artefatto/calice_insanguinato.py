from __future__ import annotations

CARD_NAME = """Calice Insanguinato"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_my_turn_start", "frequency": "each_turn"},
            "target": {"type": "cards_controlled_by_owner", "zone": "field", "owner": "me"},
            "effect": {"action": "pay_sin_or_destroy_self", "amount": 5}
        },
        {
            "trigger": {"event": "on_my_turn_end", "frequency": "each_turn"},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"name_equals": "Spirito Vacuo", "card_type_in": ["token"]},
            },
            "effect": {"action": "calice_endturn"}
        }
    ],
    "on_play_actions": [],
}


def calice_endturn(self, engine, owner_idx, source_uid, targets, effect):
    destroyed = 0
    for s_uid in list(targets):
        if s_uid not in engine.state.instances:
            continue
        if self.is_immune_to_action(
            engine.state.instances[s_uid].effect_name,
            "calice_endturn_destroy",
        ):
            continue
        engine.destroy_saint_by_uid(owner_idx, s_uid, cause="effect")
        destroyed += 1
    if destroyed > 0:
        engine.gain_sin(1 - owner_idx, destroyed * 5)
    return True


ACTION_HANDLERS = {
    'calice_endturn': calice_endturn,
}
