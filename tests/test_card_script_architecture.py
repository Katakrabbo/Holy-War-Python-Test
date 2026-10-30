import ast
import importlib
import pkgutil
from pathlib import Path

from holywar.core.engine import GameEngine  # establish the runtime import order
from holywar.data.importer import load_cards_json
from holywar.effects import card_scripts
from holywar.effects.runtime import SUPPORTED_EFFECT_ACTIONS
from holywar.validation import validate_project


ROOT = Path(__file__).resolve().parents[1]


def card_modules():
    package = importlib.import_module(f"{card_scripts.__name__}.cards")
    for item in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(item.name)
        if hasattr(module, "CARD_NAME"):
            yield module


def test_every_catalogue_card_has_one_script_in_its_type_directory() -> None:
    cards = load_cards_json(ROOT / "holywar/data/cards.json")
    modules = list(card_modules())
    for card in cards:
        matching = [module for module in modules if module.CARD_NAME == card.name]
        assert len(matching) == 1, card.name
        assert Path(matching[0].__file__).parent.name == card.card_type.lower(), card.name
    assert validate_project(ROOT / "holywar/data/cards.json").ok


def test_card_specific_extensions_are_implemented_in_the_owning_file() -> None:
    custom_actions = set()
    for module in card_modules():
        for attribute in ("ACTION_HANDLERS", "RULE_HOOKS", "TARGETING_HANDLERS"):
            for key, handler in getattr(module, attribute, {}).items():
                assert callable(handler), (module.CARD_NAME, key)
                assert handler.__module__ == module.__name__, (module.CARD_NAME, key)
                if attribute == "ACTION_HANDLERS":
                    custom_actions.add(key)
    assert custom_actions
    assert custom_actions.isdisjoint(SUPPORTED_EFFECT_ACTIONS)
    for path in (ROOT / "holywar/effects/runtime_sections").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in custom_actions, (path, node.lineno, node.value)


def test_shared_code_does_not_contain_named_card_rules() -> None:
    # Short names such as Set also occur as ordinary programming vocabulary.
    names = {
        card.name.casefold() for card in load_cards_json(ROOT / "holywar/data/cards.json")
        if len(card.name) > 4
    }
    for path in (ROOT / "holywar").rglob("*.py"):
        if "card_scripts" in path.parts or path.name == "premade_decks.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value.casefold() not in names, (path, node.lineno, node.value)
