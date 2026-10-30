from __future__ import annotations

CARD_NAME = """Ph'drna"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "scripted",
    "activate_targeting": "none",
    "can_activate_by_any_player": True,
    "inverts_saint_summon_controller": True,
    "indestructible_except_own_activation": True,
    "triggered_effects": [],
    "on_play_actions": [],
    "on_activate_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "choose_option",
                "choice_title": "Ph'drna",
                "choice_prompt": "Scegli il costo di attivazione.",
                "choice_options": [
                    {
                        "value": "building",
                        "label": "Sacrifica 1 Edificio + 10 Ispirazione",
                        "condition": {
                            "all_of": [
                                {"my_inspiration_gte": 10},
                                {
                                    "controller_has_cards": {
                                        "owner": "me",
                                        "zone": "building",
                                        "min_count": 1,
                                    }
                                },
                            ]
                        },
                    },
                    {
                        "value": "artifacts",
                        "label": "Sacrifica 4 Artefatti + 10 Ispirazione",
                        "condition": {
                            "all_of": [
                                {"my_inspiration_gte": 10},
                                {
                                    "controller_has_cards": {
                                        "owner": "me",
                                        "zone": "artifacts",
                                        "min_count": 4,
                                    }
                                },
                            ]
                        },
                    },
                ],
            },
        },
        {
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "any",
            },
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "target": {"type": "source_card"},
            "effect": {"action": "phdrna_activate_destroy_target_then_self"},
        },
    ],
}


def phdrna_activate_destroy_target_then_self(self, engine, owner_idx, source_uid, targets, effect):
    from holywar.effects.runtime import _norm
    selected = str(engine.state.flags.get("_runtime_selected_target", "")).strip()
    target_uid = selected if selected in engine.state.instances else None
    if not target_uid:
        return True

    selected_option = _norm(str(engine.state.flags.get("_runtime_selected_option", "")))
    player = engine.state.players[owner_idx]
    cost_inspiration = 10

    if selected_option == "building":
        if player.building is None:
            return True
        engine.send_to_graveyard(owner_idx, player.building)
    elif selected_option == "artifacts":
        artifacts = [uid for uid in player.artifacts if uid]
        if len(artifacts) < 4:
            return True
        for art_uid in artifacts[:4]:
            engine.send_to_graveyard(owner_idx, art_uid)
    else:
        return True

    total_inspiration = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
    if total_inspiration < cost_inspiration:
        return True

    temp = max(0, int(getattr(player, "temporary_inspiration", 0)))
    use_temp = min(temp, cost_inspiration)
    player.temporary_inspiration = temp - use_temp
    player.inspiration = max(0, int(player.inspiration) - (cost_inspiration - use_temp))

    target_inst = engine.state.instances.get(target_uid)
    if target_inst is not None:
        engine.destroy_any_card(target_inst.owner, target_uid)

    engine.state.flags["_allow_indestructible_uid"] = source_uid
    source_inst = engine.state.instances.get(source_uid)
    if source_inst is not None:
        engine.destroy_any_card(source_inst.owner, source_uid)
    engine.state.flags.pop("_allow_indestructible_uid", None)
    return True


ACTION_HANDLERS = {
    'phdrna_activate_destroy_target_then_self': phdrna_activate_destroy_target_then_self,
}
