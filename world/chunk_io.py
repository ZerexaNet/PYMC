# ============================================================
# PyMC - 区块 NBT 读写
# 将区块方块数据保存为原版 Chunk NBT / 从 Chunk NBT 读取
# 同时兼容旧版 PyMC 私有缓存格式
# ============================================================

"""
区块存储格式说明:

1. 新格式: 原版 Chunk NBT
   - 顶层为 1.21.1 兼容的 Chunk Compound
   - sections[*].block_states.palette / data
   - sections[*].biomes.palette / data
   - Heightmaps / Status / isLightOn / xPos / zPos 等基础字段

2. 旧格式: PyMC 私有二进制缓存
   - 为了兼容已生成的旧世界，仍然支持读取
   - 新写入一律使用原版 Chunk NBT
"""

import array
import json
import logging
import math

from .fastpack import flatten_section, pack_longs, palette_of, to_signed, unpack_longs
import struct
import sys
from functools import lru_cache
from pathlib import Path

from protocol.nbt import (
    NbtByte,
    NbtLong,
    NbtLongArray,
    decode_nbt,
    encode_nbt,
)
from .chunk import build_heightmap_from_terrain
from .biomes import BIOME_ID_TO_NAME, BIOME_NAME_TO_ID

logger = logging.getLogger("pymc.chunk_io")


# --------------------------------------------------
# 世界常量
# --------------------------------------------------

MIN_Y = -64
WORLD_HEIGHT = 384
NUM_SECTIONS = WORLD_HEIGHT // 16
MIN_SECTION_Y = MIN_Y // 16  # -4
DATA_VERSION = 3955  # Minecraft Java Edition 1.21.1


# --------------------------------------------------
# 旧版 PyMC 私有格式常量
# --------------------------------------------------

CHUNK_MAGIC = 0x50794D43  # "PyMC"
CHUNK_VERSION = 1
BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16  # 98304
LEGACY_HEADER_SIZE = 8
LEGACY_DATA_SIZE = BLOCKS_COUNT * 2
LEGACY_TOTAL_SIZE = LEGACY_HEADER_SIZE + LEGACY_DATA_SIZE


# --------------------------------------------------
# 方块状态注册表
# --------------------------------------------------

def _property_values(state_def: dict) -> list[str]:
    if state_def["type"] == "bool":
        # minecraft-data 中 bool 状态按 true,false 顺序展开状态 ID。
        return ["true", "false"]
    return list(state_def.get("values", []))


def _state_id_to_properties(block_def: dict, state_id: int, legacy: bool = False) -> dict[str, str]:
    """
    Decode a global state id into block properties.

    Vanilla enumerates block states with the *last* property varying fastest
    (oak_leaves 237 = distance=1,persistent=true,waterlogged=true,
    238 = ...waterlogged=false). Releases of PyMC before the fix decoded the
    first property fastest; ``legacy=True`` reproduces that order so chunks
    written by those versions can still be read correctly.
    """
    state_defs = block_def.get("states", [])
    if not state_defs:
        return {}

    offset = state_id - block_def["minStateId"]
    props: dict[str, str] = {}
    ordered = state_defs if legacy else list(reversed(state_defs))
    for state_def in ordered:
        values = _property_values(state_def)
        if not values:
            continue
        idx = offset % len(values)
        props[state_def["name"]] = values[idx]
        offset //= len(values)
    if not legacy:
        props = {d["name"]: props[d["name"]] for d in state_defs if d["name"] in props}
    return props


