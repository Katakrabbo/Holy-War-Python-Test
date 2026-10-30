from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from holywar.app_paths import bundled_data_dir
from holywar.ai.simple_ai import choose_action
from holywar.core.engine import GameEngine
from holywar.effects.runtime import runtime_cards
from holywar.core.state import GameState
from holywar.data.deck_builder import (
    available_premade_decks,
    available_religions,
    export_premades_json,
    get_premade_label,
    register_premades_from_json,
)
from holywar.data.importer import load_cards_from_xlsx, write_cards_json, load_cards_json

# This module implements a command-line interface for the Holy War game engine. It allows users to load card data, start new games, play against an AI opponent, and manage game state through various commands. The CLI provides options for loading card data from an Excel file, exporting test decks, managing premade decks, and saving/loading game states. The main game loop handles user input for playing cards, attacking, activating abilities, and other game actions, while also allowing for quick reactions from the opponent. The CLI is designed to be a simple terminal-based interface for testing and playing the Holy War game engine.
DEFAULT_JSON = bundled_data_dir() / "cards.json"

# This function builds the argument parser for the CLI, defining the various command-line options that can be used to configure the game. It includes options for specifying the path to the card data, loading a saved game state, exporting test decks, managing premade decks, setting a random seed, and configuring AI behavior. The parser is used to parse the command-line arguments when the CLI is executed.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Holy War - MVP terminale")
    parser.add_argument("--deck-xlsx", type=str, default=None, help="Percorso a Holy War.xlsx")
    parser.add_argument("--cards-json", type=str, default=str(DEFAULT_JSON), help="Cache JSON carte")
    parser.add_argument("--load", type=str, default=None, help="Carica partita da file JSON")
    parser.add_argument("--premades-json", type=str, default=None, help="Importa deck premade custom da JSON")
    parser.add_argument("--export-premades-json", type=str, default=None, help="Esporta deck premade in JSON")
    parser.add_argument("--seed", type=int, default=None, help="Seed RNG (se omesso: casuale ad ogni partita)")
    parser.add_argument("--ai-delay", type=float, default=1.2, help="Secondi di pausa tra azioni AI")
    return parser

# This function ensures that the card data is loaded and available for the game engine. It checks if a JSON file with the card data exists at the specified path, and if not, it attempts to load the card data from an Excel file and write it to the JSON file for future use. If neither source is available, it raises an error prompting the user to provide the necessary data. This function is essential for initializing the game engine with the correct card information before starting a game.
def ensure_cards(args: argparse.Namespace):
    json_path = Path(args.cards_json)
    if args.deck_xlsx:
        cards = load_cards_from_xlsx(args.deck_xlsx)
        write_cards_json(cards, json_path)
        return cards
    if json_path.exists():
        return load_cards_json(json_path)
    raise SystemExit("Serve --deck-xlsx almeno al primo avvio per generare il JSON carte.")

# This function prints the current state of the game in a human-readable format. It displays information about the current phase, turn number, active player, and the state of each player's hand, deck, attack/defense/artifact/building slots. The function uses helper functions to format the card information for display. This is useful for players to understand the current game state and make informed decisions during their turn.
def print_state(engine: GameEngine) -> None:
    st = engine.state
    print("\n" + "=" * 70)
    print(
        f"Fase: {st.phase} | Turno {st.turn_number} | Giocatore attivo: {st.players[st.active_player].name}"
    )
    for i, p in enumerate(st.players):
        marker = "*" if i == st.active_player else " "
        print(
            f"{marker} {p.name} | Peccato={p.sin}/100 | Ispirazione={p.inspiration} | Mano={len(p.hand)} | Deck={len(p.deck)}"
        )
        print("  Attacco:", _fmt_slots(engine, p.attack))
        print("  Difesa :", _fmt_slots(engine, p.defense))
        print("  Artef. :", _fmt_slots(engine, p.artifacts))
        print("  Edificio:", _fmt_card(engine, p.building))
    print("=" * 70)

