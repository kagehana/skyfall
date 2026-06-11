from __future__ import annotations


import asyncio

import threading

from typing import Callable


from loguru import logger


# timeout policy: every waitfor_* takes an optional window arg in seconds.
# defaults below suit normal Wizard101 timings; pass a number to override or
# 0 to wait forever. on timeout we log a warning and raise ScriptError rather
# than hang silently - scripts that want soft behavior wrap the call in pcall

_DEFAULT_TIMEOUTS = {
    "freedom": 60.0,
    "battle_start": 60.0,
    "battle_finish": 900.0,  # long boss fights are routine
    "dialog": 30.0,
    "window": 30.0,
    "zone": 60.0,
    "zone_change": 120.0,
    "entity": 60.0,
    "entity_gone": 60.0,
    "mob": 60.0,
    "mob_gone": 60.0,
}

# checked by the stderr sink filters in skyfall.py. flipped by the
# pause_logs / resume_logs bridge globals; reset to False when any script ends
_log_paused: bool = False


def pause_logs() -> None:
    global _log_paused
    _log_paused = True


def resume_logs() -> None:
    global _log_paused
    _log_paused = False


def _resolve_window(name: str, window: float | None) -> float | None:
    if window is None:
        return _DEFAULT_TIMEOUTS[name]
    if window <= 0:
        return None
    return float(window)


from wizwalker import XYZ, Client, Keycode
from wizwalker.constants import Primitive

from wizwalker.memory.memory_objects.conditionals import (
    school_to_str,
    school_id_to_names,
)
from wizwalker.memory.memory_objects.game_object_template import WizGameObjectTemplate


from src.combat.config import parse_config as parse_playstyle

from src.combat.handler import NativeCombat

from src.lang.bridge import ScriptError

from src.paths import advance_dialog_path, dungeon_warning_path, npc_range_path

from src.teleport import auto_adjusting_teleport, navmap_tp

from src.nav.client import is_mob
from src.nav.navigator import to_zone

from src.utils import (
    assign_school_pip,
    click_window_by_path,
    get_window_from_path,
    is_free,
    is_visible_by_path,
)


async def _teleport_with_retry(
    client: Client,
    target: XYZ,
    stop_event: threading.Event | None = None,
    *,
    settle: float = 0.15,
    backoff: float = 0.3,
) -> None:
    tolerance = 75.0  # game units
    for attempt in range(3):
        try:
            await client.teleport(target)
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(backoff)
            continue

        await asyncio.sleep(settle)
        try:
            pos = await client.body.position()
        except Exception:
            return  # can't verify - assume it took

        dx = pos.x - target.x
        dy = pos.y - target.y
        if (dx * dx + dy * dy) <= (tolerance * tolerance):
            return

        if stop_event is not None and stop_event.is_set():
            return
        await asyncio.sleep(backoff)


def _nearest_gate_toward(
    gates: list[dict], x: float, y: float, z: float
) -> dict | None:
    if not gates:
        return None

    def _d2(g: dict) -> float:
        try:
            return (g["x"] - x) ** 2 + (g["y"] - y) ** 2 + (g["z"] - z) ** 2
        except Exception:
            return float("inf")

    exits = [g for g in gates if g.get("kind") == "exit"]
    pool = exits or gates
    return min(pool, key=_d2)


# when the goal is cross-zone the quest helper sits *at* the gate, so the
# gate should be within this many units of the helper position. if the
# nearest gate is farther, we're probably not meant to cross here
GATE_NEAR_HELPER = 1500.0


async def quest_destination_zone_of(client: Client) -> str:
    try:
        qid = await client.quest_id()
    except Exception:
        return ""
    if not qid:
        return ""
    try:
        mgr = await client.quest_manager()
        quests = await mgr.quest_data()
    except Exception:
        return ""
    quest = quests.get(qid)
    if quest is None:
        return ""
    try:
        goals = await quest.goal_data()
    except Exception:
        return ""

    for g in goals.values():
        try:
            dz = await g.goal_destination_zone()
        except Exception:
            dz = ""
        if dz:
            return dz
    return ""


async def walk_quest_gate_if_cross_zone(
    client: Client,
    xyz: XYZ,
    stop_event: threading.Event | None = None,
) -> bool:
    from src.nav.scraper import enumerate_zone_gates, walk_through_gate

    try:
        dest = await quest_destination_zone_of(client)
        cur = await client.zone_name()
    except Exception:
        return False
    if not dest or not cur or dest.strip() == cur.strip():
        return False

    try:
        await _teleport_with_retry(client, xyz, stop_event)
    except Exception:
        return False

    try:
        gates = await enumerate_zone_gates(client)
    except Exception:
        gates = []
    gate = _nearest_gate_toward(gates, xyz.x, xyz.y, xyz.z)
    if gate is None:
        return False

    try:
        d2 = (
            (gate["x"] - xyz.x) ** 2
            + (gate["y"] - xyz.y) ** 2
            + (gate["z"] - xyz.z) ** 2
        )
    except Exception:
        d2 = float("inf")
    if d2 > GATE_NEAR_HELPER * GATE_NEAR_HELPER:
        return False

    try:
        # give the gate-walk the same escalating retries client:go_through_gate
        # uses (it's the primitive that actually crosses). a single base-param
        # attempt fails on most gates, and the caller's only fallback is a flat
        # teleport onto the helper xyz - which sits in the doorway, leaving the
        # wizard standing inside the door. let the walk escalate back_distance /
        # hold_seconds instead of bailing after one try.
        return await walk_through_gate(
            client, gate["name"], max_dist=GATE_NEAR_HELPER, max_attempts=3
        )
    except Exception as e:
        logger.warning(
            f"{client.title}: cross-zone gate-walk ({gate.get('name')!r}) failed: {e}"
        )
        return False


async def _quest_helper_goal_text_of(client: Client) -> str:
    from src.paths import quest_name_path
    from src.utils import get_window_from_path

    try:
        win = await get_window_from_path(client.root_window, quest_name_path)
        if not win:
            return ""
        txt = await win.maybe_text() or ""
        return txt.replace("<center>", "").replace("</center>", "").strip()
    except Exception:
        return ""


async def _active_quest_goal_of(client: Client):
    try:
        qid = await client.quest_id()
        gid = await client.goal_id()
    except Exception:
        return None, None
    if not qid:
        return None, None
    try:
        mgr = await client.quest_manager()
        quests = await mgr.quest_data()
    except Exception:
        return None, None
    quest = quests.get(qid)
    if quest is None:
        return None, None
    try:
        goals = await quest.goal_data()
    except Exception:
        return quest, None
    return quest, goals.get(gid)


async def run_tp_to_quest(client: Client, stop: threading.Event | None = None):
    tag = f"[tp_to_quest] {client.title}"

    last_zone = getattr(client, "_tpq_last_zone", None)
    last_pos = getattr(client, "_tpq_last_pos", None)
    anchors = client.__dict__.get("_tpq_anchors")
    if anchors is None:
        anchors = {}
        client._tpq_anchors = anchors

    # stale-helper guard: after a zone change the quest helper briefly keeps
    # the previous zone's xyz before the game recomputes the goal. poll until
    # the helper xyz moves away from the last value (new data ready) instead
    # of sleeping a fixed time; capped so a never-changing coord can't hang
    try:
        cur = await client.zone_name()
    except Exception:
        cur = ""
    if cur and cur != last_zone:
        prev = last_pos
        if last_zone is not None and prev is not None:
            logger.debug(
                f"{tag}: zone changed ({last_zone!r} → {cur!r}); "
                f"polling for helper refresh"
            )
            deadline = asyncio.get_event_loop().time() + 2.0
            while asyncio.get_event_loop().time() < deadline:
                if stop is not None and stop.is_set():
                    break
                try:
                    p = await client.quest_position.position()
                except Exception:
                    break
                if (
                    abs(p.x - prev.x) > 1.0
                    or abs(p.y - prev.y) > 1.0
                    or abs(p.z - prev.z) > 1.0
                ):
                    break
                await asyncio.sleep(0.05)
        last_zone = cur
        client._tpq_last_zone = cur

    # anchor capture: first time in this zone, record the wizard's current
    # (entrance-door, in-bounds) position as the snap-out recovery target
    if cur and cur not in anchors:
        try:
            anchor_pos = await client.body.position()
            anchors[cur] = anchor_pos
            logger.debug(
                f"{tag}: captured zone anchor for {cur!r} at "
                f"({anchor_pos.x:.0f}, {anchor_pos.y:.0f}, {anchor_pos.z:.0f})"
            )
        except Exception as e:
            logger.debug(f"{tag}: anchor capture failed: {type(e).__name__}: {e}")

    try:
        xyz = await client.quest_position.position()
    except Exception as e:
        logger.warning(f"{tag}: helper read failed: {e}")
        return

    client._tpq_last_pos = xyz

    try:
        objective = (await _quest_helper_goal_text_of(client)).lower()
    except Exception:
        objective = ""

    # only talk-to-NPC goals (GoalType.persona) get the post-teleport
    # stream-nudge - combat / collect / waypoint goals just need the player at
    # the xyz, and the nudge can harm them (walking out of a tight mob room)
    goal_type_name = ""
    try:
        _, goal = await _active_quest_goal_of(client)
        if goal is not None:
            goal_type_name = (await goal.goal_type()).name
    except Exception:
        pass
    try:
        pre_pos = await client.body.position()
        pre_str = f"({pre_pos.x:.0f}, {pre_pos.y:.0f}, {pre_pos.z:.0f})"
    except Exception:
        pre_pos, pre_str = None, "?"
    try:
        dest = await quest_destination_zone_of(client)
    except Exception:
        dest = ""

    logger.info(
        f"{tag}: entry objective={objective[:60]!r} "
        f"goal_type={goal_type_name or '?'} "
        f"helper=({xyz.x:.0f}, {xyz.y:.0f}, {xyz.z:.0f}) "
        f"pre={pre_str} cur_zone={cur or '?'} dest_zone={dest or '?'}"
    )

    if dest and cur and dest.strip() != cur.strip():
        logger.info(
            f"{tag}: CROSS-ZONE branch (dest={dest!r} != cur={cur!r}) "
            "→ walk_quest_gate_if_cross_zone"
        )
        crossed = await walk_quest_gate_if_cross_zone(client, xyz, stop)
        logger.info(f"{tag}: gate walk returned crossed={crossed}")
        return

    logger.info(f"{tag}: SAME-ZONE branch (dest={dest or '?'!r}) → teleport")

    # same-zone goal: single teleport attempt to the helper, then recovery
    # (a blind retry of a rejected coord just bungees the wizard)
    try:
        await client.teleport(xyz)
    except Exception as e:
        logger.debug(f"{tag}: initial teleport raised: {type(e).__name__}: {e}")

    # mandatory dwell so the next read sees a stable post-tp state (incl. any
    # snap-back the game performs on a collider-rejected position)
    await asyncio.sleep(0.8)

    if goal_type_name == "persona":
        # raw teleports don't fire the movement event the entity streamer
        # listens on, so talk-to NPCs sometimes fail to load in. a short W tap
        # ticks the streamer; re-teleport recovers any boundary-snap
        try:
            await client.send_key(Keycode.W, 0.1)
        except Exception as e:
            logger.debug(f"{tag}: stream-nudge failed: {type(e).__name__}: {e}")
        try:
            await client.teleport(xyz)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.debug(f"{tag}: re-anchor teleport failed: {type(e).__name__}: {e}")

    post_pos = None
    moved_xy = None
    try:
        post_pos = await client.body.position()
        post_str = f"({post_pos.x:.0f}, {post_pos.y:.0f}, {post_pos.z:.0f})"
        drift_xy = ((post_pos.x - xyz.x) ** 2 + (post_pos.y - xyz.y) ** 2) ** 0.5
        drift = f"{drift_xy:.0f}"
        if pre_pos is not None:
            moved_xy = (
                (post_pos.x - pre_pos.x) ** 2 + (post_pos.y - pre_pos.y) ** 2
            ) ** 0.5
    except Exception:
        post_str, drift, drift_xy = "?", "?", None

    popup = False
    try:
        popup = await is_visible_by_path(client, npc_range_path)
    except Exception:
        pass

    logger.debug(
        f"{tag}: post-tp pos={post_str} drift_xy={drift}u "
        f"moved={f'{moved_xy:.0f}u' if moved_xy is not None else '?'} "
        f"npc_range_popup={popup}"
    )

    SNAP_OUT_THRESHOLD = 1500.0
    try:
        post_zone = await client.zone_name()
    except Exception:
        post_zone = cur

    if post_zone != cur:
        # undeclared cross-zone tp: helper xyz pointed into a sub-instance and
        # the teleport landed us there at an out-of-bounds coord. walk back
        # through whichever gate in the new zone partners the previous zone
        logger.debug(
            f"{tag}: zone changed during tp "
            f"({cur!r} → {post_zone!r}); walking back to recover"
        )
        from src.nav.scraper import enumerate_zone_gates, walk_through_gate

        gate_name = None
        try:
            gates = await enumerate_zone_gates(client)
            for g in gates:
                if (g.get("partner") or "").strip() == cur:
                    gate_name = g.get("name")
                    break
        except Exception as e:
            logger.debug(f"{tag}: gate enumeration failed: {type(e).__name__}: {e}")
        if gate_name:
            try:
                ok = await walk_through_gate(client, gate_name)
                logger.debug(f"{tag}: gate-walk back through {gate_name!r}: ok={ok}")
            except Exception as e:
                logger.warning(f"{tag}: gate-walk back failed: {type(e).__name__}: {e}")
        else:
            logger.debug(
                f"{tag}: no gate in {post_zone!r} partners to {cur!r}; "
                f"leaving wizard in {post_zone!r} for the caller to handle"
            )
    elif (
        drift_xy is not None
        and drift_xy > SNAP_OUT_THRESHOLD
        and moved_xy is not None
        and moved_xy < 100.0
    ):
        # tp-rejected case: wizard didn't move (post ≈ pre). the helper xyz
        # isn't a navmesh-valid standing point; spiral out around it until a
        # valid offset takes
        logger.debug(
            f"{tag}: teleport rejected (moved {moved_xy:.0f}u; "
            f"drift {drift_xy:.0f}u) — running auto-adjusting spiral"
        )
        try:
            await auto_adjusting_teleport(client, xyz)
        except Exception as e:
            logger.debug(
                f"{tag}: auto_adjusting_teleport failed: {type(e).__name__}: {e}"
            )
    elif drift_xy is not None and drift_xy > SNAP_OUT_THRESHOLD and cur in anchors:
        # snap-out case: wizard moved but ended up far from the helper. recover
        # to the known-safe in-bounds anchor
        anchor = anchors[cur]
        moved_str = f"{moved_xy:.0f}u" if moved_xy is not None else "?"
        logger.debug(
            f"{tag}: post-tp drift {drift_xy:.0f}u exceeds threshold "
            f"({SNAP_OUT_THRESHOLD:.0f}u), moved {moved_str} — recovering to "
            f"zone anchor ({anchor.x:.0f}, {anchor.y:.0f}, {anchor.z:.0f})"
        )
        try:
            await client.teleport(anchor)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(
                f"{tag}: anchor recovery teleport failed: {type(e).__name__}: {e}"
            )


