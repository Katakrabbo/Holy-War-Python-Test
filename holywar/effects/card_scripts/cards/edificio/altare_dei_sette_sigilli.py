from __future__ import annotations

CARD_NAME = """Altare dei Sette Sigilli"""

SCRIPT = {
    "counter_tag": "sigilli",
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "provides_player_counter": True,
    "triggered_effects": [
        {
            "trigger": {
                "event": "on_saint_defeated_or_destroyed",
                "frequency": "each_turn",
                "condition": {"event_card_owner": "me"},
            },
            "target": {"type": "source_card"},
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 1},
        },
        {
            "trigger": {
                "event": "on_card_played",
                "frequency": "each_turn",
                "condition": {
                    "all_of": [
                        {"event_card_owner": "me"},
                        {"event_card_name_contains": "Sigillo"},
                    ]
                },
            },
            "target": {"type": "source_card"},
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 1},
        },
        {
            "trigger": {"event": "on_this_card_leaves_field", "frequency": "each_time"},
            "target": {"type": "source_card"},
            "effect": {"action": "remove_player_counter", "flag": "sigilli", "amount": 999},
        },
    ],
    "on_play_actions": [],
}


def player_counter(runtime, engine, value, *, player_idx, key, operation):
    if key != "sigilli":
        return value
    uid = engine.state.players[player_idx].building
    if not uid or engine.state.instances[uid].effect_name != CARD_NAME:
        return value
    inst = engine.state.instances[uid]
    if operation == "get":
        for tag in inst.blessed:
            if tag.startswith("sigilli:"):
                try:
                    return int(tag.split(":", 1)[1])
                except ValueError:
                    return 0
        return 0
    inst.blessed = [tag for tag in inst.blessed if not tag.startswith("sigilli:")]
    inst.blessed.append(f"sigilli:{max(0, int(value))}")
    return value


def prevent_destruction(runtime, engine, prevented, *, uid, **context):
    if prevented or engine.state.instances[uid].effect_name != CARD_NAME:
        return prevented
    source_uid = str(engine.state.flags.get("_runtime_effect_source", "")).strip()
    if not source_uid or source_uid == uid or source_uid not in engine.state.instances:
        return False
    try:
        cost = int(float(engine.state.instances[source_uid].definition.crosses or 0))
    except (TypeError, ValueError):
        return False
    owner = engine._find_board_owner_of_uid(uid)
    if owner is None:
        owner = engine.state.instances[uid].owner
    seals = runtime.get_player_counter(engine, owner, "sigilli")
    if cost <= 0 or seals < cost:
        return False
    runtime.set_player_counter(engine, owner, "sigilli", seals - cost)
    engine.state.log(f"{CARD_NAME} rimuove {cost} Segnalini Sigillo e annulla la distruzione.")
    return True


RULE_HOOKS = {"player_counter": player_counter, "prevent_card_destruction": prevent_destruction}
