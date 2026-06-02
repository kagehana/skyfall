from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from src.combat.handler import NativeCombat
from src.wad_icons import fetch_entity_icon_bytes, fetch_icon_bytes_by_path
from wizwalker.memory.memory_objects.conditionals import school_to_str


async def _school_stat(getter_list, getter_uni, idx: int) -> float:
    try:
        per_school = await getter_list()
    except Exception:
        per_school = []
    try:
        uni = float(await getter_uni())
    except Exception:
        uni = 0.0
    if not per_school or idx is None or idx >= len(per_school):
        return uni
    try:
        return float(per_school[idx]) + uni
    except Exception:
        return uni


async def _full_school_table(gs) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {s: {} for s in DETAIL_SCHOOLS}
    if gs is None:
        return table

    async def _pair(per_fn, uni_fn) -> tuple[list[float], float]:
        try:
            per = await per_fn()
        except Exception:
            per = []
        try:
            uni = float(await uni_fn())
        except Exception:
            uni = 0.0
        return per, uni

    dmg_per, dmg_uni = await _pair(gs.dmg_bonus_percent, gs.dmg_bonus_percent_all)
    res_per, res_uni = await _pair(gs.dmg_reduce_percent, gs.dmg_reduce_percent_all)
    pierce_per, pierce_uni = await _pair(gs.ap_bonus_percent, gs.ap_bonus_percent_all)
    acc_per, acc_uni = await _pair(gs.acc_bonus_percent, gs.acc_bonus_percent_all)
    try:
        crit_per = await gs.critical_hit_rating_by_school()
    except Exception:
        crit_per = []
    try:
        crit_uni = float(await gs.critical_hit_rating_all())
    except Exception:
        crit_uni = 0.0
    try:
        block_per = await gs.block_rating_by_school()
    except Exception:
        block_per = []
    try:
        block_uni = float(await gs.block_rating_all())
    except Exception:
        block_uni = 0.0

    def _idx(per: list[float], i: int, uni: float) -> float:
        if not per or i >= len(per):
            return uni
        try:
            return float(per[i]) + uni
        except Exception:
            return uni

    # ``DETAIL_SCHOOLS`` lines up with the list index used by game_stats
    # (Fire=0, Ice=1, Storm=2, Myth=3, Life=4, Death=5, Balance=6)
    for i, school in enumerate(DETAIL_SCHOOLS):
        table[school] = {
            "damage": _idx(dmg_per, i, dmg_uni),
            "resist": _idx(res_per, i, res_uni),
            "pierce": _idx(pierce_per, i, pierce_uni),
            "accuracy": _idx(acc_per, i, acc_uni),
            "crit": _idx(crit_per, i, crit_uni),
            "block": _idx(block_per, i, block_uni),
        }
    return table


# templates whose icon bytes have already been shipped to the GUI for this
# bot session. the GUI keeps its own pixmap cache; we only need to send the
# raw bytes once
_shipped_icons: set[int] = set()

# pip icons are shipped once per session (the GUI caches them keyed by
# pip kind, not by template id). flag goes True after the first
# successful upload
_pip_assets_shipped = False

# School icons (Fire / Ice / Storm / Myth / Life / Death / Balance) are
# shipped once per session - used by the full-stats popup to label per-
# school columns
_school_assets_shipped = False


# schools shown in the full-stats popup. matches list-index order so we
# can index ``dmg_bonus_percent()`` etc. without re-mapping.
DETAIL_SCHOOLS = ("Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance")


# School icon paths. most ship as ``.dds`` in Root; Life and Death are
# ``.tga``. pillow handles both.
_SCHOOL_ICON_PATHS = {
    "Fire": ("GUI/Icons/Icon_Fire.dds",),
    "Ice": ("GUI/Icons/Icon_Ice.dds",),
    "Storm": ("GUI/Icons/Icon_Storm.dds",),
    "Myth": ("GUI/Icons/Icon_Myth.dds",),
    "Life": ("GUI/Icons/Icon_Life.tga", "GUI/Icons/Icon_Life.dds"),
    "Death": ("GUI/Icons/Icon_Death.tga", "GUI/Icons/Icon_Death.dds"),
    "Balance": ("GUI/Icons/Icon_Balance.dds",),
}


async def _fetch_school_assets() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for school, paths in _SCHOOL_ICON_PATHS.items():
        for path in paths:
            try:
                data = await fetch_icon_bytes_by_path(path)
            except Exception:
                data = None
            if data:
                out[school] = data
                break
    return out


# pip kinds we surface in the snapshot. order is the visual display order
# the card uses: power pips first (yellow, highest value), then school-
# specific pips (any), then white pips, then shadow pips
PIP_KINDS = (
    "power",
    "fire",
    "ice",
    "storm",
    "myth",
    "life",
    "death",
    "balance",
    "normal",
    "shadow",
)


