from __future__ import annotations

from typing import TYPE_CHECKING

from holywar.effects.runtime import _norm, EffectSpec

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsRemovalMixin:
    if TYPE_CHECKING:
        def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int: ...
        def _move_uid_to_zone(self, engine: GameEngine, uid: str, to_zone: str, owner_idx: int) -> bool: ...

    def _apply_effect_removal_action(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
        effect: EffectSpec,
        action: str,
    ) -> bool:
        if action == "destroy_card":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is not None:
                    engine.destroy_any_card(inst.owner, t_uid)
            return True
        if action == "excommunicate_card":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                ctype = _norm(inst.definition.card_type)
                if ctype in {"santo", "token"}:
                    engine.destroy_saint_by_uid(inst.owner, t_uid, excommunicate=True, cause="effect")
                else:
                    engine.excommunicate_card(inst.owner, t_uid)
            return True
        if action == "excommunicate_card_no_sin":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is not None:
                    engine.excommunicate_card(inst.owner, t_uid)
            return True
        if action == "excommunicate_top_cards_from_relicario":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            count = max(1, int(effect.amount or 1))
            promise_state = dict(engine.state.flags.get("deck_graveyard_merge_active", {"0": False, "1": False}) or {"0": False, "1": False})
            merged = bool(promise_state.get(str(target), False))
            for _ in range(count):
                player = engine.state.players[target]
                if merged:
                    if player.deck:
                        top_uid = player.deck[-1]
                        player.deck.pop()
                        engine.excommunicate_card(target, top_uid, from_zone_override="relicario")
                    elif player.graveyard:
                        top_uid = player.graveyard[-1]
                        player.graveyard.pop()
                        engine.excommunicate_card(target, top_uid, from_zone_override="graveyard")
                    else:
                        break
                else:
                    if not player.deck:
                        break
                    top_uid = player.deck[-1]
                    player.deck.pop()
                    engine.excommunicate_card(target, top_uid, from_zone_override="relicario")
            return True
        if action == "remove_from_board_no_sin":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is not None:
                    engine.remove_from_board_no_sin(inst.owner, t_uid)
            return True
        if action == "move_to_hand":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                if self._move_uid_to_zone(engine, t_uid, "hand", inst.owner):
                    engine.state.log(f"{inst.definition.name} viene aggiunta alla mano.")
            return True
        if action == "move_first_to_hand":
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                if self._move_uid_to_zone(engine, t_uid, "hand", inst.owner):
                    engine.state.log(f"{inst.definition.name} viene aggiunta alla mano.")
                break
            return True
        return False
