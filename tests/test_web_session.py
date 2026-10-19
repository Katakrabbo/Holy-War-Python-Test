from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from holywar.web import WebGameSession
from holywar.effects.runtime import EffectSpec, TargetSpec, runtime_cards
from holywar.scripting_api import RuleEventContext
from holywar.multiplayer.protocol import AuthoritativeMatch, MatchCommand, ProtocolError
from holywar.multiplayer.service import MultiplayerService


def test_web_snapshot_hides_opponent_hand_and_exposes_real_cards() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    snapshot = session.snapshot()

    assert snapshot["ok"] is True
    assert snapshot["game"]["can_act"] is True
    assert snapshot["game"]["players"][0]["hand_count"] == 5
    assert snapshot["game"]["players"][0]["hand"][0]["name"]
    assert snapshot["game"]["players"][1]["hand"][0] == {
        "uid": snapshot["game"]["players"][1]["hand"][0]["uid"],
        "hidden": True,
    }


def test_web_config_identifies_the_packaged_application() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    assert session.config()["application"] == "holywar"


def test_application_session_can_start_without_preloading_a_match() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11, autoload=False)

    assert session.engine is None
    assert session.snapshot()["game"] is None


def test_online_snapshots_keep_each_players_hand_private() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})

    host = session.snapshot(viewer_idx=0)["game"]["players"]
    guest = session.snapshot(viewer_idx=1)["game"]["players"]

    assert host[0]["hand"][0].get("hidden") is not True
    assert host[1]["hand"][0]["hidden"] is True
    assert guest[0]["hand"][0].get("hidden") is not True
    assert guest[1]["hand"][0]["hidden"] is True


def test_online_spectator_sees_both_hands_but_cannot_act() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})

    snapshot = session.snapshot(viewer_idx=0, spectator=True)["game"]

    assert snapshot["spectator"] is True
    assert snapshot["can_act"] is False
    assert snapshot["players"][0]["hand"][0].get("hidden") is not True
    assert snapshot["players"][1]["hand"][0].get("hidden") is not True


def test_online_preparation_hides_opponent_field_until_both_confirm_coin_toss() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})
    assert session.engine is not None
    opponent = session.engine.state.players[1]
    hidden_uid = opponent.hand.pop()
    opponent.attack[0] = hidden_uid

    preparing = session.snapshot(viewer_idx=0)["game"]
    assert preparing["players"][1]["field_hidden"] is True
    assert preparing["players"][1]["attack"] == [None, None, None]
    assert hidden_uid not in str(preparing)

    session.action({"type": "end_turn"}, network_actor_idx=0)
    tossed = session.action({"type": "end_turn"}, network_actor_idx=1)
    assert tossed["game"]["coin_toss"]["pending"] is True
    assert tossed["game"]["players"][1]["field_hidden"] is True

    waiting = session.action({"type": "confirm_coin_toss"}, network_actor_idx=0)
    assert waiting["game"]["coin_toss"]["pending"] is True
    assert waiting["game"]["players"][1]["field_hidden"] is True

    revealed = session.action({"type": "confirm_coin_toss"}, network_actor_idx=1)
    assert revealed["game"]["coin_toss"]["pending"] is False
    assert revealed["game"]["players"][0]["field_hidden"] is False


def test_online_action_rejects_player_without_priority() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})
    assert session.engine is not None
    wrong_actor = 1 - session.engine.state.active_player

    response = session.action({"type": "end_turn"}, network_actor_idx=wrong_actor)

    assert response["ok"] is False
    assert "avversario" in response["message"].lower()


def test_online_host_uses_assigned_player_two_during_preparation() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})
    assert session.engine is not None
    session.engine.state.active_player = 1
    service = MultiplayerService(session)
    service.user_id = service.owner_id = "host"
    service.lobby_id = "lobby"
    service.role = "host"
    service.player_role = "player2"
    service.phase = "playing"
    service.members = ["host"]

    result = service.request("action", {"type": "end_turn"})

    assert result["ok"] is True
    assert result["game"]["viewer_index"] == 1


def test_online_host_tracks_hello_sender_before_broadcasting_room() -> None:
    service = MultiplayerService(WebGameSession(Path("holywar/data/cards.json"), seed=11))
    service.user_id = service.owner_id = "host"
    service.lobby_id = "lobby"
    service.role = "host"
    service.phase = "waiting"
    service.members = ["host"]
    service.profiles = {"host": {"name": "Host", "role": None, "deck": "", "ready": False}}

    with patch.object(service, "_broadcast_room") as broadcast:
        service._handle_message("guest", {"kind": "hello", "profile": {"name": "Guest"}, "password": ""})

    assert service.members == ["host", "guest"]
    assert service.profiles["guest"]["name"] == "Guest"
    broadcast.assert_called_once()