# cached per-zone nav chunks for ``_streaming_reset`` - Wizard101 streams
# entities by player distance, so a "didn't load in" sigil/NPC usually
# unsticks once the player leaves and returns. wad parsing is slow enough
# that we memoize: chunks are zone-static
_ZONE_CHUNK_CACHE: dict[str, list[XYZ]] = {}

# shared zone spawn-point resolver (reagent node sets from static WAD data)
# holds the wiztype list + reagent-id cache; build lazily, reuse across calls
_ZONE_SPAWNS = None


def _zone_spawns():
    global _ZONE_SPAWNS
    if _ZONE_SPAWNS is None:
        from src.spawns import ZoneSpawns

        _ZONE_SPAWNS = ZoneSpawns()
    return _ZONE_SPAWNS


# distance window for the re-stream "bounce": teleport this far from the
# target (to a nearby nav chunk) and back, to make Wizard101 re-run its
# distance-based entity loader. far enough to leave the target's streaming
# cell, close enough to stay in-zone and reload on the way back
_STREAM_RESET_MIN_DIST = 1500.0
_STREAM_RESET_MAX_DIST = 3000.0


async def _load_zone_chunks(client: Client) -> list[XYZ]:
    try:
        zone = await client.zone_name()
    except Exception:
        return []

    chunks = _ZONE_CHUNK_CACHE.get(zone)
    if chunks is None:
        try:
            from wizwalker.file_readers.wad import Wad
            from src.teleport import parse_nav_data, calc_chunks

            wad = Wad.from_game_data(zone.replace("/", "-"))
            nav = await wad.get_file("zone.nav")
            verts, _ = parse_nav_data(nav)
            chunks = calc_chunks(verts)
        except Exception:
            chunks = []
        _ZONE_CHUNK_CACHE[zone] = chunks

    return chunks


async def _streaming_chunk_near(
    client: Client,
    target: XYZ,
    min_dist: float = _STREAM_RESET_MIN_DIST,
    max_dist: float = _STREAM_RESET_MAX_DIST,
) -> XYZ | None:
    chunks = await _load_zone_chunks(client)
    if not chunks:
        return None

    def _d2(c):
        return (c.x - target.x) ** 2 + (c.y - target.y) ** 2

    min2 = min_dist * min_dist
    max2 = max_dist * max_dist

    in_window = [c for c in chunks if min2 <= _d2(c) <= max2]
    if in_window:
        pick = min(in_window, key=_d2)
    else:
        # fallback: closest chunk that's at least min_dist away
        far_enough = [c for c in chunks if _d2(c) >= min2]
        if not far_enough:
            return None
        pick = min(far_enough, key=_d2)

    return XYZ(pick.x, pick.y, pick.z - 550)


async def _streaming_reset(
    client: Client, target: XYZ, stop_event: threading.Event | None = None
) -> bool:
    settle = 1.0

    chunk = await _streaming_chunk_near(client, target)
    fallback = chunk is None
    if chunk is None:
        offset = (_STREAM_RESET_MIN_DIST + _STREAM_RESET_MAX_DIST) * 0.5
        chunk = XYZ(target.x + offset, target.y, target.z)

    try:
        zone = await client.zone_name()
    except Exception:
        zone = "?"
    try:
        pos = await client.body.position()
        pos_str = f"({pos.x:.0f}, {pos.y:.0f}, {pos.z:.0f})"
    except Exception:
        pos_str = "?"
    logger.debug(
        f"[lua] {client.title}: streaming_reset: zone={zone} "
        f"from={pos_str} "
        f"target=({target.x:.0f}, {target.y:.0f}, {target.z:.0f}) "
        f"chunk=({chunk.x:.0f}, {chunk.y:.0f}, {chunk.z:.0f})"
        f"{' [fallback offset — no nav chunks]' if fallback else ''}"
    )

    try:
        await _teleport_with_retry(client, chunk, stop_event=stop_event)
    except Exception:
        return False

    await asyncio.sleep(settle)

    if stop_event is not None and stop_event.is_set():
        return False

    try:
        await _teleport_with_retry(client, target, stop_event=stop_event)
    except Exception:
        return False

    return True


async def _nearest_hostile_mob_xyz(client: Client, around: XYZ, scan_radius: float):
    best, best_d2 = None, (scan_radius * scan_radius)
    try:
        entities = await client.get_base_entity_list()
    except Exception:
        return None
    for e in entities:
        try:
            if not await is_mob(e):
                continue
            loc = await e.location()
            dx = loc.x - around.x
            dy = loc.y - around.y
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2, best = d2, loc
        except Exception:
            continue
    return best


async def _teleport_near(client: Client, target: XYZ, dist: float, scan_radius: float):
    import math as _math

    mob_xyz = await _nearest_hostile_mob_xyz(client, target, scan_radius)

    dx = dy = 0.0
    if mob_xyz is not None:
        dx, dy = target.x - mob_xyz.x, target.y - mob_xyz.y

    # if no mob, or mob is degenerate-close to target, fall back to the
    # player's approach vector - we at least know that direction wasn't
    # already inside aggro range (we got here without combat firing)
    if _math.hypot(dx, dy) < 1e-3:
        try:
            me = await client.body.position()
            dx, dy = target.x - me.x, target.y - me.y
        except Exception:
            dx, dy = 1.0, 0.0

    mag = _math.hypot(dx, dy)
    if mag < 1e-3:
        dx, dy, mag = 1.0, 0.0, 1.0
    ux, uy = dx / mag, dy / mag

    offset = XYZ(target.x + ux * dist, target.y + uy * dist, target.z)
    try:
        await _teleport_with_retry(client, offset)
    except Exception:
        await _teleport_with_retry(client, target)


def _push_gui_status(tag: str, status: str, client_title: str = None) -> None:
    try:
        import sys

        main_mod = sys.modules.get("__main__")
        queue = getattr(main_mod, "gui_send_queue", None)
        if queue is None:
            return
        from src.gui import GUICommand, GUICommandType

        data = (tag, status, client_title) if client_title else (tag, status)
        queue.put(GUICommand(GUICommandType.UpdateWindow, data))
    except Exception:
        pass


def _push_combat_gui_status(status: str, client_title: str = None) -> None:
    _push_gui_status("CombatStatus", status, client_title)


def _push_dialog_gui_status(status: str, client_title: str = None) -> None:
    _push_gui_status("DialogueStatus", status, client_title)


