from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import json
import random
import copy
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
import tkinter as tk
from tkinter import filedialog, messagebox

from holywar.ai.simple_ai import choose_action
from holywar.app_paths import appdata_dir
from holywar.core.engine import GameEngine
from holywar.core.state import GameState
from holywar.data.deck_builder import available_premade_decks, get_premade_label
from holywar.effects.runtime import runtime_cards

RELOAD_RESTORE_ENV = "HOLYWAR_RELOAD_RESTORE_PATH"

# This mixin class provides methods for managing the game flow in the GUI, including showing different screens (main menu, game screen, deck manager), handling the start of a new game, managing turn flow and AI actions, handling chain priority during card interactions, and providing options to save the game state and export logs. It interacts with the game engine to execute game actions based on user input and AI decisions, while also updating the GUI accordingly.
class GUIGameFlowMixin:
    """Turn flow, AI loop, chain priority and persistence actions."""

    if TYPE_CHECKING:
        def __getattr__(self, _name: str) -> Any: ...

    # Methods to switch between different GUI sections (main menu, game screen, deck manager) by packing and unpacking the respective frames, allowing the user to navigate through the different parts of the application seamlessly.
    def show_main_menu(self) -> None:
        self.stop_replay_playback()
        self.game_screen.pack_forget()
        self.deck_manager_frame.pack_forget()
        self.replay_manager_frame.pack_forget()
        self.main_menu_frame.pack(fill="both", expand=True)

    # Methods to display the game screen and deck manager by hiding the other sections and showing the relevant frame, as well as syncing the deck filter expansions and reloading user decks when showing the deck manager to ensure that the displayed information is up to date.
    def show_game_screen(self) -> None:
        self.main_menu_frame.pack_forget()
        self.deck_manager_frame.pack_forget()
        self.replay_manager_frame.pack_forget()
        self.game_screen.pack(fill="both", expand=True)
        if not self._replay_playback:
            self._set_replay_ui_mode(False)

    # Methods to display the deck manager screen, hiding the main menu and game screen, and ensuring that the deck filter expansions are synced and user decks are reloaded to reflect any changes or updates made to the decks, providing an up-to-date view of the available decks for the user to manage.
    def show_deck_manager(self) -> None:
        self.main_menu_frame.pack_forget()
        self.game_screen.pack_forget()
        self.replay_manager_frame.pack_forget()
        self.deck_manager_frame.pack(fill="both", expand=True)
        self._sync_deck_filter_expansions()
        self._deck_manager_reload_user_decks()

    def show_replay_manager(self) -> None:
        self.main_menu_frame.pack_forget()
        self.game_screen.pack_forget()
        self.deck_manager_frame.pack_forget()
        self.replay_manager_frame.pack(fill="both", expand=True)
        self._replay_manager_reload()

    # This method updates the options for premade decks in the game setup screen based on the selected religions for player 1 and player 2. It builds a mapping of available premade decks for each religion, updates the dropdown options for selecting premade decks, and ensures that the currently selected premade deck is valid for the chosen religion.
    def update_premade_options(self) -> None:
        def build_map(religion: str) -> dict[str, str | None]:
            out: dict[str, str | None] = {}
            for deck_id, _, _name in available_premade_decks(religion):
                out[get_premade_label(deck_id)] = deck_id
            return out

        self._p1_deck_map = build_map(self.p1_rel_var.get())
        self._p2_deck_map = build_map(self.p2_rel_var.get())
        p1_vals = list(self._p1_deck_map.keys())
        p2_vals = list(self._p2_deck_map.keys())
        self.p1_deck_combo.configure(values=p1_vals)
        self.p2_deck_combo.configure(values=p2_vals)
        if self.p1_deck_var.get() not in self._p1_deck_map:
            self.p1_deck_var.set(p1_vals[0] if p1_vals else "")
        if self.p2_deck_var.get() not in self._p2_deck_map:
            self.p2_deck_var.set(p2_vals[0] if p2_vals else "")

    # This method initializes a new game based on the current settings selected in the game setup screen, including player names, selected premade decks, and game mode (AI or two-player). It creates a new game engine instance with the specified parameters, sets up the necessary callbacks for certain game actions, initializes the random number generator with the provided seed, and resets various state variables related to turn flow and chain interactions. Finally, it updates the status message and refreshes the GUI to reflect the new game state.
    def new_game(self) -> None:
        mode = self.mode_var.get().strip().lower()
        p1 = self.p1_name_var.get().strip() or "Giocatore"
        p2 = self.p2_name_var.get().strip() or ("AI" if mode == "ai" else "Giocatore 2")
        if mode == "ai":
            p2 = "AI"
            self.p2_name_var.set("AI")
        self.update_premade_options()
        p1_deck_id = self._p1_deck_map.get(self.p1_deck_var.get())
        p2_deck_id = self._p2_deck_map.get(self.p2_deck_var.get())
        self.engine = GameEngine.create_new(
            cards=self.cards,
            p1_name=p1,
            p2_name=p2,
            p1_expansion=self.p1_rel_var.get(),
            p2_expansion=self.p2_rel_var.get(),
            p1_premade_deck_id=p1_deck_id,
            p2_premade_deck_id=p2_deck_id,
            seed=self.seed,
        )
        self.engine.choose_battle_survival_from_graveyard = self._choose_battle_survival_from_graveyard
        self.engine.choose_auto_play_drawn_card = self._choose_auto_play_drawn_card
        self.engine.choose_auto_play_slot_from_draw = self._choose_auto_play_slot_from_draw
        self.engine.choose_summon_slot = self._choose_summon_slot
        self.rng = random.Random(self.seed)
        self.last_log_idx = 0
        self.turn_started = False
        self.ai_running = False
        self.chain_active = False
        self.chain_priority_idx = 0
        self.chain_pass_count = 0
        self._reveal_prompt_open = False
        self._reveal_prompt_last_uid = ""
        self._post_reveal_chain_actor = None
        self._replay_playback = False
        self._replay_loaded_snapshots = []
        self._replay_loaded_name = ""
        self._replay_index = 0
        self._replay_snapshots = []
        self._replay_last_signature = ""
        self.status_var.set("Partita avviata")
        self.refresh()
        self.begin_turn_if_needed()

    # This method returns the index of the current human player based on the game state and mode. If the game engine is not initialized, it returns None. If a chain is active, it returns the index of the player with priority in the chain. If the game mode is AI, it assumes player 0 is human and returns 0. Otherwise, it returns the index of the active player from the game engine's state.
    def current_human_idx(self) -> int | None:
        if self.engine is None:
            return None
        if self.chain_active:
            return self.chain_priority_idx
        if self.mode_var.get() == "ai":
            return 0
        return self.engine.state.active_player

    # This method determines whether the human player can currently take actions based on the game state, mode, and whether a chain is active. It checks if the game engine is initialized and if there is a winner, then evaluates the conditions for chain interactions and AI turns to determine if the human player has the opportunity to act at the current moment in the game.
    def can_human_act(self) -> bool:
        if self._replay_playback:
            return False
        if self.engine is None or self.engine.state.winner is not None:
            return False
        if self.chain_active:
            if self.mode_var.get() == "ai":
                return self.chain_priority_idx == 0
            return True
        if self.ai_running:
            return False
        if self.mode_var.get() == "ai" and self.engine.state.active_player == 1:
            return False
        return True

    # This method manages the flow of turns in the game, starting a new turn if necessary when the previous turn has ended and there is no winner. It also checks if the game mode is AI and if it's the AI's turn to act, in which case it initiates the AI turn by calling the appropriate method to start the AI's decision-making process.
    def begin_turn_if_needed(self) -> None:
        if self._replay_playback:
            return
        if self.engine is None or self.ai_running:
            return
        guard = 0
        while not self.turn_started and self.engine.state.winner is None and guard < 8:
            guard += 1
            self.engine.start_turn()
            # If the turn has been auto-closed inside start_turn (e.g. Albero Sacro),
            # phase returns to setup and we must immediately start the next one.
            self.turn_started = self.engine.state.phase != "setup"
            self.refresh()
        if self.mode_var.get() == "ai" and self.engine and self.engine.state.active_player == 1 and not self.ai_running:
            self.start_ai_turn()

    # This method initiates the AI's turn by setting the appropriate flags and scheduling the first step of the AI's decision-making process after a short delay. It ensures that the AI's actions are executed in a way that allows for smooth integration with the GUI and provides a responsive experience for the user while the AI is processing its turn.
    def start_ai_turn(self) -> None:
        self.ai_running = True
        self._ai_steps = 0
        self.after(max(50, self.ai_delay_ms), self.ai_step)

    # This method represents a single step in the AI's decision-making process during its turn. It checks the game state to determine if the AI can continue acting, and if so, it uses the choose_action function to determine the next action for the AI to take. If the AI decides to pass or if it reaches a certain number of steps without taking an action, it ends the AI's turn. Otherwise, it continues scheduling further steps until the turn is complete.
    def ai_step(self) -> None:
        if self.engine is None:
            self.ai_running = False
            return
        if self.engine.state.winner is not None or self.engine.state.active_player != 1:
            self.ai_running = False
            self.refresh()
            return
        if bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
            self._maybe_show_runtime_reveal()
            if bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
                self.after(max(50, self.ai_delay_ms), self.ai_step)
                return
        self._ai_steps += 1
        result = choose_action(self.engine, 1, self.rng)
        if result.ok and result.message != "AI passa.":
            self.start_chain(actor_idx=1)
            self.refresh()
            if self.chain_active:
                # Pause AI turn until chain resolves.
                return
        self.refresh()
        if result.message == "AI passa." or self._ai_steps >= 24:
            self.engine.end_turn()
            self.turn_started = False
            self.ai_running = False
            self.refresh()
            self.begin_turn_if_needed()
            return
        self.after(max(50, self.ai_delay_ms), self.ai_step)

    # This method enables or disables the chain interaction feature in the game, allowing players to respond to actions with quick plays. It updates the internal state to reflect whether chains are enabled and updates the status message accordingly to inform the player of the current state of chain interactions.
    def set_chain_enabled(self, enabled: bool) -> None:
        self.chain_enabled.set(enabled)
        self.status_var.set(f"Catena {'abilitata' if enabled else 'disabilitata'}.")

    # This method retrieves the indexes of cards in the player's hand that are considered "quick" cards, which can be played in response to certain actions during a chain. It checks the player's hand for cards that are of type "Benedizione", "Maledizione", or specifically named "Moribondo", and returns a list of their indexes in the hand for use in determining valid quick play options during chain interactions.
    def _quick_hand_indexes(self, player_idx: int) -> list[int]:
        if self.engine is None:
            return []
        p = self.engine.state.players[player_idx]
        out: list[int] = []
        for i, uid in enumerate(p.hand):
            inst = self.engine.state.instances[uid]
            ctype = inst.definition.card_type.lower()
            allows_quick_play = runtime_cards.allows_quick_play(inst.effect_name, inst.definition.card_type)
            if ctype in {"benedizione", "maledizione"} or allows_quick_play:
                out.append(i)
        return out

    # This method determines the default target for a quick play action based on the player's hand and the current game state. It checks the player's hand for quick cards and identifies valid targets on the board, such as attack or defense slots, artifacts, or buildings, prioritizing targets based on the card being played and the opponent's board state. This helps streamline the quick play process by suggesting a default target for the player when they choose to respond with a quick card during a chain interaction.
    def _default_quick_target_for(self, player_idx: int, hand_idx: int) -> str | None:
        if self.engine is None:
            return None
        p = self.engine.state.players[player_idx]
        uid = p.hand[hand_idx]
        inst = self.engine.state.instances[uid]
        ctype = inst.definition.card_type.lower()
        if runtime_cards.quick_target_owner(inst.effect_name, inst.definition.card_type) == "me":
            for i in range(3):
                if p.attack[i] is not None:
                    return f"a{i+1}"
                if p.defense[i] is not None:
                    return f"d{i+1}"
            return None
        opp = self.engine.state.players[1 - player_idx]
        for i in range(3):
            if opp.attack[i] is not None:
                return f"a{i+1}"
            if opp.defense[i] is not None:
                return f"d{i+1}"
        for i in range(4):
            if opp.artifacts[i] is not None:
                return f"r{i+1}"
        if opp.building is not None:
            return "b"
        return None

    # This method checks if the specified player index corresponds to an AI-controlled player based on the current game mode. It returns True if the game mode is set to "ai" and the player index is 1 (indicating the second player), which is typically designated as the AI opponent in a single-player game against AI. This helps determine whether certain actions or prompts should be handled automatically for the AI player or if user input is required for a human player.
    def _is_ai_player(self, player_idx: int) -> bool:
        return self.mode_var.get() == "ai" and player_idx == 1

    # This method handles the process of choosing a card from the graveyard to activate a battle survival effect when a card is defeated in battle. It checks if there are valid candidate cards in the graveyard, prompts the player to decide whether they want to activate the effect, and if so, allows them to select a card from the graveyard to use for the survival effect. If the player is an AI, it automatically selects the first valid card from the graveyard without prompting.
    def _choose_battle_survival_from_graveyard(
        self,
        player_idx: int,
        source_uid: str,
        candidate_uids: list[str],
    ) -> str | None:
        if self.engine is None:
            return None

        if not candidate_uids:
            return None

        # Se il controllore è AI, usa fallback automatico sulla prima carta valida.
        if self._is_ai_player(player_idx):
            return candidate_uids[0]

        source_inst = self.engine.state.instances.get(source_uid)
        source_name = source_inst.definition.name if source_inst is not None else "questa carta"
        player_name = self.engine.state.players[player_idx].name

        wants = messagebox.askyesno(
            "Effetto di sopravvivenza",
            f"{player_name}: {source_name} è stato sconfitto in battaglia.\n\n"
            "Vuoi attivare il suo effetto per annullare la distruzione?",
        )
        if not wants:
            return None

        choices: list[tuple[str, str]] = []
        for g_uid in candidate_uids:
            inst = self.engine.state.instances.get(g_uid)
            if inst is None:
                continue
            label = inst.definition.name
            choices.append((label, g_uid))

        if not choices:
            return None

        canceled, selected = self._open_board_target_picker(
            title="Scegli carta da scomunicare",
            prompt="Seleziona quale carta del tuo cimitero scomunicare per salvare Thor.",
            choices=choices,
            allow_multi=False,
            min_targets=1,
            max_targets=1,
            allow_none=False,
            allow_manual=False,
            card_uid=source_uid,
        )
        if canceled or not selected:
            return None

        return selected

    # This method handles the process of choosing a slot for automatically playing a card drawn from the deck. It checks if there are valid slot options available, prompts the player to select a slot for placing the drawn card, and returns the chosen slot token. If the player is an AI, it automatically selects the first available slot without prompting.
    def _choose_auto_play_slot_from_draw(
        self,
        player_idx: int,
        source_uid: str,
        slot_tokens: list[str],
    ) -> str | None:
        if self.engine is None:
            return slot_tokens[0] if slot_tokens else None
        if not slot_tokens:
            return None

        # AI side: deterministic first available slot.
        if self._is_ai_player(player_idx):
            return slot_tokens[0]
        # Human side: auto-effects should not open looping slot pickers.
        # Keep deterministic placement by choosing the first valid slot.
        return str(slot_tokens[0]).strip().lower()

    def _choose_summon_slot(
        self,
        player_idx: int,
        source_uid: str,
        slot_tokens: list[str],
    ) -> str | None:
        if self.engine is None:
            return slot_tokens[0] if slot_tokens else None
        if not slot_tokens:
            return None
        if self._is_ai_player(player_idx):
            return str(slot_tokens[0]).strip().lower()

        own_idx = self.current_human_idx()
        if own_idx is None:
            own_idx = player_idx

        choices: list[tuple[str, str]] = []
        for token in slot_tokens:
            base = str(token or "").strip().lower()
            if not base:
                continue
            side_prefix = "TUO" if player_idx == own_idx else "AVVERSARIO"
            if base.startswith("a") and len(base) == 2 and base[1].isdigit():
                label = f"{side_prefix} | Attacco {base[1]}"
            elif base.startswith("d") and len(base) == 2 and base[1].isdigit():
                label = f"{side_prefix} | Difesa {base[1]}"
            else:
                label = f"{side_prefix} | {base.upper()}"
            choices.append((label, base))
        if not choices:
            return None

        canceled, selected = self._open_board_target_picker(
            title="Scegli locazione evocazione",
            prompt="Seleziona dove evocare la carta.",
            choices=choices,
            allow_multi=False,
            min_targets=1,
            max_targets=1,
            allow_none=False,
            allow_manual=False,
            card_uid=source_uid,
        )
        if canceled or not selected:
            return None
        return str(selected).strip().lower()

    def _choose_auto_play_drawn_card(
        self,
        player_idx: int,
        source_uid: str,
    ) -> bool:
        if self.engine is None:
            return True

        if self._is_ai_player(player_idx):
            return True

        inst = self.engine.state.instances.get(source_uid)
        card_name = inst.definition.name if inst is not None else "questa carta"
        player_name = self.engine.state.players[player_idx].name
        return messagebox.askyesno(
            "Effetto di Nun",
            f"{player_name} ha pescato {card_name}.\n\n"
            "Vuoi evocarla subito grazie a Nun?",
        )

    # This method prompts the human player to decide whether they want to activate cards in response to an action during a chain interaction. It displays a yes/no dialog asking the player if they want to activate cards in the chain at that moment, and returns True if the player chooses to activate, or False if they choose to pass. This allows the player to make strategic decisions about when to respond with quick plays during chain interactions.
    def _prompt_human_chain_decision(self, player_idx: int) -> bool:
        if self.engine is None:
            return False
        p = self.engine.state.players[player_idx]
        return messagebox.askyesno("Catena", f"{p.name}, vuoi attivare carte in catena ora?")

    # This method registers a pass action for the current player in the chain interaction. It increments the count of consecutive passes, checks if the chain should end based on the number of passes, and if not, it switches the priority to the other player and refreshes the GUI. This is called when a player chooses to pass their opportunity to respond in a chain interaction, allowing the game to progress through the chain until it resolves or ends due to consecutive passes.
    def _register_chain_pass_current(self) -> None:
        if not self.chain_active or self.engine is None:
            return
        self.chain_pass_count += 1
        if self.chain_pass_count >= 2:
            self.end_chain()
            return
        self.chain_priority_idx = 1 - self.chain_priority_idx
        self.refresh()
        self._handle_chain_priority()

    # This method handles the priority of actions during a chain interaction. It checks if the chain is active and if the game engine is initialized, then determines which player has priority in the chain. If the player with priority is an AI, it automatically processes the AI's response to the chain. If the player with priority is human, it prompts
    def _handle_chain_priority(self) -> None:
        if not self.chain_active or self.engine is None:
            return
        prio = self.chain_priority_idx
        if self._is_ai_player(prio):
            self._maybe_ai_chain_action()
            return
        # Human side: always ask whether they want to activate now.
        wants = self._prompt_human_chain_decision(prio)
        if not wants:
            self._register_chain_pass_current()

    # This method initiates a chain interaction when a player takes an action that can be responded to with quick plays. It checks if the game engine is initialized, if chains are enabled, and if a chain is not already active. It then determines the defender player index and checks if they have valid quick cards in hand. If all conditions are met, it activates the chain, sets the priority to the defender, resets the pass count, refreshes the GUI, and handles the chain priority to allow for responses from the players.
    def start_chain(self, actor_idx: int) -> None:
        if self.engine is None or not self.chain_enabled.get() or self.chain_active:
            return
        defender_idx = 1 - actor_idx
        if not self._quick_hand_indexes(defender_idx):
            return
        self.chain_active = True
        self.chain_priority_idx = defender_idx
        self.chain_pass_count = 0
        self.refresh()
        self._handle_chain_priority()

    # This method checks if the AI player has valid quick cards in hand and automatically plays one of them in response to a chain interaction if the AI has priority. It iterates through the AI player's hand for quick cards, determines a default target for each card, and attempts to play it as a quick response. If the AI successfully plays a card, it resets the chain pass count and priority, refreshes the GUI, and continues handling chain priority. If the AI chooses to pass or has no valid quick cards, it registers a pass for the AI in the chain.
    def _maybe_ai_chain_action(self) -> None:
        if self.engine is None or not self.chain_active:
            return
        if not self._is_ai_player(self.chain_priority_idx):
            return
        # AI either plays one quick response or passes priority.
        played = False
        for i in self._quick_hand_indexes(1):
            target = self._default_quick_target_for(1, i)
            res = self.engine.quick_play(1, i, target)
            if res.ok:
                played = True
                break
        if played:
            self.chain_pass_count = 0
            self.chain_priority_idx = 0
            self.refresh()
            self._handle_chain_priority()
            return
        self._register_chain_pass_current()

    # This method ends the current chain interaction, resetting the relevant state variables and resuming the AI's turn if it was paused waiting for chain resolution. It sets the chain as inactive, resets the pass count, and if the AI was running and it's the AI's turn, it schedules the next step of the AI's decision-making process. Finally, it refreshes the GUI to reflect the end of the chain interaction.
    def end_chain(self) -> None:
        self.chain_active = False
        self.chain_pass_count = 0
        # Resume AI main turn if it was paused waiting for chain resolution.
        if self.engine and self.ai_running and self.engine.state.active_player == 1:
            self.after(max(50, self.ai_delay_ms), self.ai_step)
        self.refresh()

    # This method registers a pass action for the current player in the chain interaction when they choose to pass their opportunity to respond. It checks if a chain is active and if the game engine is initialized, then calls the internal method to register the pass for the current player, allowing the chain to progress based on the players' decisions to respond or pass during the interaction.
    def chain_ok(self) -> None:
        if not self.chain_active or self.engine is None:
            return
        self._register_chain_pass_current()

    # This method ends the current player's turn, ensuring that the game engine is initialized and that the AI is not currently running. It also checks if a chain is active, in which case it prompts the player to resolve the chain before ending the turn. If all conditions are met, it calls the game engine's method to end the turn, resets the turn state, refreshes the GUI, and begins the next turn if needed.
    def end_turn(self) -> None:
        if self.engine is None or self.ai_running:
            return
        if self.chain_active:
            messagebox.showwarning("Catena", "Chiudi prima la catena (OK Catena fino a doppio pass).")
            return
        if not self.can_human_act():
            return
        self.engine.end_turn()
        self.turn_started = False
        self.refresh()
        self.begin_turn_if_needed()

    # This method saves the current game state to a JSON file. It checks if the game engine is initialized, then prompts the user to choose a file location for saving the game. If a valid path is selected, it calls the game engine's save method to write the game state to the specified file and updates the status message to indicate that the game has been saved successfully.
    def save_game(self) -> None:
        if self.engine is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.engine.state.save(path)
        self.status_var.set(f"Partita salvata: {path}")

    def reload_scripts(self) -> None:
        try:
            do_restart = messagebox.askyesno(
                "Reload Completo",
                "Verrà riavviata l'app per ricaricare TUTTO il codice (GUI, engine, script carte).\n"
                "La partita corrente verrà salvata e ripristinata automaticamente al riavvio.\n\n"
                "Continuare?",
            )
            if not do_restart:
                return

            # Keep a best-effort script reload before restart so any bootstrap errors
            # are surfaced immediately to the user.
            runtime_cards.clear_for_tests()
            runtime_cards._bootstrap_from_cards_json()  # noqa: SLF001
            runtime_cards._bootstrap_from_script_files()  # noqa: SLF001

            restore_payload: dict[str, Any] = {
                "gui": {
                    "mode": str(self.mode_var.get() or "ai"),
                    "p1_name": str(self.p1_name_var.get() or ""),
                    "p2_name": str(self.p2_name_var.get() or ""),
                    "p1_rel": str(self.p1_rel_var.get() or ""),
                    "p2_rel": str(self.p2_rel_var.get() or ""),
                    "p1_deck": str(self.p1_deck_var.get() or ""),
                    "p2_deck": str(self.p2_deck_var.get() or ""),
                    "chain_enabled": bool(self.chain_enabled.get()),
                }
            }
            if self.engine is not None:
                restore_payload["state"] = self.engine.state.to_dict()

            restore_dir = appdata_dir() / "temp"
            restore_dir.mkdir(parents=True, exist_ok=True)
            restore_path = restore_dir / "reload_restore_state.json"
            restore_path.write_text(json.dumps(restore_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.environ[RELOAD_RESTORE_ENV] = str(restore_path)

            self.status_var.set("Riavvio in corso...")
            self.update_idletasks()

            if getattr(sys, "frozen", False):
                os.execv(sys.executable, [sys.executable, *sys.argv[1:]])

            # Always relaunch as module to guarantee package imports
            # (running a package file directly can break "import holywar").
            relaunch_args = [sys.executable, "-m", "holywar.gui", *sys.argv[1:]]
            os.execv(sys.executable, relaunch_args)
        except Exception as exc:
            messagebox.showerror("Reload Scripts", f"Errore durante il reload degli script:\n{exc}")

    def restore_after_full_reload(self, restore_path: str) -> None:
        path = Path(str(restore_path or "").strip())
        if not str(path):
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            return

        try:
            gui = dict(payload.get("gui", {}) or {})
            self.mode_var.set(str(gui.get("mode", self.mode_var.get() or "ai")))
            self.p1_name_var.set(str(gui.get("p1_name", self.p1_name_var.get() or "")))
            self.p2_name_var.set(str(gui.get("p2_name", self.p2_name_var.get() or "")))
            self.p1_rel_var.set(str(gui.get("p1_rel", self.p1_rel_var.get() or "")))
            self.p2_rel_var.set(str(gui.get("p2_rel", self.p2_rel_var.get() or "")))
            self.update_premade_options()
            self.p1_deck_var.set(str(gui.get("p1_deck", self.p1_deck_var.get() or "")))
            self.p2_deck_var.set(str(gui.get("p2_deck", self.p2_deck_var.get() or "")))
            self.chain_enabled.set(bool(gui.get("chain_enabled", self.chain_enabled.get())))

            state_payload = payload.get("state")
            if isinstance(state_payload, dict) and state_payload:
                self.engine = GameEngine(GameState.from_dict(state_payload), seed=self.seed)
                self.engine.choose_battle_survival_from_graveyard = self._choose_battle_survival_from_graveyard
                self.engine.choose_auto_play_drawn_card = self._choose_auto_play_drawn_card
                self.engine.choose_auto_play_slot_from_draw = self._choose_auto_play_slot_from_draw
                self.engine.choose_summon_slot = self._choose_summon_slot
                self.last_log_idx = 0
                self.turn_started = self.engine.state.phase != "setup"
                self.ai_running = False
                self.chain_active = False
                self.chain_pass_count = 0
                self._replay_playback = False
                self._replay_loaded_snapshots = []
                self._replay_loaded_name = ""
                self._replay_index = 0
                self._replay_snapshots = []
                self._replay_last_signature = ""
                self.status_var.set("Partita ripristinata dopo reload completo.")
                self.show_game_screen()
                self.refresh()
            else:
                self.status_var.set("Reload completo eseguito.")
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def _replay_dir(self) -> Path:
        out = appdata_dir() / "replays"
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _capture_replay_snapshot_if_changed(self, label: str = "") -> None:
        if self.engine is None or self._replay_playback:
            return
        payload = copy.deepcopy(self.engine.state.to_dict())
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if signature == self._replay_last_signature:
            return
        self._replay_last_signature = signature
        if not label:
            active = self.engine.state.players[self.engine.state.active_player].name
            label = f"Turno {self.engine.state.turn_number} | {self.engine.state.phase} | Attivo: {active}"
        self._replay_snapshots.append({"label": str(label), "state": copy.deepcopy(payload)})

    def save_replay(self) -> None:
        if self.engine is None:
            return
        self._capture_replay_snapshot_if_changed()
        if not self._replay_snapshots:
            messagebox.showwarning("Replay", "Nessun replay disponibile da salvare.")
            return
        default_name = f"replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        replay_dir = self._replay_dir()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(replay_dir),
            initialfile=default_name,
            title="Salva replay",
        )
        if not path:
            return
        winner = self.engine.state.winner
        winner_name = self.engine.state.players[winner].name if winner is not None else None
        data = {
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "meta": {
                "p1": self.engine.state.players[0].name,
                "p2": self.engine.state.players[1].name,
                "winner": winner_name,
                "turn": int(self.engine.state.turn_number),
                "snapshots": len(self._replay_snapshots),
            },
            "snapshots": self._replay_snapshots,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_var.set(f"Replay salvato: {path}")

    def _replay_manager_reload(self) -> None:
        if not hasattr(self, "replay_list"):
            return
        self.replay_list.delete(0, tk.END)
        replay_dir = self._replay_dir()
        files = sorted(replay_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            self.replay_list.insert(tk.END, p.name)
        self._replay_set_detail("Seleziona un replay per vedere i dettagli.")

    def _replay_set_detail(self, text: str) -> None:
        if not hasattr(self, "replay_detail_text"):
            return
        self.replay_detail_text.configure(state="normal")
        self.replay_detail_text.delete("1.0", tk.END)
        self.replay_detail_text.insert(tk.END, text)
        self.replay_detail_text.configure(state="disabled")

    def _selected_replay_path(self) -> Path | None:
        if not hasattr(self, "replay_list"):
            return None
        sel = self.replay_list.curselection()
        if not sel:
            return None
        name = str(self.replay_list.get(sel[0])).strip()
        if not name:
            return None
        return self._replay_dir() / name

    def _replay_on_select(self, _event=None) -> None:
        path = self._selected_replay_path()
        if path is None or not path.exists():
            self._replay_set_detail("Seleziona un replay per vedere i dettagli.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._replay_set_detail(f"Impossibile leggere replay:\n{exc}")
            return
        meta = dict(data.get("meta", {}) or {})
        snapshots = list(data.get("snapshots", []) or [])
        msg = (
            f"File: {path.name}\n"
            f"Creato: {data.get('created_at', '-')}\n"
            f"P1: {meta.get('p1', '-')}\n"
            f"P2: {meta.get('p2', '-')}\n"
            f"Vincitore: {meta.get('winner', '-')}\n"
            f"Turno finale: {meta.get('turn', '-')}\n"
            f"Snapshot: {len(snapshots)}"
        )
        self._replay_set_detail(msg)

    def replay_delete_selected(self) -> None:
        path = self._selected_replay_path()
        if path is None or not path.exists():
            messagebox.showwarning("Replay", "Seleziona un replay da eliminare.")
            return
        if not messagebox.askyesno("Replay", f"Eliminare il replay '{path.name}'?"):
            return
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            messagebox.showerror("Replay", f"Errore durante eliminazione:\n{exc}")
            return
        self._replay_manager_reload()

    def replay_rename_selected(self) -> None:
        path = self._selected_replay_path()
        if path is None or not path.exists():
            messagebox.showwarning("Replay", "Seleziona un replay da rinominare.")
            return
        new_name = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(path.parent),
            initialfile=path.name,
            title="Rinomina replay",
        )
        if not new_name:
            return
        new_path = Path(new_name)
        if new_path.suffix.lower() != ".json":
            new_path = new_path.with_suffix(".json")
        if new_path == path:
            return
        if new_path.exists():
            messagebox.showwarning("Replay", "Esiste già un replay con questo nome.")
            return
        try:
            path.rename(new_path)
        except Exception as exc:
            messagebox.showerror("Replay", f"Errore durante rinomina:\n{exc}")
            return
        self._replay_manager_reload()

    def exit_replay_to_manager(self) -> None:
        self.stop_replay_playback()
        self.show_replay_manager()

    def replay_play_selected(self) -> None:
        path = self._selected_replay_path()
        if path is None or not path.exists():
            messagebox.showwarning("Replay", "Seleziona un replay da riprodurre.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Replay", f"Impossibile leggere replay:\n{exc}")
            return
        snapshots = list(data.get("snapshots", []) or [])
        if not snapshots:
            messagebox.showwarning("Replay", "Replay vuoto.")
            return
        self.stop_replay_playback()
        self._replay_playback = True
        self._replay_paused = False
        self._replay_loaded_name = path.name
        self._replay_loaded_snapshots = snapshots
        self._replay_index = 0
        self._replay_step_ms = max(300, int(self._replay_step_ms or 1000))
        self.turn_started = True
        self.ai_running = False
        self.chain_active = False
        self.show_game_screen()
        self._set_replay_ui_mode(True)
        self._replay_apply_current_snapshot()
        self._replay_schedule_next_step()

    def _replay_apply_current_snapshot(self) -> None:
        if not self._replay_loaded_snapshots:
            return
        snap = self._replay_loaded_snapshots[self._replay_index]
        state_payload = dict(snap.get("state", {}) or {})
        flags = dict(state_payload.get("flags", {}) or {})
        flags["_runtime_waiting_for_reveal"] = False
        flags.pop("_runtime_reveal_card", None)
        state_payload["flags"] = flags
        self.engine = GameEngine(GameState.from_dict(state_payload), seed=self.seed)
        self.last_log_idx = 0
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", tk.END)
            self.log_text.configure(state="disabled")
        self.refresh()
        total = len(self._replay_loaded_snapshots)
        label = str(snap.get("label", "")).strip()
        self.status_var.set(
            f"Replay {self._replay_loaded_name}: step {self._replay_index + 1}/{total}"
            + (f" | {label}" if label else "")
        )

    def _replay_schedule_next_step(self) -> None:
        if not self._replay_playback:
            return
        if self._replay_paused:
            self._replay_after_id = None
            return
        if self._replay_index >= len(self._replay_loaded_snapshots) - 1:
            self.status_var.set(f"Replay completato: {self._replay_loaded_name}")
            self._replay_after_id = None
            return
        self._replay_after_id = self.after(max(120, int(self._replay_step_ms)), self._replay_step)

    def _replay_step(self) -> None:
        if not self._replay_playback:
            return
        self._replay_index += 1
        if self._replay_index >= len(self._replay_loaded_snapshots):
            self.status_var.set(f"Replay completato: {self._replay_loaded_name}")
            self._replay_after_id = None
            return
        self._replay_apply_current_snapshot()
        self._replay_schedule_next_step()

    def stop_replay_playback(self) -> None:
        if self._replay_after_id:
            try:
                self.after_cancel(self._replay_after_id)
            except Exception:
                pass
        self._replay_after_id = None
        self._replay_playback = False
        self._replay_paused = False
        self._replay_loaded_snapshots = []
        self._replay_loaded_name = ""
        self._replay_index = 0
        self._set_replay_ui_mode(False)

    def _set_replay_ui_mode(self, enabled: bool) -> None:
        if enabled:
            if hasattr(self, "game_top_frame"):
                self.game_top_frame.pack_forget()
            if hasattr(self, "replay_controls_frame"):
                self.replay_controls_frame.pack(fill="x", padx=8, pady=(4, 0))
            if hasattr(self, "replay_playpause_btn"):
                self.replay_playpause_btn.configure(text="Pausa" if not self._replay_paused else "Riprendi")
            if hasattr(self, "replay_speed_label"):
                self.replay_speed_label.configure(text=f"{int(self._replay_step_ms)} ms/step")
        else:
            if hasattr(self, "replay_controls_frame"):
                self.replay_controls_frame.pack_forget()
            if hasattr(self, "game_top_frame"):
                self.game_top_frame.pack(fill="x", padx=8, pady=8)

    def replay_toggle_pause(self) -> None:
        if not self._replay_playback:
            return
        self._replay_paused = not self._replay_paused
        if hasattr(self, "replay_playpause_btn"):
            self.replay_playpause_btn.configure(text="Riprendi" if self._replay_paused else "Pausa")
        if not self._replay_paused:
            self._replay_schedule_next_step()

    def replay_change_speed(self, factor: float) -> None:
        if factor <= 0:
            return
        self._replay_step_ms = max(120, min(10000, int(self._replay_step_ms * factor)))
        if hasattr(self, "replay_speed_label"):
            self.replay_speed_label.configure(text=f"{int(self._replay_step_ms)} ms/step")
        if self._replay_playback and not self._replay_paused:
            if self._replay_after_id:
                try:
                    self.after_cancel(self._replay_after_id)
                except Exception:
                    pass
                self._replay_after_id = None
            self._replay_schedule_next_step()

    def replay_jump_to_turn(self) -> None:
        if not self._replay_playback or not self._replay_loaded_snapshots:
            return
        jump_var = getattr(self, "replay_jump_turn_var", None)
        raw = str(jump_var.get() if jump_var is not None else "").strip()
        if not raw:
            return
        try:
            wanted_turn = int(raw)
        except ValueError:
            messagebox.showwarning("Replay", "Turno non valido.")
            return
        idx = None
        for i, snap in enumerate(self._replay_loaded_snapshots):
            state_payload = dict(snap.get("state", {}) or {})
            turn_number = int(state_payload.get("turn_number", 0) or 0)
            if turn_number >= wanted_turn:
                idx = i
                break
        if idx is None:
            idx = len(self._replay_loaded_snapshots) - 1
        self._replay_index = idx
        self._replay_apply_current_snapshot()
        if not self._replay_paused:
            self._replay_schedule_next_step()

    # This method exports the game logs to a text file. It checks if the game engine is initialized, then prompts the user to choose a file location for exporting the logs. If a valid path is selected, it calls the game engine's method to export the logs to the specified file and updates the status message to indicate that the log has been exported successfully.
    def export_log(self) -> None:
        if self.engine is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if not path:
            return
        self.engine.export_logs(path)
        self.status_var.set(f"Log esportato: {path}")