def test_online_room_rejects_duplicate_participant_names() -> None:
    service = MultiplayerService(WebGameSession(Path("holywar/data/cards.json"), seed=11))
    service.user_id = service.owner_id = "host"
    service.lobby_id = "lobby"
    service.role = "host"
    service.phase = "waiting"
    service.members = ["host"]
    service.profiles = {"host": {"name": "Pellegrino", "role": None, "deck": "", "ready": False}}

    with patch.object(service, "_send_message") as send, patch.object(service, "_broadcast_room") as broadcast:
        service._handle_message(
            "guest",
            {"kind": "hello", "profile": {"name": "  PELLEGRINO  "}, "password": ""},
        )

    assert "guest" not in service.members
    assert "guest" not in service.profiles
    send.assert_called_once_with({
        "kind": "join_rejected",
        "message": "Due partecipanti con lo stesso nome non possono partecipare alla stessa stanza.",
    }, "guest")
    broadcast.assert_not_called()


def test_online_room_requires_every_participant_to_choose_role() -> None:
    service = MultiplayerService(WebGameSession(Path("holywar/data/cards.json"), seed=11))
    service.user_id = service.owner_id = "host"
    service.lobby_id = "lobby"
    service.role = "host"
    service.phase = "waiting"
    service.profiles = {
        "host": {"name": "Host", "role": "player1", "deck": "", "ready": False},
        "guest": {"name": "Guest", "role": "player2", "deck": "", "ready": False},
        "third": {"name": "Third", "role": None, "deck": "", "ready": False},
    }

    with pytest.raises(ValueError, match="Ogni partecipante"):
        service._apply_room_action("host", "proceed", {})


def test_online_options_use_the_network_players_private_hand() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})
    assert session.engine is not None
    guest_uid = session.engine.state.players[1].hand[0]

    options = session.play_options({"uid": guest_uid}, network_actor_idx=1)

    assert options["ok"] is True
    assert options["uid"] == guest_uid


def test_multiplayer_transport_reassembles_large_private_snapshots() -> None:
    class RecordingBridge:
        def __init__(self) -> None:
            self.packets: list[str] = []

        def request(self, operation: str, payload: dict, *, timeout: float = 45) -> dict:
            assert operation == "send_packet"
            self.packets.append(payload["data"])
            return {"sent": True}

    sender_session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    receiver_session = WebGameSession(Path("holywar/data/cards.json"), seed=12)
    sender = MultiplayerService(sender_session)
    receiver = MultiplayerService(receiver_session)
    bridge = RecordingBridge()
    sender.bridge = bridge  # type: ignore[assignment]
    receiver.role = "guest"
    receiver.lobby_id = "lobby"
    receiver.peer_id = "host"
    receiver.members = ["host", "guest"]
    snapshot = sender_session.snapshot(viewer_idx=1)
    snapshot["game"]["logs"] = ["x" * 5000]

    sender._send_message({"kind": "state", "snapshot": snapshot}, "guest")
    for packet in bridge.packets:
        receiver._handle_bridge_event({
            "type": "packet_received",
            "payload": {"senderId": "host", "data": packet},
        })

    assert len(bridge.packets) > 1
    assert receiver.remote_snapshot == snapshot


def test_multiplayer_command_round_trip_and_validation() -> None:
    original = MatchCommand(
        match_id="match-1",
        sender_id="player-1",
        sequence=3,
        expected_revision=8,
        kind="end_turn",
    )

    restored = MatchCommand.from_dict(original.to_dict())

    assert restored == original
    invalid = original.to_dict()
    invalid["protocol_version"] = 999
    with pytest.raises(ProtocolError):
        MatchCommand.from_dict(invalid)


def test_authoritative_match_orders_commands_and_returns_private_snapshots() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"mode": "online"})
    assert session.engine is not None
    players = ("host", "guest")
    match = AuthoritativeMatch("match-1", session, players)
    active_id = players[session.engine.state.active_player]
    command = MatchCommand(
        match_id="match-1",
        sender_id=active_id,
        sequence=0,
        expected_revision=0,
        kind="end_turn",
    )

    result = match.apply(command)

    assert result["ok"] is True
    assert result["revision"] == 1
    assert result["ack_sequence"] == 0
    assert result["snapshots"]["host"]["game"]["players"][1]["hand"][0]["hidden"] is True
    assert result["snapshots"]["guest"]["game"]["players"][1]["hand"][0]["hidden"] is True
    with pytest.raises(ProtocolError, match="revisione"):
        match.apply(command)


