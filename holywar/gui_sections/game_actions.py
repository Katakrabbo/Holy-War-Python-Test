from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

from typing import TYPE_CHECKING, Any, cast
import tkinter as tk
from tkinter import messagebox

from holywar.effects.runtime import _norm, runtime_cards

# Utility functions to extract and normalize card name variants for target matching in gameplay actions.
def _card_aliases(definition) -> list[str]:
    raw_aliases = getattr(definition, "aliases", []) or []
    if isinstance(raw_aliases, str):
        return [part.strip() for part in raw_aliases.split(",") if part.strip()]
    return [str(alias).strip() for alias in raw_aliases if str(alias).strip()]

# Normalizes a string by converting it to lowercase and stripping whitespace, used for consistent target matching.
def _card_name_variants(definition) -> set[str]:
    variants = {_norm(definition.name)}
    variants.update(_norm(alias) for alias in _card_aliases(definition))
    return {v for v in variants if v}

# Creates a normalized haystack string containing the card's name and aliases, used for substring matching in target specifications.
def _card_name_haystack(definition) -> str:
    parts = [definition.name, *_card_aliases(definition)]
    return " ".join(_norm(part) for part in parts if str(part).strip())


def _crosses_to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None

# This mixin class provides methods for handling gameplay actions that require target selection, including determining if a card allows multiple targets, if it requires a target, counting cards based on specific rules, and generating candidate targets for guided selection based on the card's script and targeting specifications.
class GUIGameActionsMixin:
    """Gameplay actions and advanced target orchestration handlers."""

    if TYPE_CHECKING:
        def __getattr__(self, _name: str) -> Any: ...

    def _card_allows_multi_target(self, uid: str) -> bool:
        mode = self._play_targeting_mode(uid)

        # Compatibilità con il vecchio sistema
        if mode == "multi":
            return True

        # Nuovo sistema guidato: guarda il target vero della carta
        target = self._first_play_target_spec(uid)
        if target is None:
            return False

        if target.type == "selected_targets":
            return True

        max_targets = target.max_targets if target.max_targets is not None else 1
        return max_targets != 1

    # Determines if the card with the given UID requires a target for its play action, based on its targeting mode and the presence of target specifications in its script, which affects whether the player will be prompted to select targets when playing the card.
    def _card_requires_target(self, uid: str) -> bool:
        mode = self._play_targeting_mode(uid)
        target = self._first_play_target_spec(uid)

        if mode in {
            "own_saint",
            "opponent_saint",
            "own_graveyard_saint",
            "manual",
            "multi",
            "custom",
        }:
            return True

        # Guided cards should require manual selection only when there is at least
        # one active play target spec after condition evaluation.
        if mode == "guided":
            return target is not None

        if mode in {"none", "", None, "auto"}:
            return target is not None

        return False

    # Counts the number of cards that match specific criteria defined in a rule, such as ownership, zone, card type, name filters, crosses, and strength, which is used for determining the maximum number of targets allowed for certain card effects based on the current game state.
    def _count_cards_from_rule(self, uid: str, rule: dict) -> int:
        if self.engine is None:
            return 0

        own_idx = self.current_human_idx() or 0
        st = self.engine.state
        own = st.players[own_idx]
        opp = st.players[1 - own_idx]

        spec = rule.get("count_cards_controlled_by_owner")
        if not spec:
            return 0

        owner_key = str(spec.get("owner", "me")).strip().lower()
        zone = str(spec.get("zone", "field")).strip().lower()
        filt = spec.get("card_filter", {}) or {}

        player = own if owner_key in {"me", "owner", "controller"} else opp

        card_type_in = {x.lower().strip() for x in filt.get("card_type_in", [])}
        name_contains = filt.get("name_contains")
        name_not_contains = filt.get("name_not_contains")
        crosses_gte = filt.get("crosses_gte")
        crosses_lte = filt.get("crosses_lte")
        strength_gte = filt.get("strength_gte")
        strength_lte = filt.get("strength_lte")

        if zone == "field":
            pool = [x for x in list(player.attack) + list(player.defense) if x is not None]
        elif zone == "graveyard":
            pool = list(player.graveyard)
        elif zone == "hand":
            pool = list(player.hand)
        elif zone in {"deck", "relicario"}:
            pool = list(player.deck)
        else:
            pool = []

        total = 0
        for c_uid in pool:
            inst = st.instances.get(c_uid)
            if inst is None:
                continue

            name_variants = _card_name_variants(inst.definition)
            name_haystack = _card_name_haystack(inst.definition)
            ctype = inst.definition.card_type.lower().strip()
            crosses = _crosses_to_int(getattr(inst.definition, "crosses", None))

            if card_type_in and ctype not in card_type_in:
                continue
            if name_contains and _norm(name_contains) not in name_haystack:
                continue
            if name_not_contains and _norm(name_not_contains) in name_haystack:
                continue
            if crosses_gte is not None and (crosses is None or crosses < int(crosses_gte)):
                continue
            if crosses_lte is not None and (crosses is None or crosses > int(crosses_lte)):
                continue
            eff_strength = self.engine.get_effective_strength(c_uid)
            if strength_gte is not None and eff_strength < int(strength_gte):
                continue
            if strength_lte is not None and eff_strength > int(strength_lte):
                continue

            total += 1

        return total

    # Retrieves the first target specification from the card's on-play actions, which is used to determine the targeting requirements and candidate targets for the card when it is played.
    def _first_activate_target_spec(self, uid: str):
        script = self._card_script(uid)
        if script is None:
            return None
        for action in script.on_activate_actions:
            target = action.target
            ttype = str(target.type or "").strip().lower()
            if ttype in {"selected_target", "selected_targets"}:
                return target
        return None

    # Retrieves the first target specification from the card's on-play actions, which is used to determine the targeting requirements and candidate targets for the card when it is played.
    def _target_selection_limits(self, uid: str, *, for_activate: bool = False) -> tuple[int, int | None]:
        mode = self._play_targeting_mode(uid)

        # Nuovo sistema: solo se esiste davvero un target nello script
        target = self._first_activate_target_spec(uid) if for_activate else self._first_play_target_spec(uid)
        if target is not None:
            min_targets = target.min_targets if target.min_targets is not None else 1

            if target.max_targets_from:
                max_targets = self._count_cards_from_rule(uid, target.max_targets_from)
            else:
                max_targets = target.max_targets if target.max_targets is not None else 1

            return (min_targets, max_targets)

        # Compatibilità con i mode vecchi
        if mode == "multi":
            return (1, None)
        if mode in {"own_saint", "opponent_saint", "own_graveyard_saint", "manual"}:
            return (1, 1)
        if mode == "custom":
            return (0, None)

        # Carte senza target, tipo Concentrazione
        return (0, 0)

    def _has_custom_targeting(self, uid: str) -> bool:
        return self._play_targeting_mode(uid) == "custom"

    # Generates a list of candidate target UIDs for a card with the given UID based on its targeting mode and specifications, which is used to provide guided target selection options to the player when playing the card.
    def _guided_target_candidates(self, uid: str) -> list[str]:
        if self.engine is None:
            return []

        engine = self.engine
        own_idx = self.current_human_idx() or 0
        own = engine.state.players[own_idx]
        opp = engine.state.players[1 - own_idx]
        mode = self._play_targeting_mode(uid)
        out: list[str] = []

        # Compatibilità con i mode vecchi
        if mode == "own_graveyard_saint":
            for c_uid in own.graveyard:
                inst = self.engine.state.instances[c_uid]
                if inst.definition.card_type.lower().strip() == "santo":
                    out.append(c_uid)
            return out

        if mode == "own_saint":
            for i in range(3):
                if own.attack[i] is not None:
                    out.append(f"a{i+1}")
                if own.defense[i] is not None:
                    out.append(f"d{i+1}")
            return out

        if mode == "manual":
            return []

        # Nuovo targeting guidato data-driven
        target = self._first_play_target_spec(uid)
        if target is None:
            return []

        owner_key = str(target.owner or "me").strip().lower()
        if owner_key in {"any", "both", "all", "either"}:
            players = [own, opp]
        elif owner_key in {"me", "owner", "controller"}:
            players = [own]
        else:
            players = [opp]

        zones = [z.lower().strip() for z in (target.zones or []) if str(z).strip()]
        if not zones:
            zones = [str(target.zone or "field").strip().lower()]

        type_filter = {x.lower().strip() for x in target.card_filter.card_type_in}
        name_in = {str(x).lower().strip() for x in (target.card_filter.name_in or []) if str(x).strip()}
        name_equals = target.card_filter.name_equals.lower().strip() if target.card_filter.name_equals else None
        name_contains = target.card_filter.name_contains.lower().strip() if target.card_filter.name_contains else None
        name_not_contains = target.card_filter.name_not_contains.lower().strip() if target.card_filter.name_not_contains else None
        crosses_gte = target.card_filter.crosses_gte
        crosses_lte = target.card_filter.crosses_lte
        strength_gte = target.card_filter.strength_gte
        strength_lte = target.card_filter.strength_lte

        exclude_buildings_if_my_building_zone_occupied = (
            target.card_filter.exclude_buildings_if_my_building_zone_occupied
        )

        def matches(inst) -> bool:
            ctype = inst.definition.card_type.lower().strip()
            name_variants = _card_name_variants(inst.definition)
            name_haystack = _card_name_haystack(inst.definition)
            crosses = getattr(inst.definition, "crosses", None)

            # Converti crosses in intero se necessario
            cross_value = None
            if crosses is not None:
                if isinstance(crosses, (int, float)):
                    cross_value = int(crosses)
                else:
                    try:
                        cross_value = int(float(str(crosses)))
                    except (ValueError, TypeError):
                        cross_value = None

            if type_filter and ctype not in type_filter:
                return False
            if name_in and name_in.isdisjoint(name_variants):
                return False
            if name_equals and _norm(name_equals) not in name_variants:
                return False

            if name_contains and _norm(name_contains) not in name_haystack:
                return False

            if name_not_contains and _norm(name_not_contains) in name_haystack:
                return False

            if (
                exclude_buildings_if_my_building_zone_occupied
                and own.building is not None
                and ctype == "edificio"
            ):
                return False

            if crosses_gte is not None and (cross_value is None or cross_value < crosses_gte):
                return False

            if crosses_lte is not None and (cross_value is None or cross_value > crosses_lte):
                return False

            eff_strength = engine.get_effective_strength(inst.uid)
            if strength_gte is not None and eff_strength < int(strength_gte):
                return False
            if strength_lte is not None and eff_strength > int(strength_lte):
                return False

            return True

        seen: set[str] = set()

        for player in players:
            for zone in zones:
                if zone == "field":
                    for i in range(3):
                        a_uid = player.attack[i]
                        if a_uid is not None:
                            inst = engine.state.instances[a_uid]
                            if matches(inst):
                                token = a_uid
                                if token not in seen:
                                    out.append(token)
                                    seen.add(token)

                        d_uid = player.defense[i]
                        if d_uid is not None:
                            inst = engine.state.instances[d_uid]
                            if matches(inst):
                                token = d_uid
                                if token not in seen:
                                    out.append(token)
                                    seen.add(token)
                    for i in range(4):
                        r_uid = player.artifacts[i]
                        if r_uid is not None:
                            inst = engine.state.instances[r_uid]
                            if matches(inst):
                                token = r_uid
                                if token not in seen:
                                    out.append(token)
                                    seen.add(token)
                    b_uid = player.building
                    if b_uid is not None:
                        inst = engine.state.instances[b_uid]
                        if matches(inst):
                            token = b_uid
                            if token not in seen:
                                out.append(token)
                                seen.add(token)

                elif zone == "graveyard":
                    for c_uid in player.graveyard:
                        inst = engine.state.instances[c_uid]
                        if matches(inst) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone == "excommunicated":
                    for c_uid in player.excommunicated:
                        inst = engine.state.instances[c_uid]
                        if matches(inst) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone == "building":
                    b_uid = player.building
                    if b_uid is not None:
                        inst = engine.state.instances[b_uid]
                        if matches(inst) and b_uid not in seen:
                            out.append(b_uid)
                            seen.add(b_uid)

                elif zone == "hand":
                    for c_uid in player.hand:
                        inst = engine.state.instances[c_uid]
                        if matches(inst) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone in {"deck", "relicario"}:
                    for c_uid in player.deck:
                        inst = engine.state.instances[c_uid]
                        if matches(inst) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

        return out

    # Generates a list of candidate target UIDs for a card with the given UID based on its targeting mode and specifications, which is used to provide guided target selection options to the player when playing the card.
    def _guided_target_candidates_for_spec(self, uid: str, target) -> list[str]:
        if self.engine is None:
            return []

        engine = self.engine
        own_idx = self.current_human_idx() or 0
        own = engine.state.players[own_idx]
        opp = engine.state.players[1 - own_idx]
        out: list[str] = []

        owner_key = str(target.owner or "me").strip().lower()
        if owner_key in {"any", "both", "all", "either"}:
            players = [own, opp]
        elif owner_key in {"me", "owner", "controller"}:
            players = [own]
        else:
            players = [opp]

        zones = [z.lower().strip() for z in (target.zones or []) if str(z).strip()]
        if not zones:
            zones = [str(target.zone or "field").strip().lower()]

        type_filter = {x.lower().strip() for x in target.card_filter.card_type_in}
        name_in = {str(x).lower().strip() for x in (target.card_filter.name_in or []) if str(x).strip()}
        name_equals = target.card_filter.name_equals.lower().strip() if target.card_filter.name_equals else None
        name_contains = target.card_filter.name_contains.lower().strip() if target.card_filter.name_contains else None
        name_not_contains = target.card_filter.name_not_contains.lower().strip() if target.card_filter.name_not_contains else None
        crosses_gte = target.card_filter.crosses_gte
        crosses_lte = target.card_filter.crosses_lte
        strength_gte = target.card_filter.strength_gte
        strength_lte = target.card_filter.strength_lte

        exclude_buildings_if_my_building_zone_occupied = (
            target.card_filter.exclude_buildings_if_my_building_zone_occupied
        )

        def matches(inst_uid: str) -> bool:
            inst = engine.state.instances[inst_uid]
            ctype = inst.definition.card_type.lower().strip()
            name_variants = _card_name_variants(inst.definition)
            name_haystack = _card_name_haystack(inst.definition)

            if target.card_filter.exclude_event_card and inst_uid == uid:
                return False
            if type_filter and ctype not in type_filter:
                return False
            if name_in and name_in.isdisjoint(name_variants):
                return False
            if name_equals and _norm(name_equals) not in name_variants:
                return False
            if name_contains and _norm(name_contains) not in name_haystack:
                return False
            if name_not_contains and _norm(name_not_contains) in name_haystack:
                return False
            if (
                exclude_buildings_if_my_building_zone_occupied
                and own.building is not None
                and ctype == "edificio"
            ):
                return False

            crosses = _crosses_to_int(getattr(inst.definition, "crosses", None))
            if crosses_gte is not None and (crosses is None or crosses < int(crosses_gte)):
                return False
            if crosses_lte is not None and (crosses is None or crosses > int(crosses_lte)):
                return False
            eff_strength = engine.get_effective_strength(inst_uid)
            if strength_gte is not None and eff_strength < int(strength_gte):
                return False
            if strength_lte is not None and eff_strength > int(strength_lte):
                return False
            return True

        seen: set[str] = set()

        for player in players:
            for zone in zones:
                if zone == "field":
                    for i in range(3):
                        a_uid = player.attack[i]
                        if a_uid is not None and matches(a_uid):
                            token = a_uid
                            if token not in seen:
                                out.append(token)
                                seen.add(token)

                        d_uid = player.defense[i]
                        if d_uid is not None and matches(d_uid):
                            token = d_uid
                            if token not in seen:
                                out.append(token)
                                seen.add(token)

                    for i in range(len(player.artifacts)):
                        r_uid = player.artifacts[i]
                        if r_uid is not None and matches(r_uid):
                            token = r_uid
                            if token not in seen:
                                out.append(token)
                                seen.add(token)

                    if player.building is not None and matches(player.building):
                        token = player.building
                        if token not in seen:
                            out.append(token)
                            seen.add(token)

                elif zone == "graveyard":
                    for c_uid in player.graveyard:
                        if matches(c_uid) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone == "excommunicated":
                    for c_uid in player.excommunicated:
                        if matches(c_uid) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone == "hand":
                    for c_uid in player.hand:
                        if matches(c_uid) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone in {"deck", "relicario"}:
                    for c_uid in player.deck:
                        if matches(c_uid) and c_uid not in seen:
                            out.append(c_uid)
                            seen.add(c_uid)

                elif zone == "building":
                    if player.building is not None and matches(player.building):
                        token = player.building
                        if token not in seen:
                            out.append(token)
                            seen.add(token)

        return out

    # Generates a list of candidate target UIDs for a card with the given UID based on its targeting mode and specifications, which is used to provide guided target selection options to the player when playing the card.
    def _board_activation_candidates(self, player_idx: int) -> list[str]:
        if self.engine is None:
            return []
        own = self.engine.state.players[player_idx]
        opp = self.engine.state.players[1 - player_idx]
        out: list[str] = []
        for i in range(3):
            if own.attack[i] is not None:
                out.append(f"s:a{i+1}")
            if opp.attack[i] is not None:
                out.append(f"o:a{i+1}")
        for i in range(3):
            if own.defense[i] is not None:
                out.append(f"s:d{i+1}")
            if opp.defense[i] is not None:
                out.append(f"o:d{i+1}")
        for i in range(4):
            if own.artifacts[i] is not None:
                out.append(f"s:r{i+1}")
            if opp.artifacts[i] is not None:
                out.append(f"o:r{i+1}")
        if own.building is not None:
            out.append("s:b")
        if opp.building is not None:
            out.append("o:b")
        return out

    # Generates a list of candidate target UIDs for a card with the given UID based on its targeting mode and specifications, which is used to provide guided target selection options to the player when playing the card.
    def _format_guided_candidate(self, token: str, own_idx: int) -> str:
        if self.engine is None:
            return token
        st = self.engine.state
        own = st.players[own_idx]
        opp = st.players[1 - own_idx]
        raw = str(token or "").strip()
        side = ""
        core = raw
        if ":" in raw:
            pref, code = raw.split(":", 1)
            p = pref.strip().lower()
            if p in {"s", "self", "me", "own", "owner", "controller"}:
                side = "TUO"
                core = code.strip()
            elif p in {"o", "opp", "enemy", "opponent", "other"}:
                side = "AVV"
                core = code.strip()
        chosen_player = own if side != "AVV" else opp
        side_prefix = f"[{side}] " if side else ""
        if core.startswith("a") and len(core) == 2 and core[1].isdigit():
            i = int(core[1]) - 1
            uid = chosen_player.attack[i] if 0 <= i < 3 else None
            name = st.instances[uid].definition.name if uid is not None else "-"
            return f"{side_prefix}Attacco {i + 1} | {name}"
        if core.startswith("d") and len(core) == 2 and core[1].isdigit():
            i = int(core[1]) - 1
            uid = chosen_player.defense[i] if 0 <= i < 3 else None
            name = st.instances[uid].definition.name if uid is not None else "-"
            return f"{side_prefix}Difesa {i + 1} | {name}"
        if core.startswith("r") and len(core) == 2 and core[1].isdigit():
            i = int(core[1]) - 1
            uid = chosen_player.artifacts[i] if 0 <= i < 4 else None
            name = st.instances[uid].definition.name if uid is not None else "-"
            return f"{side_prefix}Artefatto {i + 1} | {name}"
        if core == "b":
            uid = chosen_player.building
            name = st.instances[uid].definition.name if uid else "-"
            return f"{side_prefix}Edificio | {name}"
        if ":" in token:
            pref, name = token.split(":", 1)
            if pref == "deck":
                return f"Reliquiario | {name}"
            if pref == "grave":
                return f"Cimitero | {name}"
            if pref == "excom":
                return f"Scomunicate | {name}"
            return f"{pref} | {name}"

        if token in st.instances:
            inst = st.instances[token]
            owner = "TUO" if inst.owner == own_idx else "AVV"
            p = st.players[inst.owner]
            where = "fuori campo"
            for i, c_uid in enumerate(p.attack):
                if c_uid == token:
                    where = f"Attacco {i + 1}"
                    break
            if where == "fuori campo":
                for i, c_uid in enumerate(p.defense):
                    if c_uid == token:
                        where = f"Difesa {i + 1}"
                        break
            if where == "fuori campo":
                for i, c_uid in enumerate(p.artifacts):
                    if c_uid == token:
                        where = f"Artefatto {i + 1}"
                        break
            if where == "fuori campo" and p.building == token:
                where = "Edificio"
            return f"{owner} {where} | {inst.definition.name} ({inst.definition.card_type})"

        return token

    # Handles the target selection process for the "Monsone" card effect, allowing the player to select up to 3 cards from their hand to discard and up to 3 cards on the field with 8 or fewer crosses to return to their respective reliquaries, and returns a formatted target string representing the player's choices for the card's effect resolution.

    # Handles the process of collecting target selections for cards with multiple on-play actions that require targets, prompting the player to select valid targets for each action in sequence, and returns a formatted payload string representing the player's choices for all the actions, which is used for resolving the card's effects in the game engine.
    def _collect_on_play_action_targets(self, uid: str) -> tuple[bool, str | None]:
        if self.engine is None:
            return (True, None)

        own_idx = self.current_human_idx() or 0
        manual_actions = self._manual_play_target_actions(uid)
        if not manual_actions:
            return (False, None)

        picked_parts: list[str] = []

        for action_idx, target_spec in manual_actions:
            # Use runtime-side selectable target resolution to keep UI choices
            # perfectly aligned with the actual effect resolver.
            candidates = runtime_cards._collect_selectable_targets_for_manual_target(  # noqa: SLF001
                self.engine,
                own_idx,
                target_spec,
            )

            min_targets = target_spec.min_targets if target_spec.min_targets is not None else 1
            if target_spec.max_targets_from:
                max_targets = self._count_cards_from_rule(uid, target_spec.max_targets_from)
            else:
                max_targets = target_spec.max_targets if target_spec.max_targets is not None else 1

            allow_none = (min_targets == 0)
            multi = str(target_spec.type or "").strip().lower() == "selected_targets" or max_targets != 1

            if not candidates:
                if allow_none:
                    canceled, selected = self._open_board_target_picker(
                        title="Selezione Bersaglio",
                        prompt="Nessun bersaglio valido disponibile. Conferma se vuoi procedere senza bersaglio.",
                        choices=[],
                        allow_multi=multi,
                        min_targets=min_targets,
                        max_targets=max_targets,
                        allow_none=True,
                        allow_manual=False,
                        card_uid=uid,
                    )
                    if canceled:
                        return (True, None)
                    picked_parts.append(f"{action_idx}={selected or ''}")
                    continue
                messagebox.showwarning("Selezione Bersaglio", "Nessun bersaglio valido disponibile per questa parte dell'effetto.")
                return (True, None)

            choices = [(self._format_guided_candidate(c, own_idx), c) for c in candidates]

            canceled, selected = self._open_board_target_picker(
                title="Selezione Bersaglio",
                prompt="Seleziona i bersagli validi dalla lista oppure cliccando sul campo.",
                choices=choices,
                allow_multi=multi,
                min_targets=min_targets,
                max_targets=max_targets,
                allow_none=allow_none,
                allow_manual=False,
                card_uid=uid,
            )

            if canceled:
                return (True, None)

            picked_parts.append(f"{action_idx}={selected or ''}")

        payload = "seq:" + ";;".join(picked_parts)
        return (False, payload)

    # Handles the guided target selection process when a player attempts to play a card that requires targets, providing a user interface for selecting valid targets based on the card's specifications and the current game state, and then initiates the card play action with the selected targets.
    def ask_guided_quick_target(self, uid: str) -> None:
        if self._has_custom_targeting(uid):
            script = runtime_cards.get_script(self.engine.state.instances[uid].effect_name)
            canceled, target = script.targeting_handlers["gui_target"](self, uid)
            if canceled:
                return
            self.play_uid(uid, target)
            return

        manual_actions = self._manual_play_target_actions(uid)
        if len(manual_actions) > 1:
            canceled, payload = self._collect_on_play_action_targets(uid)
            if canceled:
                return
            self.play_uid(uid, payload)
            return

        if not self._card_requires_target(uid):
            self.play_uid(uid, None)
            return
        if self.engine is None:
            return
        own_idx = self.current_human_idx() or 0
        hand = self.engine.state.players[own_idx].hand
        if uid not in hand:
            return
        hand_idx = hand.index(uid)
        is_quick = self.chain_active
        target_spec = self._first_play_target_spec(uid)
        if target_spec is not None:
            candidates = runtime_cards._collect_selectable_targets_for_manual_target(  # noqa: SLF001
                self.engine,
                own_idx,
                target_spec,
            )
        else:
            candidates = self._guided_target_candidates(uid)
        multi = self._card_allows_multi_target(uid)
        min_targets, max_targets = self._target_selection_limits(uid)
        # For multi-target cards (selected_targets), validating one candidate at a time
        # can incorrectly fail because the simulation expects the full payload.
        if not multi:
            candidates = [c for c in candidates if self._can_play_target(own_idx, hand_idx, c, quick=is_quick)]
        allow_none = self._can_play_target(own_idx, hand_idx, None, quick=is_quick)
        mode = self._play_targeting_mode(uid)
        choices = [(self._format_guided_candidate(c, own_idx), c) for c in candidates]
        if not choices:
            if mode == "manual":
                canceled, selected = self._open_board_target_picker(
                    title="Selezione Bersaglio",
                    prompt="Inserisci manualmente il bersaglio della carta.",
                    choices=[],
                    allow_multi=False,
                    min_targets=0,
                    max_targets=1,
                    allow_none=allow_none,
                    allow_manual=True,
                )
                if canceled:
                    return
                self.play_uid(uid, selected)
                return
            if allow_none:
                canceled, selected = self._open_board_target_picker(
                    title="Selezione Bersaglio",
                    prompt="Nessun bersaglio valido disponibile. Conferma se vuoi procedere senza bersaglio.",
                    choices=[],
                    allow_multi=multi,
                    min_targets=min_targets,
                    max_targets=max_targets,
                    allow_none=True,
                    allow_manual=False,
                    card_uid=uid,
                )
                if canceled:
                    return
                self.play_uid(uid, selected)
                return
            messagebox.showwarning("Selezione Bersaglio", "Nessun bersaglio valido disponibile per questa carta.")
            return
    
        canceled, selected = self._open_board_target_picker(
            title="Selezione Bersaglio",
            prompt="Seleziona i bersagli validi dalla lista oppure cliccando sul campo.",
            choices=choices,
            allow_multi=multi,
            min_targets=min_targets,
            max_targets=max_targets,
            allow_none=allow_none,
            allow_manual=False,
            card_uid=uid,
        )
        if canceled:
            return
        self.play_uid(uid, selected)

    # Executes the action of playing a card with the specified UID and target, handling both regular plays and quick plays during a chain, and providing user feedback if the action is invalid or if certain conditions are not met for playing the card.
    def play_uid(self, uid: str, target: str | None) -> None:
        if self.engine is None or not self.can_human_act():
            return
        own_idx = self.current_human_idx() or 0
        hand = self.engine.state.players[own_idx].hand
        if uid not in hand:
            return
        inst = self.engine.state.instances.get(uid)
        script = runtime_cards.get_script(inst.definition.name) if inst is not None else None

        # Ensure sacrifice-picker flow always runs when required by scripted play costs.
        # This covers non-context-menu play paths (e.g. quick play from selected hand card).
        if (
            script is not None
            and _norm(inst.definition.card_type) in {"santo", "token"}
            and isinstance(script.play_requirements.get("can_play_by_sacrificing"), dict)
            and bool(script.play_requirements.get("choose_play_sacrifices_from_target", False))
        ):
            raw_target = str(target or "")
            if "|sac:" not in raw_target.lower():
                zone_target = raw_target.split("|", 1)[0].strip()
                if zone_target:
                    self.play_saint_with_optional_sacrifice(uid, zone_target)
                    return
        idx = hand.index(uid)
        if self.chain_active:
            ctype = self.engine.state.instances[uid].definition.card_type.lower()
            allows_quick_play = runtime_cards.allows_quick_play(self.engine.state.instances[uid].effect_name, self.engine.state.instances[uid].definition.card_type)
            if ctype not in {"benedizione", "maledizione"} and not allows_quick_play:
                messagebox.showwarning("Catena", "Durante la catena puoi giocare solo Benedizioni/Maledizioni.")
                return
            res = self.engine.quick_play(own_idx, idx, target)
            if res.ok and bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
                self._post_reveal_chain_actor = own_idx
                self._maybe_show_runtime_reveal()
                self.begin_turn_if_needed()
                return
            if res.ok:
                self.chain_pass_count = 0
                self.chain_priority_idx = 1 - own_idx
                self.refresh()
                self._handle_chain_priority()
        else:
            res = self.engine.play_card(own_idx, idx, target)
            if res.ok and bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
                self._post_reveal_chain_actor = own_idx
                self._maybe_show_runtime_reveal()
                self.begin_turn_if_needed()
                return
            if res.ok:
                self.start_chain(actor_idx=own_idx)
        if not res.ok:
            messagebox.showwarning("Azione non valida", res.message)
        self.refresh()
        if not self.chain_active:
            self.begin_turn_if_needed()

    # Handles the special case of playing a Saint card that has the option to be played by sacrificing other Saints, prompting the player to select the required sacrifices if necessary, and then executing the play action with the appropriate target format to indicate the sacrifices made.
    def play_saint_with_optional_sacrifice(self, uid: str, zone_target: str) -> None:
        if self.engine is None:
            return
        own_idx = self.current_human_idx() or 0
        hand = self.engine.state.players[own_idx].hand
        if uid not in hand:
            return

        inst = self.engine.state.instances.get(uid)
        script = runtime_cards.get_script(inst.definition.name) if inst is not None else None
        if not script:
            self.play_uid(uid, zone_target)
            return

        req = script.play_requirements.get("can_play_by_sacrificing")
        needs_choice = bool(script.play_requirements.get("choose_play_sacrifices_from_target", False))
        if not isinstance(req, dict) or not needs_choice:
            self.play_uid(uid, zone_target)
            return

        count = max(1, int(req.get("count", 1) or 1))

        owner_key = _norm(str(req.get("owner", "me")))
        if owner_key in {"opponent", "enemy", "other"}:
            owners = [1 - own_idx]
        elif owner_key in {"any", "both", "all", "either"}:
            owners = [own_idx, 1 - own_idx]
        else:
            owners = [own_idx]

        zones = list(req.get("zones", []) or [])
        if not zones:
            zones = [str(req.get("zone", "field"))]

        card_filter = dict(req.get("card_filter", {}) or {})
        name_eq = _norm(str(card_filter.get("name_equals", "")))
        name_contains = _norm(str(card_filter.get("name_contains", "")))
        type_filter = {_norm(str(v)) for v in list(card_filter.get("card_type_in", []) or []) if str(v).strip()}

        def _zone_uids(owner_idx: int, zone_name: str) -> list[str]:
            p = self.engine.state.players[owner_idx]
            zone = _norm(zone_name)
            if zone == "field":
                out = [x for x in (p.attack + p.defense + p.artifacts) if x]
                if p.building:
                    out.append(p.building)
                return out
            if zone == "attack":
                return [x for x in p.attack if x]
            if zone == "defense":
                return [x for x in p.defense if x]
            if zone in {"artifact", "artifacts"}:
                return [x for x in p.artifacts if x]
            if zone == "building":
                return [p.building] if p.building else []
            if zone == "hand":
                return list(p.hand)
            if zone in {"deck", "relicario"}:
                return list(p.deck)
            if zone == "graveyard":
                return list(p.graveyard)
            if zone == "excommunicated":
                return list(p.excommunicated)
            return []

        def _matches(c_uid: str) -> bool:
            inst2 = self.engine.state.instances.get(c_uid)
            if inst2 is None:
                return False
            card_name_norm = _norm(inst2.definition.name)
            if name_eq and card_name_norm != name_eq:
                return False
            if name_contains and name_contains not in card_name_norm:
                return False
            if type_filter and _norm(inst2.definition.card_type) not in type_filter:
                return False
            return True

        candidates: list[str] = []
        seen: set[str] = set()
        for owner_idx in owners:
            for zone_name in zones:
                for c_uid in _zone_uids(owner_idx, str(zone_name)):
                    if not c_uid or c_uid in seen:
                        continue
                    if not _matches(c_uid):
                        continue
                    candidates.append(c_uid)
                    seen.add(c_uid)

        if not candidates:
            messagebox.showwarning("Sacrificio richiesto", "Non ci sono carte valide da sacrificare.")
            return
        choices = [(self._format_guided_candidate(c_uid, own_idx), c_uid) for c_uid in candidates]
        card_name = inst.definition.name if inst is not None else "Carta"
        canceled, selected = self._open_board_target_picker(
            title=f"{card_name} - Sacrificio",
            prompt=f"Seleziona {count} carta/e da sacrificare.",
            choices=choices,
            allow_multi=(count > 1),
            min_targets=count,
            max_targets=count,
            allow_none=False,
            allow_manual=False,
            card_uid=uid,
        )
        if canceled or not selected:
            return
        target = f"{zone_target}|sac:{selected}"
        self.play_uid(uid, target)

    # Handles the right-click event on the player's own board slots, providing a context menu with options to attack with the card in that slot, activate its abilities, and view details of equipped cards, while also highlighting valid targets for attacks and activations based on the current game state.
    def on_own_slot_right_click(self, source: str) -> None:
        if self.engine is None or not self.can_human_act():
            return
        self._clear_slot_highlights()
        own_idx = self.current_human_idx() or 0
        uid = self.engine.resolve_board_uid(own_idx, source)
        if uid is None:
            return
        menu = tk.Menu(cast(tk.Misc, self), tearoff=0)
        can_open_attack_menu = source.startswith("a") or source.startswith("d")
        if can_open_attack_menu:
            slot = int(source[1])
            from_slot = slot - 1 if source.startswith("a") else -slot
            m_attack = tk.Menu(menu, tearoff=0)
            valid_slots = self._valid_attack_targets(own_idx, from_slot)
            hl_tokens: list[str] = []
            for t_slot in valid_slots:
                if t_slot is None:
                    m_attack.add_command(label="Attacco diretto", command=lambda fs=from_slot: self.do_attack(fs, None))
                else:
                    t = t_slot + 1
                    m_attack.add_command(label=f"Target t{t}", command=lambda fs=from_slot, tt=t: self.do_attack(fs, tt - 1))
                    hl_tokens.append(f"a{t}")
            if not valid_slots:
                m_attack.add_command(label="Nessun bersaglio attaccabile", state="disabled")
            menu.add_cascade(label="Attacca", menu=m_attack)
            if hl_tokens:
                self._set_slot_highlights(hl_tokens, side_hint="enemy")
        has_activation = self._activation_has_any_valid_option(own_idx, source)
        if has_activation:
            menu.add_command(label="Attiva abilita", command=lambda src=source: self.do_activate(src))
        else:
            menu.add_command(label="Attiva abilita", state="disabled")
        equipped_uids = self._equipped_uids_for(uid)
        if equipped_uids:
            m_equipped = tk.Menu(menu, tearoff=0)
            for eq_uid in equipped_uids:
                eq_inst = self.engine.state.instances.get(eq_uid)
                if eq_inst is None:
                    continue
                eq_name = eq_inst.definition.name
                m_equipped.add_command(
                    label=eq_name,
                    command=lambda e_uid=eq_uid: self.show_card_detail(e_uid),
                )
            if m_equipped.index("end") is not None:
                menu.add_separator()
                menu.add_cascade(label="Carte Equipaggiate", menu=m_equipped)
        menu.bind("<Unmap>", lambda _e: self._clear_slot_highlights())
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    # Executes the attack action from a specified slot to a target slot or directly if the target slot is None, handling the game logic for validating the attack, starting a chain if the attack is successful, and providing user feedback if the attack is invalid or if certain conditions are not met for attacking.
    def do_attack(self, from_slot: int, target_slot: int | None) -> None:
        if self.engine is None or not self.can_human_act():
            return
        if self.chain_active:
            messagebox.showwarning("Catena", "Durante la catena puoi solo giocare carte rapide o passare con OK Catena.")
            return
        own_idx = self.current_human_idx() or 0
        res = self.engine.attack(own_idx, from_slot, target_slot)
        if res.ok:
            self.start_chain(actor_idx=own_idx)
        if not res.ok:
            messagebox.showwarning("Attacco non valido", res.message)
        self.refresh()
        self.begin_turn_if_needed()

    # Executes the activation of an ability from a specified source on the player's board, handling the game logic for validating the activation, starting a chain if the activation is successful, and providing user feedback if the activation is invalid or if certain conditions are not met for activating the ability.
    def do_activate(self, source: str) -> None:
        if self.engine is None or not self.can_human_act():
            return
        if self.chain_active:
            messagebox.showwarning("Catena", "Durante la catena puoi solo giocare carte rapide o passare con OK Catena.")
            return
        own_idx = self.current_human_idx() or 0
        uid = self.engine.resolve_board_uid(own_idx, source)
        if uid is None:
            messagebox.showwarning("Abilita non valida", "Sorgente non valida.")
            return
        mode = self._activate_targeting_mode(uid)
        if mode == "none":
            res = self.engine.activate_ability(own_idx, source, None)
            if res.ok and bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
                self._post_reveal_chain_actor = own_idx
                self._maybe_show_runtime_reveal()
                self.begin_turn_if_needed()
                return
            if res.ok:
                self.start_chain(actor_idx=own_idx)
            if not res.ok:
                messagebox.showwarning("Abilita non valida", res.message)
            self.refresh()
            self.begin_turn_if_needed()
            return
        if mode == "manual":
            target_spec = self._first_activate_target_spec(uid)
            if target_spec is not None:
                candidates = self._guided_target_candidates_for_spec(uid, target_spec)
                choices = [(self._format_guided_candidate(c, own_idx), c) for c in candidates]
                min_targets = target_spec.min_targets if target_spec.min_targets is not None else 1
                if target_spec.max_targets_from:
                    max_targets = self._count_cards_from_rule(uid, target_spec.max_targets_from)
                else:
                    max_targets = target_spec.max_targets if target_spec.max_targets is not None else 1
                allow_none = min_targets == 0 and self._can_activate_target(own_idx, source, None)
                if not choices and not allow_none:
                    messagebox.showwarning("Abilita non valida", "Nessun bersaglio valido disponibile.")
                    return
                canceled, target = self._open_board_target_picker(
                    title="Attiva Abilita",
                    prompt="Seleziona un bersaglio valido per l'abilita.",
                    choices=choices,
                    allow_multi=(max_targets is None or max_targets > 1),
                    min_targets=min_targets,
                    max_targets=max_targets,
                    allow_none=allow_none,
                    allow_manual=False,
                    card_uid=uid,
                )
                if canceled:
                    return
            else:
                canceled, target = self._open_board_target_picker(
                    title="Attiva Abilita",
                    prompt="Inserisci manualmente il bersaglio dell'abilita.",
                    choices=[],
                    allow_multi=False,
                    min_targets=0,
                    max_targets=1,
                    allow_none=True,
                    allow_manual=True,
                    card_uid=uid,
                )
                if canceled:
                    return
            res = self.engine.activate_ability(own_idx, source, target)
            if res.ok:
                self.start_chain(actor_idx=own_idx)
            if not res.ok:
                messagebox.showwarning("Abilita non valida", res.message)
            self.refresh()
            self.begin_turn_if_needed()
            return
        min_targets, max_targets = self._target_selection_limits(uid, for_activate=True)
        valid_tokens = self._valid_activation_targets(own_idx, source, uid)
        allow_no_target = self._can_activate_target(own_idx, source, None)

        valid_tokens = [
            tok
            for tok in valid_tokens
            if (
                not self._is_board_token(tok)
                or self._resolve_highlight_widget(tok, own_idx=own_idx, side_hint="auto", card_uid=uid) is not None
            )
        ]

        if not valid_tokens and not allow_no_target:
            messagebox.showwarning("Abilita non valida", "Nessun bersaglio valido disponibile.")
            return

        choices = [(self._format_guided_candidate(c, own_idx), c) for c in valid_tokens]
        canceled, target = self._open_board_target_picker(
            title="Attiva Abilita",
            prompt="Seleziona un bersaglio valido per l'abilita dalla lista oppure cliccando sul campo.",
            choices=choices,
            allow_multi=(max_targets is None or max_targets > 1),
            min_targets=min_targets,
            max_targets=max_targets,
            allow_none=allow_no_target,
            allow_manual=False,
            card_uid=uid,
        )
        if canceled:
            return
        res = self.engine.activate_ability(own_idx, source, target)
        if res.ok and bool(self.engine.state.flags.get("_runtime_waiting_for_reveal")):
            self._post_reveal_chain_actor = own_idx
            self._maybe_show_runtime_reveal()
            self.begin_turn_if_needed()
            return
        if res.ok:
            self.start_chain(actor_idx=own_idx)
        if not res.ok:
            messagebox.showwarning("Abilita non valida", res.message)
        self.refresh()
        self.begin_turn_if_needed()
