from __future__ import annotations

CARD_NAME = "Cenote Sacro"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "guided",
    "triggered_effects": [],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "target": {
                "type": "selected_target",
                "owner": "me",
                "zone": "field",
                "card_filter": {"card_type_in": ["santo", "token"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "destroy_target_and_remove_sin_equal_faith"},
        },
    ],
}


def destroy_target_and_remove_sin_equal_faith(self, engine, owner_idx, source_uid, targets, effect):
    from holywar.effects.runtime import EffectSpec
    for t_uid in targets:
        inst = engine.state.instances.get(t_uid)
        if inst is None or not self._is_uid_on_field(engine, t_uid):
            continue
        faith = max(0, int(inst.current_faith or 0))
        destroyed = []
        def record_destruction(ctx):
            if ctx.payload.get("card") == t_uid:
                destroyed.append(True)
        api = engine.rules_api(owner_idx)
        api.subscribe("on_this_card_destroyed", record_destruction)
        try:
            engine.destroy_any_card(inst.owner, t_uid)
        finally:
            api.unsubscribe("on_this_card_destroyed", record_destruction)
        if destroyed:
            self._apply_effect(engine, owner_idx, source_uid, [], EffectSpec(
                action="remove_sin", amount=faith, target_player="me",
            ))
    return True


ACTION_HANDLERS = {
    'destroy_target_and_remove_sin_equal_faith': destroy_target_and_remove_sin_equal_faith,
}
