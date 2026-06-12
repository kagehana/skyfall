from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from wizwalker.file_readers.wad import Wad
from wizwalker.utils import XYZ

from src.objprop import STATEFUL_FLAGS, Serializer, TypeDef, TypeList, iter_objects
from src.objprop.reader import BitReader

_TYPES_PATH = Path(__file__).resolve().parent.parent / "servertypes.json"
_CACHE_PATH = Path(__file__).resolve().parent / "nav" / "data" / "reagent_node_ids.json"

# class WizSpawnObjectInfo (servertypes.json)
_WSOI_HASH = 1839222684

# some zones (e.g. grizzleheim's GH_HFjord sub-zones) author their spawn list
# under a different, unregistered class hash that has the *identical* property
# layout as WizSpawnObjectInfo - same field hashes, same order. without a type
# def the deserializer recovers the field hashes but leaves every value opaque,
# so the zone reads as empty. we register each as a WSOI clone (see
# _register_wsoi_aliases) and scan for it alongside the canonical class
_WSOI_ALIAS_HASHES = (824433843,)
_WSOI_HASHES = (_WSOI_HASH, *_WSOI_ALIAS_HASHES)

# pathData.xml property hashes (stable engine-wide; the property hash is a
# function of name+type, so it's shared across every zone's path file)
_PD_PATHID = 2090569797  # m_pathID  (unsigned __int64)
_PD_NODES = 1430564382  # the path's ordered node-id list

# Root/TemplateManifest.xml -> class WizTemplateLocation property hashes.
_TM_FILENAME = 3117322428
_TM_ID = 2301988666
_REAGENT_PREFIX = "ObjectData/Reagent_Nodes/"


@dataclass(slots=True)
class Spawn:
    template_id: int
    path_id: int
    points: list[XYZ]


def _zone_wad_name(zone: str) -> str:
    return zone.replace("/", "-")


def _same_point(a: XYZ, b: XYZ, eps: float = 1.0) -> bool:
    return abs(a.x - b.x) < eps and abs(a.y - b.y) < eps and abs(a.z - b.z) < eps


_NODE_HEADER = 20  # bytes before the first record
_NODE_POS_OFFSET = 16  # position float-triple offset within a record


def _node_positions(node_data: bytes) -> dict[int, XYZ]:
    count = struct.unpack_from("<I", node_data, 16)[0]
    if count <= 0:
        return {}
    stride = (len(node_data) - _NODE_HEADER) // count
    if stride < _NODE_POS_OFFSET + 12:  # can't hold a position triple
        return {}

    out: dict[int, XYZ] = {}
    for k in range(count):
        base = _NODE_HEADER + _NODE_POS_OFFSET + stride * k
        x, y, z = struct.unpack_from("<3f", node_data, base)
        out[k + 1] = XYZ(x, y, z)
    return out


def _path_nodes(path_data: bytes) -> dict[int, list[int]]:
    flags = struct.unpack_from("<I", path_data, 4)[0]
    compact = bool(flags & 0x2)
    r = BitReader(path_data[8:])
    r.read_bits_aligned(32)  # root tag
    r.read_bits(32)  # root bit size
    r.read_bits_aligned(32)  # list property size
    r.read_bits(32)  # list property hash
    npaths = r.read_container_length(compact)

    out: dict[int, list[int]] = {}
    for _ in range(npaths):
        r.read_bits_aligned(32)  # element tag
        size = r.read_bits(32) - 32  # element bit size
        end = r.pos + size
        path_id = None
        nodes: list[int] = []
        while r.pos < end:
            before = r.bits_remaining()
            prop_size = r.read_bits_aligned(32)
            prop_hash = r.read_bits(32)
            if prop_hash == _PD_PATHID:
                path_id = r.read_bits_aligned(64)
            elif prop_hash == _PD_NODES:
                n = r.read_container_length(compact)
                nodes = [r.read_bits_aligned(64) for _ in range(n)]
            r.skip_bits(prop_size - (before - r.bits_remaining()))
        if path_id is not None:
            out[path_id] = nodes
    return out


