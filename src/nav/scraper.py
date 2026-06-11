from __future__ import annotations

import math
import struct
from collections import defaultdict

from loguru import logger

from wizwalker import Client, MemoryReadError
from wizwalker.memory.memory_object import Primitive
from wizwalker.memory.memory_objects.enums import ObjectType

# memory layout
#
# zone pointer chain:
#   GameClient base + 0x21368  →  zone*
#   zone* + 0xD8               →  zone_data*
#   zone_data is scanned for the trigger-volume std::list head (see below)
#
# trigger-volume std::list node layout (MSVC doubly-linked list):
#   node + 0x00   next*   (sentinel node marks end)
#   node + 0x08   prev*
#   node + 0x10   vtable  (confirms node is live; data starts here → data_addr)
#   data_addr + 0x00   vtable                    (exe range 0x7FF6_0000_0000+)
#   data_addr + 0x48   std::string  name         ("Zone/SubZone_TriggerName")
#   data_addr + 0x68   float[3]     XYZ center   (world-space anchor)
#   data_addr + 0x074  float        yaw          (radians; forward = sin/cos(yaw))
#
# msvc std::string (32-byte SSO layout):
#   offset  0  : char buf[16]  (inline data when capacity < 16)
#              OR  char* ptr   (heap pointer when capacity >= 16)
#   offset 16  : size_t size
#   offset 24  : size_t capacity
#   → if capacity < 16: string data is in buf[0:size]
#   → if capacity >= 16: dereference ptr, read size bytes from heap
#
# exe image address range (used to distinguish vtable/code ptrs from heap ptrs):
#   0x7FF6_0000_0000 - 0x7FFF_FFFF_FFFF

DOOR_OBJECT_TYPE = ObjectType.door
_TELEPORT_KEYWORDS = (
    "teleport",
    "door",
    "gate",
    "portal",
    "exit",
    "entrance",
    "arch",
    "passage",
    "warp",
    "sigil",
)
_EXE_BASE = 0x7FF600000000


# shared helpers


async def _safe(coro, label: str, default=None):
    try:
        return await coro
    except (ValueError, MemoryReadError, AttributeError, OSError) as exc:
        logger.debug(f"  [skip {label}: {type(exc).__name__}: {exc}]")

        return default


async def _read_msvc_string(mem, addr: int) -> str:
    try:
        raw = await mem.read_bytes(addr, 32)
        size = struct.unpack_from("<Q", raw, 16)[0]
        cap = struct.unpack_from("<Q", raw, 24)[0]

        if size > 4096 or cap > 4096 or size == 0:
            return ""
        if cap < 16:
            data = raw[:size]
        else:
            ptr = struct.unpack_from("<Q", raw, 0)[0]

            if not (0x10000 < ptr < _EXE_BASE):
                return ""

            data = await mem.read_bytes(ptr, min(size, 512))
        s = data.decode("ascii", "replace")

        return s if all(32 <= ord(c) < 127 for c in s) else ""
    except Exception:
        return ""


async def _read_zone_data_addr(client: Client) -> int:
    try:
        mem = client.hook_handler
        base = await client.game_client.read_base_address()
        zone = await mem.read_typed(base + 0x21368, Primitive.uint64)

        if zone == 0:
            return 0
        return await mem.read_typed(zone + 0xD8, Primitive.uint64)
    except Exception:
        return 0


async def _find_trigger_list(mem, zone_data_addr: int) -> int:
    try:
        raw = await mem.read_bytes(zone_data_addr, 0x400)
    except Exception:
        return 0

    best_addr = 0
    best_size = 0

    for i in range(0, len(raw) - 15, 8):
        ptr = struct.unpack_from("<Q", raw, i)[0]
        size = struct.unpack_from("<Q", raw, i + 8)[0]

        if not (0x10000 < ptr < 0x7FFFFFFFFFFF and 0 < size < 256):
            continue
        try:
            head = await mem.read_typed(ptr, Primitive.uint64)
            vt = await mem.read_typed(head + 0x10, Primitive.uint64)
        except Exception:
            continue
        if vt < _EXE_BASE:
            continue

        nm = await _read_msvc_string(mem, head + 0x10 + 0x48)

        if nm and size > best_size:
            best_size = size
            best_addr = zone_data_addr + i

    return best_addr


def _bar(ratio: float, width: int = 16) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)

    return "█" * filled + "░" * (width - filled)


def _div(label: str = "", width: int = 64) -> str:
    s = f"  {label}  " if label else "  "

    return s + "─" * max(0, width - len(s))


# scan


