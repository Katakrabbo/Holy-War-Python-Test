from __future__ import annotations

CARD_NAME = "Pietra Levigata"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "activate_once_per_turn": True,
    "play_targeting": "none",
    "activate_targeting": "guided",
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_saint_defeated_or_destroyed",
            },
            "target": {
                "type": "source_card",
            },
            "effect": {
                "action": "destroy_source_if_linked_to_event_card",
            },
        },
    ],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "target": {
                "type": "selected_target",
                "owner": "opponent",
                "zone": "field",
                "card_filter": {
                    "card_type_in": ["santo", "token"],
                },
                "min_targets": 1,
                "max_targets": 1,
            },
            "effect": {
                "action": "absorb_target_stats_and_link",
            },
        },
    ],
}


def absorb_target_stats_and_link(self, engine, owner_idx, source_uid, targets, effect):
    source_inst = engine.state.instances.get(source_uid)
    if source_inst is None:
        return True
    for t_uid in targets:
        target_inst = engine.state.instances.get(t_uid)
        if target_inst is None:
            continue
        gain_faith = max(0, int(target_inst.current_faith or 0))
        gain_strength = max(0, int(engine.get_effective_strength(t_uid)))
        source_inst.current_faith = max(0, int(source_inst.current_faith or 0) + gain_faith)
        if gain_strength > 0:
            source_inst.blessed.append(f"buff_str:{gain_strength}")
        link_tag = f"levigata_link:{t_uid}"
        if link_tag not in source_inst.blessed:
            source_inst.blessed.append(link_tag)
        break
    return True


def destroy_source_if_linked_to_event_card(self, engine, owner_idx, source_uid, targets, effect):
    source_inst = engine.state.instances.get(source_uid)
    if source_inst is None:
        return True
    event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
    if not event_uid:
        return True
    link_tag = f"levigata_link:{event_uid}"
    if link_tag not in source_inst.blessed:
        return True
    engine.destroy_saint_by_uid(source_inst.owner, source_uid, cause="effect")
    return True


ACTION_HANDLERS = {
    'absorb_target_stats_and_link': absorb_target_stats_and_link,
    'destroy_source_if_linked_to_event_card': destroy_source_if_linked_to_event_card,
}
