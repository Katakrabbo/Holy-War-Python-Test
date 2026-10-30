from __future__ import annotations

CARD_NAME = """Moribondo"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "own_saint",
    "play_requirements": {
        "allow_quick_play_out_of_turn": True,
        "quick_target_owner": "me",
        "quick_play_excommunicate_self": True,
        "quick_play_grant_blessed_tag": "moribondo_shield",
    },
    "triggered_effects": [
    ],
    "on_play_actions": [],
}


def prevent_destruction(runtime, engine, prevented, *, uid, **context):
    if prevented:
        return True
    inst = engine.state.instances[uid]
    if "moribondo_shield" not in inst.blessed:
        return False
    inst.blessed.remove("moribondo_shield")
    engine.state.log(f"{CARD_NAME} annulla la distruzione di {inst.definition.name}.")
    return True


RULE_HOOKS = {"prevent_saint_destruction": prevent_destruction}
