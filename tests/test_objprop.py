import struct

import pytest

from src.objprop import Object, Serializer, TypeList, iter_objects
from src.objprop.reader import BitReader
from src.objprop.typelist import Property, TypeDef


# ── BitReader ─────────────────────────────────────────────────────────────
class TestBitReader:
    def test_byte_reads_are_little_endian(self):
        r = BitReader(bytes([0xAB, 0xCD]))
        assert r.read_bits(8) == 0xAB
        assert r.read_bits(8) == 0xCD

    def test_multibyte_is_little_endian(self):
        assert BitReader(bytes([0xAB, 0xCD])).read_bits(16) == 0xCDAB
        assert BitReader(bytes([1, 0, 0, 0])).read_bits(32) == 1

    def test_sub_byte_lsb_first(self):
        r = BitReader(bytes([0b10101011]))
        assert r.read_bits(4) == 0b1011  # low nibble first
        assert r.read_bits(4) == 0b1010

    def test_align_advances_to_byte_boundary(self):
        r = BitReader(bytes([0xFF, 0x7E]))
        r.read_bits(1)
        r.align()
        assert r.pos == 8
        assert r.read_bits(8) == 0x7E

    def test_sign_extend(self):
        # 5-bit two's complement 0b11111 == -1
        r = BitReader(bytes([0b00011111]))
        assert r.read_signed_bits(5) == -1

    def test_compact_length_small_and_large(self):
        assert BitReader(bytes([0x10])).read_compact_length() == 8
        # is_large=1, then 200 across the next 31 bits
        assert BitReader(bytes([0x91, 0x01, 0x00, 0x00])).read_compact_length() == 200

    def test_read_string_compact(self):
        # compact length 3 (0x06 -> is_large=0, 7-bit value 3) then "abc"
        data = bytes([0x06]) + b"abc"
        assert BitReader(data).read_string(compact=True) == b"abc"

    def test_read_float(self):
        data = struct.pack("<f", 1234.5)
        assert BitReader(data).read_float() == pytest.approx(1234.5)

    def test_read_vec3(self):
        data = struct.pack("<3f", 1.0, -2.0, 3.5)
        assert BitReader(data).read_vec3() == pytest.approx((1.0, -2.0, 3.5))


# ── TypeList / Property ───────────────────────────────────────────────────
class TestTypeList:
    def test_loads_and_indexes_by_hash(self):
        tl = TypeList.from_dict(
            {
                "class Foo": {
                    "hash": 42,
                    "properties": {
                        "m_x": {
                            "type": "int",
                            "id": 0,
                            "flags": 31,
                            "dynamic": False,
                            "hash": 7,
                        },
                    },
                }
            }
        )
        td = tl.get(42)
        assert td is not None and td.name == "class Foo"
        assert td.properties[7].name == "m_x"

    def test_is_enum_detection(self):
        p_enum = Property("m_e", "enum eSomething", 0, 0, False, 1)
        p_flag = Property("m_f", "int", 0, 1 << 21, False, 2)  # ENUM flag
        p_plain = Property("m_p", "int", 0, 31, False, 3)
        assert p_enum.is_enum() and p_flag.is_enum()
        assert not p_plain.is_enum()


# ── Serializer round-trip on a hand-built deep object ─────────────────────
class TestSerializer:
    def _types(self):
        # class Foo { int m_v; }  (hash 100, property hash 200)
        return TypeList(
            {
                100: TypeDef(
                    "class Foo",
                    100,
                    {200: Property("m_v", "int", 0, 31, False, 200)},
                )
            }
        )

    def _deep_foo(self, value: int) -> bytes:
        prop = struct.pack("<i", value)  # 32-bit value
        prop_size = 32 + 32 + 32  # propsize + prophash + value, in bits
        body = struct.pack("<I", prop_size) + struct.pack("<I", 200) + prop
        obj_size_field = len(body) * 8 + 32  # reader does saturating_sub(32)
        blob = (
            struct.pack("<I", 0)  # stateful flags = 0 (plain)
            + struct.pack("<I", 100)  # tag
            + struct.pack("<I", obj_size_field)
            + body
        )
        return blob

    def test_deep_deserialize_scalar(self):
        from src.objprop import STATEFUL_FLAGS

        ser = Serializer(self._types(), flags=STATEFUL_FLAGS, shallow=False)
        obj = ser.deserialize(self._deep_foo(-7))
        assert isinstance(obj, Object)
        assert obj.type_hash == 100
        assert obj["m_v"] == -7

    def test_iter_objects_walks_nested(self):
        inner = Object(100)
        inner["m_v"] = 5
        outer = Object(999)
        outer["kids"] = [inner, "noise", 3]
        found = list(iter_objects(outer, 100))
        assert found == [inner]


# ── End-to-end resolver (needs the game install + zone WAD) ───────────────
def _austrilund_available() -> bool:
    try:
        from wizwalker.file_readers.wad import Wad

        return Wad.from_game_data(
            "Grizzleheim-GH_HFjord-GH_Austrilund"
        ).file_path.exists()
    except Exception:
        return False


@pytest.mark.skipif(not _austrilund_available(), reason="zone WAD not installed")
def test_black_lotus_resolution():
    import asyncio

    from src.spawns import ZoneSpawns

    async def _run():
        zs = ZoneSpawns()
        zone = "Grizzleheim/GH_HFjord/GH_Austrilund"
        # case-insensitive name resolution
        assert await zs.reagent_node_id("black lotus") == 175095
        pts = await zs.reagent_points(zone, "Black Lotus")
        assert len(pts) == 10
        # nodes are spread across the zone, not at the origin
        assert all(abs(p.x) + abs(p.y) > 1.0 for p in pts)

        # the zone-wide reagent map keeps display casing and includes Lotus
        spawns = await zs.reagent_spawns(zone)
        assert "Black Lotus" in spawns
        assert spawns["Black Lotus"] == pts
        assert {"Stone", "Ore", "Frost Flower", "Wood"} <= set(spawns)

    # Match the suite's loop handling; asyncio.run() would close the shared
    # loop that other test modules reuse via get_event_loop().
    asyncio.get_event_loop().run_until_complete(_run())
