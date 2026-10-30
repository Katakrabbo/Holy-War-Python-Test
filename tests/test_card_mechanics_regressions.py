from pathlib import Path
from dataclasses import replace

import pytest

from holywar.core.engine import GameEngine
from holywar.core.state import CardInstance, GameState, PlayerState
from holywar.data.importer import load_cards_json
from holywar.effects.runtime import ActionSpec, EffectSpec, TargetSpec, runtime_cards
from holywar.web import WebGameSession


CARDS = {card.name: card for card in load_cards_json(Path("holywar/data/cards.json"))}


def game(*names: str) -> GameEngine:
    instances = {
        f"c{i}": CardInstance(f"c{i}", CARDS[name], 0, CARDS[name].faith)
        for i, name in enumerate(names)
    }
    return GameEngine(GameState(
        players=[PlayerState.empty("P1"), PlayerState.empty("P2")],
        instances=instances, active_player=0, turn_number=1, phase="main",
    ))


def test_cura_rapida_heals_exactly_two_distinct_friendly_saints() -> None:
    engine = game("Cura Rapida", "Sif", "Han Xiangzi", "Muninn")
    p = engine.state.players[0]
    p.hand = ["c0"]
    p.attack = ["c1", "c2", "c3"]
    before = {uid: engine.state.instances[uid].current_faith for uid in p.attack}
    for invalid in ("c1", "c1,c1"):
        assert not runtime_cards.can_play(engine, 0, "c0", target=invalid)[0]
    assert engine.play_card(0, 0, "c1,c2").ok
    assert engine.state.instances["c1"].current_faith == before["c1"] + 3
    assert engine.state.instances["c2"].current_faith == before["c2"] + 3
    assert engine.state.instances["c3"].current_faith == before["c3"]


def test_manual_targets_reject_enemy_and_wrong_zone_uids() -> None:
    engine = game("Cura Rapida", "Sif", "Han Xiangzi", "Muninn")
    p, enemy = engine.state.players
    p.hand = ["c0", "c3"]
    p.attack[0] = "c1"
    enemy.attack[0] = "c2"
    engine.state.instances["c2"].owner = 1
    assert not runtime_cards.can_play(engine, 0, "c0", target="c1,c2")[0]
    assert not runtime_cards.can_play(engine, 0, "c0", target="c1,c3")[0]


def test_cenote_has_one_selection_and_uses_current_faith_once() -> None:
    engine = game("Cenote Sacro", "Sif", "Muninn")
    p = engine.state.players[0]
    p.artifacts[0] = "c0"
    p.attack[:2] = ["c1", "c2"]
    p.sin = 30
    engine.state.instances["c1"].current_faith = 9
    session = WebGameSession.__new__(WebGameSession)
    session.engine = engine
    script = runtime_cards.get_script("Cenote Sacro")
    assert len(session._manual_action_steps("c0", 0, script.on_activate_actions, "on_activate")) == 1
    assert engine.activate_ability(0, "r1", "seq:0=c1").ok
    expected = 30 + CARDS["Sif"].faith - 9
    assert p.sin == expected
    assert "c1" in p.graveyard
    assert "c2" in p.attack
    engine.activate_ability(0, "r1", "c2")
    assert "c2" in p.attack
    assert p.sin == expected


def test_cenote_does_not_remove_sin_when_destruction_is_prevented() -> None:
    engine = game("Cenote Sacro", "Sif")
    p = engine.state.players[0]
    p.artifacts[0], p.attack[0], p.sin = "c0", "c1", 30
    engine.state.instances["c1"].blessed.append("moribondo_shield")
    assert engine.activate_ability(0, "r1", "c1").ok
    assert p.sin == 30
    assert p.attack[0] == "c1"


@pytest.mark.parametrize("saint", ["Sif", "Han Xiangzi", "Gub-ner Antico"])
def test_vasi_canopi_revives_only_equipped_saint_without_effects(saint: str) -> None:
    engine = game("Vasi Canopi", saint, "Muninn")
    p = engine.state.players[0]
    p.hand, p.attack[:2] = ["c0"], ["c1", "c2"]
    assert engine.play_card(0, 0, "c1").ok
    assert "c0" not in p.graveyard
    assert "c0" not in p.artifacts
    # Also exercise restoring a match with a blessing attached outside board slots.
    engine = GameEngine(GameState.from_dict(engine.state.to_dict()))
    p = engine.state.players[0]
    engine.destroy_saint_by_uid(0, "c2", cause="battle")
    assert "c2" in p.graveyard
    assert "equipped_to:c1" in engine.state.instances["c0"].blessed
    engine.destroy_saint_by_uid(0, "c1", cause="battle")
    assert "c1" in p.attack + p.defense
    assert "c1" not in p.graveyard
    assert "c0" in p.graveyard
    assert not engine.state.instances["c0"].blessed
    assert engine.state.instances["c1"].current_faith == CARDS[saint].faith
    assert "silenced" in engine.state.instances["c1"].cursed
    assert not engine.state.flags.get("_runtime_waiting_for_reveal")
    assert not engine.activate_ability(0, "c1", "c1").ok
    engine.destroy_saint_by_uid(0, "c1", cause="battle")
    assert "c1" in p.graveyard
    assert "silenced" not in engine.state.instances["c1"].cursed


