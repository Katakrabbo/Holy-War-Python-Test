from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import json
import re
import unicodedata

from holywar.app_paths import appdata_dir, bundled_data_dir
from holywar.data.models import CardDefinition


CANONICAL_RELIGIONS = [
    "Cristianesimo",
    "Mitologia Norrena",
    "Animismo",
    "Egiziane",
    "Ph-DakGaph",
    "Ombre Maya",
    "Taoismo"
]

RELIGION_ALIASES = {
    "Cristianesimo": {"Cristianesimo", "CRI-1"},
    "Mitologia Norrena": {"Mitologia Norrena", "NOR-1"},
    "Animismo": {"Animismo", "ANI-1"},
    "Egiziane": {"Egiziane", "EGI-1"},
    "Ph-DakGaph": {"Ph-DakGaph", "PHD-1"},
    "Ombre Maya": {"Ombre Maya", "MAY-1"},
    "Neutre": {"Neutre", "NEU-1"},
    "Taoismo": {"Taoismo", "TAO-1"},
}

TYPE_PRIORITY = {
    "santo": 0,
    "artefatto": 1,
    "edificio": 2,
    "benedizione": 3,
    "maledizione": 4,
    "innata": 5,
    "token": 6,
}


@dataclass(slots=True)
class DeckBuildResult:
    main_deck: list[CardDefinition]
    white_deck: list[CardDefinition]
    innate_deck: list[CardDefinition]


@dataclass(slots=True)
class PremadeBuild:
    deck: DeckBuildResult
    warnings: list[str]


_FALLBACK_PREMADE_STORE_PATH = Path("holywar/data/premade_decks.json")
_DEFAULT_PREMADE_SOURCE_PATH = bundled_data_dir() / "premade_decks.json"
_LEGACY_PREMADE_PATHS = [
    Path("holywar/data/premade_decks.json"),
    Path("holywar/data/user_decks.json"),
]
_RUNTIME_PREMADE_DECKS: dict[str, dict] = {}


def _resolve_premade_store_path() -> Path:
    primary = appdata_dir() / "premade_decks.json"
    for candidate in (primary, _FALLBACK_PREMADE_STORE_PATH):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    return _FALLBACK_PREMADE_STORE_PATH


PREMADE_STORE_PATH = _resolve_premade_store_path()


def _is_in_group(card: CardDefinition, canonical: str) -> bool:
    aliases = RELIGION_ALIASES.get(canonical, {canonical})
    return card.expansion in aliases


def _sort_cards(cards: Iterable[CardDefinition]) -> list[CardDefinition]:
    return sorted(
        cards,
        key=lambda c: (
            TYPE_PRIORITY.get(c.card_type.lower(), 99),
            (c.faith if c.faith is not None else 0),
            c.name,
        ),
    )


def _norm(text: str) -> str:
    value = (
        text.replace("’", "'")
        .replace("`", "'")
        .replace("ø", "o")
        .replace("Ø", "O")
        .replace("ð", "d")
        .replace("Ð", "D")
    )
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def available_religions(cards: list[CardDefinition]) -> list[str]:
    present_from_cards = {rel for rel in CANONICAL_RELIGIONS if any(_is_in_group(c, rel) for c in cards)}
    present_from_premades = {str(cfg.get("religion", "")).strip() for cfg in _RUNTIME_PREMADE_DECKS.values()}
    out: list[str] = []
    for rel in CANONICAL_RELIGIONS:
        if rel in present_from_cards or rel in present_from_premades:
            out.append(rel)
    return out


def available_premade_decks(religion: str | None = None) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for deck_id, cfg in _RUNTIME_PREMADE_DECKS.items():
        rel = cfg["religion"]
        if religion and rel != religion:
            continue
        out.append((deck_id, rel, cfg["name"]))
    out.sort(key=lambda x: (x[1], x[2]))
    return out


def get_runtime_premade(deck_id: str) -> dict | None:
    cfg = _RUNTIME_PREMADE_DECKS.get(str(deck_id))
    if cfg is None:
        return None
    return {
        "id": str(deck_id),
        "religion": str(cfg.get("religion", "")),
        "name": str(cfg.get("name", "")),
        "cards": list(cfg.get("cards", []) or []),
        "allow_over_45": bool(cfg.get("allow_over_45", False)),
    }


def runtime_premade_decks() -> list[dict]:
    out: list[dict] = []
    for deck_id, cfg in _RUNTIME_PREMADE_DECKS.items():
        out.append(
            {
                "id": str(deck_id),
                "religion": str(cfg.get("religion", "")),
                "name": str(cfg.get("name", "")),
                "cards": list(cfg.get("cards", []) or []),
                "allow_over_45": bool(cfg.get("allow_over_45", False)),
            }
        )
    out.sort(key=lambda d: (str(d.get("religion", "")), str(d.get("name", ""))))
    return out


