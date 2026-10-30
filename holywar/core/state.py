from __future__ import annotations

import json
import copy
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from holywar.data.models import CardDefinition


ATTACK_SLOTS = 3
DEFENSE_SLOTS = 3
ARTIFACT_SLOTS = 4
MAX_HAND = 8
TURN_INSPIRATION = 10

# Note: The GameState and related classes are designed to be serializable to JSON for easy saving/loading of game states, as well as for potential use in a GUI or networked environment where the state needs to be transmitted. The to_dict and from_dict methods handle the conversion between the class instances and plain dictionaries that can be easily serialized. The save and load methods on GameState provide convenient ways to persist the game state to a file and load it back, which can be useful for features like saving progress or debugging.
@dataclass(slots=True)
class CardInstance:
    uid: str
    definition: CardDefinition
    owner: int
    current_faith: int | None
    exhausted: bool = False
    blessed: list[str] = field(default_factory=list)
    cursed: list[str] = field(default_factory=list)

    @property
    def effect_name(self) -> str:
        """Script lookup key; a silenced instance retains its printed identity."""
        return "" if "silenced" in self.cursed else self.definition.name

    # The to_dict and from_dict methods allow for easy serialization and deserialization of CardInstance objects, which is essential for saving game states or transmitting them over a network. The to_dict method converts the CardInstance into a dictionary format, while the from_dict class method creates a CardInstance from a given dictionary, ensuring that all necessary fields are properly handled and any missing optional fields are given default values.
    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "definition": self.definition.to_dict(),
            "owner": self.owner,
            "current_faith": self.current_faith,
            "exhausted": self.exhausted,
            "blessed": self.blessed,
            "cursed": self.cursed,
        }

    # The from_dict method is a class method that takes a dictionary representation of a CardInstance and constructs a new CardInstance object from it. It handles the conversion of the nested CardDefinition as well, ensuring that the entire structure is properly reconstructed from the dictionary format. This allows for seamless deserialization of game states that include card instances, making it easier to manage and persist the state of the game.
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CardInstance":
        return cls(
            uid=data["uid"],
            definition=CardDefinition.from_dict(data["definition"]),
            owner=data["owner"],
            current_faith=data.get("current_faith"),
            exhausted=bool(data.get("exhausted", False)),
            blessed=list(data.get("blessed", [])),
            cursed=list(data.get("cursed", [])),
        )

# The PlayerState class represents the state of an individual player in the game, including their name, decks, hand, graveyard, excommunicated cards, cards on the field (attack, defense, artifacts), building, sin count, inspiration points, and temporary inspiration. The empty class method provides a convenient way to create a new PlayerState with default values for all fields except the player's name. The to_dict and from_dict methods allow for easy serialization and deserialization of PlayerState objects, which is essential for saving game states or transmitting them over a network.
@dataclass(slots=True)
class PlayerState:
    name: str
    deck: list[str]
    white_deck: list[str]
    hand: list[str]
    graveyard: list[str]
    excommunicated: list[str]
    attack: list[str | None]
    defense: list[str | None]
    artifacts: list[str | None]
    building: str | None
    sin: int = 0
    inspiration: int = TURN_INSPIRATION
    temporary_inspiration: int = 0

    # The empty class method allows for the creation of a new PlayerState with default values for all fields except the player's name. This is useful for initializing a new player at the start of a game, where they will have an empty deck, hand, graveyard, etc., and can be populated with the appropriate cards and values as the game progresses.
    @classmethod
    def empty(cls, name: str) -> "PlayerState":
        return cls(
            name=name,
            deck=[],
            white_deck=[],
            hand=[],
            graveyard=[],
            excommunicated=[],
            attack=[None] * ATTACK_SLOTS,
            defense=[None] * DEFENSE_SLOTS,
            artifacts=[None] * ARTIFACT_SLOTS,
            building=None,
        )

    # The to_dict method converts the PlayerState instance into a dictionary format, which can be easily serialized to JSON for saving or transmitting the game state. The from_dict class method takes a dictionary representation of a PlayerState and constructs a new PlayerState object from it, ensuring that all necessary fields are properly handled and any missing optional fields are given default values. This allows for seamless serialization and deserialization of player states, making it easier to manage and persist the state of the game.
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "deck": self.deck,
            "white_deck": self.white_deck,
            "hand": self.hand,
            "graveyard": self.graveyard,
            "excommunicated": self.excommunicated,
            "attack": self.attack,
            "defense": self.defense,
            "artifacts": self.artifacts,
            "building": self.building,
            "sin": self.sin,
            "inspiration": self.inspiration,
            "temporary_inspiration": self.temporary_inspiration,
        }

    # The from_dict method is a class method that takes a dictionary representation of a PlayerState and constructs a new PlayerState object from it. It handles the conversion of all fields, ensuring that any missing optional fields are given default values. This allows for seamless deserialization of game states that include player states, making it easier to manage and persist the state of the game.
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlayerState":
        return cls(
            name=data["name"],
            deck=list(data["deck"]),
            white_deck=list(data["white_deck"]),
            hand=list(data["hand"]),
            graveyard=list(data["graveyard"]),
            excommunicated=list(data["excommunicated"]),
            attack=list(data["attack"]),
            defense=list(data["defense"]),
            artifacts=list(data["artifacts"]),
            building=data.get("building"),
            sin=int(data.get("sin", 0)),
            inspiration=int(data.get("inspiration", TURN_INSPIRATION)),
            temporary_inspiration=int(data.get("temporary_inspiration", 0)),
        )

