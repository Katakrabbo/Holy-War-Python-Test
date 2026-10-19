from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4


class BridgeError(RuntimeError):
    pass


def _creation_flags() -> int:
    if not sys.platform.startswith("win"):
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def discover_bridge() -> tuple[list[str], Path]:
    override = os.environ.get("HOLYWAR_MULTIPLAYER_BRIDGE", "").strip()
    settings_override = os.environ.get("HOLYWAR_EOS_SETTINGS", "").strip()
    source_root = Path(__file__).resolve().parents[2]
    installed_root = Path(sys.executable).resolve().parent

    candidates = [Path(override)] if override else [
        installed_root / "multiplayer" / "HolyWar.Multiplayer.Bridge.exe",
        source_root / "multiplayer" / "HolyWar.Multiplayer.Bridge" / "bin" / "x64" / "Release" / "net8.0" / "HolyWar.Multiplayer.Bridge.exe",
    ]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise BridgeError(
            "Componente multiplayer EOS non trovato. Ricrea l'installer oppure esegui "
            "scripts\\setup_multiplayer_dev.ps1 sul PC di sviluppo."
        )

    settings_candidates = [Path(settings_override)] if settings_override else [
        executable.parent / "eos.settings.json",
        source_root / "multiplayer" / "eos.settings.json",
    ]
    settings = next((path for path in settings_candidates if path.is_file()), None)
    if settings is None:
        raise BridgeError("Configurazione EOS non trovata (eos.settings.json).")
    return [str(executable), "--provider", "eos", "--settings", str(settings)], settings


class BridgeClient:
    """Thread-safe JSON-lines client for the isolated EOS/.NET process."""

    def __init__(self) -> None:
        command, _settings = discover_bridge()
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False
        self.diagnostics: deque[str] = deque(maxlen=80)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_creation_flags(),
        )
        self._reader = threading.Thread(target=self._read_stdout, name="holywar-eos-output", daemon=True)
        self._errors = threading.Thread(target=self._read_stderr, name="holywar-eos-errors", daemon=True)
        self._reader.start()
        self._errors.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self.diagnostics.append(f"Risposta bridge non valida: {line.rstrip()}")
                    continue
                request_id = str(message.get("requestId") or "")
                if message.get("type") == "response" and request_id:
                    with self._pending_lock:
                        target = self._pending.get(request_id)
                    if target is not None:
                        target.put(message)
                else:
                    self.events.put(message)
        finally:
            error = {
                "type": "bridge_closed",
                "ok": False,
                "error": "Il processo multiplayer EOS si e chiuso inaspettatamente.",
            }
            self.events.put(error)
            with self._pending_lock:
                targets = list(self._pending.values())
            for target in targets:
                target.put(error)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            if line.strip():
                self.diagnostics.append(line.rstrip())

    def request(self, operation: str, payload: dict[str, Any] | None = None, *, timeout: float = 45) -> Any:
        if self._closed or self.process.poll() is not None:
            raise BridgeError("Il servizio multiplayer EOS non e disponibile.")
        request_id = uuid4().hex
        target: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = target
        command = {
            "protocolVersion": 1,
            "requestId": request_id,
            "operation": operation,
            "payload": payload or {},
        }
        try:
            assert self.process.stdin is not None
            with self._write_lock:
                self.process.stdin.write(json.dumps(command, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.process.stdin.flush()
            try:
                response = target.get(timeout=timeout)
            except queue.Empty as exc:
                raise BridgeError(f"EOS non ha risposto all'operazione {operation!r}.") from exc
            if not response.get("ok"):
                raise BridgeError(str(response.get("error") or "Operazione EOS non riuscita."))
            return response.get("payload")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self.process.poll() is None:
                try:
                    self.request("shutdown", timeout=5)
                except Exception:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        finally:
            self._closed = True

