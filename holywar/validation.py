from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The current runtime expects the core engine to establish the normal import order.
# Keeping that same order makes this diagnostic behave exactly like the application.
import holywar.core.engine  # noqa: F401
from holywar.effects.catalog import CANONICAL_ACTIONS, CANONICAL_CONDITIONS, CANONICAL_EVENTS
from holywar.effects.runtime import EFFECT_ACTION_ALIASES


ACTION_GROUPS = ("triggered_effects", "on_play_actions", "on_enter_actions", "on_activate_actions")


def _norm(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).strip().lower()


@dataclass(slots=True)
class ValidationReport:
    cards: int = 0
    scripts: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate_condition(node: Any, location: str, report: ValidationReport) -> None:
    if not node:
        return
    if not isinstance(node, dict):
        report.errors.append(f"{location}: la condizione deve essere un oggetto.")
        return
    for key, payload in node.items():
        if key not in CANONICAL_CONDITIONS:
            report.errors.append(f"{location}: condizione sconosciuta '{key}'.")
            continue
        if key in {"all_of", "any_of"}:
            if not isinstance(payload, list):
                report.errors.append(f"{location}.{key}: deve essere una lista.")
                continue
            for index, child in enumerate(payload):
                _validate_condition(child, f"{location}.{key}[{index}]", report)
        elif key == "not":
            _validate_condition(payload, f"{location}.not", report)


def _validate_target(raw: Any, location: str, report: ValidationReport) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        report.errors.append(f"{location}: target deve essere un oggetto.")
        return
    minimum = raw.get("min_targets")
    maximum = raw.get("max_targets")
    for label, value in (("min_targets", minimum), ("max_targets", maximum)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            report.errors.append(f"{location}.{label}: deve essere un intero non negativo.")
    if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
        report.errors.append(f"{location}: min_targets ({minimum}) supera max_targets ({maximum}).")


def _validate_action(raw: Any, location: str, report: ValidationReport, *, triggered: bool) -> None:
    if not isinstance(raw, dict):
        report.errors.append(f"{location}: l'azione deve essere un oggetto.")
        return

    if triggered:
        trigger = raw.get("trigger")
        if not isinstance(trigger, dict):
            report.errors.append(f"{location}.trigger: trigger mancante o non valido.")
        else:
            event = str(trigger.get("event", "")).strip()
            if not event:
                report.errors.append(f"{location}.trigger: evento mancante.")
            elif event not in CANONICAL_EVENTS:
                report.errors.append(f"{location}.trigger: evento sconosciuto '{event}'.")
            _validate_condition(trigger.get("condition"), f"{location}.trigger.condition", report)

    _validate_condition(raw.get("condition"), f"{location}.condition", report)
    _validate_target(raw.get("target"), f"{location}.target", report)

    effect = raw.get("effect")
    if not isinstance(effect, dict):
        report.errors.append(f"{location}.effect: effetto mancante o non valido.")
        return
    action = str(effect.get("action", "")).strip().lower()
    if not action:
        report.errors.append(f"{location}.effect: action mancante.")
        return
    canonical = EFFECT_ACTION_ALIASES.get(action, action)
    if canonical not in CANONICAL_ACTIONS:
        report.errors.append(f"{location}.effect: action sconosciuta '{action}'.")

    minimum = effect.get("min_targets")
    maximum = effect.get("max_targets")
    if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
        report.errors.append(
            f"{location}.effect: min_targets ({minimum}) supera max_targets ({maximum})."
        )


def _load_card_names(cards_path: Path, report: ValidationReport) -> set[str]:
    try:
        payload = json.loads(cards_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.errors.append(f"Impossibile leggere {cards_path}: {exc}")
        return set()
    if not isinstance(payload, list):
        report.errors.append(f"{cards_path}: la radice JSON deve essere una lista.")
        return set()

    names: dict[str, str] = {}
    for index, card in enumerate(payload):
        if not isinstance(card, dict):
            report.errors.append(f"Carta #{index + 1}: deve essere un oggetto.")
            continue
        name = str(card.get("name", "")).strip()
        card_type = str(card.get("card_type", "")).strip()
        if not name:
            report.errors.append(f"Carta #{index + 1}: nome mancante.")
            continue
        key = _norm(name)
        if key in names:
            report.errors.append(f"Carta duplicata: '{name}' e '{names[key]}'.")
        else:
            names[key] = name
        if not card_type:
            report.errors.append(f"Carta '{name}': tipo mancante.")
    report.cards = len(names)
    return set(names)


def validate_project(cards_path: str | Path) -> ValidationReport:
    report = ValidationReport()
    card_names = _load_card_names(Path(cards_path), report)

    import holywar.effects.card_scripts.cards as scripts_package

    scripts: dict[str, str] = {}
    for module_info in pkgutil.walk_packages(scripts_package.__path__, scripts_package.__name__ + "."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # diagnostic boundary: report every broken card module
            report.errors.append(f"{module_info.name}: import fallito ({type(exc).__name__}: {exc}).")
            continue
        card_name = getattr(module, "CARD_NAME", None)
        spec = getattr(module, "SCRIPT", None)
        if card_name is None and spec is None:
            continue
        if not isinstance(card_name, str) or not card_name.strip():
            report.errors.append(f"{module_info.name}: CARD_NAME mancante o non valido.")
            continue
        if not isinstance(spec, dict):
            report.errors.append(f"{module_info.name}: SCRIPT mancante o non valido.")
            continue

        name = card_name.strip()
        key = _norm(name)
        if key in scripts:
            report.errors.append(f"Script duplicato per '{name}': {scripts[key]} e {module_info.name}.")
            continue
        scripts[key] = module_info.name
        if card_names and key not in card_names:
            report.warnings.append(f"{name}: esiste uno script ma non una carta nel JSON.")

        for group in ACTION_GROUPS:
            actions = spec.get(group, [])
            if not isinstance(actions, list):
                report.errors.append(f"{name}.{group}: deve essere una lista.")
                continue
            for index, action in enumerate(actions):
                _validate_action(
                    action,
                    f"{name}.{group}[{index}]",
                    report,
                    triggered=group == "triggered_effects",
                )

    report.scripts = len(scripts)
    for key in sorted(card_names - set(scripts)):
        report.warnings.append(f"Carta senza script dedicato: '{key}'.")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida dati e script delle carte di Holy War.")
    parser.add_argument("--cards-json", default="holywar/data/cards.json")
    args = parser.parse_args(argv)
    report = validate_project(args.cards_json)

    print(f"Carte: {report.cards} | Script: {report.scripts}")
    for message in report.errors:
        print(f"ERRORE: {message}")
    for message in report.warnings:
        print(f"AVVISO: {message}")
    if report.ok:
        print(f"Validazione completata: 0 errori, {len(report.warnings)} avvisi.")
        return 0
    print(f"Validazione fallita: {len(report.errors)} errori, {len(report.warnings)} avvisi.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