def test_web_deck_editor_exposes_saved_decks_and_unique_catalogue() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    editor = session.deck_editor()

    assert editor["religions"]
    assert any(deck["id"] == "cristianesimo_b3_creatore" for deck in editor["decks"])
    names = [card["name"].casefold() for card in editor["cards"]]
    assert len(names) == len(set(names))
    assert all(card["card_type"].casefold() != "token" for card in editor["cards"])
    assert all(card["max_copies"] >= 1 for card in editor["cards"])


def test_web_deck_editor_uses_legacy_minimum_and_copy_limits() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    catalogue = session.deck_editor()["cards"]
    five_copy_card = next(card for card in catalogue if card["max_copies"] == 5)

    incomplete = session.validate_deck({"cards": [{"name": five_copy_card["name"], "qty": 6}]})

    assert incomplete["valid"] is False
    assert any("6/45" in error for error in incomplete["errors"])
    assert any("max 5" in error for error in incomplete["errors"])


def test_effect_target_options_include_complete_card_preview() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    uid = session.engine.state.players[0].hand[0]

    option = session._candidate_option(uid, 0)

    assert option["value"] == uid
    assert option["card"]["name"]
    assert "cost" in option["card"]
    assert "strength" in option["card"]
    assert "faith" in option["card"]
    assert "effect" in option["card"]


def test_card_preview_exposes_current_and_original_combat_values() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    uid = next(
        uid for uid, instance in session.engine.state.instances.items()
        if instance.definition.strength is not None and instance.definition.faith is not None
    )
    instance = session.engine.state.instances[uid]
    instance.current_faith = int(instance.definition.faith or 0) + 2

    card = session._card(uid)

    assert card is not None
    assert card["base_strength"] == instance.definition.strength
    assert card["base_faith"] == instance.definition.faith
    assert card["faith"] == int(instance.definition.faith or 0) + 2


def _move_named_card_to_hand(session: WebGameSession, player_idx: int, name: str) -> str:
    assert session.engine is not None
    player = session.engine.state.players[player_idx]
    uid = next(
        uid
        for uid, instance in session.engine.state.instances.items()
        if instance.owner == player_idx and instance.definition.name == name
    )
    for zone in (player.deck, player.white_deck, player.graveyard, player.excommunicated, player.hand):
        if uid in zone:
            zone.remove(uid)
    player.hand.append(uid)
    return uid


def _draw_control_test_payload(
    *,
    mode: str,
    active_player: int,
    player_attack: list[str] | None = None,
    player_artifacts: list[str] | None = None,
    opponent_attack: list[str] | None = None,
    opponent_artifacts: list[str] | None = None,
) -> dict:
    draw_cards = ["Preghiera", "Cura", "Meditazione", "Rinforzi", "Perdono"]
    return {
        "mode": mode,
        "active_player": active_player,
        "initial_draw": True,
        "players": [
            {
                "name": "Pellegrino",
                "deck": draw_cards,
                "attack": player_attack or [],
                "artifacts": player_artifacts or [],
            },
            {
                "name": "Custode",
                "deck": draw_cards,
                "attack": opponent_attack or [],
                "artifacts": opponent_artifacts or [],
            },
        ],
    }


def test_element_artifacts_activate_creator_only_with_complete_set() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.start_test_game(
        _draw_control_test_payload(
            mode="local",
            active_player=0,
            player_artifacts=["Acqua", "Aria", "Fuoco", "Terra"],
        )
    )
    assert session.engine is not None

    cards = [session._card(uid) for uid in session.engine.state.players[0].artifacts]

    assert all(card is not None and card["can_activate"] is False for card in cards)

    complete_session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    payload = _draw_control_test_payload(
        mode="local",
        active_player=0,
        player_artifacts=["Acqua", "Aria", "Fuoco", "Terra"],
    )
    payload["players"][0]["deck"].insert(0, "Dio, il Creatore")
    complete_session.start_test_game(payload)
    assert complete_session.engine is not None
    player = complete_session.engine.state.players[0]
    creator_uid = next(
        uid for uid in player.deck
        if complete_session.engine.state.instances[uid].definition.name == "Dio, il Creatore"
    )
    complete_cards = [complete_session._card(uid) for uid in player.artifacts]
    inspiration_before = player.inspiration + player.temporary_inspiration

    assert all(card is not None and card["can_activate"] is True for card in complete_cards)
    assert all(
        "evoca Dio, il Creatore dal tuo deck o mano senza pagare costo in Ispirazione" in card["effect"]
        for card in complete_cards if card is not None
    )

    waiting = complete_session.action({"type": "activate", "source": "r1", "target": creator_uid})

    decision = waiting["game"]["decision"]
    assert decision["title"] == "Scegli locazione evocazione"
    assert {option["value"] for option in decision["options"]} == {
        "a1", "a2", "a3", "d1", "d2", "d3"
    }

    result = complete_session.resolve_decision({"id": decision["id"], "answer": "a2"})

    assert result["ok"] is True
    assert creator_uid not in player.deck
    assert player.attack[1] == creator_uid
    assert player.inspiration + player.temporary_inspiration == inspiration_before


