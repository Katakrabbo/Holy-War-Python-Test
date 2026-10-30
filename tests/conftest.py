from pathlib import Path

import pytest

from holywar.data import deck_builder


@pytest.fixture(autouse=True)
def isolated_premade_decks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test the bundled decks and a disposable save location."""
    bundled_decks = Path(__file__).resolve().parents[1] / "holywar" / "data" / "premade_decks.json"
    test_store = tmp_path / "premade_decks.json"
    test_store.write_bytes(bundled_decks.read_bytes())
    monkeypatch.setattr(deck_builder, "PREMADE_STORE_PATH", test_store)
    monkeypatch.setattr(deck_builder, "_RUNTIME_PREMADE_DECKS", {})
    deck_builder.reset_runtime_premades()
