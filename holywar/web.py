from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from holywar.ai.simple_ai import choose_action
from holywar.app_paths import appdata_dir, bundled_data_dir, bundled_project_root, local_appdata_dir
from holywar.core.engine import GameEngine
from holywar.core.state import CardInstance, PlayerState
from holywar.data.deck_builder import (
    available_premade_decks,
    available_religions,
    delete_runtime_deck,
    export_runtime_decks,
    import_runtime_deck_documents,
    max_copies_for_crosses,
    register_premades_from_json,
    runtime_premade_decks,
    save_runtime_deck,
    validate_deck_cards,
)
from holywar.data.importer import load_cards_json
from holywar.effects.runtime import runtime_cards
from holywar.effects.runtime import CardFilterSpec, TargetSpec
from holywar.effects.library import resolve_card_effect
from holywar.scripting_api import RuleEventContext
from holywar.multiplayer.service import MultiplayerService


DEFAULT_PLAYER_DECK = "cristianesimo_b3_creatore"
DEFAULT_AI_DECK = "cristianesimo_b1_sigilli_martirio"


class WebGameSession:
    """Single local match shared by the local browser UI."""

    def __init__(self, cards_path: Path, seed: int | None = None, *, autoload: bool = True) -> None:
        self.cards = load_cards_json(cards_path)
        self.seed = seed
        self.rng = random.Random(seed)
        self.engine: GameEngine | None = None
        self.mode = "ai"
        self.ai_steps = 0
        self.chain_active = False
        self._chain_enabled = [True, True]
        self.chain_participants: list[int] = []
        self.chain_priority_idx = 0
        self.chain_pass_count = 0
        self.post_runtime_chain_actor: int | None = None
        self.lock = threading.RLock()
        self.operation_condition = threading.Condition()
        self.operation_thread: threading.Thread | None = None
        self.operation_result: Any = None
        self.operation_done = False
        self.operation_error: Exception | None = None
        self.pending_decision: dict[str, Any] | None = None
        self.decision_answer: Any = None
        self._decision_waiting = object()
        self.decision_counter = 0
        self.coin_toss_pending = False
        self.coin_toss_confirmed: set[int] = set()
        if autoload:
            self.new_game({})

    @property
    def chain_enabled(self) -> bool:
        """Compatibility view for callers that predate per-player chain settings."""
        return bool(self._chain_enabled[0])

    @chain_enabled.setter
    def chain_enabled(self, enabled: bool) -> None:
        self._chain_enabled = [bool(enabled), bool(enabled)]

    def _bind_choices(self) -> None:
        if self.engine is None:
            return
        self.engine.choose_auto_play_drawn_card = self._choose_auto_play_drawn_card
        # The legacy GUI intentionally chose the first slot for draw-triggered
        # auto-play to avoid recursive prompt loops. Preserve that behavior.
        self.engine.choose_auto_play_slot_from_draw = lambda _player, _uid, slots: slots[0] if slots else None
        self.engine.choose_summon_slot = self._choose_summon_slot
        self.engine.choose_battle_survival_from_graveyard = self._choose_battle_survival

    def _is_ai_player(self, player_idx: int) -> bool:
        return self.mode == "ai" and player_idx == 1

    def _request_decision(
        self,
        *,
        player_idx: int,
        kind: str,
        title: str,
        prompt: str,
        options: list[dict[str, Any]],
        minimum: int = 1,
        maximum: int = 1,
        allow_cancel: bool = False,
        card_uid: str | None = None,
    ) -> Any:
        if self._is_ai_player(player_idx):
            if kind == "confirm":
                return True
            return options[0]["value"] if options else None
        # Callbacks are normally reached inside an asynchronous web operation.
        # Retain a deterministic fallback for startup-only engine hooks.
        if threading.current_thread() is not self.operation_thread:
            if kind == "confirm":
                return True
            return options[0]["value"] if options else None
        with self.operation_condition:
            self.decision_counter += 1
            self.pending_decision = {
                "id": self.decision_counter,
                "player_index": player_idx,
                "kind": kind,
                "title": title,
                "prompt": prompt,
                "options": options,
                "minimum": minimum,
                "maximum": maximum,
                "allow_cancel": allow_cancel,
                "card_uid": card_uid,
            }
            self.decision_answer = self._decision_waiting
            self.operation_condition.notify_all()
            while self.decision_answer is self._decision_waiting:
                self.operation_condition.wait()
            answer = self.decision_answer
            self.pending_decision = None
            self.decision_answer = None
            self.operation_condition.notify_all()
            return answer

    def _choose_auto_play_drawn_card(self, player_idx: int, source_uid: str) -> bool:
        assert self.engine is not None
        inst = self.engine.state.instances.get(source_uid)
        card_name = inst.definition.name if inst is not None else "questa carta"
        return bool(
            self._request_decision(
                player_idx=player_idx,
                kind="confirm",
                title="Effetto di Nun",
                prompt=f"Vuoi evocare subito {card_name}?",
                options=[{"value": True, "label": "Evoca"}, {"value": False, "label": "Lascia in mano"}],
                minimum=1,
                maximum=1,
                card_uid=source_uid,
            )
        )

    def _choose_summon_slot(self, player_idx: int, source_uid: str, slots: list[str]) -> str | None:
        options = [{"value": slot, "label": self._slot_label(slot)} for slot in slots]
        answer = self._request_decision(
            player_idx=player_idx,
            kind="single",
            title="Scegli locazione evocazione",
            prompt="Seleziona dove evocare la carta.",
            options=options,
            card_uid=source_uid,
        )
        return str(answer) if answer else None

    def _choose_battle_survival(self, player_idx: int, source_uid: str, choices: list[str]) -> str | None:
        assert self.engine is not None
        source = self.engine.state.instances.get(source_uid)
        source_name = source.definition.name if source is not None else "questa carta"
        wants = self._request_decision(
            player_idx=player_idx,
            kind="confirm",
            title="Effetto di sopravvivenza",
            prompt=f"{source_name} e stato sconfitto. Vuoi annullare la distruzione?",
            options=[{"value": True, "label": "Attiva"}, {"value": False, "label": "Non attivare"}],
            card_uid=source_uid,
        )
        if not wants:
            return None
        options = [self._candidate_option(uid, player_idx) for uid in choices]
        answer = self._request_decision(
            player_idx=player_idx,
            kind="single",
            title="Scegli carta da scomunicare",
            prompt="Seleziona la carta del cimitero da scomunicare.",
            options=options,
            card_uid=source_uid,
        )
        return str(answer) if answer else None

    def _slot_label(self, token: str) -> str:
        value = str(token).strip().lower()
        if value.startswith("a") and value[1:].isdigit():
            return f"Attacco {value[1:]}"
        if value.startswith("d") and value[1:].isdigit():
            return f"Difesa {value[1:]}"
        if value.startswith("r") and value[1:].isdigit():
            return f"Artefatto {value[1:]}"
        if value == "b":
            return "Edificio"
        return value.upper()

    def _execute_operation(self, operation: Any) -> tuple[bool, str]:
        with self.operation_condition:
            if self.operation_thread is not None and self.operation_thread.is_alive():
                return (False, "Completa prima la scelta in corso.")
            self.operation_result = None
            self.operation_done = False
            self.operation_error = None
            self.pending_decision = None

            def worker() -> None:
                try:
                    result = operation()
                    self._settle_ai_runtime_choices()
                    with self.operation_condition:
                        self.operation_result = result
                        self.operation_done = True
                        self.operation_condition.notify_all()
                except Exception as exc:  # surfaced to the local UI
                    with self.operation_condition:
                        self.operation_error = exc
                        self.operation_condition.notify_all()

            self.operation_thread = threading.Thread(target=worker, name="holywar-web-operation", daemon=True)
            self.operation_thread.start()
            self.operation_condition.wait_for(
                lambda: self.pending_decision is not None
                or self.operation_done
                or self.operation_error is not None,
                timeout=15,
            )
            return self._operation_status()

    def _operation_status(self) -> tuple[bool, str]:
        if self.pending_decision is not None:
            return (True, "Scelta richiesta.")
        if self.operation_error is not None:
            error = self.operation_error
            self.operation_error = None
            self.operation_thread = None
            return (False, f"Errore durante la risoluzione: {error}")
        result = self.operation_result
        self.operation_result = None
        self.operation_done = False
        self.operation_thread = None
        if result is None:
            return (True, "")
        return (bool(getattr(result, "ok", True)), str(getattr(result, "message", result or "")))

    def resolve_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("id", "")).startswith("runtime:"):
            return self.resolve_runtime_decision(payload)
        with self.lock:
            with self.operation_condition:
                pending = self.pending_decision
                if pending is None:
                    return self.snapshot(ok=False, message="Nessuna scelta in attesa.")
                if int(payload.get("id", -1)) != int(pending["id"]):
                    return self.snapshot(ok=False, message="Questa scelta non e piu valida.")
                answer = payload.get("answer")
                self.decision_answer = answer
                self.operation_condition.notify_all()
                previous_id = int(pending["id"])
                self.operation_condition.wait_for(
                    lambda: self.operation_error is not None
                    or self.operation_done
                    or (
                        self.pending_decision is not None
                        and int(self.pending_decision["id"]) != previous_id
                    ),
                    timeout=15,
                )
                ok, message = self._operation_status()
                return self.snapshot(ok=ok, message=message)

    def new_game(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            mode = str(payload.get("mode") or "ai").strip().lower()
            if mode not in {"ai", "local", "online"}:
                raise ValueError("Modalita sconosciuta.")
            self.mode = mode
            p1_deck = self._resolve_deck_id(payload.get("player_deck"), DEFAULT_PLAYER_DECK)
            p2_deck = self._resolve_deck_id(payload.get("opponent_deck"), DEFAULT_AI_DECK, offset=1)
            p1_name = str(payload.get("player_name") or "Pellegrino").strip() or "Pellegrino"
            default_p2_name = "Custode" if mode == "ai" else "Giocatore 2"
            p2_name = str(payload.get("opponent_name") or default_p2_name).strip() or default_p2_name
            self.engine = GameEngine.create_new(
                cards=self.cards,
                p1_name=p1_name,
                p2_name=p2_name,
                p1_expansion=self._deck_religion(p1_deck),
                p2_expansion=self._deck_religion(p2_deck),
                p1_premade_deck_id=p1_deck,
                p2_premade_deck_id=p2_deck,
                seed=self.seed,
            )
            self.rng = random.Random(self.seed)
            self.ai_steps = 0
            self.chain_active = False
            self._chain_enabled = [bool(payload.get("chain_enabled", True)), True]
            self.chain_participants = []
            self.chain_priority_idx = 0
            self.chain_pass_count = 0
            self.post_runtime_chain_actor = None
            self.coin_toss_pending = False
            self.coin_toss_confirmed.clear()
            self._bind_choices()
            self.engine.start_turn()
            return self.snapshot(message="Nuova partita avviata.")

    def test_editor(self) -> dict[str, Any]:
        unique: dict[str, Any] = {}
        for card in self.cards:
            key = card.name.strip().casefold()
            if key and key not in unique:
                unique[key] = card
        return {
            "cards": [
                {
                    **card.to_dict(),
                    "max_copies": (99 if card.card_type.strip().lower() == "token" else max_copies_for_crosses(card.crosses)),
                }
                for card in sorted(unique.values(), key=lambda item: item.name.casefold())
            ],
            "zones": {
                "deck": None, "hand": None, "graveyard": None, "excommunicated": None,
                "attack": 3, "defense": 3, "artifacts": 4, "building": 1,
                "innate": 1,
            },
        }

    def start_test_game(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            mode = str(payload.get("mode") or "ai").strip().lower()
            if mode not in {"ai", "local"}:
                raise ValueError("Modalita test sconosciuta.")
            active_player = int(payload.get("active_player", 0))
            if active_player not in {0, 1}:
                raise ValueError("Giocatore iniziale non valido.")
            raw_players = payload.get("players")
            if not isinstance(raw_players, list) or len(raw_players) != 2:
                raise ValueError("Configura entrambi i lati della partita.")

            by_name = {card.name.strip().casefold(): card for card in self.cards}
            instance_counter = 0
            instances: dict[str, CardInstance] = {}
            innate_uids: dict[int, list[str]] = {0: [], 1: []}

            def create_instance(name: str, owner: int) -> str:
                nonlocal instance_counter
                definition = by_name.get(str(name or "").strip().casefold())
                if definition is None:
                    raise ValueError(f"Carta non trovata: {name}")
                instance_counter += 1
                uid = f"test{instance_counter:05d}"
                copied = type(definition).from_dict(definition.to_dict())
                instances[uid] = CardInstance(
                    uid=uid, definition=copied, owner=owner,
                    current_faith=copied.faith if copied.faith is not None else None,
                )
                return uid

            def names(raw: Any) -> list[str]:
                if not isinstance(raw, list):
                    return []
                return [str(value).strip() for value in raw if str(value).strip()]

            def slot_names(raw: Any, limit: int) -> list[str | None]:
                values = raw if isinstance(raw, list) else []
                if len(values) > limit:
                    raise ValueError("Una zona del terreno contiene troppe carte.")
                out: list[str | None] = []
                for value in values:
                    name = str(value or "").strip()
                    out.append(name or None)
                return out + [None] * (limit - len(out))

            def build_player(owner: int, raw: Any) -> PlayerState:
                if not isinstance(raw, dict):
                    raise ValueError("Configurazione lato non valida.")
                player = PlayerState.empty(str(raw.get("name") or ("Pellegrino" if owner == 0 else "Custode")))
                collections = {
                    "deck": names(raw.get("deck")),
                    "hand": names(raw.get("hand")),
                    "graveyard": names(raw.get("graveyard")),
                    "excommunicated": names(raw.get("excommunicated")),
                }
                slots = {
                    "attack": slot_names(raw.get("attack"), 3),
                    "defense": slot_names(raw.get("defense"), 3),
                    "artifacts": slot_names(raw.get("artifacts"), 4),
                    "building": slot_names(raw.get("building"), 1),
                    "innate": slot_names(raw.get("innate"), 1),
                }

                all_names = [name for group in (*collections.values(), *slots.values()) for name in group if name]
                counts: dict[str, int] = {}
                for name in all_names:
                    card = by_name.get(name.casefold())
                    if card is None:
                        raise ValueError(f"Carta non trovata: {name}")
                    key = card.name.casefold()
                    counts[key] = counts.get(key, 0) + 1
                    maximum = 99 if card.card_type.strip().lower() == "token" else max_copies_for_crosses(card.crosses)
                    if counts[key] > maximum:
                        raise ValueError(f"{card.name}: {counts[key]} copie (max {maximum}).")

                for zone, zone_names in collections.items():
                    setattr(player, zone, [create_instance(name, owner) for name in zone_names])
                for zone in ("attack", "defense", "artifacts"):
                    zone_uids: list[str | None] = []
                    expected = {"attack": {"santo", "token"}, "defense": {"santo", "token"}, "artifacts": {"artefatto"}}[zone]
                    for name in slots[zone]:
                        if name is None:
                            zone_uids.append(None)
                            continue
                        card = by_name[name.casefold()]
                        if card.card_type.strip().lower() not in expected:
                            raise ValueError(f"{card.name} non puo essere inserita in {zone}.")
                        zone_uids.append(create_instance(name, owner))
                    setattr(player, zone, zone_uids)
                if slots["building"]:
                    building_name = slots["building"][0]
                    if building_name is not None:
                        card = by_name[building_name.casefold()]
                        if card.card_type.strip().lower() != "edificio":
                            raise ValueError(f"{card.name} non e un Edificio.")
                        player.building = create_instance(card.name, owner)
                innate_name = slots["innate"][0]
                if innate_name is not None:
                    card = by_name[innate_name.casefold()]
                    if card.card_type.strip().lower() != "innata":
                        raise ValueError(f"{card.name} non e una carta Innata.")
                    innate_uids[owner].append(create_instance(card.name, owner))
                player.sin = max(0, min(99, int(raw.get("sin", 0) or 0)))
                return player

            p1 = build_player(0, raw_players[0])
            p2 = build_player(1, raw_players[1])
            p1_base_deck = self._resolve_deck_id(None, DEFAULT_PLAYER_DECK)
            p2_base_deck = self._resolve_deck_id(None, DEFAULT_AI_DECK, offset=1)
            base = GameEngine.create_new(
                cards=self.cards, p1_name=p1.name, p2_name=p2.name,
                p1_expansion=self._deck_religion(p1_base_deck),
                p2_expansion=self._deck_religion(p2_base_deck),
                p1_premade_deck_id=p1_base_deck,
                p2_premade_deck_id=p2_base_deck, seed=self.seed,
            )
            flags = base.state.flags
            flags.pop("runtime_state", None)
            flags["innate_pending_setup"] = {"0": [], "1": []}
            flags["innate_active_uids"] = {"0": list(innate_uids[0]), "1": list(innate_uids[1])}
            if not bool(payload.get("initial_draw", True)):
                flags["skip_next_draw_phase"] = {"0": active_player == 0, "1": active_player == 1}
            self.engine = GameEngine(
                type(base.state)(
                    players=[p1, p2], instances=instances, active_player=active_player,
                    turn_number=1, phase="test_setup", preparation_turns_done=2,
                    coin_toss_winner=active_player, flags=flags,
                    logs=["Partita di test configurata manualmente."], winner=None,
                ),
                seed=self.seed,
            )
            self.mode = mode
            self.rng = random.Random(self.seed)
            self.ai_steps = 0
            self.chain_active = False
            self._chain_enabled = [True, True]
            self.chain_participants = []
            self.chain_priority_idx = active_player
            self.chain_pass_count = 0
            self.post_runtime_chain_actor = None
            self.coin_toss_pending = False
            self.coin_toss_confirmed.clear()
            self._bind_choices()
            for owner, uids in innate_uids.items():
                for uid in uids:
                    resolve_card_effect(self.engine, owner, uid, None)
                    self.engine.state.log(
                        f"{self.engine.state.players[owner].name} inizia il test con Innata "
                        f"{self.engine.state.instances[uid].definition.name} attiva."
                    )
            ok, message = self._execute_operation(self.engine.start_turn)
            return self.snapshot(ok=ok, message=message or "Partita di test avviata.")

    def _deck_religion(self, deck_id: str) -> str:
        for candidate_id, religion, _name in available_premade_decks():
            if candidate_id == deck_id:
                return religion
        raise ValueError(f"Deck sconosciuto: {deck_id}")

    def _resolve_deck_id(self, requested: object, preferred: str, *, offset: int = 0) -> str:
        deck_ids = [deck_id for deck_id, _religion, _name in available_premade_decks()]
        requested_id = str(requested or "").strip()
        if requested_id in deck_ids:
            return requested_id
        if preferred in deck_ids:
            return preferred
        if not deck_ids:
            raise ValueError("Non ci sono deck disponibili. Creane o importane uno dal Deck Editor.")
        return deck_ids[min(max(0, offset), len(deck_ids) - 1)]

    def config(self) -> dict[str, Any]:
        decks = [
            {"id": deck_id, "religion": religion, "name": name}
            for deck_id, religion, name in available_premade_decks()
        ]
        player_default = self._resolve_deck_id(None, DEFAULT_PLAYER_DECK) if decks else ""
        opponent_default = self._resolve_deck_id(None, DEFAULT_AI_DECK, offset=1) if decks else ""
        return {
            "application": "holywar",
            "decks": decks,
            "modes": [
                {"id": "ai", "name": "Giocatore contro CPU"},
                {"id": "local", "name": "Giocatore contro giocatore (locale)"},
                {"id": "online", "name": "Multiplayer online (Epic Online Services)"},
            ],
            "defaults": {"player_deck": player_default, "opponent_deck": opponent_default},
        }

    def deck_editor(self) -> dict[str, Any]:
        unique: dict[str, Any] = {}
        for card in self.cards:
            key = card.name.strip().casefold()
            if key and key not in unique and card.card_type.strip().lower() != "token":
                unique[key] = card
        catalogue = []
        for card in sorted(unique.values(), key=lambda item: item.name.casefold()):
            catalogue.append({
                **card.to_dict(),
                "max_copies": max_copies_for_crosses(card.crosses),
            })
        decks = runtime_premade_decks()
        for deck in decks:
            deck["cards"] = [{"name": name, "qty": qty} for name, qty in deck.get("cards", [])]
        return {
            "religions": available_religions(self.cards),
            "decks": decks,
            "cards": catalogue,
            "rules": {
                "minimum": 45,
                "band_79": 10,
                "band_10": 3,
                "white": 1,
            },
        }

    def validate_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        entries = payload.get("cards", [])
        if not isinstance(entries, list):
            raise ValueError("Elenco carte non valido.")
        return validate_deck_cards(self.cards, entries)

    def save_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        entries = payload.get("cards", [])
        if not isinstance(entries, list):
            raise ValueError("Elenco carte non valido.")
        with self.lock:
            deck = save_runtime_deck(
                self.cards,
                deck_id=str(payload.get("id") or "").strip() or None,
                name=str(payload.get("name") or ""),
                religion=str(payload.get("religion") or ""),
                entries=entries,
            )
            return {"ok": True, "message": "Deck salvato.", "deck": deck, "editor": self.deck_editor(), "config": self.config()}

    def delete_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        deck_id = str(payload.get("id") or "").strip()
        if not deck_id:
            raise ValueError("Deck non specificato.")
        with self.lock:
            if not delete_runtime_deck(deck_id):
                raise ValueError("Deck non trovato.")
            return {"ok": True, "message": "Deck eliminato.", "editor": self.deck_editor(), "config": self.config()}

    def export_decks(self, payload: dict[str, Any]) -> dict[str, Any]:
        deck_ids = payload.get("deck_ids", [])
        if not isinstance(deck_ids, list):
            raise ValueError("Selezione deck non valida.")
        document = export_runtime_decks([str(deck_id) for deck_id in deck_ids])
        count = len(document["decks"])
        filename = "holywar-deck.json" if count == 1 else f"holywar-{count}-decks.json"
        return {"ok": True, "filename": filename, "document": document}

    def import_decks(self, payload: dict[str, Any]) -> dict[str, Any]:
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            raise ValueError("Documenti di importazione non validi.")
        with self.lock:
            report = import_runtime_deck_documents(self.cards, documents)
            imported_count = len(report["imported"])
            skipped_count = len(report["skipped"])
            error_count = len(report["errors"])
            message = f"Importati {imported_count} deck"
            if skipped_count:
                message += f", {skipped_count} duplicati ignorati"
            if error_count:
                message += f", {error_count} non validi"
            return {
                "ok": imported_count > 0 or (skipped_count > 0 and error_count == 0),
                "message": message + ".",
                "report": report,
                "editor": self.deck_editor(),
                "config": self.config(),
            }

    def _card(
        self,
        uid: str | None,
        *,
        hidden: bool = False,
        hand_owner: int | None = None,
    ) -> dict[str, Any] | None:
        if not uid or self.engine is None:
            return None
        if hidden:
            return {"uid": uid, "hidden": True}
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return None
        definition = inst.definition
        script = runtime_cards.get_script(definition.name)
        can_activate = False
        if script and script.on_activate_actions:
            activation_owner = self.engine.state.active_player if script.can_activate_by_any_player else inst.owner
            allowed, activation_reason = runtime_cards.can_activate(self.engine, activation_owner, uid, None)
            reason_key = str(activation_reason or "").lower()
            can_activate = bool(allowed or ("selezionare" in reason_key and "bersaglio" in reason_key))
            if runtime_cards.is_activate_once_per_turn(definition.name):
                can_activate = can_activate and self.engine.can_activate_once_per_turn(uid)
            can_activate = can_activate and activation_owner == self.engine.state.active_player
        play_targeting = str(getattr(script, "play_targeting", "auto") or "auto").strip().lower()
        manual_steps = self._manual_play_steps(uid, hand_owner) if hand_owner is not None else []
        legacy_target_modes = {"own_saint", "opponent_saint", "own_graveyard_saint", "manual", "multi", "custom"}
        play_requires_target = bool(manual_steps) or play_targeting in legacy_target_modes
        play_ready = False
        if script is not None and hand_owner is not None:
            can_play, reason = runtime_cards.can_play(self.engine, hand_owner, uid, None)
            reason_text = str(reason or "").lower()
            # A missing selection means that valid candidates exist: the UI must
            # highlight the card and collect one. An empty candidate pool instead
            # deliberately leaves the card unlit.
            missing_selection = "selezionare" in reason_text and "bersaglio" in reason_text
            play_ready = bool(can_play or missing_selection)
        if definition.card_type.strip().lower() in {"santo", "token"}:
            try:
                strength = self.engine.get_effective_strength(uid)
            except Exception:
                strength = definition.strength
        else:
            strength = definition.strength
        return {
            "uid": uid,
            "name": definition.name,
            "type": definition.card_type,
            "cost": definition.faith,
            "faith": inst.current_faith,
            "base_faith": definition.faith,
            "strength": strength,
            "base_strength": definition.strength,
            "crosses": definition.crosses,
            "effect": definition.effect_text,
            "expansion": definition.expansion,
            "exhausted": inst.exhausted,
            "can_activate": can_activate,
            "play_targeting": play_targeting,
            "play_requires_target": play_requires_target,
            "play_ready": play_ready,
            "blessed": list(inst.blessed),
            "cursed": list(inst.cursed),
        }

    def _dynamic_target_max(self, player_idx: int, rule: dict[str, Any] | None) -> int | None:
        if self.engine is None or not rule:
            return None
        spec = dict(rule.get("count_cards_controlled_by_owner", {}) or {})
        if not spec:
            return None
        raw_filter = dict(spec.get("card_filter", {}) or {})
        target = TargetSpec(
            type="selected_targets",
            zone=str(spec.get("zone", "field")),
            owner=str(spec.get("owner", "me")),
            card_filter=CardFilterSpec(
                name_in=[str(value) for value in raw_filter.get("name_in", []) or []],
                name_equals=raw_filter.get("name_equals"),
                name_contains=raw_filter.get("name_contains"),
                name_not_contains=raw_filter.get("name_not_contains"),
                card_type_in=[str(value) for value in raw_filter.get("card_type_in", []) or []],
                crosses_gte=raw_filter.get("crosses_gte"),
                crosses_lte=raw_filter.get("crosses_lte"),
                strength_gte=raw_filter.get("strength_gte"),
                strength_lte=raw_filter.get("strength_lte"),
            ),
        )
        return len(runtime_cards._collect_selectable_targets_for_manual_target(self.engine, player_idx, target))  # noqa: SLF001

    def _candidate_label(self, uid: str, viewer_idx: int) -> str:
        assert self.engine is not None
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return uid
        player = self.engine.state.players[inst.owner]
        side = "Tuo" if inst.owner == viewer_idx else "Avversario"
        if uid in player.deck:
            zone = "Reliquiario"
        elif uid in player.hand:
            zone = "Mano"
        elif uid in player.graveyard:
            zone = "Cimitero"
        elif uid in player.excommunicated:
            zone = "Scomunicate"
        elif uid in player.attack:
            zone = f"Attacco {player.attack.index(uid) + 1}"
        elif uid in player.defense:
            zone = f"Difesa {player.defense.index(uid) + 1}"
        elif uid in player.artifacts:
            zone = f"Artefatto {player.artifacts.index(uid) + 1}"
        elif player.building == uid:
            zone = "Edificio"
        else:
            zone = "Zona effetto"
        return f"{inst.definition.name} · {side} {zone}"

    def _candidate_option(self, uid: str, viewer_idx: int) -> dict[str, Any]:
        """Return both the target label and the complete public card preview."""
        return {
            "value": uid,
            "label": self._candidate_label(uid, viewer_idx),
            "card": self._card(uid),
        }

    def _definition_preview(self, card_name: str) -> dict[str, Any] | None:
        wanted = str(card_name or "").strip().casefold()
        definition = next((card for card in self.cards if card.name.strip().casefold() == wanted), None)
        if definition is None:
            return None
        return {
            "uid": None,
            "name": definition.name,
            "type": definition.card_type,
            "cost": definition.faith,
            "faith": definition.faith,
            "strength": definition.strength,
            "crosses": definition.crosses,
            "effect": definition.effect_text,
            "expansion": definition.expansion,
        }

    def _pending_slot_summon_name(self, source_uid: str) -> str:
        """Describe a slot picker without changing how the effect is resolved."""
        if self.engine is None:
            return ""
        source = self.engine.state.instances.get(source_uid)
        script = runtime_cards.get_script(source.definition.name) if source is not None else None
        if script is None:
            return ""

        flags = self.engine.state.flags
        mode = str(flags.get("_runtime_pending_mode", "")).strip().lower()
        try:
            action_index = int(str(flags.get("_runtime_action_index_resume", "0")) or "0")
        except ValueError:
            action_index = 0
        action_groups = {
            "play": list(script.on_play_actions or []),
            "enter": list(script.on_enter_actions or []),
            "activate": list(script.on_activate_actions or []),
        }
        names: list[str] = []
        current_actions = action_groups.get(mode, [])
        for action in current_actions[action_index + 1:]:
            effect = action.effect
            if str(effect.action or "").strip().lower() == "summon_generated_token" and str(effect.position or "").strip().lower() == "selected_target_slot":
                if str(effect.card_name or "").strip():
                    names.append(str(effect.card_name).strip())
                break

        if not names:
            for actions in action_groups.values():
                for action in actions:
                    effect = action.effect
                    if str(effect.action or "").strip().lower() == "summon_generated_token" and str(effect.position or "").strip().lower() == "selected_target_slot":
                        if str(effect.card_name or "").strip():
                            names.append(str(effect.card_name).strip())
            for triggered in script.triggered_effects or []:
                effect = triggered.effect
                if str(effect.action or "").strip().lower() == "summon_generated_token" and str(effect.position or "").strip().lower() == "selected_target_slot":
                    if str(effect.card_name or "").strip():
                        names.append(str(effect.card_name).strip())
        unique_names = list(dict.fromkeys(names))
        return unique_names[0] if len(unique_names) == 1 else ""

    def _runtime_card_value(self, uid: str) -> int:
        if self.engine is None:
            return 0
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return 0
        card_type = str(inst.definition.card_type or "").strip().lower()
        faith = int(inst.current_faith or inst.definition.faith or 0)
        try:
            strength = int(self.engine.get_effective_strength(uid))
        except Exception:
            strength = int(inst.definition.strength or 0)
        if card_type in {"santo", "token"}:
            return faith * 5 + strength * 8 + 20
        if card_type == "edificio":
            return faith * 3 + 35
        if card_type == "artefatto":
            return faith * 3 + 25
        if card_type in {"benedizione", "maledizione"}:
            return 16
        return 10

    def _ai_runtime_selection(
        self, owner_idx: int, candidates: list[str], minimum: int, maximum: int, prompt: str, title: str
    ) -> str:
        prompt_key = f"{title} {prompt}".lower()
        harmful = any(key in prompt_key for key in ("cimitero", "distrugg", "scarta", "scomunic", "annulla"))
        beneficial = any(key in prompt_key for key in ("evoca", "aggiung", "cura", "ripristina", "potenz", "guadagn"))
        sacrificial = "sacrific" in prompt_key
        scored: list[tuple[int, str]] = []
        assert self.engine is not None
        for uid in candidates:
            inst = self.engine.state.instances.get(uid)
            if inst is None:
                continue
            same_owner = int(inst.owner) == int(owner_idx)
            value = self._runtime_card_value(uid)
            if sacrificial:
                score = (-value + 200) if same_owner else (value + 50)
            elif harmful:
                score = (value + 500) if not same_owner else (-value + 100)
            elif beneficial:
                score = (value + 500) if same_owner else (-value + 100)
            else:
                score = (value + 120) if not same_owner else (value + 80)
            scored.append((score, uid))
        scored.sort(key=lambda item: item[0], reverse=True)
        ordered = [uid for _score, uid in scored]
        count = max(0, minimum)
        if count == 0 and ordered:
            count = 1
        count = min(count, maximum, len(ordered))
        return ",".join(ordered[:count])

    def _runtime_decision(self) -> dict[str, Any] | None:
        if self.engine is None:
            return None
        flags = self.engine.state.flags
        if not bool(flags.get("_runtime_waiting_for_reveal")):
            return None
        reveal_uid = str(flags.get("_runtime_reveal_card", "")).strip()
        if not reveal_uid:
            return None
        try:
            owner_idx = int(str(flags.get("_runtime_choice_owner", self.engine.state.active_player)))
        except ValueError:
            owner_idx = self.engine.state.active_player
        title = str(flags.get("_runtime_choice_title", "Carta rivelata")) or "Carta rivelata"
        prompt = str(flags.get("_runtime_choice_prompt", "")).strip()
        candidates = [value for value in str(flags.get("_runtime_choice_candidates", "")).split(";;") if value]
        values = [value for value in str(flags.get("_runtime_choice_values", "")).split(";;") if value]
        try:
            labels = json.loads(str(flags.get("_runtime_choice_labels", "{}")))
        except (TypeError, ValueError, json.JSONDecodeError):
            labels = {}
        minimum = int(str(flags.get("_runtime_choice_min_targets", "0")) or "0")
        maximum = int(str(flags.get("_runtime_choice_max_targets", "1")) or "1")
        source = str(flags.get("_runtime_choice_source", reveal_uid))
        slot_candidates = bool(candidates) and all(
            len(value) >= 2 and value[:1].lower() in {"a", "d", "r"} and value[1:].isdigit()
            for value in candidates
        )
        summon_name = self._pending_slot_summon_name(source) if slot_candidates else ""
        summon_card = self._definition_preview(summon_name) if summon_name else None
        if candidates and summon_card:
            title = f"Evoca {summon_name}"
            prompt = f"Scegli lo slot del terreno in cui evocare {summon_name}."
            options = [
                {"value": token, "label": self._slot_label(token), "card": summon_card, "slot": token}
                for token in candidates
            ]
        elif candidates:
            options = [self._candidate_option(uid, owner_idx) for uid in candidates]
        elif values:
            options = [{"value": value, "label": str(labels.get(value, value))} for value in values]
        else:
            inst = self.engine.state.instances.get(reveal_uid)
            name = inst.definition.name if inst is not None else "la carta"
            prompt = prompt or f"Hai rivelato {name}. Continua la risoluzione dell'effetto."
            options = [{"value": "__continue__", "label": "Continua"}]
            minimum = maximum = 1
        return {
            "id": f"runtime:{source}:{reveal_uid}", "source": "runtime", "player_index": owner_idx,
            "kind": ("summon_slot" if summon_card else ("reveal" if not candidates and not values else ("multi" if maximum != 1 else "single"))),
            "title": title, "prompt": prompt,
            "options": options, "minimum": minimum, "maximum": maximum, "allow_cancel": minimum == 0,
            "card_uid": reveal_uid,
            "revealed_card": (self._card(reveal_uid) if not candidates and not values else None),
            "preserve_order": bool(flags.get("_runtime_choice_preserve_order")),
        }

    def _settle_ai_runtime_choices(self) -> None:
        if self.engine is None:
            return
        for _guard in range(20):
            decision = self._runtime_decision()
            if decision is None or not self._is_ai_player(int(decision["player_index"])):
                break
            options = [str(option["value"]) for option in decision["options"]]
            flags = self.engine.state.flags
            if str(flags.get("_runtime_choice_candidates", "")).strip():
                selected = self._ai_runtime_selection(
                    int(decision["player_index"]), options, int(decision["minimum"]), int(decision["maximum"]),
                    str(decision["prompt"]), str(decision["title"]),
                )
            elif str(flags.get("_runtime_choice_values", "")).strip():
                lowered = [value.lower() for value in options]
                selected = options[lowered.index("si")] if "si" in lowered else (
                    options[lowered.index("yes")] if "yes" in lowered else (options[0] if options else "")
                )
            else:
                selected = ""
            flags["_runtime_choice_selected"] = selected
            flags["_runtime_choice_ready"] = True
            flags["_runtime_waiting_for_reveal"] = False
            flags.pop("_runtime_reveal_card", None)
            runtime_cards.resume_pending_effect(self.engine)
            self.engine.resume_pending_draws()
        if self.post_runtime_chain_actor is not None and self._runtime_decision() is None:
            actor_idx = self.post_runtime_chain_actor
            self.post_runtime_chain_actor = None
            self._start_chain(actor_idx)
        self._continue_deferred_turn_start()

    def _finish_turn_transition(self) -> None:
        """Start the next turn only after mandatory end-turn choices resolve."""
        assert self.engine is not None
        if self._runtime_decision() is not None:
            self.engine.state.flags["_web_start_turn_after_runtime_choice"] = True
            return
        if (
            self.engine.state.preparation_turns_done >= 2
            and self.engine.state.coin_toss_winner in {0, 1}
            and self.engine.state.turn_number == 1
            and str(self.engine.state.flags.get("runtime_state", {}).get("phase", "")) == "setup"
        ):
            self.coin_toss_pending = True
            self.coin_toss_confirmed.clear()
            if self.mode == "ai":
                self.coin_toss_confirmed.add(1)
            return
        if self.mode == "ai":
            self._start_next_turn()
        elif self.engine.state.winner is None:
            self.engine.start_turn()

    def _continue_deferred_turn_start(self) -> None:
        if self.engine is None or self._runtime_decision() is not None:
            return
        if not bool(self.engine.state.flags.pop("_web_start_turn_after_runtime_choice", False)):
            return
        self._finish_turn_transition()

    def resolve_runtime_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            decision = self._runtime_decision()
            if decision is None:
                return self.snapshot(ok=False, message="Nessuna scelta effetto in attesa.")
            if str(payload.get("id", "")) != str(decision["id"]):
                return self.snapshot(ok=False, message="Questa scelta non e piu valida.")
            raw_answer = payload.get("answer")
            answers = raw_answer if isinstance(raw_answer, list) else ([] if raw_answer in {None, ""} else [raw_answer])
            allowed = {str(option["value"]) for option in decision["options"]}
            selected = [str(value) for value in answers if str(value) in allowed]
            if not int(decision["minimum"]) <= len(selected) <= int(decision["maximum"]):
                return self.snapshot(ok=False, message="Numero di scelte non valido.")
            assert self.engine is not None
            flags = self.engine.state.flags
            flags["_runtime_choice_selected"] = ",".join(value for value in selected if value != "__continue__")
            flags["_runtime_choice_ready"] = True
            flags["_runtime_waiting_for_reveal"] = False
            flags.pop("_runtime_reveal_card", None)
            def resume() -> None:
                assert self.engine is not None
                runtime_cards.resume_pending_effect(self.engine)
                self.engine.resume_pending_draws()
                if self.post_runtime_chain_actor is not None and self._runtime_decision() is None:
                    actor_idx = self.post_runtime_chain_actor
                    self.post_runtime_chain_actor = None
                    self._start_chain(actor_idx)
                self._continue_deferred_turn_start()
            return self._run_and_snapshot(resume)

    def _manual_play_steps(self, uid: str, player_idx: int | None) -> list[dict[str, Any]]:
        if self.engine is None or player_idx is None:
            return []
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return []
        script = runtime_cards.get_script(inst.definition.name)
        if script is None:
            return []
        return self._manual_action_steps(uid, player_idx, script.on_play_actions, "on_play")

    def _manual_action_steps(
        self,
        uid: str,
        player_idx: int,
        actions: list[Any],
        event_name: str,
    ) -> list[dict[str, Any]]:
        if self.engine is None or player_idx is None:
            return []
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return []
        steps: list[dict[str, Any]] = []
        context = RuleEventContext(engine=self.engine, event=event_name, player_idx=player_idx, payload={"card": uid})
        for action_idx, action in enumerate(actions):
            target = action.target
            if not runtime_cards._target_requires_manual_selection(target):  # noqa: SLF001
                continue
            if action.condition and not runtime_cards._eval_condition_node(context, player_idx, action.condition):  # noqa: SLF001
                continue
            candidates = runtime_cards._collect_selectable_targets_for_manual_target(  # noqa: SLF001
                self.engine, player_idx, target
            )
            minimum = runtime_cards._required_min_targets_for_manual_target(target)  # noqa: SLF001
            dynamic_max = self._dynamic_target_max(player_idx, target.max_targets_from)
            maximum = dynamic_max if dynamic_max is not None else target.max_targets
            if maximum is None:
                maximum = 1
            steps.append(
                {
                    "action_index": action_idx,
                    "zone": str(target.zone or "field"),
                    "minimum": minimum,
                    "maximum": max(0, int(maximum)),
                    "candidates": [self._candidate_option(candidate, player_idx) for candidate in candidates],
                }
            )
        return steps

    def play_options(self, payload: dict[str, Any], *, network_actor_idx: int | None = None) -> dict[str, Any]:
        with self.lock:
            if self.engine is None:
                raise ValueError("Partita non inizializzata.")
            actor_idx = network_actor_idx if network_actor_idx is not None else (
                self.chain_priority_idx if self.chain_active else (self.engine.state.active_player if self.mode == "local" else 0)
            )
            uid = str(payload.get("uid") or "")
            if uid not in self.engine.state.players[actor_idx].hand:
                raise ValueError("La carta non e nella mano del giocatore attivo.")
            placement = str(payload.get("placement") or "").strip()
            inst = self.engine.state.instances[uid]
            script = runtime_cards.get_script(inst.definition.name)
            steps = self._manual_play_steps(uid, actor_idx)
            formatter = "standard"
            if script is not None and "web_options" in script.targeting_handlers:
                steps = script.targeting_handlers["web_options"](self, uid, actor_idx)
                formatter = "named_steps"
            sacrifice = self._sacrifice_step(uid, actor_idx, script)
            if sacrifice is not None:
                steps.append(sacrifice)
                formatter = "sacrifice"
            return {
                "ok": True, "uid": uid, "steps": steps, "formatter": formatter,
                "placement": placement,
                "target_prefix": script.target_payload_prefix if script else "",
            }


    def _sacrifice_step(self, uid: str, player_idx: int, script: Any) -> dict[str, Any] | None:
        if self.engine is None or script is None:
            return None
        engine = self.engine
        requirement = script.play_requirements.get("can_play_by_sacrificing")
        if not isinstance(requirement, dict) or not script.play_requirements.get("choose_play_sacrifices_from_target"):
            return None
        owner_key = str(requirement.get("owner", "me")).strip().lower()
        owners = [1 - player_idx] if owner_key in {"opponent", "enemy", "other"} else (
            [player_idx, 1 - player_idx] if owner_key in {"any", "both", "all", "either"} else [player_idx]
        )
        zones = list(requirement.get("zones", []) or [requirement.get("zone", "field")])
        card_filter = dict(requirement.get("card_filter", {}) or {})
        equals = str(card_filter.get("name_equals", "")).strip().lower()
        contains = str(card_filter.get("name_contains", "")).strip().lower()
        types = {str(value).strip().lower() for value in card_filter.get("card_type_in", []) or []}

        def zone_uids(owner_idx: int, zone_name: str) -> list[str]:
            player = engine.state.players[owner_idx]
            zone = str(zone_name).strip().lower()
            mapping = {
                "attack": player.attack, "defense": player.defense, "artifact": player.artifacts,
                "artifacts": player.artifacts, "hand": player.hand, "deck": player.deck,
                "relicario": player.deck, "graveyard": player.graveyard,
                "excommunicated": player.excommunicated,
            }
            if zone == "field":
                return [value for value in player.attack + player.defense + player.artifacts + [player.building] if value]
            if zone == "building":
                return [player.building] if player.building else []
            return [value for value in mapping.get(zone, []) if value]

        candidates: list[str] = []
        for owner_idx in owners:
            for zone in zones:
                for candidate in zone_uids(owner_idx, str(zone)):
                    inst = engine.state.instances.get(candidate)
                    if inst is None or candidate == uid or candidate in candidates:
                        continue
                    name = inst.definition.name.strip().lower()
                    card_type = inst.definition.card_type.strip().lower()
                    if equals and name != equals or contains and contains not in name or types and card_type not in types:
                        continue
                    candidates.append(candidate)
        count = max(1, int(requirement.get("count", 1) or 1))
        return {
            "action_index": 0, "key": "sacrifice", "zone": "Sacrificio richiesto",
            "minimum": count, "maximum": count,
            "candidates": [self._candidate_option(candidate, player_idx) for candidate in candidates],
        }

    def activation_options(self, payload: dict[str, Any], *, network_actor_idx: int | None = None) -> dict[str, Any]:
        with self.lock:
            if self.engine is None:
                raise ValueError("Partita non inizializzata.")
            actor_idx = network_actor_idx if network_actor_idx is not None else (
                self.engine.state.active_player if self.mode == "local" else 0
            )
            source = str(payload.get("source") or "")
            uid = self.engine.resolve_board_uid(actor_idx, source)
            if uid is None:
                raise ValueError("La sorgente dell'abilita non e valida.")
            script = runtime_cards.get_script(self.engine.state.instances[uid].definition.name)
            if script is None:
                return {"ok": True, "uid": uid, "source": source, "steps": [], "legacy_requires_target": False}
            mode = str(script.activate_targeting or "auto").strip().lower()
            legacy_requires_target = mode in {"board_card", "own_saint", "opponent_saint", "manual", "multi"}
            return {
                "ok": True,
                "uid": uid,
                "source": source,
                "steps": self._manual_action_steps(uid, actor_idx, script.on_activate_actions, "on_activate"),
                "legacy_requires_target": legacy_requires_target,
            }

    def _player(self, player_idx: int, *, reveal_hand: bool, hide_field: bool = False) -> dict[str, Any]:
        assert self.engine is not None
        player = self.engine.state.players[player_idx]
        promise = dict(self.engine.state.flags.get("deck_graveyard_merge_active", {}) or {})
        attack_cards = [None] * len(player.attack) if hide_field else [self._card(uid) for uid in player.attack]
        defense_cards = [None] * len(player.defense) if hide_field else [self._card(uid) for uid in player.defense]
        if player_idx == self.engine.state.active_player:
            for index, card in enumerate(attack_cards):
                if card is not None:
                    card["attack_targets"] = self._valid_attack_targets(player_idx, index)
            for index, card in enumerate(defense_cards):
                if card is not None:
                    card["attack_targets"] = self._valid_attack_targets(player_idx, -(index + 1))
        return {
            "index": player_idx,
            "name": player.name,
            "sin": player.sin,
            "inspiration": player.inspiration + player.temporary_inspiration,
            "deck_count": len(player.deck),
            "white_deck_count": len(player.white_deck),
            "hand_count": len(player.hand),
            "hand": [
                self._card(uid, hidden=not reveal_hand, hand_owner=player_idx if reveal_hand else None)
                for uid in player.hand
            ],
            "field_hidden": hide_field,
            "graveyard": [] if hide_field else [self._card(uid) for uid in player.graveyard],
            "excommunicated": [] if hide_field else [self._card(uid) for uid in player.excommunicated],
            "graveyard_acts_as_deck": bool(promise.get(str(player_idx), False)),
            "excommunicated_acts_as_deck": False,
            "attack": attack_cards,
            "defense": defense_cards,
            "artifacts": [None] * len(player.artifacts) if hide_field else [self._card(uid) for uid in player.artifacts],
            "building": None if hide_field else self._card(player.building),
        }

    def _valid_attack_targets(self, player_idx: int, from_slot: int) -> list[str]:
        assert self.engine is not None
        engine = self.engine
        state = engine.state
        if state.phase == "preparation" or player_idx != state.active_player:
            return []
        if int(state.flags.get("no_attacks_turn", -1)) == int(state.turn_number):
            return []
        runtime_state = dict(state.flags.get("runtime_state", {}) or {})
        if any(str(uid).strip() for uid in runtime_state.get("no_attacks_until_draw_sources", []) or []):
            return []

        attacker_player = state.players[player_idx]
        defender_idx = 1 - player_idx
        defender = state.players[defender_idx]
        requested_defense = from_slot < 0
        slot_idx = (-from_slot - 1) if requested_defense else from_slot
        if not 0 <= slot_idx < 3:
            return []
        attacker_uid = attacker_player.defense[slot_idx] if requested_defense else attacker_player.attack[slot_idx]
        if attacker_uid is None and not requested_defense:
            attacker_uid = attacker_player.defense[slot_idx]
            requested_defense = True
        if attacker_uid is None:
            return []
        attacker = state.instances[attacker_uid]
        if requested_defense and not runtime_cards.get_can_attack_from_defense(attacker.definition.name):
            return []

        enemy_saints = [uid for uid in defender.attack + defender.defense if uid]
        if not enemy_saints:
            blocked = engine._validate_attack_preconditions(player_idx, defender_idx, attacker_uid, attacker, None)
            return ["direct"] if blocked is None else []

        forced_slots = [
            index for index, uid in enumerate(defender.attack)
            if uid and runtime_cards.get_attack_targeting_mode(state.instances[uid].definition.name) == "must_be_attack_target"
        ]
        targets: list[str] = []
        for target_slot, defender_uid in enumerate(defender.attack):
            if defender_uid is None or (forced_slots and target_slot not in forced_slots):
                continue
            targeting_mode = runtime_cards.get_attack_targeting_mode(state.instances[defender_uid].definition.name)
            if targeting_mode == "untargetable":
                continue
            if targeting_mode == "only_if_no_other_attackers" and any(
                uid for index, uid in enumerate(defender.attack) if index != target_slot
            ):
                continue
            blocked = engine._validate_attack_preconditions(
                player_idx, defender_idx, attacker_uid, attacker, target_slot
            )
            if blocked is None:
                targets.append(f"a{target_slot + 1}")
        return targets

    def _quick_hand_indexes(self, player_idx: int) -> list[int]:
        assert self.engine is not None
        indexes: list[int] = []
        for index, uid in enumerate(self.engine.state.players[player_idx].hand):
            definition = self.engine.state.instances[uid].definition
            if runtime_cards.allows_quick_play(definition.name, definition.card_type):
                indexes.append(index)
        return indexes

    def _default_quick_target(self, player_idx: int, hand_index: int) -> str | None:
        assert self.engine is not None
        player = self.engine.state.players[player_idx]
        inst = self.engine.state.instances[player.hand[hand_index]]
        own_target = runtime_cards.quick_target_owner(inst.effect_name, inst.definition.card_type) == "me"
        target_player = player if own_target else self.engine.state.players[1 - player_idx]
        for index in range(3):
            if target_player.attack[index]:
                return f"a{index + 1}"
            if target_player.defense[index]:
                return f"d{index + 1}"
        if not own_target:
            for index, uid in enumerate(target_player.artifacts):
                if uid:
                    return f"r{index + 1}"
            if target_player.building:
                return "b"
        return None

    def _start_chain(self, actor_idx: int) -> None:
        if (
            self.engine is None
            or self.engine.state.phase == "preparation"
            or self.chain_active
            or self.engine.state.flags.get("_runtime_waiting_for_reveal")
        ):
            return
        turn_owner = int(self.engine.state.active_player)
        participants = [
            player_idx for player_idx in (turn_owner, 1 - turn_owner)
            if self._chain_enabled[player_idx] and self._quick_hand_indexes(player_idx)
        ]
        if not participants:
            return
        self.chain_active = True
        self.chain_participants = participants
        self.chain_priority_idx = participants[0]
        self.chain_pass_count = 0

    def _chain_pass(self) -> str:
        if not self.chain_active:
            return "Nessuna catena attiva."
        self.chain_pass_count += 1
        if self.chain_pass_count >= max(1, len(self.chain_participants)):
            self.chain_active = False
            self.chain_participants = []
            self.chain_pass_count = 0
            return "Catena risolta."
        current = self.chain_participants.index(self.chain_priority_idx)
        self.chain_priority_idx = self.chain_participants[(current + 1) % len(self.chain_participants)]
        return "Priorita passata."

    def _perform_ai_chain_step(self) -> Any:
        assert self.engine is not None
        for hand_index in self._quick_hand_indexes(self.chain_priority_idx):
            target = self._default_quick_target(self.chain_priority_idx, hand_index)
            result = self.engine.quick_play(self.chain_priority_idx, hand_index, target)
            if result.ok:
                self.chain_pass_count = 0
                current = self.chain_participants.index(self.chain_priority_idx)
                self.chain_priority_idx = self.chain_participants[(current + 1) % len(self.chain_participants)]
                return result
        return self._chain_pass()

    def snapshot(
        self,
        *,
        ok: bool = True,
        message: str = "",
        viewer_idx: int | None = None,
        spectator: bool = False,
    ) -> dict[str, Any]:
        if self.engine is None:
            return {"ok": ok, "message": message, "game": None}
        state = self.engine.state
        runtime_state = dict(state.flags.get("runtime_state", {}) or {})
        raw_decision = self.pending_decision or self._runtime_decision()
        if viewer_idx is not None and viewer_idx not in {0, 1}:
            raise ValueError("Indice spettatore non valido.")
        if viewer_idx is None and self.mode == "local":
            if self.coin_toss_pending:
                viewer_idx = next((idx for idx in (0, 1) if idx not in self.coin_toss_confirmed), state.active_player)
            else:
                viewer_idx = int(raw_decision["player_index"]) if raw_decision is not None else (
                    self.chain_priority_idx if self.chain_active else state.active_player
                )
        elif viewer_idx is None:
            viewer_idx = 0
        decision = (
            raw_decision
            if not spectator and raw_decision is not None and int(raw_decision["player_index"]) == viewer_idx
            else None
        )
        opponent_idx = 1 - viewer_idx
        relative_winner = None
        if state.winner is not None:
            relative_winner = 0 if state.winner == viewer_idx else 1
        hide_opponent_field = not spectator and (state.phase == "preparation" or self.coin_toss_pending)
        coin_winner = state.coin_toss_winner if state.coin_toss_winner in {0, 1} else None
        return {
            "ok": ok,
            "message": message,
            "game": {
                "active_player": 0 if state.active_player == viewer_idx else 1,
                "actual_active_player": state.active_player,
                "viewer_index": viewer_idx,
                "mode": self.mode,
                "turn": state.turn_number,
                "phase": runtime_state.get("phase", state.phase),
                "preparation": state.phase == "preparation",
                "winner": relative_winner,
                "spectator": spectator,
                "can_act": not spectator and not self.coin_toss_pending and state.winner is None and (
                    self.chain_active and self.chain_priority_idx == viewer_idx
                    or not self.chain_active and state.active_player == viewer_idx
                ),
                "ai_pending": self.mode == "ai" and not self.coin_toss_pending and state.winner is None and (
                    self.chain_active and self.chain_priority_idx == 1
                    or not self.chain_active and state.active_player == 1
                ),
                "chain": {
                    "active": self.chain_active,
                    "enabled": self._chain_enabled[viewer_idx],
                    "enabled_players": list(self._chain_enabled),
                    "priority": 0 if self.chain_priority_idx == viewer_idx else 1,
                    "passes": self.chain_pass_count,
                    "quick_cards": [state.players[viewer_idx].hand[index] for index in self._quick_hand_indexes(viewer_idx)]
                    if self.chain_active and self.chain_priority_idx == viewer_idx else [],
                },
                "coin_toss": {
                    "pending": self.coin_toss_pending,
                    "confirmed": viewer_idx in self.coin_toss_confirmed,
                    "winner": None if coin_winner is None else (0 if coin_winner == viewer_idx else 1),
                    "winner_name": "" if coin_winner is None else state.players[coin_winner].name,
                },
                "decision": decision,
                "players": [
                    self._player(viewer_idx, reveal_hand=True),
                    self._player(opponent_idx, reveal_hand=spectator, hide_field=hide_opponent_field),
                ],
                "logs": [] if hide_opponent_field else list(state.logs),
            },
        }

    def _result(self, result: Any) -> dict[str, Any]:
        return self.snapshot(ok=bool(result.ok), message=str(result.message))

    def _run_and_snapshot(self, operation: Any) -> dict[str, Any]:
        ok, message = self._execute_operation(operation)
        return self.snapshot(ok=ok, message=message)

    def action(self, payload: dict[str, Any], *, network_actor_idx: int | None = None) -> dict[str, Any]:
        with self.lock:
            if self.engine is None:
                return {"ok": False, "message": "Partita non inizializzata."}
            state = self.engine.state
            kind = str(payload.get("type") or "").strip().lower()
            if kind == "set_chain":
                setting_actor = network_actor_idx if network_actor_idx is not None else (
                    (self.chain_priority_idx if self.chain_active else state.active_player)
                    if self.mode == "local" else 0
                )
                if setting_actor not in {0, 1}:
                    return self.snapshot(ok=False, message="Identita giocatore non valida.")
                enabled = bool(payload.get("enabled"))
                self._chain_enabled[setting_actor] = enabled
                status = "attivata" if enabled else "disattivata"
                if self.chain_active and setting_actor in self.chain_participants and not enabled:
                    return self.snapshot(message=f"Catena {status}. La catena gia aperta deve essere conclusa.")
                return self.snapshot(message=f"Catena {status} per {state.players[setting_actor].name}.")
            if kind == "confirm_coin_toss":
                if not self.coin_toss_pending:
                    return self.snapshot(ok=False, message="Nessun lancio della moneta da confermare.")
                actor_idx = network_actor_idx if network_actor_idx is not None else (
                    next((idx for idx in (0, 1) if idx not in self.coin_toss_confirmed), state.active_player)
                    if self.mode == "local" else 0
                )
                if actor_idx not in {0, 1}:
                    return self.snapshot(ok=False, message="Identita giocatore non valida.")
                self.coin_toss_confirmed.add(actor_idx)
                if self.mode == "ai":
                    self.coin_toss_confirmed.add(1)
                if len(self.coin_toss_confirmed) < 2:
                    return self.snapshot(message="Conferma registrata. In attesa dell'altro giocatore.")
                self.coin_toss_pending = False
                return self._run_and_snapshot(self.engine.start_turn)
            if state.winner is not None:
                return self.snapshot(ok=False, message="La partita è terminata.")
            if kind == "surrender":
                # Resigning is always legal, even during the opponent's turn
                # or while the opponent owns chain priority.
                if network_actor_idx is not None:
                    if self.mode != "online" or network_actor_idx not in {0, 1}:
                        return self.snapshot(ok=False, message="Identita giocatore di rete non valida.")
                    surrendering_idx = network_actor_idx
                elif self.mode == "local":
                    surrendering_idx = state.active_player
                else:
                    surrendering_idx = 0
                state.winner = 1 - surrendering_idx
                state.log(
                    f"{state.players[surrendering_idx].name} si arrende. "
                    f"Vince {state.players[state.winner].name}."
                )
                return self.snapshot(message="Hai abbandonato la partita.")
            expected_actor_idx = self.chain_priority_idx if self.chain_active else state.active_player
            if network_actor_idx is not None:
                if self.mode != "online" or network_actor_idx not in {0, 1}:
                    return self.snapshot(ok=False, message="Identita giocatore di rete non valida.")
                if network_actor_idx != expected_actor_idx:
                    return self.snapshot(ok=False, message="Attendi il turno dell'avversario.")
                actor_idx = network_actor_idx
            else:
                actor_idx = expected_actor_idx if self.mode == "local" else 0
            expected_human = not self._is_ai_player(actor_idx)
            if not expected_human or (not self.chain_active and state.active_player != actor_idx):
                return self.snapshot(ok=False, message="Attendi il turno dell'avversario.")

            if kind == "play":
                uid = str(payload.get("uid") or "")
                if uid not in state.players[actor_idx].hand:
                    return self.snapshot(ok=False, message="La carta non è più nella tua mano.")
                hand_index = state.players[actor_idx].hand.index(uid)
                target = payload.get("target")
                def play() -> Any:
                    assert self.engine is not None
                    if self.chain_active:
                        definition = self.engine.state.instances[uid].definition
                        is_quick = runtime_cards.allows_quick_play(definition.name, definition.card_type)
                        if not is_quick:
                            return type("Result", (), {"ok": False, "message": "Durante la catena puoi giocare solo carte rapide."})()
                        result = self.engine.quick_play(actor_idx, hand_index, str(target) if target else None)
                        if result.ok:
                            self.chain_pass_count = 0
                            current = self.chain_participants.index(actor_idx)
                            self.chain_priority_idx = self.chain_participants[(current + 1) % len(self.chain_participants)]
                        return result
                    result = self.engine.play_card(actor_idx, hand_index, str(target) if target else None)
                    if result.ok:
                        if self.engine.state.flags.get("_runtime_waiting_for_reveal"):
                            self.post_runtime_chain_actor = actor_idx
                        else:
                            self._start_chain(actor_idx)
                    return result
                return self._run_and_snapshot(play)

            if kind == "attack":
                source = str(payload.get("source") or "").lower()
                if len(source) < 2 or not source[1:].isdigit() or source[0] not in {"a", "d"}:
                    return self.snapshot(ok=False, message="Sorgente di attacco non valida.")
                slot = int(source[1:]) - 1
                from_slot = slot if source[0] == "a" else -(slot + 1)
                raw_target = payload.get("target")
                target_slot = None
                if raw_target:
                    target = str(raw_target).lower()
                    if not target.startswith("a") or not target[1:].isdigit():
                        return self.snapshot(ok=False, message="Bersaglio di attacco non valido.")
                    target_slot = int(target[1:]) - 1
                def attack() -> Any:
                    assert self.engine is not None
                    result = self.engine.attack(actor_idx, from_slot, target_slot)
                    if result.ok:
                        if self.engine.state.flags.get("_runtime_waiting_for_reveal"):
                            self.post_runtime_chain_actor = actor_idx
                        else:
                            self._start_chain(actor_idx)
                    return result
                return self._run_and_snapshot(attack)

            if kind == "activate":
                source = str(payload.get("source") or "")
                target = payload.get("target")
                def activate() -> Any:
                    assert self.engine is not None
                    result = self.engine.activate_ability(actor_idx, source, str(target) if target else None)
                    if result.ok:
                        if self.engine.state.flags.get("_runtime_waiting_for_reveal"):
                            self.post_runtime_chain_actor = actor_idx
                        else:
                            self._start_chain(actor_idx)
                    return result
                return self._run_and_snapshot(activate)

            if kind == "chain_pass":
                return self.snapshot(message=self._chain_pass())

            if kind == "end_turn":
                if self.chain_active:
                    return self.snapshot(ok=False, message="Risolvi prima la catena.")
                def finish_turn() -> str:
                    assert self.engine is not None
                    self.engine.end_turn()
                    if self.mode == "ai":
                        self.ai_steps = 0
                    self._finish_turn_transition()
                    return "Turno completato."

                return self._run_and_snapshot(finish_turn)

            return self.snapshot(ok=False, message="Azione sconosciuta.")

    def _start_next_turn(self) -> None:
        assert self.engine is not None
        guard = 0
        while self.engine.state.winner is None and guard < 8:
            guard += 1
            self.engine.start_turn()
            if self.engine.state.phase != "setup":
                return

    def ai_step(self) -> dict[str, Any]:
        """Execute at most one visible AI move; the browser controls pacing."""
        with self.lock:
            if self.engine is None:
                raise ValueError("Partita non inizializzata.")
            state = self.engine.state
            if self.coin_toss_pending:
                return self.snapshot(message="Conferma prima il risultato del lancio della moneta.")
            if self.chain_active:
                if self.chain_priority_idx != 1:
                    return self.snapshot(message="La catena attende il giocatore.")
                return self._run_and_snapshot(self._perform_ai_chain_step)
            if self.mode != "ai" or state.winner is not None or state.active_player != 1:
                return self.snapshot(message="Nessuna mossa CPU in attesa.")

            def perform_step() -> Any:
                assert self.engine is not None
                self.ai_steps += 1
                log_count_before = len(self.engine.state.logs)
                result = choose_action(self.engine, 1, self.rng)
                if result.ok and result.message != "AI passa." and len(self.engine.state.logs) > log_count_before:
                    if self.engine.state.flags.get("_runtime_waiting_for_reveal"):
                        self.post_runtime_chain_actor = 1
                    else:
                        self._start_chain(1)
                should_end = (
                    result.message == "AI passa."
                    or self.ai_steps >= 24
                    or self.engine.state.winner is not None
                )
                if should_end and self.engine.state.winner is None and not self.chain_active:
                    self.engine.end_turn()
                    self.ai_steps = 0
                    self._finish_turn_transition()
                return result

            return self._run_and_snapshot(perform_step)


class HolyWarRequestHandler(SimpleHTTPRequestHandler):
    session: WebGameSession
    multiplayer: MultiplayerService
    user_settings: dict[str, Any]
    user_settings_path: Path

    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            # This is a local development UI: always serve the latest HTML/CSS/JS
            # after an edit instead of leaving the browser on an obsolete bundle.
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(self.multiplayer.snapshot())
            return
        if path == "/api/multiplayer/status":
            self._send_json(self.multiplayer.status())
            return
        if path == "/api/config":
            self._send_json(self.session.config())
            return
        if path == "/api/options":
            self._send_json({"ok": True, **self.user_settings})
            return
        if path == "/api/deck-editor":
            with self.session.lock:
                self._send_json(self.session.deck_editor())
            return
        if path == "/api/test-editor":
            with self.session.lock:
                self._send_json(self.session.test_editor())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Payload non valido.")
            path = urlparse(self.path).path
            if path == "/api/multiplayer/find":
                self._send_json(self.multiplayer.find_lobbies(payload))
                return
            if path == "/api/multiplayer/host":
                self._send_json(self.multiplayer.host(payload))
                return
            if path == "/api/multiplayer/join":
                self._send_json(self.multiplayer.join(payload))
                return
            if path == "/api/multiplayer/leave":
                self._send_json(self.multiplayer.leave())
                return
            if path == "/api/multiplayer/room-action":
                self._send_json(self.multiplayer.room_action(payload))
                return
            if path == "/api/options":
                username = str(payload.get("username") or "Pellegrino").strip()[:28] or "Pellegrino"
                default_deck = self.session._resolve_deck_id(payload.get("default_deck"), DEFAULT_PLAYER_DECK)
                chain_enabled = bool(payload.get("chain_enabled", True))
                self.user_settings.update({
                    "username": username,
                    "default_deck": default_deck,
                    "chain_enabled": chain_enabled,
                })
                self.user_settings_path.parent.mkdir(parents=True, exist_ok=True)
                self.user_settings_path.write_text(
                    json.dumps(self.user_settings, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._send_json({"ok": True, "message": "Opzioni salvate.", **self.user_settings})
                return
            if path == "/api/new-game":
                if self.multiplayer.active:
                    self.multiplayer.leave()
                self._send_json(self.session.new_game(payload))
                return
            if path == "/api/test-game":
                self._send_json(self.session.start_test_game(payload))
                return
            if path == "/api/play-options":
                self._send_json(
                    self.multiplayer.request("play_options", payload)
                    if self.multiplayer.active else self.session.play_options(payload)
                )
                return
            if path == "/api/activate-options":
                self._send_json(
                    self.multiplayer.request("activate_options", payload)
                    if self.multiplayer.active else self.session.activation_options(payload)
                )
                return
            if path == "/api/ai-step":
                self._send_json(self.session.ai_step())
                return
            if path == "/api/decision":
                self._send_json(
                    self.multiplayer.request("decision", payload)
                    if self.multiplayer.active else self.session.resolve_decision(payload)
                )
                return
            if path == "/api/action":
                self._send_json(
                    self.multiplayer.request("action", payload)
                    if self.multiplayer.active else self.session.action(payload)
                )
                return
            if path == "/api/deck-editor/validate":
                self._send_json(self.session.validate_deck(payload))
                return
            if path == "/api/deck-editor/save":
                self._send_json(self.session.save_deck(payload))
                return
            if path == "/api/deck-editor/delete":
                self._send_json(self.session.delete_deck(payload))
                return
            if path == "/api/deck-editor/export":
                self._send_json(self.session.export_decks(payload))
                return
            if path == "/api/deck-editor/import":
                self._send_json(self.session.import_decks(payload))
                return
            self._send_json({"ok": False, "message": "Endpoint sconosciuto."}, HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # keep the local UI alive and surface engine errors
            self._send_json({"ok": False, "message": f"Errore interno: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/"):
            return
        super().log_message(format, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Holy War - interfaccia web locale")
    parser.add_argument("--cards-json", default=str(bundled_data_dir() / "cards.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--premades-json", type=str, default=None, help="Importa deck premade custom da JSON")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--browser", action="store_true", help="Apri l'interfaccia nel browser predefinito")
    display.add_argument("--no-browser", action="store_true", help="Avvia soltanto il servizio locale")
    display.add_argument("--smoke-window", action="store_true", help=argparse.SUPPRESS)
    return parser


def _is_running_holywar(url: str) -> bool:
    try:
        with urlopen(f"{url}api/config", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return isinstance(payload, dict) and payload.get("application") == "holywar"
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _show_startup_error(log_path: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            f"Holy War non e riuscito ad avviarsi.\n\nDettagli salvati in:\n{log_path}",
            "Holy War - Errore di avvio",
            0x10,
        )
    except Exception:
        pass


def _open_desktop_window(url: str, *, smoke_test: bool = False) -> None:
    import webview

    class DesktopApi:
        def close(self) -> bool:
            if window is not None:
                window.destroy()
            return True

        def save_deck_export(self, content: str, suggested_filename: str) -> dict[str, Any]:
            safe_name = Path(str(suggested_filename or "holywar-decks.json")).name
            if not safe_name.lower().endswith(".json"):
                safe_name += ".json"
            if window is None:
                return {"ok": False, "message": "Finestra non disponibile."}
            selected = window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=safe_name,
                file_types=("File JSON (*.json)",),
            )
            if not selected:
                return {"ok": False, "cancelled": True}
            destination = Path(selected[0])
            destination.write_text(str(content), encoding="utf-8")
            return {"ok": True, "path": str(destination)}

    window = webview.create_window(
        "Holy War",
        url,
        width=1440,
        height=900,
        min_size=(1180, 760),
        resizable=True,
        maximized=not smoke_test,
        hidden=smoke_test,
        background_color="#080b12",
        text_select=False,
        zoomable=False,
        js_api=DesktopApi(),
    )
    if window is None:
        raise RuntimeError("Impossibile creare la finestra di Holy War.")
    if smoke_test:
        window.events.loaded += lambda: window.destroy()
    storage_dir = local_appdata_dir() / "WebView2"
    storage_dir.mkdir(parents=True, exist_ok=True)
    webview.start(
        gui="edgechromium",
        private_mode=False,
        storage_path=str(storage_dir),
        debug=False,
    )


def _run() -> None:
    args = build_parser().parse_args()
    if args.premades_json:
        for warning in register_premades_from_json(args.premades_json):
            print(f"Avviso deck: {warning}")
    static_dir = bundled_project_root() / "web_concept"
    session = WebGameSession(Path(args.cards_json), seed=args.seed, autoload=False)
    multiplayer = MultiplayerService(session)
    settings_path = appdata_dir() / "options.json"
    user_settings: dict[str, Any] = {
        "username": "Pellegrino",
        "default_deck": DEFAULT_PLAYER_DECK,
        "chain_enabled": True,
    }
    if settings_path.is_file():
        try:
            loaded_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded_settings, dict):
                for key in ("username", "default_deck"):
                    if key in loaded_settings:
                        user_settings[key] = str(loaded_settings[key])
                if "chain_enabled" in loaded_settings:
                    user_settings["chain_enabled"] = bool(loaded_settings["chain_enabled"])
        except (OSError, ValueError, TypeError):
            pass

    def handler(*handler_args: Any, **handler_kwargs: Any) -> HolyWarRequestHandler:
        HolyWarRequestHandler.session = session
        HolyWarRequestHandler.multiplayer = multiplayer
        HolyWarRequestHandler.user_settings = user_settings
        HolyWarRequestHandler.user_settings_path = settings_path
        return HolyWarRequestHandler(*handler_args, directory=str(static_dir), **handler_kwargs)

    server: ThreadingHTTPServer | None
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError:
        requested_url = f"http://{args.host}:{args.port}/"
        if args.port and _is_running_holywar(requested_url):
            server = None
            url = requested_url
        else:
            # A different application owns the requested port. Keep the local-only
            # security boundary and let Windows assign a free ephemeral port.
            server = ThreadingHTTPServer((args.host, 0), handler)
    if server is not None:
        server.daemon_threads = True
        actual_port = int(server.server_address[1])
        url = f"http://{args.host}:{actual_port}/"

    if args.browser:
        if server is None:
            webbrowser.open(url)
            multiplayer.close()
            return
        print(f"Holy War web avviato su {url}")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            multiplayer.close()
        return

    if args.no_browser:
        if server is None:
            multiplayer.close()
            return
        print(f"Holy War web avviato su {url}")
        print("Premi Ctrl+C per arrestare il server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            multiplayer.close()
        return

    server_thread: threading.Thread | None = None
    if server is not None:
        server_thread = threading.Thread(target=server.serve_forever, name="holywar-local-server", daemon=True)
        server_thread.start()
    try:
        _open_desktop_window(url, smoke_test=args.smoke_window)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        multiplayer.close()


def main() -> None:
    try:
        _run()
    except Exception:
        log_dir = appdata_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "startup_error.log"
        timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        log_path.write_text(f"[{timestamp}]\n{traceback.format_exc()}", encoding="utf-8")
        _show_startup_error(log_path)
        raise


if __name__ == "__main__":
    main()