def test_campana_gains_turn_counter_and_spends_chosen_amount_to_buff_all_saints() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.start_test_game(
        _draw_control_test_payload(
            mode="local",
            active_player=0,
            player_attack=["Araldo della Fine"],
            player_artifacts=["Campana"],
        )
    )
    assert session.engine is not None
    player = session.engine.state.players[0]
    campana_uid = next(uid for uid in player.artifacts if uid)
    campana = session.engine.state.instances[campana_uid]
    saint_uid = next(uid for uid in player.attack if uid)
    saint = session.engine.state.instances[saint_uid]

    assert "campana_counter:1" in campana.blessed
    campana.blessed.remove("campana_counter:1")
    campana.blessed.append("campana_counter:3")
    faith_before = int(saint.current_faith or 0)
    inspiration_before = player.inspiration + player.temporary_inspiration

    waiting = session.action({"type": "activate", "source": "r1"})
    decision = waiting["game"]["decision"]

    assert decision["title"] == "Campana"
    assert {option["value"] for option in decision["options"]} == {"1", "2", "3"}

    resolved = session.resolve_decision({"id": decision["id"], "answer": "2"})

    assert resolved["ok"] is True
    assert "campana_counter:1" in campana.blessed
    assert saint.current_faith == faith_before + 2
    assert player.inspiration + player.temporary_inspiration == inspiration_before


def test_ptah_prompts_with_only_cards_drawn_this_turn_and_replaces_one() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    waiting = session.start_test_game(
        _draw_control_test_payload(mode="local", active_player=0, player_attack=["Ptah"])
    )

    assert session.engine is not None
    decision = waiting["game"]["decision"]
    drawn_before = list(session.engine.state.flags["cards_drawn_this_turn"]["0"])
    assert decision["title"] == "Ptah"
    assert decision["allow_cancel"] is True
    assert {option["value"] for option in decision["options"]} == set(drawn_before)
    assert len(drawn_before) == 3

    resolved = session.resolve_decision({"id": decision["id"], "answer": drawn_before[0]})

    assert resolved["game"]["decision"] is None
    assert len(session.engine.state.players[0].hand) == 3
    assert len(session.engine.state.flags["cards_drawn_this_turn"]["0"]) == 4


@pytest.mark.parametrize("chain_enabled", [True, False])
def test_faro_prompts_on_opponent_draw_without_revealing_card_and_replaces_it(chain_enabled: bool) -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.chain_enabled = chain_enabled

    waiting = session.start_test_game(
        _draw_control_test_payload(mode="local", active_player=1, player_artifacts=["Faro di Alessandria"])
    )

    assert session.engine is not None
    decision = waiting["game"]["decision"]
    assert decision["title"] == "Faro di Alessandria"
    assert {option["value"] for option in decision["options"]} == {"yes", "no"}
    assert all("card" not in option for option in decision["options"])
    assert decision["revealed_card"] is None

    resolved = session.resolve_decision({"id": decision["id"], "answer": "yes"})

    assert resolved["game"]["decision"] is None
    assert len(session.engine.state.players[1].hand) == 3
    assert len(session.engine.state.flags["cards_drawn_this_turn"]["1"]) == 4


def test_faro_can_decline_one_draw_and_trigger_again_on_the_next() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    waiting = session.start_test_game(
        _draw_control_test_payload(mode="local", active_player=1, player_artifacts=["Faro di Alessandria"])
    )
    assert session.engine is not None
    first = waiting["game"]["decision"]
    assert len(session.engine.state.players[1].hand) == 1

    waiting_again = session.resolve_decision({"id": first["id"], "answer": "no"})

    second = waiting_again["game"]["decision"]
    assert second["title"] == "Faro di Alessandria"
    assert len(session.engine.state.players[1].hand) == 2

    resolved = session.resolve_decision({"id": second["id"], "answer": "yes"})

    assert resolved["game"]["decision"] is None
    assert len(session.engine.state.players[1].hand) == 3
    assert len(session.engine.state.flags["cards_drawn_this_turn"]["1"]) == 4


@pytest.mark.parametrize(
    ("active_player", "opponent_attack", "opponent_artifacts"),
    [(1, ["Ptah"], []), (0, [], ["Faro di Alessandria"])],
)
def test_cpu_resolves_draw_control_choices(
    active_player: int,
    opponent_attack: list[str],
    opponent_artifacts: list[str],
) -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    result = session.start_test_game(
        _draw_control_test_payload(
            mode="ai",
            active_player=active_player,
            opponent_attack=opponent_attack,
            opponent_artifacts=opponent_artifacts,
        )
    )

    assert session.engine is not None
    drawn_player = active_player
    assert result["game"]["decision"] is None
    assert len(session.engine.state.players[drawn_player].hand) == 3
    assert len(session.engine.state.flags["cards_drawn_this_turn"][str(drawn_player)]) == 4


