from __future__ import annotations


from wizwalker.memory.memory_objects.enums import (
    EffectTarget,
    HangingDisposition,
    SpellEffects,
)


_DAMAGE = {
    SpellEffects.damage,
    SpellEffects.damage_no_crit,
    SpellEffects.steal_health,
    SpellEffects.damage_per_total_pip_power,
    SpellEffects.deferred_damage,
}

_HEAL = {SpellEffects.heal, SpellEffects.heal_percent, SpellEffects.set_heal_percent}

_CHARM = {
    SpellEffects.modify_incoming_damage,
    SpellEffects.modify_outgoing_damage,
    SpellEffects.modify_incoming_armor_piercing,
    SpellEffects.modify_incoming_heal,
    SpellEffects.modify_outgoing_heal,
    SpellEffects.crit_boost,
    SpellEffects.crit_block,
}

_WARD = {
    SpellEffects.modify_incoming_damage,
    SpellEffects.modify_incoming_armor_piercing,
    SpellEffects.absorb_damage,
    SpellEffects.absorb_heal,
}

_OVER_TIME = {SpellEffects.damage_over_time, SpellEffects.heal_over_time}

_AURA = {
    SpellEffects.modify_accuracy,
    SpellEffects.modify_power_pip_chance,
    SpellEffects.crit_boost,
    SpellEffects.crit_block,
    SpellEffects.pip_conversion,
}

_DISPEL = {SpellEffects.dispel}

_PRISM = {SpellEffects.modify_incoming_damage_type}

_PIERCE = {
    SpellEffects.modify_incoming_armor_piercing,
    SpellEffects.modify_outgoing_armor_piercing,
}

_SHADOW = {SpellEffects.shadow_self}

_POLYMORPH = {SpellEffects.polymorph}


_ENEMY_TGT = {
    EffectTarget.enemy_single,
    EffectTarget.multi_target_enemy,
    EffectTarget.at_least_one_enemy,
    EffectTarget.enemy_team,
    EffectTarget.enemy_team_all_at_once,
    EffectTarget.preselected_enemy_single,
}

_ALLY_TGT = {
    EffectTarget.friendly_single,
    EffectTarget.multi_target_friendly,
    EffectTarget.self,
    EffectTarget.friendly_team,
    EffectTarget.friendly_team_all_at_once,
    EffectTarget.friendly_single_not_me,
}

_AOE_TGT = {
    EffectTarget.multi_target_enemy,
    EffectTarget.enemy_team,
    EffectTarget.enemy_team_all_at_once,
}


HANGING_CATEGORIES: dict[str, tuple] = {
    "charms": (_CHARM, "charm", SpellEffects.swap_charm),
    "wards": (_WARD, "ward", SpellEffects.swap_ward),
    "over_time": (_OVER_TIME, "over_time", SpellEffects.swap_over_time),
    "auras": (_AURA, "aura", None),
}


_REQ_TO_CAT = {
    "blade": "charms",
    "charm": "charms",
    "ward": "wards",
    "trap": "wards",
    "dot": "over_time",
    "hot": "over_time",
    "aura": "auras",
}


async def flatten_effects(effect, depth: int = 0) -> list:

    if depth > 8:
        return []

    tn = await effect.read_type_name()

    if tn == "CompoundSpellEffect":
        out = []

        for e in await effect.effects_list():
            out.extend(await flatten_effects(e, depth + 1))

        return out

    if tn == "ConditionalSpellEffect":
        out = []

        for elem in await effect.elements():
            out.extend(await flatten_effects(await elem.effect(), depth + 1))

        return out

    if tn == "HangingConversionSpellEffect":
        out = []

        for e in await effect.output_effect():
            out.extend(await flatten_effects(e, depth + 1))

        return [effect] + out

    if tn == "InvalidSpellEffect":
        try:
            inner = await effect.maybe_effect_list()

            if inner:
                out = []

                for e in inner:
                    out.extend(await flatten_effects(e, depth + 1))

                return out

        except Exception:
            pass

    return [effect]