def test_equipped_blessing_is_discarded_when_host_leaves_without_defeat() -> None:
    engine = game("Vasi Canopi", "Sif")
    p = engine.state.players[0]
    p.hand, p.attack[0] = ["c0"], "c1"
    assert engine.play_card(0, 0, "c1").ok
    assert engine.move_board_card_to_hand(0, "c1")
    assert "c0" in p.graveyard
    assert "c1" in p.hand
    assert not engine.state.instances["c0"].blessed


def test_mela_del_peccato_death_triggers_survive_equipment_cleanup() -> None:
    engine = game("Mela del Peccato", "Sif")
    p = engine.state.players[0]
    p.hand, p.attack[0], p.sin = ["c0"], "c1", 0
    assert engine.play_card(0, 0, "c1").ok
    engine.destroy_saint_by_uid(0, "c1", cause="effect")
    assert p.sin == 2 * CARDS["Sif"].faith
    assert "c0" in p.excommunicated
    assert "c0" not in p.graveyard


def test_scambio_dei_pesi_selects_each_saint_once_and_applies_both_stats() -> None:
    engine = game("Scambio dei Pesi", "Sif", "Han Xiangzi")
    p, enemy = engine.state.players
    p.hand, p.attack[0], enemy.attack[0] = ["c0"], "c1", "c2"
    engine.state.instances["c2"].owner = 1
    engine.state.instances["c2"].current_faith = 10
    session = WebGameSession.__new__(WebGameSession)
    session.engine = engine
    script = runtime_cards.get_script("Scambio dei Pesi")
    steps = session._manual_action_steps("c0", 0, script.on_play_actions, "on_play")
    assert len(steps) == 2
    friendly_strength = engine.get_effective_strength("c1")
    enemy_strength = engine.get_effective_strength("c2")
    assert engine.play_card(0, 0, "seq:0=c1;;2=c2").ok
    assert engine.state.instances["c1"].current_faith == CARDS["Sif"].faith + 2
    assert engine.get_effective_strength("c1") == friendly_strength + 2
    assert engine.state.instances["c2"].current_faith == 8
    assert engine.get_effective_strength("c2") == max(0, enemy_strength - 2)


def test_sequoia_doubles_total_strength_without_recounting_existing_buffs() -> None:
    engine = game("Sequoia")
    engine.state.players[0].attack[0] = "c0"
    inst = engine.state.instances["c0"]
    inst.blessed.append("buff_str:3")
    runtime_cards.on_enter_bind_triggers(engine, 0, "c0")
    before = engine.get_effective_strength("c0")
    engine._emit_event("on_this_card_kills_in_battle", 0, card="c0")
    assert engine.get_effective_strength("c0") == before * 2
    engine._emit_event("on_this_card_kills_in_battle", 0, card="c0")
    assert engine.get_effective_strength("c0") == before * 4
    assert inst.definition.strength == CARDS["Sequoia"].strength


def test_vasi_canopi_removes_passive_bonuses_as_well_as_activated_effects() -> None:
    engine = game("Vasi Canopi", "Odino", "Gungnir")
    p = engine.state.players[0]
    p.hand, p.attack[0], p.artifacts[0] = ["c0"], "c1", "c2"
    assert engine.get_effective_strength("c1") == CARDS["Odino"].strength + 4
    assert engine.play_card(0, 0, "c1").ok
    engine.destroy_saint_by_uid(0, "c1", cause="battle")
    assert "c1" in p.attack + p.defense
    assert engine.get_effective_strength("c1") == CARDS["Odino"].strength
    engine = GameEngine(GameState.from_dict(engine.state.to_dict()))
    assert engine.get_effective_strength("c1") == CARDS["Odino"].strength