def test_opponent_draw_trigger_only_affects_the_correct_controller() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    session.start_test_game(
        _draw_control_test_payload(
            mode="local",
            active_player=0,
            player_attack=["Frate Curatore"],
            opponent_attack=["Frate Curatore"],
        )
    )

    assert session.engine is not None
    player_frate = session.engine.state.players[0].attack[0]
    opponent_frate = session.engine.state.players[1].attack[0]
    assert player_frate is not None and opponent_frate is not None
    assert session.engine.state.instances[player_frate].current_faith == 3
    assert session.engine.state.instances[opponent_frate].current_faith == 6


def test_no_target_effect_cards_are_ready_and_play_without_target() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    player = session.engine.state.players[0]
    player.sin = 8
    prayer_uid = _move_named_card_to_hand(session, 0, "Preghiera")

    prayer = session._card(prayer_uid, hand_owner=0)
    assert prayer is not None
    assert prayer["play_ready"] is True
    assert prayer["play_targeting"] == "none"
    assert prayer["play_requires_target"] is False

    result = session.action({"type": "play", "uid": prayer_uid})
    assert result["ok"] is True
    assert session.engine.state.players[0].sin == 3


def test_giudizio_universale_never_requests_a_manual_target() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    player = session.engine.state.players[0]
    judgment_uid = _move_named_card_to_hand(session, 0, "Giudizio Universale")
    buried_uid = player.deck.pop()
    player.graveyard.append(buried_uid)

    judgment = session._card(judgment_uid, hand_owner=0)
    assert judgment is not None
    assert judgment["play_ready"] is True
    assert judgment["play_requires_target"] is False

    result = session.action({"type": "play", "uid": judgment_uid})
    assert result["ok"] is True
    assert buried_uid not in player.graveyard
    assert judgment_uid in player.graveyard


def test_local_mode_rotates_the_revealed_player_after_end_turn() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    first = session.new_game({"mode": "local", "player_name": "Uno", "opponent_name": "Due"})
    assert first["game"]["mode"] == "local"
    assert first["game"]["players"][0]["name"] == "Uno"

    second = session.action({"type": "end_turn"})
    assert second["game"]["can_act"] is True
    assert second["game"]["viewer_index"] == 1
    assert second["game"]["players"][0]["name"] == "Due"
    assert second["game"]["players"][0]["hand"][0].get("hidden") is not True
    assert second["game"]["players"][1]["hand"][0].get("hidden") is True


def test_web_action_supports_direct_attack_when_enemy_has_no_saints() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    state = session.engine.state
    attacker_player = state.players[0]
    defender = state.players[1]
    state.phase = "main"
    attacker_uid = next(
        uid
        for uid in attacker_player.deck
        if session.engine.state.instances[uid].definition.card_type.lower() == "santo"
        and runtime_cards.get_can_attack(session.engine.state.instances[uid].definition.name)
    )
    attacker_player.deck.remove(attacker_uid)
    attacker_player.attack[0] = attacker_uid
    defender.attack = [None, None, None]
    defender.defense = [None, None, None]
    expected_damage = session.engine.get_effective_strength(attacker_uid)

    result = session.action({"type": "attack", "source": "a1", "target": None})

    assert result["ok"] is True
    assert "Attacco diretto riuscito" in result["message"]
    assert defender.sin == expected_damage
    assert session.engine.state.instances[attacker_uid].exhausted is True


def test_diboscamento_uses_reliquary_candidates_instead_of_board_targets() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"player_deck": "animismo_b3_cataclismi"})
    assert session.engine is not None
    player = session.engine.state.players[0]
    spell_uid = _move_named_card_to_hand(session, 0, "Diboscamento")

    card = session._card(spell_uid, hand_owner=0)
    options = session.play_options({"uid": spell_uid})

    assert card is not None
    assert card["play_requires_target"] is True
    assert len(options["steps"]) == 1
    step = options["steps"][0]
    assert step["zone"] == "deck"
    assert step["minimum"] == 1
    assert step["maximum"] == 3
    assert step["candidates"]
    assert all("Reliquiario" in item["label"] for item in step["candidates"])
    assert all(item["value"] in player.deck for item in step["candidates"])

    selected = [item["value"] for item in step["candidates"][:3]]
    result = session.action({"type": "play", "uid": spell_uid, "target": ",".join(selected)})
    assert result["ok"] is True
    assert all(uid in player.graveyard for uid in selected)


