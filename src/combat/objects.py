import re

from typing import Any, Coroutine, Dict, List, Tuple


from wizwalker.combat import CombatCard, CombatMember

from wizwalker.memory.memory_objects.game_stats import DynamicGameStats

from wizwalker.memory.memory_objects.spell_effect import (
    DynamicSpellEffect,
    SpellEffects,
)


from src.utils import index_with_str


school_ids = {
    0: 2343174,
    1: 72777,
    2: 83375795,
    3: 2448141,
    4: 2330892,
    5: 78318724,
    6: 1027491821,
    7: 2625203,
    8: 78483,
    9: 2504141,
    10: 663550619,
    11: 1429009101,
    12: 1488274711,
    13: 1760873841,
    14: 806477568,
    15: 931528087,
}

school_id_to_names = {
    "Fire": 2343174,
    "Ice": 72777,
    "Storm": 83375795,
    "Myth": 2448141,
    "Life": 2330892,
    "Death": 78318724,
    "Balance": 1027491821,
    "Star": 2625203,
    "Sun": 78483,
    "Moon": 2504141,
    "Gardening": 663550619,
    "Shadow": 1429009101,
    "Fishing": 1488274711,
    "Cantrips": 1760873841,
    "CastleMagic": 806477568,
    "WhirlyBurly": 931528087,
}

school_to_str = {index: i for i, index in school_id_to_names.items()}

school_list_ids = {index: i for i, index in school_ids.items()}

school_names = list(school_id_to_names.keys())

school_id_list = list(school_ids.values())


side_excluded_ids = [663550619, 806477568, 931528087, 1488274711, 1760873841]

shadow_excluded_ids = [1429009101]

astral_excluded_ids = [78483, 2625203, 2504141]


non_main_excluded_ids = side_excluded_ids + shadow_excluded_ids + astral_excluded_ids


opposite_school_ids = {
    72777: 2343174,
    2330892: 78318724,
    2343174: 72777,
    2448141: 83375795,
    78318724: 2330892,
    83375795: 2448141,
}


class InvalidSchoolID(Exception):
    pass


def get_school_stat(stats: List, school_id: int):

    if school_id in school_id_list:
        stat_index = school_list_ids[school_id]

        return stats[stat_index]

    else:
        raise InvalidSchoolID


def get_relevant_school_stats(stats: List, excluded_ids: List[int]):

    relevant_stats = []

    for i, stat in enumerate(stats):
        if school_ids[i] not in excluded_ids:
            relevant_stats.append(stat)

    return relevant_stats


async def get_game_stats(
    member_id: int, members: List[CombatMember]
) -> DynamicGameStats:

    member = await id_to_member(member_id, members)

    participant = await member.get_participant()

    game_stats = await participant.game_stats()

    return game_stats


async def get_hanging_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(member_id, members)

    participant = await member.get_participant()

    hanging_effects = await participant.hanging_effects()

    return hanging_effects


async def get_aura_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(member_id, members)

    participant = await member.get_participant()

    aura_effects = await participant.aura_effects()

    return aura_effects


async def get_shadow_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(member_id, members)

    participant = await member.get_participant()

    shadow_effects = await participant.shadow_spell_effects()

    return shadow_effects


async def get_total_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    effects: List[DynamicSpellEffect] = []

    effects += await get_hanging_effects(member_id, members)

    effects += await get_aura_effects(member_id, members)

    effects += await get_shadow_effects(member_id, members)

    return effects


async def ids_from_cards(cards: List[CombatCard]) -> List[int]:

    spell_ids: List[int] = []

    for card in cards:
        spell_id = await card.spell_id()

        spell_ids.append(spell_id)

    return spell_ids


async def id_to_member(member_id: int, members: List[CombatMember]) -> CombatMember:

    for member in members:
        if await member.owner_id() == member_id:
            return member

    raise ValueError


async def id_to_card(spell_id: int, cards: List[CombatCard]) -> CombatCard:

    for card in cards:
        if await card.spell_id() == spell_id:
            return card

    raise ValueError


async def id_to_hanging_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(members, member_id)

    effects = await get_hanging_effects(member)

    return effects


async def id_to_aura_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(members, member_id)

    effects = await get_aura_effects(member)

    return effects


async def id_to_shadow_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(members, member_id)

    effects = await get_shadow_effects(member)

    return effects


async def id_to_total_effects(
    member_id: int, members: List[CombatMember]
) -> List[DynamicSpellEffect]:

    member = await id_to_member(members, member_id)

    effects = await get_total_effects(member)

    return effects


async def spell_id_to_effects(
    spell_id: int, cards: List[CombatCard]
) -> List[DynamicSpellEffect]:

    card = await id_to_card(cards, spell_id)

    if card:
        g_spell = await card.get_graphical_spell()

        spell_effects = await g_spell.spell_effects()

        return spell_effects

    raise ValueError


