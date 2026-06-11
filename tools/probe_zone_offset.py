"""Probe the scraper's current-zone offset against a live client.

Confirms (independently of the scraper) that the client is in a zone, then checks
whether `base + 0x21348 -> +0xD8 -> zone_data` still resolves to a walkable trigger
list. If it doesn't, scans nearby base offsets to find the one that does.

Usage:  py -3.13 tools/probe_zone_offset.py
"""

import asyncio
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymem
import pymem.process

from wizwalker import ClientHandler
from wizwalker.memory.memory_reader import Primitive

from src.nav.scraper import _read_msvc_string, _find_trigger_list

CUR_OFFSET = 0x21348      # what the scraper hardcodes today
ZONE_DATA_OFFSET = 0xD8
SCAN_RADIUS = 0x800       # +/- bytes around CUR_OFFSET to sweep
EXE_NAME = "WizardGraphicalClient.exe"


async def count_named_gates(mem, zone_data_addr: int) -> int:
    """How many named trigger nodes the scraper logic finds off this zone_data."""
    list_addr = await _find_trigger_list(mem, zone_data_addr)
    if not list_addr:
        return 0
    try:
        sentinel = await mem.read_typed(list_addr, Primitive.uint64)
        head = await mem.read_typed(sentinel, Primitive.uint64)
    except Exception:
        return 0

    named = 0
    node = head
    visited = {sentinel}
    while node not in visited and node != 0 and len(visited) < 256:
        visited.add(node)
        nm = await _read_msvc_string(mem, node + 0x10 + 0x48)
        if nm and len(nm) >= 3:
            named += 1
        try:
            node = await mem.read_typed(node, Primitive.uint64)
        except Exception:
            break
    return named


async def probe(client, idx: int):
    print(f"\n========== client #{idx} ==========")
    # No activate_hooks(): pure ReadProcessMemory works unhooked, and re-hooking an
    # already-hooked client fails the autobot pattern scan.

    # Independent "are we in a zone" signal (wizwalker's own path), best-effort.
    try:
        zname = await client.zone_name()
    except Exception as exc:
        zname = f"<unavailable unhooked: {type(exc).__name__}>"
    print(f"  wizwalker zone_name(): {zname!r}")

    mem = client.hook_handler
    base = await client.game_client.read_base_address()
    print(f"  base address:          0x{base:X}")

    module = pymem.process.module_from_name(mem.process.process_handle, EXE_NAME)
    mod_base, mod_end = module.lpBaseOfDll, module.lpBaseOfDll + module.SizeOfImage
    print(f"  {EXE_NAME}: 0x{mod_base:X} - 0x{mod_end:X}")

    def is_heap(p: int) -> bool:
        return 0x10000 < p < 0x7FFFFFFFFFFF and not (mod_base <= p < mod_end)

    # What the scraper reads right now.
    cur_zone = await mem.read_typed(base + CUR_OFFSET, Primitive.uint64)
    print(f"\n  *(base+0x{CUR_OFFSET:X}) = 0x{cur_zone:X}   "
          f"{'<-- ZERO => reports not-in-zone' if cur_zone == 0 else ''}")
    if cur_zone:
        try:
            zd = await mem.read_typed(cur_zone + ZONE_DATA_OFFSET, Primitive.uint64)
            gates = await count_named_gates(mem, zd) if is_heap(zd) else 0
            print(f"    +0x{ZONE_DATA_OFFSET:X} zone_data = 0x{zd:X}  named gates: {gates}")
            if gates:
                print("    => current offset STILL WORKS for this client.")
                return
        except Exception as exc:
            print(f"    +0x{ZONE_DATA_OFFSET:X} read failed ({type(exc).__name__}) "
                  f"=> 0x{cur_zone:X} is not a valid object pointer.")

    # Sweep nearby offsets for a working two-level chain.
    print(f"\n  scanning base +/- 0x{SCAN_RADIUS:X} for a working zone chain...")
    hits = []
    lo = (CUR_OFFSET - SCAN_RADIUS) & ~0x7
    hi = CUR_OFFSET + SCAN_RADIUS
    for off in range(lo, hi + 1, 8):
        try:
            zone = await mem.read_typed(base + off, Primitive.uint64)
        except Exception:
            continue
        if not is_heap(zone):
            continue
        try:
            zd = await mem.read_typed(zone + ZONE_DATA_OFFSET, Primitive.uint64)
        except Exception:
            continue
        if not is_heap(zd):
            continue
        gates = await count_named_gates(mem, zd)
        if gates:
            hits.append((off, zone, zd, gates))

    if not hits:
        print("    no working offset found in range "
              "(client may not be fully in a zone, or 0xD8/list layout changed).")
        return

    hits.sort(key=lambda h: h[3], reverse=True)
    print(f"    {'offset':>10}  {'zone ptr':>16}  {'zone_data':>16}  gates")
    for off, zone, zd, gates in hits:
        flag = "  <-- current" if off == CUR_OFFSET else ""
        print(f"    0x{off:08X}  0x{zone:014X}  0x{zd:014X}  {gates:>5}{flag}")
    best = hits[0][0]
    print(f"\n  BEST: 0x{best:X}"
          + (f"  (delta {best - CUR_OFFSET:+#x} from current 0x{CUR_OFFSET:X})"
             if best != CUR_OFFSET else "  == current offset"))


async def main():
    handler = ClientHandler()
    clients = handler.get_new_clients()
    print(f"found {len(clients)} client(s)")
    try:
        for i, c in enumerate(clients, 1):
            try:
                await probe(c, i)
            except Exception as exc:
                print(f"  client #{i} probe failed: {type(exc).__name__}: {exc}")
    finally:
        await handler.close()


if __name__ == "__main__":
    asyncio.run(main())
