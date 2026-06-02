from __future__ import annotations

import struct
import zlib

from .reader import BitReader
from .typelist import F_DELTA_ENCODE, F_DEPRECATED, Property, TypeDef, TypeList

# SerializerFlags (katsuba serde.rs)
STATEFUL_FLAGS = 1 << 0
COMPACT_LENGTH_PREFIXES = 1 << 1
HUMAN_READABLE_ENUMS = 1 << 2
WITH_COMPRESSION = 1 << 3
FORBID_DELTA_ENCODE = 1 << 4

# default property mask (TRANSMIT | PRIVILEGED_TRANSMIT); only used in shallow
DEFAULT_PROPERTY_MASK = (1 << 3) | (1 << 4)

_RECURSION_LIMIT = 127

# sentinel: a type string that simple_data does not recognise -> it's an object
_NOT_SIMPLE = object()
_EMPTY = object()
_OPAQUE = object()  # an unknown property value we chose not to interpret


class Object(dict):
    __slots__ = ("type_hash",)

    def __init__(self, type_hash: int):
        super().__init__()
        self.type_hash = type_hash

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Object(0x{self.type_hash:08x}, {dict.__repr__(self)})"


class DeserializeError(Exception):
    pass


class Serializer:
    def __init__(
        self,
        types: TypeList,
        *,
        flags: int = 0,
        shallow: bool = True,
        skip_unknown_types: bool = False,
        recover_unknown: bool = False,
        property_mask: int = DEFAULT_PROPERTY_MASK,
        manual_compression: bool = False,
    ):
        if shallow and (skip_unknown_types or recover_unknown):
            raise DeserializeError("cannot skip/recover unknown types in shallow mode")
        self.types = types
        self.flags = flags
        self.shallow = shallow
        self.skip_unknown_types = skip_unknown_types
        # ``recover_unknown`` walks objects of an unregistered class generically
        # using the self-describing deep framing (per-object bit size, per-
        # property size+hash) so nested *known* objects are still recovered
        # lets a partial type list extract its targets from a full tree
        self.recover_unknown = recover_unknown
        self.property_mask = property_mask
        self.manual_compression = manual_compression
        self.unknown_properties: list[int] = []

    # entry
    def deserialize(self, data: bytes) -> Object:
        reader = self._configure(data)
        self.unknown_properties = []
        value = self._object(reader, 0)
        if value is _EMPTY:
            raise DeserializeError("root object cannot be null")
        return value

    def _configure(self, data: bytes) -> BitReader:
        flags = self.flags
        off = 0

        if self.manual_compression:
            data = _zlib_decompress(data)

        if flags & STATEFUL_FLAGS:
            flags = struct.unpack_from("<I", data, off)[0]
            off += 4

        if flags & WITH_COMPRESSION:
            compressed = data[off]
            off += 1
            if compressed != 0:
                data = _zlib_decompress(data[off:])
                off = 0

        self.flags = flags
        return BitReader(data[off:])

    # objects
    def _read_bit_size(self, reader: BitReader) -> int:
        if self.shallow:
            return 0
        v = reader.read_bits(32)
        return max(0, v - 32)  # saturating_sub(u32::BITS)

    def _object(self, reader: BitReader, depth: int):
        if depth > _RECURSION_LIMIT:
            raise DeserializeError("recursion limit exceeded")

        tag = reader.read_bits_aligned(32)
        if tag == 0:
            return _EMPTY

        type_def = self.types.get(tag)
        if type_def is None:
            object_size = self._read_bit_size(reader)
            if self.recover_unknown:
                return self._object_recover(reader, tag, object_size, depth)
            if not self.skip_unknown_types:
                raise DeserializeError(f"unknown type tag {tag}")
            # consume exactly the bits this object claims to occupy
            aligned = object_size & ~7
            reader.read_bytes(aligned >> 3)
            rem = object_size - aligned
            if rem:
                reader.read_bits(rem)
            return _EMPTY

        object_size = self._read_bit_size(reader)
        obj = Object(type_def.hash)
        if self.shallow:
            self._props_shallow(reader, type_def, obj, depth)
        else:
            self._props_deep(reader, object_size, type_def, obj, depth)
        return obj

    def _object_recover(
        self, reader: BitReader, tag: int, object_size: int, depth: int
    ):
        obj = Object(tag)  # keyed by property hash; type unknown
        while object_size > 0:
            prev = reader.bits_remaining()
            property_size = reader.read_bits_aligned(32)
            property_hash = reader.read_bits(32)
            header = prev - reader.bits_remaining()
            # valid framing always spends more than its header, so each pass
            # shrinks object_size. a property_size that doesn't clear the header
            # means we misread the region; without this guard the reader snaps
            # backwards and never reaches 0 (the depth cap can't catch a flat
            # loop). reject fast so the caller falls back to opaque
            if property_size < header:
                raise DeserializeError("non-progressing property (recover)")
            region_bits = property_size - header
            region_end = reader.pos + region_bits

            value = self._value_generic(reader, region_end, depth)
            reader.pos = region_end  # snap to the exact boundary regardless
            obj[property_hash] = value

            object_size -= property_size
            if object_size < 0:
                raise DeserializeError("object size underflow (recover)")
        return obj

    def _value_generic(self, reader: BitReader, region_end: int, depth: int):
        region_bits = region_end - reader.pos
        if region_bits < 64:  # too small to hold tag + bit-size header
            return _OPAQUE
        start = reader.pos
        compact = bool(self.flags & COMPACT_LENGTH_PREFIXES)

        # attempt: single nested object. a deep object is laid out as
        # [tag:32][bitsize_field:32][content], and the field equals
        # content_bits + 32. for a value region that is exactly one object,
        # content_bits == region_bits - 64, so field == region_bits - 32
        # that cheap equality gates the recursion - no blind backtracking
        if self._looks_like_object(reader, region_bits):
            try:
                val = self._object(reader, depth + 1)
                if reader.pos == region_end and val is not _EMPTY:
                    return val
            except (EOFError, DeserializeError):
                pass
            reader.pos = start

        # attempt: list of nested objects ([count][obj][obj]...). gate on the
        # first element's framing, then parse sequentially (linear, bounded)
        try:
            count = reader.read_container_length(compact)
            if 0 < count < 65536 and self._looks_like_object(reader, None):
                items = [self._object(reader, depth + 1) for _ in range(count)]
                if reader.pos == region_end and any(o is not _EMPTY for o in items):
                    return items
        except (EOFError, DeserializeError):
            pass
        reader.pos = start

        return _OPAQUE  # leave the snap-to-region_end to the caller

    def _looks_like_object(self, reader: BitReader, region_bits) -> bool:
        save = reader.pos
        try:
            tag = reader.read_bits_aligned(32)
            field = reader.read_bits(32)
        except EOFError:
            reader.pos = save
            return False
        reader.pos = save
        if tag == 0:
            return False
        if field < 32:
            return False
        if region_bits is not None:
            return field == region_bits - 32
        return True

    def _props_shallow(self, reader, type_def: TypeDef, obj: Object, depth: int):
        mask = self.property_mask
        for prop in type_def.properties.values():
            if not (prop.flags & mask) or (prop.flags & F_DEPRECATED):
                continue
            if prop.flags & F_DELTA_ENCODE:
                if not reader.read_bool():
                    if self.flags & FORBID_DELTA_ENCODE:
                        raise DeserializeError("missing delta-encoded property")
                    continue
            obj[prop.name] = self._property(reader, prop, depth)

    def _props_deep(
        self, reader, object_size: int, type_def: TypeDef, obj: Object, depth: int
    ):
        while object_size > 0:
            prev = reader.bits_remaining()
            property_size = reader.read_bits_aligned(32)
            property_hash = reader.read_bits(32)
            header = prev - reader.bits_remaining()
            # property_size covers the header it just consumed plus the value;
            # anything less is invalid framing that would skip backward and
            # stall the loop. reject rather than spin.
            if property_size < header:
                raise DeserializeError("non-progressing property")

            prop = type_def.properties.get(property_hash)
            if prop is None:
                # permissive extension: skip the property by its declared size
                consumed = prev - reader.bits_remaining()
                reader.skip_bits(property_size - consumed)
                self.unknown_properties.append(property_hash)
            else:
                value = self._property(reader, prop, depth)
                actual = prev - reader.bits_remaining()
                if property_size != actual:
                    raise DeserializeError(
                        f"property size mismatch for {prop.name}: "
                        f"expected {property_size}, got {actual}"
                    )
                obj[prop.name] = value

            object_size -= property_size
            if object_size < 0:
                raise DeserializeError("object size underflow")

    # properties
    def _property(self, reader: BitReader, prop: Property, depth: int):
        if prop.dynamic:
            n = reader.read_container_length(bool(self.flags & COMPACT_LENGTH_PREFIXES))
            if depth > _RECURSION_LIMIT:
                raise DeserializeError("recursion limit exceeded")
            return [self._property_value(reader, prop, depth + 1) for _ in range(n)]
        return self._property_value(reader, prop, depth)

    def _property_value(self, reader: BitReader, prop: Property, depth: int):
        if prop.is_enum():
            return self._enum(reader, prop)
        v = self._simple(reader, prop.type)
        if v is _NOT_SIMPLE:
            return self._object(reader, depth + 1)
        return v

    def _enum(self, reader: BitReader, prop: Property):
        if self.flags & HUMAN_READABLE_ENUMS:
            raw = reader.read_string(bool(self.flags & COMPACT_LENGTH_PREFIXES))
            text = raw.decode("utf-8", errors="replace")
            opt = prop.enum_options.get(text)
            if opt is None:
                return text  # lenient: keep the raw label
            try:
                return int(opt)
            except (TypeError, ValueError):
                return opt
        return reader.read_bits(32)

    def _simple(self, reader: BitReader, ty: str):
        # strings carry a length prefix whose encoding depends on a live flag
        if ty == "std::string":
            raw = reader.read_string(bool(self.flags & COMPACT_LENGTH_PREFIXES))
            return raw.decode("utf-8", errors="replace")
        if ty == "std::wstring":
            return reader.read_wstring(bool(self.flags & COMPACT_LENGTH_PREFIXES))
        fn = _SIMPLE.get(ty)
        if fn is None:
            return _NOT_SIMPLE
        return fn(reader)