def test_ai_turn_is_exposed_one_move_at_a_time() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)

    waiting = session.action({"type": "end_turn"})
    assert waiting["game"]["ai_pending"] is True
    assert waiting["game"]["actual_active_player"] == 1

    with patch("holywar.web.choose_action", return_value=SimpleNamespace(ok=True, message="CPU gioca una carta.")) as choose:
        first_step = session.ai_step()
    choose.assert_called_once()
    assert first_step["message"] == "CPU gioca una carta."
    assert first_step["game"]["ai_pending"] is True

    completed = first_step
    pass_calls = 0
    while completed["game"]["ai_pending"] and pass_calls < 3:
        with patch("holywar.web.choose_action", return_value=SimpleNamespace(ok=True, message="AI passa.")) as choose:
            completed = session.ai_step()
        choose.assert_called_once()
        pass_calls += 1
    assert completed["game"]["ai_pending"] is False
    assert completed["game"]["coin_toss"]["pending"] is True

    started = session.action({"type": "confirm_coin_toss"})
    assert started["game"]["coin_toss"]["pending"] is False


def test_manual_activation_exposes_runtime_zone_candidates() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    player = session.engine.state.players[0]
    warrior_uid = next(
        uid
        for uid, instance in session.engine.state.instances.items()
        if instance.owner == 0 and instance.definition.name == "Guerriero Santificato"
    )
    for zone in (player.deck, player.hand):
        if warrior_uid in zone:
            zone.remove(warrior_uid)
    player.attack[0] = warrior_uid

    options = session.activation_options({"source": "a1"})

    assert len(options["steps"]) == 1
    assert options["steps"][0]["zone"] == "hand"
    assert options["steps"][0]["minimum"] == 1
    assert options["steps"][0]["maximum"] == 1
    assert {item["value"] for item in options["steps"][0]["candidates"]} == set(player.hand)


def test_monsone_keeps_its_two_independent_multiselects() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"player_deck": "animismo_b3_cataclismi"})
    assert session.engine is not None
    player = session.engine.state.players[0]
    spell_uid = _move_named_card_to_hand(session, 0, "Monsone")
    field_uid = next(uid for uid in player.deck if int(session.engine.state.instances[uid].definition.crosses or 99) <= 8)
    player.deck.remove(field_uid)
    player.attack[0] = field_uid

    options = session.play_options({"uid": spell_uid})

    assert options["formatter"] == "monsone"
    assert [step["key"] for step in options["steps"]] == ["discard", "return"]
    assert options["steps"][0]["maximum"] <= 3
    assert field_uid in {item["value"] for item in options["steps"][1]["candidates"]}


def test_sacrifice_play_exposes_exact_candidates_and_preserves_placement() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    player = session.engine.state.players[0]
    brigante_uid = _move_named_card_to_hand(session, 0, "Brigante")
    sacrifice_uid = next(
        uid for uid in player.deck
        if session.engine.state.instances[uid].definition.card_type.lower() == "santo"
    )
    player.deck.remove(sacrifice_uid)
    player.attack[0] = sacrifice_uid

    options = session.play_options({"uid": brigante_uid, "placement": "a2"})

    assert options["formatter"] == "sacrifice"
    assert options["placement"] == "a2"
    step = options["steps"][-1]
    assert step["key"] == "sacrifice"
    assert step["minimum"] == step["maximum"] == 1
    assert sacrifice_uid in {item["value"] for item in step["candidates"]}


def test_runtime_reveal_choice_is_exposed_and_resumed() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    player = session.engine.state.players[0]
    candidate = player.hand[0]
    reveal = player.hand[1]
    flags = session.engine.state.flags
    flags.update({
        "_runtime_waiting_for_reveal": True,
        "_runtime_reveal_card": reveal,
        "_runtime_choice_source": reveal,
        "_runtime_choice_owner": "0",
        "_runtime_choice_candidates": candidate,
        "_runtime_choice_min_targets": "1",
        "_runtime_choice_max_targets": "1",
        "_runtime_choice_title": "Scelta test",
    })
    decision = session.snapshot()["game"]["decision"]
    assert decision["source"] == "runtime"
    assert decision["options"][0]["value"] == candidate

    with patch.object(runtime_cards, "resume_pending_effect") as resume:
        result = session.resolve_decision({"id": decision["id"], "answer": candidate})
    resume.assert_called_once_with(session.engine)
    assert result["ok"] is True
    assert flags["_runtime_choice_selected"] == candidate


