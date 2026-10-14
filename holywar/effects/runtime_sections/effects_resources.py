from __future__ import annotations

from typing import TYPE_CHECKING

from holywar.effects.runtime import _norm, EffectSpec

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsResourcesMixin:
    if TYPE_CHECKING:
        def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int: ...

    def _apply_effect_resource_action(
        self,
        engine: GameEngine,
        owner_idx: int,
        source_uid: str,
        targets: list[str],
        effect: EffectSpec,
        action: str,
    ) -> bool:
        if action == "inflict_sin_to_event_controller":
            raw_controller = engine.state.flags.get("_runtime_event_controller", owner_idx)
            try:
                target = int(raw_controller)
            except (TypeError, ValueError):
                target = owner_idx
            if target not in {0, 1}:
                target = owner_idx
            amount = max(0, int(effect.amount))
            engine.gain_sin(target, amount)
            if amount > 0:
                engine._emit_event(
                    "on_sin_inflicted",
                    owner_idx,
                    card=source_uid,
                    target_player=target,
                    amount=amount,
                )
            return True
        if action == "inflict_sin":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            amount = max(0, int(effect.amount))
            engine.gain_sin(target, amount)
            if amount > 0:
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}_to_{int(target)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_to_opponent_{int(owner_idx)}"] = (
                    amount if target == (1 - int(owner_idx)) else 0
                )
                engine._emit_event(
                    "on_sin_inflicted",
                    owner_idx,
                    card=source_uid,
                    target_player=int(target),
                    amount=amount,
                )
            return True
        if action == "inflict_sin_from_source_paid_inspiration":
            source_inst = engine.state.instances.get(source_uid)
            if source_inst is None:
                return True
            amount = 0
            for tag in list(source_inst.blessed):
                if not isinstance(tag, str) or not tag.startswith("paid_inspiration_on_summon:"):
                    continue
                try:
                    amount = max(0, int(tag.split(":", 1)[1]))
                except (TypeError, ValueError):
                    amount = 0
                break
            if amount <= 0:
                return True
            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            engine.gain_sin(target, amount)
            if amount > 0:
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}_to_{int(target)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_to_opponent_{int(owner_idx)}"] = (
                    amount if target == (1 - int(owner_idx)) else 0
                )
                engine._emit_event(
                    "on_sin_inflicted",
                    owner_idx,
                    card=source_uid,
                    target_player=int(target),
                    amount=amount,
                )
            return True
        if action == "inflict_sin_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True

            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = int(raw_value)
            except (TypeError, ValueError):
                amount = 0

            if amount <= 0:
                engine.state.flags.pop(flag_name, None)
                return True

            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            engine.gain_sin(target, amount)
            if amount > 0:
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}_to_{int(target)}"] = amount
                engine.state.flags[f"_runtime_last_inflicted_sin_to_opponent_{int(owner_idx)}"] = (
                    amount if target == (1 - int(owner_idx)) else 0
                )
                engine._emit_event(
                    "on_sin_inflicted",
                    owner_idx,
                    card=source_uid,
                    target_player=int(target),
                    amount=amount,
                )
            engine.state.flags.pop(flag_name, None)
            return True
        if action == "inflict_sin_from_flag_scaled":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                base = max(0, int(raw_value))
            except (TypeError, ValueError):
                base = 0
            scale = max(0, int(effect.amount or 1))
            amount = base * scale
            if amount <= 0:
                return True
            target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
            engine.gain_sin(target, amount)
            return True
        if action == "inflict_sin_to_target_owners":
            per_card = max(0, int(effect.amount))
            if per_card <= 0:
                return True
            counts: dict[int, int] = {}
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                counts[inst.owner] = int(counts.get(inst.owner, 0)) + 1
            for p_idx, qty in counts.items():
                if qty > 0:
                    amount = per_card * qty
                    engine.gain_sin(p_idx, amount)
                    engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}"] = amount
                    engine.state.flags[f"_runtime_last_inflicted_sin_by_{int(owner_idx)}_to_{int(p_idx)}"] = amount
                    engine.state.flags[f"_runtime_last_inflicted_sin_to_opponent_{int(owner_idx)}"] = (
                        amount if int(p_idx) == (1 - int(owner_idx)) else 0
                    )
                    engine._emit_event(
                        "on_sin_inflicted",
                        owner_idx,
                        card=source_uid,
                        target_player=int(p_idx),
                        amount=amount,
                    )
            return True
        if action == "remove_sin_equal_to_stored_value":
            default_flag = f"_runtime_last_inflicted_sin_to_opponent_{int(owner_idx)}"
            flag_name = str(effect.flag or default_flag).strip() or default_flag
            amount_raw = engine.state.flags.get(flag_name, 0)
            try:
                amount = max(0, int(amount_raw))
            except (TypeError, ValueError):
                amount = 0
            scale = int(effect.amount) if int(effect.amount) > 0 else 1
            amount *= scale
            divisor = int(effect.divisor) if effect.divisor is not None else 0
            if divisor > 1:
                amount //= divisor
            threshold = int(effect.threshold) if effect.threshold is not None else None
            if threshold is not None:
                amount = min(amount, max(0, threshold))
            if amount > 0:
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                engine.reduce_sin(target, amount)
            if _norm(str(effect.stored or "")) != "keep":
                engine.state.flags.pop(flag_name, None)
            return True
        if action == "remove_sin":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            engine.reduce_sin(target, max(0, int(effect.amount)))
            return True
        if action == "remove_sin_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = max(0, int(raw_value))
            except (TypeError, ValueError):
                amount = 0
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            if amount > 0:
                engine.reduce_sin(target, amount)
            engine.state.flags.pop(flag_name, None)
            return True
        if action == "remove_sin_from_flag_scaled":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                base = max(0, int(raw_value))
            except (TypeError, ValueError):
                base = 0
            scale = max(0, int(effect.amount or 1))
            amount = base * scale
            if amount <= 0:
                return True
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            engine.reduce_sin(target, amount)
            return True
        if action == "set_pending_sin_mirror_once":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            mirror = engine.state.flags.setdefault("sin_mirror_once", {"0": 0, "1": 0})
            key = str(int(target))
            mirror[key] = max(0, int(mirror.get(key, 0))) + max(1, int(effect.amount or 1))
            return True
        if action == "increase_faith_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = int(raw_value)
            except (TypeError, ValueError):
                amount = 0
            if amount <= 0:
                engine.state.flags.pop(flag_name, None)
                return True
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                inst.current_faith = int(inst.current_faith or 0) + amount
            engine.state.flags.pop(flag_name, None)
            return True
        if action == "decrease_faith_from_flag":
            flag_name = str(effect.flag or "").strip()
            if not flag_name:
                return True
            raw_value = engine.state.flags.get(flag_name, 0)
            try:
                amount = max(0, int(raw_value))
            except (TypeError, ValueError):
                amount = 0
            if amount <= 0:
                engine.state.flags.pop(flag_name, None)
                return True
            for t_uid in targets:
                inst = engine.state.instances.get(t_uid)
                if inst is None:
                    continue
                current = int(inst.current_faith or 0)
                inst.current_faith = current - amount
                if _norm(inst.definition.card_type) in {"santo", "token"} and int(inst.current_faith or 0) <= 0:
                    engine.destroy_saint_by_uid(inst.owner, t_uid, cause="effect")
            engine.state.flags.pop(flag_name, None)
            return True
        if action == "add_inspiration":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]
            before = int(player.inspiration)
            player.inspiration = max(0, int(player.inspiration) + int(effect.amount))
            gained = max(0, int(player.inspiration) - before)
            if gained > 0:
                engine._emit_event(
                    "on_inspiration_gained",
                    owner_idx,
                    target_player=int(target),
                    amount=gained,
                    temporary=False,
                )
            return True
        if action == "pay_inspiration":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]

            cost = max(0, int(effect.amount))
            temp = max(0, int(getattr(player, "temporary_inspiration", 0)))
            normal = max(0, int(player.inspiration))

            use_temp = min(temp, cost)
            temp -= use_temp
            cost -= use_temp

            if cost > 0:
                normal = max(0, normal - cost)

            player.temporary_inspiration = temp
            player.inspiration = normal
            return True
        if action == "pay_inspiration_per_target":
            target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
            player = engine.state.players[target]

            cost = max(0, int(effect.amount)) * max(0, int(len(targets)))
            temp = max(0, int(getattr(player, "temporary_inspiration", 0)))
            normal = max(0, int(player.inspiration))

            use_temp = min(temp, cost)
            temp -= use_temp
            cost -= use_temp

            if cost > 0:
                normal = max(0, normal - cost)

            player.temporary_inspiration = temp
            player.inspiration = normal
            return True
        return False
