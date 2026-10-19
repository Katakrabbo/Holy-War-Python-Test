from __future__ import annotations

import base64
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from holywar.multiplayer.bridge import BridgeClient, BridgeError


PLAYER_ROLES = {"player1": 0, "player2": 1}


@dataclass
class _PendingReply:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class MultiplayerService:
    """Public EOS room browser and host-authoritative match coordinator."""

    _CHUNK_SIZE = 760

    def __init__(self, session: Any) -> None:
        self.session = session
        self.lock = threading.RLock()
        self.bridge: BridgeClient | None = None
        self.worker: threading.Thread | None = None
        self.user_id: str | None = None
        self.lobby_id: str | None = None
        self.owner_id: str | None = None
        self.role: str | None = None
        self.player_role: str | None = None
        self.phase = "offline"
        self.message = "Multiplayer non connesso."
        self.members: list[str] = []
        self.local_profile: dict[str, str] = {}
        self.profiles: dict[str, dict[str, Any]] = {}
        self.room_name = ""
        self._password = ""
        self.password_protected = False
        self.remote_snapshot: dict[str, Any] | None = None
        self.rematch_votes: dict[str, bool] = {}
        self._fragments: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending: dict[str, _PendingReply] = {}

    @property
    def active(self) -> bool:
        return self.role in {"host", "guest"} and self.lobby_id is not None

    def _ensure_online(self, display_name: str) -> None:
        if self.bridge is not None:
            return
        bridge = BridgeClient()
        try:
            bridge.request("initialize")
            login = dict(bridge.request("login", {"displayName": display_name}) or {})
        except Exception:
            bridge.close()
            raise
        self.bridge = bridge
        self.user_id = str(login.get("userId") or "")
        if not self.user_id:
            bridge.close()
            self.bridge = None
            raise BridgeError("EOS non ha restituito l'identita del giocatore.")
        self.worker = threading.Thread(target=self._event_loop, name="holywar-multiplayer", daemon=True)
        self.worker.start()

    @staticmethod
    def _profile(payload: dict[str, Any]) -> dict[str, str]:
        return {
            "name": str(payload.get("player_name") or "Pellegrino").replace("|", " ").strip()[:28] or "Pellegrino",
            "deck": str(payload.get("player_deck") or "").strip(),
        }

    def find_lobbies(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._profile(payload)
        self._ensure_online(profile["name"])
        if self.active:
            return {"ok": True, "rooms": []}
        assert self.bridge is not None
        result = dict(self.bridge.request("find_lobbies", timeout=30) or {})
        return {"ok": True, "rooms": list(result.get("rooms", []))}

    def host(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.active:
                raise ValueError("Esci prima dalla stanza corrente.")
            profile = self._profile(payload)
            room_name = str(payload.get("room_name") or "").strip()[:40]
            if not room_name:
                raise ValueError("Inserisci il nome della stanza.")
            password = str(payload.get("password") or "")[:64]
            self._ensure_online(profile["name"])
            assert self.bridge is not None
            created = dict(self.bridge.request("create_lobby", {
                "roomName": room_name,
                "passwordProtected": bool(password),
                "playerNames": profile["name"],
            }) or {})
            self.lobby_id = str(created.get("lobbyId") or "")
            self.owner_id = str(created.get("ownerId") or self.user_id)
            self.role, self.player_role, self.phase = "host", None, "waiting"
            self.message = "Stanza creata. Scegli un ruolo quando entra un altro giocatore."
            self.members = [self.user_id] if self.user_id else []
            self.local_profile, self.room_name = profile, room_name
            self._password, self.password_protected = password, bool(password)
            self.remote_snapshot = None
            self.rematch_votes.clear()
            self.profiles = {
                self.user_id: {"name": profile["name"], "role": None, "deck": "", "ready": False}
            } if self.user_id else {}
            return self.status()

    def join(self, payload: dict[str, Any]) -> dict[str, Any]:
        lobby_id = str(payload.get("lobby_id") or "").strip()
        if not lobby_id:
            raise ValueError("Stanza non specificata.")
        with self.lock:
            if self.active:
                raise ValueError("Esci prima dalla stanza corrente.")
            profile = self._profile(payload)
            self._ensure_online(profile["name"])
            assert self.bridge is not None
            joined = dict(self.bridge.request("join_lobby", {"lobbyId": lobby_id}) or {})
            self.lobby_id = str(joined.get("lobbyId") or lobby_id)
            self.owner_id = str(joined.get("ownerId") or "")
            self.role, self.player_role, self.phase = "guest", None, "authenticating"
            self.message = "Accesso alla stanza in corso..."
            self.local_profile = profile
            self.room_name = str(payload.get("room_name") or "")
            self.password_protected = bool(payload.get("password_protected"))
            self.remote_snapshot = None
            if not self.owner_id:
                bridge_status = dict(self.bridge.request("status") or {})
                self.owner_id = str(bridge_status.get("ownerId") or "")
                self.members = [str(item) for item in bridge_status.get("members", [])]
            if not self.owner_id:
                raise BridgeError("EOS non ha comunicato il proprietario della stanza.")
            self._send_message({"kind": "hello", "profile": profile, "password": str(payload.get("password") or "")}, self.owner_id)
            return self.status()

    def leave(self) -> dict[str, Any]:
        bridge = self.bridge
        if bridge is not None and self.lobby_id:
            try:
                for peer in self._peer_ids():
                    self._send_message({"kind": "left"}, peer)
                bridge.request("leave_lobby", timeout=20)
            except Exception:
                pass
        with self.lock:
            self.lobby_id = self.owner_id = self.role = self.player_role = None
            self.phase = "browser"
            self.message = "Seleziona una stanza o creane una nuova."
            self.members, self.profiles = [], {}
            self.remote_snapshot = None
            self.rematch_votes.clear()
        return self.status()

    def _peer_ids(self) -> list[str]:
        return [member for member in self.members if member and member != self.user_id]

    def status(self) -> dict[str, Any]:
        with self.lock:
            participants = [{
                "id": user_id,
                "name": str(profile.get("name") or "Giocatore"),
                "role": profile.get("role"),
                "ready": bool(profile.get("ready")),
                "is_local": user_id == self.user_id,
                "is_host": user_id == self.owner_id,
            } for user_id, profile in self.profiles.items()]
            return {
                "ok": True, "available": True, "connected": self.active,
                "connection_role": self.role, "player_role": self.player_role,
                "is_host": self.user_id is not None and self.user_id == self.owner_id,
                "phase": self.phase, "message": self.message, "room_name": self.room_name,
                "lobby_id": self.lobby_id, "members": len(self.members), "participants": participants,
                "playing": self.phase in {"playing", "rematch"},
                "rematch_required": self.phase == "rematch" and self.player_role in PLAYER_ROLES,
                "rematch_vote": self.rematch_votes.get(self.user_id or ""),
            }

    def room_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"select_role", "proceed", "select_deck", "start", "rematch"}:
            raise ValueError("Azione stanza non valida.")
        if not self.active:
            raise ValueError("Nessuna stanza attiva.")
        if self.role == "host":
            result = self._apply_room_action(self.user_id or "", action, payload)
            self._broadcast_room()
            return result
        if not self.owner_id:
            raise ValueError("Host della stanza non disponibile.")
        if action == "rematch" and self.user_id:
            self.rematch_votes[self.user_id] = bool(payload.get("accept"))
        return self._remote_call("room_request", {"action": action, "payload": payload}, self.owner_id)

    def _apply_room_action(self, user_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            profile = self.profiles.get(user_id)
            if profile is None:
                raise ValueError("Giocatore non riconosciuto nella stanza.")
            if action == "select_role":
                if self.phase != "waiting":
                    raise ValueError("La selezione dei ruoli e chiusa.")
                selected = str(payload.get("role") or "")
                if selected not in {"player1", "player2", "spectator"}:
                    raise ValueError("Ruolo non valido.")
                if selected in PLAYER_ROLES and any(p.get("role") == selected for uid, p in self.profiles.items() if uid != user_id):
                    raise ValueError("Questo posto e gia occupato.")
                occupied = {p.get("role") for uid, p in self.profiles.items() if uid != user_id}
                if selected == "spectator" and not {"player1", "player2"}.issubset(occupied):
                    raise ValueError("Gli spettatori possono entrare dopo l'assegnazione dei due giocatori.")
                profile["role"], profile["ready"] = selected, False
                if user_id == self.user_id:
                    self.player_role = selected
                self.message = "Ruoli aggiornati."
            elif action == "proceed":
                if user_id != self.owner_id:
                    raise ValueError("Solo l'host puo procedere.")
                if self.phase != "waiting" or not self._players_assigned():
                    raise ValueError("Servono Giocatore 1 e Giocatore 2.")
                if any(not item.get("role") for item in self.profiles.values()):
                    raise ValueError("Ogni partecipante deve scegliere un ruolo prima di procedere.")
                self.phase = "deck_select"
                for item in self.profiles.values():
                    item["ready"], item["deck"] = False, ""
                self.message = "Ogni giocatore scelga il proprio mazzo."
            elif action == "select_deck":
                if self.phase != "deck_select" or profile.get("role") not in PLAYER_ROLES:
                    raise ValueError("Non puoi scegliere un mazzo in questo momento.")
                deck = str(payload.get("deck") or "").strip()
                self.session._deck_religion(deck)  # noqa: SLF001
                profile["deck"], profile["ready"] = deck, True
                self.message = "Mazzo confermato."
            elif action == "start":
                if user_id != self.owner_id:
                    raise ValueError("Solo l'host puo avviare la partita.")
                self._start_match()
            elif action == "rematch":
                if self.phase != "rematch" or profile.get("role") not in PLAYER_ROLES:
                    raise ValueError("Voto rematch non disponibile.")
                self.rematch_votes[user_id] = bool(payload.get("accept"))
                if not self.rematch_votes[user_id]:
                    self.phase, self.message = "return_browser", "Rematch rifiutato. Ritorno alla lista stanze."
                elif all(self.rematch_votes.get(uid) is True for uid in self._player_ids()):
                    self._start_match(rematch=True)
            return self.status()

    def _players_assigned(self) -> bool:
        return {"player1", "player2"}.issubset({p.get("role") for p in self.profiles.values()})

    def _player_ids(self) -> list[str]:
        by_role = {str(p.get("role")): uid for uid, p in self.profiles.items() if p.get("role") in PLAYER_ROLES}
        return [by_role[role] for role in ("player1", "player2") if role in by_role]

    def _start_match(self, *, rematch: bool = False) -> None:
        players = self._player_ids()
        if len(players) != 2 or any(not self.profiles[uid].get("deck") for uid in players):
            raise ValueError("Entrambi i giocatori devono confermare il mazzo.")
        first, second = (self.profiles[uid] for uid in players)
        self.session.new_game({"mode": "online", "player_name": first["name"], "player_deck": first["deck"], "opponent_name": second["name"], "opponent_deck": second["deck"]})
        self.phase, self.message = "playing", ("Rematch avviato." if rematch else "Partita online avviata.")
        self.rematch_votes.clear()
        self._update_listing("started")
        self._broadcast_state(start=True)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            if self.role == "guest":
                if self.remote_snapshot is None:
                    raise ValueError("La partita online non e ancora iniziata.")
                return self.remote_snapshot
            if self.role == "host" and self.phase in {"playing", "rematch"}:
                with self.session.lock:
                    return self._snapshot_for_role(self.player_role)
        with self.session.lock:
            return self.session.snapshot()

    def _snapshot_for_role(self, role: str | None, *, ok: bool = True, message: str = "") -> dict[str, Any]:
        if role in PLAYER_ROLES:
            return self.session.snapshot(ok=ok, message=message, viewer_idx=PLAYER_ROLES[role])
        return self.session.snapshot(ok=ok, message=message, viewer_idx=0, spectator=True)

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"action", "decision", "play_options", "activate_options"}:
            raise ValueError("Operazione multiplayer non consentita.")
        if self.phase != "playing":
            raise ValueError("La partita online non e attiva.")
        if self.player_role not in PLAYER_ROLES:
            raise ValueError("Gli spettatori non possono interagire con la partita.")
        if self.role == "host":
            result = self._execute(operation, payload, PLAYER_ROLES[self.player_role])
            self._after_game_operation()
            if isinstance(result.get("game"), dict):
                return self._snapshot_for_role(
                    self.player_role,
                    ok=bool(result.get("ok")),
                    message=str(result.get("message") or ""),
                )
            return result
        if not self.owner_id:
            raise ValueError("Host non disponibile.")
        return self._remote_call("request", {"operation": operation, "payload": payload}, self.owner_id)

    def _remote_call(self, kind: str, message: dict[str, Any], owner: str) -> dict[str, Any]:
        request_id, pending = uuid4().hex, _PendingReply()
        with self.lock:
            self._pending[request_id] = pending
        try:
            self._send_message({"kind": kind, "request_id": request_id, **message}, owner)
            if not pending.event.wait(45):
                raise BridgeError("L'host non ha risposto. Controlla la connessione.")
            return pending.result or {"ok": False, "message": "Risposta multiplayer vuota."}
        finally:
            with self.lock:
                self._pending.pop(request_id, None)

    def _execute(self, operation: str, payload: dict[str, Any], actor_idx: int) -> dict[str, Any]:
        if operation == "action":
            return self.session.action(payload, network_actor_idx=actor_idx)
        if operation == "decision":
            pending = self.session.pending_decision or self.session._runtime_decision()  # noqa: SLF001
            if pending is None or int(pending["player_index"]) != actor_idx:
                return self.session.snapshot(ok=False, message="Nessuna scelta valida per questo giocatore.", viewer_idx=actor_idx)
            return self.session.resolve_decision(payload)
        if operation == "play_options":
            return self.session.play_options(payload, network_actor_idx=actor_idx)
        return self.session.activation_options(payload, network_actor_idx=actor_idx)

    def _after_game_operation(self) -> None:
        winner = self.session.engine.state.winner if self.session.engine else None
        if winner is not None:
            with self.lock:
                self.phase, self.message = "rematch", "Partita terminata. Scegli se giocare il rematch."
                self.rematch_votes.clear()
        self._broadcast_state()
        if winner is not None:
            self._broadcast_room()

    def _broadcast_state(self, *, start: bool = False) -> None:
        if self.role != "host" or self.phase not in {"playing", "rematch"}:
            return
        recipients = [(uid, str(p.get("role") or "spectator")) for uid, p in self.profiles.items() if uid != self.user_id]
        for user_id, role in recipients:
            with self.session.lock:
                snapshot = self._snapshot_for_role(role)
            self._send_message({"kind": "start" if start else "state", "snapshot": snapshot}, user_id)

    def _public_room(self) -> dict[str, Any]:
        return {"room_name": self.room_name, "phase": self.phase, "participants": [{
            "id": uid, "name": p.get("name"), "role": p.get("role"), "ready": bool(p.get("ready")),
            "is_host": uid == self.owner_id, "rematch_vote": self.rematch_votes.get(uid),
        } for uid, p in self.profiles.items()]}

    def _broadcast_room(self) -> None:
        if self.role != "host":
            return
        room = self._public_room()
        for peer in self._peer_ids():
            self._send_message({"kind": "room_state", "room": room}, peer)
        self._update_listing("started" if self.phase in {"playing", "rematch"} else self.phase)

    def _update_listing(self, phase: str) -> None:
        if self.role != "host" or self.bridge is None or not self.lobby_id:
            return
        names = "|".join(str(p.get("name") or "") for p in self.profiles.values())
        self.bridge.request("update_lobby", {"roomName": self.room_name, "passwordProtected": self.password_protected, "phase": phase, "playerNames": names}, timeout=20)

    def _send_message(self, message: dict[str, Any], peer_id: str) -> None:
        if self.bridge is None:
            raise BridgeError("Bridge EOS non avviato.")
        encoded = base64.b64encode(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()).decode("ascii")
        fragment_id = uuid4().hex
        chunks = [encoded[i:i + self._CHUNK_SIZE] for i in range(0, len(encoded), self._CHUNK_SIZE)] or [""]
        for index, chunk in enumerate(chunks):
            envelope = json.dumps({"v": 1, "id": fragment_id, "i": index, "n": len(chunks), "d": chunk}, separators=(",", ":"))
            self.bridge.request("send_packet", {"remoteUserId": peer_id, "data": envelope}, timeout=20)

    def _event_loop(self) -> None:
        assert self.bridge is not None
        while self.bridge is not None:
            try:
                event = self.bridge.events.get(timeout=1)
            except queue.Empty:
                self._discard_old_fragments()
                continue
            try:
                self._handle_bridge_event(event)
            except Exception as exc:
                with self.lock:
                    self.message = f"Errore multiplayer: {exc}"

    def _handle_bridge_event(self, event: dict[str, Any]) -> None:
        event_type, payload = str(event.get("type") or ""), dict(event.get("payload") or {})
        if event_type == "bridge_closed":
            self.phase, self.message = "error", str(event.get("error") or "Connessione EOS interrotta.")
            return
        if event_type == "lobby_updated":
            members = [str(item) for item in payload.get("members", [])]
            previous, self.members = set(self.members), members
            self.owner_id = str(payload.get("ownerId") or self.owner_id or "")
            for user_id in previous - set(members):
                self.profiles.pop(user_id, None)
            if previous - set(members) and self.role == "host":
                self._broadcast_room()
            elif self.role == "guest" and self.owner_id and members and self.owner_id not in members:
                self.phase, self.message = "return_browser", "L'host ha chiuso la stanza."
            return
        if event_type != "packet_received":
            return
        sender = str(payload.get("senderId") or "")
        if not self.active or not sender:
            return
        try:
            envelope = json.loads(str(payload.get("data") or ""))
            fragment_id, index, total, chunk = str(envelope["id"]), int(envelope["i"]), int(envelope["n"]), str(envelope["d"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        if total < 1 or total > 512 or not 0 <= index < total:
            return
        key = (sender, fragment_id)
        with self.lock:
            assembly = self._fragments.setdefault(key, {"time": time.monotonic(), "total": total, "parts": {}})
            if assembly["total"] != total:
                self._fragments.pop(key, None)
                return
            assembly["parts"][index] = chunk
            if len(assembly["parts"]) != total:
                return
            encoded = "".join(assembly["parts"][part] for part in range(total))
            self._fragments.pop(key, None)
        try:
            message = json.loads(base64.b64decode(encoded, validate=True).decode())
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return
        self._handle_message(sender, message)

    def _handle_message(self, sender: str, message: dict[str, Any]) -> None:
        kind = str(message.get("kind") or "")
        if kind == "hello" and self.role == "host":
            profile = dict(message.get("profile") or {})
            if str(message.get("password") or "") != self._password:
                self._send_message({"kind": "join_rejected", "message": "Password della stanza errata."}, sender)
                return
            participant_name = str(profile.get("name") or "Giocatore").replace("|", " ").strip()[:28] or "Giocatore"
            normalized_name = participant_name.casefold()
            if any(
                str(existing.get("name") or "").strip().casefold() == normalized_name
                for user_id, existing in self.profiles.items()
                if user_id != sender
            ):
                self._send_message({
                    "kind": "join_rejected",
                    "message": "Due partecipanti con lo stesso nome non possono partecipare alla stessa stanza.",
                }, sender)
                return
            auto_role = None
            if self.phase in {"deck_select", "playing", "rematch"} and self._players_assigned():
                if sum(1 for item in self.profiles.values() if item.get("role") == "spectator") >= 5:
                    self._send_message({"kind": "join_rejected", "message": "Posti spettatore esauriti."}, sender)
                    return
                auto_role = "spectator"
            if sender not in self.members:
                self.members.append(sender)
            self.profiles[sender] = {
                "name": participant_name,
                "role": auto_role,
                "deck": "",
                "ready": False,
            }
            self.message = "Un giocatore e entrato nella stanza."
            self._broadcast_room()
            return
        if kind == "join_rejected" and self.role == "guest":
            self.phase, self.message = "rejected", str(message.get("message") or "Accesso rifiutato.")
            return
        if kind == "room_state" and self.role == "guest":
            room = dict(message.get("room") or {})
            self.room_name, self.phase = str(room.get("room_name") or self.room_name), str(room.get("phase") or "waiting")
            self.profiles = {str(item["id"]): dict(item) for item in room.get("participants", []) if isinstance(item, dict) and item.get("id")}
            self.player_role = self.profiles.get(self.user_id or "", {}).get("role")
            own_vote = self.profiles.get(self.user_id or "", {}).get("rematch_vote")
            if own_vote is not None and self.user_id:
                self.rematch_votes[self.user_id] = bool(own_vote)
            self.message = "Stanza aggiornata."
            return
        if kind in {"start", "state"} and self.role == "guest":
            snapshot = message.get("snapshot")
            if isinstance(snapshot, dict):
                self.remote_snapshot = snapshot
                if self.phase != "rematch":
                    self.phase = "playing"
                self.message = "Partita online avviata."
            return
        if kind in {"request", "room_request"} and self.role == "host" and sender in self.profiles:
            request_id = str(message.get("request_id") or "")
            try:
                if kind == "room_request":
                    self._apply_room_action(sender, str(message.get("action") or ""), dict(message.get("payload") or {}))
                    result = {"ok": True, "message": self.message}
                    self._broadcast_room()
                else:
                    operation = str(message.get("operation") or "")
                    if operation not in {"action", "decision", "play_options", "activate_options"}:
                        raise ValueError("Operazione multiplayer non consentita.")
                    role = self.profiles[sender].get("role")
                    if role not in PLAYER_ROLES:
                        raise ValueError("Gli spettatori non possono interagire.")
                    result = self._execute(operation, dict(message.get("payload") or {}), PLAYER_ROLES[role])
                    if isinstance(result.get("game"), dict):
                        result = self._snapshot_for_role(role, ok=bool(result.get("ok")), message=str(result.get("message") or ""))
                    self._after_game_operation()
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            self._send_message({"kind": "response", "request_id": request_id, "result": result}, sender)
            return
        if kind == "response" and self.role == "guest":
            pending = self._pending.get(str(message.get("request_id") or ""))
            result = message.get("result")
            if pending is not None and isinstance(result, dict):
                pending.result = result
                if isinstance(result.get("game"), dict):
                    self.remote_snapshot = result
                pending.event.set()
            return
        if kind == "left":
            self.message = "Un partecipante ha lasciato la stanza."

    def _discard_old_fragments(self) -> None:
        cutoff = time.monotonic() - 30
        with self.lock:
            for key in [key for key, value in self._fragments.items() if float(value["time"]) < cutoff]:
                self._fragments.pop(key, None)

    def close(self) -> None:
        try:
            self.leave()
        finally:
            bridge = self.bridge
            self.bridge = None
            if bridge is not None:
                bridge.close()
