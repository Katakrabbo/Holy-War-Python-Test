from __future__ import annotations

from typing import Any

CARD_NAME = """Monsone"""

SCRIPT = {
    "on_play_mode": "scripted",
    "on_enter_mode": "auto",
    "on_activate_mode": "auto",
    "play_targeting": "custom",
    "target_payload_prefix": "monsone",
    "triggered_effects": [],
    "on_play_actions": [
        {
            "target": {"type": "source_card"},
            "effect": {"action": "resolve_monsone_payload"},
        }
    ],
}


def resolve_monsone_payload(self, engine, owner_idx, source_uid, targets, effect):
    raw = self._selected_target_raw_for_current_action(engine)
    if raw.startswith("monsone:"):
        raw = raw.split(":", 1)[1]
    selections: dict[str, list[str]] = {"discard": [], "return": []}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, values = part.split("=", 1)
        key = key.strip().lower()
        if key in selections:
            selections[key] = [uid.strip() for uid in values.split(",") if uid.strip()]

    player = engine.state.players[owner_idx]
    discarded = 0
    for uid in selections["discard"][:3]:
        if uid not in player.hand or uid == source_uid:
            continue
        engine.send_to_graveyard(owner_idx, uid, from_zone_override="hand")
        discarded += 1
    while discarded < 3 and player.deck:
        uid = player.deck[-1]
        engine.send_to_graveyard(owner_idx, uid, from_zone_override="deck")
        discarded += 1

    for uid in selections["return"][:3]:
        inst = engine.state.instances.get(uid)
        if inst is None or not self._is_uid_on_field(engine, uid):
            continue
        try:
            crosses = int(float(inst.definition.crosses))
        except (TypeError, ValueError):
            continue
        if crosses > 8:
            continue
        card_owner = int(inst.owner)
        if self._move_uid_to_zone(engine, uid, "relicario", card_owner):
            engine.state.log(f"{inst.definition.name} torna nel reliquiario.")
    for player_idx in (0, 1):
        engine.rng.shuffle(engine.state.players[player_idx].deck)
    return True


def web_target_options(self, spell_uid: str, player_idx: int) -> list[dict[str, Any]]:
    assert self.engine is not None
    player = self.engine.state.players[player_idx]
    hand = [uid for uid in player.hand if uid != spell_uid]
    field: list[str] = []
    for owner_idx in (0, 1):
        target_player = self.engine.state.players[owner_idx]
        uids = [uid for uid in target_player.attack + target_player.defense + target_player.artifacts if uid]
        if target_player.building:
            uids.append(target_player.building)
        for uid in uids:
            inst = self.engine.state.instances.get(uid)
            try:
                crosses = int(float(inst.definition.crosses)) if inst is not None else 99
            except (TypeError, ValueError):
                crosses = 99
            if crosses <= 8:
                field.append(uid)
    return [
        {
            "action_index": 0, "key": "discard", "zone": "Mano - scarto",
            "minimum": 0, "maximum": min(3, len(hand)),
            "candidates": [self._candidate_option(uid, player_idx) for uid in hand],
        },
        {
            "action_index": 1, "key": "return", "zone": "Terreno - ritorno al reliquiario (Croci <= 8)",
            "minimum": 0, "maximum": min(3, len(field)),
            "candidates": [self._candidate_option(uid, player_idx) for uid in field],
        },
    ]


def gui_target_payload(self, spell_uid: str) -> tuple[bool, str | None]:
    if self.engine is None:
        return (True, None)
    own_idx = self.current_human_idx() or 0
    player = self.engine.state.players[own_idx]

    hand_choices: list[tuple[str, str]] = []
    for h_uid in player.hand:
        if h_uid == spell_uid:
            continue
        c = self.engine.state.instances[h_uid].definition
        hand_choices.append((f"{c.name} ({c.card_type})", h_uid))

    canceled, picked_hand = self._open_board_target_picker(
        title="Monsone - Scarto",
        prompt="Seleziona fino a 3 carte dalla tua mano da mandare al cimitero.",
        choices=hand_choices,
        allow_multi=True,
        min_targets=0,
        max_targets=3,
        allow_none=True,
        allow_manual=False,
        card_uid=spell_uid,
    )
    if canceled:
        return (True, None)
    discard_uids: list[str] = []
    if picked_hand:
        discard_uids = [x for x in picked_hand.split(",") if x]

    field_choices: list[tuple[str, str]] = []
    for p_idx in (0, 1):
        side = "Tuo campo" if p_idx == own_idx else "Campo avversario"
        p = self.engine.state.players[p_idx]
        for i, s_uid in enumerate(p.attack):
            if not s_uid:
                continue
            inst = self.engine.state.instances[s_uid]
            try:
                crosses = int(float(inst.definition.crosses))
            except (ValueError, TypeError):
                crosses = 99
            if crosses <= 8:
                field_choices.append((f"{side} Attacco {i+1} | {inst.definition.name} (Croci {inst.definition.crosses})", s_uid))
        for i, s_uid in enumerate(p.defense):
            if not s_uid:
                continue
            inst = self.engine.state.instances[s_uid]
            try:
                crosses = int(float(inst.definition.crosses))
            except (ValueError, TypeError):
                crosses = 99
            if crosses <= 8:
                field_choices.append((f"{side} Difesa {i+1} | {inst.definition.name} (Croci {inst.definition.crosses})", s_uid))
        for i, a_uid in enumerate(p.artifacts):
            if not a_uid:
                continue
            inst = self.engine.state.instances[a_uid]
            try:
                crosses = int(float(inst.definition.crosses))
            except (ValueError, TypeError):
                crosses = 99
            if crosses <= 8:
                field_choices.append((f"{side} Artefatto {i+1} | {inst.definition.name} (Croci {inst.definition.crosses})", a_uid))
        if p.building:
            b_uid = p.building
            inst = self.engine.state.instances[b_uid]
            try:
                crosses = int(float(inst.definition.crosses))
            except (ValueError, TypeError):
                crosses = 99
            if crosses <= 8:
                field_choices.append((f"{side} Edificio | {inst.definition.name} (Croci {inst.definition.crosses})", b_uid))

    canceled, picked_field = self._open_board_target_picker(
        title="Monsone - Ritorno al Reliquiario",
        prompt="Seleziona fino a 3 carte sul terreno (Croci <= 8) da rimettere nei reliquiari dei rispettivi proprietari.",
        choices=field_choices,
        allow_multi=True,
        min_targets=0,
        max_targets=3,
        allow_none=True,
        allow_manual=False,
        card_uid=spell_uid,
    )
    if canceled:
        return (True, None)
    return_uids: list[str] = []
    if picked_field:
        return_uids = [x for x in picked_field.split(",") if x]

    target = f"monsone:discard={','.join(discard_uids)};return={','.join(return_uids)}"
    return (False, target)


TARGETING_HANDLERS = {"web_options": web_target_options, "gui_target": gui_target_payload}


ACTION_HANDLERS = {
    'resolve_monsone_payload': resolve_monsone_payload,
}
