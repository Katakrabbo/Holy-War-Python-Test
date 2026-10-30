from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import json
from typing import TYPE_CHECKING, Any, cast
import tkinter as tk
from tkinter import messagebox, ttk

from holywar.core import query_helpers as query_ops
from holywar.effects.runtime import runtime_cards

# This mixin class provides methods for rendering the game board and hand, as well as handling user interactions related to these elements. It includes methods for updating the display of player resources, showing card details, and managing interactions with cards in the player's hand and on the board. The methods in this class are designed to work with the game engine's state to ensure that the GUI accurately reflects the current game situation and allows players to interact with their cards effectively.
class GUIGameViewMixin:
    """Board/hand rendering and user interaction handlers."""

    if TYPE_CHECKING:
        def __getattr__(self, _name: str) -> Any: ...

    def _ui_alive(self) -> bool:
        try:
            if int(self.winfo_exists()) != 1:
                return False
            label = getattr(self, "info_label", None)
            if label is not None and int(label.winfo_exists()) != 1:
                return False
            return True
        except Exception:
            return False

    def _board_text_color(self) -> str:
        return str(getattr(self, "_game_palette", {}).get("text", "#f2ead7"))

    def _board_special_text_color(self) -> str:
        return str(getattr(self, "_game_palette", {}).get("gold", "#d4a94f"))

    def _board_alert_text_color(self) -> str:
        return str(getattr(self, "_game_palette", {}).get("danger", "#a84f4f"))

    def _ai_runtime_card_value(self, uid: str) -> int:
        if self.engine is None:
            return 0
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return 0
        ctype = str(inst.definition.card_type or "").strip().lower()
        faith = int(inst.current_faith if inst.current_faith is not None else (inst.definition.faith or 0) or 0)
        strength = 0
        try:
            strength = int(self.engine.get_effective_strength(uid))
        except Exception:
            strength = int(inst.definition.strength or 0 or 0)

        if ctype in {"santo", "token"}:
            return faith * 5 + strength * 8 + 20
        if ctype == "edificio":
            return faith * 3 + 35
        if ctype == "artefatto":
            return faith * 3 + 25
        if ctype in {"benedizione", "maledizione"}:
            return 16
        return 10

    def _ai_pick_runtime_candidates(
        self,
        choice_owner: int,
        candidates: list[str],
        min_targets: int,
        max_targets: int,
        prompt: str,
        title: str,
    ) -> str:
        if self.engine is None or not candidates:
            return ""
        prompt_key = f"{title} {prompt}".lower()
        harmful = any(k in prompt_key for k in ("cimitero", "distrugg", "scarta", "scomunic", "annulla"))
        beneficial = any(k in prompt_key for k in ("evoca", "aggiung", "cura", "ripristina", "potenz", "guadagn"))
        sacrificial = "sacrific" in prompt_key

        scored: list[tuple[int, str]] = []
        for uid in candidates:
            inst = self.engine.state.instances.get(uid)
            if inst is None:
                continue
            same_owner = int(inst.owner) == int(choice_owner)
            base = self._ai_runtime_card_value(uid)
            if sacrificial:
                score = (-base + 200) if same_owner else (base + 50)
            elif harmful:
                score = (base + 500) if not same_owner else (-base + 100)
            elif beneficial:
                score = (base + 500) if same_owner else (-base + 100)
            else:
                score = (base + 120) if not same_owner else (base + 80)
            scored.append((score, uid))

        scored.sort(key=lambda x: x[0], reverse=True)
        ordered = [uid for _, uid in scored] or list(candidates)

        pick_count = max(0, int(min_targets))
        if pick_count == 0:
            pick_count = 1 if ordered else 0
        if max_targets >= 0:
            pick_count = min(pick_count, max_targets)
        pick_count = min(pick_count, len(ordered))
        if pick_count <= 0:
            return ""
        if pick_count == 1:
            return ordered[0]
        return ",".join(ordered[:pick_count])

    def _ai_pick_runtime_value(self, values: list[str], prompt: str, title: str) -> str:
        if not values:
            return ""
        prompt_key = f"{title} {prompt}".lower()
        lowered = [str(v).strip().lower() for v in values]
        if "si" in lowered and "no" in lowered:
            # Default aggressivo: usa l'effetto se disponibile.
            return values[lowered.index("si")]
        if "yes" in lowered and "no" in lowered:
            return values[lowered.index("yes")]
        return values[0]

    def _counter_value(self, inst) -> int:
        script = runtime_cards.get_script(inst.effect_name)
        if script is None or not script.counter_tag:
            return 0
        prefix = f"{script.counter_tag}:"
        for tag in inst.blessed:
            if isinstance(tag, str) and tag.startswith(prefix):
                try:
                    return int(tag[len(prefix):])
                except ValueError:
                    return 0
        return 0

    def _provides_player_counter(self, uid: str | None) -> bool:
        if not uid or self.engine is None:
            return False
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return False
        script = runtime_cards.get_script(inst.definition.name)
        return bool(script and bool(script.provides_player_counter))

    # This method arranges the widgets for the attack, defense, artifacts, and building slots in a grid layout within the specified parent frame. It organizes the widgets into rows and columns, with labels indicating the type of slot (attack, defense, artifacts, building) and the corresponding widgets for each slot type. The method uses padding to ensure proper spacing between the widgets and labels for a clean and organized display of the game board elements.
    def _grid_slots(self, parent, attack, defense, artifacts, building) -> None:
        ttk.Label(parent, text="Attacco").grid(row=0, column=0, sticky="w")
        for i, w in enumerate(attack):
            w.grid(row=1, column=i, padx=2, pady=2)
        ttk.Label(parent, text="Difesa").grid(row=2, column=0, sticky="w")
        for i, w in enumerate(defense):
            w.grid(row=3, column=i, padx=2, pady=2)
        ttk.Label(parent, text="Artefatti").grid(row=4, column=0, sticky="w")
        for i, w in enumerate(artifacts):
            w.grid(row=5, column=i, padx=2, pady=2)
        ttk.Label(parent, text="Edificio").grid(row=6, column=0, sticky="w")
        building.grid(row=7, column=0, padx=2, pady=2)

    # This method builds the resource panel for a player, which displays the player's name, sin level, inspiration, hand size, and deck size. It creates labels and a progress bar to visually represent these resources and organizes them in a grid layout within the specified parent frame. The method also stores references to the created widgets in lists for later updates when the game state changes.
    def _build_resource_panel(self, parent, caption: str) -> None:
        panel = ttk.Frame(parent)
        panel.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        name = ttk.Label(panel, text=f"{caption}: -")
        name.grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Peccato").grid(row=1, column=0, sticky="w", pady=(2, 0))
        sin_lbl = ttk.Label(panel, text="0/100")
        sin_lbl.grid(row=1, column=1, sticky="w", padx=6, pady=(2, 0))
        sin_bar = ttk.Progressbar(panel, mode="determinate", maximum=100, length=170)
        sin_bar.grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=(2, 0))
        ttk.Label(panel, text="Ispirazione").grid(row=2, column=0, sticky="w")
        insp_lbl = ttk.Label(panel, text="0")
        insp_lbl.grid(row=2, column=1, sticky="w", padx=6)
        hand_lbl = ttk.Label(panel, text="Mano 0")
        hand_lbl.grid(row=2, column=2, sticky="e")
        deck_lbl = ttk.Label(panel, text="Deck 0")
        deck_lbl.grid(row=3, column=2, sticky="e")
        panel.columnconfigure(2, weight=1)
        self.resource_name_labels.append(name)
        self.resource_sin_labels.append(sin_lbl)
        self.resource_insp_labels.append(insp_lbl)
        self.resource_hand_labels.append(hand_lbl)
        self.resource_deck_labels.append(deck_lbl)
        self.resource_sin_bars.append(sin_bar)

    # This method refreshes the game view by updating the display of player resources, card slots, hand, and logs based on the current state of the game engine. It retrieves the relevant information for both players, updates the labels and widgets accordingly, and handles any necessary visual highlights for equipped cards. The method also checks for any runtime reveal prompts that may need to be displayed and updates the status message to reflect the current game situation.
    def refresh(self) -> None:
        if self.engine is None or not self._ui_alive():
            return
        if hasattr(self, "_capture_replay_snapshot_if_changed"):
            self._capture_replay_snapshot_if_changed()
        # Any real state refresh invalidates the cached preview snapshot.
        self._sim_state_snapshot = None
        self._clear_slot_highlights()
        st = self.engine.state
        own_idx = self.current_human_idx() or 0
        enemy_idx = 1 - own_idx
        own = st.players[own_idx]
        enemy = st.players[enemy_idx]
        self.info_label.configure(
            text=(
                f"Fase: {st.phase.upper()} | Turno {st.turn_number} | Attivo: {st.players[st.active_player].name}"
            )
        )
        self._update_resource_panel(0, own)
        self._update_resource_panel(1, enemy)

        self._set_slot_widgets(self.own_attack, own.attack)
        self._set_slot_widgets(self.own_defense, own.defense)
        self._set_slot_widgets(self.own_artifacts, own.artifacts, hide_equipped=True)
        self.own_building.configure(text=self.card_label(own.building))
        self.own_building.configure(fg="#a970ff" if self._provides_player_counter(own.building) else self._board_text_color())
        self._apply_equipment_highlight(self.own_building, own.building)

        self._set_slot_widgets(self.enemy_attack, enemy.attack)
        self._set_slot_widgets(self.enemy_defense, enemy.defense)
        self._set_slot_widgets(self.enemy_artifacts, enemy.artifacts, hide_equipped=True)
        self.enemy_building.configure(text=self.card_label(enemy.building))
        self.enemy_building.configure(foreground="#a970ff" if self._provides_player_counter(enemy.building) else self._board_text_color())
        self._apply_equipment_highlight(self.enemy_building, enemy.building)
        self._apply_blocked_artifact_slot_highlights()

        self.hand_list.delete(0, tk.END)
        for i, uid in enumerate(own.hand):
            self.hand_list.insert(tk.END, self.hand_entry_label(i, uid))

        self._append_new_logs()

        if st.winner is not None:
            winner = st.players[st.winner].name
            self.status_var.set(f"Partita terminata. Vince {winner}")
        else:
            status = (
                f"{own.name}: Peccato {own.sin}/100 | Ispirazione {int(own.inspiration) + int(getattr(own, 'temporary_inspiration', 0))} | Mano {len(own.hand)} | Deck {len(own.deck)}"
            )
            if self.chain_active:
                prio = st.players[self.chain_priority_idx].name
                status += f" | CATENA: priorita {prio} (OK Catena = passa)"
            self.status_var.set(status)
        try:
            self.after_idle(self._maybe_show_runtime_reveal)
        except Exception:
            return

    # This method checks if there is a pending runtime reveal prompt that needs to be displayed to the player. It verifies the relevant flags in the game engine's state to determine if a reveal is waiting, retrieves the card instance to be revealed, and displays the appropriate prompt or information to the player. The method also handles any choices that may be associated with the reveal and updates the game state accordingly after the player interacts with the prompt.
    def _maybe_show_runtime_reveal(self) -> None:
        if self.engine is None or self._reveal_prompt_open or not self._ui_alive():
            return

        flags = self.engine.state.flags
        waiting = bool(flags.get("_runtime_waiting_for_reveal"))
        reveal_uid = str(flags.get("_runtime_reveal_card", "")).strip()

        if not waiting or not reveal_uid:
            self._reveal_prompt_last_uid = ""
            return

        if reveal_uid == self._reveal_prompt_last_uid:
            return

        # AI-owned runtime choices should never open human dialogs.
        choice_owner_raw = str(flags.get("_runtime_choice_owner", "")).strip()
        if choice_owner_raw:
            try:
                choice_owner = int(choice_owner_raw)
            except ValueError:
                choice_owner = None
            if choice_owner is not None and self._is_ai_player(choice_owner):
                choice_candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
                choice_values_raw = str(flags.get("_runtime_choice_values", "")).strip()
                title = str(flags.get("_runtime_choice_title", "")).strip()
                prompt = str(flags.get("_runtime_choice_prompt", "")).strip()
                min_targets = int(str(flags.get("_runtime_choice_min_targets", "0")) or "0")
                max_targets_raw = str(flags.get("_runtime_choice_max_targets", "1")).strip()
                max_targets = int(max_targets_raw) if max_targets_raw else 1

                selected = ""
                if choice_candidates_raw:
                    candidates = [v for v in choice_candidates_raw.split(";;") if v]
                    selected = self._ai_pick_runtime_candidates(
                        choice_owner,
                        candidates,
                        min_targets,
                        max_targets,
                        prompt,
                        title,
                    )
                    flags["_runtime_choice_selected"] = selected
                    flags["_runtime_choice_ready"] = True
                elif choice_values_raw:
                    values = [v for v in choice_values_raw.split(";;") if v]
                    flags["_runtime_choice_selected"] = self._ai_pick_runtime_value(values, prompt, title)
                    flags["_runtime_choice_ready"] = True

                flags["_runtime_waiting_for_reveal"] = False
                flags.pop("_runtime_reveal_card", None)
                runtime_cards.resume_pending_effect(self.engine)
                self._reveal_prompt_last_uid = ""
                if self._ui_alive():
                    self.refresh()
                return

        inst = self.engine.state.instances.get(reveal_uid)
        if inst is None:
            flags["_runtime_waiting_for_reveal"] = False
            flags.pop("_runtime_reveal_card", None)
            self._reveal_prompt_last_uid = ""
            return

        self._reveal_prompt_open = True
        self._reveal_prompt_last_uid = reveal_uid
        try:
            choice_candidates_raw = str(flags.get("_runtime_choice_candidates", "")).strip()
            choice_values_raw = str(flags.get("_runtime_choice_values", "")).strip()

            if choice_candidates_raw:
                candidate_uids = [v for v in choice_candidates_raw.split(";;") if v]
                choice_owner = int(str(flags.get("_runtime_choice_owner", "0")) or "0")
                choices: list[tuple[str, str]] = []
                for c_uid in candidate_uids:
                    c_inst = self.engine.state.instances.get(c_uid)
                    if c_inst is None:
                        continue
                    choices.append((self._format_guided_candidate(c_uid, choice_owner), c_uid))

                title = str(flags.get("_runtime_choice_title", "Scegli Carta")) or "Scegli Carta"
                prompt = (
                    str(flags.get("_runtime_choice_prompt", "")).strip()
                    or "Scegli una carta tra le prime del reliquiario oppure Nessuna."
                )
                min_targets = int(str(flags.get("_runtime_choice_min_targets", "0")) or "0")
                max_targets_raw = str(flags.get("_runtime_choice_max_targets", "1")).strip()
                max_targets = int(max_targets_raw) if max_targets_raw else 1
                allow_multi = max_targets != 1
                preserve_selection_order = bool(flags.get("_runtime_choice_preserve_order"))

                canceled, selected = self._open_board_target_picker(
                    title=title,
                    prompt=prompt,
                    choices=choices,
                    allow_multi=allow_multi,
                    min_targets=min_targets,
                    max_targets=max_targets,
                    allow_none=(min_targets == 0),
                    allow_manual=False,
                    card_uid=reveal_uid,
                    preserve_selection_order=preserve_selection_order,
                )
                flags["_runtime_choice_selected"] = "" if canceled or not selected else str(selected)
                flags["_runtime_choice_ready"] = True

            elif choice_values_raw:
                values = [v for v in choice_values_raw.split(";;") if v]
                labels_raw = str(flags.get("_runtime_choice_labels", "")).strip()
                try:
                    labels_map = json.loads(labels_raw) if labels_raw else {}
                except Exception:
                    labels_map = {}

                choices: list[tuple[str, str]] = []
                for value in values:
                    label = str(labels_map.get(value, value))
                    choices.append((label, value))

                title = str(flags.get("_runtime_choice_title", "Scegli un'opzione")) or "Scegli un'opzione"
                prompt = str(flags.get("_runtime_choice_prompt", "")).strip() or "Seleziona una modalità."
                min_targets = int(str(flags.get("_runtime_choice_min_targets", "1")) or "1")
                max_targets_raw = str(flags.get("_runtime_choice_max_targets", "1")).strip()
                max_targets = int(max_targets_raw) if max_targets_raw else 1
                allow_multi = max_targets != 1

                canceled, selected = self._open_board_target_picker(
                    title=title,
                    prompt=prompt,
                    choices=choices,
                    allow_multi=allow_multi,
                    min_targets=min_targets,
                    max_targets=max_targets,
                    allow_none=False,
                    allow_manual=False,
                    card_uid=reveal_uid,
                )
                flags["_runtime_choice_selected"] = "" if canceled or not selected else str(selected)
                flags["_runtime_choice_ready"] = True

            else:
                messagebox.showinfo(
                    "Carta rivelata",
                    f"Hai rivelato: {inst.definition.name}\n\nPremi OK per continuare la risoluzione dell'effetto.",
                )
        finally:
            self._reveal_prompt_open = False

        flags["_runtime_waiting_for_reveal"] = False
        flags.pop("_runtime_reveal_card", None)
        runtime_cards.resume_pending_effect(self.engine)

        pending_actor = self._post_reveal_chain_actor
        self._post_reveal_chain_actor = None
        self._reveal_prompt_last_uid = ""

        if self._ui_alive():
            self.refresh()
        if pending_actor is not None and self._ui_alive():
            self.start_chain(actor_idx=pending_actor)

    # This method updates the resource panel for a player by setting the text of the labels and progress bar to reflect the player's current name, sin level, inspiration, hand size, and deck size. It takes the index of the panel to update and the player object as parameters, and it ensures that the displayed information is accurate based on the player's current state in the game.
    def _update_resource_panel(self, panel_idx: int, player) -> None:
        if panel_idx >= len(self.resource_name_labels):
            return
        self.resource_name_labels[panel_idx].configure(text=player.name)
        self.resource_sin_labels[panel_idx].configure(text=f"{player.sin}/100")
        total_inspiration = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
        self.resource_insp_labels[panel_idx].configure(text=str(total_inspiration))
        self.resource_hand_labels[panel_idx].configure(text=f"Mano {len(player.hand)}")
        self.resource_deck_labels[panel_idx].configure(text=f"Deck {len(player.deck)}")
        self.resource_sin_bars[panel_idx]["value"] = max(0, min(100, player.sin))

    # This method generates a label for a card in the player's hand based on its index and unique identifier (UID). It retrieves the card instance from the game engine's state, extracts relevant information such as the card's name, type, faith, and strength (if applicable), and formats this information into a string that can be displayed in the hand list. The method also handles cases where the card may not have certain attributes or when the game engine is not initialized, providing appropriate fallback values in those situations.
    def hand_entry_label(self, hand_idx: int, uid: str) -> str:
        if self.engine is None:
            return "-"
        inst = self.engine.state.instances[uid]
        c = inst.definition
        faith = inst.current_faith if inst.current_faith is not None else c.faith
        f_txt = f"F:{faith}" if faith is not None else "F:-"
        p_txt = ""
        if c.card_type.lower().strip() in {"santo", "token"}:
            p_txt = f" | P:{self.engine.get_effective_strength(uid)}"
        return f"[{hand_idx}] {c.name} ({c.card_type}) | {f_txt}{p_txt}"

    # This method updates the text of the widgets corresponding to the card slots (attack, defense, artifacts) based on the unique identifiers (UIDs) of the cards currently occupying those slots. It iterates through the provided list of UIDs and updates each widget's text to reflect the card's name and relevant attributes. If the `hide_equipped` flag is set to True, it will display a placeholder instead of the card's information for any equipment cards that are currently equipped, while still applying any necessary visual highlights for equipped cards.
    def _set_slot_widgets(self, widgets, slots, *, hide_equipped: bool = False) -> None:
        for i, uid in enumerate(slots):
            widget = widgets[i]
            display_uid = uid
            if hide_equipped and self._is_equipment_card_equipped(uid):
                display_uid = None
            widget.configure(text=self.card_label(display_uid))
            try:
                widget.configure(fg=self._board_text_color())
            except tk.TclError:
                try:
                    widget.configure(foreground=self._board_text_color())
                except tk.TclError:
                    pass
            self._apply_equipment_highlight(widget, display_uid)

    # This method retrieves a list of unique identifiers (UIDs) for cards that are currently equipped to the specified card UID. It checks the game engine's state for the card instance corresponding to the provided UID and looks for any tags that indicate an "equipped_by" relationship. If such tags are found, it extracts the UIDs of the equipped cards and returns them in a list. The method also handles cases where the game engine is not initialized or when the provided UID is invalid, returning an empty list in those situations.
    def _equipped_uids_for(self, uid: str | None) -> list[str]:
        if self.engine is None or not uid:
            return []
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return []
        out: list[str] = []
        for tag in list(inst.blessed):
            if not isinstance(tag, str) or not tag.startswith("equipped_by:"):
                continue
            eq_uid = tag.split(":", 1)[1].strip()
            if not eq_uid or eq_uid not in self.engine.state.instances:
                continue
            if eq_uid not in out:
                out.append(eq_uid)
        return out

    # This method checks if a given card UID corresponds to an equipment card that is currently equipped to another card. It retrieves the card instance from the game engine's state and looks for any tags that indicate an "equipped_by" relationship. If such tags are found, it returns True to indicate that the card is equipped, otherwise it returns False. The method also handles cases where the game engine is not initialized or when the provided UID is invalid, returning False in those situations.
    def _is_equipment_card_equipped(self, uid: str | None) -> bool:
        if self.engine is None or not uid:
            return False
        inst = self.engine.state.instances.get(uid)
        if inst is None:
            return False
        for tag in list(inst.blessed):
            if isinstance(tag, str) and tag.startswith("equipped_to:"):
                return True
        return False

    # This method applies a visual highlight to a widget based on whether the corresponding card UID has any equipment cards currently equipped. It checks if the card has equipped cards using the `_equipped_uids_for` method and sets the text color to a warning tone if it does, or back to the themed board text color if it does not. The method also handles differences in widget types, attempting to configure both "fg" and "foreground" properties as needed, while gracefully handling any exceptions that may arise from unsupported configurations.
    def _apply_equipment_highlight(self, widget, uid: str | None) -> None:
        has_equipment = bool(self._equipped_uids_for(uid))
        color = self._board_alert_text_color() if has_equipment else self._board_text_color()
        # tk.Button uses "fg", ttk widgets generally use "foreground".
        try:
            widget.configure(fg=color)
        except tk.TclError:
            try:
                widget.configure(foreground=color)
            except tk.TclError:
                pass

    def _apply_blocked_artifact_slot_highlights(self) -> None:
        if self.engine is None:
            return
        own_idx = self.current_human_idx() or 0
        enemy_idx = 1 - own_idx
        own_blocked = query_ops.get_blocked_artifact_slots_for_player(self.engine, own_idx)
        enemy_blocked = query_ops.get_blocked_artifact_slots_for_player(self.engine, enemy_idx)

        for i, btn in enumerate(self.own_artifacts):
            try:
                if i in own_blocked:
                    btn.configure(highlightthickness=2, highlightbackground="#1f6feb", highlightcolor="#1f6feb")
                else:
                    btn.configure(highlightthickness=0)
            except tk.TclError:
                pass

        for i, lbl in enumerate(self.enemy_artifacts):
            try:
                if i in enemy_blocked:
                    lbl.configure(relief="solid", borderwidth=2, foreground="#1f6feb")
                else:
                    lbl.configure(relief="flat", borderwidth=0, foreground=self._board_text_color())
            except tk.TclError:
                pass

    # This method appends any new log lines generated by the engine to the log panel.
    def _append_new_logs(self) -> None:
        if self.engine is None:
            return
        logs = self.engine.state.logs
        if self.last_log_idx >= len(logs):
            return
        self.log_text.configure(state="normal")
        for line in logs[self.last_log_idx :]:
            self.log_text.insert(tk.END, f"{line}\n")
        self.last_log_idx = len(logs)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # This method generates a label for a card based on its unique identifier (UID) by retrieving the card instance from the game engine's state and extracting relevant information such as the card's name, faith, strength (if applicable), and any counters. It formats this information into a string that can be displayed in the GUI to represent the card's current state. The method also handles cases where the UID is invalid or when the game engine is not initialized, returning a placeholder value in those situations.
    def card_label(self, uid: str | None) -> str:
        if not uid or self.engine is None:
            return "-"
        inst = self.engine.state.instances[uid]
        faith = f" F:{inst.current_faith}" if inst.current_faith is not None else ""
        ctype = inst.definition.card_type.lower()
        if ctype in {"santo", "token"}:
            strength = f" P:{self.engine.get_effective_strength(uid)}"
        else:
            strength = ""
        counter = self._counter_value(inst)
        counter_txt = f" C:{counter}" if counter > 0 else ""
        name = f"[{counter}] {inst.definition.name}" if counter > 0 else inst.definition.name
        return f"{name}{faith}{strength}{counter_txt}"

    # This method handles the right-click event on a card in the player's hand, providing a context menu with options for playing the card or activating its effects. It checks if the game engine is initialized and if the player can take actions, then determines which card was clicked based on the event's coordinates. Depending on the type of card and the current game state, it generates a context menu with appropriate options for playing the card or activating its effects, including any valid targets for those actions. The method also manages visual highlights for valid targets and ensures that the menu is displayed at the correct location on the screen.
    def on_hand_right_click(self, event) -> None:
        if self.engine is None or not self.can_human_act():
            return
        self._clear_slot_highlights()
        idx = self.hand_list.nearest(event.y)
        if idx < 0:
            return
        own_idx = self.current_human_idx() or 0
        hand = self.engine.state.players[own_idx].hand
        if idx >= len(hand):
            return
        uid = hand[idx]
        inst = self.engine.state.instances[uid]
        ctype = inst.definition.card_type.lower()
        allows_quick_play = runtime_cards.allows_quick_play(inst.effect_name, inst.definition.card_type)

        menu = tk.Menu(cast(tk.Misc, self), tearoff=0)
        if self._has_custom_targeting(uid):
            menu.add_command(label="Gioca Effetto...", command=lambda uu=uid: self.ask_guided_quick_target(uu))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return
        if self.chain_active and (ctype in {"benedizione", "maledizione"} or allows_quick_play):
            valid_targets = self._valid_play_targets(own_idx, idx, uid, quick=True)
            if valid_targets:
                self._set_slot_highlights(valid_targets, card_uid=uid)
                menu.add_command(label="Gioca Effetto...", command=lambda uu=uid: self.ask_guided_quick_target(uu))
            elif self._can_play_target(own_idx, idx, None, quick=True):
                menu.add_command(label="Gioca Effetto", command=lambda uu=uid: self.play_uid(uu, None))
            else:
                menu.add_command(label="Nessun target valido", state="disabled")
        elif ctype in {"santo", "token"}:
            play_owner = self._play_owner_idx(uid)
            m_att = tk.Menu(menu, tearoff=0)
            att_targets: list[str] = []
            for s in range(1, 4):
                target = f"a{s}"
                if self._can_play_target(own_idx, idx, target):
                    att_targets.append(target)
                    m_att.add_command(
                        label=f"Attacco {s}",
                        command=lambda uu=uid, ss=s: self.play_saint_with_optional_sacrifice(uu, f"a{ss}"),
                    )
            if not att_targets:
                m_att.add_command(label="Nessuno slot valido", state="disabled")
            menu.add_cascade(label="Gioca in Attacco", menu=m_att)
            m_def = tk.Menu(menu, tearoff=0)
            def_targets: list[str] = []
            for s in range(1, 4):
                target = f"d{s}"
                if self._can_play_target(own_idx, idx, target):
                    def_targets.append(target)
                    m_def.add_command(
                        label=f"Difesa {s}",
                        command=lambda uu=uid, ss=s: self.play_saint_with_optional_sacrifice(uu, f"d{ss}"),
                    )
            if not def_targets:
                m_def.add_command(label="Nessuno slot valido", state="disabled")
            menu.add_cascade(label="Gioca in Difesa", menu=m_def)
            self._set_slot_highlights(att_targets + def_targets, side_hint="enemy" if play_owner != own_idx else "own")
        elif ctype in {"benedizione", "maledizione"}:
            valid_targets = self._valid_play_targets(own_idx, idx, uid, quick=False)
            if valid_targets:
                self._set_slot_highlights(valid_targets, card_uid=uid)
                menu.add_command(label="Gioca Effetto...", command=lambda uu=uid: self.ask_guided_quick_target(uu))
            elif self._can_play_target(own_idx, idx, None, quick=False):
                menu.add_command(label="Gioca Effetto", command=lambda uu=uid: self.play_uid(uu, None))
            else:
                menu.add_command(label="Nessun target valido", state="disabled")
        else:
            menu.add_command(label="Gioca", command=lambda uu=uid: self.play_uid(uu, None))

        menu.bind("<Unmap>", lambda _e: self._clear_slot_highlights())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # This method handles the selection event when a player clicks on a card in their hand. It checks if the game engine is initialized and retrieves the index of the selected card based on the current selection in the hand list. If a valid card is selected, it calls the `show_card_detail` method to display the details of the selected card, showing only the effect text if the `effect_only` flag is set to True. The method ensures that it gracefully handles cases where no card is selected or when the selection index is out of bounds.
    def on_hand_select(self, _event) -> None:
        if self.engine is None:
            return
        own_idx = self.current_human_idx() or 0
        sel = self.hand_list.curselection()
        if not sel:
            return
        idx = sel[0]
        hand = self.engine.state.players[own_idx].hand
        if idx < 0 or idx >= len(hand):
            return
        self.show_card_detail(hand[idx], effect_only=True)

    # This method retrieves the unique identifier (UID) of the currently selected card in the player's hand. It checks if the game engine is initialized and retrieves the index of the selected card based on the current selection in the hand list. If a valid card is selected, it returns the UID of that card; otherwise, it returns None. The method also handles cases where no card is selected or when the selection index is out of bounds, ensuring that it returns None in those situations.
    def _selected_hand_uid(self) -> str | None:
        if self.engine is None:
            return None
        own_idx = self.current_human_idx() or 0
        sel = self.hand_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        hand = self.engine.state.players[own_idx].hand
        if idx < 0 or idx >= len(hand):
            return None
        return hand[idx]

    # This method finds the first available slot for a card to be played in either the attack or defense lane for a given player. It checks the player's current slots in the specified lane and returns the identifier of the first open slot (e.g., "a1", "a2", "a3" for attack or "d1", "d2", "d3" for defense). If all slots in the specified lane are occupied, it returns None. The method also handles cases where the game engine is not initialized, returning None in that situation.
    def _first_open_slot(self, player_idx: int, lane: str) -> str | None:
        if self.engine is None:
            return None
        player = self.engine.state.players[player_idx]
        slots = player.attack if lane == "a" else player.defense
        for i, uid in enumerate(slots):
            if uid is None:
                return f"{lane}{i + 1}"
        return None

    # This method handles the action of playing the currently selected card from the player's hand. It checks if the game engine is initialized and if the player can take actions, then retrieves the UID of the selected card. Depending on the type of card and whether it requires a target, it either prompts the player to select a target or determines an appropriate target based on the card's type (e.g., placing a "santo" or "token" in an open attack or defense slot). If no valid target is available, it shows a warning message. Finally, it calls the `play_uid` method to execute the action of playing the card with the determined target.
    def play_selected_card(self) -> None:
        if self.engine is None or not self.can_human_act():
            return
        uid = self._selected_hand_uid()
        if uid is None:
            messagebox.showinfo("Gioca Carta", "Seleziona prima una carta dalla mano.")
            return
        own_idx = self.current_human_idx() or 0
        inst = self.engine.state.instances[uid]
        ctype = inst.definition.card_type.lower().strip()
        target: str | None = None
        if self._card_requires_target(uid):
            self.ask_guided_quick_target(uid)
            return
        if ctype in {"santo", "token"}:
            play_owner = self._play_owner_idx(uid)
            target = self._first_open_slot(play_owner, "a") or self._first_open_slot(play_owner, "d")
            if target is None:
                messagebox.showwarning("Campo pieno", "Nessuno slot libero in Attacco/Difesa.")
                return
        self.play_uid(uid, target)

    # This method handles the action of showing the details of a card that is currently on the board (in attack, defense, artifacts, or building slots). It checks if the game engine is initialized and retrieves the player index based on the relative player parameter. Then, it determines the unique identifier (UID) of the card in the specified zone and index, and if a valid UID is found, it calls the `show_card_detail` method to display the details of that card. The method ensures that it gracefully handles cases where the game engine is not initialized or when the specified zone and index do not correspond to a valid card, returning without action in those situations.
    def show_board_card_detail(self, relative_player: int, zone: str, idx: int) -> None:
        if self.engine is None:
            return
        human_idx = self.current_human_idx() or 0
        player_idx = human_idx if relative_player == 0 else 1 - human_idx
        player = self.engine.state.players[player_idx]
        uid: str | None = None
        if zone == "attack":
            uid = player.attack[idx]
        elif zone == "defense":
            uid = player.defense[idx]
        elif zone == "artifacts":
            uid = player.artifacts[idx]
        elif zone == "building":
            uid = player.building
        if uid:
            self.show_card_detail(uid)

    # This method displays the details of a card based on its unique identifier (UID). It retrieves the card instance from the game engine's state and extracts relevant information such as the card's name, effect text, and any equipped cards. The method formats this information into a detailed string that can be displayed in the GUI, showing the card's name, its effect, and any equipped cards along with their effects. If the `effect_only` flag is set to True, it will display only the effect text without the card's name or equipped cards. The method also handles cases where the game engine is not initialized or when the provided UID is invalid, returning without action in those situations.
    def show_card_detail(self, uid: str, effect_only: bool = False) -> None:
        if self.engine is None:
            return
        inst = self.engine.state.instances[uid]
        c = inst.definition
        effect = (c.effect_text or "").strip() or "Nessun effetto testuale disponibile."
        equipped_uids = self._equipped_uids_for(uid)
        equipped_section = ""
        if equipped_uids:
            lines = []
            for eq_uid in equipped_uids:
                eq_inst = self.engine.state.instances.get(eq_uid)
                if eq_inst is None:
                    continue
                eq_effect = (eq_inst.definition.effect_text or "").strip() or "Nessun effetto testuale disponibile."
                lines.append(f"- {eq_inst.definition.name}: {eq_effect}")
            if lines:
                equipped_section = "\n\nCarte equipaggiate:\n" + "\n".join(lines)
        detail = effect if effect_only else f"{c.name}\n\n{effect}{equipped_section}"
        self.card_detail_text.configure(state="normal")
        self.card_detail_text.delete("1.0", tk.END)
        self.card_detail_text.insert(tk.END, detail)
        self.card_detail_text.configure(state="disabled")

    # This method opens a debug window that displays the contents of a specified zone (deck, graveyard, or excommunicated) for the current player. It retrieves the relevant information from the game engine's state and creates a new window with a list of cards in the selected zone, allowing the user to view details of each card by selecting it from the list. The method also handles cases where the game engine is not initialized or when an invalid zone is specified, showing appropriate messages in those situations.
    def open_debug_zone(self, zone: str) -> None:
        engine = self.engine
        if engine is None:
            messagebox.showinfo("Debug Zone", "Avvia prima una partita.")
            return
        zone_key = str(zone).strip().lower()
        if zone_key in {"innate", "innata", "innate_active"}:
            active_map = engine.state.flags.get("innate_active_uids", {"0": [], "1": []}) or {"0": [], "1": []}
            players = engine.state.players

            win = tk.Toplevel(cast(Any, self))
            win.title("Innate Attive")
            self._center_toplevel(win, 760, 560)
            win.transient(cast(Any, self))

            both_active = bool(active_map.get("0")) and bool(active_map.get("1"))
            if both_active:
                status_text = "Entrambi i giocatori hanno carte Innata attive."
            elif bool(active_map.get("0")):
                status_text = f"Solo {players[0].name} ha carte Innata attive."
            elif bool(active_map.get("1")):
                status_text = f"Solo {players[1].name} ha carte Innata attive."
            else:
                status_text = "Nessun giocatore ha carte Innata attive."

            ttk.Label(win, text=status_text).pack(anchor="w", padx=8, pady=(8, 4))

            details = tk.Text(win, wrap="word")
            details.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            details.configure(state="normal")

            for p_idx in (0, 1):
                p_name = players[p_idx].name
                active_uids = list(active_map.get(str(p_idx), []) or [])
                details.insert(tk.END, f"{p_name}\n")
                if not active_uids:
                    details.insert(tk.END, "  - Nessuna Innata attiva.\n\n")
                    continue
                for uid in active_uids:
                    inst = engine.state.instances.get(uid)
                    if inst is None:
                        details.insert(tk.END, f"  - [UID {uid}] carta non trovata.\n")
                        continue
                    cdef = inst.definition
                    effect = (cdef.effect_text or "").strip() or "Nessun effetto testuale disponibile."
                    details.insert(tk.END, f"  - {cdef.name}\n")
                    details.insert(tk.END, f"    {effect}\n")
                details.insert(tk.END, "\n")

            details.configure(state="disabled")
            return

        labels = {
            "deck": "Deck",
            "graveyard": "Cimitero",
            "excommunicated": "Scomunicate",
        }
        if zone_key not in labels:
            return
        player_idx = self.current_human_idx()
        if player_idx is None:
            player_idx = 0
        player = engine.state.players[player_idx]
        if zone_key == "deck":
            uids = list(player.deck)
        elif zone_key == "graveyard":
            uids = list(player.graveyard)
        else:
            uids = list(player.excommunicated)

        win = tk.Toplevel(cast(Any, self))
        win.title(f"{labels[zone_key]} (Debug)")
        self._center_toplevel(win, 560, 500)
        win.transient(cast(Any, self))

        ttk.Label(
            win,
            text=f"{labels[zone_key]} di {player.name} - {len(uids)} carte",
        ).pack(anchor="w", padx=8, pady=(8, 4))

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        lb = tk.Listbox(body)
        lb.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        details = tk.Text(win, wrap="word", height=8)
        details.pack(fill="x", padx=8, pady=(0, 8))
        details.configure(state="disabled")

        for i, uid in enumerate(uids, start=1):
            inst = engine.state.instances.get(uid)
            if inst is None:
                lb.insert(tk.END, f"{i:02d}. <missing> [{uid}]")
                continue
            lb.insert(tk.END, f"{i:02d}. {inst.definition.name} [{uid}]")

        def _on_pick(_event=None):
            sel = lb.curselection()
            if not sel:
                return
            row = int(sel[0])
            if row < 0 or row >= len(uids):
                return
            uid = uids[row]
            inst = engine.state.instances.get(uid)
            if inst is None:
                text = f"{uid}\n\nCarta non trovata nelle istanze."
            else:
                cdef = inst.definition
                effect = (cdef.effect_text or "").strip() or "Nessun effetto testuale disponibile."
                text = f"{cdef.name}\nTipo: {cdef.card_type}\nUID: {uid}\n\n{effect}"
            details.configure(state="normal")
            details.delete("1.0", tk.END)
            details.insert(tk.END, text)
            details.configure(state="disabled")

        lb.bind("<<ListboxSelect>>", _on_pick)
        if uids:
            lb.selection_set(0)
            _on_pick()
