from __future__ import annotations

CARD_NAME = "Bende Consacrate"

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "guided",
    "triggered_effects": [],
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
        },
        {
            "target": {"type": "equipped_target_of_source"},
            "effect": {"action": "grant_blessed_tag_from_source", "flag": "bende_consacrate"},
        },
    ],
}


def prevent_destruction(runtime, engine, prevented, *, uid, **context):
    if prevented:
        return True
    inst = engine.state.instances[uid]
    tags = [tag for tag in inst.blessed if str(tag).startswith("bende_consacrate")]
    if not tags:
        return False
    used_tag = tags[0]
    inst.blessed.remove(used_tag)
    if ":" in used_tag:
        source = engine.state.instances.get(used_tag.split(":", 1)[1].strip())
        if source is not None:
            engine.destroy_any_card(source.owner, source.uid)
    inst.current_faith = 1
    engine.state.log(f"{CARD_NAME} salva {inst.definition.name}: rimane con 1 Fede.")
    return True


RULE_HOOKS = {"prevent_saint_destruction": prevent_destruction}