# WAD paths for each pip kind's icon. both wads are in our priority list
# so resolution is instant
_PIP_ICON_PATHS = {
    "normal": "GUI/PlayerInfo/pip_normal.dds",  # in Root.wad - 32x32
    "power": "GUI/PlayerInfo/pip_power.dds",  # 32x32
    # pip_shadow.dds is the 16x16 in-game size; the _large variant is 32x32
    # like the rest, so it scales to our 18px target at matching fidelity
    "shadow": "GUI/PlayerInfo/pip_shadow_large.dds",  # 32x32
    "fire": "GUI/PlayerInfo/pip_fire.dds",  # 32x32
    "ice": "GUI/PlayerInfo/pip_ice.dds",
    "storm": "GUI/PlayerInfo/pip_storm.dds",
    "myth": "GUI/PlayerInfo/pip_myth.dds",
    "life": "GUI/PlayerInfo/pip_life.dds",
    "death": "GUI/PlayerInfo/pip_death.dds",
    "balance": "GUI/PlayerInfo/pip_balance.dds",
}


def reset_icon_cache() -> None:
    global _pip_assets_shipped, _school_assets_shipped
    _shipped_icons.clear()
    _pip_assets_shipped = False
    _school_assets_shipped = False


async def _fetch_pip_assets() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for kind, path in _PIP_ICON_PATHS.items():
        try:
            data = await fetch_icon_bytes_by_path(path)
            if data:
                out[kind] = data
        except Exception:
            continue
    return out


async def _pip_breakdown(part) -> dict[str, int]:
    breakdown = {k: 0 for k in PIP_KINDS}
    try:
        pc = await part.pip_count()
    except Exception:
        pc = None
    if pc is None:
        return breakdown
    # read each kind defensively - pip_count fields are single bytes off
    # one struct; one bad read shouldn't poison the whole breakdown
    for kind, getter_name in (
        ("normal", "generic_pips"),
        ("power", "power_pips"),
        ("shadow", "shadow_pips"),
        ("fire", "fire_pips"),
        ("ice", "ice_pips"),
        ("storm", "storm_pips"),
        ("myth", "myth_pips"),
        ("life", "life_pips"),
        ("death", "death_pips"),
        ("balance", "balance_pips"),
    ):
        getter = getattr(pc, getter_name, None)
        if getter is None:
            continue
        try:
            breakdown[kind] = int(await getter())
        except Exception:
            pass
    return breakdown


async def _safe(awaitable, default: Any) -> Any:
    try:
        return await awaitable
    except Exception:
        return default