async def scan_game(client: Client) -> None:
    zone = (await _safe(client.zone_name(), "zone_name")) or "<unknown>"
    t = f" {zone} "
    pad = max(0, 64 - len(t))

    logger.info("═" * (pad // 2) + t + "═" * (pad - pad // 2))
    logger.info("")

    # player
    logger.info(_div("player"))
    logger.info(f"  {'zone':<10}{zone}")

    try:
        pos = await client.body.position()
        yaw = await client.body.yaw()

        logger.info(
            f"  {'pos':<10}({pos.x:>8.1f}, {pos.y:>8.1f}, {pos.z:>7.1f})    yaw  {math.degrees(yaw):>+7.1f}°"
        )

    except Exception:
        logger.info(f"  {'pos':<10}<unavailable>")

    try:
        hp = await client.stats.current_hitpoints()
        max_hp = await client.stats.max_hitpoints()
        pct = hp / max_hp if max_hp else 0.0

        logger.info(
            f"  {'health':<10}{hp:>5}  / {max_hp:>5}   {_bar(pct)}   {pct:>4.0%}"
        )

    except Exception:
        pass
    try:
        mp = await client.stats.current_mana()
        max_mp = await client.stats.max_mana()
        pct = mp / max_mp if max_mp else 0.0

        logger.info(f"  {'mana':<10}{mp:>5}  / {max_mp:>5}   {_bar(pct)}   {pct:>4.0%}")

    except Exception:
        pass
    try:
        energy = await client.stats.current_energy()

        logger.info(f"  {'energy':<10}{energy}")
    except Exception:
        pass

    logger.info("")

    # triggers
    gates = await enumerate_zone_gates(client)
    n_exit = sum(1 for e in gates if e["kind"] == "exit")
    n_arrival = sum(1 for e in gates if e["kind"] == "arrival")
    n_other = sum(1 for e in gates if e["kind"] == "other")

    logger.info(
        _div(
            f"triggers ({len(gates)})   {n_exit} exit  {n_arrival} arrival  {n_other} other"
        )
    )
    for e in gates:
        name = e["name"]
        disp = name if len(name) <= 34 else name[:33] + "…"
        partner = f"→ {e['partner']}" if e["partner"] else ""

        logger.info(
            f"  {disp:<34}  ({e['x']:>8.1f}, {e['y']:>8.1f}, {e['z']:>7.1f})"
            f"   {e['yaw_deg']:>+7.1f}°   {e['kind']:<8} {partner}"
        )

    logger.info("")


import re as _re

# trigger names embed routing hints in a few conventions; parse them once at
# module scope so walk_through_gate can match the same "partner zone" hints
# enumerate_zone_gates produces
_RE_EXIT_PAREN = _re.compile(
    r"Target\s+location\s*\(\s*(?:WC_Hub|Hub)\s+([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*?)"
    r"(?:\s+Exit)?\s*\)"
)

_RE_ARRIVAL_FROM = _re.compile(r"(?:^|[\s\-_(])From[_\s]?([A-Za-z0-9_]+)", _re.I)
_RE_ARRIVAL_TO_HUB = _re.compile(r"\(\s*([A-Za-z0-9_]+)\s+to\s+\w+\s*\)", _re.I)
_RE_PAREN_ANY = _re.compile(r"\(\s*([^)]+?)\s*\)")


def _classify_trigger_name(name: str) -> tuple[str, str | None]:
    if m := _RE_ARRIVAL_TO_HUB.search(name):
        return ("arrival", m.group(1))
    if m := _RE_ARRIVAL_FROM.search(name):
        return ("arrival", m.group(1))
    if m := _RE_EXIT_PAREN.search(name):
        return ("exit", m.group(1).strip())
    if name.startswith("Target location") and (m := _RE_PAREN_ANY.search(name)):
        return ("exit", m.group(1).strip())
    return ("other", None)


async def enumerate_zone_gates(client: Client) -> list[dict]:
    mem = client.hook_handler
    out: list[dict] = []

    zone_data_addr = await _read_zone_data_addr(client)

    if zone_data_addr == 0:
        logger.warning("enumerate_zone_gates: not in a zone")
        return out

    async def _read_xyz(data_addr: int) -> tuple[float, float, float] | None:
        try:
            raw = await mem.read_bytes(data_addr + 0x68, 12)
            x, y, z = struct.unpack("<fff", raw)

            if not all(math.isfinite(v) and abs(v) <= 100000.0 for v in (x, y, z)):
                return None
            if max(abs(x), abs(y), abs(z)) < 1.0:
                return None

            return (x, y, z)
        except Exception:
            return None

    async def _read_yaw(data_addr: int) -> float:
        try:
            (yaw,) = struct.unpack("<f", await mem.read_bytes(data_addr + 0x074, 4))

            return yaw if math.isfinite(yaw) else 0.0
        except Exception:
            return 0.0

    async def _walk_candidate(list_addr: int) -> list[dict]:
        try:
            sentinel = await mem.read_typed(list_addr, Primitive.uint64)
            size_val = await mem.read_typed(list_addr + 8, Primitive.uint64)
        except Exception:
            return []

        if not (0x10000 < sentinel < 0x7FFFFFFFFFFF) or not (0 < size_val < 256):
            return []
        try:
            head = await mem.read_typed(sentinel, Primitive.uint64)
        except Exception:
            return []

        # sniff first 3 nodes - confirm vtable + readable name before committing
        sniff_addr = head
        sniff_hits = 0
        sniff_visited = {sentinel}

        for _ in range(3):
            if sniff_addr in sniff_visited or sniff_addr == 0:
                break
            sniff_visited.add(sniff_addr)
            try:
                vt = await mem.read_typed(sniff_addr + 0x10, Primitive.uint64)
            except Exception:
                break
            if vt >= _EXE_BASE:
                nm = await _read_msvc_string(mem, sniff_addr + 0x10 + 0x48)
                if nm and len(nm) >= 3:
                    sniff_hits += 1
            try:
                sniff_addr = await mem.read_typed(sniff_addr, Primitive.uint64)
            except Exception:
                break

        if sniff_hits < min(2, size_val):
            return []

        results: list[dict] = []
        node = head
        visited = {sentinel}

        while node not in visited and node != 0 and len(results) < 256:
            visited.add(node)
            data_addr = node + 0x10
            try:
                vt = await mem.read_typed(data_addr, Primitive.uint64)
            except Exception:
                break
            if vt >= _EXE_BASE:
                name = await _read_msvc_string(mem, data_addr + 0x48)
                xyz = await _read_xyz(data_addr)
                if name and xyz:
                    yaw = await _read_yaw(data_addr)
                    kind, partner = _classify_trigger_name(name)
                    results.append(
                        {
                            "name": name,
                            "x": round(xyz[0], 2),
                            "y": round(xyz[1], 2),
                            "z": round(xyz[2], 2),
                            "yaw": round(yaw, 4),
                            "yaw_deg": round(math.degrees(yaw), 1),
                            "kind": kind,
                            "partner": partner,
                        }
                    )
            try:
                node = await mem.read_typed(node, Primitive.uint64)
            except Exception:
                break

        return results

    try:
        raw = await mem.read_bytes(zone_data_addr, 0x400)
    except Exception as exc:
        logger.error(f"enumerate_zone_gates: failed to read zone_data: {exc}")
        return out

    best: list[dict] = []

    for i in range(0, len(raw) - 15, 8):
        ptr = struct.unpack_from("<Q", raw, i)[0]
        size_candidate = struct.unpack_from("<Q", raw, i + 8)[0]

        if not (0x10000 < ptr < 0x7FFFFFFFFFFF and 0 < size_candidate < 256):
            continue

        hits = await _walk_candidate(zone_data_addr + i)

        if len(hits) > len(best):
            best = hits

    return best


async def enumerate_interactive_teleporters(client: Client) -> list[dict]:
    out: list[dict] = []

    try:
        entities = await client.get_base_entity_list()
    except Exception as exc:
        logger.error(f"interactive_teleporters: entity list failed: {exc}")
        return out

    KEYWORDS = ("teleport", "sigil", "warp", "portal")

    for ent in entities:
        try:
            obj_name = ""
            tmpl = await _safe(ent.object_template(), "tmpl")
            if tmpl:
                obj_name = (await _safe(tmpl.object_name(), "obj_name", "")) or ""

            behavior_names: list[str] = []
            try:
                for b in await ent.inactive_behaviors():
                    nm = await _safe(b.behavior_name(), "bname", "") or ""
                    if nm:
                        behavior_names.append(nm)
            except Exception:
                pass

            haystack = (obj_name + " " + " ".join(behavior_names)).lower()
            if not any(k in haystack for k in KEYWORDS):
                continue
            if not any(
                (
                    "interactive" in n.lower()
                    or "sigil" in n.lower()
                    or "teleport" in n.lower()
                    or "warp" in n.lower()
                )
                for n in behavior_names
            ):
                continue

            xyz = await _safe(ent.location(), "loc")
            if not xyz:
                continue
            out.append(
                {
                    "name": obj_name or "<unnamed>",
                    "x": round(xyz.x, 2),
                    "y": round(xyz.y, 2),
                    "z": round(xyz.z, 2),
                    "behaviors": behavior_names,
                }
            )
        except Exception:
            continue

    logger.info(_div(f"interactive teleporters ({len(out)})"))

    for e in out:
        bn = ", ".join(e["behaviors"][:4]) + ("…" if len(e["behaviors"]) > 4 else "")
        logger.info(
            f"  {e['name']:<35}  ({e['x']:>8.1f}, {e['y']:>8.1f}, {e['z']:>7.1f})  [{bn}]"
        )

    return out


def _build_wad_index(world: str) -> list[tuple[str, str, str]]:
    from pathlib import Path as _Path
    from src.nav.wad_scraper import GAME_DATA_DIR

    gd = _Path(GAME_DATA_DIR)
    wad_index: list[tuple[str, str, str]] = []

    if gd.exists():
        for w in gd.glob(f"{world}-*.wad"):
            stem = w.name[:-4]
            zp = stem.replace("-", "/")
            tail = zp.rsplit("/", 1)[-1]
            wad_index.append((zp, tail, tail.replace("_", "").lower()))

    return wad_index


def _resolve_partner(
    partner: str | None,
    current_zone: str,
    wad_index: list[tuple[str, str, str]],
) -> str | None:
    if not partner:
        return None

    p = partner.strip()
    if p.lower().endswith(" exit"):
        p = p[:-5].strip()

    current_tail = current_zone.rsplit("/", 1)[-1]
    cur_norm = current_tail.replace("_", "").lower()
    full_norm = p.replace(" ", "").replace("_", "").lower()

    for zp, _tail, norm in wad_index:
        if norm == full_norm:
            return zp

    tokens = [
        t
        for t in p.split()
        if t.replace("_", "").lower() not in cur_norm
        and cur_norm not in t.replace("_", "").lower()
    ]
    if not tokens:
        tokens = p.split()

    target_norm = "_".join(tokens).replace("_", "").lower()
    if not target_norm:
        return None

    best: tuple[int, str] | None = None

    for zp, _tail, norm in wad_index:
        if norm == target_norm:
            return zp
        score = 0
        if target_norm in norm or norm in target_norm:
            score = min(len(target_norm), len(norm))
        else:
            for tok in tokens:
                tn = tok.replace("_", "").lower()
                if len(tn) >= 3 and tn in norm:
                    score += len(tn)
        if score >= 3 and (best is None or score > best[0]):
            best = (score, zp)

    return best[1] if best else None


async def process_current_zone(client: Client, append: bool = True) -> list[dict]:
    from src.nav.gate_recorder import (
        _ZONES_TXT,
        _load_existing_gates,
        _ensure_world_header,
    )

    zone = await _safe(client.zone_name(), "zone_name", None)
    if not zone:
        logger.warning("process_current_zone: client not in a zone")
        return []

    live = await enumerate_zone_gates(client)
    if not live:
        logger.info(f"process_current_zone: no live gates found in {zone}")
        return []

    world = zone.split("/")[0] if "/" in zone else zone
    wad_index = _build_wad_index(world)

    def _resolve(partner: str | None) -> str | None:
        return _resolve_partner(partner, zone, wad_index)

    parent_zone: str | None = None
    if "/Interiors/" in zone:
        all_gates = _load_existing_gates(_ZONES_TXT)
        for src, dst in all_gates:
            if dst == zone:
                parent_zone = src
                break

    resolved: list[dict] = []
    for e in live:
        dest = _resolve(e.get("partner"))
        if dest is None and e["kind"] == "other" and e["name"] == "Start":
            dest = parent_zone
        resolved.append(dict(e, dest_zone=dest))

    n_res = sum(1 for e in resolved if e["dest_zone"])
    logger.info(
        _div(f"process_current_zone  {zone}  ({n_res}/{len(resolved)} resolved)")
    )

    for e in resolved:
        tag = e["dest_zone"] or f"<? partner={e['partner']!r}>"
        logger.info(
            f"  [{e['kind']:<8}]  ({e['x']:>8.1f}, {e['y']:>8.1f}, {e['z']:>7.1f})  → {tag}"
        )

    if append:
        existing = _load_existing_gates(_ZONES_TXT)
        added = 0
        _ensure_world_header(_ZONES_TXT, world)
        with _ZONES_TXT.open("a", encoding="utf-8") as f:
            for e in resolved:
                if not (
                    (
                        e["kind"] == "exit"
                        or (e["kind"] == "other" and e["name"] == "Start")
                    )
                    and e["dest_zone"]
                ):
                    continue
                pair = (zone, e["dest_zone"])
                if pair in existing:
                    continue
                f.write(
                    f"GATE;standard;{e['x']};{e['y']};{e['z']};{zone};{e['dest_zone']}\n"
                )
                existing.add(pair)
                added += 1
        if added:
            logger.info(f"  → appended {added} new GATE rows to zones.txt")

    return resolved


# calibration


async def _settle_after_zone_change(client: Client, *, timeout: float = 6.0) -> None:
    import asyncio as _asyncio_local

    deadline = _asyncio_local.get_event_loop().time() + timeout

    # 1. loading screen UI gone.
    while _asyncio_local.get_event_loop().time() < deadline:
        try:
            if not await client.is_loading():
                break
        except Exception:
            pass
        await _asyncio_local.sleep(0.1)

    # 2. player body readable (entity struct repopulated).
    while _asyncio_local.get_event_loop().time() < deadline:
        try:
            await client.body.position()
            break
        except Exception:
            await _asyncio_local.sleep(0.1)

    # 3. teleport helper bound and idle.
    while _asyncio_local.get_event_loop().time() < deadline:
        try:
            if await client._teleport_helper.should_update() is False:
                break
        except Exception:
            pass
        await _asyncio_local.sleep(0.1)

    # final tiny breather - gives the game one frame to finish wiring input
    # focus before the caller's send_key/click_window lands
    await _asyncio_local.sleep(0.15)


async def walk_through_gate(
    client: Client,
    name_substring: str,
    back_distance: float = 250.0,
    hold_seconds: float = 4.0,
    yaw_offset: int = 0x074,
    max_attempts: int = 3,
    max_dist: float | None = None,
) -> bool:
    from src.combat.handler import NativeCombat
    import asyncio as _asyncio_top

    for attempt in range(1, max_attempts + 1):
        # if combat started (during a previous attempt, or because the
        # caller forgot to wait for combat to finish), drive it through
        # before walking. without this the next teleport silently fails
        # and the loop spins forever
        try:
            if await client.in_battle():
                logger.debug(
                    f"walk_through_gate: in combat (attempt {attempt}); "
                    "driving to completion before walking"
                )
                cfg = getattr(client, "combat_config", None)
                await NativeCombat(client, cfg).wait_for_combat()
                await _asyncio_top.sleep(0.5)
        except Exception as exc:
            logger.warning(f"walk_through_gate: combat-drive failed: {exc}")

        # escalate per attempt: 1.0x, 1.5x, 2.0x back, 1.0x, 1.25x, 1.5x hold.
        bd = back_distance * (1.0 + 0.5 * (attempt - 1))
        hs = hold_seconds * (1.0 + 0.25 * (attempt - 1))

        if attempt > 1:
            logger.debug(
                f"walk_through_gate: retry {attempt}/{max_attempts} "
                f"(back_distance={bd:.0f}, hold_seconds={hs:.1f})"
            )

        ok = await _walk_through_gate_once(
            client, name_substring, bd, hs, yaw_offset, max_dist=max_dist
        )
        if ok:
            return True

    logger.error(
        f"walk_through_gate: failed after {max_attempts} attempts for "
        f"'{name_substring}'. Player may be stuck on collision, or the "
        "gate trigger anchor doesn't reflect the actual portal location."
    )
    return False


async def _walk_through_gate_once(
    client: Client,
    name_substring: str,
    back_distance: float = 250.0,
    hold_seconds: float = 4.0,
    yaw_offset: int = 0x074,
    max_dist: float | None = None,
) -> bool:
    import asyncio as _asyncio
    from wizwalker import XYZ, Keycode

    mem = client.hook_handler
    zone_data_addr = await _read_zone_data_addr(client)

    if zone_data_addr == 0:
        logger.warning("walk_through_gate: not in a zone")
        return False

    list_addr = await _find_trigger_list(mem, zone_data_addr)

    if not list_addr:
        logger.warning("walk_through_gate: no trigger list found")
        return False

    needle = name_substring.lower()
    sentinel = await mem.read_typed(list_addr, Primitive.uint64)
    node = await mem.read_typed(sentinel, Primitive.uint64)
    visited = {sentinel}
    candidates: list[tuple[str, float, float, float, float]] = []
    # track every (kind, partner, resolved_dest, name) we see so a no-match
    # failure can tell the user what *is* available - "no gate to X" is far
    # more actionable when we can also print "but exits go to A, B, C."
    observed: list[tuple[str, str | None, str | None, str]] = []

    # build the wad index once so partner hints can be resolved to full zone
    # paths the user actually sees in process_current_zone output (e.g.
    # 'Marleybone/Interiors/MB_Event_Maestro/MB_Z04_ClandestineTower'). without
    # this the user's "MB_Z04_ClandestineTower" substring only matches the
    # short partner hint, which is often a different abbreviation entirely
    try:
        cur_zone_for_resolve = await client.zone_name() or ""
    except Exception:
        cur_zone_for_resolve = ""
    world_for_resolve = (
        cur_zone_for_resolve.split("/")[0]
        if "/" in cur_zone_for_resolve
        else cur_zone_for_resolve
    )
    wad_index = _build_wad_index(world_for_resolve) if world_for_resolve else []

    while node not in visited and node != 0:
        visited.add(node)
        data_addr = node + 0x10
        try:
            vt = await mem.read_typed(data_addr, Primitive.uint64)
        except Exception:
            break
        if vt >= _EXE_BASE:
            try:
                body = await mem.read_bytes(data_addr, max(0x80, yaw_offset + 8))
                name = await _read_msvc_string(mem, data_addr + 0x48)
                if name:
                    # match the substring against the literal trigger name,
                    # the raw partner hint, OR the wad-resolved dest_zone
                    # (the full path the user sees in process_current_zone)
                    # the dest_zone is what users actually think of as "the
                    # gate's destination," so it's the most natural input
                    kind, partner = _classify_trigger_name(name)
                    dest_zone = (
                        _resolve_partner(partner, cur_zone_for_resolve, wad_index)
                        if wad_index
                        else None
                    )
                    observed.append((kind, partner, dest_zone, name))
                    name_match = needle in name.lower()
                    partner_match = bool(partner) and needle in partner.lower()
                    dest_match = bool(dest_zone) and needle in dest_zone.lower()
                    if name_match or partner_match or dest_match:
                        px, py, pz = struct.unpack_from("<fff", body, 0x68)
                        (yaw,) = struct.unpack_from("<f", body, yaw_offset)
                        candidates.append((name, px, py, pz, yaw))
            except Exception:
                pass
        try:
            node = await mem.read_typed(node, Primitive.uint64)
        except Exception:
            break

    if not candidates:
        cur_zone = cur_zone_for_resolve or "<unknown>"
        dests = sorted({d for _, _, d, _ in observed if d})
        partners = sorted({p for _, p, _, _ in observed if p})
        if dests:
            hint = "available destinations: " + ", ".join(dests)
        elif partners:
            hint = (
                "no destinations resolved, but partner hints in this zone: "
                + ", ".join(partners)
            )
        elif observed:
            hint = (
                f"{len(observed)} trigger(s) in this zone but none have a parsed "
                "partner — try list_gates() to see raw names"
            )
        else:
            hint = "no trigger volumes in this zone at all"
        logger.warning(
            f"walk_through_gate: no trigger matching '{name_substring}' "
            f"in zone {cur_zone!r}. {hint}"
        )
        return False

    # pick the nearest match to the player. with a unique substring this is a
    # no-op (one candidate); with duplicates it gives the script a deterministic,
    # position-based tiebreak instead of "whichever came first in memory."
    try:
        player_pos = await client.body.position()
        ppx, ppy, ppz = player_pos.x, player_pos.y, player_pos.z
    except Exception:
        ppx = ppy = ppz = 0.0

    def _d2(c):
        _, x, y, z, _ = c
        dx, dy, dz = x - ppx, y - ppy, z - ppz
        return dx * dx + dy * dy + dz * dz

    if max_dist is not None:
        limit2 = max_dist * max_dist
        filtered = [c for c in candidates if _d2(c) <= limit2]
        if not filtered:
            logger.warning(
                f"walk_through_gate: {len(candidates)} trigger(s) matched "
                f"'{name_substring}' but none within {max_dist:.0f} units"
            )
            return False
        candidates = filtered

    candidates.sort(key=_d2)
    if len(candidates) > 1:
        logger.info(
            f"walk_through_gate: {len(candidates)} triggers matched "
            f"'{name_substring}'; picking nearest "
            f"({math.sqrt(_d2(candidates[0])):.0f}u away)"
        )

    name, px, py, pz, t = candidates[0]
    fx = math.sin(t)
    fy = math.cos(t)
    start_x = px - back_distance * fx
    start_y = py - back_distance * fy
    yaw_face = (t + math.pi) % (2 * math.pi)
    if yaw_face > math.pi:
        yaw_face -= 2 * math.pi

    logger.debug(
        f"walk_through_gate: '{name}'  anchor=({px:.1f},{py:.1f},{pz:.1f})"
        f"  yaw={math.degrees(t):+.1f}°  start=({start_x:.1f},{start_y:.1f},{pz:.1f})"
        f"  walk={hold_seconds:.1f}s"
    )

    try:
        zone_before = await client.zone_name()
    except Exception:
        zone_before = None

    try:
        await client.teleport(XYZ(start_x, start_y, pz), wait_on_inuse=True)
    except Exception as exc:
        logger.error(f"walk_through_gate: teleport failed: {exc}")
        return False

    await _asyncio.sleep(0.15)
    try:
        await client.body.write_yaw(yaw_face)
    except Exception as exc:
        logger.error(f"walk_through_gate: write_yaw failed: {exc}")
        return False
    await _asyncio.sleep(0.05)

    from ctypes import windll

    user32 = windll.user32
    hwnd = client.window_handle
    WM_KEYDOWN = 0x100
    WM_KEYUP = 0x101
    W_VK = Keycode.W.value

    # some gates trigger an "exit dungeon" confirmation popup partway through
    # the walk. if we don't dismiss it, the player just stands there pressing
    # w into a modal dialog until hold_seconds runs out and we report failure
    # questing/sigil/utils all use the same pattern: check dungeon_warning_path,
    # press ENTER. mirror that here so go_through_gate handles it transparently.
    from src.paths import dungeon_warning_path
    from src.utils import is_visible_by_path

    loop = _asyncio.get_event_loop()
    deadline = loop.time() + hold_seconds
    stop_reason = "timeout"
    zone_after = zone_before
    poll_counter = 0

    try:
        while loop.time() < deadline:
            user32.SendMessageW(hwnd, WM_KEYDOWN, W_VK, 0)
            await _asyncio.sleep(0.05)
            poll_counter += 1

            if poll_counter % 3 == 0:
                try:
                    if await is_visible_by_path(client, dungeon_warning_path):
                        logger.debug(
                            "walk_through_gate: exit-dungeon confirmation up; sending ENTER"
                        )
                        try:
                            await client.send_key(Keycode.ENTER, 0.1)
                        except Exception as exc:
                            logger.warning(
                                f"walk_through_gate: ENTER on dungeon warning failed: {exc}"
                            )
                except Exception:
                    pass
                try:
                    zone_now = await client.zone_name()
                except Exception:
                    zone_now = None
                if zone_now and zone_now != zone_before:
                    zone_after = zone_now
                    stop_reason = "zone_change"
                    break
    finally:
        user32.SendMessageW(hwnd, WM_KEYUP, W_VK, 0)

    if stop_reason == "zone_change":
        await _settle_after_zone_change(client)
        logger.debug(f"walk_through_gate: zone changed → '{zone_after}'")
        return True

    try:
        zone_after = await client.zone_name()
    except Exception:
        pass
    if zone_after and zone_after != zone_before:
        await _settle_after_zone_change(client)
        logger.debug(f"walk_through_gate: zone changed → '{zone_after}'")
        return True

    logger.warning(
        f"walk_through_gate: zone unchanged ('{zone_before}'). "
        "Try increasing back_distance or hold_seconds."
    )
    return False


def apply_calibration_fixes(
    min_samples: int = 3,
    max_xy_std: float = 50.0,
    min_offset: float = 20.0,
    dry_run: bool = False,
) -> dict:
    import json
    from pathlib import Path as _Path

    cal_path = _Path(__file__).parent / "data" / "calibration.jsonl"
    zones_path = _Path(__file__).parent / "data" / "zones.txt"

    stats = {
        k: 0
        for k in (
            "patched",
            "skipped_low_n",
            "skipped_high_var",
            "skipped_low_offset",
            "missing_in_zones",
            "total_pairs",
        )
    }

    if not cal_path.exists():
        logger.warning("apply_calibration_fixes: no calibration.jsonl yet")
        return stats
    if not zones_path.exists():
        logger.error("apply_calibration_fixes: zones.txt missing")
        return stats

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in cal_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            groups[(e["src"], e["dst"])].append(e)
        except Exception:
            pass

    stats["total_pairs"] = len(groups)

    fixes: dict[tuple[str, str], tuple[float, float, float, float, int]] = {}
    for (src, dst), entries in groups.items():
        n = len(entries)
        if n < min_samples:
            stats["skipped_low_n"] += 1
            continue
        actuals = [e["actual_xyz"] for e in entries]
        mx = sum(a[0] for a in actuals) / n
        my = sum(a[1] for a in actuals) / n
        mz = sum(a[2] for a in actuals) / n
        xystd = math.sqrt(sum((a[0] - mx) ** 2 + (a[1] - my) ** 2 for a in actuals) / n)
        if xystd > max_xy_std:
            stats["skipped_high_var"] += 1
            continue
        fixes[(src, dst)] = (mx, my, mz, xystd, n)

    if not fixes:
        logger.info("apply_calibration_fixes: no gates qualify")
        return stats

    lines = zones_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line in lines:
        parts = line.rstrip("\n").split(";")
        if parts[0] != "GATE" or len(parts) < 7:
            new_lines.append(line)
            continue
        key = (parts[5], parts[6])
        if key not in fixes:
            new_lines.append(line)
            continue
        seen.add(key)
        mx, my, mz, xystd, n = fixes[key]
        try:
            cx, cy, cz = float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            new_lines.append(line)
            continue
        offset = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2 + (mz - cz) ** 2)
        if offset < min_offset:
            stats["skipped_low_offset"] += 1
            new_lines.append(line)
            continue
        parts[2], parts[3], parts[4] = f"{mx:.1f}", f"{my:.1f}", f"{mz:.1f}"
        new_lines.append(";".join(parts) + "\n")
        stats["patched"] += 1
        logger.info(
            f"  PATCH  {key[0]} → {key[1]:<40}"
            f"  ({cx:.1f},{cy:.1f},{cz:.1f}) → ({mx:.1f},{my:.1f},{mz:.1f})"
            f"  n={n}  std={xystd:.1f}  Δ={offset:.1f}"
        )

    for key in fixes:
        if key not in seen:
            stats["missing_in_zones"] += 1
            logger.warning(f"  MISSING in zones.txt: {key[0]} → {key[1]}")

    if dry_run:
        logger.info(
            f"apply_calibration_fixes: dry run — would patch {stats['patched']}"
        )
    elif stats["patched"]:
        zones_path.write_text("".join(new_lines), encoding="utf-8")
        logger.info(
            f"apply_calibration_fixes: patched {stats['patched']} / {stats['total_pairs']}"
        )
    else:
        logger.info(
            f"apply_calibration_fixes: nothing to patch  "
            f"(low_n={stats['skipped_low_n']}  high_var={stats['skipped_high_var']}  "
            f"low_offset={stats['skipped_low_offset']})"
        )

    return stats


async def correlate_calibration() -> None:
    import json
    from pathlib import Path as _Path

    cal_path = _Path(__file__).parent / "data" / "calibration.jsonl"
    if not cal_path.exists():
        logger.warning("no calibration.jsonl yet — walk through gates first")
        return

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in cal_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            groups[(e["src"], e["dst"])].append(e)
        except Exception:
            pass

    logger.info(_div("calibration offsets  (actual − trigger center)"))
    logger.info(
        f"  {'src → dst':<55}  {'n':>3}   {'Δx':>7}  {'Δy':>7}  {'Δz':>7}   std"
    )
    logger.info("  " + "─" * 86)
    for (src, dst), entries in sorted(groups.items()):
        n = len(entries)
        actuals = [e["actual_xyz"] for e in entries]
        trig = entries[0]["trigger_xyz"]
        mx = sum(a[0] for a in actuals) / n
        my = sum(a[1] for a in actuals) / n
        mz = sum(a[2] for a in actuals) / n
        dx, dy, dz = mx - trig[0], my - trig[1], mz - trig[2]
        std = math.sqrt(
            sum((a[0] - mx) ** 2 + (a[1] - my) ** 2 + (a[2] - mz) ** 2 for a in actuals)
            / n
        )
        pair = f"{src} → {dst}"
        logger.info(
            f"  {pair:<55}  {n:>3}   {dx:>+7.1f}  {dy:>+7.1f}  {dz:>+7.1f}   {std:.1f}"
        )


def sanity_sweep_zones_txt() -> dict:
    from pathlib import Path as _Path

    path = _Path(__file__).parent / "data" / "zones.txt"
    if not path.exists():
        logger.error(f"sanity_sweep: file not found: {path}")
        return {}

    lines = path.read_text(encoding="utf-8").splitlines()
    declared_worlds: set[str] = set()
    gates_by_pair: dict[
        tuple[str, str], list[tuple[int, tuple[float, float, float]]]
    ] = defaultdict(list)
    raw_rows: dict[str, list[int]] = defaultdict(list)
    malformed: list[tuple[int, str, str]] = []
    bad_world_header: list[tuple[int, str]] = []
    bad_zone_path: list[tuple[int, str]] = []

    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s == "END":
            continue
        if s.startswith("WORLD"):
            parts = s.split("-", 1)
            if len(parts) == 2:
                declared_worlds.add(parts[1].strip())
            else:
                malformed.append((i, "bad WORLD header", line))
            continue
        if s.startswith("ENTRY"):
            continue
        if s.startswith("GATE"):
            raw_rows[s].append(i)
            parts = s.split(";")
            if len(parts) < 7:
                malformed.append((i, f"GATE wants 7 fields, got {len(parts)}", line))
                continue
            try:
                x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                malformed.append((i, "non-numeric XYZ", line))
                continue
            src, dst = parts[5], parts[6]
            for tag, zp in (("src", src), ("dst", dst)):
                if "/" not in zp or zp.startswith("/") or zp.endswith("/"):
                    bad_zone_path.append((i, f"{tag}={zp!r}"))
            if src.split("/", 1)[0] not in declared_worlds:
                bad_world_header.append(
                    (i, f"GATE for {src.split('/')[0]!r} has no WORLD header")
                )
            gates_by_pair[(src, dst)].append((i, (x, y, z)))

    pair_xyz_mismatch = [
        (p, r) for p, r in gates_by_pair.items() if len({x[1] for x in r}) > 1
    ]
    pair_exact_dups = [
        (p, [r[0] for r in rows])
        for p, rows in gates_by_pair.items()
        if len(rows) > 1 and len({r[1] for r in rows}) == 1
    ]
    exact_line_dups = {row: nums for row, nums in raw_rows.items() if len(nums) > 1}
    pair_set = set(gates_by_pair)
    orphans = [(s, d) for s, d in pair_set if (d, s) not in pair_set]

    total_gates = sum(len(v) for v in gates_by_pair.values())
    logger.info(
        _div(
            f"zones.txt audit  ({total_gates} gates  {len(gates_by_pair)} pairs  {len(declared_worlds)} worlds)"
        )
    )

    if malformed:
        logger.warning(f"  malformed ({len(malformed)})")
        for ln, why, raw in malformed[:20]:
            logger.warning(f"    L{ln}: {why}  →  {raw}")
    if exact_line_dups:
        logger.warning(f"  exact duplicate lines ({len(exact_line_dups)})")
        for raw, nums in list(exact_line_dups.items())[:20]:
            logger.warning(f"    lines {nums}: {raw}")
    if pair_exact_dups:
        logger.warning(f"  duplicate (src,dst) same XYZ ({len(pair_exact_dups)})")
        for pair, nums in pair_exact_dups[:10]:
            logger.warning(f"    {pair[0]} → {pair[1]}  lines {nums}")
    if pair_xyz_mismatch:
        logger.warning(f"  mismatched XYZ for same pair ({len(pair_xyz_mismatch)})")
        for pair, rows in pair_xyz_mismatch[:10]:
            logger.warning(f"    {pair[0]} → {pair[1]}")
            for ln, xyz in rows:
                logger.warning(
                    f"      L{ln}: ({xyz[0]:.1f}, {xyz[1]:.1f}, {xyz[2]:.1f})"
                )
    if bad_world_header:
        logger.warning(f"  missing WORLD header ({len(bad_world_header)})")
        for ln, msg in bad_world_header[:10]:
            logger.warning(f"    L{ln}: {msg}")
    if bad_zone_path:
        logger.warning(f"  suspicious zone paths ({len(bad_zone_path)})")
        for ln, msg in bad_zone_path[:10]:
            logger.warning(f"    L{ln}: {msg}")
    if orphans:
        logger.info(f"  one-way pairs ({len(orphans)})")
        for src, dst in orphans[:15]:
            logger.info(f"    {src} → {dst}")
        if len(orphans) > 15:
            logger.info(f"    … +{len(orphans) - 15} more")
    if not any(
        [
            malformed,
            exact_line_dups,
            pair_exact_dups,
            pair_xyz_mismatch,
            bad_world_header,
            bad_zone_path,
        ]
    ):
        logger.info("  ✓ no structural issues")

    return {
        "total_gates": total_gates,
        "unique_pairs": len(gates_by_pair),
        "malformed": len(malformed),
        "exact_line_dups": len(exact_line_dups),
        "pair_exact_dups": len(pair_exact_dups),
        "pair_xyz_mismatch": len(pair_xyz_mismatch),
        "missing_world_header": len(bad_world_header),
        "bad_zone_paths": len(bad_zone_path),
        "orphans": len(orphans),
    }


# yaw tools


async def probe_yaw_offset(client: Client, body_window: int = 0x200) -> dict:
    TWO_PI = 2 * math.pi

    mem = client.hook_handler
    zone_data_addr = await _read_zone_data_addr(client)

    if zone_data_addr == 0:
        return {}

    list_addr = await _find_trigger_list(mem, zone_data_addr)

    if not list_addr:
        logger.warning("probe_yaw_offset: no trigger list found")
        return {}

    sentinel = await mem.read_typed(list_addr, Primitive.uint64)
    node = await mem.read_typed(sentinel, Primitive.uint64)
    visited = {sentinel}
    bodies: list[tuple[str, bytes]] = []

    while node not in visited and node != 0 and len(bodies) < 256:
        visited.add(node)
        data_addr = node + 0x10
        try:
            vt = await mem.read_typed(data_addr, Primitive.uint64)
        except Exception:
            break
        if vt >= _EXE_BASE:
            try:
                body = await mem.read_bytes(data_addr, body_window)
                name = await _read_msvc_string(mem, data_addr + 0x48)
                if body and name:
                    bodies.append((name, body))
            except Exception:
                pass
        try:
            node = await mem.read_typed(node, Primitive.uint64)
        except Exception:
            break

    if not bodies:
        logger.warning("probe_yaw_offset: no trigger bodies collected")
        return {}

    n = len(bodies)

    def _var(vals: list[float]) -> float:
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        return sum((v - m) ** 2 for v in vals) / len(vals)

    # check single-float yaw candidates
    single: list[tuple[int, int, float, float]] = []
    for off in range(0x70, body_window - 4, 4):
        if 0x68 <= off < 0x74:
            continue
        vals = []
        for _name, body in bodies:
            if off + 4 > len(body):
                break
            (v,) = struct.unpack_from("<f", body, off)
            if math.isfinite(v) and abs(v) <= TWO_PI + 0.01:
                vals.append(v)
        if len(vals) >= n * 0.8 and _var(vals) >= 0.01:
            single.append((off, len(vals), _var(vals), sum(vals) / len(vals)))
    single.sort(key=lambda r: (-r[1], -r[2]))

    # check quaternion candidates (xyzw, unit length)
    quat: list[tuple[int, int, float]] = []
    for off in range(0x70, body_window - 16, 4):
        if 0x68 <= off < 0x74:
            continue
        ws = []
        hits = 0
        for _name, body in bodies:
            if off + 16 > len(body):
                break
            x, y, z, w = struct.unpack_from("<ffff", body, off)
            if not all(math.isfinite(v) for v in (x, y, z, w)):
                continue
            if not (0.95 < x * x + y * y + z * z + w * w < 1.05) or abs(w) < 0.05:
                continue
            hits += 1
            ws.append(w)
        if hits >= n * 0.8 and _var(ws) >= 0.0001:
            quat.append((off, hits, _var(ws)))
    quat.sort(key=lambda r: (-r[1], -r[2]))

    # check euler triple candidates (pitch/yaw/roll or similar)
    euler: list[tuple[int, int, float]] = []
    for off in range(0x70, body_window - 12, 4):
        if 0x68 <= off < 0x74:
            continue
        triples = []
        for _name, body in bodies:
            if off + 12 > len(body):
                break
            x, y, z = struct.unpack_from("<fff", body, off)
            if not all(math.isfinite(v) for v in (x, y, z)):
                continue
            if any(abs(v) > TWO_PI + 0.01 for v in (x, y, z)):
                continue
            if abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z) < 1e-6:
                continue
            triples.append((x, y, z))
        tv = sum(_var([t[i] for t in triples]) for i in range(3)) if triples else 0.0
        if len(triples) >= n * 0.5 and tv >= 0.01:
            euler.append((off, len(triples), tv))
    euler.sort(key=lambda r: (-r[1], -r[2]))

    logger.info(_div(f"probe yaw offset  ({n} triggers)"))

    logger.info(f"  single float  (top 5 of {len(single)})")
    for off, hits, var, mean in single[:5]:
        logger.info(
            f"    +0x{off:03x}   hits={hits}/{n}   var={var:.4f}   mean={mean:+.3f}"
        )
        for name, body in bodies[:5]:
            (v,) = (
                struct.unpack_from("<f", body, off)
                if off + 4 <= len(body)
                else (float("nan"),)
            )
            deg = math.degrees(v) if math.isfinite(v) else float("nan")
            logger.info(f"      {name[:48]:<48}  {v:>+8.4f} rad  ({deg:>+7.1f}°)")

    logger.info(f"  quaternion    (top 5 of {len(quat)})")
    for off, hits, var_w in quat[:5]:
        logger.info(f"    +0x{off:03x}   hits={hits}/{n}   var(w)={var_w:.4f}")
        for name, body in bodies[:5]:
            if off + 16 > len(body):
                continue
            x, y, z, w = struct.unpack_from("<ffff", body, off)
            yaw = 2 * math.atan2(z, w)
            logger.info(
                f"      {name[:48]:<48}  q=({x:+.3f},{y:+.3f},{z:+.3f},{w:+.3f})  yaw≈{math.degrees(yaw):>+7.1f}°"
            )

    logger.info(f"  euler triple  (top 5 of {len(euler)})")
    for off, hits, tv in euler[:5]:
        logger.info(f"    +0x{off:03x}   hits={hits}/{n}   var={tv:.4f}")
        for name, body in bodies[:5]:
            if off + 12 > len(body):
                continue
            x, y, z = struct.unpack_from("<fff", body, off)
            logger.info(
                f"      {name[:48]:<48}  ({x:>+8.4f}, {y:>+8.4f}, {z:>+8.4f}) rad"
            )

    return {
        "single_float": single[:10],
        "quaternion": quat[:10],
        "euler_triple": euler[:10],
        "n_triggers": n,
    }


