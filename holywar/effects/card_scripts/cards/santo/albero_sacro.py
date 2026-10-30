from __future__ import annotations

CARD_NAME = """Albero Sacro"""

SCRIPT = {
    "on_play_mode": "noop",
    "on_enter_mode": "scripted",
    "on_activate_mode": "auto",
    "play_targeting": "none",
    "auto_play_on_draw": True,
    "end_turn_on_draw": True,
    "triggered_effects": [
        {
            "trigger": {"event": "on_preparation_complete", "frequency": "each_turn"},
            "target": {"type": "empty_saint_slots_controlled_by_owner", "owner": "me"},
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "trigger": {"event": "on_preparation_complete", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {
                "action": "summon_generated_token",
                "card_name": "Token Albero",
                "owner": "me",
                "position": "selected_target_slot",
            },
        },
        {
            "trigger": {"event": "on_my_turn_end", "frequency": "each_turn"},
            "target": {"type": "empty_saint_slots_controlled_by_owner", "owner": "me"},
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "trigger": {"event": "on_opponent_turn_end", "frequency": "each_turn"},
            "target": {"type": "empty_saint_slots_controlled_by_owner", "owner": "me"},
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "trigger": {"event": "on_my_turn_end", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {
                "action": "summon_generated_token",
                "card_name": "Token Albero",
                "owner": "me",
                "position": "selected_target_slot",
            },
        },
        {
            "trigger": {"event": "on_opponent_turn_end", "frequency": "each_turn"},
            "target": {"type": "source_card"},
            "effect": {
                "action": "summon_generated_token",
                "card_name": "Token Albero",
                "owner": "me",
                "position": "selected_target_slot",
            },
        },
        {
            "trigger": {"event": "on_saint_defeated_in_battle", "frequency": "each_turn"},
            "condition": {"event_card_name_is": "Token Albero"},
            "target": {"type": "source_card"},
            "effect": {"action": "increase_faith", "amount": 2},
        },
    ],
    "on_play_actions": [],
    "on_enter_actions": [
        {
            "target": {"type": "empty_saint_slots_controlled_by_owner", "owner": "me"},
            "effect": {"action": "choose_targets", "min_targets": 1, "max_targets": 1},
        },
        {
            "target": {"type": "source_card"},
            "effect": {
                "action": "summon_generated_token",
                "card_name": "Token Albero",
                "owner": "me",
                "position": "selected_target_slot",
            },
        },
    ],
}


def choose_auto_play_target(runtime, engine, target, *, player_idx, uid, preparation):
    if preparation or engine.state.instances[uid].effect_name != CARD_NAME:
        return target
    chooser = getattr(engine, "choose_auto_play_slot_from_draw", None)
    if not callable(chooser):
        return target
    player = engine.state.players[player_idx]
    slots = [f"a{i+1}" for i, card in enumerate(player.attack) if card is None]
    slots += [f"d{i+1}" for i, card in enumerate(player.defense) if card is None]
    if not slots:
        return target
    chosen = str(chooser(player_idx, uid, slots) or "").strip().lower()
    return chosen if chosen in slots else target


RULE_HOOKS = {"auto_play_target": choose_auto_play_target}


def ai_score(runtime, engine, score, *, uid, stage):
    if engine.state.instances[uid].effect_name != CARD_NAME:
        return score
    return score + {"permanent": 25, "building_play": 40, "building_tactical": 35}.get(stage, 0)


RULE_HOOKS["ai_score"] = ai_score