def export_runtime_decks(deck_ids: list[str]) -> dict:
    """Return a portable, versioned JSON payload for one or more decks."""
    requested = [str(deck_id).strip() for deck_id in deck_ids if str(deck_id).strip()]
    if not requested:
        raise ValueError("Seleziona almeno un deck da esportare.")
    missing = [deck_id for deck_id in requested if deck_id not in _RUNTIME_PREMADE_DECKS]
    if missing:
        raise ValueError(f"Deck non trovato: {missing[0]}")
    decks = []
    for deck_id in dict.fromkeys(requested):
        deck = get_runtime_premade(deck_id)
        if deck is None:
            continue
        decks.append({
            "id": deck["id"],
            "religion": deck["religion"],
            "name": deck["name"],
            "allow_over_45": bool(deck.get("allow_over_45", False)),
            "cards": [{"name": name, "qty": qty} for name, qty in deck.get("cards", [])],
        })
    return {"format": "holywar-decks", "version": 1, "decks": decks}


def _portable_decks_from_document(document: object) -> list[dict]:
    if isinstance(document, dict) and isinstance(document.get("decks"), list):
        return [item for item in document["decks"] if isinstance(item, dict)]
    if isinstance(document, dict) and all(key in document for key in ("name", "religion", "cards")):
        return [document]
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    raise ValueError("Formato deck non riconosciuto.")


def _unique_import_id(preferred_id: str, name: str) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", _norm(preferred_id or name).replace(" ", "_")).strip("_") or "deck"
    candidate = base
    suffix = 2
    while candidate in _RUNTIME_PREMADE_DECKS:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def import_runtime_deck_documents(cards: list[CardDefinition], documents: list[object]) -> dict:
    """Validate and persist decks imported from one or more JSON documents."""
    if not documents:
        raise ValueError("Seleziona almeno un file JSON da importare.")
    raw_decks: list[dict] = []
    for document in documents:
        raw_decks.extend(_portable_decks_from_document(document))
    if not raw_decks:
        raise ValueError("Il file non contiene deck importabili.")
    if len(raw_decks) > 200:
        raise ValueError("Puoi importare al massimo 200 deck alla volta.")

    imported: list[dict] = []
    skipped: list[str] = []
    errors: list[str] = []
    valid_religions = set(available_religions(cards))
    for index, raw in enumerate(raw_decks, start=1):
        label = str(raw.get("name") or f"Deck {index}").strip()
        try:
            deck = _normalize_deck_payload({**raw, "id": str(raw.get("id") or label)})
            if not deck["name"] or not deck["religion"]:
                raise ValueError("nome o religione mancanti")
            if deck["religion"] not in valid_religions:
                raise ValueError(f"religione non valida: {deck['religion']}")
            entries = [{"name": name, "qty": qty} for name, qty in deck["cards"]]
            report = validate_deck_cards(cards, entries)
            if not report["valid"]:
                raise ValueError("; ".join(report["errors"]))

            preferred_id = str(deck["id"]).strip()
            existing = _RUNTIME_PREMADE_DECKS.get(preferred_id)
            normalized_cards = [(item["name"], item["qty"]) for item in report["cards"]]
            if existing is not None:
                existing_cards = sorted(
                    [(str(name), int(qty)) for name, qty in list(existing.get("cards", []))],
                    key=lambda item: _norm(item[0]),
                )
                same_deck = (
                    str(existing.get("religion")) == deck["religion"]
                    and str(existing.get("name")) == deck["name"]
                    and existing_cards == normalized_cards
                )
                if same_deck:
                    skipped.append(deck["name"])
                    continue
                resolved_id = _unique_import_id(f"{preferred_id}_imported", deck["name"])
            else:
                resolved_id = _unique_import_id(preferred_id, deck["name"])

            _RUNTIME_PREMADE_DECKS[resolved_id] = {
                "religion": deck["religion"],
                "name": deck["name"],
                "cards": normalized_cards,
                "allow_over_45": bool(deck.get("allow_over_45", True)),
            }
            imported_deck = get_runtime_premade(resolved_id)
            if imported_deck is not None:
                imported.append(imported_deck)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{label}: {exc}")

    if imported:
        export_premades_json(PREMADE_STORE_PATH)
    return {"imported": imported, "skipped": skipped, "errors": errors}


