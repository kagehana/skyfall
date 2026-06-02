from __future__ import annotations
from typing import Callable
from wizwalker.memory.memory_objects.conditionals import school_to_str


class LuaCombatant:
    def __init__(self, member, call: Callable):

        self._m = member

        self._call = call

    def name(self) -> str:

        return self._call(self._m.name())

    def school(self) -> str:

        async def _():

            part = await self._m.get_participant()

            sid = await part.primary_magic_school_id()

            return school_to_str.get(sid, "Unknown")

        return self._call(_())

    def health(self) -> int:

        return self._call(self._m.health())

    def max_health(self) -> int:

        return self._call(self._m.max_health())

    def mana(self) -> int:

        return self._call(self._m.mana())

    def max_mana(self) -> int:

        return self._call(self._m.max_mana())

    def level(self) -> int:

        return self._call(self._m.level())

    def pips(self) -> int:

        return self._call(self._m.normal_pips())

    def power_pips(self) -> int:

        return self._call(self._m.power_pips())

    def shadow_pips(self) -> int:

        return self._call(self._m.shadow_pips())

    def is_boss(self) -> bool:

        return self._call(self._m.is_boss())

    def is_dead(self) -> bool:

        return self._call(self._m.is_dead())

    def is_stunned(self) -> bool:

        return self._call(self._m.is_stunned())

    def is_player(self) -> bool:

        return self._call(self._m.is_player())

    def is_monster(self) -> bool:

        return self._call(self._m.is_monster())

    def is_minion(self) -> bool:

        return self._call(self._m.is_minion())

    # ── participant helper ────────────────────────────────────────────────────

    async def _part(self):
        return await self._m.get_participant()

    # ── identity ──────────────────────────────────────────────────────────────

    def owner_id(self) -> int:
        async def _():
            return await (await self._part()).owner_id_full()

        return self._call(_())

    def template_id(self) -> int:
        async def _():
            return await (await self._part()).template_id_full()

        return self._call(_())

    def zone_id(self) -> int:
        async def _():
            return await (await self._part()).zone_id_full()

        return self._call(_())

    def team_id(self) -> int:
        async def _():
            return await (await self._part()).team_id()

        return self._call(_())

    def original_team(self) -> int:
        async def _():
            return await (await self._part()).original_team()

        return self._call(_())

    def side(self) -> str:
        async def _():
            return await (await self._part()).side()

        return self._call(_())

    # ── stats ─────────────────────────────────────────────────────────────────

    def stat_damage(self) -> float:
        async def _():
            return await (await self._part()).stat_damage()

        return self._call(_())

    def stat_resist(self) -> float:
        async def _():
            return await (await self._part()).stat_resist()

        return self._call(_())

    def stat_pierce(self) -> float:
        async def _():
            return await (await self._part()).stat_pierce()

        return self._call(_())

    def base_spell_damage(self) -> int:
        async def _():
            return await (await self._part()).base_spell_damage()

        return self._call(_())

    def accuracy_bonus(self) -> float:
        async def _():
            return await (await self._part()).accuracy_bonus()

        return self._call(_())

    def mob_level(self) -> int:
        async def _():
            return await (await self._part()).mob_level()

        return self._call(_())

    def max_hand_size(self) -> int:
        async def _():
            return await (await self._part()).max_hand_size()

        return self._call(_())

    def deck_fullness(self) -> float:
        async def _():
            return await (await self._part()).deck_fullness()

        return self._call(_())

    # ── archmastery ───────────────────────────────────────────────────────────

    def archmastery_points(self) -> float:
        async def _():
            return await (await self._part()).archmastery_points()

        return self._call(_())

    def max_archmastery_points(self) -> float:
        async def _():
            return await (await self._part()).max_archmastery_points()

        return self._call(_())

    def archmastery_school(self) -> int:

        async def _():
            return await (await self._part()).archmastery_school()

        return self._call(_())

    def archmastery_flags(self) -> int:
        async def _():
            return await (await self._part()).archmastery_flags()

        return self._call(_())

    # ── shadow ────────────────────────────────────────────────────────────────

    def shadow_creature_level(self) -> int:
        async def _():
            return await (await self._part()).shadow_creature_level()

        return self._call(_())

    def past_shadow_creature_level(self) -> int:
        async def _():
            return await (await self._part()).past_shadow_creature_level()

        return self._call(_())

    def shadow_creature_level_count(self) -> int:
        async def _():
            return await (await self._part()).shadow_creature_level_count()

        return self._call(_())

    def rounds_since_shadow_pip(self) -> int:
        async def _():
            return await (await self._part()).rounds_since_shadow_pip()

        return self._call(_())

    def shadow_pip_rate_threshold(self) -> float:
        async def _():
            return await (await self._part()).shadow_pip_rate_threshold()

        return self._call(_())

    def shadow_spells_disabled(self) -> bool:
        async def _():
            return await (await self._part()).shadow_spells_disabled()

        return self._call(_())

    def shadow_pact_target(self) -> int:
        async def _():
            return await (await self._part()).shadow_pact_target()

        return self._call(_())

    # ── backlash ──────────────────────────────────────────────────────────────

    def backlash(self) -> int:
        async def _():
            return await (await self._part()).backlash()

        return self._call(_())

    def past_backlash(self) -> int:
        async def _():
            return await (await self._part()).past_backlash()

        return self._call(_())

    # ── pip state ─────────────────────────────────────────────────────────────

    def pips_suspended(self) -> bool:
        async def _():
            return await (await self._part()).pips_suspended()

        return self._call(_())

    # ── status effects ────────────────────────────────────────────────────────

    def mindcontrolled(self) -> bool:
        async def _():
            return bool(await (await self._part()).mindcontrolled())

        return self._call(_())

    def confused(self) -> bool:
        async def _():
            return bool(await (await self._part()).confused())

        return self._call(_())

    def confusion_trigger(self) -> int:
        async def _():
            return await (await self._part()).confusion_trigger()

        return self._call(_())

    def confused_target(self) -> bool:
        async def _():
            return await (await self._part()).confused_target()

        return self._call(_())

    def untargetable(self) -> bool:
        async def _():
            return await (await self._part()).untargetable()

        return self._call(_())

    def untargetable_rounds(self) -> int:
        async def _():
            return await (await self._part()).untargetable_rounds()

        return self._call(_())

    def restricted_target(self) -> bool:
        async def _():
            return await (await self._part()).restricted_target()

        return self._call(_())

    def hide_current_hp(self) -> bool:
        async def _():
            return await (await self._part()).hide_current_hp()

        return self._call(_())

    # ── round state ───────────────────────────────────────────────────────────

    def auto_pass(self) -> bool:
        async def _():
            return await (await self._part()).auto_pass()

        return self._call(_())

    def vanish(self) -> bool:
        async def _():
            return await (await self._part()).vanish()

        return self._call(_())

    def my_team_turn(self) -> bool:
        async def _():
            return await (await self._part()).my_team_turn()

        return self._call(_())

    def exit_combat(self) -> bool:
        async def _():
            return await (await self._part()).exit_combat()

        return self._call(_())

    def rounds_dead(self) -> int:
        async def _():
            return await (await self._part()).rounds_dead()

        return self._call(_())

    def clue(self) -> int:
        async def _():
            return await (await self._part()).clue()

        return self._call(_())

    def aura_turn_length(self) -> int:
        async def _():
            return await (await self._part()).aura_turn_length()

        return self._call(_())

    # ── polymorph ─────────────────────────────────────────────────────────────

    def polymorph_turn_length(self) -> int:
        async def _():
            return await (await self._part()).polymorph_turn_length()

        return self._call(_())

    def polymorph_spell_template_id(self) -> int:
        async def _():
            return await (await self._part()).polymorph_spell_template_id()

        return self._call(_())

    # ── position in circle ────────────────────────────────────────────────────

    def rotation(self) -> float:
        async def _():
            return await (await self._part()).rotation()

        return self._call(_())

    def radius(self) -> float:
        async def _():
            return await (await self._part()).radius()

        return self._call(_())

    def subcircle(self) -> int:
        async def _():
            return await (await self._part()).subcircle()

        return self._call(_())

    def minion_sub_circle(self) -> int:
        async def _():
            return await (await self._part()).minion_sub_circle()

        return self._call(_())

    # ── flags ─────────────────────────────────────────────────────────────────

    def pvp(self) -> bool:
        async def _():
            return await (await self._part()).pvp()

        return self._call(_())

    def raid(self) -> bool:
        async def _():
            return await (await self._part()).raid()

        return self._call(_())

    def is_accompany_npc(self) -> bool:
        async def _():
            return await (await self._part()).is_accompany_npc()

        return self._call(_())

    def combat_trigger_ids(self) -> int:
        async def _():
            return await (await self._part()).combat_trigger_ids()

        return self._call(_())

    def pet_combat_trigger(self) -> int:
        async def _():
            return await (await self._part()).pet_combat_trigger()

        return self._call(_())

    def pet_combat_trigger_target(self) -> int:
        async def _():
            return await (await self._part()).pet_combat_trigger_target()

        return self._call(_())

    def stunned_display(self) -> bool:
        async def _():
            return await (await self._part()).stunned_display()

        return self._call(_())

    def mindcontrolled_display(self) -> bool:
        async def _():
            return await (await self._part()).mindcontrolled_display()

        return self._call(_())

    def confusion_display(self) -> bool:
        async def _():
            return await (await self._part()).confusion_display()

        return self._call(_())

    def hide_pvp_enemy_chat(self) -> bool:
        async def _():
            return await (await self._part()).hide_pvp_enemy_chat()

        return self._call(_())

    def ignore_spells_pvp_only_flag(self) -> bool:
        async def _():
            return await (await self._part()).ignore_spells_pvp_only_flag()

        return self._call(_())

    def ignore_spells_pve_only_flag(self) -> bool:
        async def _():
            return await (await self._part()).ignore_spells_pve_only_flag()

        return self._call(_())

    def saved_primary_magic_school_id(self) -> int:
        async def _():
            return await (await self._part()).saved_primary_magic_school_id()

        return self._call(_())

    def player_time_updated(self) -> bool:
        async def _():
            return await (await self._part()).player_time_updated()

        return self._call(_())

    def player_time_eliminated(self) -> bool:
        async def _():
            return await (await self._part()).player_time_eliminated()

        return self._call(_())

    def player_time_warning(self) -> bool:
        async def _():
            return await (await self._part()).player_time_warning()

        return self._call(_())

    def planning_phase_pip_aquired_type(self) -> int:

        async def _():
            v = await (await self._part()).planning_phase_pip_aquired_type()
            return int(v) if v is not None else 0

        return self._call(_())