# This function formats the information of a card instance for display. It takes the game engine and the unique identifier of the card as parameters. It retrieves the card instance from the game state and constructs a string that includes the card's name, current faith, and effective strength (if applicable). If the card is not present (e.g., an empty slot), it returns a placeholder string. This function is used to display the cards in the player's attack/defense/artifact/building slots in a readable format.
def _fmt_card(engine: GameEngine, uid: str | None) -> str:
    if not uid:
        return "-"
    inst = engine.state.instances[uid]
    faith = f" F:{inst.current_faith}" if inst.current_faith is not None else ""
    strength_val = (
        engine.get_effective_strength(uid)
        if inst.definition.card_type.lower() in {"santo", "token"}
        else inst.definition.strength
    )
    strength = f" P:{strength_val}" if strength_val is not None else ""
    return f"{inst.definition.name}{faith}{strength}"

# This function formats a list of card instances for display by calling the `_fmt_card` function on each card in the list and joining the results with a separator. It is used to display the contents of the player's attack, defense, artifact, and building slots in a readable format.
def _fmt_slots(engine: GameEngine, slots: list[str | None]) -> str:
    return " | ".join(_fmt_card(engine, uid) for uid in slots)

# This function prints the current state of the game in a human-readable format. It displays information about the current phase, turn number, active player, and the state of each player's hand, deck, attack/defense/artifact/building slots. The function uses helper functions to format the card information for display. This is useful for players to understand the current game state and make informed decisions during their turn.
def print_hand(engine: GameEngine, player_idx: int) -> None:
    p = engine.state.players[player_idx]
    print(f"\nMano di {p.name}:")
    for idx, uid in enumerate(p.hand):
        c = engine.state.instances[uid].definition
        cost = c.faith if c.faith is not None else 0
        print(f"  [{idx}] {c.name} ({c.card_type}) costo={cost} croci={c.crosses}")

# This function prompts the player to choose an expansion from the available options. It displays a list of expansions and asks the player to input the corresponding index to select one. The function validates the input and returns the name of the chosen expansion. This is used during game setup to allow players to select which expansion they want to use for their game.
def choose_expansion(cards, prompt: str) -> str:
    expansions = available_religions(cards)
    print(prompt)
    for i, exp in enumerate(expansions):
        print(f"  [{i}] {exp}")
    while True:
        val = input("> ").strip()
        if val.isdigit() and 0 <= int(val) < len(expansions):
            return expansions[int(val)]
        print("Scelta non valida.")

# This function prompts the player to choose a premade deck for a given religion. It displays a list of available premade decks for the specified religion and asks the player to input the corresponding index to select one. The function also includes an option for "Auto (deck test)" which allows the engine to automatically select a deck for testing purposes. The function validates the input and returns the identifier of the chosen premade deck, or `None` if the auto option is selected. This is used during game setup to allow players to select a premade deck based on their chosen religion.
def choose_premade_for_religion(religion: str, prompt: str) -> str | None:
    decks = available_premade_decks(religion)
    print(prompt)
    print("  [0] Auto (deck test)")
    for i, (deck_id, _, name) in enumerate(decks, 1):
        print(f"  [{i}] {name}")
    while True:
        val = input("> ").strip()
        if val.isdigit():
            idx = int(val)
            if idx == 0:
                return None
            if 1 <= idx <= len(decks):
                return decks[idx - 1][0]
        print("Scelta non valida.")

# This function prompts the player to choose a premade deck for a given religion. It displays a list of available premade decks for the specified religion and asks the player to input the corresponding index to select one. The function also includes an option for "Auto (deck test)" which allows the engine to automatically select a deck for testing purposes. The function validates the input and returns the identifier of the chosen premade deck, or `None` if the auto option is selected. This is used during game setup to allow players to select a premade deck based on their chosen religion.
def prompt_reaction(engine: GameEngine, defender_idx: int) -> None:
    p = engine.state.players[defender_idx]
    while True:
        quick_indexes = []
        for i, uid in enumerate(p.hand):
            inst = engine.state.instances[uid].definition
            t = inst.card_type.lower()
            if runtime_cards.allows_quick_play(inst.name, inst.card_type):
                quick_indexes.append(i)
        if not quick_indexes:
            return
        print(f"{p.name}, reazione? (quick <idx> <target> | pass)")
        cmd = input(f"{p.name}> ").strip()
        if cmd == "pass" or cmd == "":
            return
        parts = cmd.split()
        if parts[0] == "quick" and len(parts) >= 2 and parts[1].isdigit():
            idx = int(parts[1])
            target = parts[2] if len(parts) >= 3 else None
            res = engine.quick_play(defender_idx, idx, target)
            print(res.message)
            continue
        print("Comando reazione non valido.")

