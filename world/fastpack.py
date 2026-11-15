"""
Fast pure-Python helpers for chunk section encoding.

Chunk sections hold 4096 block states; encoding them one block at a time in
nested Python loops costs ~150 ms per chunk, which made far chunks arrive
tens of seconds late. These helpers work on whole lists with slices,
comprehensions and C-level builtins instead (no numpy dependency).
"""

from __future__ import annotations

import struct
from itertools import chain

_U64 = 1 << 64
_I64_MAX = 1 << 63


def flatten_section(section_blocks) -> list[int]:
    """[16][16][16] (y, z, x) -> flat list in y*256 + z*16 + x order."""
    return list(chain.from_iterable(chain.from_iterable(section_blocks)))


def palette_of(flat: list[int]) -> tuple[list[int], list[int]]:
    """(palette in first-seen order, palette index of every entry)."""
    palette = list(dict.fromkeys(flat))
    if len(palette) == 1:
        return palette, [0] * len(flat)
    index = {value: i for i, value in enumerate(palette)}
    return palette, list(map(index.__getitem__, flat))


def pack_longs(entries: list[int], bits: int) -> list[int]:
    """
    Pack entries into unsigned 64-bit longs, entry i of each long at bit
    i*bits, no entry spanning two longs (the 1.16+ layout).
    """
    per_long = 64 // bits
    mask = (1 << bits) - 1
    count = -(-len(entries) // per_long)
    padded = list(entries) + [0] * (count * per_long - len(entries))
    if padded and (max(padded) > mask or min(padded) < 0):
        padded = [v & mask for v in padded]
    longs = padded[0::per_long]
    for i in range(1, per_long):
        shift = i * bits
        longs = [acc | (v << shift) for acc, v in zip(longs, padded[i::per_long])]
    return longs


def to_signed(longs: list[int]) -> list[int]:
    return [v - _U64 if v >= _I64_MAX else v for v in longs]


def to_unsigned(longs) -> list[int]:
    return [v + _U64 if v < 0 else v for v in longs]


def longs_to_bytes(longs: list[int]) -> bytes:
    """Unsigned longs -> big-endian bytes (network Long array body)."""
    return struct.pack(f">{len(longs)}Q", *longs)


def unpack_longs(longs, bits: int, total: int) -> list[int]:
    """Inverse of pack_longs (accepts signed or unsigned longs)."""
    if bits <= 0:
        return [0] * total
    per_long = 64 // bits
    mask = (1 << bits) - 1
    values = to_unsigned(longs)
    out = [0] * (len(values) * per_long)
    for i in range(per_long):
        shift = i * bits
        out[i::per_long] = [(v >> shift) & mask for v in values]
    if len(out) < total:
        out.extend([0] * (total - len(out)))
    return out[:total]


def column_heights(chunk_blocks, skip: int | None = None) -> list[int]:
    """
    Height (index of the highest matching block + 1, 0 if none) of each of the
    256 columns, x + z*16 order. Air never counts; ``skip`` is one more state
    that is ignored (water for MOTION_BLOCKING-style maps).
    """
    heights = [0] * 256
    remaining = list(range(256))
    for yi in range(len(chunk_blocks) - 1, -1, -1):
        row = list(chain.from_iterable(chunk_blocks[yi]))
        if row.count(0) == 256:
            continue
        still = []
        for i in remaining:
            block = row[i]
            if block != 0 and block != skip:
                heights[i] = yi + 1
            else:
                still.append(i)
        remaining = still
        if not remaining:
            break
    return heights
