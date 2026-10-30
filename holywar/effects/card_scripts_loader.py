from __future__ import annotations

import importlib
import pkgutil
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# This module provides functionality for loading card scripts in the Holy War game engine. It defines a function `iter_card_scripts` that iterates through all the card script modules in the specified package, imports them, and yields their card names and script specifications as tuples. The module also includes helper functions for normalizing card names and managing module import times to ensure that changes to card scripts are reflected without needing to restart the engine.
def _norm_name(name: str) -> str:
    value = unicodedata.normalize("NFKD", name or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


_MODULE_MTIMES: dict[str, float] = {}

# This function imports a module by name and checks if the source file has been modified since the last import. If the file has been modified, it reloads the module to ensure that any changes are reflected in the game engine. The function uses the module's origin to determine the file path and its modification time, and it keeps track of the last known modification times in a dictionary.
def _import_or_reload_if_changed(module_name: str):
    module = importlib.import_module(module_name)
    origin = getattr(getattr(module, "__spec__", None), "origin", None) or getattr(module, "__file__", None)
    if not isinstance(origin, str) or not origin:
        return module
    try:
        mtime = Path(origin).stat().st_mtime
    except OSError:
        return module
    previous = _MODULE_MTIMES.get(module_name)
    if previous is None:
        _MODULE_MTIMES[module_name] = float(mtime)
        return module
    if float(mtime) > float(previous):
        module = importlib.reload(module)
        _MODULE_MTIMES[module_name] = float(mtime)
    return module


def iter_card_scripts() -> Iterator[tuple[str, dict[str, Any]]]:
    import holywar.effects.card_scripts.cards as scripts_pkg

    seen: set[str] = set()
    for mod in pkgutil.walk_packages(scripts_pkg.__path__, scripts_pkg.__name__ + "."):
        module = _import_or_reload_if_changed(mod.name)
        card_name = getattr(module, "CARD_NAME", None)
        spec = getattr(module, "SCRIPT", None)
        if not isinstance(card_name, str) or not card_name.strip():
            continue
        if not isinstance(spec, dict):
            continue
        key = _norm_name(card_name)
        if key in seen:
            continue
        seen.add(key)
        loaded = dict(spec)
        loaded["action_handlers"] = dict(getattr(module, "ACTION_HANDLERS", {}) or {})
        loaded["rule_hooks"] = dict(getattr(module, "RULE_HOOKS", {}) or {})
        loaded["targeting_handlers"] = dict(getattr(module, "TARGETING_HANDLERS", {}) or {})
        yield card_name, loaded