class LuaItem:
    def __init__(
        self, item, call: Callable, table_from: Callable, *, equipped: bool = False
    ):
        self._item = item
        self._call = call
        self._table = table_from
        self._equipped = equipped

    async def _template(self):
        core = await self._item.object_template()
        if core is None:
            return None
        return WizGameObjectTemplate(core.hook_handler, await core.read_base_address())

    def name(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    return await tmpl.object_name() or ""
            except Exception:
                pass
            return await self._item.debug_name() or ""

        return self._call(_())

    def debug_name(self) -> str:
        return self._call(self._item.debug_name())

    def global_id(self) -> int:
        return self._call(self._item.global_id_full())

    def perm_id(self) -> int:
        return self._call(self._item.perm_id())

    def template_id(self) -> int:
        return self._call(self._item.template_id_full())

    def object_type(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    t = await tmpl.object_type()
                    return str(t).split(".")[-1].lower() if t is not None else ""
            except Exception:
                pass
            return ""

        return self._call(_())

    def school(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    return await tmpl.primary_school_name() or ""
            except Exception:
                pass
            return ""

        return self._call(_())

    def description(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    return await tmpl.description() or ""
            except Exception:
                pass
            return ""

        return self._call(_())

    def icon(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    return await tmpl.icon() or ""
            except Exception:
                pass
            return ""

        return self._call(_())

    def adjective_list(self) -> str:
        async def _():
            try:
                tmpl = await self._template()
                if tmpl:
                    return await tmpl.adjective_list() or ""
            except Exception:
                pass
            return ""

        return self._call(_())

    def is_equipped(self) -> bool:
        return self._equipped

    def info(self):

        async def _():
            result = {
                "name": "",
                "debug_name": "",
                "global_id": 0,
                "perm_id": 0,
                "template_id": 0,
                "object_type": "",
                "school": "",
                "description": "",
                "icon": "",
                "adjective_list": "",
                "is_equipped": self._equipped,
            }
            try:
                result["debug_name"] = await self._item.debug_name() or ""
                result["global_id"] = await self._item.global_id_full()
                result["perm_id"] = await self._item.perm_id()
                result["template_id"] = await self._item.template_id_full()
                tmpl = await self._template()
                if tmpl:
                    result["name"] = await tmpl.object_name() or result["debug_name"]
                    t = await tmpl.object_type()
                    result["object_type"] = (
                        str(t).split(".")[-1].lower() if t is not None else ""
                    )
                    result["school"] = await tmpl.primary_school_name() or ""
                    result["description"] = await tmpl.description() or ""
                    result["icon"] = await tmpl.icon() or ""
                    result["adjective_list"] = await tmpl.adjective_list() or ""
                else:
                    result["name"] = result["debug_name"]
            except Exception:
                pass
            return result

        return self._table(self._call(_()))


class LuaClient:
    def __init__(
        self,
        client: Client,
        call: Callable,
        stop: threading.Event,
        table_from: Callable,
        bridge=None,
    ):

        self._c = client

        self._call = call

        self._stop = stop

        self._table = table_from

        # owning LuaBridge, used to register teardown for toggles the script
        # turns on so they don't outlive it. none in tests/standalone, where
        # toggles just aren't auto-torn-down
        self._bridge = bridge

        # zone the script last acknowledged (via zone(), waitfor_zone*,
        # go_through_gate). lets waitfor_zone_change() notice the zone already
        # changed and return instead of waiting for a second change that never
        # comes. none = no baseline yet. combat/dialog/loading don't need this
        # since their waits check current state, not a transition; zone is the
        # one case you can miss by checking after the fact
        self._last_seen_zone: str | None = None

        # tp_to_quest's per-call state lives on the client object (managed by
        # run_tp_to_quest) so the lua method and the auto-quester toggle share
        # one view across rebuilt LuaClient wrappers

    @property
    def title(self) -> str:

        return self._c.title

    def health(self) -> int:

        return self._call(self._c.stats.current_hitpoints())

    def max_health(self) -> int:

        return self._call(self._c.stats.max_hitpoints())

    def mana(self) -> int:

        return self._call(self._c.stats.current_mana())

    def max_mana(self) -> int:

        return self._call(self._c.stats.max_mana())

    def energy(self) -> int:

        return self._call(self._c.stats.current_energy())

    def level(self) -> int:

        return self._call(self._c.stats.reference_level())

    def bag_used(self) -> int:

        return self._call(self._c.backpack_space())[0]

    def bag_max(self) -> int:

        return self._call(self._c.backpack_space())[1]

    def zone(self) -> str:

        z = self._call(self._c.zone_name())
        # reading zone() counts as acknowledging where we are, so a later
        # waitfor_zone_change() waits for a change from here. only ack non-None
        # readings - a nil baseline (mid-load) would make it wait forever
        if z is not None:
            self._last_seen_zone = z
        return z

    def zone_quiet(self) -> str:
        return self._call(self._c.zone_name())

    def in_zone(self, name: str) -> bool:

        return name in self._call(self._c.zone_name())

    def health_pct(self) -> float:

        async def _():
            hp = await self._c.stats.current_hitpoints()
            mx = await self._c.stats.max_hitpoints()
            return (hp / mx * 100.0) if mx else 0.0

        return self._call(_())

    def mana_pct(self) -> float:

        async def _():
            mp = await self._c.stats.current_mana()
            mx = await self._c.stats.max_mana()
            return (mp / mx * 100.0) if mx else 0.0

        return self._call(_())

    def in_combat(self) -> bool:

        return self._call(self._c.in_battle())

    def is_free(self) -> bool:
        from src.utils import is_free as _is_free

        return self._call(_is_free(self._c))

    def is_loading(self) -> bool:

        async def _():
            try:
                return await self._c.is_loading()
            except Exception:
                return False

        return self._call(_())

    def window_disabled(self, path) -> bool:
        path_list = list(path.values()) if hasattr(path, "values") else list(path)
        from wizwalker.memory import WindowFlags

        async def _():
            try:
                w = await get_window_from_path(self._c.root_window, path_list)
            except Exception:
                return False
            if not w:
                return False
            try:
                flags = await w.flags()
                return WindowFlags.disabled in flags
            except Exception:
                return False

        return self._call(_())

    def release_mouse(self):

        async def _():
            try:
                await self._c.mouse_handler.release_mouse()
            except Exception:
                pass

        self._call(_())

    # ── potions ──────────────────────────────────────────────────────────────
    def potion_count(self) -> float:

        return self._call(self._c.stats.potion_charge())

    def has_potion(self) -> bool:

        async def _():
            return (await self._c.stats.potion_charge()) >= 1.0

        return self._call(_())

    def use_potion(self) -> bool:

        async def _():
            if (await self._c.stats.potion_charge()) < 1.0:
                return False
            try:
                async with self._c.mouse_handler:
                    await self._c.mouse_handler.click_window_with_name("btnPotions")
                return True
            except Exception:
                return False

        return self._call(_())

    def lookup_template(self, template_id):

        async def _():
            try:
                return await self._c.cache_handler.get_template_name(int(template_id))
            except Exception:
                return None

        return self._call(_())

    def x(self) -> float:

        async def _():
            return (await self._c.body.position()).x

        return self._call(_())

    def y(self) -> float:

        async def _():
            return (await self._c.body.position()).y

        return self._call(_())

    def z(self) -> float:

        async def _():
            return (await self._c.body.position()).z

        return self._call(_())

    def position(self):

        async def _():
            pos = await self._c.body.position()
            return [pos.x, pos.y, pos.z]

        return self._table(self._call(_()))

    def facing(self) -> float:

        async def _():
            try:
                return await self._c.body.yaw()
            except Exception:
                return 0.0

        return self._call(_())

    def distance_to(self, x: float, y: float, z: float) -> float:

        async def _():
            pos = await self._c.body.position()
            return pos.distance(XYZ(x, y, z))

        return self._call(_())

    def _timeout(self, kind: str, detail: str):
        msg = (
            f"waitfor_{kind}: timed out — {detail}. "
            "Pass window=0 to wait forever, or a larger number of seconds."
        )
        logger.warning(f"[lua] {self._c.title}: {msg}")
        return ScriptError(msg)

    def waitfor_freedom(self, window: float = None):
        deadline_s = _resolve_window("freedom", window)

        async def _():
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while not await is_free(self._c):
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout("freedom", "client never reached an idle state")
                await asyncio.sleep(0.25)

        self._call(_())

    def waitfor_battle_start(self, window: float = None):
        deadline_s = _resolve_window("battle_start", window)

        async def _():
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while not await self._c.in_battle():
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        "battle_start", "no battle started within the window"
                    )
                await asyncio.sleep(0.25)

        self._call(_())

    def waitfor_battle_finish(self, window: float = None):
        deadline_s = _resolve_window("battle_finish", window)

        async def _():
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while not await self._c.in_battle():
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        "battle_finish", "no battle began within the window"
                    )
                await asyncio.sleep(0.25)

            # if the GUI combat_task owns this client, let it drive the fight
            # (it spawns its own NativeCombat per battle). starting a competing
            # one here races for _active_combat and both fire packets, so one
            # cast silently clobbers the other. just wait for combat to end
            gui_combat_on = bool(getattr(self._c, "combat_status", False))
            if gui_combat_on:
                while await self._c.in_battle():
                    if self._stop.is_set():
                        return
                    await asyncio.sleep(0.25)
            else:
                # Drive the fight to completion. toggle-off / KillBot signal the
                # active handler via cancel_combat() - see combat/handler.py.
                # NativeCombat respects the same stop event, so kill-button works
                await NativeCombat(self._c, self._c.combat_config).wait_for_combat()

            # final check: if combat is somehow still active and we blew the
            # window, surface that rather than returning success silently
            if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                if await self._c.in_battle():
                    raise self._timeout(
                        "battle_finish", "combat exceeded the window without ending"
                    )

        self._call(_())

    def waitfor_dialog(self, window: float = None):
        deadline_s = _resolve_window("dialog", window)

        async def _():
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while not await is_visible_by_path(self._c, advance_dialog_path):
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        "dialog", "no dialog appeared within the window"
                    )
                await asyncio.sleep(0.25)

        self._call(_())

    def waitfor_window(self, path, window: float = None):
        path_list = list(path.values()) if hasattr(path, "values") else list(path)
        deadline_s = _resolve_window("window", window)

        async def _():
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while not await is_visible_by_path(self._c, path_list):
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        "window", f"window {path_list!r} never appeared"
                    )
                await asyncio.sleep(0.25)

        self._call(_())

    def waitfor_zone(self, name: str, window: float = None):
        deadline_s = _resolve_window("zone", window)

        async def _():
            needle = name.lower()
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            while needle not in (await self._c.zone_name() or "").lower():
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    cur = await self._c.zone_name() or "<unknown>"
                    raise self._timeout(
                        "zone",
                        f"never entered zone matching {name!r} (still in {cur!r})",
                    )
                await asyncio.sleep(0.5)
            # acknowledge - keeps the zone-change baseline in sync. guard
            # against a transient None reading right at the load boundary;
            # a nil baseline poisons waitfor_zone_change
            try:
                z = await self._c.zone_name()
                if z is not None:
                    self._last_seen_zone = z
            except Exception:
                pass

        self._call(_())

    def waitfor_zone_change(self, current: str = None, window: float = None):
        deadline_s = _resolve_window("zone_change", window)

        async def _():
            if current is not None:
                baseline = None  # substring mode - no fixed baseline
            elif self._last_seen_zone is not None:
                baseline = self._last_seen_zone
            else:
                baseline = await self._c.zone_name()

            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )

            while True:
                if self._stop.is_set():
                    return False

                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    cur = await self._c.zone_name() or "<unknown>"
                    raise self._timeout(
                        "zone_change",
                        f"zone never changed from {baseline!r} (still in {cur!r}); "
                        "did a previous call already consume the change?"
                        if current is None
                        else f"zone never stopped matching {current!r} (current: {cur!r})",
                    )

                now = await self._c.zone_name()

                # zone_name() momentarily reads none mid-transition. treating
                # that as a change poisons the baseline (none then makes
                # waitfor_zone_change wait forever), so skip none and only
                # count real zone strings as changes
                if now is None:
                    pass
                elif current is not None:
                    if current.lower() not in now.lower():
                        self._last_seen_zone = now
                        return True
                else:
                    if now != baseline:
                        self._last_seen_zone = now
                        return True

                step = 0.25
                if deadline is not None:
                    step = min(
                        step, max(0.05, deadline - asyncio.get_event_loop().time())
                    )
                await asyncio.sleep(step)

        return self._call(_())

    async def _entity_matches(self, e, needle: str, mob_only: bool) -> bool:
        try:
            obj = (await e.object_name() or "").lower()
            disp = (await e.display_name() or "").lower()
            name_match = needle in obj or needle in disp
            if not name_match:
                try:
                    tmpl = await e.object_template()
                    if tmpl is not None:
                        tdisp = (await tmpl.display_name() or "").lower()
                        if needle in tdisp:
                            name_match = True
                except Exception:
                    pass
            if not name_match:
                return False
            if mob_only and not await is_mob(e):
                return False
            return True
        except Exception:
            return False

    def _waitfor_entity_impl(
        self,
        name: str,
        window: float,
        max_dist: float | None,
        *,
        mob_only: bool,
        kind: str,
    ):
        deadline_s = _resolve_window(kind, window)

        async def _():
            needle = name.lower()
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            label = "mob" if mob_only else "entity"
            while True:
                if self._stop.is_set():
                    return None
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        kind,
                        f"no {label} matching {name!r} appeared"
                        + (f" within {max_dist} units" if max_dist else ""),
                    )
                # these reads go through the client-object tree, which is
                # transiently invalid during loading/transitions - exactly when
                # these waiters run. guard the tick so a read failure just means
                # "not visible yet, poll again" and only the deadline ends it
                try:
                    pos = await self._c.body.position()
                    entities = await self._c.get_base_entity_list()
                except Exception:
                    entities = None
                for e in entities or ():
                    try:
                        dist = pos.distance(await e.location())
                        if max_dist is not None and dist > max_dist:
                            continue
                        if await self._entity_matches(e, needle, mob_only):
                            return LuaMob(e, dist, self._call, self._c, self._table)
                    except Exception:
                        continue
                step = 0.25
                if deadline is not None:
                    step = min(
                        step, max(0.05, deadline - asyncio.get_event_loop().time())
                    )
                await asyncio.sleep(step)

        return self._call(_())

    def _waitfor_entity_gone_impl(
        self,
        name: str,
        max_dist: float | None,
        window: float,
        *,
        mob_only: bool,
        kind: str,
    ):
        deadline_s = _resolve_window(kind, window)

        async def _():
            needle = name.lower()
            deadline = (
                asyncio.get_event_loop().time() + deadline_s
                if deadline_s is not None
                else None
            )
            label = "mob" if mob_only else "entity"
            while True:
                if self._stop.is_set():
                    return
                if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                    raise self._timeout(
                        kind,
                        f"{label} matching {name!r} never disappeared"
                        + (f" (within {max_dist} units)" if max_dist else ""),
                    )
                # a failed world read here must NOT be read as "entity gone"
                # (see _waitfor_entity_impl for why these reads throw during
                # transitions). on read failure, keep polling.
                try:
                    pos = await self._c.body.position()
                    entities = await self._c.get_base_entity_list()
                except Exception:
                    await asyncio.sleep(0.5)
                    continue
                found = False
                for e in entities or ():
                    try:
                        dist = pos.distance(await e.location())
                        if max_dist is not None and dist > max_dist:
                            continue
                        if await self._entity_matches(e, needle, mob_only):
                            found = True
                            break
                    except Exception:
                        continue
                if not found:
                    return
                await asyncio.sleep(0.5)

        self._call(_())

    def waitfor_entity(self, name: str, window: float = None, max_dist: float = None):
        return self._waitfor_entity_impl(
            name, window, max_dist, mob_only=False, kind="entity"
        )

    def waitfor_entity_gone(
        self, name: str, max_dist: float = None, window: float = None
    ):
        return self._waitfor_entity_gone_impl(
            name, max_dist, window, mob_only=False, kind="entity_gone"
        )

    def waitfor_mob(self, name: str, window: float = None, max_dist: float = None):
        return self._waitfor_entity_impl(
            name, window, max_dist, mob_only=True, kind="mob"
        )

    def waitfor_mob_gone(self, name: str, max_dist: float = None, window: float = None):
        return self._waitfor_entity_gone_impl(
            name, max_dist, window, mob_only=True, kind="mob_gone"
        )

    def send_key(self, key: str, secs: float = 0.1):

        self._call(self._c.send_key(key=Keycode[key], seconds=secs))

    def interact(self, window: float = 1.5, await_dialog: bool = True):

        async def _():
            loop = asyncio.get_event_loop()

            async def _visible(path) -> bool:
                try:
                    return await is_visible_by_path(self._c, path)
                except Exception:
                    return False

            async def _wait_visible(path, timeout) -> bool:
                dl = loop.time() + timeout if timeout and timeout > 0 else None
                while True:
                    if self._stop.is_set():
                        return False
                    if await _visible(path):
                        return True
                    if dl is not None and loop.time() >= dl:
                        return False
                    await asyncio.sleep(0.03)

            # anything to interact with? short probe - no popup ⇒ bail, no cost
            if not await _wait_visible(npc_range_path, window):
                return False
            try:
                await self._c.send_key(Keycode.X, 0.1)
            except Exception:
                pass
            if not await_dialog:
                return True

            # a real X-press opens the dialog shortly after
            if not await _wait_visible(advance_dialog_path, window):
                return False

            # hold until the watcher finishes the conversation and we're free
            # again. no deadline - a long dialog should run to completion;
            # only `stop` breaks out
            while True:
                if self._stop.is_set():
                    return False
                try:
                    if await is_free(self._c):
                        return True
                except Exception:
                    return True
                await asyncio.sleep(0.03)

        return self._call(_())

    def teleport(self, x: float, y: float, z: float):

        async def _():
            await self._c.teleport(XYZ(x, y, z))

        self._call(_())

    def teleport_near(
        self,
        x: float,
        y: float,
        z: float,
        dist: float = 180.0,
        scan_radius: float = 1500.0,
    ):

        async def _():
            await _teleport_near(self._c, XYZ(x, y, z), dist, scan_radius)

        self._call(_())

    def go_through_gate(
        self,
        name: str,
        back_distance: float = 250.0,
        hold_seconds: float = 4.0,
        max_dist: float = None,
    ) -> bool:

        async def _():
            from src.nav.scraper import walk_through_gate

            return await walk_through_gate(
                self._c,
                name,
                back_distance=back_distance,
                hold_seconds=hold_seconds,
                max_dist=max_dist,
            )

        return self._call(_())

    def list_gates(self):

        async def _():
            from src.nav.scraper import enumerate_zone_gates

            return await enumerate_zone_gates(self._c)

        return self._table(self._call(_()))

    def reagent_nodes(self, name: str):

        async def _():
            zone = await self._c.zone_name()
            pts = await _zone_spawns().reagent_points(zone, name)
            return [{"x": p.x, "y": p.y, "z": p.z} for p in pts]

        return self._table(self._call(_()))

    def reagent_spawns(self):

        async def _():
            zone = await self._c.zone_name()
            data = await _zone_spawns().reagent_spawns(zone)
            return [
                {"name": name, "x": p.x, "y": p.y, "z": p.z}
                for name, pts in sorted(data.items())
                for p in pts
            ]

        return self._table(self._call(_()))

    def reagents_present(self, max_dist: float = 3000):

        async def _():
            return [
                {"name": nm, "x": loc.x, "y": loc.y, "z": loc.z}
                for nm, loc in await self._scan_reagents(max_dist)
            ]

        return self._table(self._call(_()))

    async def _scan_reagents(self, max_dist: float):
        table = await _zone_spawns()._load_reagent_ids()  # name -> id
        id_to_name = {tid: nm for nm, tid in table.items()}

        pos, entities = await self._world_scan()
        if pos is None:
            return []

        out = []
        for e in entities:
            try:
                # match the OBJECT TEMPLATE's id (offset-128 uint32), not the
                # entity's template_id_full (offset-96 uint64) - the latter is
                # the global instance id and never equals the manifest id
                tmpl = await e.object_template()
                if tmpl is None:
                    continue
                nm = id_to_name.get(await tmpl.template_id())
                if nm is None:
                    continue
                loc = await e.location()
                if pos.distance(loc) <= max_dist:
                    out.append((nm, loc))
            except Exception:
                continue
        return out

    def farm_reagent(self, name=None, amount=None, zones=None, hop_realms=True):
        # the {...} call form arrives as a single Lua table in `name`.
        if name is not None and not isinstance(name, str):
            opts = name
            name, amount, zones = opts["name"], opts["amount"], opts["zones"]
            hr = opts["hop_realms"]
            hop_realms = True if hr is None else bool(hr)

        SCAN, NEAR, SETTLE, POPUP, CAST = 2800.0, 160.0, 0.8, 2.5, 6.0
        # chunk vantages cover a whole streamed cell, so scan the full streaming
        # radius the nav grid was tiled against (calc_chunks' entity_distance) -
        # else reagents in a chunk's corner (up to ~3147u out, shared by 4
        # chunks) sit beyond SCAN from every vantage and never get harvested
        CHUNK_SCAN = 3200.0
        target = int(amount) if amount else None
        want = name.lower() if name else None
        zone_list = (
            list(zones.values())
            if hasattr(zones, "values")
            else list(zones)
            if zones
            else None
        )

        async def _():
            loop = asyncio.get_event_loop()
            sweep_zones = zone_list or [None]  # none ⇒ wherever we are now
            home = zone_list[0] if zone_list else None
            done = lambda: target is not None and collected >= target

            dead = set()  # (zone, cx, cy) NPC-squat cells, session-blacklisted
            cur_zone = ""  # set per zone; folded into the dead-cell key

            def dkey(x, y):
                return (cur_zone, int(x // 200), int(y // 200))

            def near(rows, nm, x, y):
                for rn, rx, ry in rows:
                    if rn == nm and (rx - x) ** 2 + (ry - y) ** 2 < NEAR * NEAR:
                        return True
                return False

            async def still_here(nm, x, y):
                for rn, loc in await self._scan_reagents(300):
                    if rn == nm and (loc.x - x) ** 2 + (loc.y - y) ** 2 < NEAR * NEAR:
                        return True
                return False

            async def press_x():
                end = loop.time() + POPUP
                while loop.time() < end:
                    if self._stop.is_set():
                        return False
                    try:
                        if await is_visible_by_path(self._c, npc_range_path):
                            await self._c.send_key(Keycode.X, 0.1)
                            return True
                    except Exception:
                        pass
                    await asyncio.sleep(0.03)
                return False

            async def harvest(x, y, z, nm):
                k = dkey(x, y)
                if k in dead:
                    return False
                await _teleport_with_retry(self._c, XYZ(x, y, z), self._stop)
                if not await press_x():
                    return False
                # stay put for the pickup cast; "collected" gated on seen-then-gone
                saw, end = False, loop.time() + CAST
                while loop.time() < end:
                    if self._stop.is_set():
                        return False
                    try:
                        if await is_visible_by_path(self._c, advance_dialog_path):
                            dead.add(k)
                            logger.info(f"[farm_reagent] NPC at {k} — blacklisted")
                            return False
                    except Exception:
                        pass
                    if await still_here(nm, x, y):
                        saw = True
                    elif saw:
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def load_nodes(zone_full):
                zs = _zone_spawns()
                spawns = await zs.reagent_spawns(zone_full)
                nodes = [
                    (nm, p)
                    for nm, pts in spawns.items()
                    for p in pts
                    if want is None or nm.lower() == want
                ]
                # "readable" keys off the *unfiltered* spawn table (cached from
                # the reagent_spawns call above), not the reagent-filtered result:
                # a zone that parsed but holds only non-reagent spawns is still
                # readable, so we skip it rather than chunk-sweep. only a truly
                # undecodable zone (empty spawn table) takes the chunk fallback
                readable = bool(await zs.zone_spawns(zone_full))
                return nodes, readable

            collected, pass_n = 0, 0
            while not self._stop.is_set() and not done():
                pass_n += 1
                picked = 0
                for zone in sweep_zones:
                    if self._stop.is_set() or done():
                        break
                    cur_zone = await self._c.zone_name()
                    if zone is not None and zone not in cur_zone:
                        logger.info(f"[farm_reagent] travelling to {zone!r}...")
                        try:
                            await to_zone([self._c], zone)
                        except Exception as exc:
                            logger.warning(
                                f"[farm_reagent] can't reach {zone!r}: {exc}"
                            )
                            continue
                        cur_zone = await self._c.zone_name()
                    nodes, readable = await load_nodes(cur_zone)
                    scan = SCAN
                    if nodes:
                        logger.info(
                            f"[farm_reagent] sweeping {cur_zone}: {len(nodes)} candidate node(s)"
                        )
                    elif readable:
                        # the zone's spawn data parsed and just doesn't list the
                        # wanted reagent - trust that and skip, rather than burn a
                        # whole-zone sweep on something we know isn't here
                        logger.info(
                            f"[farm_reagent] {name or 'reagent'} not in {cur_zone}'s spawn data"
                        )
                        continue
                    else:
                        scan = CHUNK_SCAN
                        # spawn data unreadable (some zones use a format the WAD
                        # reader can't decode). fall back to a whole-zone sweep:
                        # visit each chunk and grab whatever reagents stream in
                        # live. slower, but it farms the zone instead of skipping
                        chunks = await _load_zone_chunks(self._c)
                        nodes = [(None, c) for c in chunks]
                        if not nodes:
                            logger.info(
                                f"[farm_reagent] no reagent or nav data in {cur_zone}"
                            )
                            continue
                        logger.info(
                            f"[farm_reagent] {cur_zone} data unreadable; "
                            f"sweeping {len(nodes)} chunk(s) live"
                        )

                    got = []  # reagents handled this zone-sweep (dedup + node-skip)
                    for nm, p in nodes:
                        if self._stop.is_set() or done():
                            break
                        if dkey(p.x, p.y) in dead or near(got, nm, p.x, p.y):
                            continue
                        await _teleport_with_retry(self._c, p, self._stop)
                        present = await self._scan_reagents(scan)
                        end = loop.time() + SETTLE
                        while not present and loop.time() < end:
                            await asyncio.sleep(0.1)
                            present = await self._scan_reagents(scan)
                        for rn, loc in present:
                            if want is not None and rn.lower() != want:
                                continue
                            if not near(got, rn, loc.x, loc.y):
                                if await harvest(loc.x, loc.y, loc.z, rn):
                                    picked += 1
                                    collected += 1
                                    logger.debug(
                                        f"[farm_reagent] harvested {rn} "
                                        f"({collected}{'/' + str(target) if target else ''})"
                                    )
                                got.append((rn, loc.x, loc.y))
                            if done():
                                break

                tally = (
                    f"{collected}/{target}"
                    if target is not None
                    else f"{collected} total"
                )
                logger.info(f"[farm_reagent] pass {pass_n}: +{picked} ({tally})")
                if self._stop.is_set() or done():
                    break
                if hop_realms:
                    # close up: return home before hopping so each realm's sweep
                    # starts from the same place
                    if home is not None and home not in await self._c.zone_name():
                        logger.info(f"[farm_reagent] closing up to {home!r}...")
                        try:
                            await to_zone([self._c], home)
                        except Exception as exc:
                            logger.warning(
                                f"[farm_reagent] can't close up to {home!r}: {exc}"
                            )
                    logger.info("[farm_reagent] hopping realm")
                    await self._change_realm()
            return collected

        return self._call(_())

    def change_realm(self):
        return self._call(self._change_realm())

    async def _change_realm(self) -> bool:
        SETTING = ["WorldView", "DeckConfiguration", "SettingPage"]
        realms_tab = SETTING + ["TabWindow", "RealmsButton"]
        opts = SETTING + ["RealmOptions"]
        btn_right = opts + ["btnRealmRight"]
        go_to_realm = opts + ["btnGoToRealm"]
        panel = opts + ["wndRealmPanel"]

        # The rotation. index 0 is page 6's lone overflow realm (Wu) - a safe
        # first/restart hop, since a farmer is almost never parked there. then
        # pages 5..1 run emptiest→fullest. cursor walks 0→35 and wraps, so Wu
        # recurs once per cycle, never consecutively
        cycle = [(6, 0)]
        for pg in (5, 4, 3, 2, 1):
            cycle += [(pg, s) for s in (6, 5, 4, 3, 2, 1, 0)]
        cursor = getattr(self, "_realm_cursor", 0) % len(cycle)
        page, slot = cycle[cursor]
        self._realm_cursor = (cursor + 1) % len(cycle)
        realm_btn = panel + [f"btnRealm{slot}"]
        realm_name = realm_btn + [f"txtRealm{slot}Name"]

        loop = asyncio.get_event_loop()

        async def visible(path):
            try:
                return await is_visible_by_path(self._c, path)
            except Exception:
                return False

        async def text(path):
            try:
                w = await get_window_from_path(self._c.root_window, path)
                return (await w.maybe_text() or "") if w else ""
            except Exception:
                return ""

        async def wait_for(path, secs):
            end = loop.time() + secs
            while loop.time() < end:
                if await visible(path):
                    return True
                await asyncio.sleep(0.1)
            return False

        try:
            # open the settings menu and switch to the Realms tab
            await self._c.send_key(Keycode.ESC, 0.1)
            if not await wait_for(realms_tab, 5):
                logger.warning("[change_realm] settings didn't open — skipping hop")
                await self._c.send_key(Keycode.ESC, 0.1)
                return False
            await click_window_by_path(self._c, realms_tab)
            await wait_for(panel + ["btnRealm0"], 5)  # page 1 always has realms

            # open state is page 1/6 → click right (page-1) times to the target
            # page (stop early if the arrow vanishes, i.e. fewer pages exist).
            for _ in range(page - 1):
                if not await visible(btn_right):
                    break
                await click_window_by_path(self._c, btn_right)
                await asyncio.sleep(0.3)

            name = (await text(realm_name)).strip()
            if not name:
                logger.warning(
                    f"[change_realm] page {page} btnRealm{slot} empty — aborting hop"
                )
                await self._c.send_key(Keycode.ESC, 0.1)
                return False
            await click_window_by_path(self._c, realm_btn)
            await asyncio.sleep(0.2)
            await click_window_by_path(self._c, go_to_realm)
            logger.info(
                f"[change_realm] hopping to {name!r} (page {page}, slot {slot})"
            )

            # ride out the travel/reload
            await asyncio.sleep(1.0)
            end = loop.time() + 30
            while loop.time() < end:
                try:
                    if await is_free(self._c):
                        return True
                except Exception:
                    pass
                await asyncio.sleep(0.25)
            return True
        except Exception as exc:
            logger.warning(f"[change_realm] failed: {exc}")
            return False

    def reagent_debug(self, max_dist: float = 600):

        async def _():
            table = await _zone_spawns()._load_reagent_ids()  # name -> id
            ids = set(table.values())
            print(
                f"[rdbg] reagent-id table: {len(table)} ids; sample={list(table.items())[:6]}"
            )

            pos, entities = await self._world_scan()
            if pos is None:
                print("[rdbg] world scan empty (loading / zoning?)")
                return 0
            print(
                f"[rdbg] base entity list: {len(entities)} entities; "
                f"player=({pos.x:.0f},{pos.y:.0f},{pos.z:.0f})"
            )

            seen = []
            for e in entities:
                try:
                    loc = await e.location()
                    dist = pos.distance(loc)
                    if dist > max_dist:
                        continue
                    full = await e.template_id_full()
                    try:
                        tmpl = await e.object_template()
                        obj_tid = (await tmpl.template_id()) if tmpl else None
                    except Exception:
                        obj_tid = "<err>"
                    obj = await e.object_name() or ""
                    disp = await e.display_name() or ""
                    seen.append((dist, full, obj_tid, obj, disp))
                except Exception:
                    continue

            seen.sort(key=lambda r: r[0])
            for dist, full, obj_tid, obj, disp in seen[:40]:
                flag = ""
                if full in ids:
                    flag += " FULL_MATCH"
                if obj_tid in ids:
                    flag += " OBJ_MATCH"
                print(
                    f"[rdbg] d={dist:6.0f} full={full} obj_tid={obj_tid} "
                    f"obj={obj!r} disp={disp!r}{flag}"
                )
            print(
                f"[rdbg] {len(seen)} entities within {max_dist} (showing closest "
                f"{min(40, len(seen))})"
            )
            return len(seen)

        return self._call(_())

    def zone_chunks(self):

        async def _():
            chunks = await _load_zone_chunks(self._c)
            return [{"x": c.x, "y": c.y, "z": c.z} for c in chunks]

        return self._table(self._call(_()))

    def navigate(self, x: float, y: float, z: float):

        self._call(navmap_tp(self._c, XYZ(x, y, z)))

    def to_zone(self, name: str):

        self._call(to_zone([self._c], name))

    # ── quest tracking ───────────────────────────────────────────────────
    def quest_position(self):

        async def _():
            xyz = await self._c.quest_position.position()
            return [xyz.x, xyz.y, xyz.z]

        return self._table(self._call(_()))

    def tp_to_quest(self):
        self._call(run_tp_to_quest(self._c, self._stop))

    async def _resolve_lang(self, lang_key: str | None) -> str:
        if not lang_key:
            return ""
        try:
            name = await self._c.cache_handler.get_langcode_name(lang_key)
            return name or lang_key
        except Exception:
            return lang_key

    async def _active_quest_goal(self):
        return await _active_quest_goal_of(self._c)

    def current_quest_name(self) -> str:

        async def _():
            quest, _ = await self._active_quest_goal()
            if quest is None:
                return ""
            try:
                key = await quest.name_lang_key()
            except Exception:
                return ""
            return await self._resolve_lang(key)

        return self._call(_())

    async def _quest_destination_zone(self) -> str:
        return await quest_destination_zone_of(self._c)

    def quest_destination_zone(self) -> str:
        return self._call(self._quest_destination_zone())

    def quest_in_zone(self, needle: str, settle: float = 0.5) -> bool:
        if not needle:
            return False
        n = needle.lower()

        async def _():
            async def hit() -> bool:
                dz = await self._quest_destination_zone()
                return n in (dz or "").lower()

            if await hit():
                return True
            if settle and settle > 0:
                deadline = asyncio.get_event_loop().time() + settle
                while asyncio.get_event_loop().time() < deadline:
                    if self._stop.is_set():
                        return False
                    await asyncio.sleep(0.1)
                    if await hit():
                        return True
            return False

        return self._call(_())

    async def _quest_helper_goal_text(self) -> str:
        return await _quest_helper_goal_text_of(self._c)

    def current_goal_name(self) -> str:
        return self._call(self._quest_helper_goal_text())

    def tracking_quest(self, needle: str) -> bool:
        if not needle:
            return False

        async def _():
            quest, _ = await self._active_quest_goal()
            if quest is None:
                return False
            try:
                key = await quest.name_lang_key()
            except Exception:
                return False
            text = await self._resolve_lang(key)
            return needle.lower() in (text or "").lower()

        return self._call(_())

    def tracking_goal(self, needle: str) -> bool:
        if not needle:
            return False

        async def _():
            text = await self._quest_helper_goal_text()
            return needle.lower() in text.lower()

        return self._call(_())

    def dump_quest(self):

        async def _():
            out = {
                "quest_id": None,
                "goal_id": None,
                "quest_name": "",
                "active_goal_name": "",
                "goal_in_map": False,
                "goals": [],
            }
            try:
                qid = await self._c.quest_id()
                gid = await self._c.goal_id()
            except Exception as e:
                out["error"] = f"id read failed: {type(e).__name__}: {e}"
                return out
            out["quest_id"], out["goal_id"] = qid, gid
            if not qid:
                out["error"] = "no active quest"
                return out
            try:
                mgr = await self._c.quest_manager()
                quests = await mgr.quest_data()
            except Exception as e:
                out["error"] = f"quest_data failed: {type(e).__name__}: {e}"
                return out
            quest = quests.get(qid)
            if quest is None:
                out["error"] = "active quest_id not in quest_data map"
                return out
            try:
                out["quest_name"] = await self._resolve_lang(
                    await quest.name_lang_key()
                )
            except Exception:
                pass
            try:
                goals = await quest.goal_data()
            except Exception as e:
                out["error"] = f"goal_data failed: {type(e).__name__}: {e}"
                return out
            out["goal_in_map"] = gid in goals
            for g_id, g in goals.items():
                entry = {"id": g_id, "name": "", "type": "", "dest_zone": ""}
                try:
                    entry["name"] = await self._resolve_lang(await g.name_lang_key())
                except Exception:
                    pass
                try:
                    entry["type"] = str(await g.goal_type())
                except Exception:
                    pass
                try:
                    entry["dest_zone"] = await g.goal_destination_zone()
                except Exception:
                    pass
                if g_id == gid:
                    out["active_goal_name"] = entry["name"]
                out["goals"].append(entry)
            return out

        return self._table(self._call(_()))

    def friend_tp(self, friend_name: str) -> bool:
        from wizwalker.extensions.scripting.utils import (
            _cycle_to_online_friends,
            _friend_list_entry,
            _maybe_get_named_window,
        )

        async def _():
            c = self._c

            # snapshot pre-state. the only honest success signal in the
            # modern UI is "did we actually teleport?", so we compare
            # zone+position before and after
            try:
                pre_pos = await c.body.position()
                pre_zone = await c.zone_name()
            except Exception:
                pre_pos, pre_zone = None, None

            # lock the zone baseline before the tp lands. if friend_tp crosses
            # zones, baseline = pre_zone so a later waitfor_zone_change returns
            # right away. if it lands in the same zone there's no change to see,
            # so _finalize_zone_baseline (end of this fn) writes a sentinel that
            # no zone matches, making that wait a no-op
            if pre_zone is not None:
                self._last_seen_zone = pre_zone

            # movement threshold. the old 500u gate false-negatived when the
            # friend stood within 500u of the caller (tp landed but _moved said
            # it failed). a standing player doesn't drift, so a few units of
            # movement is already real
            _MOVE_THRESHOLD = 75.0

            async def _moved() -> bool:
                # a loading screen during the poll window is itself a
                # teleport signal - cross-instance / cross-zone friend tps
                # always flash one, and the load can clear before our next
                # zone_name sample. checking is_loading first catches that
                # race
                try:
                    if await c.is_loading():
                        return True
                except Exception:
                    pass
                try:
                    z = await c.zone_name()
                    p = await c.body.position()
                except Exception:
                    return False
                if pre_zone is not None and z != pre_zone:
                    return True
                if pre_pos is not None and p is not None:
                    dx = p.x - pre_pos.x
                    dy = p.y - pre_pos.y
                    dz = p.z - pre_pos.z
                    if (dx * dx + dy * dy + dz * dz) > (
                        _MOVE_THRESHOLD * _MOVE_THRESHOLD
                    ):
                        return True
                return False

            async def _finalize_zone_baseline():
                try:
                    post_zone = await c.zone_name()
                except Exception:
                    post_zone = None
                if pre_zone is None:
                    # can't reason about it - leave whatever's already there
                    return
                if post_zone is None or post_zone == pre_zone:
                    # same zone (or unreadable). use a sentinel so
                    # waitfor_zone_change sees current_zone != baseline
                    # on its first poll and returns immediately
                    self._last_seen_zone = "<friend_tp-no-zone-change>"
                else:
                    # zone crossed. keep baseline at pre_zone so the
                    # change is visible to waitfor_zone_change
                    self._last_seen_zone = pre_zone

            def _parse_page(text: str) -> tuple[int, int]:
                try:
                    cur, total = map(
                        int,
                        (text or "1 / 1")
                        .replace("<center>", "")
                        .replace("</center>", "")
                        .replace(" ", "")
                        .split("/"),
                    )
                    return cur, total
                except Exception:
                    return 1, 1

            try:
                async with c.mouse_handler:
                    # ── 1. open friends list ──────────────────────────
                    friends_window = None
                    try:
                        friends_window = await _maybe_get_named_window(
                            c.root_window, "NewFriendsListWindow", retries=1
                        )
                    except ValueError:
                        friends_window = None
                    if friends_window is None or not await friends_window.is_visible():
                        btn = await _maybe_get_named_window(c.root_window, "btnFriends")
                        await c.mouse_handler.click_window(btn)
                        # poll for the list to render instead of a flat 0.4s
                        # wait - opens the instant the UI is ready. ceiling
                        # (2s) matches the old retry path's worst case
                        friends_window = None
                        deadline = asyncio.get_event_loop().time() + 2.0
                        while asyncio.get_event_loop().time() < deadline:
                            try:
                                friends_window = await _maybe_get_named_window(
                                    c.root_window,
                                    "NewFriendsListWindow",
                                    retries=0,
                                )
                            except ValueError:
                                friends_window = None
                            if friends_window is not None and (
                                await friends_window.is_visible()
                            ):
                                break
                            friends_window = None
                            await asyncio.sleep(0.1)
                        if friends_window is None:
                            friends_window = await _maybe_get_named_window(
                                c.root_window, "NewFriendsListWindow"
                            )

                    # ── 2. filter to "Online Friends" ─────────────────
                    await _cycle_to_online_friends(c, friends_window)

                    # ── 3. find friend across pages ───────────────────
                    list_friends = await _maybe_get_named_window(
                        friends_window, "listFriends"
                    )
                    page_w = await _maybe_get_named_window(friends_window, "PageNumber")
                    arrow_down = await _maybe_get_named_window(
                        friends_window, "btnArrowDown"
                    )

                    # rewind to page 1 so iteration covers everyone
                    cur_p, total_p = _parse_page(await page_w.maybe_text())
                    safety = total_p + 2
                    while cur_p > 1 and safety > 0:
                        await c.mouse_handler.click_window(arrow_down)
                        await asyncio.sleep(0.25)
                        cur_p, total_p = _parse_page(await page_w.maybe_text())
                        safety -= 1

                    # the modern UI fires the teleport on a *double*-click of
                    # the friend row - a single click only selects it. mirror
                    # _click_on_friend's coordinate math, then click twice
                    # inside the OS double-click window
                    async def _double_click_friend(idx: int) -> None:
                        rect = await list_friends.scale_to_client()
                        ui_scale = await c.render_context.ui_scale()
                        cx = rect.center()[0]
                        cy = int(rect.y1 + ((idx % 10) * 30) * ui_scale + 15 * ui_scale)
                        await c.mouse_handler.click(cx, cy)
                        await asyncio.sleep(0.12)
                        await c.mouse_handler.click(cx, cy)
                        await asyncio.sleep(1)

                    target = friend_name.lower()
                    clicked = False
                    for _page in range(total_p):
                        text = await list_friends.maybe_text() or ""
                        for idx, entry in enumerate(_friend_list_entry.finditer(text)):
                            if entry.group("name").lower() == target:
                                await _double_click_friend(idx)
                                clicked = True
                                break
                        if clicked:
                            break
                        await c.mouse_handler.click_window(arrow_down)
                        await asyncio.sleep(0.35)

                    if not clicked:
                        raise ValueError(f"{friend_name!r} not found in online friends")

                    # ── 4. confirm if a modal appears, else just wait ─
                    # modern UI usually skips the confirmation, but some
                    # destinations (cross-instance, busy friend) still
                    # show one. 1.5s budget - if no modal, the row-click
                    # already fired the teleport
                    modal = None
                    for _ in range(6):
                        try:
                            candidate = await _maybe_get_named_window(
                                c.root_window,
                                "MessageBoxModalWindow",
                                retries=0,
                            )
                            if candidate and await candidate.is_visible():
                                modal = candidate
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.25)

                    if modal is not None:
                        try:
                            yes = await _maybe_get_named_window(modal, "centerButton")
                            await c.mouse_handler.click_window(yes)
                            await asyncio.sleep(1.0)
                        except Exception:
                            pass

                # ── 5. verify observable outcome ──────────────────────
                # poll for up to 15s: the teleport kicks off a zone load that
                # can take several seconds (cross-instance / dungeon entry), so
                # position/zone don't update the instant the click lands
                deadline = asyncio.get_event_loop().time() + 15.0
                while asyncio.get_event_loop().time() < deadline:
                    if await _moved():
                        await _finalize_zone_baseline()
                        return True
                    await asyncio.sleep(0.25)

                logger.warning(
                    f"[lua] {c.title}: friend_tp({friend_name!r}): "
                    "click sequence completed but no movement detected"
                )
                await _finalize_zone_baseline()
                return False

            except Exception as e:
                # last-chance check: maybe the teleport fired before the
                # exception we caught, in which case the warning would be
                # noise. same motion test.
                if await _moved():
                    await _finalize_zone_baseline()
                    return True
                logger.warning(
                    f"[lua] {c.title}: friend_tp({friend_name!r}) failed: {e}"
                )
                await _finalize_zone_baseline()
                return False

        return self._call(_())

    def click_window(self, path):

        path_list = list(path.values()) if hasattr(path, "values") else list(path)

        self._call(click_window_by_path(self._c, path_list))

    def window_text(self, path) -> str:

        path_list = list(path.values()) if hasattr(path, "values") else list(path)

        async def _():

            w = await get_window_from_path(self._c.root_window, path_list)

            return (await w.maybe_text() or "") if w else ""

        return self._call(_())

    def window_visible(self, path) -> bool:

        path_list = list(path.values()) if hasattr(path, "values") else list(path)

        return self._call(is_visible_by_path(self._c, path_list))

    def dump_windows(self, max_depth: int = 4, only_visible: bool = False):
        from wizwalker.memory import WindowFlags

        async def _():
            printed = 0

            async def _walk(w, depth):
                nonlocal printed
                if depth > max_depth:
                    return
                try:
                    name = await w.name() or "<anon>"
                    flags = await w.flags()
                    visible = WindowFlags.visible in flags
                except Exception:
                    return
                if only_visible and not visible:
                    return
                vis_tag = "v" if visible else " "
                print(f"  {vis_tag} {'  ' * depth}{name}")
                printed += 1
                try:
                    for c in await w.children():
                        await _walk(c, depth + 1)
                except Exception:
                    return

            try:
                await _walk(self._c.root_window, 0)
            except Exception as e:
                print(f"dump_windows: {e}")
            return printed

        return self._call(_())

    async def _world_scan(self):
        try:
            pos = await self._c.body.position()
            entities = await self._c.get_base_entity_list()
            return pos, (entities or [])
        except Exception:
            return None, []

    def boss_nearby(self, max_dist: float = 5000) -> bool:

        async def _():

            pos, entities = await self._world_scan()

            for e in entities:
                try:
                    if pos.distance(await e.location()) > max_dist:
                        continue

                    # fetch_npc_behavior_template() returns None for non-NPC
                    # entities - that's our fast skip. the previous
                    # read_type_name() gate compared against the C++ class
                    # name (RTTI), not the behavior_name string, so it
                    # never matched and boss_nearby always returned False
                    npc = await e.fetch_npc_behavior_template()
                    if not npc:
                        continue

                    # check both the bool flag *and* the mob_title enum
                    # (NpcBehaviorTemplateTitleType.boss == 3). some templates
                    # only set one or the other reliably, so OR them
                    if await npc.boss_mob():
                        return True
                    try:
                        title = await npc.mob_title()
                        if title is not None and getattr(title, "value", None) == 3:
                            return True
                    except Exception:
                        pass

                except Exception:
                    continue

            return False

        return self._call(_())

    def dump_entities(self, max_dist: float = 5000, needle: str = None):

        async def _():
            pos, entities = await self._world_scan()
            n = needle.lower() if needle else None
            count = 0

            for e in entities:
                try:
                    dist = pos.distance(await e.location())
                    if dist > max_dist:
                        continue

                    obj = await e.object_name() or ""
                    disp = await e.display_name() or ""
                    try:
                        tmpl = await e.object_template()
                        tdisp = (await tmpl.display_name()) if tmpl else ""
                    except Exception:
                        tdisp = "<err>"

                    is_mob = "?"
                    try:
                        b = await e.search_behavior_by_name("NPCBehavior")
                        if b is None:
                            is_mob = "no_npc_behavior"
                        else:
                            is_mob = (
                                "yes"
                                if await b.read_value_from_offset(288, Primitive.bool)
                                else "no"
                            )
                    except Exception:
                        is_mob = "<err>"

                    tag = ""
                    if n is not None:
                        hit = (
                            n in obj.lower()
                            or n in disp.lower()
                            or n in (tdisp or "").lower()
                        )
                        tag = "MATCH    " if hit else "no-match "

                    logger.info(
                        f"[dump_entities] {tag}d={dist:>6.0f}  "
                        f"obj={obj!r}  disp={disp!r}  tmpl_disp={tdisp!r}  is_mob={is_mob}"
                    )
                    count += 1

                except Exception as exc:
                    logger.info(f"[dump_entities] entity error: {exc}")
                    continue

            logger.info(f"[dump_entities] {count} entities within {max_dist}")
            return count

        return self._call(_())

    def dump_npcs(self, max_dist: float = 5000):

        async def _():

            pos, entities = await self._world_scan()
            count = 0

            for e in entities:
                try:
                    dist = pos.distance(await e.location())
                    if dist > max_dist:
                        continue

                    obj_name = await e.object_name() or "?"
                    try:
                        tmpl = await e.object_template()
                        disp = (await tmpl.display_name()) if tmpl else ""
                    except Exception:
                        disp = "?"

                    npc = await e.fetch_npc_behavior_template()
                    if not npc:
                        logger.info(
                            f"[dump_npcs] d={dist:.0f} obj={obj_name!r} "
                            f"disp={disp!r} no_npc_template"
                        )
                        count += 1
                        continue

                    try:
                        boss_flag = await npc.boss_mob()
                    except Exception:
                        boss_flag = "<err>"
                    try:
                        title = await npc.mob_title()
                        title_str = (
                            str(title).split(".")[-1] if title is not None else "?"
                        )
                        title_val = getattr(title, "value", None)
                    except Exception:
                        title_str = "<err>"
                        title_val = None
                    try:
                        school = await npc.school_of_focus()
                    except Exception:
                        school = "<err>"

                    # mirror boss_nearby's verdict: boss_mob OR mob_title==3
                    is_boss = (boss_flag is True) or (title_val == 3)

                    logger.info(
                        f"[dump_npcs] d={dist:.0f} obj={obj_name!r} "
                        f"disp={disp!r} is_boss={is_boss} title={title_str} "
                        f"boss_mob={boss_flag} school={school!r}"
                    )
                    count += 1

                except Exception as exc:
                    logger.info(f"[dump_npcs] entity error: {exc}")
                    continue

            logger.info(f"[dump_npcs] total entities within {max_dist}: {count}")
            return count

        return self._call(_())

    def entities(self, max_dist: float = None):

        async def _():

            pos, entities = await self._world_scan()

            result = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    result.append(LuaMob(e, dist, self._call, self._c, self._table))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def mobs(self, max_dist: float = None):

        async def _():

            pos, entities = await self._world_scan()

            result = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    if not await is_mob(e):
                        continue

                    result.append(LuaMob(e, dist, self._call, self._c, self._table))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def nearest_named(self, name: str, max_dist: float = None):

        async def _():

            needle = name.lower()

            pos, entities = await self._world_scan()

            best_e, best_dist = None, float("inf")

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    if dist >= best_dist:
                        continue

                    obj = (await e.object_name() or "").lower()

                    disp = (await e.display_name() or "").lower()

                    if needle in obj or needle in disp:
                        best_dist, best_e = dist, e

                except Exception:
                    continue

            return (
                LuaMob(best_e, best_dist, self._call, self._c, self._table)
                if best_e
                else None
            )

        return self._call(_())

    def find_mob(self, name: str, max_dist: float = None):

        async def _():

            needle = name.lower()

            pos, entities = await self._world_scan()

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    obj = (await e.object_name() or "").lower()

                    disp = (await e.display_name() or "").lower()

                    if needle in obj or needle in disp:
                        return LuaMob(e, dist, self._call, self._c, self._table)

                except Exception:
                    continue

            return None

        return self._call(_())

    def find_mobs(self, name: str, max_dist: float = None):

        async def _():

            needle = name.lower()

            pos, entities = await self._world_scan()

            result = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    obj = (await e.object_name() or "").lower()

                    disp = (await e.display_name() or "").lower()

                    if needle in obj or needle in disp:
                        result.append(LuaMob(e, dist, self._call, self._c, self._table))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def find_mobs_sorted(self, name: str, max_dist: float = None):

        async def _():

            needle = name.lower()

            pos, entities = await self._world_scan()

            scored = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    obj = (await e.object_name() or "").lower()

                    disp = (await e.display_name() or "").lower()

                    if needle in obj or needle in disp:
                        scored.append((dist, e))

                except Exception:
                    continue

            scored.sort(key=lambda pair: pair[0])

            return [LuaMob(e, d, self._call, self._c, self._table) for d, e in scored]

        return self._table(self._call(_()))

    def nearest_mob(self, max_dist: float = None):

        async def _():

            pos, entities = await self._world_scan()

            best_e, best_dist = None, float("inf")

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    if dist < best_dist:
                        best_dist, best_e = dist, e

                except Exception:
                    continue

            return (
                LuaMob(best_e, best_dist, self._call, self._c, self._table)
                if best_e
                else None
            )

        return self._call(_())

    def nearest_boss(self, max_dist: float = None):

        async def _():

            pos, entities = await self._world_scan()

            best_e, best_dist = None, float("inf")

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    npc = await e.fetch_npc_behavior_template()
                    if not npc:
                        continue

                    is_boss = False
                    if await npc.boss_mob():
                        is_boss = True
                    else:
                        try:
                            title = await npc.mob_title()
                            if title is not None and getattr(title, "value", None) == 3:
                                is_boss = True
                        except Exception:
                            pass

                    if is_boss and dist < best_dist:
                        best_dist, best_e = dist, e

                except Exception:
                    continue

            return (
                LuaMob(best_e, best_dist, self._call, self._c, self._table)
                if best_e
                else None
            )

        return self._call(_())

    def mob_by_id(self, global_id: int):

        async def _():

            pos, entities = await self._world_scan()

            for e in entities:
                try:
                    if await e.global_id_full() == int(global_id):
                        return LuaMob(
                            e,
                            pos.distance(await e.location()),
                            self._call,
                            self._c,
                            self._table,
                        )

                except Exception:
                    continue

            return None

        return self._call(_())

    def mob_by_template(self, template_id: int):

        async def _():

            pos, entities = await self._world_scan()

            for e in entities:
                try:
                    if await e.template_id_full() == int(template_id):
                        return LuaMob(
                            e,
                            pos.distance(await e.location()),
                            self._call,
                            self._c,
                            self._table,
                        )

                except Exception:
                    continue

            return None

        return self._call(_())

    def has_mob(self, name: str, max_dist: float = None) -> bool:

        return self.find_mob(name, max_dist) is not None

    def mobs_by_school(self, school: str, max_dist: float = None):

        async def _():

            target = school.lower()

            pos, entities = await self._world_scan()

            result = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    npc = await e.fetch_npc_behavior_template()
                    if npc and target in (await npc.school_of_focus() or "").lower():
                        result.append(LuaMob(e, dist, self._call, self._c, self._table))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def mobs_by_title(self, title: str, max_dist: float = None):

        async def _():

            target = title.lower()

            pos, entities = await self._world_scan()

            result = []

            for e in entities:
                try:
                    dist = pos.distance(await e.location())

                    if max_dist is not None and dist > max_dist:
                        continue

                    npc = await e.fetch_npc_behavior_template()
                    if npc:
                        t = await npc.mob_title()
                        t_str = (
                            str(t).split(".")[-1].lower() if t is not None else "normal"
                        )

                        if target in t_str:
                            result.append(
                                LuaMob(e, dist, self._call, self._c, self._table)
                            )

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def combatants(self):

        async def _():

            combat = NativeCombat(self._c, self._c.combat_config)

            result = []

            for m in await combat.get_members():
                try:
                    result.append(LuaCombatant(m, self._call))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def enemies(self):

        async def _():

            combat = NativeCombat(self._c, self._c.combat_config)

            result = []

            for m in await combat.get_members():
                try:
                    if await m.is_monster():
                        result.append(LuaCombatant(m, self._call))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    def allies(self):

        async def _():

            combat = NativeCombat(self._c, self._c.combat_config)

            result = []

            for m in await combat.get_members():
                try:
                    if await m.is_player():
                        result.append(LuaCombatant(m, self._call))

                except Exception:
                    continue

            return result

        return self._table(self._call(_()))

    # school focus
    # read/write the self participant's primary magic school. writing swaps the
    # school they're treated as (power-pip conversion, school-locked spells, UI).
    # local memory poke only, the server keeps its own view. handy for testing
    # school-specific playstyle branches without rerolling
    async def _self_participant(self):
        members = await NativeCombat(self._c, self._c.combat_config).get_members()
        for m in members:
            try:
                if await m.is_player():
                    return await m.get_participant()
            except Exception:
                continue
        return None

    def focus_school(self) -> str:

        async def _():
            part = await self._self_participant()
            if part is None:
                return "Unknown"
            sid = await part.primary_magic_school_id()
            return school_to_str.get(sid, "Unknown")

        return self._call(_())

    def set_focus_school(self, school: str):
        # school_id_to_names is keyed by capitalised name ("Fire", "Ice", ...).
        # build a case-insensitive lookup on the way in instead of mutating
        # the upstream dict
        key = (school or "").strip().lower()
        match = next(
            (sid for name, sid in school_id_to_names.items() if name.lower() == key),
            None,
        )
        if match is None:
            valid = sorted(name.lower() for name in school_id_to_names)
            raise ScriptError(
                f"set_focus_school: unknown school {school!r} (valid: {valid})"
            )

        async def _():
            part = await self._self_participant()
            if part is None:
                return
            await part.write_primary_magic_school_id(int(match))

        self._call(_())

    # school pip assignment (UI click path)
    # the real way to set a flexible pip's school: click SchoolPipPanel during
    # planning. goes through the server (unlike memory pokes) so the pip can
    # actually be spent. click sequence lives in src.utils.assign_school_pip so
    # the playstyle `pip: <school>` directive shares it
    _SCHOOL_PIP_BUTTONS = (
        "Fire",
        "Ice",
        "Storm",
        "Myth",
        "Life",
        "Death",
        "Balance",
    )

    def set_pip_school(self, school: str):
        key = (school or "").strip().lower()
        if not any(s.lower() == key for s in self._SCHOOL_PIP_BUTTONS):
            raise ScriptError(
                f"set_pip_school: unknown school {school!r} "
                f"(expected one of {self._SCHOOL_PIP_BUTTONS})"
            )
        self._call(assign_school_pip(self._c, key))

    def load_playstyle(self, config):
        from src.combat.config import parse_lua_table, CombatConfig

        if isinstance(config, str):
            cfg = parse_playstyle(config)
        elif hasattr(config, "items"):
            cfg = parse_lua_table(config)
        elif isinstance(config, CombatConfig):
            cfg = config
        else:
            cfg = parse_playstyle(str(config))

        self._c._playstyle_config = cfg

        # only write combat_config when combat is already armed (it's non-None).
        # both the GUI task and the lua watcher gate engagement on combat_config
        # alone, so an unconditional write here would silently arm combat and
        # break toggles. canonical order is load_playstyle() before
        # enable_combat(), but enable_combat snapshots the config so either
        # order works on a fresh client
        if self._c.combat_config is not None:
            self._c.combat_config = cfg
            active = getattr(self._c, "_active_combat", None)
            if active is not None:
                active._config = cfg
                active._reset_round_state()

    def exclude_from_questing(self, excluded: bool = True):
        self._c.quest_excluded = bool(excluded)

    async def _teardown_combat(self):
        client = self._c
        client.combat_config = None
        active = getattr(client, "_active_combat", None)
        if active is not None:
            active._config = None
            try:
                active.cancel_combat()
            except Exception:
                pass

        task = getattr(client, "_lua_combat_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        client._lua_combat_task = None

        _push_combat_gui_status("Disabled", getattr(client, "title", None))

    def disable_combat(self):
        if self._bridge is not None:
            self._bridge.unregister_toggle_cleanup((id(self._c), "combat"))
        try:
            self._call(self._teardown_combat())
        except Exception:
            pass

    def enable_combat(self):
        cfg = getattr(self._c, "_playstyle_config", None)
        self._c.combat_config = cfg
        active = getattr(self._c, "_active_combat", None)
        if active is not None:
            active._config = cfg
            if cfg is not None:
                active._reset_round_state()

        client = self._c
        stop = self._stop

        existing = getattr(client, "_lua_combat_task", None)
        if existing is None or existing.done():

            async def _watcher():
                from wizwalker import Keycode

                while not stop.is_set():
                    try:
                        if not await client.in_battle():
                            await asyncio.sleep(1)
                            continue
                        if not getattr(client, "combat_config", None):
                            await asyncio.sleep(1)
                            continue
                        # yield to anything already handling combat - the
                        # GUI's combat_loop, Quester, or another script
                        # that called waitfor_battle_finish()
                        if getattr(client, "_active_combat", None) is not None:
                            await asyncio.sleep(0.5)
                            continue
                        logger.info(
                            f"client {client.title} in combat, handling combat."
                        )
                        battle = NativeCombat(
                            client, client.combat_config, cast_time=0.25
                        )
                        try:
                            await battle.wait_for_combat()
                        finally:
                            try:
                                await client.mouse_handler.release_mouse()
                            except Exception:
                                pass
                            try:
                                await client.send_key(Keycode.ESCAPE)
                            except Exception:
                                pass
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # don't let a transient memory-read failure kill
                        # the watcher - sleep and retry on next iteration
                        await asyncio.sleep(1)

            # schedule on the bridge's event loop. enable_combat runs on
            # the Lua thread, so asyncio.create_task() here would target
            # the wrong loop. _call hops over to the loop's thread.
            async def _spawn():
                return asyncio.get_event_loop().create_task(_watcher())

            try:
                client._lua_combat_task = self._call(_spawn())
            except Exception:
                client._lua_combat_task = None

        _push_combat_gui_status("Enabled", getattr(client, "title", None))

        # auto-combat outlives the watcher only until the script ends - the
        # bridge tears it back down then unless the script disabled it first
        if self._bridge is not None:
            self._bridge.register_toggle_cleanup(
                (id(client), "combat"), self._teardown_combat
            )

    # ── auto-dialog ───────────────────────────────────────────────────
    async def _teardown_dialog(self):
        client = self._c
        task = getattr(client, "_lua_dialog_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        client._lua_dialog_task = None

        _push_dialog_gui_status("Disabled", getattr(client, "title", None))

    def disable_dialog(self):
        if self._bridge is not None:
            self._bridge.unregister_toggle_cleanup((id(self._c), "dialog"))
        try:
            self._call(self._teardown_dialog())
        except Exception:
            pass

    def enable_dialog(self):
        client = self._c
        stop = self._stop

        existing = getattr(client, "_lua_dialog_task", None)
        if existing is None or existing.done():

            async def _watcher():
                from wizwalker import Keycode

                while not stop.is_set():
                    try:
                        if await is_visible_by_path(client, advance_dialog_path):
                            try:
                                await client.send_key(Keycode.SPACEBAR)
                            except Exception:
                                pass
                        await asyncio.sleep(0.03)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # memory read can race a zone change; keep watching
                        await asyncio.sleep(0.1)

            # schedule on the bridge's event loop, same as enable_combat
            async def _spawn():
                return asyncio.get_event_loop().create_task(_watcher())

            try:
                client._lua_dialog_task = self._call(_spawn())
            except Exception:
                client._lua_dialog_task = None

        _push_dialog_gui_status("Enabled", getattr(client, "title", None))

        # auto-dialog is torn back down when the script ends unless the
        # script disabled it first
        if self._bridge is not None:
            self._bridge.register_toggle_cleanup(
                (id(client), "dialog"), self._teardown_dialog
            )

    # ------------------------------------------------------------------
    # packet-level combat actions (no UI interaction)
    # all require the client to be in combat. hand_index is 0-based,
    # left-to-right. target is a subcircle index (0-7) or 0 for "self".
    # ------------------------------------------------------------------
    def cast_spell(self, hand_index: int, target: int = 0):
        return self._call(self._c.send_combat_spell(int(hand_index), int(target)))

    def pass_turn(self):
        return self._call(self._c.send_combat_pass())

    def flee(self):
        return self._call(self._c.send_combat_flee())

    def discard_card(self, hand_index: int):
        return self._call(self._c.send_combat_discard(int(hand_index)))

    def enchant_card(self, enchant_index: int, target_index: int):
        return self._call(
            self._c.send_combat_enchant(int(enchant_index), int(target_index))
        )

    def fuse_cards(
        self, primary_index: int, secondary_index: int, fused_spell_id: int = 0
    ):
        return self._call(
            self._c.send_combat_fusion(
                int(primary_index), int(secondary_index), int(fused_spell_id)
            )
        )

    def draw_tc(self):
        return self._call(self._c.send_combat_draw())

    def pet_willcast(self, spell_name: str, target: int):
        return self._call(self._c.send_pet_willcast(str(spell_name), int(target)))

    def _headers(self, headers, extra: dict = None) -> dict:
        h = dict(headers.items()) if headers is not None else {}
        if extra:
            h = {**extra, **h}
        return h

    def http_get(self, url: str, headers=None) -> str:
        import requests

        r = requests.get(url, headers=self._headers(headers), timeout=10)
        return r.text

    def http_post(self, url: str, body: str = "", headers=None) -> str:
        import requests

        r = requests.post(
            url,
            data=body.encode(),
            headers=self._headers(headers, {"Content-Type": "application/json"}),
            timeout=10,
        )
        return r.text

    def http_put(self, url: str, body: str = "", headers=None) -> str:
        import requests

        r = requests.put(
            url,
            data=body.encode(),
            headers=self._headers(headers, {"Content-Type": "application/json"}),
            timeout=10,
        )
        return r.text

    def http_patch(self, url: str, body: str = "", headers=None) -> str:
        import requests

        r = requests.patch(
            url,
            data=body.encode(),
            headers=self._headers(headers, {"Content-Type": "application/json"}),
            timeout=10,
        )
        return r.text

    def http_delete(self, url: str, headers=None) -> str:
        import requests

        r = requests.delete(url, headers=self._headers(headers), timeout=10)
        return r.text

    def recent_drops(self, n: int = 25):
        raw = getattr(self._c, "latest_drops", "") or ""
        items = [d for d in raw.split("\n") if d]
        return self._table(items[-int(n) :])

    def got_drop(self, name: str) -> bool:
        raw = getattr(self._c, "latest_drops", "") or ""
        needle = name.lower()
        return any(needle in d.lower() for d in raw.split("\n") if d)

    # ── inventory ────────────────────────────────────────────────────────────

    def backpack(self):

        async def _():
            result = []
            try:
                inv = await self._c.client_object.try_get_inventory_behavior()
                if inv:
                    for item in await inv.item_list():
                        result.append(LuaItem(item, self._call, self._table))
            except Exception:
                pass
            return result

        return self._table(self._call(_()))

    def equipped(self):

        async def _():
            result = []
            try:
                eq = await self._c.client_object.try_get_equipment_behavior()
                if eq:
                    for item in await eq.item_list():
                        result.append(
                            LuaItem(item, self._call, self._table, equipped=True)
                        )
            except Exception:
                pass
            return result

        return self._table(self._call(_()))

    def find_item(self, name: str):

        async def _():
            needle = name.lower()
            try:
                inv = await self._c.client_object.try_get_inventory_behavior()
                if inv:
                    for item in await inv.item_list():
                        try:
                            dn = (await item.debug_name() or "").lower()
                            if needle in dn:
                                return LuaItem(item, self._call, self._table)
                            core = await item.object_template()
                            if core:
                                tmpl = WizGameObjectTemplate(
                                    core.hook_handler, await core.read_base_address()
                                )
                                n = (await tmpl.object_name() or "").lower()
                                if needle in n:
                                    return LuaItem(item, self._call, self._table)
                        except Exception:
                            continue
            except Exception:
                pass
            return None

        return self._call(_())

    def find_equipped(self, name: str):

        async def _():
            needle = name.lower()
            try:
                eq = await self._c.client_object.try_get_equipment_behavior()
                if eq:
                    for item in await eq.item_list():
                        try:
                            dn = (await item.debug_name() or "").lower()
                            if needle in dn:
                                return LuaItem(
                                    item, self._call, self._table, equipped=True
                                )
                            core = await item.object_template()
                            if core:
                                tmpl = WizGameObjectTemplate(
                                    core.hook_handler, await core.read_base_address()
                                )
                                n = (await tmpl.object_name() or "").lower()
                                if needle in n:
                                    return LuaItem(
                                        item, self._call, self._table, equipped=True
                                    )
                        except Exception:
                            continue
            except Exception:
                pass
            return None

        return self._call(_())

    def has_item(self, name: str) -> bool:
        return self.find_item(name) is not None

    def item_count(self, name: str) -> int:

        async def _():
            needle = name.lower()
            count = 0
            try:
                inv = await self._c.client_object.try_get_inventory_behavior()
                if inv:
                    for item in await inv.item_list():
                        try:
                            dn = (await item.debug_name() or "").lower()
                            if needle in dn:
                                count += 1
                                continue
                            core = await item.object_template()
                            if core:
                                tmpl = WizGameObjectTemplate(
                                    core.hook_handler, await core.read_base_address()
                                )
                                n = (await tmpl.object_name() or "").lower()
                                if needle in n:
                                    count += 1
                        except Exception:
                            continue
            except Exception:
                pass
            return count

        return self._call(_())

    # recipes
    # high-level helpers that compose primitives into common patterns. they
    # live on LuaClient (not sky.*) so they're discoverable via `client:<tab>`
    # and read as english. all are sync python methods on the lua thread; they
    # call other LuaClient methods and any lua callbacks from `opts`, all on the
    # lua thread, so there's no cross-thread lupa hazard

    def _opt(self, opts, key: str, default=None):
        if opts is None:
            return default
        if isinstance(opts, dict):
            return opts.get(key, default)
        try:
            v = getattr(opts, key)
        except (AttributeError, KeyError):
            return default
        return default if v is None else v

    def _sleep_interruptible(self, secs: float):
        import time as _t
        from src.lang.bridge import _ScriptStopped

        end = _t.monotonic() + max(0.0, secs)
        while _t.monotonic() < end:
            if self._stop.is_set():
                raise _ScriptStopped("stopped")
            _t.sleep(min(0.05, max(0.0, end - _t.monotonic())))

    # ── state predicates ──────────────────────────────────────────────

    def at_position(
        self, x: float, y: float, z: float, tolerance: float = 75.0
    ) -> bool:
        return self.distance_to(x, y, z) <= tolerance

    def is_full_hp(self) -> bool:
        return self.health() >= self.max_health()

    def in_danger(self, hp_pct: float = 25.0) -> bool:
        return self.health_pct() < hp_pct

    def has_drops(self, names) -> bool:
        if names is None:
            return True
        if isinstance(names, str):
            return self.got_drop(names)
        # Lua arrays come through as objects supporting .values() (lupa)
        # or as plain sequences if called from Python
        iterable = names.values() if hasattr(names, "values") else names
        for n in iterable:
            if not self.got_drop(n):
                return False
        return True

    # ── health management ─────────────────────────────────────────────

    def ensure_health(self, min_pct: float = 50.0) -> bool:
        if self.health_pct() >= min_pct:
            return False
        if not self.has_potion():
            logger.warning(
                f"[lua] {self._c.title}: ensure_health: "
                f"hp={self.health_pct():.0f}% < {min_pct}% but no potions"
            )
            return False
        return self.use_potion()

    def wait_until_healed(self, target_pct: float = 95.0, window: float = 60.0) -> bool:
        import time as _t

        deadline = _t.monotonic() + window if window and window > 0 else None
        while self.health_pct() < target_pct:
            if self._stop.is_set():
                return False
            if deadline is not None and _t.monotonic() >= deadline:
                msg = (
                    f"wait_until_healed: hp={self.health_pct():.0f}% "
                    f"< {target_pct}% after {window}s. "
                    "Pass window=0 to wait forever, or a larger number of seconds."
                )
                logger.warning(f"[lua] {self._c.title}: {msg}")
                raise ScriptError(msg)
            self._sleep_interruptible(0.5)
        return True

    # ── navigation recipes ────────────────────────────────────────────

    def enter_sigil(self, x: float, y: float, z: float, opts=None):
        key = self._opt(opts, "key", "X")
        confirm_key = self._opt(opts, "confirm_key", "ENTER")
        settle = float(self._opt(opts, "settle", 0.6))
        window = float(self._opt(opts, "window", 60.0))
        retry_every = float(self._opt(opts, "retry_every", 3.0))
        require_popup_opt = self._opt(opts, "require_popup", True)
        # Lua truthiness: only literal nil/false counts as "off"
        require_popup = require_popup_opt is not False and require_popup_opt is not None
        deadline_s = _resolve_window("zone_change", window)

        async def _():
            loop = asyncio.get_event_loop()
            deadline = loop.time() + deadline_s if deadline_s is not None else None

            try:
                baseline = await self._c.zone_name()
            except Exception:
                baseline = None
            if baseline is None:
                # ``zone_name`` raised - fall back to the script's last
                # acknowledged zone. if we still have nothing, the
                # zone-name signal is disabled (the is_loading rising
                # edge is enough). without this guard, the ``now != None``
                # check would false-positive on the first successful read
                baseline = self._last_seen_zone

            async def _entry_signal() -> bool:
                # primary: real zone change. suppressed when baseline was
                # unreadable at start (the ``baseline is None`` branch)
                if baseline is not None:
                    try:
                        now = await self._c.zone_name()
                    except Exception:
                        now = None
                    if now is not None and now != baseline:
                        self._last_seen_zone = now
                        return True

                # secondary: loading screen visible → wait for it to
                # clear, then re-check zone_name. only return success on
                # an actual change; otherwise it was a transient
                try:
                    if await self._c.is_loading():
                        load_started = loop.time()
                        cleared = False
                        while True:
                            if self._stop.is_set():
                                return True
                            if deadline is not None and loop.time() >= deadline:
                                break
                            try:
                                if not await self._c.is_loading():
                                    cleared = True
                                    break
                            except Exception:
                                cleared = True
                                break
                            await asyncio.sleep(0.1)
                        if not cleared:
                            raise self._timeout(
                                "zone_change",
                                "loading screen appeared but never cleared "
                                "within window; game may be stuck mid-load",
                            )
                        # loading cleared - verify it was a real entry by
                        # re-checking zone_name
                        try:
                            now = await self._c.zone_name()
                        except Exception:
                            now = None
                        if baseline is not None and now is not None and now != baseline:
                            self._last_seen_zone = now
                            return True
                        # same-named instance fallback: only trust an
                        # is_loading event as "real entry" if it was
                        # sustained (>= 0.5s). sub-half-second flickers
                        # are the X-press server query, not a load
                        if (loop.time() - load_started) >= 0.5:
                            try:
                                self._last_seen_zone = await self._c.zone_name()
                            except Exception:
                                pass
                            return True
                        # otherwise: transient, keep watching
                except ScriptError:
                    raise
                except Exception:
                    pass
                return False

            # once True we've sent the confirm ENTER and the dungeon is loading.
            # don't re-teleport or re-press X after this - the player's already
            # inside, and retrying would fling them to the outside-sigil coords
            # and spam X at nothing. just watch for the load to finish
            committed = False
            commit_deadline = None

            # if the sigil/NPC hasn't streamed in, NPCRangeWin stays invisible
            # and a naive loop re-teleports forever. count consecutive misses so
            # we can tp away and back, forcing a re-stream around the sigil
            popup_misses = 0

            attempt = 0
            while True:
                if self._stop.is_set():
                    return
                attempt += 1

                # skip the teleport+settle+popup-check entirely once we've
                # committed (post-ENTER) - we're either mid-load or already
                # inside. just keep polling for the signal.
                if not committed:
                    try:
                        await _teleport_with_retry(
                            self._c, XYZ(x, y, z), stop_event=self._stop
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[lua] {self._c.title}: enter_sigil teleport "
                            f"failed on attempt {attempt}: "
                            f"{type(exc).__name__}: {exc}"
                        )

                if not committed:
                    # first attempt gets the user-provided settle so the
                    # game has time to register the new position; retries
                    # only need a short beat - already on the sigil
                    await asyncio.sleep(settle if attempt == 1 else 0.25)

                    # step 1: positional confirmation. NPCRangeWin is the
                    # game's own "press X to interact" popup, visible only
                    # when the player is standing on a sigil/NPC trigger
                    # if it's not up, the teleport landed off-sigil -
                    # re-teleport rather than firing a wasted keypress
                    if require_popup:
                        popup_visible = False
                        popup_deadline = loop.time() + 1.0
                        while loop.time() < popup_deadline:
                            if self._stop.is_set():
                                return
                            try:
                                if await is_visible_by_path(self._c, npc_range_path):
                                    popup_visible = True
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.1)
                        if not popup_visible:
                            if attempt == 1:
                                logger.debug(
                                    f"[lua] {self._c.title}: NPCRangeWin not "
                                    f"visible after teleport; running "
                                    "streaming reset."
                                )

                            # reset on the first miss - the sigil probably
                            # hasn't streamed in, and waiting for a second miss
                            # just burns a cycle. _streaming_reset bounces to a
                            # nearby chunk and back to force a re-stream, then we
                            # re-poll for the popup
                            await _streaming_reset(
                                self._c, XYZ(x, y, z), stop_event=self._stop
                            )
                            popup_misses += 1

                            # re-poll for the popup right after the reset
                            # if it's now up, fall through to the X press -
                            # otherwise loop and try again
                            reset_recheck = loop.time() + 1.0
                            while loop.time() < reset_recheck:
                                if self._stop.is_set():
                                    return
                                try:
                                    if await is_visible_by_path(
                                        self._c, npc_range_path
                                    ):
                                        popup_visible = True
                                        break
                                except Exception:
                                    pass
                                await asyncio.sleep(0.1)

                            if not popup_visible:
                                if deadline is not None and loop.time() >= deadline:
                                    break
                                continue

                        # popup is up - clear miss counter so a later
                        # transient unstick doesn't fire prematurely
                        popup_misses = 0

                    # step 2: press X to open the sigil's entry popup
                    try:
                        await self._c.send_key(key=Keycode[key], seconds=0.1)
                    except Exception as exc:
                        logger.warning(
                            f"[lua] {self._c.title}: enter_sigil send_key "
                            f"failed on attempt {attempt}: "
                            f"{type(exc).__name__}: {exc}"
                        )

                    # step 2b: did the game accept the X press? if so the
                    # NPCRangeWin prompt disappears, which covers every post-X
                    # state (confirm dialog, queue, join overlay, instant load).
                    # without this gate, queue UIs that don't match
                    # dungeon_warning_path get retried and re-teleport
                    if require_popup:
                        accept_check_until = loop.time() + 1.0
                        if deadline is not None:
                            accept_check_until = min(accept_check_until, deadline)
                        while loop.time() < accept_check_until:
                            if self._stop.is_set():
                                return
                            try:
                                if not await is_visible_by_path(
                                    self._c, npc_range_path
                                ):
                                    committed = True
                                    commit_deadline = loop.time() + 20.0
                                    if deadline is not None:
                                        commit_deadline = min(commit_deadline, deadline)
                                    break
                            except Exception:
                                pass
                            # also commit early if a confirmation dialog
                            # already showed up while we were polling
                            try:
                                if await is_visible_by_path(
                                    self._c, dungeon_warning_path
                                ):
                                    committed = True
                                    commit_deadline = loop.time() + 20.0
                                    if deadline is not None:
                                        commit_deadline = min(commit_deadline, deadline)
                                    break
                            except Exception:
                                pass
                            # or commit on is_loading rising edge - handled
                            # below by _entry_signal, but latching here
                            # too avoids a race where the load finishes
                            # before the slow path notices
                            try:
                                if await self._c.is_loading():
                                    committed = True
                                    commit_deadline = loop.time() + 20.0
                                    if deadline is not None:
                                        commit_deadline = min(commit_deadline, deadline)
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.1)
                        # if still not committed after 1s of looking,
                        # the X press was eaten - let the outer loop
                        # re-teleport (back to top of while True)

                # step 3: watch for entry, auto-confirming any
                # MessageBoxModalWindow (Polaris/team-up sigils always show an
                # "Are you sure?" that ENTER dismisses; otherwise it absorbs our
                # X presses). after ENTER we latch committed and extend the poll
                # budget, since the load may flash past our 0.15s poll, and a
                # re-teleport now would drop us at outside-sigil coords inside
                # the dungeon
                if committed and commit_deadline is not None:
                    poll_until = commit_deadline
                else:
                    poll_until = loop.time() + retry_every
                if deadline is not None:
                    poll_until = min(poll_until, deadline)

                while loop.time() < poll_until:
                    if self._stop.is_set():
                        return

                    if await _entry_signal():
                        return

                    # confirmation dialog handling. we check is_loading
                    # FIRST in _entry_signal so a dialog that's already
                    # transitioning to a load screen doesn't get re-pressed
                    try:
                        if await is_visible_by_path(self._c, dungeon_warning_path):
                            try:
                                await self._c.send_key(
                                    key=Keycode[confirm_key], seconds=0.1
                                )
                            except Exception as exc:
                                logger.warning(
                                    f"[lua] {self._c.title}: enter_sigil "
                                    f"confirm send_key failed: "
                                    f"{type(exc).__name__}: {exc}"
                                )
                            committed = True
                            # extend the watch window post-confirm. 20s is
                            # plenty for any normal dungeon load and is
                            # bounded by the overall window= budget anyway
                            commit_deadline = loop.time() + 20.0
                            if deadline is not None:
                                commit_deadline = min(commit_deadline, deadline)
                            poll_until = commit_deadline
                            # give the game a moment to start the load
                            # before we resume polling
                            await asyncio.sleep(0.5)
                            continue
                    except Exception:
                        pass

                    await asyncio.sleep(0.15)

                if committed:
                    # we confirmed the dialog but never observed the load
                    # complete. don't retry - re-teleporting inside the
                    # dungeon causes the very bug this branch exists to
                    # prevent. surface the timeout instead.
                    raise self._timeout(
                        "zone_change",
                        "dungeon-entry confirmation was sent but no load "
                        "screen or zone change was observed within the "
                        "extended commit window; either the confirm key "
                        "is wrong or the load completed faster than the "
                        "poll interval. Try increasing window= or set "
                        "confirm_key= explicitly",
                    )
                if deadline is not None and loop.time() >= deadline:
                    raise self._timeout(
                        "zone_change",
                        f"sigil entry never triggered a loading screen or "
                        f"zone change from {baseline!r} after {attempt} "
                        f"press(es); teleport may be landing off-sigil, "
                        f"or the dungeon needs a different confirm key",
                    )
                # otherwise: outer loop re-teleports + re-presses

        self._call(_())

    def exit_dungeon(self, gate: str = "Start") -> bool:
        return self.go_through_gate(gate)

    def equip_deck(self, name: str, window: float = 20.0):
        if not name or not name.strip():
            raise ScriptError(
                "equip_deck: name must be a non-empty substring "
                "(empty matches every preset)"
            )

        # get_window_from_path / click_window_by_path / is_visible_by_path
        # are already imported at module scope (top of file). no re-import.

        DECK_BASE = [
            "WorldView",
            "DeckConfiguration",
            "DeckConfigurationWindow",
            "ControlSprite",
            "DeckPage",
        ]
        DECK_NAME = DECK_BASE + ["DeckName"]
        NEXT_DECK = DECK_BASE + ["NextDeck"]
        # Note: EquipButton's path is the same whether the currently-shown
        # preset is equipped or not - clicking it toggles. the equipFist
        # icon (visible only on the equipped preset) is what we probe to
        # tell the states apart before clicking
        EQUIP_BUTTON = DECK_BASE + ["EquipButton"]
        EQUIP_FIST = DECK_BASE + ["equipFist"]
        SPELLBOOK_ROOT = ["WorldView", "DeckConfiguration"]

        deadline_s = max(1.0, float(window))

        async def _body():
            loop = asyncio.get_event_loop()
            deadline = loop.time() + deadline_s

            async def _read_name() -> str:
                # DeckName window can resolve to False (not None - that's
                # get_window_from_path's miss sentinel) right after a
                # prev/next click while the UI updates. retry until we get
                # a non-empty string, capped so a genuinely-broken path
                # still bails
                for _ in range(6):
                    w = await get_window_from_path(self._c.root_window, DECK_NAME)
                    if w:  # both None and False are falsy
                        text = (await w.maybe_text() or "").strip()
                        if text:
                            return text
                    await asyncio.sleep(0.05)
                return ""

            async def _click(path):
                # swallow runtime UI hiccups so a transient path-resolution
                # failure doesn't abort the whole swap. the downside is
                # that a silent click failure looks like "name didn't
                # change" → premature edge-detection, but we gate on
                # DECK_NAME visibility before entering the cycling loops
                # so the buttons are live by then
                try:
                    await click_window_by_path(self._c, path)
                except Exception as exc:
                    logger.warning(
                        f"[lua] {self._c.title}: equip_deck click failed at "
                        f"{path[-1]}: {type(exc).__name__}: {exc}"
                    )

            # open spellbook - toggle P up to 3 times until the
            # DeckConfiguration root is visible
            opens = 0
            while not await is_visible_by_path(self._c, SPELLBOOK_ROOT):
                if self._stop.is_set():
                    return
                if loop.time() >= deadline or opens >= 3:
                    raise self._timeout(
                        "window",
                        "spellbook never opened (P press did not show "
                        "DeckConfiguration)",
                    )
                await self._c.send_key(key=Keycode.P, seconds=0.1)
                opens += 1
                await asyncio.sleep(0.5)

            # Wait briefly for DeckPage to settle. if we opened on a
            # different tab (Equipment Manager etc.), bail with a clear
            # message rather than guessing at tab-switch UI
            page_deadline = min(loop.time() + 5.0, deadline)
            while not await is_visible_by_path(self._c, DECK_NAME):
                if self._stop.is_set():
                    return
                if loop.time() >= page_deadline:
                    raise ScriptError(
                        "equip_deck: spellbook opened but DeckPage is not "
                        "the visible tab. Open the deck-page tab manually "
                        "or call equip_deck while the spellbook is closed."
                    )
                await asyncio.sleep(0.15)

            target = name.lower()

            async def _equip_and_close():
                # the EquipButton toggles: clicking it on the already-
                # equipped preset would *unequip* it. skip the click if
                # the equipFist icon is showing (game's own marker that
                # this preset is the active one)
                already_equipped = await is_visible_by_path(self._c, EQUIP_FIST)
                if not already_equipped:
                    await _click(EQUIP_BUTTON)
                    await asyncio.sleep(0.4)
                # independent 5s cleanup budget - once the equip click
                # has gone through we always want a clean spellbook
                # close, even if the main deadline already ran out
                close_deadline = loop.time() + 5.0
                while await is_visible_by_path(self._c, SPELLBOOK_ROOT):
                    if self._stop.is_set():
                        return
                    if loop.time() >= close_deadline:
                        break
                    await self._c.send_key(key=Keycode.P, seconds=0.1)
                    await asyncio.sleep(0.3)

            # cycle through presets with NextDeck, looking for the target
            # we can't rely on "name stopped changing = reached the edge"
            # because the game wraps around - with 2 presets, prev/next
            # oscillates forever. instead, track names we've already seen:
            # the first repeat means we've gone full circle without a match
            seen = set()
            cur = await _read_name()
            logger.debug(f"[equip_deck] start name={cur!r}")
            if target in cur.lower():
                await _equip_and_close()
                return
            seen.add(cur)

            for _step in range(20):
                if self._stop.is_set():
                    return
                if loop.time() >= deadline:
                    raise self._timeout(
                        "window",
                        f"equip_deck never matched {name!r} before window expired",
                    )
                await _click(NEXT_DECK)
                await asyncio.sleep(0.3)
                cur = await _read_name()
                logger.debug(f"[equip_deck] next step={_step} name={cur!r}")
                if target in cur.lower():
                    await _equip_and_close()
                    return
                if cur in seen:
                    # wrapped around to an already-visited preset - the
                    # full list has been exhausted without a match
                    break
                seen.add(cur)

            # not found. close the spellbook before raising so we
            # don't strand the UI open for the next script call. the
            # cleanup gets its own 3s budget independent of the main
            # deadline - even if cycling burned the whole window, we
            # want a clean state when we raise
            cleanup_deadline = loop.time() + 3.0
            while await is_visible_by_path(self._c, SPELLBOOK_ROOT):
                if self._stop.is_set():
                    break
                if loop.time() >= cleanup_deadline:
                    break
                await self._c.send_key(key=Keycode.P, seconds=0.1)
                await asyncio.sleep(0.3)
            raise ScriptError(
                f"equip_deck: no deck preset matching {name!r} found in "
                f"the configuration list."
            )

        async def _():
            # always release the mouse handler however _body() exits. otherwise
            # a failed deck-cycle can leave the W101 window disabled
            # (EnableWindow False with no matching True) and the mouseless hook
            # active, locking the user out of clicking until a restart
            try:
                await _body()
            finally:
                try:
                    await self._c.mouse_handler.release_mouse()
                except Exception:
                    pass

        self._call(_())

    def follow_path(self, points):
        if points is None:
            return
        iterable = points.values() if hasattr(points, "values") else points
        for p in iterable:
            # p is a Lua table; index it positionally
            try:
                x, y, z = p[1], p[2], p[3]
            except Exception:
                x, y, z = p[0], p[1], p[2]
            self.teleport(x, y, z)
            pause = self._opt(p, "sleep", 0)
            if pause:
                self._sleep_interruptible(float(pause))

    def go_to_npc(self, name: str, max_dist: float = None):
        m = self.find_mob(name, max_dist)
        if not m:
            raise ScriptError(f"go_to_npc: no entity matching {name!r}")
        m.navigate_to()
        return m

    def go_to_dorm(self):
        self.click_window(
            [
                "WorldView",
                "windowHUD",
                "compassAndTeleporterButtons",
                "GotoDormButton",
            ]
        )

    # ── UI recipes ────────────────────────────────────────────────────

    def auto_dialog(self, max_clicks: int = 30) -> int:
        clicks = 0
        for _ in range(int(max_clicks)):
            # 2s window per check - short enough that we don't hang on
            # dialog that just closed, long enough to catch slow openers
            try:
                self.waitfor_dialog(window=2.0)
            except ScriptError:
                return clicks
            self.send_key("SPACEBAR")
            self._sleep_interruptible(0.4)
            clicks += 1
        return clicks

    # ── farming recipes ───────────────────────────────────────────────

    def farm_dungeon(self, opts) -> int:
        enter_fn = self._opt(opts, "enter")
        playstyle = self._opt(opts, "playstyle")
        until_drop = self._opt(opts, "until_drop")
        max_runs = self._opt(opts, "max_runs")
        pre_fight = self._opt(opts, "pre_fight")
        exit_gate = self._opt(opts, "exit_gate", "Start")
        on_run_end = self._opt(opts, "on_run_end")

        if enter_fn is None:
            raise ScriptError("farm_dungeon: opts.enter is required")
        if playstyle is None:
            raise ScriptError("farm_dungeon: opts.playstyle is required")
        if until_drop is None and max_runs is None:
            raise ScriptError("farm_dungeon: pass until_drop or max_runs (or both)")

        cap = float(max_runs) if max_runs is not None else float("inf")
        i = 0
        while i < cap:
            if until_drop and self.got_drop(until_drop):
                break
            i += 1
            self.log(f"farm_dungeon: run {i}")
            self.load_playstyle(playstyle)
            self.enable_combat()
            enter_fn()
            if pre_fight:
                pre_fight()
            self.waitfor_battle_start()
            self.waitfor_battle_finish()
            self.waitfor_freedom()
            ok = self.go_through_gate(exit_gate)
            if not ok:
                # the engine already retried with escalating params and
                # drove any stray combat. if it still failed, looping
                # would just trash state - the next iteration's `enter`
                # would teleport to outside-zone coords from inside the
                # dungeon. abort loudly so the user can intervene.
                raise ScriptError(
                    f"farm_dungeon: could not exit through gate {exit_gate!r} "
                    f"after multiple attempts (run {i}). Player may be stuck "
                    "on collision, or the gate's trigger anchor doesn't "
                    "match the actual portal location for this dungeon."
                )
            if on_run_end:
                on_run_end(i)
        suffix = f" (got {until_drop})" if until_drop else ""
        self.log(f"farm_dungeon: completed {i} run(s){suffix}")
        return i

    def farm_mob(self, opts) -> int:
        mob_name = self._opt(opts, "mob_name")
        playstyle = self._opt(opts, "playstyle")
        until_drop = self._opt(opts, "until_drop")
        max_runs = self._opt(opts, "max_runs")
        max_dist = self._opt(opts, "max_dist")
        approach = self._opt(opts, "approach", "teleport")
        on_run_end = self._opt(opts, "on_run_end")

        if mob_name is None:
            raise ScriptError("farm_mob: opts.mob_name is required")
        if playstyle is None:
            raise ScriptError("farm_mob: opts.playstyle is required")
        if until_drop is None and max_runs is None:
            raise ScriptError("farm_mob: pass until_drop or max_runs")

        import time as _t

        cap = float(max_runs) if max_runs is not None else float("inf")
        i = 0
        while i < cap:
            if until_drop and self.got_drop(until_drop):
                break
            i += 1
            self.log(f"farm_mob: run {i} (looking for {mob_name})")
            # arm combat for waitfor_battle_finish's NativeCombat to pick up
            # do NOT call enable_combat() here - that spawns a per-client
            # watcher that creates its own NativeCombat each battle, which
            # races waitfor_battle_finish's NativeCombat for _active_combat
            # and silently clobbers cast packets mid-planning-phase
            self.load_playstyle(playstyle)
            self._c.combat_config = self._c._playstyle_config
            # engage loop: cycle through every matching mob, tp'ing to a
            # different one each retry until combat starts. re-fetches the list
            # each pass so new spawns count and despawns drop out, so one missed
            # teleport doesn't time out waitfor_battle_start and abort
            ENGAGE_WINDOW = 60.0
            ENGAGE_RETRY_SECS = 1.0
            engage_deadline = _t.monotonic() + ENGAGE_WINDOW
            engaged = False
            attempt = 0
            while _t.monotonic() < engage_deadline:
                raw_mobs = self.find_mobs_sorted(mob_name, max_dist)
                # via the bridge find_mobs_sorted returns a 1-indexed lua-table
                # proxy. copy it into a python list (1-indexed access) for clean
                # 0-indexed cycling below; the fallback handles a plain list too
                try:
                    n_raw = len(raw_mobs)
                    mobs = [raw_mobs[i] for i in range(1, n_raw + 1)]
                except (TypeError, KeyError):
                    mobs = list(raw_mobs) if raw_mobs else []
                # strip Nones in case the proxy reports a length that
                # overshoots the populated slots (defensive)
                mobs = [m for m in mobs if m is not None]
                n = len(mobs)
                if n == 0:
                    self._sleep_interruptible(ENGAGE_RETRY_SECS)
                    continue
                m = mobs[attempt % n]
                attempt += 1
                if approach == "navigate":
                    m.navigate_to()
                else:
                    m.to()
                # poll for combat for up to ENGAGE_RETRY_SECS before
                # rotating to the next mob
                slice_end = _t.monotonic() + ENGAGE_RETRY_SECS
                while _t.monotonic() < slice_end:
                    if self.in_combat():
                        engaged = True
                        break
                    self._sleep_interruptible(0.25)
                if engaged:
                    break
                self.log(
                    f"farm_mob: no combat after teleport to {mob_name!r} "
                    f"(attempt {attempt}/{n} visible); trying next"
                )
            if not engaged:
                raise ScriptError(
                    f"farm_mob: could not engage {mob_name!r} within "
                    f"{ENGAGE_WINDOW:.0f}s of retries"
                )
            self.waitfor_battle_finish()
            self.waitfor_freedom()
            if on_run_end:
                on_run_end(i)
        return i

    def farm_until(self, drop_name: str, body, max_runs: int = 1000) -> int:
        i = 0
        cap = int(max_runs)
        while i < cap:
            if self.got_drop(drop_name):
                break
            i += 1
            body(i)
        return i

    def kill_boss(self, opts=None):
        mob_name = self._opt(opts, "mob")
        playstyle = self._opt(opts, "playstyle")
        b = self.find_mob(mob_name) if mob_name else self.nearest_boss()
        if not b:
            raise ScriptError(
                "kill_boss: no boss found"
                + (f" matching {mob_name!r}" if mob_name else "")
            )
        if playstyle is not None:
            self.load_playstyle(playstyle)
        b.to()
        self.waitfor_battle_start()
        self.waitfor_battle_finish()
        self.waitfor_freedom()

    # ── debug ─────────────────────────────────────────────────────────

    def log_state(self, label: str = "state"):
        try:
            z = self.zone()
        except Exception:
            z = "<err>"
        try:
            hp = self.health()
        except Exception:
            hp = -1
        try:
            in_c = self.in_combat()
        except Exception:
            in_c = False
        self.log(f"{label} | zone={z} hp={hp} combat={in_c}")

    def log(self, msg: str):

        logger.info(f"[lua] {self._c.title}: {msg}")


# re-import the extracted classes at the bottom so LuaClient's method
# bodies (which reference them at call time, never module-load time)
# can resolve them via this module's namespace
from src.lang.client._mob import LuaMob  # noqa: E402
from src.lang.client._combatant import LuaCombatant  # noqa: E402
