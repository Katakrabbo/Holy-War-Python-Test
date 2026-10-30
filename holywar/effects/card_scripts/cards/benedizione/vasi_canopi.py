from __future__ import annotations

CARD_NAME = "Vasi Canopi"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [
        {
            "trigger": {"event": "on_saint_defeated_in_battle", "frequency": "each_turn"},
            "target": {"type": "event_card"},
            "effect": {"action": "revive_equipped_saint_without_effects"},
        },
    ],
    "on_play_actions": [
        {
            "target": {
                "type": "selected_target",
                "owner": "me",
                "zone": "field",
                "card_filter": {"card_type_in": ["santo", "token"]},
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {"action": "equip_card"},
        }
    ],
}


def revive_equipped_saint_without_effects(self, engine, owner_idx, source_uid, targets, effect):
    from holywar.effects.runtime import EffectSpec
    equipped_uid = self._equipment_target_uid(engine, source_uid)
    event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
    source_inst = engine.state.instances.get(source_uid)
    if not equipped_uid or equipped_uid != event_uid or source_inst is None:
        return True
    inst = engine.state.instances.get(equipped_uid)
    if inst is None or equipped_uid not in engine.state.players[inst.owner].graveyard:
        return True
    engine.destroy_any_card(source_inst.owner, source_uid)
    inst.cursed.append("silenced")
    self._apply_effect(engine, owner_idx, source_uid, [equipped_uid], EffectSpec(action="summon_target_to_field"))
    if not self._is_uid_on_field(engine, equipped_uid):
        inst.cursed.remove("silenced")
    return True


ACTION_HANDLERS = {
    'revive_equipped_saint_without_effects': revive_equipped_saint_without_effects,
}