async def verify_yaw(client: Client, yaw_offset: int = 0x074) -> list:
    mem = client.hook_handler
    zone_data_addr = await _read_zone_data_addr(client)

    if zone_data_addr == 0:
        logger.warning("verify_yaw: not in a zone")
        return []

    list_addr = await _find_trigger_list(mem, zone_data_addr)

    if not list_addr:
        logger.warning("verify_yaw: no trigger list found")
        return []

    logger.info(_div(f"verify yaw (+0x{yaw_offset:03x})"))
    logger.info(f"  {'Trigger':<50} {'X':>9} {'Y':>9} {'Z':>8}   {'Yaw°':>7}   Forward")
    logger.info("  " + "─" * 96)

    sentinel = await mem.read_typed(list_addr, Primitive.uint64)
    node = await mem.read_typed(sentinel, Primitive.uint64)
    visited = {sentinel}
    rows: list = []

    while node not in visited and node != 0 and len(rows) < 256:
        visited.add(node)
        data_addr = node + 0x10
        try:
            vt = await mem.read_typed(data_addr, Primitive.uint64)
        except Exception:
            break
        if vt >= _EXE_BASE:
            try:
                body = await mem.read_bytes(data_addr, max(0x80, yaw_offset + 8))
                name = await _read_msvc_string(mem, data_addr + 0x48)
                if body and name:
                    px, py, pz = struct.unpack_from("<fff", body, 0x68)
                    (yaw,) = struct.unpack_from("<f", body, yaw_offset)
                    fx = -math.sin(yaw)
                    fy = math.cos(yaw)
                    deg = math.degrees(yaw)
                    logger.info(
                        f"  {name[:50]:<50} {px:>9.1f} {py:>9.1f} {pz:>8.1f}"
                        f"   {deg:>+7.1f}°   ({fx:>+.3f}, {fy:>+.3f})"
                    )
                    rows.append((name, (px, py, pz), yaw, (fx, fy)))
            except Exception:
                pass
        try:
            node = await mem.read_typed(node, Primitive.uint64)
        except Exception:
            break

    logger.info(f"  {len(rows)} triggers verified")

    return rows
