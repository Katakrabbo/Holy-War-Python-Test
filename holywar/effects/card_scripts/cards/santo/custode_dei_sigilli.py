from __future__ import annotations

CARD_NAME = """Custode dei Sigilli"""

SCRIPT = {
    "on_play_mode": "noop",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "triggered_effects": [
        {
            "trigger": {"event": "on_enter_field", "frequency": "each_turn"},
            "target": {
                "type": "cards_controlled_by_owner",
                "zone": "field",
                "owner": "me",
                "card_filter": {"name_contains": "__no_target__"},
            },
            "effect": {"action": "add_player_counter", "flag": "sigilli", "amount": 2},
        }
    ],
    "on_play_actions": [],
}


def refresh_bonus(runtime, engine, value, *, player_idx):
    seals = runtime.get_player_counter(engine, player_idx, "sigilli")
    for uid in engine.all_saints_on_field(player_idx):
        inst = engine.state.instances[uid]
        if inst.effect_name != CARD_NAME:
            continue
        level = seals // 3
        old_level = 0
        kept = []
        for tag in inst.blessed:
            if tag.startswith("custode_bonus:"):
                try:
                    old_level = int(tag.split(":", 1)[1])
                except ValueError:
                    pass
            else:
                kept.append(tag)
        if level > old_level:
            delta = level - old_level
            inst.current_faith = (inst.current_faith or 0) + delta * 4
            kept.extend(["buff_str:4"] * delta)
        kept.append(f"custode_bonus:{max(level, old_level)}")
        inst.blessed = kept
    return value


RULE_HOOKS = {"refresh_continuous_effects": refresh_bonus}