def test_chain_priority_is_paced_between_ai_and_player() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    session.engine.state.phase = "active"
    opponent = session.engine.state.players[1]
    quick_uid = next(
        uid for uid, instance in session.engine.state.instances.items()
        if instance.owner == 1 and instance.definition.card_type.lower() in {"benedizione", "maledizione"}
    )
    for zone in (opponent.deck, opponent.white_deck, opponent.graveyard, opponent.excommunicated, opponent.hand):
        if quick_uid in zone:
            zone.remove(quick_uid)
    opponent.hand.append(quick_uid)
    player = session.engine.state.players[0]
    player_quick = next(
        uid for uid, instance in session.engine.state.instances.items()
        if instance.owner == 0 and instance.definition.card_type.lower() in {"benedizione", "maledizione"}
    )
    for zone in (player.deck, player.white_deck, player.graveyard, player.excommunicated, player.hand):
        if player_quick in zone:
            zone.remove(player_quick)
    player.hand.append(player_quick)
    session._start_chain(0)

    waiting = session.snapshot()
    assert waiting["game"]["chain"]["active"] is True
    assert waiting["game"]["chain"]["priority"] == 0
    assert waiting["game"]["ai_pending"] is False

    passed_first_priority = session.action({"type": "chain_pass"})
    assert passed_first_priority["game"]["ai_pending"] is True

    with patch.object(session.engine, "quick_play", return_value=SimpleNamespace(ok=True, message="Risposta rapida.")):
        answered = session.ai_step()
    assert answered["game"]["chain"]["priority"] == 0
    assert answered["game"]["can_act"] is True

    passed = session.action({"type": "chain_pass"})
    assert passed["game"]["ai_pending"] is True
    with patch.object(session.engine, "quick_play", return_value=SimpleNamespace(ok=False, message="Non valida.")):
        resolved = session.ai_step()
    assert resolved["game"]["chain"]["active"] is False


def test_chain_can_be_disabled_and_reenabled_from_topbar_setting() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    session.engine.state.phase = "active"
    opponent = session.engine.state.players[1]
    quick_uid = next(
        uid for uid, instance in session.engine.state.instances.items()
        if instance.owner == 1 and instance.definition.card_type.lower() in {"benedizione", "maledizione"}
    )
    for zone in (opponent.deck, opponent.white_deck, opponent.graveyard, opponent.excommunicated, opponent.hand):
        if quick_uid in zone:
            zone.remove(quick_uid)
    opponent.hand.append(quick_uid)

    disabled = session.action({"type": "set_chain", "enabled": False})
    assert disabled["game"]["chain"]["enabled"] is False
    session._start_chain(0)
    assert session.chain_active is True
    assert session.chain_priority_idx == 1

    session.chain_active = False
    session.chain_participants = []
    session.action({"type": "set_chain", "enabled": False}, network_actor_idx=1)
    session._start_chain(0)
    assert session.chain_active is False

    session.engine.state.active_player = 1
    session._start_chain(1)
    assert session.chain_active is False

    session.action({"type": "set_chain", "enabled": True}, network_actor_idx=1)
    session._start_chain(0)
    assert session.chain_active is True
    assert session.chain_priority_idx == 1


def test_chain_never_opens_during_preparation() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    assert session.engine.state.phase == "preparation"
    for player_idx in (0, 1):
        player = session.engine.state.players[player_idx]
        quick_uid = next(
            uid for uid, instance in session.engine.state.instances.items()
            if instance.owner == player_idx
            and instance.definition.card_type.lower() in {"benedizione", "maledizione"}
        )
        for zone in (player.deck, player.white_deck, player.graveyard, player.excommunicated, player.hand):
            if quick_uid in zone:
                zone.remove(quick_uid)
        player.hand.append(quick_uid)

    session._start_chain(0)
    assert session.chain_active is False