def max_copies_for_crosses(crosses: str) -> int:
    """Return the copy limit used by the legacy deck editor."""
    raw = str(crosses or "").strip().lower()
    if raw in {"white", "croce bianca"}:
        value = 11
    else:
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return 1
    if 1 <= value <= 3:
        return 5
    if 4 <= value <= 6:
        return 3
    return 1


def validate_deck_cards(cards: list[CardDefinition], entries: list[dict]) -> dict:
    """Validate a deck with the same limits as the legacy desktop editor."""
    by_name = {_norm(card.name): card for card in cards}
    normalized: dict[str, tuple[CardDefinition, int]] = {}
    errors: list[str] = []
    notes: list[str] = []
    stats = {"band_13": 0, "band_46": 0, "band_79": 0, "band_10": 0, "band_white": 0, "innata": 0}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        try:
            qty = int(entry.get("qty", 0))
        except (TypeError, ValueError):
            qty = 0
        if not name or qty <= 0:
            continue
        card = by_name.get(_norm(name))
        if card is None:
            errors.append(f"Carta non trovata nel catalogo: {name}")
            continue
        key = _norm(card.name)
        previous = normalized.get(key)
        normalized[key] = (card, qty + (previous[1] if previous else 0))

    total = sum(qty for _card, qty in normalized.values())
    if total < 45:
        errors.append(f"Carte nel reliquiario insufficienti: {total}/45 (minimo 45).")

    for card, qty in sorted(normalized.values(), key=lambda item: _norm(item[0].name)):
        maximum = max_copies_for_crosses(card.crosses)
        if qty > maximum:
            errors.append(f"{card.name}: {qty} copie (max {maximum}).")
        if card.card_type.strip().lower() == "innata":
            stats["innata"] += qty
            notes.append(f"{card.name} e Innata: usarla solo in deck tematici.")
        raw = str(card.crosses or "").strip().lower()
        try:
            value = 11 if raw in {"white", "croce bianca"} else int(float(raw))
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 3:
            stats["band_13"] += qty
        elif 4 <= value <= 6:
            stats["band_46"] += qty
        elif 7 <= value <= 9:
            stats["band_79"] += qty
        elif value == 10:
            stats["band_10"] += qty
        elif value >= 11:
            stats["band_white"] += qty

    if stats["band_79"] > 10:
        errors.append(f"Carte 7-9 Croci: {stats['band_79']}/10 (massimo 10).")
    if stats["band_10"] > 3:
        errors.append(f"Carte 10 Croci: {stats['band_10']}/3 (massimo 3).")
    if stats["band_white"] > 1:
        errors.append(f"Carte Croce Bianca: {stats['band_white']}/1 (massimo 1).")

    payload = [{"name": card.name, "qty": qty} for card, qty in normalized.values()]
    payload.sort(key=lambda item: _norm(item["name"]))
    return {"valid": not errors, "errors": errors, "notes": notes, "total": total, "stats": stats, "cards": payload}


def save_runtime_deck(
    cards: list[CardDefinition], *, deck_id: str | None, name: str, religion: str, entries: list[dict]
) -> dict:
    """Validate and persist a deck in the store already used by the desktop UI."""
    name = str(name or "").strip()
    religion = str(religion or "").strip()
    if not name:
        raise ValueError("Inserisci un nome deck.")
    if not religion:
        raise ValueError("Seleziona una religione.")
    if religion not in available_religions(cards):
        raise ValueError("Religione non valida.")
    report = validate_deck_cards(cards, entries)
    if not report["valid"]:
        raise ValueError("\n".join(report["errors"]))

    resolved_id = str(deck_id or "").strip()
    if not resolved_id:
        base = re.sub(r"[^a-z0-9_]+", "_", _norm(name).replace(" ", "_")).strip("_") or "deck"
        resolved_id = f"user_{base}"
        suffix = 2
        while resolved_id in _RUNTIME_PREMADE_DECKS:
            resolved_id = f"user_{base}_{suffix}"
            suffix += 1
    _RUNTIME_PREMADE_DECKS[resolved_id] = {
        "religion": religion,
        "name": name,
        "cards": [(item["name"], item["qty"]) for item in report["cards"]],
        "allow_over_45": True,
    }
    export_premades_json(PREMADE_STORE_PATH)
    return get_runtime_premade(resolved_id) or {}


def delete_runtime_deck(deck_id: str) -> bool:
    """Delete a persisted deck, mirroring the legacy editor's delete action."""
    removed = _RUNTIME_PREMADE_DECKS.pop(str(deck_id), None) is not None
    if removed:
        export_premades_json(PREMADE_STORE_PATH)
    return removed


