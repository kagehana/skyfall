from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

from wizwalker.file_readers.wad import Wad


GAME_DATA_DIR = Path(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData")

# match printable ASCII runs (length 6+) inside the BiND blob
_STRING_RE = re.compile(rb"[\x20-\x7e]{6,200}")

# after length-byte prefixes the BiND format leaves leading non-letter
# noise on most strings; trim it
_LEAD_TRIM_RE = re.compile(r"^[^A-Za-z(]+")

# trailing type tags: 'H', 'A', '`', etc. strip a single trailing tag char
# only if it's preceded by a "normal" closing char
_TAIL_TRIM_RE = re.compile(r"[`H]+$")

# patterns we recognise
_TELEPORT_LOC_RE = re.compile(r"Teleport location \(([^)]+)\)")
_ZONE_ENTRY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_ ]*?)ZoneEntryTrigger\b")
_ENTER_ZE_RE = re.compile(r"Enter_([A-Za-z][\w' ]*?) Zone Entry\b")

# gate-to pattern: must include a world prefix like WC_/KT_ to avoid prefix
# byte noise picking up. examples: "WC_GateCommons_ToUnicornWay",
# "KT_StoneGate_ToCrypt", "Trigger OpenGateToUW"
_GATE_TO_RE = re.compile(
    r"([A-Z]{2,4}_[A-Za-z0-9]*?(?:Gate|gate)[A-Za-z]*?)_?(?:To|TO|to)([A-Z][A-Za-z0-9_]+?)(?=[A-Z@`H]?\b|$)"
)
_TRIGGER_TP_RE = re.compile(r"Trigger \(Teleport to ([^)]+?)\)")
_ENTER_POI_RE = re.compile(r"Enter_([A-Za-z][\w' ]*?)POI\b")

# Newer worlds (Wallaru, Lemuria, Novus): "Teleport to <Dest>" without parens
_TELEPORT_TO_RE = re.compile(r"Teleport to ([A-Za-z][\w]*)")

# Direct zone-path strings: "Wallaru/WL_Z01_Hub", "Arcanum/AR_Z01_Hub", etc
# anchor to a known world list to avoid catching BiND length-byte prefixes
_KNOWN_WORLDS = (
    "WizardCity",
    "Krokotopia",
    "MarleyBone",
    "MooShu",
    "DragonSpire",
    "Grizzleheim",
    "GrizzleheimLite",
    "Celestia",
    "Wysteria",
    "Zafaria",
    "Avalon",
    "Azteca",
    "Khrysalis",
    "Polaris",
    "Mirage",
    "Empyrea",
    "Karamelle",
    "Lemuria",
    "Novus",
    "Wallaru",
    "Aquila",
    "Arcanum",
    "Test_Realm",
    "Housing",
    "Heroic_Dungeons_01",
    "MonthlyEvents",
    "WorldData",
    "Cantrips",
    "Pet_Promenade",
    "Pet_Pavilion",
)

_ZONE_PATH_RE = re.compile(r"\b(" + "|".join(_KNOWN_WORLDS) + r")/([A-Z][\w/]{2,80})")

# "Trigger_TeleportSource_<Name>" / "Trigger_<ZoneSubPath>"
_TRIGGER_PREFIX_RE = re.compile(r"Trigger_(?:TeleportSource_)?([A-Z][\w]+)")


@dataclass
class WadFindings:
    wad: str
    zone: str
    teleport_locations: list[str] = field(default_factory=list)
    teleport_to: list[str] = field(default_factory=list)
    zone_entry_triggers: list[str] = field(default_factory=list)
    enter_zone_entries: list[str] = field(default_factory=list)
    gate_to: list[str] = field(default_factory=list)
    trigger_teleport_to: list[str] = field(default_factory=list)
    poi_entries: list[str] = field(default_factory=list)
    zone_path_refs: list[str] = field(default_factory=list)
    trigger_names: list[str] = field(default_factory=list)
    raw_destination_strings: list[str] = field(default_factory=list)
    error: str | None = None


def _clean(s: str) -> str:
    s = _LEAD_TRIM_RE.sub("", s)
    s = _TAIL_TRIM_RE.sub("", s)

    return s.strip()


def _wad_to_zone(wad_name: str) -> str:
    stem = wad_name[:-4] if wad_name.endswith(".wad") else wad_name

    return stem.replace("-", "/")


def _extract_strings(blob: bytes) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for m in _STRING_RE.findall(blob):
        s = _clean(m.decode("ascii", "replace"))

        if not s or s in seen:
            continue

        seen.add(s)
        out.append(s)

    return out