async def spell_id_school(spell_id: int, cards: List[CombatCard]) -> int:

    card = await id_to_card(cards, spell_id)

    if card:
        g_spell = await card.get_graphical_spell()

        school_id = await g_spell.magic_school_id()

        return school_id


async def spell_id_school_str(spell_id: int, cards: List[CombatCard]) -> str:

    school_id = await spell_id_school(cards, spell_id)

    return school_to_str(school_id)


symbol_to_effect_type = {
    "Afterlife": SpellEffects.afterlife,
    "DamageOverTime": SpellEffects.damage_over_time,
    "HealOverTime": SpellEffects.heal_over_time,
    "DeferredDamage": SpellEffects.deferred_damage,
    "Jinx": SpellEffects.modify_incoming_damage,
    "Trap": SpellEffects.modify_incoming_damage,
    "Ward": SpellEffects.modify_incoming_damage,
    "Resist": SpellEffects.modify_incoming_damage,
    "Curse": SpellEffects.modify_outgoing_damage,
    "Blade": SpellEffects.modify_outgoing_damage,
}


def generate_mastery_funcs(stats: DynamicGameStats) -> List[Coroutine[Any, Any, int]]:

    mastery_funcs = [
        stats.fire_mastery,
        stats.ice_mastery,
        stats.storm_mastery,
        stats.myth_mastery,
        stats.life_mastery,
        stats.death_mastery,
        stats.balance_mastery,
    ]

    return mastery_funcs


def add_universal_stat(input_stats: List[float], uni_stat: float) -> List[float]:

    real_stats = []

    for stat in input_stats:
        real_stat = stat + uni_stat

        real_stats.append(real_stat)

    return real_stats


def to_percent_str(input_stats: List[float]) -> List[str]:

    readable_stats = []

    for stat in input_stats:
        readable_stats.append(str(f"{stat * 100}%"))

    return readable_stats


def to_percent(input_stats: List[float]) -> List[float]:

    readable_stats = []

    for stat in input_stats:
        readable_stats.append(stat * 100)

    return readable_stats


def to_relevant_stats(
    input_stats: List[float], blacklist: List[str] = [10, 12, 13, 14, 15]
) -> Dict[int, float]:

    output_stats: Dict[int, float] = {}

    for i, stat in enumerate(input_stats):
        if i not in blacklist:
            index_id = school_ids[i]

            output_stats[index_id] = stat


def to_relevant_str_stats(
    input_stats: List[float], blacklist: List[str] = [10, 12, 13, 14, 15]
) -> Dict[str, float]:

    output_stats: Dict[int, float] = {}

    for i, stat in enumerate(input_stats):
        if i not in blacklist:
            index_name = school_names[i]

            output_stats[index_name] = stat


def to_seperated_str_stats(
    input_stats: List[float],
) -> Tuple[Dict[str, float], Dict[str, float]]:

    positives: Dict[str, float] = {}

    negatives: Dict[str, float] = {}

    for i, stat in enumerate(input_stats):
        index_name = school_names[i]

        if stat > 0.0:
            positives[index_name] = stat

        elif stat < 0.0:
            negatives[index_name] = stat

    return (positives, negatives)


async def get_str_masteries(member: CombatMember) -> List[str]:

    stats = await member.get_stats()

    mastery_funcs = generate_mastery_funcs(stats)

    mastery_str = ["Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance"]

    masteries = []

    for mastery, str in zip(mastery_funcs, mastery_str):
        if await mastery():
            masteries.append(str)

    return masteries


async def get_masteries(member: CombatMember) -> List[int]:

    stats = await member.get_stats()

    mastery_funcs = generate_mastery_funcs(stats)

    masteries = [mastery for mastery in mastery_funcs]

    return masteries


async def enemy_type_str(member: CombatMember) -> str:

    if await member.is_boss():
        return "Boss"

    elif await member.is_minion():
        return "Minion"

    elif await member.is_monster():
        return "Mob"

    else:
        return "Player"


def content_from_str(input_str: str, seperator: str = "") -> str:

    return seperator.join(re.findall(">.*?<", input_str))


def image_name_from_str(input_str: str) -> str:

    start_index = index_with_str(input_str, ";") + 1

    end_index = index_with_str(input_str[start_index:], ";")

    image_path = input_str[start_index:end_index]

    slash_index = index_with_str(image_path, "/") + 1

    filetype_index = index_with_str(image_path, ".")

    return image_path[slash_index:filetype_index]


def total_effects_from_str(
    input_str: str,
) -> List[Tuple[SpellEffects, float, int, int, str, SpellEffects, int, str]]:

    if "Clear" in input_str:
        start_index = index_with_str(input_str, "(")

        end_index = index_with_str(input_str, ")")

        if end_index == len(input_str) - 1:
            end_index = None

        int(input_str[start_index:end_index])
