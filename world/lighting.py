# ============================================================
# PyMC - 区块光照
# ============================================================

"""
Per-chunk sky light and block light.

The client lights block *changes* itself, but the light it shows for freshly
loaded chunks is whatever the server sent, so wrong data here means black
patches under every tree, tuft of grass or pane of glass.

Model (the same rules as the vanilla light engine, limited to one chunk
column, so light does not flow across chunk borders):

  * sky light is 15 straight down from the sky until it meets a block that
    filters light; every block subtracts its opacity (leaves, water and ice
    filter 1 level, glass and plants 0, solid blocks stop it);
  * both light types spread to the six neighbours, losing
    ``max(1, opacity)`` per step;
  * block light starts at each emitting block (torch 14, lava 15, ...).

Opacity and emission come from ``world/blocks.json`` (``filterLight`` /
``emitLight``).
"""

from __future__ import annotations

import ctypes
import threading
from array import array
from collections import deque
from itertools import chain

SECTION_VOLUME = 4096
LAYER = 256

_tables: tuple[list[int], list[int], frozenset[int]] | None = None


def _light_tables() -> tuple[list[int], list[int], frozenset[int]]:
    """(opacity by state id, emission by state id, set of emitting state ids)."""
    global _tables
    if _tables is not None:
        return _tables
    import json
    from .chunk_io import _find_blocks_json

    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        blocks = json.load(f)
    size = max(block["maxStateId"] for block in blocks) + 1
    opacity = [15] * size
    emission = [0] * size
    for block in blocks:
        filter_light = int(block.get("filterLight", 15))
        emit = int(block.get("emitLight", 0))
        for state in range(block["minStateId"], block["maxStateId"] + 1):
            opacity[state] = filter_light
            emission[state] = emit
    emitting = frozenset(i for i, value in enumerate(emission) if value > 0)
    _tables = (opacity, emission, emitting)
    return _tables