def _classify(strings: list[str], findings: WadFindings) -> None:
    for s in strings:
        matched = False

        if m := _TELEPORT_LOC_RE.search(s):
            findings.teleport_locations.append(m.group(1).strip())
            findings.raw_destination_strings.append(s)

            matched = True
        if m := _ZONE_ENTRY_RE.search(s):
            findings.zone_entry_triggers.append(m.group(1).strip())

            matched = True
        if m := _ENTER_ZE_RE.search(s):
            findings.enter_zone_entries.append(m.group(1).strip())
            findings.raw_destination_strings.append(s)

            matched = True
        if m := _GATE_TO_RE.search(s):
            gate, dest = m.group(1), m.group(2)

            # strip lone trailing tag char (BiND end-of-string marker)
            if dest.endswith(("A", "H")) and len(dest) > 2 and dest[-2].islower():
                dest = dest[:-1]

            findings.gate_to.append(f"{gate} -> {dest}")
            findings.raw_destination_strings.append(s)
            matched = True
        if m := _TRIGGER_TP_RE.search(s):
            findings.trigger_teleport_to.append(m.group(1).strip())
            findings.raw_destination_strings.append(s)

            matched = True
        if m := _ENTER_POI_RE.search(s):
            findings.poi_entries.append(m.group(1).strip())

            matched = True

        # newer-world conventions
        for m in _TELEPORT_TO_RE.finditer(s):
            findings.teleport_to.append(m.group(1).strip())
            findings.raw_destination_strings.append(s)

            matched = True
        for m in _ZONE_PATH_RE.finditer(s):
            full = f"{m.group(1)}/{m.group(2)}"

            # strip BiND trailing tag char if present
            if full.endswith(("A", "H")) and full[-2:-1].islower():
                full = full[:-1]

            findings.zone_path_refs.append(full)

            matched = True
        if m := _TRIGGER_PREFIX_RE.search(s):
            findings.trigger_names.append(m.group(1).strip())
            matched = True
        _ = matched  # placeholder for future "unmatched" diagnostic if needed


async def scrape_wad(wad_path: Path) -> WadFindings:
    findings = WadFindings(wad=wad_path.name, zone=_wad_to_zone(wad_path.name))
    w = Wad(wad_path)

    try:
        try:
            blob = await w.get_file("triggers.xml")
        except Exception as e:
            findings.error = f"no triggers.xml: {e}"

            return findings

        strings = _extract_strings(blob)

        _classify(strings, findings)
    finally:
        w.close()

    return findings


async def scrape_all(filter_substr: str | None = None) -> list[WadFindings]:
    if not GAME_DATA_DIR.exists():
        raise SystemExit(f"GameData not found: {GAME_DATA_DIR}")

    wads = sorted(GAME_DATA_DIR.glob("*.wad"))

    if filter_substr:
        wads = [w for w in wads if filter_substr.lower() in w.name.lower()]

    print(f"scraping {len(wads)} WADs ...", file=sys.stderr)

    out: list[WadFindings] = []

    for i, wp in enumerate(wads):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{len(wads)} ...", file=sys.stderr)
        try:
            f = await scrape_wad(wp)
        except Exception as e:
            f = WadFindings(
                wad=wp.name,
                zone=_wad_to_zone(wp.name),
                error=f"{type(e).__name__}: {e}",
            )

        # skip wads that yielded no transitions and no error
        if (
            f.teleport_locations
            or f.teleport_to
            or f.zone_entry_triggers
            or f.enter_zone_entries
            or f.gate_to
            or f.trigger_teleport_to
            or f.poi_entries
            or f.zone_path_refs
            or f.trigger_names
            or f.error
        ):
            out.append(f)

    return out


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--zone", help="filter substring on wad filename")
    parser.add_argument("--out", default="scrape_dump.json", help="output JSON path")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print compact human-readable summary instead of full JSON",
    )

    args = parser.parse_args()
    results = asyncio.run(scrape_all(args.zone))

    if args.summary:
        for r in results:
            if r.error:
                print(f"[ERR] {r.zone}: {r.error}")

                continue

            total = (
                len(r.teleport_locations)
                + len(r.teleport_to)
                + len(r.zone_entry_triggers)
                + len(r.enter_zone_entries)
                + len(r.gate_to)
                + len(r.trigger_teleport_to)
                + len(r.poi_entries)
                + len(r.zone_path_refs)
                + len(r.trigger_names)
            )

            print(f"{r.zone}  ({total} hits)")

            for tl in r.teleport_locations:
                print(f"    teleport-loc: {tl}")
            for tt in r.teleport_to:
                print(f"    teleport-to: {tt}")
            for zp in r.zone_path_refs:
                print(f"    zone-path: {zp}")
            for ze in r.enter_zone_entries:
                print(f"    zone-entry: {ze}")
            for g in r.gate_to:
                print(f"    gate: {g}")
            for t in r.trigger_teleport_to:
                print(f"    trigger-tp: {t}")
            for p in r.poi_entries:
                print(f"    poi: {p}")
            for tn in r.trigger_names:
                print(f"    trigger: {tn}")

        return

    out_path = Path(args.out)

    out_path.write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"wrote {out_path} ({len(results)} zones)", file=sys.stderr)


if __name__ == "__main__":
    main()