class ZoneSpawns:
    def __init__(self, types_path: Optional[Path] = None):
        self._types = TypeList.open(str(types_path or _TYPES_PATH))
        self._register_wsoi_aliases()
        self._reagent_ids: Optional[dict[str, int]] = None
        self._template_names: Optional[dict[int, str]] = None
        self._zone_cache: dict[str, dict[int, list[XYZ]]] = {}

    def _register_wsoi_aliases(self) -> None:
        wsoi = self._types.get(_WSOI_HASH)
        if wsoi is None:
            return
        for h in _WSOI_ALIAS_HASHES:
            if self._types.get(h) is None:
                self._types.add(
                    TypeDef(name=wsoi.name, hash=h, properties=wsoi.properties)
                )

    # spawn points per zone
    async def zone_spawns(self, zone: str) -> dict[int, list[XYZ]]:
        if zone in self._zone_cache:
            return self._zone_cache[zone]

        result: dict[int, list[XYZ]] = {}
        try:
            wad = Wad.from_game_data(_zone_wad_name(zone))
            spawn_blob = await wad.get_file("spawnData.xml")
            path_blob = await wad.get_file("pathData.xml")
            node_blob = await wad.get_file("pathNodeData.bin")
        except (ValueError, FileNotFoundError, OSError) as exc:
            logger.debug(f"[spawns] no spawn data for {zone}: {exc}")
            self._zone_cache[zone] = result
            return result

        # parsing the spawn/path blobs can raise on a zone whose data trips the
        # deserializer (struct/bit-reader edge cases, recover_unknown walks)
        # contain it to this zone - returning {} - so one bad WAD can't abort a
        # caller sweeping many zones (e.g. farm_reagent), matching the missing-
        # data contract above
        try:
            node_pos = _node_positions(node_blob)
            path_nodes = _path_nodes(path_blob)

            ser = Serializer(
                self._types, flags=STATEFUL_FLAGS, shallow=False, recover_unknown=True
            )
            root = ser.deserialize(spawn_blob[4:])  # skip BINd magic
            spawn_objs = [o for h in _WSOI_HASHES for o in iter_objects(root, h)]
            for wsoi in spawn_objs:
                tid = wsoi.get("m_templateID.m_full")
                if tid is None:
                    continue

                pts: list[XYZ] = []
                # DYNAMIC_SERVER spawns carry no coordinate of their own - the
                # candidate set is every node of the assigned path (and we keep
                # accumulating if the same templateID owns several paths)
                for nid in path_nodes.get(wsoi.get("m_pathID"), ()):
                    if nid in node_pos:
                        pts.append(node_pos[nid])
                # statically placed spawns instead carry a real m_location; include
                # it so fixed-position reagents aren't dropped
                loc = wsoi.get("m_location")
                if loc is not None and (
                    abs(loc[0]) > 0.5 or abs(loc[1]) > 0.5 or abs(loc[2]) > 0.5
                ):
                    pts.append(XYZ(*loc))

                if pts:
                    bucket = result.setdefault(tid, [])
                    for p in pts:  # de-dup; paths/locations can overlap
                        if not any(_same_point(p, q) for q in bucket):
                            bucket.append(p)
        except Exception as exc:
            logger.warning(f"[spawns] failed to parse spawn data for {zone}: {exc}")
            result = {}

        self._zone_cache[zone] = result
        return result

    # reagent name -> world node template id
    async def reagent_node_id(self, reagent_name: str) -> Optional[int]:
        table = await self._load_reagent_ids()
        key = reagent_name.lower()
        return next((tid for name, tid in table.items() if name.lower() == key), None)

    async def reagent_points(self, zone: str, reagent_name: str) -> list[XYZ]:
        tid = await self.reagent_node_id(reagent_name)
        if tid is None:
            return []
        return (await self.zone_spawns(zone)).get(tid, [])

    async def reagent_spawns(self, zone: str) -> dict[str, list[XYZ]]:
        table = await self._load_reagent_ids()
        id_to_name = {tid: name for name, tid in table.items()}
        out: dict[str, list[XYZ]] = {}
        for tid, pts in (await self.zone_spawns(zone)).items():
            name = id_to_name.get(tid)
            if name is not None:
                out[name] = pts
        return out

    # every spawn node in a zone as flat (display name, point) rows, named via
    # the full template manifest. a DYNAMIC_SERVER spawn contributes one row per
    # node in its "possible list"; a statically placed one a single row. unknown
    # template ids fall back to #<id>. optional needle filters names (substring)
    async def spawn_nodes(
        self, zone: str, needle: Optional[str] = None
    ) -> list[tuple[str, XYZ]]:
        names = await self._load_template_names()
        key = needle.lower() if needle else None
        rows: list[tuple[str, XYZ]] = []
        for tid, pts in (await self.zone_spawns(zone)).items():
            name = names.get(tid, f"#{tid}")
            if key and key not in name.lower():
                continue
            rows.extend((name, p) for p in pts)
        rows.sort(key=lambda r: r[0].lower())
        return rows

    # manifest parsing (reagent display name -> id)
    async def _load_reagent_ids(self) -> dict[str, int]:
        if self._reagent_ids is not None:
            return self._reagent_ids

        if _CACHE_PATH.exists():
            try:
                self._reagent_ids = {
                    k: int(v) for k, v in json.loads(_CACHE_PATH.read_text()).items()
                }
                return self._reagent_ids
            except (ValueError, OSError):
                pass

        self._reagent_ids = await self._parse_reagent_manifest()
        try:
            _CACHE_PATH.write_text(json.dumps(self._reagent_ids, indent=0))
        except OSError:
            pass
        return self._reagent_ids

    # walk Root/TemplateManifest.xml, yielding (filename, templateID) for every
    # WizTemplateLocation. shared by the reagent-only index and the full
    # template-name map below
    async def _manifest_entries(self) -> list[tuple[str, int]]:
        wad = Wad.from_game_data("Root")
        data = await wad.get_file("TemplateManifest.xml")
        body = data[4:]  # skip BINd
        flags = struct.unpack_from("<I", body, 0)[0]
        off = 4
        compact = bool(flags & 0x2)
        if flags & 0x8:  # WITH_COMPRESSION
            compressed = body[off]
            off += 1
            if compressed:
                off += 4  # decompressed-size prefix
                body = zlib.decompress(body[off:])
                off = 0
        r = BitReader(body[off:])
        r.read_bits_aligned(32)  # root tag
        r.read_bits(32)  # root bit size
        r.read_bits_aligned(32)  # list property size
        r.read_bits(32)  # list property hash
        count = r.read_container_length(compact)

        out: list[tuple[str, int]] = []
        for _ in range(count):
            r.read_bits_aligned(32)
            size = r.read_bits(32) - 32
            end = r.pos + size
            fn = None
            mid = None
            while r.pos < end:
                before = r.bits_remaining()
                prop_size = r.read_bits_aligned(32)
                prop_hash = r.read_bits(32)
                if prop_hash == _TM_FILENAME:
                    fn = r.read_string(compact).decode("latin1")
                elif prop_hash == _TM_ID:
                    mid = r.read_bits_aligned(32)
                r.skip_bits(prop_size - (before - r.bits_remaining()))
            if fn and mid is not None:
                out.append((fn, mid))
        return out

    async def _parse_reagent_manifest(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for fn, mid in await self._manifest_entries():
            if fn.startswith(_REAGENT_PREFIX):
                name = fn[len(_REAGENT_PREFIX) :].removesuffix(".xml")
                out[name] = mid  # display case; lookups are case-insensitive
        logger.debug(f"[spawns] indexed {len(out)} reagent nodes from manifest")
        return out

    # templateID -> display name (file basename) for the whole manifest; lets
    # spawn_nodes label arbitrary entities (chests, NPCs, ...), not just
    # reagents. kept in-memory only - the full map is ~5 MB, not worth shipping
    async def _load_template_names(self) -> dict[int, str]:
        if self._template_names is not None:
            return self._template_names
        names: dict[int, str] = {}
        for fn, mid in await self._manifest_entries():
            names[mid] = fn.rsplit("/", 1)[-1].removesuffix(".xml")
        self._template_names = names
        logger.debug(f"[spawns] indexed {len(names)} template names from manifest")
        return names