def test_preparation_resolves_own_automatic_effects_but_isolates_opponent_side() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    assert session.engine is not None
    engine = session.engine
    engine.state.active_player = 0
    assert engine.state.phase == "preparation"

    own_source = next(uid for uid, inst in engine.state.instances.items() if inst.owner == 0)
    own_target = next(uid for uid, inst in engine.state.instances.items() if inst.owner == 0 and uid != own_source)
    enemy_target = next(uid for uid, inst in engine.state.instances.items() if inst.owner == 1)
    own_before = engine.state.instances[own_target].current_faith or 0
    enemy_before = engine.state.instances[enemy_target].current_faith or 0

    # Mandatory effects on the preparing player's own side still resolve.
    runtime_cards._apply_effect(  # noqa: SLF001
        engine,
        0,
        own_source,
        [own_target],
        EffectSpec(action="increase_faith", amount=2),
    )
    assert engine.state.instances[own_target].current_faith == own_before + 2

    # The same automatic resolution cannot touch a hidden opposing card or
    # apply an opponent-scoped player effect during preparation.
    runtime_cards._apply_effect(  # noqa: SLF001
        engine,
        0,
        own_source,
        [enemy_target],
        EffectSpec(action="increase_faith", amount=2),
    )
    runtime_cards._apply_effect(  # noqa: SLF001
        engine,
        0,
        own_source,
        [],
        EffectSpec(action="inflict_sin", amount=3, target_player="opponent"),
    )
    assert engine.state.instances[enemy_target].current_faith == enemy_before
    assert engine.state.players[1].sin == 0

    candidates = runtime_cards._collect_selectable_targets_for_manual_target(  # noqa: SLF001
        engine,
        0,
        TargetSpec(type="cards_controlled_by_owner", owner="both", zone="field"),
    )
    assert all(engine.state.instances[uid].owner == 0 for uid in candidates)
    assert runtime_cards._collect_selectable_targets_for_manual_target(  # noqa: SLF001
        engine,
        0,
        TargetSpec(type="cards_controlled_by_owner", owner="opponent", zone="field"),
    ) == []
    assert runtime_cards._eval_condition_node(  # noqa: SLF001
        RuleEventContext(engine=engine, player_idx=0, event="on_enter", payload={}),
        0,
        {"my_saints_lt_opponent": True},
    ) is False


def test_opponent_permanents_do_not_trigger_during_hidden_preparation() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"opponent_deck": "phdk_b1_volere"})
    assert session.engine is not None
    engine = session.engine
    engine.state.active_player = 0
    opponent_source = next(
        uid for uid, inst in engine.state.instances.items()
        if inst.owner == 1 and inst.definition.name == "Volere di Ph"
    )
    drawn_uid = engine.state.players[0].hand[0]
    runtime_cards.on_enter_bind_triggers(engine, 1, opponent_source)

    engine._emit_event("on_card_drawn", 0, card=drawn_uid, player=0)

    assert engine.state.players[0].sin == 0


def test_cataclisma_ciclico_forces_owner_target_choice_even_with_chain_disabled() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"player_deck": "animismo_b3_cataclismi"})
    assert session.engine is not None
    engine = session.engine
    owner = engine.state.players[0]
    opponent = engine.state.players[1]
    cataclisma_uid = next(
        uid for uid, instance in engine.state.instances.items()
        if instance.owner == 0 and instance.definition.name == "Cataclisma Ciclico"
    )
    own_saint = next(uid for uid in owner.deck if engine.state.instances[uid].definition.card_type.lower() == "santo")
    opponent_saint = next(uid for uid in opponent.deck if engine.state.instances[uid].definition.card_type.lower() == "santo")
    for uid, player in ((cataclisma_uid, owner), (own_saint, owner), (opponent_saint, opponent)):
        for zone in (player.deck, player.white_deck, player.hand, player.graveyard, player.excommunicated):
            if uid in zone:
                zone.remove(uid)
    owner.artifacts[0] = cataclisma_uid
    owner.attack[0] = own_saint
    opponent.attack[0] = opponent_saint
    owner.sin = 5
    runtime_cards.on_enter_bind_triggers(engine, 0, cataclisma_uid)
    session.action({"type": "set_chain", "enabled": False})

    waiting = session._run_and_snapshot(lambda: engine._emit_event("on_my_turn_start", 0, player=0))

    decision = waiting["game"]["decision"]
    assert waiting["game"]["chain"]["enabled"] is False
    assert decision["title"] == "Cataclisma Ciclico"
    assert {option["value"] for option in decision["options"]} == {own_saint, opponent_saint}
    assert opponent.attack[0] == opponent_saint  # no auto-target before the answer

    resolved = session.resolve_decision({"id": decision["id"], "answer": opponent_saint})

    assert resolved["ok"] is True
    assert opponent_saint in opponent.graveyard
    assert owner.sin == 4


def test_cataclisma_ciclico_destroys_itself_when_no_saints_exist() -> None:
    session = WebGameSession(Path("holywar/data/cards.json"), seed=11)
    session.new_game({"player_deck": "animismo_b3_cataclismi"})
    assert session.engine is not None
    engine = session.engine
    owner = engine.state.players[0]
    cataclisma_uid = next(
        uid for uid, instance in engine.state.instances.items()
        if instance.owner == 0 and instance.definition.name == "Cataclisma Ciclico"
    )
    if cataclisma_uid in owner.deck:
        owner.deck.remove(cataclisma_uid)
    owner.artifacts[0] = cataclisma_uid
    for player in engine.state.players:
        player.attack = [None, None, None]
        player.defense = [None, None, None]
    runtime_cards.on_enter_bind_triggers(engine, 0, cataclisma_uid)

    engine._emit_event("on_my_turn_start", 0, player=0)

    assert owner.artifacts[0] is None
    assert cataclisma_uid in owner.graveyard