# This function runs the AI's turn in an automated manner. It allows the AI to take up to 12 actions during its turn, checking after each action if the game has been won. It also prints the logs of the AI's actions and prompts the opponent for reactions after each action that is not a pass. The function includes a delay between AI actions to simulate thinking time and improve the user experience. After the AI finishes its actions or decides to pass, it ends its turn.
def run_ai_turn(engine: GameEngine, rng: random.Random, player_idx: int, ai_delay: float) -> None:
    for _ in range(12):
        if engine.state.winner is not None:
            return
        before_logs = len(engine.state.logs)
        result = choose_action(engine, player_idx, rng)
        new_logs = engine.state.logs[before_logs:]
        for line in new_logs:
            print(f"[LOG] {line}")
        # Human can respond with quick effects to each AI action.
        if result.message != "AI passa.":
            prompt_reaction(engine, 0)
        if result.message == "AI passa.":
            print("[LOG] AI passa.")
            break
        if ai_delay > 0:
            time.sleep(ai_delay)
    engine.end_turn()

# This function runs the main game loop, allowing players to take turns and perform actions until a winner is determined. It handles user input for various commands such as playing cards, attacking, activating abilities, saving/loading game states, and more. The function also manages the flow of the game, including starting turns, ending turns, and prompting for reactions when necessary. The game state is printed after each action to keep players informed of the current situation. Once a winner is determined, it announces the winner and ends the game.
def run_game(engine: GameEngine, mode: str, seed: int, ai_delay: float) -> None:
    rng = random.Random(seed)
    while engine.state.winner is None:
        active = engine.state.active_player
        player = engine.state.players[active]
        engine.start_turn()

        if mode == "ai" and active == 1:
            run_ai_turn(engine, rng, active, ai_delay)
            continue

        while True:
            if engine.state.winner is not None:
                break
            print_state(engine)
            print_hand(engine, active)
            cmd = input(f"\n{player.name}> ").strip()
            if not cmd:
                continue
            parts = cmd.split()
            op = parts[0].lower()

            if op == "help":
                print("Comandi: state, hand, play <idx> [a1|a2|a3|d1|d2|d3|r1..r4|b], attack <a1..a3|d1..d3> [t1..t3], activate <a1|a2|a3|d1|d2|d3|r1|r2|r3|r4|b> [target], swap <a1..a3> <a1..a3>, quick <idx> [target], save <path>, log <path>, end, quit")
                continue
            if op == "state":
                print_state(engine)
                continue
            if op == "hand":
                print_hand(engine, active)
                continue
            if op == "play" and len(parts) >= 2 and parts[1].isdigit():
                idx = int(parts[1])
                target = parts[2] if len(parts) >= 3 else None
                res = engine.play_card(active, idx, target)
                print(res.message)
                if res.ok and mode == "local":
                    prompt_reaction(engine, 1 - active)
                continue
            if op == "quick" and len(parts) >= 2 and parts[1].isdigit():
                idx = int(parts[1])
                target = parts[2] if len(parts) >= 3 else None
                res = engine.quick_play(active, idx, target)
                print(res.message)
                continue
            if op == "swap" and len(parts) == 3:
                if parts[1].startswith("a") and parts[2].startswith("a"):
                    f = int(parts[1][1]) - 1
                    t = int(parts[2][1]) - 1
                    res = engine.move_attack_positions(active, f, t)
                    print(res.message)
                    continue
            if op == "attack" and len(parts) >= 2:
                source = parts[1].strip().lower()
                from_slot = -99
                if len(source) >= 2 and source[1].isdigit():
                    slot = int(source[1]) - 1
                    if source[0] == "a":
                        from_slot = slot
                    elif source[0] == "d":
                        from_slot = -(slot + 1)
                target_slot = None
                if len(parts) >= 3 and parts[2].startswith("t"):
                    target_slot = int(parts[2][1]) - 1
                res = engine.attack(active, from_slot, target_slot)
                print(res.message)
                if res.ok and mode == "local":
                    prompt_reaction(engine, 1 - active)
                continue
            if op == "activate" and len(parts) >= 2:
                source = parts[1]
                target = parts[2] if len(parts) >= 3 else None
                res = engine.activate_ability(active, source, target)
                print(res.message)
                if res.ok and mode == "local":
                    prompt_reaction(engine, 1 - active)
                continue
            if op == "save" and len(parts) == 2:
                out = engine.state.save(parts[1])
                print(f"Salvato in {out}")
                continue
            if op == "log" and len(parts) == 2:
                out = engine.export_logs(parts[1])
                print(f"Log esportato in {out}")
                continue
            if op == "end":
                engine.end_turn()
                break
            if op == "quit":
                return
            print("Comando non valido. Usa 'help'.")

    winner = engine.state.players[engine.state.winner].name
    print(f"\nPartita terminata. Vincitore: {winner}")