# The GameState class represents the overall state of the game, including the list of players, the card instances on the field, the active player, turn number, current phase, preparation turns done, coin toss winner, any runtime flags, logs of game events, and the winner of the game if there is one. The to_dict and from_dict methods allow for easy serialization and deserialization of GameState objects, which is essential for saving game states or transmitting them over a network. The save and load methods provide convenient ways to persist the game state to a file and load it back, which can be useful for features like saving progress or debugging.
@dataclass(slots=True)
class GameState:
    players: list[PlayerState]
    instances: dict[str, CardInstance]
    active_player: int
    turn_number: int
    phase: str = "preparation"
    preparation_turns_done: int = 0
    coin_toss_winner: int | None = None
    flags: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    winner: int | None = None

    # The log method allows for adding messages to the game's log, which can be useful for tracking events that occur during the game, such as card plays, attacks, or other significant actions. This can be helpful for debugging, providing feedback to players in a GUI, or keeping a record of the game's progression.
    def log(self, message: str) -> None:
        self.logs.append(message)

    # The to_dict method converts the GameState instance into a dictionary format, which can be easily serialized to JSON for saving or transmitting the game state. The from_dict class method takes a dictionary representation of a GameState and constructs a new GameState object from it, ensuring that all necessary fields are properly handled and any missing optional fields are given default values. This allows for seamless serialization and deserialization of game states, making it easier to manage and persist the state of the game.
    def to_dict(self) -> dict[str, Any]:
        return {
            "players": [p.to_dict() for p in self.players],
            "instances": {k: v.to_dict() for k, v in self.instances.items()},
            "active_player": self.active_player,
            "turn_number": self.turn_number,
            "phase": self.phase,
            "preparation_turns_done": self.preparation_turns_done,
            "coin_toss_winner": self.coin_toss_winner,
            # Deep-copy runtime flags so cloned states used by GUI simulations
            # cannot mutate nested dictionaries of the live match state.
            "flags": copy.deepcopy(self.flags),
            "logs": self.logs,
            "winner": self.winner,
        }

    # The from_dict method is a class method that takes a dictionary representation of a GameState and constructs a new GameState object from it. It handles the conversion of all fields, ensuring that any missing optional fields are given default values. This allows for seamless deserialization of game states, making it easier to manage and persist the state of the game.
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        return cls(
            players=[PlayerState.from_dict(item) for item in data["players"]],
            instances={k: CardInstance.from_dict(v) for k, v in data["instances"].items()},
            active_player=int(data["active_player"]),
            turn_number=int(data["turn_number"]),
            phase=str(data.get("phase", "preparation")),
            preparation_turns_done=int(data.get("preparation_turns_done", 0)),
            coin_toss_winner=data.get("coin_toss_winner"),
            flags=copy.deepcopy(data.get("flags", {})),
            logs=list(data.get("logs", [])),
            winner=data.get("winner"),
        )

    # The save method takes a file path as input and saves the current game state to that file in JSON format. It uses the to_dict method to convert the GameState into a dictionary, which is then serialized to JSON and written to the specified file. The load class method takes a file path as input, reads the JSON data from that file, deserializes it into a dictionary, and then uses the from_dict method to create a new GameState object from that dictionary. This allows for easy saving and loading of game states, which can be useful for features like saving progress or debugging.
    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    # The load class method reads a JSON file from the specified path, deserializes it into a dictionary, and then constructs a GameState object from that dictionary using the from_dict method. This allows for easy loading of game states that have been previously saved to a file, enabling features like resuming a game or analyzing past game states for debugging or improvement purposes.
    @classmethod
    def load(cls, path: str | Path) -> "GameState":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

# The _norm function is a helper function that normalizes a given text string by applying Unicode normalization (NFKD), removing any combining characters, and converting the result to lowercase. This is useful for standardizing card types or other text inputs in a way that allows for consistent comparisons, regardless of variations in formatting, accents, or case. By using this function, the code can reliably compare card types or other strings without being affected by differences in how they are represented.
def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()

# The is_innata_card_type function checks if a given card type string corresponds to the "innata" card type, using the _norm function to ensure that the comparison is case-insensitive and ignores any formatting differences. This allows the code to determine if a card is of the "innata" type in a consistent way, which can be important for applying specific rules or effects that only apply to innata cards.
def is_innata_card_type(card_type: str | None) -> bool:
    return _norm(card_type or "") == "innata"

# The hand_count_for_limit function calculates the number of cards in a player's hand that count towards the maximum hand limit, excluding any innata cards. It iterates through the player's hand and checks each card instance against the provided instances dictionary to determine if it is an innata card or not. This allows the game to enforce a maximum hand size while allowing players to have additional innata cards in their hand without counting against the limit.
def hand_count_for_limit(player: PlayerState, instances: dict[str, CardInstance]) -> int:
    total = 0
    for uid in player.hand:
        inst = instances.get(uid)
        if inst is None:
            total += 1
            continue
        if is_innata_card_type(inst.definition.card_type):
            continue
        total += 1
    return total

# The hand_has_space_for_non_innata function checks if the player's hand has space for additional non-innata cards by comparing the count of non-innata cards in the player's hand against the maximum hand limit. It uses the hand_count_for_limit function to get the count of non-innata cards and returns True if there is still room for more non-innata cards, or False if the hand is already at or above the limit. This is useful for enforcing hand size restrictions while allowing players to have additional innata cards without penalty.
def hand_has_space_for_non_innata(player: PlayerState, instances: dict[str, CardInstance]) -> bool:
    return hand_count_for_limit(player, instances) < MAX_HAND