async def is_req_satisfied(effect, req: str, allow_aoe: bool = True) -> bool:

    try:
        et = await effect.effect_type()

        tgt = await effect.effect_target()

        prm = await effect.effect_param()

        rds = await effect.num_rounds()

    except Exception:
        return False

    req = req.lower().strip()

    if req == "damage":
        if et == SpellEffects.steal_health:
            return tgt in _ENEMY_TGT
        # pip-scaling spells store per-pip value in param which can be 0; don't gate on prm
        if et == SpellEffects.damage_per_total_pip_power:
            return tgt in _ENEMY_TGT
        return et in _DAMAGE and tgt in _ENEMY_TGT and prm

    if req == "aoe":
        return et in _DAMAGE and tgt in _AOE_TGT

    if req == "damage&aoe":
        return et in _DAMAGE and tgt in _AOE_TGT and prm

    if req in ("heal", "healing"):
        return et in _HEAL and tgt in _ALLY_TGT and prm > 0

    if req == "blade":
        return et in _CHARM and tgt in _ALLY_TGT and prm > 0 and rds == 0

    if req == "charm":
        return et in _CHARM and tgt in _ENEMY_TGT and prm < 0 and rds == 0

    if req == "ward":
        return et in _WARD and tgt in _ALLY_TGT and prm < 0 and rds == 0

    if req == "trap":
        return et in _WARD and tgt in _ENEMY_TGT and prm > 0 and rds == 0

    if req == "aura":
        return et in _AURA and rds > 0

    if req == "global":
        return tgt == EffectTarget.target_global

    if req == "prism":
        return et in _PRISM

    if req == "dispel":
        return et in _DISPEL

    if req == "pierce":
        return et in _PIERCE

    if req == "shadow":
        return et in _SHADOW

    if req == "polymorph":
        return et in _POLYMORPH

    if req in ("dot", "damage_over_time"):
        return et in _OVER_TIME and tgt in _ENEMY_TGT

    if req in ("hot", "heal_over_time"):
        return et in _OVER_TIME and tgt in _ALLY_TGT

    if req in ("mod_damage", "enchant", "damage_enchant"):
        return et == SpellEffects.modify_incoming_damage and rds == 0

    return False


async def card_matches_reqs(card, reqs: list[str]) -> bool:

    if not reqs:
        return True

    effects = await flatten_effects_for_card(card)

    needed = list(reqs)

    matched = set()

    has_aoe_req = "aoe" in reqs or "damage&aoe" in reqs

    for eff in effects:
        for req in needed:
            if req in matched:
                continue

            if await is_req_satisfied(eff, req):
                matched.add(req)

                try:
                    tgt = await eff.effect_target()

                    if tgt == EffectTarget.multi_target_enemy and "damage" in needed:
                        matched.add("damage")

                    if tgt == EffectTarget.multi_target_friendly and "heal" in needed:
                        matched.add("heal")

                except Exception:
                    pass

    if matched != set(needed):
        return False

    if has_aoe_req:
        for eff in effects:
            try:
                et = await eff.effect_type()

                tgt = await eff.effect_target()

                if et in _DAMAGE and tgt == EffectTarget.enemy:
                    return False

            except Exception:
                pass

    return True


async def flatten_effects_for_card(card) -> list:

    out = []

    for eff in await card.get_spell_effects():
        out.extend(await flatten_effects(eff))

    return out


