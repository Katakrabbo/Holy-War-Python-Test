from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import uuid4

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from holywar.web import WebGameSession


PROTOCOL_VERSION = 1
GAMEPLAY_COMMANDS = frozenset(
    {
        "play",
        "attack",
        "activate",
        "chain_pass",
        "end_turn",
        "surrender",
        "decision",
    }
)


class ProtocolError(ValueError):
    """Raised when an untrusted multiplayer message is malformed."""


@dataclass(frozen=True, slots=True)
class MatchCommand:
    match_id: str
    sender_id: str
    sequence: int
    expected_revision: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: uuid4().hex)
    protocol_version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "match_id": self.match_id,
            "sender_id": self.sender_id,
            "sequence": self.sequence,
            "expected_revision": self.expected_revision,
            "kind": self.kind,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MatchCommand":
        try:
            command = cls(
                protocol_version=int(raw["protocol_version"]),
                message_id=str(raw["message_id"]).strip(),
                match_id=str(raw["match_id"]).strip(),
                sender_id=str(raw["sender_id"]).strip(),
                sequence=int(raw["sequence"]),
                expected_revision=int(raw["expected_revision"]),
                kind=str(raw["kind"]).strip().lower(),
                payload=dict(raw.get("payload") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"Messaggio multiplayer non valido: {exc}") from exc
        command.validate()
        return command

    def validate(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"Versione protocollo {self.protocol_version} non supportata; attesa {PROTOCOL_VERSION}."
            )
        if not self.message_id or len(self.message_id) > 128:
            raise ProtocolError("message_id mancante o troppo lungo.")
        if not self.match_id or len(self.match_id) > 128:
            raise ProtocolError("match_id mancante o troppo lungo.")
        if not self.sender_id or len(self.sender_id) > 128:
            raise ProtocolError("sender_id mancante o troppo lungo.")
        if self.sequence < 0 or self.expected_revision < 0:
            raise ProtocolError("Sequenza e revisione devono essere non negative.")
        if self.kind not in GAMEPLAY_COMMANDS:
            raise ProtocolError(f"Comando multiplayer sconosciuto: {self.kind!r}.")


class AuthoritativeMatch:
    """Validate ordered network commands before they reach the Python engine."""

    def __init__(self, match_id: str, session: "WebGameSession", player_ids: tuple[str, str]) -> None:
        if session.mode != "online":
            raise ValueError("La sessione deve essere inizializzata in modalita online.")
        if not match_id.strip() or len(set(player_ids)) != 2 or any(not item.strip() for item in player_ids):
            raise ValueError("Identificatori partita/giocatori non validi.")
        self.match_id = match_id
        self.session = session
        self.player_indexes = {player_ids[0]: 0, player_ids[1]: 1}
        self.next_sequence = {player_ids[0]: 0, player_ids[1]: 0}
        self.revision = 0

    def apply(self, command: MatchCommand) -> dict[str, Any]:
        command.validate()
        if command.match_id != self.match_id:
            raise ProtocolError("Il comando appartiene a un'altra partita.")
        if command.sender_id not in self.player_indexes:
            raise ProtocolError("Giocatore non appartenente alla partita.")
        if command.expected_revision != self.revision:
            raise ProtocolError(
                f"Stato desincronizzato: revisione locale {self.revision}, ricevuta {command.expected_revision}."
            )
        expected_sequence = self.next_sequence[command.sender_id]
        if command.sequence != expected_sequence:
            raise ProtocolError(
                f"Sequenza non valida per {command.sender_id}: attesa {expected_sequence}, ricevuta {command.sequence}."
            )

        actor_idx = self.player_indexes[command.sender_id]
        if command.kind == "decision":
            pending = self.session.pending_decision or self.session._runtime_decision()
            if pending is None or int(pending["player_index"]) != actor_idx:
                response = self.session.snapshot(ok=False, message="Nessuna scelta di rete valida.", viewer_idx=actor_idx)
            else:
                response = self.session.resolve_decision(dict(command.payload))
        else:
            payload = dict(command.payload)
            payload["type"] = command.kind
            response = self.session.action(payload, network_actor_idx=actor_idx)

        accepted = bool(response.get("ok"))
        if accepted:
            self.next_sequence[command.sender_id] += 1
            self.revision += 1
        return {
            "ok": accepted,
            "message": str(response.get("message", "")),
            "revision": self.revision,
            "ack_sequence": command.sequence if accepted else None,
            "snapshots": {
                player_id: self.session.snapshot(viewer_idx=player_idx)
                for player_id, player_idx in self.player_indexes.items()
            },
        }
