from __future__ import annotations

import struct


class BitReader:
    __slots__ = ("data", "pos", "total")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0  # absolute bit offset from the start of ``data``
        self.total = len(data) * 8

    # core
    def bits_remaining(self) -> int:
        return self.total - self.pos

    def read_bits(self, nbits: int) -> int:
        if nbits == 0:
            return 0
        end = self.pos + nbits
        if end > self.total:
            raise EOFError("premature EOF in bit stream")
        data = self.data
        pos = self.pos
        result = 0
        got = 0
        while got < nbits:
            byte_i = pos >> 3
            bit_i = pos & 7
            take = 8 - bit_i
            if take > nbits - got:
                take = nbits - got
            chunk = (data[byte_i] >> bit_i) & ((1 << take) - 1)
            result |= chunk << got
            got += take
            pos += take
        self.pos = end
        return result

    def align(self) -> None:
        self.pos += (-self.pos) & 7

    def read_bits_aligned(self, nbits: int) -> int:
        self.align()
        return self.read_bits(nbits)

    def read_bytes(self, length: int) -> bytes:
        self.align()
        start = self.pos >> 3
        end = start + length
        if end > len(self.data):
            raise EOFError("premature EOF reading bytes")
        self.pos = end * 8
        return self.data[start:end]

    def skip_bits(self, nbits: int) -> None:
        if self.pos + nbits > self.total:
            raise EOFError("premature EOF skipping bits")
        self.pos += nbits

    # signed / bool
    @staticmethod
    def sign_extend(value: int, nbits: int) -> int:
        if value & (1 << (nbits - 1)):
            value -= 1 << nbits
        return value

    def read_signed_bits(self, nbits: int) -> int:
        return self.sign_extend(self.read_bits(nbits), nbits)

    def read_signed_bits_aligned(self, nbits: int) -> int:
        return self.sign_extend(self.read_bits_aligned(nbits), nbits)

    def read_bool(self) -> bool:
        return self.read_bits(1) != 0

    # length prefixes
    def read_compact_length(self) -> int:
        is_large = self.read_bool()
        return self.read_bits(31) if is_large else self.read_bits(7)

    def read_string_length(self, compact: bool) -> int:
        if compact:
            return self.read_compact_length()
        self.align()
        return self.read_bits(16)

    def read_container_length(self, compact: bool) -> int:
        if compact:
            return self.read_compact_length()
        self.align()
        return self.read_bits(32)

    # strings
    def read_string(self, compact: bool) -> bytes:
        n = self.read_string_length(compact)
        return self.read_bytes(n) if n else b""

    def read_wstring(self, compact: bool) -> str:
        n = self.read_string_length(compact)
        if not n:
            return ""
        self.align()
        return self.read_bytes(2 * n).decode("utf-16-le", errors="replace")

    # leaf math types
    def read_float(self) -> float:
        return struct.unpack("<f", struct.pack("<I", self.read_bits_aligned(32)))[0]

    def read_double(self) -> float:
        return struct.unpack("<d", struct.pack("<Q", self.read_bits_aligned(64)))[0]

    def read_vec3(self) -> tuple[float, float, float]:
        return struct.unpack("<3f", self.read_bytes(12))

    def read_quat(self) -> tuple[float, float, float, float]:
        w, x, y, z = struct.unpack("<4f", self.read_bytes(16))
        return (x, y, z, w)

    def read_euler(self) -> tuple[float, float, float]:
        pitch, yaw, roll = struct.unpack("<3f", self.read_bytes(12))
        return (pitch, yaw, roll)

    def read_matrix(self) -> tuple[tuple[float, ...], ...]:
        f = struct.unpack("<9f", self.read_bytes(36))
        return (f[0:3], f[3:6], f[6:9])

    def read_color(self) -> tuple[int, int, int, int]:
        b = self.read_bits_aligned(8)
        g = self.read_bits(8)
        r = self.read_bits(8)
        a = self.read_bits(8)
        return (r, g, b, a)