def get_premade_label(deck_id: str) -> str:
    cfg = _RUNTIME_PREMADE_DECKS[deck_id]
    return f"{cfg['religion']} - {cfg['name']}"


def reset_runtime_premades() -> None:
    _RUNTIME_PREMADE_DECKS.clear()
    _ensure_premade_store_exists()
    if PREMADE_STORE_PATH.exists():
        register_premades_from_json(PREMADE_STORE_PATH)


def _ensure_premade_store_exists() -> None:
    if PREMADE_STORE_PATH.exists():
        return
    PREMADE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

    for legacy in _LEGACY_PREMADE_PATHS:
        try:
            if not legacy.exists():
                continue
            src = legacy.resolve()
            dst = PREMADE_STORE_PATH.resolve()
            if src == dst:
                return
            PREMADE_STORE_PATH.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            return
        except Exception:
            continue

    if _DEFAULT_PREMADE_SOURCE_PATH.exists():
        PREMADE_STORE_PATH.write_text(_DEFAULT_PREMADE_SOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        return

    PREMADE_STORE_PATH.write_text(json.dumps({"decks": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_deck_payload(item: dict) -> dict:
    deck_id = str(item["id"]).strip()
    religion = str(item["religion"]).strip()
    name = str(item["name"]).strip()
    cards_payload = item.get("cards", [])
    cards: list[tuple[str, int]] = []
    for c in cards_payload:
        if isinstance(c, dict):
            cname = str(c.get("name", "")).strip()
            qty = int(c.get("qty", 1))
        else:
            continue
        if cname and qty > 0:
            cards.append((cname, qty))
    return {
        "id": deck_id,
        "religion": religion,
        "name": name,
        "cards": cards,
        "allow_over_45": bool(item.get("allow_over_45", False)),
    }


def register_premades_from_json(path: str | Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    decks = data.get("decks", [])
    warnings: list[str] = []
    if not isinstance(decks, list):
        warnings.append("Formato JSON non valido: 'decks' deve essere una lista.")
        return warnings
    for raw in decks:
        if not isinstance(raw, dict):
            warnings.append("Entry deck non valida (non dict), ignorata.")
            continue
        try:
            deck = _normalize_deck_payload(raw)
            if not deck["id"] or not deck["religion"] or not deck["name"]:
                warnings.append("Deck con id/religion/name vuoti, ignorato.")
                continue
            _RUNTIME_PREMADE_DECKS[deck["id"]] = {
                "religion": deck["religion"],
                "name": deck["name"],
                "cards": deck["cards"],
                "allow_over_45": bool(deck.get("allow_over_45", False)),
            }
        except Exception as exc:
            warnings.append(f"Deck non valido: {exc}")
    return warnings


def export_premades_json(path: str | Path, include_builtin: bool = True) -> Path:
    _ = include_builtin
    src = _RUNTIME_PREMADE_DECKS
    payload = {
        "decks": [
            {
                "id": deck_id,
                "religion": cfg["religion"],
                "name": cfg["name"],
                "allow_over_45": bool(cfg.get("allow_over_45", False)),
                "cards": [{"name": n, "qty": q} for n, q in cfg["cards"]],
            }
            for deck_id, cfg in src.items()
        ]
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def disable_runtime_premade(deck_id: str) -> None:
    _ = deck_id
    return


def build_premade_deck(cards: list[CardDefinition], deck_id: str) -> PremadeBuild:
    cfg = _RUNTIME_PREMADE_DECKS[deck_id]
    religion = cfg["religion"]
    allow_over_45 = bool(cfg.get("allow_over_45", False))
    warnings: list[str] = []

    by_name: dict[str, CardDefinition] = {}
    for c in cards:
        by_name.setdefault(_norm(c.name), c)

    main: list[CardDefinition] = []
    white: list[CardDefinition] = []
    innate: list[CardDefinition] = []

    def add_card(name: str, qty: int, source: str) -> None:
        card = by_name.get(_norm(name))
        if card is None:
            warnings.append(f"{source}: carta non trovata -> {name}")
            return
        ctype = card.card_type.lower()
        if ctype == "token":
            target = white
        elif ctype == "innata":
            target = innate
        else:
            target = main
        for _ in range(max(0, qty)):
            target.append(card)

    for name, qty in cfg["cards"]:
        add_card(name, qty, cfg["name"])

    if len(main) < 45:
        warnings.append(f"{cfg['name']}: deck incompleto ({len(main)}/45)")

    if not allow_over_45:
        main = main[:45]

    return PremadeBuild(
        deck=DeckBuildResult(main_deck=main, white_deck=white, innate_deck=innate),
        warnings=warnings,
    )


reset_runtime_premades()