async def _participant_dict(member, client) -> Optional[dict]:
    try:
        part = await member.get_participant()
    except Exception:
        return None

    template_id = await _safe(part.template_id_full(), 0)
    owner_id = await _safe(part.owner_id_full(), 0)
    school_id = await _safe(part.primary_magic_school_id(), 0)
    school_name = school_to_str.get(school_id, "Unknown")
    is_player = bool(await _safe(part.is_player(), False))

    # per-school damage/resist/pierce/accuracy live on ``game_stats``, not
    # on CombatParticipant - the offset-based ``stat_damage`` / ``stat_resist``
    # fields read 0.0 even for fully-geared L165 wizards. we mirror
    # viewer.py's formula here.
    try:
        gs = await part.game_stats()
    except Exception:
        gs = None

    # full per-school table (damage/resist/pierce/accuracy/crit/block for
    # all seven schools) - feeds the click-to-expand full-stats popup
    school_stats = await _full_school_table(gs)

    # card-level summary stats are just the participant's primary-school
    # entries from the same table - keeps the card and the popup in sync
    primary = school_stats.get(school_name, {}) if school_name in school_stats else {}
    stat_damage = primary.get("damage", 0.0)
    stat_resist = primary.get("resist", 0.0)
    stat_pierce = primary.get("pierce", 0.0)
    accuracy_bonus = primary.get("accuracy", 0.0)

    # Name resolution. CombatMember.name() pulls from the participant. if it
    # fails we still want a row, just labelled "<unknown>"
    name = await _safe(member.name(), "<unknown>")

    # fetch icon bytes the first time we see a template, committing to
    # _shipped_icons only on success. misses can be transient (entity not in
    # the list yet, wad index not there yet), so we retry on later snapshots
    # rather than lock a template into the placeholder after one bad tick
    icon_bytes: Optional[bytes] = None
    if template_id and template_id not in _shipped_icons:
        try:
            entity = await part.fetch_entity()
            if entity is not None:
                icon_bytes = await fetch_entity_icon_bytes(entity)
        except Exception as exc:
            logger.debug(f"[snapshot] icon fetch failed for {name!r}: {exc}")

        # wizards have customisable looks and ship without a static
        # portrait - their template's icon field is empty. fall back to
        # the player's school icon. most schools ship as ``.dds`` in
        # Root.wad; Life and Death are ``.tga`` (Pillow handles both).
        if icon_bytes is None and is_player and school_name not in ("Unknown", ""):
            for ext in ("dds", "tga"):
                try:
                    icon_bytes = await fetch_icon_bytes_by_path(
                        f"GUI/Icons/Icon_{school_name}.{ext}"
                    )
                    if icon_bytes is not None:
                        break
                except Exception:
                    continue

        if icon_bytes is not None:
            _shipped_icons.add(template_id)

    # hangs / aura summary. read the linked-list lengths only - cheap, and
    # gives the GUI an at-a-glance "n active effects" badge without dragging
    # every DynamicSpellEffect through the queue
    hang_count = 0
    aura_count = 0
    try:
        hang_count = len(await part.hanging_effects())
    except Exception:
        pass
    try:
        aura_count = len(await part.aura_effects())
    except Exception:
        pass

    return {
        # identity
        "template_id": int(template_id),
        "owner_id": int(owner_id),
        "name": name,
        "school": school_name,
        "school_id": int(school_id),
        "team_id": await _safe(part.team_id(), 0),
        "side": await _safe(part.side(), ""),
        "slot_subcircle": await _safe(part.subcircle(), 0),
        # type flags
        "is_player": is_player,
        "is_monster": bool(await _safe(part.is_monster(), 0)),
        "is_minion": bool(await _safe(part.is_minion(), False)),
        "is_boss": bool(await _safe(part.boss_mob(), False)),
        "is_dead": bool(await _safe(member.is_dead(), False)),
        # vitals
        "level": int(await _safe(member.level(), 0)),
        "mob_level": int(await _safe(part.mob_level(), 0)),
        "health": int(await _safe(member.health(), 0)),
        "max_health": int(await _safe(member.max_health(), 0)),
        "mana": int(await _safe(member.mana(), 0)),
        "max_mana": int(await _safe(member.max_mana(), 0)),
        # pips - full per-kind breakdown so the card can render the
        # correct mix of school/power/normal/shadow pip icons
        "pips_breakdown": await _pip_breakdown(part),
        "pips_suspended": bool(await _safe(part.pips_suspended(), False)),
        # combat math stats (per primary school + universal bonus)
        "stat_damage": stat_damage,
        "stat_resist": stat_resist,
        "stat_pierce": stat_pierce,
        "accuracy_bonus": accuracy_bonus,
        # full per-school table used by the click-to-expand popup
        "school_stats": school_stats,
        # archmastery
        "archmastery_points": float(await _safe(part.archmastery_points(), 0.0)),
        "max_archmastery_points": float(
            await _safe(part.max_archmastery_points(), 0.0)
        ),
        "archmastery_school": int(await _safe(part.archmastery_school(), 0)),
        # status flags (booleans for at-a-glance chips)
        "stunned": bool(await _safe(part.stunned(), 0)),
        "mindcontrolled": bool(await _safe(part.mindcontrolled(), 0)),
        "confused": bool(await _safe(part.confused(), 0)),
        "untargetable": bool(await _safe(part.untargetable(), False)),
        "vanish": bool(await _safe(part.vanish(), False)),
        "auto_pass": bool(await _safe(part.auto_pass(), False)),
        "my_team_turn": bool(await _safe(part.my_team_turn(), False)),
        # shadow / backlash
        "shadow_creature_level": int(await _safe(part.shadow_creature_level(), 0)),
        "backlash": int(await _safe(part.backlash(), 0)),
        # effect counts
        "hang_count": hang_count,
        "aura_count": aura_count,
        # icon - bytes only the first time we ship this template id
        "icon_bytes": icon_bytes,
    }


async def build_snapshot(client) -> dict:
    global _pip_assets_shipped, _school_assets_shipped
    snap: dict = {
        "in_combat": False,
        "client_title": getattr(client, "title", "") or "",
        "combatants": [],
        # set on the first snapshot the GUI receives in this session; None
        # thereafter. the GUI caches the decoded pixmaps by kind name.
        "pip_assets": None,
        # school icons - shipped once per session. keyed by school name
        # ("fire", "Ice", ...).
        "school_assets": None,
    }
    if client is None:
        return snap

    try:
        in_battle = await client.in_battle()
    except Exception:
        in_battle = False

    if not in_battle:
        return snap

    snap["in_combat"] = True

    try:
        combat = NativeCombat(client, getattr(client, "combat_config", None))
        members = await combat.get_members()
    except Exception as exc:
        logger.warning(f"[snapshot] failed to enumerate members: {exc}")
        return snap

    rows: list[dict] = []
    for m in members:
        d = await _participant_dict(m, client)
        if d is not None:
            rows.append(d)
    snap["combatants"] = rows

    # ship the pip-icon bytes once per session
    if not _pip_assets_shipped:
        assets = await _fetch_pip_assets()
        if assets:
            snap["pip_assets"] = assets
            _pip_assets_shipped = True

    # ship school icons once per session
    if not _school_assets_shipped:
        s_assets = await _fetch_school_assets()
        if s_assets:
            snap["school_assets"] = s_assets
            _school_assets_shipped = True

    return snap