def test_card_owned_damage_rule_halves_direct_attack_and_death_sin() -> None:
    engine = game("Sif", "Giorno 2: Cielo Terrestre", "Muninn")
    attacker, defender = engine.state.players
    attacker.attack[0], defender.artifacts[0], defender.attack[0] = "c0", "c1", "c2"
    engine.state.instances["c1"].owner = engine.state.instances["c2"].owner = 1
    engine.destroy_saint_by_uid(1, "c2", cause="battle")
    assert defender.sin == CARDS["Muninn"].faith // 2
    before = defender.sin
    strength = engine.get_effective_strength("c0")
    assert engine.attack(0, 0, None).ok
    assert defender.sin == before + strength // 2


def test_card_owned_bandage_rule_restores_faith_and_consumes_equipment() -> None:
    engine = game("Bende Consacrate", "Sif")
    player = engine.state.players[0]
    player.hand, player.attack[0] = ["c0"], "c1"
    assert engine.play_card(0, 0, "c1").ok
    engine.state.instances["c1"].current_faith = 0
    engine._cleanup_zero_faith_saints()
    assert player.attack[0] == "c1"
    assert engine.state.instances["c1"].current_faith == 1
    assert "c0" in player.graveyard
    engine.destroy_saint_by_uid(0, "c1", cause="battle")
    assert "c1" in player.graveyard


def test_player_counter_rules_apply_guardian_bonus_and_altar_protection() -> None:
    engine = game("Altare dei Sette Sigilli", "Custode dei Sigilli", "Cura")
    player = engine.state.players[0]
    player.building, player.attack[0] = "c0", "c1"
    engine.state.instances["c2"].owner = 1
    base_faith = engine.state.instances["c1"].current_faith
    base_strength = engine.get_effective_strength("c1")
    runtime_cards._apply_effect(engine, 0, "c0", [], EffectSpec(
        action="add_player_counter", flag="sigilli", amount=6,
    ))
    assert runtime_cards.get_player_counter(engine, 0, "sigilli") == 6
    assert engine.state.instances["c1"].current_faith == base_faith + 8
    assert engine.get_effective_strength("c1") == base_strength + 8
    engine.state.flags["_runtime_effect_source"] = "c2"
    engine.destroy_any_card(0, "c0")
    assert player.building == "c0"
    assert runtime_cards.get_player_counter(engine, 0, "sigilli") == 6 - int(CARDS["Cura"].crosses)


def test_kah_ok_script_resolves_its_threshold_and_sin_cost() -> None:
    engine = game("Kah-ok")
    player = engine.state.players[0]
    player.attack[0] = "c0"
    engine.state.instances["c0"].current_faith = 8
    runtime_cards.on_enter_bind_triggers(engine, 0, "c0")
    engine._emit_event("on_my_turn_start", 0)
    assert "c0" in player.graveyard
    assert player.sin == CARDS["Kah-ok"].faith + 10


def test_custom_actions_are_dispatched_only_from_the_owning_script(monkeypatch) -> None:
    engine = game("Sif", "Muninn")
    calls = []

    def custom_action(runtime, engine, owner_idx, source_uid, targets, effect):
        calls.append((owner_idx, source_uid, targets))
        engine.state.instances[source_uid].current_faith += 3

    script = replace(runtime_cards.get_script("Sif"),
        action_handlers={"test_custom_action": custom_action},
        on_play_mode="scripted",
        on_play_actions=[ActionSpec(TargetSpec(type="source_card"), EffectSpec(action="test_custom_action"))],
    )
    monkeypatch.setitem(runtime_cards._scripts, "sif", script)
    before = engine.state.instances["c0"].current_faith
    runtime_cards.resolve_play(engine, 0, "c0", None)
    runtime_cards._apply_effect(engine, 0, "c1", [], EffectSpec(action="test_custom_action"))
    assert calls == [(0, "c0", ["c0"])]
    assert engine.state.instances["c0"].current_faith == before + 3


def test_quick_target_defaults_follow_script_preferences() -> None:
    engine = game("Moribondo", "Cura", "Corruzione", "Sif", "Muninn")
    player, opponent = engine.state.players
    player.hand, player.attack[1], opponent.attack[2] = ["c0", "c1", "c2"], "c3", "c4"
    engine.state.instances["c4"].owner = 1
    session = WebGameSession.__new__(WebGameSession)
    session.engine = engine
    assert session._default_quick_target(0, 0) == "a2"
    assert session._default_quick_target(0, 1) == "a2"
    assert session._default_quick_target(0, 2) == "a3"


def test_card_script_restores_legacy_merged_zone_state() -> None:
    engine = game("Promessa dell'oltretomba")
    engine.state.flags["oltretomba_promise_active"] = {"0": True, "1": False}
    restored = GameEngine(GameState.from_dict(engine.state.to_dict()))
    assert restored.state.flags["deck_graveyard_merge_active"] == {"0": True, "1": False}
    assert "oltretomba_promise_active" not in restored.state.flags