def _find_blocks_json() -> str:
    """Locate blocks.json from multiple possible paths (source, Nuitka bundle, CWD)."""
    candidates = [
        # 1. Same directory as this file (source checkout / normal install)
        Path(__file__).resolve().parent / "blocks.json",
        # 2. Nuitka standalone: data files may be alongside the executable
        Path(__file__).resolve().parent.parent / "world" / "blocks.json",
        # 3. Nuitka onefile: check relative to the executable
        Path(sys.argv[0]).resolve().parent / "world" / "blocks.json",
        # 4. Current working directory
        Path("world") / "blocks.json",
        Path("blocks.json"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise FileNotFoundError(
        f"Cannot find blocks.json. Searched: {[str(c) for c in candidates]}"
    )


def _load_blocks_json() -> list:
    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        return json.load(f)


def _build_block_registry():
    """State tables for every block state. Keys and property pairs are shared objects, which keeps the
    ~25k entries small; the legacy (pre-1.21 state order) table is only built when an old chunk needs it."""
    pairs: dict[tuple[str, str], tuple[str, str]] = {}

    def share(key):
        return tuple(pairs.setdefault(pair, pair) for pair in key)

    state_id_to_block: dict[int, tuple[str, dict[str, str]]] = {}
    block_key_to_state_id: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
    block_name_to_default_state: dict[str, int] = {}

    for block in _load_blocks_json():
        name = f"minecraft:{block['name']}"
        default_state = int(block["defaultState"])
        block_name_to_default_state[name] = default_state

        min_state = int(block["minStateId"])
        max_state = int(block["maxStateId"])
        for state_id in range(min_state, max_state + 1):
            props = _state_id_to_properties(block, state_id)
            state_id_to_block[state_id] = (name, props)
            block_key_to_state_id[(name, share(sorted(props.items())))] = state_id

        # 允许省略 Properties 时直接落到 defaultState
        default_props = _state_id_to_properties(block, default_state)
        block_key_to_state_id[(name, tuple())] = default_state
        block_key_to_state_id[(name, share(sorted(default_props.items())))] = default_state

    return state_id_to_block, block_key_to_state_id, block_name_to_default_state


_LEGACY_KEY_TO_STATE_ID: dict | None = None


def _legacy_table() -> dict:
    global _LEGACY_KEY_TO_STATE_ID
    if _LEGACY_KEY_TO_STATE_ID is None:
        table: dict = {}
        for block in _load_blocks_json():
            name = f"minecraft:{block['name']}"
            for state_id in range(int(block["minStateId"]), int(block["maxStateId"]) + 1):
                legacy_props = _state_id_to_properties(block, state_id, legacy=True)
                table[(name, tuple(sorted(legacy_props.items())))] = state_id
        _LEGACY_KEY_TO_STATE_ID = table
    return _LEGACY_KEY_TO_STATE_ID


STATE_ID_TO_BLOCK, BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE = _build_block_registry()

# Chunks written by this version carry this tag; see _uses_legacy_state_order().
PYMC_STATE_ORDER_TAG = "PyMCStateOrder"
PYMC_STATE_ORDER = 2


def _uses_legacy_state_order(root: dict) -> bool:
    """
    True for chunks written by PyMC before the property-order fix.

    Those chunks have no PyMCStateOrder tag, LastUpdate == 0 and no
    block_ticks/fluid_ticks lists, which every vanilla 1.21.1 chunk has.
    """
    if PYMC_STATE_ORDER_TAG in root:
        return False
    if "block_ticks" in root or "fluid_ticks" in root:
        return False
    last_update = root.get("LastUpdate", 0)
    last_update = getattr(last_update, "value", last_update)
    return int(last_update or 0) == 0


def is_pymc_chunk_data(data: bytes) -> bool:
    """判断是否为旧版 PyMC 私有区块缓存。"""
    if len(data) < LEGACY_HEADER_SIZE:
        return False
    magic, version, height = struct.unpack_from("<IHH", data, 0)
    return magic == CHUNK_MAGIC and version == CHUNK_VERSION and height == WORLD_HEIGHT


def _decode_legacy_chunk(data: bytes) -> list[list[list[int]]] | None:
    if len(data) < LEGACY_HEADER_SIZE:
        logger.warning(f"区块数据过小: {len(data)} 字节")
        return None

    magic, version, height = struct.unpack_from("<IHH", data, 0)
    if magic != CHUNK_MAGIC or version != CHUNK_VERSION or height != WORLD_HEIGHT:
        return None

    expected_size = LEGACY_HEADER_SIZE + height * 16 * 16 * 2
    if len(data) < expected_size:
        logger.warning(f"旧版区块数据不完整: 期望 {expected_size}, 实际 {len(data)}")
        return None

    flat = array.array("H")
    flat.frombytes(data[LEGACY_HEADER_SIZE:LEGACY_HEADER_SIZE + BLOCKS_COUNT * 2])

    blocks = []
    offset = 0
    for _ in range(WORLD_HEIGHT):
        layer = []
        for _ in range(16):
            layer.append(list(flat[offset:offset + 16]))
            offset += 16
        blocks.append(layer)
    return blocks


def _pack_palette_indices(entries: list[int], bits_per_entry: int) -> list[int]:
    if bits_per_entry <= 0:
        return []
    return to_signed(pack_longs(entries, bits_per_entry))


def _unpack_palette_indices(longs: list[int], bits_per_entry: int,
                            total_entries: int) -> list[int]:
    return unpack_longs(longs, bits_per_entry, total_entries)


def _state_id_to_palette_entry(state_id: int) -> dict:
    block_name, props = STATE_ID_TO_BLOCK.get(
        state_id,
        ("minecraft:air", {}),
    )
    entry = {"Name": block_name}
    if props:
        default_state = BLOCK_NAME_TO_DEFAULT_STATE.get(block_name)
        if default_state is not None and default_state != state_id:
            entry["Properties"] = props
    return entry


def _palette_entry_to_state_id(entry: dict, legacy: bool = False) -> int:
    if not isinstance(entry, dict):
        return 0

    name = entry.get("Name")
    if not isinstance(name, str):
        return 0

    props = entry.get("Properties", {})
    if not isinstance(props, dict):
        props = {}

    normalized = tuple(sorted(
        (str(k), str(v.value) if hasattr(v, "value") else str(v))
        for k, v in props.items()
    ))

    table = _legacy_table() if legacy else BLOCK_KEY_TO_STATE_ID
    state_id = table.get((name, normalized))
    if state_id is not None:
        return state_id
    return BLOCK_NAME_TO_DEFAULT_STATE.get(name, 0)


def _build_section_nbt(section_blocks: list[list[list[int]]], section_y: int,
                       biome_ids: list[int] | None = None) -> dict:
    flat = flatten_section(section_blocks)
    non_air_count = len(flat) - flat.count(0)
    palette_state_ids, entries = palette_of(flat)

    if not palette_state_ids:
        palette_state_ids = [0]
        entries = [0] * 4096

    block_states = {
        "palette": [_state_id_to_palette_entry(state_id) for state_id in palette_state_ids]
    }
    if len(palette_state_ids) > 1:
        bits = max(4, math.ceil(math.log2(len(palette_state_ids))))
        block_states["data"] = NbtLongArray(_pack_palette_indices(entries, bits))

    biome_palette_ids = biome_ids or [BIOME_NAME_TO_ID["minecraft:plains"]] * 64
    biome_palette_map: dict[int, int] = {}
    biome_palette_values: list[int] = []
    biome_entries: list[int] = []
    for biome_id in biome_palette_ids:
        if biome_id not in biome_palette_map:
            biome_palette_map[biome_id] = len(biome_palette_values)
            biome_palette_values.append(biome_id)
        biome_entries.append(biome_palette_map[biome_id])

    biome_container = {
        "palette": [BIOME_ID_TO_NAME.get(biome_id, "minecraft:plains")
                    for biome_id in biome_palette_values]
    }
    if len(biome_palette_values) > 1:
        bits = max(1, math.ceil(math.log2(len(biome_palette_values))))
        biome_container["data"] = NbtLongArray(_pack_palette_indices(biome_entries, bits))

    section = {
        "Y": NbtByte(section_y),
        "block_states": block_states,
        "biomes": biome_container,
    }
    if non_air_count:
        section["block_count"] = non_air_count
    return section


@lru_cache(maxsize=1)
def _empty_heightmaps() -> dict:
    empty_chunk = [[[0 for _ in range(16)] for _ in range(16)] for _ in range(WORLD_HEIGHT)]
    return {
        "MOTION_BLOCKING": NbtLongArray(build_heightmap_from_terrain(empty_chunk, include_water=False)),
        "WORLD_SURFACE": NbtLongArray(build_heightmap_from_terrain(empty_chunk, include_water=True)),
    }


def serialize_chunk(chunk_blocks: list[list[list[int]]], chunk_x: int = 0,
                    chunk_z: int = 0, chunk_biomes: list[list[int]] | None = None) -> bytes:
    """
    将区块方块数组编码为原版 Chunk NBT。

    参数:
        chunk_blocks: [y][z][x] 方块 state ID 数组, 384x16x16
        chunk_x, chunk_z: 区块坐标
    """
    sections = []
    for section_index in range(NUM_SECTIONS):
        y_start = section_index * 16
        section_blocks = chunk_blocks[y_start:y_start + 16]
        biome_section = None
        if chunk_biomes is not None and section_index < len(chunk_biomes):
            biome_section = chunk_biomes[section_index]
        sections.append(_build_section_nbt(
            section_blocks, MIN_SECTION_Y + section_index, biome_section
        ))

    root = {
        "DataVersion": DATA_VERSION,
        "xPos": int(chunk_x),
        "zPos": int(chunk_z),
        "Status": "minecraft:full",
        "isLightOn": NbtByte(1),
        "InhabitedTime": NbtLong(0),
        "LastUpdate": NbtLong(0),
        "Heightmaps": {
            "MOTION_BLOCKING": NbtLongArray(build_heightmap_from_terrain(chunk_blocks, include_water=False)),
            "WORLD_SURFACE": NbtLongArray(build_heightmap_from_terrain(chunk_blocks, include_water=True)),
        },
        "sections": sections,
        PYMC_STATE_ORDER_TAG: PYMC_STATE_ORDER,
        "block_ticks": [],
        "fluid_ticks": [],
        "PostProcessing": [[] for _ in range(NUM_SECTIONS)],
        "block_entities": [],
        "structures": {
            "starts": {},
            "references": {},
        },
    }
    return encode_nbt(root, with_type=True, root_name="")


def _root_chunk_compound(raw_root: dict) -> dict:
    if not isinstance(raw_root, dict):
        return {}
    if "sections" in raw_root:
        return raw_root
    level = raw_root.get("Level")
    if isinstance(level, dict):
        return level
    return raw_root


def _decode_section_blocks(section: dict, target: list[list[list[int]]], legacy: bool = False):
    if not isinstance(section, dict):
        return

    y_tag = section.get("Y")
    section_y = int(y_tag.value if hasattr(y_tag, "value") else y_tag)
    section_index = section_y - MIN_SECTION_Y
    if section_index < 0 or section_index >= NUM_SECTIONS:
        return

    block_states = section.get("block_states")
    if not isinstance(block_states, dict):
        return

    palette = block_states.get("palette")
    if not isinstance(palette, list) or not palette:
        return

    palette_ids = [_palette_entry_to_state_id(entry, legacy) for entry in palette]
    if len(palette_ids) == 1:
        entries = [0] * 4096
    else:
        data = block_states.get("data")
        raw_longs = data.values if hasattr(data, "values") else list(data or [])
        bits = max(4, math.ceil(math.log2(len(palette_ids))))
        entries = _unpack_palette_indices(list(raw_longs), bits, 4096)

    if len(palette_ids) == 1:
        states = [palette_ids[0]] * 4096
    else:
        # out-of-range indices (corrupt data) read as air
        lookup = palette_ids + [0] * (max(entries) + 1 - len(palette_ids))
        states = list(map(lookup.__getitem__, entries))
    y_start = section_index * 16
    offset = 0
    for local_y in range(16):
        layer = target[y_start + local_y]
        for z in range(16):
            layer[z] = states[offset:offset + 16]
            offset += 16


def _decode_section_biomes(section: dict, target: list[list[int]]):
    if not isinstance(section, dict):
        return

    y_tag = section.get("Y")
    section_y = int(y_tag.value if hasattr(y_tag, "value") else y_tag)
    section_index = section_y - MIN_SECTION_Y
    if section_index < 0 or section_index >= NUM_SECTIONS:
        return

    biomes = section.get("biomes")
    if not isinstance(biomes, dict):
        return

    palette = biomes.get("palette")
    if not isinstance(palette, list) or not palette:
        return

    palette_ids = [
        BIOME_NAME_TO_ID.get(str(entry.value if hasattr(entry, "value") else entry), BIOME_NAME_TO_ID["minecraft:plains"])
        for entry in palette
    ]
    if len(palette_ids) == 1:
        entries = [0] * 64
    else:
        data = biomes.get("data")
        raw_longs = data.values if hasattr(data, "values") else list(data or [])
        bits = max(1, math.ceil(math.log2(len(palette_ids))))
        entries = _unpack_palette_indices(list(raw_longs), bits, 64)

    decoded = []
    for palette_index in entries[:64]:
        decoded.append(palette_ids[palette_index] if palette_index < len(palette_ids) else BIOME_NAME_TO_ID["minecraft:plains"])
    if len(decoded) < 64:
        decoded.extend([BIOME_NAME_TO_ID["minecraft:plains"]] * (64 - len(decoded)))
    target[section_index] = decoded


def deserialize_chunk_with_biomes(data: bytes) -> tuple[list[list[list[int]]], list[list[int]] | None] | None:
    """从区块字节数据恢复方块数组和 biome section ids。"""
    if not data:
        return None

    blocks = deserialize_chunk(data)
    if blocks is None:
        return None

    if is_pymc_chunk_data(data):
        return blocks, None

    try:
        root, _ = decode_nbt(data, with_type=True, with_name=True)
    except Exception as exc:
        logger.warning(f"解码 Chunk NBT biome 失败: {exc}")
        return blocks, None

    chunk = _root_chunk_compound(root)
    sections = chunk.get("sections")
    if not isinstance(sections, list):
        return blocks, None

    biome_sections = [[BIOME_NAME_TO_ID["minecraft:plains"]] * 64 for _ in range(NUM_SECTIONS)]
    for section in sections:
        _decode_section_biomes(section, biome_sections)
    return blocks, biome_sections


def deserialize_chunk(data: bytes) -> list[list[list[int]]] | None:
    """
    从区块字节数据恢复方块数组。

    兼容:
        - 旧版 PyMC 私有缓存格式
        - 原版 Chunk NBT
    """
    if not data:
        return None

    if is_pymc_chunk_data(data):
        return _decode_legacy_chunk(data)

    try:
        root, _ = decode_nbt(data, with_type=True, with_name=True)
    except Exception as exc:
        logger.warning(f"解码 Chunk NBT 失败: {exc}")
        return None

    chunk = _root_chunk_compound(root)
    sections = chunk.get("sections")
    if not isinstance(sections, list):
        logger.warning("Chunk NBT 缺少 sections 列表")
        return None

    blocks = [[[0 for _ in range(16)] for _ in range(16)]
              for _ in range(WORLD_HEIGHT)]

    legacy = _uses_legacy_state_order(chunk)
    for section in sections:
        _decode_section_blocks(section, blocks, legacy)

    return blocks


def serialize_chunk_fast(flat_blocks: array.array, chunk_x: int = 0,
                         chunk_z: int = 0) -> bytes:
    """
    从扁平 uint16 数组编码原版 Chunk NBT。
    """
    if len(flat_blocks) != BLOCKS_COUNT:
        raise ValueError(f"flat_blocks 长度应为 {BLOCKS_COUNT}, 实际 {len(flat_blocks)}")

    blocks = []
    offset = 0
    for _ in range(WORLD_HEIGHT):
        layer = []
        for _ in range(16):
            layer.append(list(flat_blocks[offset:offset + 16]))
            offset += 16
        blocks.append(layer)

    return serialize_chunk(blocks, chunk_x=chunk_x, chunk_z=chunk_z)
