"""Scan every locally-installed zone WAD and list all cantrip ritual chests.

A "cantrip chest" is the hidden chest a cantrip reveals - authored in the world
as a WizSpawnObjectInfo whose template basename matches ``*-Chest-Ritual-*``.
Like reagents they're DYNAMIC_SERVER spawns, so each one carries a "possible
list" of candidate nodes it can appear at.

Usage:  py -3.13 tools/scan_cantrip_chests.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from loguru import logger
from wizwalker.utils import get_wiz_install

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.spawns import ZoneSpawns  # noqa: E402

CHEST_RE = re.compile(r"chest[-_]ritual", re.IGNORECASE)
_JSON_PATH = Path(__file__).resolve().parent / "cantrip_chests.json"

# the deserializer trips on a slice of housing/minigame/dungeon WADs that use a
# spawnData encoding it doesn't handle yet. those carry no cantrip chests, so we
# mute the console but capture the failures into a list - the run footer reports
# them so a silent parser gap can never masquerade as "no chests here"
_parse_failures: list[str] = []
logger.remove()
logger.add(
    lambda m: _parse_failures.append(m.record["extra"].get("zone", "?"))
    if "failed to parse" in m.record["message"]
    else None,
    level="WARNING",
)

# outdoor/explorable zones are where cantrip chests live; a parse failure in one
# of these is worth surfacing loudly. dungeon/housing/minigame interiors are not
_BENIGN = re.compile(
    r"Interior|WorldData|LandingZone|Skel|Gauntlet|Dungeon|Cinematic|Arena|Raid|"
    r"Housing|PetGame|Derby|PhantomZone|Flight|Teleporter|Graduation|_Lite|Preview",
    re.IGNORECASE,
)


async def main() -> None:
    data_dir = get_wiz_install() / "Data" / "GameData"
    wads = sorted(data_dir.glob("*.wad"))

    zs = ZoneSpawns()
    names = await zs._load_template_names()
    chest_ids = {tid: nm for tid, nm in names.items() if CHEST_RE.search(nm)}
    if not chest_ids:
        sys.exit("no cantrip-chest templates in the manifest - manifest read failed?")
    print(f"{len(chest_ids)} cantrip-chest template ids in the manifest")
    print(f"scanning {len(wads)} wads...\n", flush=True)

    # world -> zone -> chest name -> [[x, y, z], ...] candidate node positions
    tree: dict[str, dict[str, dict[str, list[list[float]]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    placed: set[str] = set()
    zones_with = 0

    for i, wad in enumerate(wads, 1):
        # reconstruct the zone name; zone_spawns only uses it to rebuild the wad
        # filename (/<->- is symmetric), so the round-trip is exact. bind it onto
        # the logger so a parse failure is captured against the right zone
        zone = wad.stem.replace("-", "/")
        with logger.contextualize(zone=zone):
            try:
                spawns = await zs.zone_spawns(zone)
            except Exception:
                continue
        hits = {chest_ids[t]: p for t, p in spawns.items() if t in chest_ids}
        if not hits:
            continue
        zones_with += 1
        world, _, sub = zone.partition("/")
        for nm in sorted(hits):
            placed.add(nm)
            tree[world][sub][nm] = [
                [round(p.x, 2), round(p.y, 2), round(p.z, 2)] for p in hits[nm]
            ]
        if i % 200 == 0:
            print(f"  ...{i}/{len(wads)} wads, {zones_with} chest zones so far", flush=True)

    plain = {w: {z: dict(c) for z, c in zs_.items()} for w, zs_ in tree.items()}
    _JSON_PATH.write_text(json.dumps(plain, indent=1))

    total_nodes = sum(
        len(pts) for zs_ in tree.values() for c in zs_.values() for pts in c.values()
    )
    total_chests = sum(len(c) for zs_ in tree.values() for c in zs_.values())
    print("\n" + "=" * 70)
    print(f"{total_chests} cantrip chests across {zones_with} zones in "
          f"{len(tree)} worlds ({total_nodes} candidate node positions)")
    print(f"json -> {_JSON_PATH}")
    print("=" * 70)

    for world in sorted(tree):
        print(f"\n### {world}")
        for sub in sorted(tree[world]):
            for nm in sorted(tree[world][sub]):
                pts = tree[world][sub][nm]
                print(f"  {sub}  [{nm}]  ({len(pts)} nodes)")
                for x, y, z in pts:
                    print(f"      {x:>10.1f}  {y:>10.1f}  {z:>8.1f}")

    # --- safeguards: never let a parser gap or new content pass silently ---
    print("\n" + "=" * 70)
    print("DIAGNOSTICS")
    print("=" * 70)

    unplaced = sorted(set(chest_ids.values()) - placed)
    if unplaced:
        print(f"\n{len(unplaced)} chest templates in the manifest but placed in NO "
              f"scanned zone (authored-but-unused, or that zone's WAD isn't on disk):")
        for nm in unplaced:
            print(f"  {nm}")

    risky = sorted(z for z in _parse_failures if not _BENIGN.search(z))
    benign = len(_parse_failures) - len(risky)
    print(f"\n{len(_parse_failures)} zones failed to parse "
          f"({benign} benign dungeon/housing/minigame, {len(risky)} need a look):")
    for z in risky:
        print(f"  ! {z}")
    if not risky:
        print("  (none — every parse failure is a zone type that holds no cantrip chests)")


if __name__ == "__main__":
    asyncio.run(main())