def iter_objects(value, type_hash: int):
    if isinstance(value, Object):
        if value.type_hash == type_hash:
            yield value
        for v in value.values():
            yield from iter_objects(v, type_hash)
    elif isinstance(value, list):
        for v in value:
            yield from iter_objects(v, type_hash)


def _zlib_decompress(data: bytes) -> bytes:
    size = struct.unpack_from("<I", data, 0)[0]
    out = zlib.decompress(data[4:])
    if len(out) != size:
        raise DeserializeError(
            f"decompressed size mismatch: expected {size}, got {len(out)}"
        )
    return out


# primitive readers keyed by wiztype type string (katsuba simple_data.rs).
_SIMPLE = {
    "bool": lambda r: r.read_bool(),
    "char": lambda r: r.read_signed_bits_aligned(8),
    "unsigned char": lambda r: r.read_bits_aligned(8),
    "short": lambda r: r.read_signed_bits_aligned(16),
    "unsigned short": lambda r: r.read_bits_aligned(16),
    "wchar_t": lambda r: r.read_bits_aligned(16),
    "int": lambda r: r.read_signed_bits_aligned(32),
    "unsigned int": lambda r: r.read_bits_aligned(32),
    "long": lambda r: r.read_signed_bits_aligned(32),
    "unsigned long": lambda r: r.read_bits_aligned(32),
    "float": lambda r: r.read_float(),
    "double": lambda r: r.read_double(),
    "unsigned __int64": lambda r: r.read_bits_aligned(64),
    "gid": lambda r: r.read_bits_aligned(64),
    "union gid": lambda r: r.read_bits_aligned(64),
    "bi2": lambda r: r.read_signed_bits(2),
    "bui2": lambda r: r.read_bits(2),
    "bi3": lambda r: r.read_signed_bits(3),
    "bui3": lambda r: r.read_bits(3),
    "bi4": lambda r: r.read_signed_bits(4),
    "bui4": lambda r: r.read_bits(4),
    "bi5": lambda r: r.read_signed_bits(5),
    "bui5": lambda r: r.read_bits(5),
    "bi6": lambda r: r.read_signed_bits(6),
    "bui6": lambda r: r.read_bits(6),
    "bi7": lambda r: r.read_signed_bits(7),
    "bui7": lambda r: r.read_bits(7),
    "s24": lambda r: r.read_signed_bits(24),
    "u24": lambda r: r.read_bits(24),
    "class Color": lambda r: r.read_color(),
    "class Vector3D": lambda r: r.read_vec3(),
    "class Quaternion": lambda r: r.read_quat(),
    "class Euler": lambda r: r.read_euler(),
    "class Matrix3x3": lambda r: r.read_matrix(),
}