def _spread(light: bytearray, queue: deque, blocks, opacity: list[int], height: int) -> None:
    """Flood-fill light levels from the queued cells (x, y, z)."""
    size = len(opacity)
    while queue:
        x, y, z = queue.popleft()
        level = light[y * LAYER + z * 16 + x]
        if level <= 1:
            continue
        for nx, ny, nz in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                           (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
            if not (0 <= nx < 16 and 0 <= nz < 16 and 0 <= ny < height):
                continue
            state = blocks[ny][nz][nx]
            cost = opacity[state] if state < size else 15
            new_level = level - (cost if cost > 1 else 1)
            if new_level <= 0:
                continue
            index = ny * LAYER + nz * 16 + nx
            if light[index] < new_level:
                light[index] = new_level
                queue.append((nx, ny, nz))


def _compute_python(blocks) -> tuple[bytearray, bytearray]:
    """
    Compute light for one chunk column.

    ``blocks`` is the ``[y][z][x]`` state-id array. Returns flat
    ``(sky, block)`` arrays indexed ``y * 256 + z * 16 + x`` with levels 0-15.
    """
    opacity, emission, emitting = _light_tables()
    table_size = len(opacity)
    height = len(blocks)
    sky = bytearray(height * LAYER)
    block_light = bytearray(height * LAYER)

    # Highest layer that contains anything: everything above is open sky.
    top = height - 1
    while top >= 0:
        layer = blocks[top]
        if any(any(row) for row in layer):
            break
        top -= 1
    if top < height - 1:
        start = (top + 1) * LAYER
        sky[start:] = b"\x0f" * (len(sky) - start)

    # --- direct sky light, column by column ---
    floors = [[0] * 16 for _ in range(16)]   # lowest layer still at level 15
    partial: list[tuple[int, int, int]] = []
    for z in range(16):
        floor_row = floors[z]
        for x in range(16):
            level = 15
            y = top
            offset = z * 16 + x
            while y >= 0:
                state = blocks[y][z][x]
                cost = opacity[state] if state < table_size else 15
                if level == 15:
                    if cost:
                        level -= cost
                        floor_row[x] = y + 1
                        if level <= 0:
                            break
                        sky[y * LAYER + offset] = level
                        partial.append((x, y, z))
                    else:
                        sky[y * LAYER + offset] = 15
                else:
                    level -= cost if cost > 1 else 1
                    if level <= 0:
                        break
                    sky[y * LAYER + offset] = level
                    partial.append((x, y, z))
                y -= 1
            else:
                floor_row[x] = 0

    # --- sideways spread: fully lit cells next to a column whose direct light
    #     stops higher up (overhangs, tree canopies, cliffs, cave mouths) ---
    queue: deque = deque(partial)
    for z in range(16):
        for x in range(16):
            floor = floors[z][x]
            highest_neighbour = floor
            if x > 0 and floors[z][x - 1] > highest_neighbour:
                highest_neighbour = floors[z][x - 1]
            if x < 15 and floors[z][x + 1] > highest_neighbour:
                highest_neighbour = floors[z][x + 1]
            if z > 0 and floors[z - 1][x] > highest_neighbour:
                highest_neighbour = floors[z - 1][x]
            if z < 15 and floors[z + 1][x] > highest_neighbour:
                highest_neighbour = floors[z + 1][x]
            for y in range(floor, min(highest_neighbour, top + 1)):
                queue.append((x, y, z))
    _spread(sky, queue, blocks, opacity, height)

    # --- block light ---
    queue = deque()
    for y in range(top + 1):
        layer = blocks[y]
        for z in range(16):
            row = layer[z]
            if emitting.isdisjoint(row):
                continue
            for x in range(16):
                state = row[x]
                if state in emitting:
                    block_light[y * LAYER + z * 16 + x] = emission[state]
                    queue.append((x, y, z))
    if queue:
        _spread(block_light, queue, blocks, opacity, height)

    return sky, block_light


_native = None          # the loaded native library with the light tables set, False if unavailable
_native_lock = threading.Lock()


def _native_lib():
    """The native engine (vrs_light_*) with the tables set, or None to use the Python version."""
    global _native
    if _native is None:
        with _native_lock:
            if _native is None:
                _native = False
                try:
                    from world.rs.native import load_library
                    lib = load_library()
                except Exception:  # the Python version is always there
                    lib = None
                if lib is not None:
                    opacity, emission, _ = _light_tables()
                    lib.vrs_light_set_tables(bytes(opacity), bytes(emission), len(opacity))
                    _native = lib
    return _native or None


def _address(buffer: bytearray) -> int:
    return ctypes.addressof((ctypes.c_char * len(buffer)).from_buffer(buffer))


def _compute_native(lib, blocks) -> tuple[bytearray, bytearray]:
    height = len(blocks)
    flat = array("H", chain.from_iterable(chain.from_iterable(blocks)))
    sky = bytearray(height * LAYER)
    block_light = bytearray(height * LAYER)
    lib.vrs_light_compute(flat.buffer_info()[0], height, _address(sky), _address(block_light))
    return sky, block_light


def compute_light_flat(flat, height: int | None = None) -> tuple[bytearray, bytearray]:
    """
    Same as compute_light, for blocks already in a flat ``array('H')`` (index
    ``y * 256 + z * 16 + x``). This is the fast path: the native engine reads the
    array directly, while the nested-list form costs a few milliseconds to flatten.
    """
    if height is None:
        height = len(flat) // LAYER
    lib = _native_lib()
    if lib is not None:
        sky = bytearray(height * LAYER)
        block_light = bytearray(height * LAYER)
        lib.vrs_light_compute(flat.buffer_info()[0], height, _address(sky), _address(block_light))
        return sky, block_light
    nested = [[[flat[y * LAYER + z * 16 + x] for x in range(16)] for z in range(16)] for y in range(height)]
    return _compute_python(nested)


def compute_light(blocks) -> tuple[bytearray, bytearray]:
    """
    Compute light for one chunk column.

    ``blocks`` is the ``[y][z][x]`` state-id array. Returns flat
    ``(sky, block)`` arrays indexed ``y * 256 + z * 16 + x`` with levels 0-15.
    """
    # Nested lists: the Python version is faster (flattening them costs more than the
    # native call saves). Flat arrays go to the native engine: see compute_light_flat.
    return _compute_python(blocks)


_FULL = b"\x0f" * SECTION_VOLUME
_EMPTY = bytes(SECTION_VOLUME)
_FULL_NIBBLES = b"\xff" * 2048


def _pack_section(levels) -> bytes | None:
    """4096 light levels -> 2048 packed nibbles; None if the section is all dark."""
    if levels == _EMPTY:
        return None
    if levels == _FULL:
        return _FULL_NIBBLES
    low = int.from_bytes(levels[0::2], "little")
    high = int.from_bytes(levels[1::2], "little")
    return (low | (high << 4)).to_bytes(2048, "little")


def build_light_sections(blocks) -> tuple[int, int, int, int, list[bytes], list[bytes]]:
    """
    Light data in the Chunk Data packet layout.

    Returns ``(sky_mask, block_mask, empty_sky_mask, empty_block_mask,
    sky_arrays, block_arrays)``. Bit ``i`` of a mask refers to light section
    ``i``: section 0 is the one below the world, 1..N are the world sections
    and N+1 is the one above the world.
    """
    sky, block_light = compute_light(blocks)
    world_sections = len(blocks) // 16

    sky_mask = block_mask = empty_sky_mask = empty_block_mask = 0
    sky_arrays: list[bytes] = []
    block_arrays: list[bytes] = []

    def add(index: int, sky_data: bytes | None, block_data: bytes | None):
        nonlocal sky_mask, block_mask, empty_sky_mask, empty_block_mask
        if sky_data is None:
            empty_sky_mask |= 1 << index
        else:
            sky_mask |= 1 << index
            sky_arrays.append(sky_data)
        if block_data is None:
            empty_block_mask |= 1 << index
        else:
            block_mask |= 1 << index
            block_arrays.append(block_data)

    add(0, None, None)                         # below the world: dark
    for section in range(world_sections):
        start = section * SECTION_VOLUME
        end = start + SECTION_VOLUME
        add(section + 1, _pack_section(sky[start:end]), _pack_section(block_light[start:end]))
    add(world_sections + 1, _FULL_NIBBLES, None)   # above the world: open sky

    return sky_mask, block_mask, empty_sky_mask, empty_block_mask, sky_arrays, block_arrays