# This function runs the main game loop, allowing players to take turns and perform actions until a winner is determined. It handles user input for various commands such as playing cards, attacking, activating abilities, saving/loading game states, and more. The function also manages the flow of the game, including starting turns, ending turns, and prompting for reactions when necessary. The game state is printed after each action to keep players informed of the current situation. Once a winner is determined, it announces the winner and ends the game.
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.premades_json:
        warns = register_premades_from_json(args.premades_json)
        for w in warns:
            print(f"[WARN PREMADE] {w}")
    if args.export_premades_json:
        out = export_premades_json(args.export_premades_json, include_builtin=True)
        print(f"Premade esportati in {out}")
        return

    if args.load:
        state = GameState.load(args.load)
        engine = GameEngine(state)
        mode = input("Modalita (local/ai)? ").strip().lower() or "local"
        run_game(engine, mode, args.seed, args.ai_delay)
        return

    cards = ensure_cards(args)
    print("Seleziona modalita: [0] 1v1 locale, [1] vs AI")
    mode_pick = input("> ").strip()
    mode = "ai" if mode_pick == "1" else "local"

    p1_name = input("Nome Giocatore 1: ").strip() or "Giocatore 1"
    p2_name = "AI" if mode == "ai" else (input("Nome Giocatore 2: ").strip() or "Giocatore 2")

    p1_expansion = choose_expansion(cards, "Espansione Giocatore 1:")
    p2_expansion = choose_expansion(cards, "Espansione Giocatore 2:")
    print("Selezione deck: [0] Auto test deck, [1] Deck premade")
    deck_mode = input("> ").strip()
    p1_premade = None
    p2_premade = None
    if deck_mode == "1":
        p1_premade = choose_premade_for_religion(p1_expansion, f"Deck premade per {p1_name}:")
        p2_premade = choose_premade_for_religion(p2_expansion, f"Deck premade per {p2_name}:")
        if p1_premade:
            print(f"{p1_name} usa: {get_premade_label(p1_premade)}")
        if p2_premade:
            print(f"{p2_name} usa: {get_premade_label(p2_premade)}")

    engine = GameEngine.create_new(
        cards=cards,
        p1_name=p1_name,
        p2_name=p2_name,
        p1_expansion=p1_expansion,
        p2_expansion=p2_expansion,
        p1_premade_deck_id=p1_premade,
        p2_premade_deck_id=p2_premade,
        seed=args.seed,
    )
    run_game(engine, mode, args.seed, args.ai_delay)


if __name__ == "__main__":
    main()
