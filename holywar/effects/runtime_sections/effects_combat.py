from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
import json
from pathlib import Path

from holywar.core import state
from holywar.core import query_helpers as query_ops
from holywar.core.state import MAX_HAND, CardInstance
from holywar.scripting_api import RuleEventContext
from holywar.data.importer import load_cards_json
from holywar.data.models import CardDefinition
from holywar.effects.runtime import (
    _norm,
    _card_name_haystack,
    _card_matches_name,
    EFFECT_ACTION_ALIASES,
    CardFilterSpec,
    TargetSpec,
    EffectSpec,
    ActionSpec,
    CardScript,
)

if TYPE_CHECKING:
    from holywar.core.engine import GameEngine


class RuntimeEffectsCombatMixin:
    if TYPE_CHECKING:
        _temp_faith: ClassVar[dict[int, dict[str, list[tuple[str, int, str]]]]]
        def _resolve_player_scope(self, owner_idx: int, scope: str | None) -> int: ...
        def _resolve_owner_scope(self, owner_idx: int, owner_key: str | None) -> int: ...
        def _get_zone_cards(self, engine: GameEngine, owner_idx: int, zone_name: str) -> list[str]: ...
        def _equipment_target_uid(self, engine: GameEngine, equipment_uid: str) -> str | None: ...
        def _clear_equipment_link(self, engine: GameEngine, equipment_uid: str) -> str | None: ...
        def _place_equipment_on_field(self, engine: GameEngine, owner_idx: int, uid: str) -> bool: ...
        def _remove_uid_from_all_player_zones(self, engine: GameEngine, owner_idx: int, uid: str) -> bool: ...
        def _is_uid_on_field(self, engine: GameEngine, uid: str) -> bool: ...
        def _move_uid_to_zone(self, engine: GameEngine, uid: str, to_zone: str, owner_idx: int) -> bool: ...
        def _selected_target_raw_for_current_action(self, engine: GameEngine) -> str: ...
        def _selected_target_uid_for_current_action(self, engine: GameEngine, owner_idx: int) -> str | None: ...
        def _shuffle_graveyard_if_oltretomba_active(self, engine: GameEngine, player_idx: int) -> None: ...
        def _maybe_auto_activate_discarded_from_hand_by_effect(self, engine: GameEngine, discarded_owner_idx: int, discarded_uid: str, source_uid: str) -> None: ...
        def _resolve_targets(self, engine: GameEngine, owner_idx: int, target: TargetSpec) -> list[str]: ...
        def _summon_generated_token(self, engine: GameEngine, owner_idx: int, token_name: str, preferred_zone: str | None = None, preferred_slot_token: str | None = None) -> str | None: ...
        def _has_invert_saint_summon_aura(self, engine: GameEngine) -> bool: ...
        def _apply_effect(
            self,
            engine: GameEngine,
            owner_idx: int,
            source_uid: str,
            targets: list[str],
            effect: EffectSpec,
        ) -> None: ...
        def resolve_enter(self, engine: GameEngine, player_idx: int, uid: str) -> object: ...
        def is_immune_to_action(self, card_name: str, action_name: str) -> bool: ...
        def get_is_altare_sigilli(self, card_name: str) -> bool: ...
        def _count_named_cards_on_field(self, engine: GameEngine, card_name: str) -> int: ...
        def _effect_usage_consume(self, engine: GameEngine, owner_idx: int, source_uid: str, effect: EffectSpec) -> None: ...
        def get_context_bonus_amount(
            self,
            engine: GameEngine,
            owner_idx: int,
            context: str,
            amount_mode: str = "flat",
            target_uid: str | None = None,
        ) -> int: ...

    def _apply_effect_combat_action(self, engine: GameEngine, owner_idx: int, source_uid: str, targets: list[str], effect: EffectSpec, action: str) -> bool:
            if action == "increase_faith":
                for t_uid in targets:
                    inst = engine.state.instances[t_uid]
                    inst.current_faith = (inst.current_faith or 0) + int(effect.amount)
                    if _norm(effect.duration) in {"until_source_leaves", "while_source_on_field", "source_bound"}:
                        marker = f"runtime_faith:{source_uid}:{int(effect.amount)}"
                        inst.blessed.append(marker)
                        ek = id(engine)
                        by_source = self._temp_faith.setdefault(ek, {}).setdefault(source_uid, [])
                        by_source.append((t_uid, int(effect.amount), marker))
                return True
            if action == "increase_faith_equal_to_base":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    base_faith = max(0, int(inst.definition.faith or 0))
                    if base_faith <= 0:
                        continue
                    inst.current_faith = (inst.current_faith or 0) + base_faith
                return True
            if action == "increase_strength":
                for t_uid in targets:
                    engine.state.instances[t_uid].blessed.append(f"buff_str:{int(effect.amount)}")
                return True
            if action == "increase_strength_equal_to_target_base_faith":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    bonus = max(0, int(inst.definition.faith or 0))
                    if bonus <= 0:
                        continue
                    inst.blessed.append(f"buff_str:{bonus}")
                return True
            if action == "increase_source_stats_from_zone_count_div":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                zone_name = str(effect.zone or "graveyard").strip() or "graveyard"
                cards_in_zone = self._get_zone_cards(engine, target, zone_name)
                threshold = max(0, int(effect.threshold or 1))
                if len(cards_in_zone) < threshold:
                    return True
                divisor = max(1, int(effect.divisor or 1))
                per_amount = int(effect.amount or 0)
                bonus = (len(cards_in_zone) // divisor) * per_amount
                if bonus <= 0:
                    return True
                source_inst.current_faith = int(source_inst.current_faith or 0) + int(bonus)
                source_inst.blessed.append(f"buff_str:{int(bonus)}")
                return True
            if action == "grant_attack_barrier":
                charges = max(1, int(effect.amount or 1))
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    for _ in range(charges):
                        inst.blessed.append(f"barrier_once:attack:{source_uid}")
                return True
            if action == "grant_blessed_tag_from_source":
                tag_base = str(effect.flag or "").strip()
                if not tag_base:
                    return True
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    marker = f"{tag_base}:{source_uid}"
                    if marker not in inst.blessed:
                        inst.blessed.append(marker)
                return True
            if action == "prevent_specific_card_from_attacking":
                duration_turns = max(1, int(effect.amount or 1))
                until_turn = int(engine.state.turn_number) + duration_turns - 1
                tag = f"no_attack_until:{until_turn}"
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    if tag not in inst.cursed:
                        inst.cursed.append(tag)
                return True
            if action == "negate_next_activation":
                duration_turns = max(1, int(effect.amount or 1))
                until_turn = int(engine.state.turn_number) + duration_turns - 1
                tag = f"no_activate_until:{until_turn}"
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    if tag not in inst.cursed:
                        inst.cursed.append(tag)
                return True
            if action == "grant_counter_spell":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                amount = max(1, int(effect.amount or 1))
                flags = engine.state.flags.setdefault("counter_spell_ready", {"0": 0, "1": 0})
                key = str(target)
                flags[key] = int(flags.get(key, 0)) + amount
                return True
            if action == "grant_extra_attack_this_turn":
                current_turn = int(engine.state.turn_number)
                tag = f"extra_attack_turn:{current_turn}"
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    inst.blessed = [t for t in inst.blessed if not (isinstance(t, str) and t.startswith("extra_attack_turn:"))]
                    inst.blessed.append(tag)
                return True
            if action == "equip_card":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                source_is_artifact = _norm(source_inst.definition.card_type) == _norm("artefatto")
                for t_uid in targets:
                    target_inst = engine.state.instances.get(t_uid)
                    if target_inst is None:
                        continue
                    if not self._is_uid_on_field(engine, t_uid):
                        continue
                    previous_target = self._clear_equipment_link(engine, source_uid)
                    if source_is_artifact and not self._place_equipment_on_field(engine, source_inst.owner, source_uid):
                        if previous_target and previous_target in engine.state.instances:
                            source_inst.blessed.append(f"equipped_to:{previous_target}")
                            prev_inst = engine.state.instances[previous_target]
                            if f"equipped_by:{source_uid}" not in prev_inst.blessed:
                                prev_inst.blessed.append(f"equipped_by:{source_uid}")
                        continue
                    if not source_is_artifact:
                        self._remove_uid_from_all_player_zones(engine, source_inst.owner, source_uid)
                    source_inst.blessed.append(f"equipped_to:{t_uid}")
                    equip_tag = f"equipped_by:{source_uid}"
                    if equip_tag not in target_inst.blessed:
                        target_inst.blessed.append(equip_tag)
                    engine._emit_event(
                        "on_player_equips_card",
                        owner_idx,
                        card=source_uid,
                        equipment=source_uid,
                        target=t_uid,
                    )
                    break
                return True
            if action == "unequip_card":
                to_zone = str(effect.to_zone or "").strip()
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    target_uid = self._clear_equipment_link(engine, t_uid)
                    engine._emit_event(
                        "on_player_unequips_card",
                        owner_idx,
                        card=t_uid,
                        equipment=t_uid,
                        target=target_uid,
                    )
                    if to_zone:
                        self._move_uid_to_zone(engine, t_uid, to_zone, inst.owner)
                return True
            if action == "destroy_equipment":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    target_uid = self._clear_equipment_link(engine, t_uid)
                    engine._emit_event(
                        "on_player_unequips_card",
                        owner_idx,
                        card=t_uid,
                        equipment=t_uid,
                        target=target_uid,
                    )
                    engine.send_to_graveyard(inst.owner, t_uid)
                return True
            if action == "destroy_equipped_target_and_excommunicate_source":
                source_inst = engine.state.instances.get(source_uid)
                equipped_uid = self._clear_equipment_link(engine, source_uid)
                equipped_inst = engine.state.instances.get(equipped_uid or "")
                if equipped_uid and equipped_inst is not None and self._is_uid_on_field(engine, equipped_uid):
                    engine.destroy_saint_by_uid(equipped_inst.owner, equipped_uid, cause="effect")
                if source_inst is not None:
                    self._move_uid_to_zone(
                        engine,
                        source_uid,
                        "excommunicated",
                        source_inst.owner,
                    )
                    engine._emit_event(
                        "on_card_excommunicated",
                        source_inst.owner,
                        card=source_uid,
                        from_zone="equipped",
                        owner=source_inst.owner,
                    )
                return True
            if action == "absorb_target_stats_and_link":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                for t_uid in targets:
                    target_inst = engine.state.instances.get(t_uid)
                    if target_inst is None:
                        continue
                    gain_faith = max(0, int(target_inst.current_faith or 0))
                    gain_strength = max(0, int(engine.get_effective_strength(t_uid)))
                    source_inst.current_faith = max(0, int(source_inst.current_faith or 0) + gain_faith)
                    if gain_strength > 0:
                        source_inst.blessed.append(f"buff_str:{gain_strength}")
                    link_tag = f"levigata_link:{t_uid}"
                    if link_tag not in source_inst.blessed:
                        source_inst.blessed.append(link_tag)
                    break
                return True
            if action == "decrease_strength":
                amount = max(0, int(effect.amount))
                if amount <= 0:
                    return True
                for t_uid in targets:
                    engine.state.instances[t_uid].blessed.append(f"buff_str:{-amount}")
                return True
            if action == "halve_strength_rounded_down":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    current_strength = max(0, int(engine.get_effective_strength(t_uid)))
                    reduced = current_strength // 2
                    delta = current_strength - reduced
                    if delta > 0:
                        inst.blessed.append(f"buff_str:{-delta}")
                return True
            if action == "halve_target_base_faith_rounded_down":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    base_faith = int(inst.definition.faith or 0)
                    halved = max(0, base_faith // 2)
                    inst.definition.faith = halved
                    if inst.current_faith is not None and int(inst.current_faith) > halved:
                        inst.current_faith = halved
                return True
            if action == "retaliate_damage_to_event_source_if_enemy_saint":
                dmg = max(0, int(effect.amount or 0))
                if dmg <= 0:
                    return True
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                attacker_uid = str(engine.state.flags.get("_runtime_event_source", "")).strip()
                if not attacker_uid or attacker_uid not in engine.state.instances:
                    return True
                attacker_inst = engine.state.instances[attacker_uid]
                if int(attacker_inst.owner) == int(owner_idx):
                    return True
                if _norm(attacker_inst.definition.card_type) not in {"santo", "token"}:
                    return True
                dmg = engine._apply_damage_mitigation(attacker_inst.owner, dmg, target_uid=attacker_uid)
                if dmg <= 0:
                    return True
                before = attacker_inst.current_faith or 0
                attacker_inst.current_faith = max(0, (attacker_inst.current_faith or 0) - dmg)
                after = attacker_inst.current_faith or 0
                engine.state.log(
                    f"{attacker_inst.definition.name} subisce {dmg} danni di ritorsione (Fede {before}->{after})."
                )
                if (attacker_inst.current_faith or 0) <= 0:
                    engine.destroy_saint_by_uid(attacker_inst.owner, attacker_uid, cause="effect")
                return True
            if action == "retaliate_event_damage_to_event_source_if_enemy_saint":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                attacker_uid = str(engine.state.flags.get("_runtime_event_source", "")).strip()
                if not attacker_uid or attacker_uid not in engine.state.instances:
                    return True
                attacker_inst = engine.state.instances[attacker_uid]
                if int(attacker_inst.owner) == int(owner_idx):
                    return True
                if _norm(attacker_inst.definition.card_type) not in {"santo", "token"}:
                    return True
                try:
                    dmg = max(0, int(engine.state.flags.get("_runtime_event_amount", "0") or 0))
                except (TypeError, ValueError):
                    dmg = 0
                if dmg <= 0:
                    return True
                dmg = engine._apply_damage_mitigation(attacker_inst.owner, dmg, target_uid=attacker_uid)
                if dmg <= 0:
                    return True
                before = attacker_inst.current_faith or 0
                attacker_inst.current_faith = max(0, (attacker_inst.current_faith or 0) - dmg)
                after = attacker_inst.current_faith or 0
                engine.state.log(
                    f"{attacker_inst.definition.name} subisce {dmg} danni di ritorsione (Fede {before}->{after})."
                )
                if (attacker_inst.current_faith or 0) <= 0:
                    base_faith = max(0, int(attacker_inst.definition.faith or 0))
                    engine.destroy_saint_by_uid(attacker_inst.owner, attacker_uid, cause="effect", by_whom=source_uid)
                    if base_faith > 0:
                        engine.reduce_sin(owner_idx, base_faith)
                return True
            if action == "retaliate_event_damage_divided_to_event_source_if_enemy_saint":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                attacker_uid = str(engine.state.flags.get("_runtime_event_source", "")).strip()
                if not attacker_uid or attacker_uid not in engine.state.instances:
                    return True
                attacker_inst = engine.state.instances[attacker_uid]
                if int(attacker_inst.owner) == int(owner_idx):
                    return True
                if _norm(attacker_inst.definition.card_type) not in {"santo", "token"}:
                    return True
                try:
                    event_amount = max(0, int(engine.state.flags.get("_runtime_event_amount", "0") or 0))
                except (TypeError, ValueError):
                    event_amount = 0
                if event_amount <= 0:
                    return True
                scale = max(1, int(effect.amount or 1))
                divisor = max(1, int(effect.divisor or 2))
                dmg = (event_amount * scale) // divisor
                if dmg <= 0:
                    return True
                dmg = engine._apply_damage_mitigation(attacker_inst.owner, dmg, target_uid=attacker_uid)
                if dmg <= 0:
                    return True
                before = attacker_inst.current_faith or 0
                attacker_inst.current_faith = max(0, (attacker_inst.current_faith or 0) - dmg)
                after = attacker_inst.current_faith or 0
                engine.state.log(
                    f"{attacker_inst.definition.name} subisce {dmg} danni di ritorsione (Fede {before}->{after})."
                )
                if (attacker_inst.current_faith or 0) <= 0:
                    engine.destroy_saint_by_uid(attacker_inst.owner, attacker_uid, cause="effect")
                return True
            if action == "destroy_source_if_linked_to_event_card":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
                if not event_uid:
                    return True
                link_tag = f"levigata_link:{event_uid}"
                if link_tag not in source_inst.blessed:
                    return True
                engine.destroy_saint_by_uid(source_inst.owner, source_uid, cause="effect")
                return True
            if action == "destroy_source_if_equipped_target_is_event_card":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
                if not event_uid:
                    return True
                equipped_uid = self._equipment_target_uid(engine, source_uid)
                if not equipped_uid or equipped_uid != event_uid:
                    return True
                engine.destroy_any_card(source_inst.owner, source_uid)
                return True
            if action == "move_source_to_zone_if_equipped_target_is_event_card":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
                if not event_uid:
                    return True
                equipped_uid = self._equipment_target_uid(engine, source_uid)
                if not equipped_uid or equipped_uid != event_uid:
                    return True
                to_zone = str(effect.to_zone or "").strip()
                if not to_zone:
                    return True
                self._move_uid_to_zone(engine, source_uid, to_zone, source_inst.owner)
                return True
            if action == "inflict_sin_to_event_owner_equal_base_faith_if_equipped_target":
                event_uid = str(engine.state.flags.get("_runtime_event_card", "")).strip()
                if not event_uid or event_uid not in engine.state.instances:
                    return True
                equipped_uid = self._equipment_target_uid(engine, source_uid)
                if not equipped_uid or equipped_uid != event_uid:
                    return True
                event_inst = engine.state.instances[event_uid]
                amount = max(0, int(event_inst.definition.faith or 0))
                if amount <= 0:
                    return True
                engine.gain_sin(int(event_inst.owner), amount)
                return True
            if action == "reveal_stored_card":
                store_name = str(effect.stored or "").strip()
                if not store_name:
                    return True

                stored_uid = str(engine.state.flags.get(f"_runtime_store_{store_name}", "")).strip()
                if not stored_uid:
                    return True

                engine.state.flags["_runtime_reveal_card"] = stored_uid
                engine.state.flags["_runtime_waiting_for_reveal"] = True
                return True
            if action == "reveal_selected_target":
                selected_uid = self._selected_target_uid_for_current_action(engine, owner_idx)
                if not selected_uid:
                    return True
                engine.state.flags["_runtime_reveal_card"] = selected_uid
                engine.state.flags["_runtime_waiting_for_reveal"] = True
                return True
            if action == "add_temporary_inspiration":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                player = engine.state.players[target]
                before = int(getattr(player, "temporary_inspiration", 0))
                player.temporary_inspiration = max(
                    0,
                    before + int(effect.amount)
                )
                gained = max(0, int(getattr(player, "temporary_inspiration", 0)) - before)
                if gained > 0:
                    engine._emit_event(
                        "on_inspiration_gained",
                        owner_idx,
                        target_player=int(target),
                        amount=gained,
                        temporary=True,
                    )
                return True
        
            if action == "store_target_strength":
                flag_name = str(effect.flag or "").strip()
                if not flag_name:
                    return True

                value = 0
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    value = max(0, int(engine.get_effective_strength(t_uid) or 0))
                    break

                engine.state.flags[flag_name] = value
                return True

            if action == "store_target_faith":
                flag_name = str(effect.flag or "").strip()
                if not flag_name:
                    return True

                value = 0
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    value = max(0, int(inst.current_faith or 0))
                    break

                engine.state.flags[flag_name] = value
                return True
            if action == "store_target_faith_and_excommunicate_no_sin":
                flag_name = str(effect.flag or "").strip()
                if not flag_name:
                    return True

                value = 0
                selected_uid: str | None = None
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    value = max(0, int(inst.current_faith or 0))
                    selected_uid = t_uid
                    break

                engine.state.flags[flag_name] = value
                if selected_uid:
                    target_inst = engine.state.instances.get(selected_uid)
                    if target_inst is not None:
                        engine.excommunicate_card(target_inst.owner, selected_uid)
                return True
        
            if action == "store_top_card_of_zone":
                store_name = str(effect.store_as or "").strip()
                if not store_name:
                    return True

                scoped_owner = self._resolve_owner_scope(owner_idx, effect.owner or "me")
                zone_name = str(effect.zone or "deck").strip()
                position = _norm(effect.position or "top")

                cards = self._get_zone_cards(engine, scoped_owner, zone_name)

                picked_uid = ""
                if cards:
                    picked_uid = cards[-1] if position == "top" else cards[0]

                engine.state.flags[f"_runtime_store_{store_name}"] = picked_uid
                return True
        
            if action == "move_stored_card_to_zone":
                store_name = str(effect.stored or "").strip()
                to_zone = str(effect.to_zone or "").strip()
                if not store_name or not to_zone:
                    return True

                stored_uid = str(engine.state.flags.get(f"_runtime_store_{store_name}", "")).strip()
                if not stored_uid:
                    return True

                self._move_uid_to_zone(engine, stored_uid, to_zone, owner_idx)
                return True

            if action == "destroy_stored_card":
                store_name = str(effect.stored or "").strip()
                if not store_name:
                    return True

                stored_uid = str(engine.state.flags.get(f"_runtime_store_{store_name}", "")).strip()
                if not stored_uid or stored_uid not in engine.state.instances:
                    return True

                source_name = ""
                if source_uid and source_uid in engine.state.instances:
                    source_name = str(engine.state.instances[source_uid].definition.name or "").strip()
                inst = engine.state.instances.get(stored_uid)
                if inst is None:
                    return True
                if _norm(source_name) == _norm("Ponte tra Cielo e Polvere"):
                    me_field_before = [
                        engine.state.instances[uid].definition.name
                        for uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
                        if uid and uid in engine.state.instances
                    ]
                    engine.state.log(
                        "[PONTE][DESTROY_STORED][BEFORE] "
                        f"source_uid={source_uid} stored_uid={stored_uid} stored_name={inst.definition.name} "
                        f"owner={inst.owner} my_field={me_field_before}"
                    )
                    ctype = _norm(inst.definition.card_type)
                    if ctype in {"santo", "token"}:
                        engine.destroy_saint_by_uid(inst.owner, stored_uid, cause="effect", by_whom=str(source_uid or ""))
                    else:
                        engine.destroy_any_card(inst.owner, stored_uid)
                    me_field_after = [
                        engine.state.instances[uid].definition.name
                        for uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
                        if uid and uid in engine.state.instances
                    ]
                    engine.state.log(
                        "[PONTE][DESTROY_STORED][AFTER] "
                        f"source_uid={source_uid} stored_uid={stored_uid} my_field={me_field_after}"
                    )
                else:
                    engine.destroy_any_card(inst.owner, stored_uid)
                return True
        
            if action == "summon_stored_card_to_field":
                store_name = str(effect.stored or "").strip()
                if not store_name:
                    return True

                stored_uid = str(engine.state.flags.get(f"_runtime_store_{store_name}", "")).strip()
                if not stored_uid or stored_uid not in engine.state.instances:
                    return True

                self._apply_effect(
                    engine,
                    owner_idx,
                    source_uid,
                    [stored_uid],
                    EffectSpec(action="summon_target_to_field"),
                )
                return True
        
            if action == "move_source_to_zone":
                to_zone = str(effect.to_zone or "").strip()
                if not source_uid or not to_zone:
                    return True

                self._move_uid_to_zone(engine, source_uid, to_zone, owner_idx)
                return True
         
            if action == "add_temporary_inspiration_from_flag":
                flag_name = str(effect.flag or "").strip()
                if not flag_name:
                    return True

                raw_value = engine.state.flags.get(flag_name, 0)
                try:
                    amount = int(raw_value)
                except (TypeError, ValueError):
                    amount = 0

                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                player = engine.state.players[target]
                before = int(getattr(player, "temporary_inspiration", 0))
                player.temporary_inspiration = max(
                    0,
                    before + amount
                )
                gained = max(0, int(getattr(player, "temporary_inspiration", 0)) - before)
                if gained > 0:
                    engine._emit_event(
                        "on_inspiration_gained",
                        owner_idx,
                        target_player=int(target),
                        amount=gained,
                        temporary=True,
                    )

                engine.state.flags.pop(flag_name, None)
                return True
        
            if action == "gain_inspiration_from_flag":
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

                # Adatta questo campo al nome reale che usi per l'ispirazione extra nel turno
                current = int(engine.state.flags.get("_extra_inspiration_this_turn", 0))
                engine.state.flags["_extra_inspiration_this_turn"] = current + amount

                engine.state.flags.pop(flag_name, None)
                return True
        
            if action == "store_target_strength":
                flag_name = str(effect.flag or "").strip()
                if not flag_name:
                    return True

                value = 0
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    value = max(0, int(engine.get_effective_strength(t_uid) or 0))
                    break

                engine.state.flags[flag_name] = value
                return True
        
            if action == "remove_sin_equal_to_target_strength":
                target_player = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                player = engine.state.players[target_player]

                amount = 0
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    amount = max(0, int(engine.get_effective_strength(t_uid) or 0))
                    break

                player.sin = max(0, int(player.sin) - amount)
                return True
            if action == "remove_sin_equal_to_target_faith_and_strength":
                target_player = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                player = engine.state.players[target_player]

                amount = 0
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue

                    strength_base = int(inst.definition.strength or 0)
                    strength_bonus = 0
                    for tag in list(inst.blessed) + list(inst.cursed):
                        if isinstance(tag, str) and tag.startswith("buff_str:"):
                            try:
                                strength_bonus += int(tag.split(":", 1)[1])
                            except ValueError:
                                pass

                    total_strength = max(0, strength_base + strength_bonus)
                    total_faith = max(0, int(inst.current_faith or 0))
                    amount = total_strength + total_faith
                    break

                player.sin = max(0, int(player.sin) - amount)
                return True

            if action == "reset_faith_to_base":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    if inst.current_faith is None:
                        continue

                    base_faith = inst.definition.faith
                    if base_faith is None:
                        continue

                    inst.current_faith = base_faith

                    engine._emit_event(
                        "on_faith_modified",
                        inst.owner,
                        card=t_uid,
                        amount=0,
                    )
                return True
            if action == "set_faith_to":
                value = max(0, int(effect.amount))
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue
                    inst.current_faith = value
                    if value <= 0 and _norm(inst.definition.card_type) in {"santo", "token"}:
                        engine.destroy_saint_by_uid(inst.owner, t_uid, cause="effect")
                return True
        
            if action == "summon_target_to_field":
                source_name_dbg = ""
                if source_uid and source_uid in engine.state.instances:
                    source_name_dbg = str(engine.state.instances[source_uid].definition.name or "").strip()
                is_ponte_flow = _norm(source_name_dbg) == _norm("Ponte tra Cielo e Polvere")
                if is_ponte_flow:
                    chosen_names = [
                        engine.state.instances[t_uid].definition.name
                        for t_uid in targets
                        if t_uid in engine.state.instances
                    ]
                    my_field_before = [
                        engine.state.instances[uid].definition.name
                        for uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
                        if uid and uid in engine.state.instances
                    ]
                    engine.state.log(
                        "[PONTE][SUMMON][BEFORE] "
                        f"source_uid={source_uid} targets={targets} target_names={chosen_names} my_field={my_field_before}"
                    )
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue

                    owner = inst.owner
                    board_owner = owner
                    player = engine.state.players[owner]
                    ctype = _norm(inst.definition.card_type)
                    if ctype == _norm("santo") and self._has_invert_saint_summon_aura(engine):
                        board_owner = 1 - board_owner
                    board_player = engine.state.players[board_owner]

                    if t_uid in player.hand:
                        player.hand.remove(t_uid)
                        actual_from_zone = "hand"
                    elif t_uid in player.deck:
                        player.deck.remove(t_uid)
                        actual_from_zone = "deck"
                    elif t_uid in player.graveyard:
                        player.graveyard.remove(t_uid)
                        actual_from_zone = "graveyard"
                    elif t_uid in player.excommunicated:
                        player.excommunicated.remove(t_uid)
                        actual_from_zone = "excommunicated"
                    elif t_uid in player.attack:
                        player.attack[player.attack.index(t_uid)] = None
                        actual_from_zone = "attack"
                    elif t_uid in player.defense:
                        player.defense[player.defense.index(t_uid)] = None
                        actual_from_zone = "defense"
                    elif t_uid in player.artifacts:
                        player.artifacts[player.artifacts.index(t_uid)] = None
                        actual_from_zone = "artifacts"
                    elif player.building == t_uid:
                        player.building = None
                        actual_from_zone = "building"
                    else:
                        actual_from_zone = "summon"

                    placed = False

                    if ctype == _norm("artefatto"):
                        blocked_slots = query_ops.get_blocked_artifact_slots_for_player(engine, owner)
                        usable_slots = [idx for idx in range(state.ARTIFACT_SLOTS) if idx not in blocked_slots]
                        if usable_slots:
                            slot = next((i for i in usable_slots if player.artifacts[i] is None), None)
                            if slot is None:
                                slot = usable_slots[-1]
                                replaced = player.artifacts[slot]
                                if replaced:
                                    engine.send_to_graveyard(owner, replaced)
                            player.artifacts[slot] = t_uid
                            placed = True

                    elif ctype == _norm("edificio"):
                        if player.building is None:
                            player.building = t_uid
                            placed = True

                    else:
                        attack_slots = [f"a{i + 1}" for i, u in enumerate(board_player.attack) if u is None]
                        defense_slots = [f"d{i + 1}" for i, u in enumerate(board_player.defense) if u is None]
                        open_slots = attack_slots + defense_slots
                        slot = None
                        zone = "attack"
                        if open_slots:
                            chosen_token = ""
                            chooser = getattr(engine, "choose_summon_slot", None)
                            if not callable(chooser):
                                chooser = getattr(engine, "choose_auto_play_slot_from_draw", None)
                            if callable(chooser):
                                try:
                                    chosen_token = str(chooser(board_owner, t_uid, open_slots) or "").strip().lower()
                                except Exception:
                                    chosen_token = ""
                            if chosen_token in {s.lower() for s in open_slots}:
                                if chosen_token.startswith("a"):
                                    zone = "attack"
                                    slot = int(chosen_token[1:]) - 1
                                elif chosen_token.startswith("d"):
                                    zone = "defense"
                                    slot = int(chosen_token[1:]) - 1
                            if slot is None:
                                slot = engine._first_open(board_player.attack)
                                zone = "attack"
                                if slot is None:
                                    slot = engine._first_open(board_player.defense)
                                    zone = "defense"
                        if slot is not None and engine.place_card_from_uid(board_owner, t_uid, zone, slot):
                            placed = True

                    if not placed:
                        card_name = inst.definition.name
                        owner_name = engine.state.players[owner].name
                        engine.state.log(
                            f"{owner_name}: impossibile evocare {card_name} ora (nessuno slot valido disponibile)."
                        )
                        if actual_from_zone == "hand":
                            if t_uid not in player.hand:
                                player.hand.append(t_uid)
                        elif actual_from_zone == "graveyard":
                            if t_uid not in player.graveyard:
                                player.graveyard.append(t_uid)
                        elif actual_from_zone in {"deck", "relicario"}:
                            if t_uid not in player.deck:
                                player.deck.append(t_uid)
                        elif actual_from_zone == "excommunicated":
                            if t_uid not in player.excommunicated:
                                player.excommunicated.append(t_uid)
                        elif actual_from_zone == "attack":
                            restore = engine._first_open(player.attack)
                            if restore is not None:
                                player.attack[restore] = t_uid
                            else:
                                player.graveyard.append(t_uid)
                        elif actual_from_zone == "defense":
                            restore = engine._first_open(player.defense)
                            if restore is not None:
                                player.defense[restore] = t_uid
                            else:
                                player.graveyard.append(t_uid)
                        elif actual_from_zone == "artifacts":
                            restore = engine._first_open(player.artifacts)
                            if restore is not None:
                                player.artifacts[restore] = t_uid
                            else:
                                player.graveyard.append(t_uid)
                        elif actual_from_zone == "building":
                            if player.building is None:
                                player.building = t_uid
                            else:
                                player.graveyard.append(t_uid)
                        else:
                            player.graveyard.append(t_uid)
                        continue

                    inst.exhausted = False
                    if ctype in {_norm("santo"), _norm("token")}:
                        bonus_multiplier = self.get_context_bonus_amount(
                            engine,
                            owner,
                            context="summon_faith",
                            amount_mode="base_faith_multiplier",
                        )
                        if bonus_multiplier > 0:
                            inst.current_faith = (inst.current_faith or 0) + max(0, int(inst.definition.faith or 0)) * bonus_multiplier
                        bonus_flat = self.get_context_bonus_amount(
                            engine,
                            owner,
                            context="summon_faith",
                            amount_mode="flat",
                        )
                        if bonus_flat > 0:
                            inst.current_faith = (inst.current_faith or 0) + int(bonus_flat)

                    engine._emit_event("on_enter_field", owner, card=t_uid, from_zone=actual_from_zone)
                    if actual_from_zone == "graveyard":
                        engine._emit_event("on_summoned_from_graveyard", owner, card=t_uid)
                    elif actual_from_zone == "hand":
                        engine._emit_event("on_summoned_from_hand", owner, card=t_uid)
                    if ctype == _norm("token"):
                        engine._emit_event("on_token_summoned", owner, token=t_uid, summoner=owner)
                    elif ctype == _norm("santo"):
                        engine._emit_event("on_opponent_saint_enters_field", 1 - owner, saint=t_uid)
                    enter_msg = self.resolve_enter(engine, owner, t_uid)
                    if enter_msg:
                        engine.state.log(str(enter_msg))
                if is_ponte_flow:
                    my_field_after = [
                        engine.state.instances[uid].definition.name
                        for uid in (engine.state.players[owner_idx].attack + engine.state.players[owner_idx].defense)
                        if uid and uid in engine.state.instances
                    ]
                    engine.state.log(
                        "[PONTE][SUMMON][AFTER] "
                        f"source_uid={source_uid} my_field={my_field_after}"
                    )
                return True

            if action == "return_to_hand":
                for uid in targets:
                    inst = engine.state.instances.get(uid)
                    if inst is None:
                        continue

                    owner = inst.owner
                    if not engine.move_board_card_to_hand(owner, uid):
                        continue
                    self._effect_usage_consume(engine, owner_idx, source_uid, effect)
                return True
            if action == "send_to_graveyard":
                for t_uid in targets:
                    inst = engine.state.instances.get(t_uid)
                    if inst is None:
                        continue

                    owner = inst.owner
                    player = engine.state.players[owner]

                    # Caso: carta in mano → SCARTO
                    if t_uid in player.hand:
                        player.hand.remove(t_uid)
                        if t_uid not in player.graveyard:
                            player.graveyard.append(t_uid)
                            self._shuffle_graveyard_if_oltretomba_active(engine, owner)

                        engine._emit_event(
                            "on_card_discarded",
                            owner,
                            card=t_uid,
                            from_hand_to_graveyard=True,
                        )

                        engine._emit_event(
                            "on_card_sent_to_graveyard",
                            owner,
                            card=t_uid,
                            from_zone="hand",
                            owner=owner,
                        )
                        self._maybe_auto_activate_discarded_from_hand_by_effect(engine, owner, t_uid, source_uid)
                        continue

                    # Caso: carta nel deck
                    if t_uid in player.deck:
                        player.deck.remove(t_uid)
                        if t_uid not in player.graveyard:
                            player.graveyard.append(t_uid)
                            self._shuffle_graveyard_if_oltretomba_active(engine, owner)

                        engine._emit_event(
                            "on_card_sent_to_graveyard",
                            owner,
                            card=t_uid,
                            from_zone="relicario",
                            owner=owner,
                        )
                        continue

                    # Caso: già nel cimitero
                    if t_uid in player.graveyard:
                        continue

                    # Caso: carta sul campo → usa funzione già esistente
                    engine.send_to_graveyard(owner, t_uid)

                return True
            if action == "double_strength":
                for t_uid in targets:
                    inst = engine.state.instances[t_uid]
                    current = engine.get_effective_strength(t_uid)
                    base = max(0, inst.definition.strength or 0)
                    bonus = current - base
                    inst.definition.strength = max(0, base + bonus)
                    inst.blessed.append(f"buff_str:{current}")
                return True
            if action == "add_seal_counter":
                amount = max(0, int(effect.amount))
                if amount <= 0:
                    return True
                before = engine._get_altare_sigilli(owner_idx)
                after = before + amount
                engine._set_altare_sigilli(owner_idx, after)
                owner_name = engine.state.players[owner_idx].name
                engine.state.log(
                    f"Altare dei Sette Sigilli: {owner_name} aggiunge {amount} Segnalini Sigillo ({before}->{after})."
                )
                return True
            if action == "remove_seal_counter":
                amount = max(0, int(effect.amount))
                if amount <= 0:
                    return True
                before = engine._get_altare_sigilli(owner_idx)
                after = max(0, before - amount)
                engine._set_altare_sigilli(owner_idx, after)
                owner_name = engine.state.players[owner_idx].name
                engine.state.log(
                    f"Altare dei Sette Sigilli: {owner_name} rimuove {amount} Segnalini Sigillo ({before}->{after})."
                )
                return True
            if action == "decrease_faith":
                amount = int(effect.amount)
                if effect.amount_multiplier_card_name:
                    amount *= self._count_named_cards_on_field(engine, effect.amount_multiplier_card_name)
                if amount <= 0:
                    return True
                for t_uid in targets:
                    inst = engine.state.instances[t_uid]
                    dmg = amount
                    if _norm(inst.definition.card_type) in {"santo", "token"}:
                        dmg = engine._apply_damage_mitigation(inst.owner, dmg, target_uid=t_uid)
                    if dmg <= 0:
                        continue
                    inst.current_faith = max(0, (inst.current_faith or 0) - dmg)
                    if (inst.current_faith or 0) <= 0 and _norm(inst.definition.card_type) in {"santo", "token"}:
                        engine.destroy_saint_by_uid(inst.owner, t_uid, cause="effect")
                return True
            if action == "calice_upkeep":
                player = engine.state.players[owner_idx]
                if player.sin >= 5:
                    player.sin -= 5
                    engine.state.log(f"{player.name} paga 5 Peccato per mantenere Calice Insanguinato.")
                else:
                    engine.send_to_graveyard(owner_idx, source_uid)
                    engine.state.log(f"{player.name} non puo pagare Calice Insanguinato: la carta viene distrutta.")
                return True
            if action == "calice_endturn":
                destroyed = 0
                for s_uid in list(targets):
                    if s_uid not in engine.state.instances:
                        continue
                    if self.is_immune_to_action(
                        engine.state.instances[s_uid].definition.name,
                        "calice_endturn_destroy",
                    ):
                        continue
                    engine.destroy_saint_by_uid(owner_idx, s_uid, cause="effect")
                    destroyed += 1
                if destroyed > 0:
                    engine.gain_sin(1 - owner_idx, destroyed * 5)
                return True
            if action == "campana_add_counter":
                inst = engine.state.instances[source_uid]
                counter = 0
                for tag in list(inst.blessed):
                    if tag.startswith("campana_counter:"):
                        try:
                            counter = int(tag.split(":", 1)[1])
                        except ValueError:
                            counter = 0
                        inst.blessed.remove(tag)
                counter += 1
                inst.blessed.append(f"campana_counter:{counter}")
                return True
            if action == "campana_remove_counter":
                inst = engine.state.instances.get(source_uid)
                if inst is None:
                    return True
                amount = max(0, int(effect.amount or 0))
                if amount <= 0:
                    return True
                counter = 0
                for tag in list(inst.blessed):
                    if not isinstance(tag, str) or not tag.startswith("campana_counter:"):
                        continue
                    try:
                        counter = int(tag.split(":", 1)[1])
                    except ValueError:
                        counter = 0
                    inst.blessed.remove(tag)
                    break
                counter = max(0, counter - amount)
                inst.blessed.append(f"campana_counter:{counter}")
                return True
            if action == "campana_spend_counters_grant_faith":
                inst = engine.state.instances.get(source_uid)
                if inst is None:
                    return True
                counter = 0
                counter_tag = ""
                for tag in list(inst.blessed):
                    if not isinstance(tag, str) or not tag.startswith("campana_counter:"):
                        continue
                    counter_tag = tag
                    try:
                        counter = max(0, int(tag.split(":", 1)[1]))
                    except ValueError:
                        counter = 0
                    break
                if counter <= 0:
                    return True

                flags = engine.state.flags
                expected_choice_source = f"{source_uid}:campana_spend_counters_grant_faith"
                choice_source = str(flags.get("_runtime_choice_source", "")).strip()
                choice_ready = bool(flags.get("_runtime_choice_ready"))
                if choice_ready and choice_source == expected_choice_source:
                    try:
                        amount = int(str(flags.get("_runtime_choice_selected", "0")).strip())
                    except ValueError:
                        amount = 0
                    amount = max(1, min(amount, counter))
                    for key in (
                        "_runtime_choice_source",
                        "_runtime_choice_ready",
                        "_runtime_choice_selected",
                        "_runtime_choice_values",
                        "_runtime_choice_labels",
                        "_runtime_choice_owner",
                        "_runtime_choice_title",
                        "_runtime_choice_prompt",
                        "_runtime_choice_min_targets",
                        "_runtime_choice_max_targets",
                    ):
                        flags.pop(key, None)
                    if counter_tag:
                        inst.blessed.remove(counter_tag)
                    inst.blessed.append(f"campana_counter:{counter - amount}")
                    for saint_uid in engine.all_saints_on_field(owner_idx):
                        saint = engine.state.instances.get(saint_uid)
                        if saint is not None:
                            saint.current_faith = int(saint.current_faith or 0) + amount
                    return True

                values = [str(amount) for amount in range(1, counter + 1)]
                labels = {
                    value: (f"Rimuovi {value} Segnalino" if value == "1" else f"Rimuovi {value} Segnalini")
                    for value in values
                }
                flags["_runtime_choice_source"] = expected_choice_source
                flags["_runtime_choice_values"] = ";;".join(values)
                flags["_runtime_choice_labels"] = json.dumps(labels, ensure_ascii=False)
                flags["_runtime_choice_owner"] = str(owner_idx)
                flags["_runtime_choice_title"] = str(effect.choice_title or "Campana")
                flags["_runtime_choice_prompt"] = str(
                    effect.choice_prompt or "Quanti Segnalini vuoi rimuovere?"
                )
                flags["_runtime_choice_min_targets"] = "1"
                flags["_runtime_choice_max_targets"] = "1"
                flags["_runtime_choice_ready"] = False
                flags["_runtime_resume_same_action"] = True
                flags["_runtime_reveal_card"] = source_uid
                flags["_runtime_waiting_for_reveal"] = True
                return True
            if action == "cataclisma_ciclico":
                flags = engine.state.flags
                expected_choice_source = f"{source_uid}:cataclisma_ciclico"
                own_saints = engine.all_saints_on_field(owner_idx)
                opp_idx = 1 - owner_idx
                opp_saints = engine.all_saints_on_field(opp_idx)
                candidates = list(dict.fromkeys(own_saints + opp_saints))
                if not candidates:
                    # The printed effect destroys Cataclisma itself when there
                    # are no Saints on the field.
                    engine.destroy_any_card(owner_idx, source_uid)
                    return True

                choice_source = str(flags.get("_runtime_choice_source", "")).strip()
                choice_ready = bool(flags.get("_runtime_choice_ready"))
                if choice_ready and choice_source == expected_choice_source:
                    selected_uid = str(flags.get("_runtime_choice_selected", "")).strip().split(",", 1)[0]
                    target_uid = selected_uid if selected_uid in candidates else ""
                    for key in (
                        "_runtime_choice_source",
                        "_runtime_choice_ready",
                        "_runtime_choice_selected",
                        "_runtime_choice_candidates",
                        "_runtime_choice_owner",
                        "_runtime_choice_title",
                        "_runtime_choice_prompt",
                        "_runtime_choice_min_targets",
                        "_runtime_choice_max_targets",
                    ):
                        flags.pop(key, None)
                    if not target_uid:
                        return True
                else:
                    flags["_runtime_choice_source"] = expected_choice_source
                    flags["_runtime_choice_candidates"] = ";;".join(candidates)
                    flags["_runtime_choice_owner"] = str(owner_idx)
                    flags["_runtime_choice_title"] = "Cataclisma Ciclico"
                    flags["_runtime_choice_prompt"] = "Scegli il Santo che Cataclisma Ciclico deve distruggere."
                    flags["_runtime_choice_min_targets"] = "1"
                    flags["_runtime_choice_max_targets"] = "1"
                    flags["_runtime_choice_ready"] = False
                    flags["_runtime_reveal_card"] = source_uid
                    flags["_runtime_waiting_for_reveal"] = True
                    flags["_runtime_resume_source"] = source_uid
                    flags["_runtime_resume_owner"] = str(owner_idx)
                    flags["_runtime_pending_mode"] = "trigger_action"
                    flags["_runtime_trigger_action"] = "cataclisma_ciclico"
                    flags["_runtime_trigger_event_name"] = str(flags.get("_runtime_event_name", "on_my_turn_start"))
                    return True

                target_owner = engine.state.instances[target_uid].owner
                target_name = engine.state.instances[target_uid].definition.name
                engine.destroy_saint_by_uid(target_owner, target_uid, cause="effect")
                if target_owner == owner_idx:
                    engine.gain_sin(opp_idx, 2)
                    engine.state.log(
                        f"Cataclisma Ciclico distrugge {target_name}: +2 Peccato a {engine.state.players[opp_idx].name}."
                    )
                else:
                    engine.reduce_sin(owner_idx, 1)
                    engine.state.log(
                        f"Cataclisma Ciclico distrugge {target_name}: {engine.state.players[owner_idx].name} perde 1 Peccato."
                    )
                return True
            if action == "kah_ok_tick":
                inst = engine.state.instances[source_uid]
                inst.current_faith = (inst.current_faith or 0) + 2
                if (inst.current_faith or 0) >= 10:
                    gained = max(0, inst.current_faith or 0)
                    engine.destroy_saint_by_uid(owner_idx, source_uid, cause="effect")
                    engine.gain_sin(owner_idx, gained)
                    engine.state.log(
                        f"Kah-ok raggiunge 10 Fede e si distrugge: {engine.state.players[owner_idx].name} +{gained} Peccato."
                    )
                return True
            if action == "trombe_del_giudizio_tick":
                b_uid = engine.state.players[owner_idx].building
                if b_uid is None:
                    return True
                if not self.get_is_altare_sigilli(engine.state.instances[b_uid].definition.name):
                    return True
                seals = engine._get_altare_sigilli(owner_idx)
                if seals >= 7:
                    amount = 10
                elif seals >= 5:
                    amount = 6
                elif seals >= 3:
                    amount = 3
                else:
                    amount = 0
                if amount > 0:
                    engine.gain_sin(1 - owner_idx, amount)
                return True
            if action == "av_drna_on_opponent_draw":
                inst = engine.state.instances[source_uid]
                inst.current_faith = max(0, (inst.current_faith or 0) - 1)
                engine.reduce_sin(owner_idx, 2)
                if (inst.current_faith or 0) <= 0:
                    engine.send_to_graveyard(owner_idx, source_uid)
                return True
            if action == "phdrna_activate_destroy_target_then_self":
                selected = str(engine.state.flags.get("_runtime_selected_target", "")).strip()
                target_uid = selected if selected in engine.state.instances else None
                if not target_uid:
                    return True

                selected_option = _norm(str(engine.state.flags.get("_runtime_selected_option", "")))
                player = engine.state.players[owner_idx]
                cost_inspiration = 10

                if selected_option == "building":
                    if player.building is None:
                        return True
                    engine.send_to_graveyard(owner_idx, player.building)
                elif selected_option == "artifacts":
                    artifacts = [uid for uid in player.artifacts if uid]
                    if len(artifacts) < 4:
                        return True
                    for art_uid in artifacts[:4]:
                        engine.send_to_graveyard(owner_idx, art_uid)
                else:
                    return True

                total_inspiration = int(player.inspiration) + int(getattr(player, "temporary_inspiration", 0))
                if total_inspiration < cost_inspiration:
                    return True

                temp = max(0, int(getattr(player, "temporary_inspiration", 0)))
                use_temp = min(temp, cost_inspiration)
                player.temporary_inspiration = temp - use_temp
                player.inspiration = max(0, int(player.inspiration) - (cost_inspiration - use_temp))

                target_inst = engine.state.instances.get(target_uid)
                if target_inst is not None:
                    engine.destroy_any_card(target_inst.owner, target_uid)

                engine.state.flags["_allow_indestructible_uid"] = source_uid
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is not None:
                    engine.destroy_any_card(source_inst.owner, source_uid)
                engine.state.flags.pop("_allow_indestructible_uid", None)
                return True
            if action == "pay_sin_or_destroy_self":
                cost = max(0, int(effect.amount))
                player = engine.state.players[owner_idx]
                source_inst = engine.state.instances.get(source_uid)
                source_name = source_inst.definition.name if source_inst is not None else source_uid

                if player.sin + cost < 100:
                    engine.gain_sin(owner_idx, cost)
                    engine.state.log(f"{source_name}: {player.name} accumula {cost} Peccato.")
                else:
                    engine.state.log(
                        f"{source_name}: {player.name} non può accumulare {cost} Peccato senza perdere e la carta viene distrutta."
                    )
                    engine.send_to_graveyard(owner_idx, source_uid)

                return True

            if action == "mill_cards":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
                player = engine.state.players[target]
                for _ in range(max(0, int(effect.amount))):
                    if not player.deck:
                        break
                    uid = player.deck.pop()
                    player.graveyard.append(uid)
                    self._shuffle_graveyard_if_oltretomba_active(engine, target)
                return True
            if action == "mill_top_and_store_card_type":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "opponent")
                player = engine.state.players[target]
                store_name = str(effect.store_as or "milled_type").strip()
                if not player.deck:
                    engine.state.flags[f"_runtime_store_{store_name}"] = ""
                    return True
                uid = player.deck.pop()
                player.graveyard.append(uid)
                self._shuffle_graveyard_if_oltretomba_active(engine, target)
                inst = engine.state.instances.get(uid)
                engine.state.flags[f"_runtime_store_{store_name}"] = _norm(inst.definition.card_type) if inst is not None else ""
                return True
            if action == "draw_if_stored_values_not_equal":
                left_name = str(effect.flag or "").strip()
                right_name = str(effect.stored or "").strip()
                if not left_name or not right_name:
                    return True
                left = _norm(str(engine.state.flags.get(f"_runtime_store_{left_name}", "")))
                right = _norm(str(engine.state.flags.get(f"_runtime_store_{right_name}", "")))
                if left and right and left != right:
                    target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                    amount = max(0, int(effect.amount or 1))
                    if amount > 0:
                        engine.draw_cards(target, amount)
                return True
            if action == "draw_cards_and_store_last_drawn":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                amount = max(0, int(effect.amount or 1))
                store_name = str(effect.store_as or "last_drawn").strip()
                drawn_map = engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})
                before = list(drawn_map.get(str(target), []) or [])
                if amount <= 0:
                    engine.state.flags[f"_runtime_store_{store_name}"] = ""
                    return True
                engine.draw_cards(target, amount)
                after = list(drawn_map.get(str(target), []) or [])
                new_uids = [uid for uid in after if uid not in before]
                engine.state.flags[f"_runtime_store_{store_name}"] = str(new_uids[-1]) if new_uids else ""
                return True
            if action == "destroy_source_if_effective_strength_lte":
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                threshold = int(effect.threshold) if effect.threshold is not None else 0
                current = max(0, int(engine.get_effective_strength(source_uid)))
                if current <= threshold:
                    engine.destroy_any_card(source_inst.owner, source_uid)
                return True
            if action == "draw_cards":
                target = self._resolve_player_scope(owner_idx, effect.target_player)
                amount = 1 if effect.amount is None else int(effect.amount)
                engine.draw_cards(target, max(0, amount))
                return True
            if action == "draw_cards_and_set_play_cost_for_drawn_until_turn_end":
                target = self._resolve_player_scope(owner_idx, effect.target_player or "me")
                draw_amount = max(0, int(effect.amount or 0))
                fixed_cost = max(0, int(effect.override_cost or 0))
                if draw_amount <= 0:
                    return True
                drawn_map = engine.state.flags.setdefault("cards_drawn_this_turn", {"0": [], "1": []})
                before = list(drawn_map.get(str(target), []) or [])
                engine.draw_cards(target, draw_amount)
                after = list(drawn_map.get(str(target), []) or [])
                new_uids = [uid for uid in after if uid not in before]
                if not new_uids:
                    return True
                cost_map_all = engine.state.flags.setdefault("drawn_play_cost_override_until_turn_end", {"0": {}, "1": {}})
                target_map = dict(cost_map_all.get(str(target), {}) or {})
                for uid in new_uids:
                    target_map[str(uid)] = fixed_cost
                cost_map_all[str(target)] = target_map
                return True
            if action == "process_deck_edges_by_type":
                player = engine.state.players[owner_idx]
                deck_now = list(player.deck)
                if not deck_now:
                    return True

                top_count = max(0, int(effect.top_count if effect.top_count is not None else 0))
                bottom_count = max(0, int(effect.bottom_count if effect.bottom_count is not None else 0))
                unique_only = bool(effect.unique_edges_only)

                picked: list[str] = []
                for uid in reversed(deck_now[-top_count:]) if top_count > 0 else []:
                    if (not unique_only) or uid not in picked:
                        picked.append(uid)
                for uid in (deck_now[:bottom_count] if bottom_count > 0 else []):
                    if (not unique_only) or uid not in picked:
                        picked.append(uid)

                saint_token_to = _norm(effect.saint_token_to_zone or "excommunicated")
                blessing_curse_to = _norm(effect.blessing_curse_to_zone or "graveyard")
                artifact_to = _norm(effect.artifact_to_zone or "artifacts")
                building_to = _norm(effect.building_to_zone or "building")
                fallback_to = _norm(effect.fallback_to_zone or "graveyard")

                for uid in picked:
                    inst = engine.state.instances.get(uid)
                    if inst is None:
                        continue
                    if uid in player.deck:
                        player.deck.remove(uid)

                    ctype = _norm(inst.definition.card_type)
                    if ctype in {"santo", "token"}:
                        if saint_token_to == "excommunicated":
                            engine.excommunicate_card(owner_idx, uid)
                        else:
                            self._move_uid_to_zone(engine, uid, saint_token_to, owner_idx)
                        continue
                    if ctype in {"benedizione", "maledizione"}:
                        self._move_uid_to_zone(engine, uid, blessing_curse_to, owner_idx)
                        continue
                    if ctype == "artefatto":
                        if artifact_to in {"artifact", "artifacts", "field"}:
                            slot = engine._first_open(player.artifacts)
                            if slot is None and bool(effect.replace_occupied_artifact):
                                slot = len(player.artifacts) - 1
                                replaced_uid = player.artifacts[slot]
                                if replaced_uid:
                                    engine.send_to_graveyard(engine.state.instances[replaced_uid].owner, replaced_uid)
                            if slot is not None:
                                player.artifacts[slot] = uid
                            else:
                                self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
                        else:
                            self._move_uid_to_zone(engine, uid, artifact_to, owner_idx)
                        continue
                    if ctype == "edificio":
                        if building_to in {"building", "field"}:
                            if player.building and bool(effect.replace_occupied_building):
                                engine.send_to_graveyard(engine.state.instances[player.building].owner, player.building)
                                player.building = uid
                            elif player.building is None:
                                player.building = uid
                            else:
                                self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
                        else:
                            self._move_uid_to_zone(engine, uid, building_to, owner_idx)
                        continue

                    self._move_uid_to_zone(engine, uid, fallback_to, owner_idx)
                return True
            if action == "set_blocked_enemy_artifact_slot_from_selected_option":
                selected = str(engine.state.flags.get("_runtime_selected_option", "")).strip().lower()
                if len(selected) != 2 or not selected.startswith("r") or not selected[1].isdigit():
                    return True
                slot = int(selected[1]) - 1
                if slot < 0 or slot >= state.ARTIFACT_SLOTS:
                    return True
                source_inst = engine.state.instances.get(source_uid)
                if source_inst is None:
                    return True
                source_inst.blessed = [
                    tag for tag in list(source_inst.blessed)
                    if not (isinstance(tag, str) and tag.startswith("block_enemy_artifact_slot:"))
                ]
                source_inst.blessed.append(f"block_enemy_artifact_slot:{slot}")
                return True
            return False