async def count_hanging(
    participant, category: str, disposition: str | None = None
) -> int:

    cat_info = HANGING_CATEGORIES.get(category)

    if not cat_info:
        return 0

    type_set, _, _ = cat_info

    is_aura = category == "auras"

    try:
        if is_aura:
            effects = await participant.aura_effects()

        else:
            effects = await participant.hanging_effects()

    except Exception:
        return 0

    count = 0

    for eff in effects:
        try:
            et = await eff.effect_type()

            disp = await eff.disposition()

        except Exception:
            continue

        if et not in type_set:
            continue

        if disposition == "beneficial" and disp != HangingDisposition.beneficial:
            continue

        if disposition == "harmful" and disp != HangingDisposition.harmful:
            continue

        count += 1

    return min(count, 1) if is_aura else count


async def effect_satisfies_verb(
    effect,
    verb: str,
    category: str,
    caster_participant,
    target_participant,
    min_count: int = 1,
) -> bool:

    try:
        tn = await effect.read_type_name()

    except Exception:
        return False

    if tn == "HangingConversionSpellEffect":
        return await _conversion_verb(
            effect, verb, category, caster_participant, target_participant, min_count
        )

    if tn == "ConditionalSpellEffect":
        return await _conditional_verb(
            effect, verb, category, caster_participant, target_participant, min_count
        )

    if verb == "swap":
        cat_info = HANGING_CATEGORIES.get(category)

        if cat_info:
            _, _, swap_effect = cat_info

            if swap_effect:
                try:
                    et = await effect.effect_type()

                    return et == swap_effect

                except Exception:
                    pass

    return False


async def _conversion_verb(
    conv, verb: str, category: str, caster_p, target_p, min_count: int
) -> bool:

    try:
        he_type = await conv.hanging_effect_type()

        min_n = max(min_count, await conv.min_effect_count())

    except Exception:
        return False

    sides = _verb_sides(verb)

    cat_info = HANGING_CATEGORIES.get(category)

    if not cat_info:
        return False

    type_set = cat_info[0]

    for side, disp in sides:
        participant = caster_p if side == "caster" else target_p

        if participant is None:
            continue

        cnt = await count_hanging(participant, category, disp)

        if cnt >= min_n:
            if await _he_type_matches(conv, he_type, type_set):
                return True

    return False


async def _he_type_matches(conv, he_type, type_set) -> bool:

    from wizwalker.memory.memory_objects.enums import HangingEffectType

    try:
        if he_type == HangingEffectType.any:
            return True

        specific = await conv.specific_effect_types()

        if specific:
            return any(s in type_set for s in specific)

        return True

    except Exception:
        return True


async def _conditional_verb(
    cond_eff, verb: str, category: str, caster_p, target_p, min_count: int
) -> bool:

    try:
        elements = await cond_eff.elements()

    except Exception:
        return False

    sides = _verb_sides(verb)

    for elem in elements:
        try:
            reqs = await (await elem.reqs()).requirements()

        except Exception:
            continue

        for req in reqs:
            try:
                if await req.apply_not():
                    continue

                rtn = type(req).__name__.lower()

                if not any(
                    cat in rtn for cat in (category, _REQ_TO_CAT.get(category, ""))
                ):
                    continue

                disp_attr = getattr(req, "disposition", None)

                if disp_attr:
                    disp = (await disp_attr()).name.lower()

                else:
                    disp = None

                tgt_attr = getattr(req, "target_type", None)

                if tgt_attr:
                    tgt = (await tgt_attr()).name.lower()

                    side = "caster" if tgt == "self" else "target"

                else:
                    side = "caster"

                if (side, disp) in sides or (side, None) in sides:
                    participant = caster_p if side == "caster" else target_p

                    if participant is None:
                        return False

                    cnt = await count_hanging(participant, category, disp)

                    if cnt >= min_count:
                        return True

            except Exception:
                continue

    return False


def _verb_sides(verb: str) -> list[tuple[str, str | None]]:

    if verb == "gambit":
        return [("caster", "beneficial"), ("target", "harmful")]

    if verb == "clear":
        return [("caster", "harmful"), ("target", "beneficial")]

    if verb == "echo":
        return [("target", "beneficial"), ("target", "harmful")]

    return []
