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


@dataclass
class _PendingReply:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class MultiplayerService:
    """Host-authoritative Holy War match transported over EOS Lobby/P2P."""

    _CHUNK_SIZE = 760

    def __init__(self, session: Any) -> None:
        self.session = session
        self.lock = threading.RLock()
        self.bridge: BridgeClient | None = None
        self.worker: threading.Thread | None = None
        self.user_id: str | None = None
        self.lobby_id: str | None = None
        self.owner_id: str | None = None
        self.peer_id: str | None = None
        self.role: str | None = None
        self.phase = "offline"
        self.message = "Multiplayer non connesso."
        self.members: list[str] = []
        self.local_profile: dict[str, str] = {}
        self.remote_snapshot: dict[str, Any] | None = None
        self._host_started = False
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
            "name": str(payload.get("player_name") or "Pellegrino").strip()[:28] or "Pellegrino",
            "deck": str(payload.get("player_deck") or "").strip(),
        }

    def host(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.active:
                raise ValueError("Esci prima dalla lobby corrente.")
            profile = self._profile(payload)
            self._ensure_online(profile["name"])
            assert self.bridge is not None
            created = dict(self.bridge.request("create_lobby") or {})
            self.lobby_id = str(created.get("lobbyId") or "")
            self.owner_id = str(created.get("ownerId") or self.user_id)
            self.role = "host"
            self.phase = "waiting"
            self.message = "Lobby creata. Condividi il codice con il tuo amico."
            self.members = [self.user_id] if self.user_id else []
            self.local_profile = profile
            self.remote_snapshot = None
            self._host_started = False
            return self.status()

    def join(self, payload: dict[str, Any]) -> dict[str, Any]:
        lobby_id = str(payload.get("lobby_id") or "").strip()
        if not lobby_id:
            raise ValueError("Inserisci il codice lobby.")
        with self.lock:
            if self.active:
                raise ValueError("Esci prima dalla lobby corrente.")
            profile = self._profile(payload)
            self._ensure_online(profile["name"])
            assert self.bridge is not None
            joined = dict(self.bridge.request("join_lobby", {"lobbyId": lobby_id}) or {})
            self.lobby_id = str(joined.get("lobbyId") or lobby_id)
            self.owner_id = str(joined.get("ownerId") or "")
            self.role = "guest"
            self.phase = "waiting"
            self.message = "Lobby raggiunta. Attendo l'avvio dell'host."
            self.local_profile = profile
            self.remote_snapshot = None
            if not self.owner_id:
                status = dict(self.bridge.request("status") or {})
                self.owner_id = str(status.get("ownerId") or "")
                self.members = [str(item) for item in status.get("members", [])]
            if not self.owner_id:
                raise BridgeError("EOS non ha comunicato il proprietario della lobby.")
            self.peer_id = self.owner_id
            self._send_message({"kind": "hello", "profile": profile}, self.owner_id)
            return self.status()

    def leave(self) -> dict[str, Any]:
        bridge = self.bridge
        if bridge is not None and self.lobby_id:
            try:
                if self.peer_id:
                    self._send_message({"kind": "left"}, self.peer_id)
                bridge.request("leave_lobby", timeout=20)
            except Exception:
                pass
        with self.lock:
            self.lobby_id = None
            self.owner_id = None
            self.peer_id = None
            self.role = None
            self.phase = "offline"
            self.message = "Multiplayer disconnesso."
            self.members = []
            self.remote_snapshot = None
            self._host_started = False
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "available": True,
                "connected": self.active,
                "role": self.role,
                "phase": self.phase,
                "message": self.message,
                "lobby_id": self.lobby_id,
                "members": len(self.members),
                "playing": self.phase == "playing",
            }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            if self.role == "guest":
                if self.remote_snapshot is None:
                    raise ValueError("La partita online non e ancora iniziata.")
                return self.remote_snapshot
            if self.role == "host" and self.phase == "playing":
                with self.session.lock:
                    return self.session.snapshot(viewer_idx=0)
        with self.session.lock:
            return self.session.snapshot()

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"action", "decision", "play_options", "activate_options"}:
            raise ValueError("Operazione multiplayer non consentita.")
        with self.lock:
            if self.phase != "playing":
                raise ValueError("La partita online non e ancora iniziata.")
            role = self.role
        if role == "host":
            result = self._execute(operation, payload, 0)
            self._broadcast_state()
            return result
        if role != "guest" or not self.peer_id:
            raise ValueError("Nessuna partita multiplayer attiva.")
        request_id = uuid4().hex
        pending = _PendingReply()
        with self.lock:
            self._pending[request_id] = pending
        try:
            self._send_message(
                {"kind": "request", "request_id": request_id, "operation": operation, "payload": payload},
                self.peer_id,
            )
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

    def _broadcast_state(self) -> None:
        with self.lock:
            if self.role != "host" or not self.peer_id or self.phase != "playing":
                return
            with self.session.lock:
                snapshot = self.session.snapshot(viewer_idx=1)
            peer = self.peer_id
        self._send_message({"kind": "state", "snapshot": snapshot}, peer)

    def _send_message(self, message: dict[str, Any], peer_id: str) -> None:
        bridge = self.bridge
        if bridge is None:
            raise BridgeError("Bridge EOS non avviato.")
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        fragment_id = uuid4().hex
        chunks = [encoded[index:index + self._CHUNK_SIZE] for index in range(0, len(encoded), self._CHUNK_SIZE)] or [""]
        for index, chunk in enumerate(chunks):
            envelope = json.dumps(
                {"v": 1, "id": fragment_id, "i": index, "n": len(chunks), "d": chunk},
                separators=(",", ":"),
            )
            bridge.request("send_packet", {"remoteUserId": peer_id, "data": envelope}, timeout=20)

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
        event_type = str(event.get("type") or "")
        payload = dict(event.get("payload") or {})
        if event_type == "bridge_closed":
            with self.lock:
                self.phase = "error"
                self.message = str(event.get("error") or "Connessione EOS interrotta.")
            return
        if event_type == "lobby_updated":
            members = [str(item) for item in payload.get("members", [])]
            with self.lock:
                self.members = members
                self.owner_id = str(payload.get("ownerId") or self.owner_id or "")
                peers = [item for item in members if item != self.user_id]
                self.peer_id = peers[0] if peers else None
                if self.phase == "playing" and not peers:
                    self.phase = "disconnected"
                    self.message = "L'avversario ha lasciato la partita."
            return
        if event_type != "packet_received":
            return
        sender = str(payload.get("senderId") or "")
        # The native bridge has already rejected packets from users outside the
        # current lobby. Do not repeat that check against the asynchronously
        # updated Python member cache, otherwise the first hello can race it.
        if not self.active or not sender:
            return
        try:
            envelope = json.loads(str(payload.get("data") or ""))
            fragment_id = str(envelope["id"])
            index = int(envelope["i"])
            total = int(envelope["n"])
            chunk = str(envelope["d"])
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
            message = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return
        self._handle_message(sender, message)

    def _handle_message(self, sender: str, message: dict[str, Any]) -> None:
        kind = str(message.get("kind") or "")
        if kind == "hello" and self.role == "host" and not self._host_started:
            profile = dict(message.get("profile") or {})
            self.peer_id = sender
            self.session.new_game({
                "mode": "online",
                "player_name": self.local_profile.get("name"),
                "player_deck": self.local_profile.get("deck"),
                "opponent_name": str(profile.get("name") or "Giocatore 2"),
                "opponent_deck": str(profile.get("deck") or ""),
            })
            with self.lock:
                self._host_started = True
                self.phase = "playing"
                self.message = "Partita online avviata."
            self._send_message({"kind": "start", "snapshot": self.session.snapshot(viewer_idx=1)}, sender)
            return
        if kind in {"start", "state"} and self.role == "guest":
            snapshot = message.get("snapshot")
            if isinstance(snapshot, dict):
                with self.lock:
                    self.remote_snapshot = snapshot
                    self.phase = "playing"
                    self.message = "Partita online avviata."
            return
        if kind == "request" and self.role == "host" and sender == self.peer_id:
            request_id = str(message.get("request_id") or "")
            operation = str(message.get("operation") or "")
            payload = dict(message.get("payload") or {})
            try:
                if operation not in {"action", "decision", "play_options", "activate_options"}:
                    raise ValueError("Operazione multiplayer non consentita.")
                result = self._execute(operation, payload, 1)
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            if isinstance(result.get("game"), dict):
                result = self.session.snapshot(
                    ok=bool(result.get("ok")),
                    message=str(result.get("message") or ""),
                    viewer_idx=1,
                )
            self._send_message({"kind": "response", "request_id": request_id, "result": result}, sender)
            return
        if kind == "response" and self.role == "guest":
            request_id = str(message.get("request_id") or "")
            with self.lock:
                pending = self._pending.get(request_id)
                result = message.get("result")
                if pending is not None and isinstance(result, dict):
                    pending.result = result
                    if isinstance(result.get("game"), dict):
                        self.remote_snapshot = result
                    pending.event.set()
            return
        if kind == "left":
            with self.lock:
                self.phase = "disconnected"
                self.message = "L'avversario ha lasciato la partita."

    def _discard_old_fragments(self) -> None:
        cutoff = time.monotonic() - 30
        with self.lock:
            stale = [key for key, value in self._fragments.items() if float(value["time"]) < cutoff]
            for key in stale:
                self._fragments.pop(key, None)

    def close(self) -> None:
        try:
            self.leave()
        finally:
            bridge = self.bridge
            self.bridge = None
            if bridge is not None:
                bridge.close()

