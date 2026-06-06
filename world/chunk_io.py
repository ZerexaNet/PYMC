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
import struct
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


def _state_id_to_properties(block_def: dict, state_id: int) -> dict[str, str]:
    state_defs = block_def.get("states", [])
    if not state_defs:
        return {}

    offset = state_id - block_def["minStateId"]
    props: dict[str, str] = {}
    for state_def in state_defs:
        values = _property_values(state_def)
        if not values:
            continue
        idx = offset % len(values)
        props[state_def["name"]] = values[idx]
        offset //= len(values)
    return props


def _build_block_registry():
    blocks_path = Path(__file__).resolve().parent / "blocks.json"
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))

    state_id_to_block: dict[int, tuple[str, dict[str, str]]] = {}
    block_key_to_state_id: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
    block_name_to_default_state: dict[str, int] = {}

    for block in blocks:
        name = f"minecraft:{block['name']}"
        default_state = int(block["defaultState"])
        block_name_to_default_state[name] = default_state

        min_state = int(block["minStateId"])
        max_state = int(block["maxStateId"])
        for state_id in range(min_state, max_state + 1):
            props = _state_id_to_properties(block, state_id)
            state_id_to_block[state_id] = (name, props)
            block_key_to_state_id[(name, tuple(sorted(props.items())))] = state_id

        # 允许省略 Properties 时直接落到 defaultState
        default_props = _state_id_to_properties(block, default_state)
        block_key_to_state_id[(name, tuple())] = default_state
        block_key_to_state_id[(name, tuple(sorted(default_props.items())))] = default_state

    return state_id_to_block, block_key_to_state_id, block_name_to_default_state


STATE_ID_TO_BLOCK, BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE = _build_block_registry()


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

    entry_mask = (1 << bits_per_entry) - 1
    entries_per_long = 64 // bits_per_entry
    num_longs = math.ceil(len(entries) / entries_per_long)
    longs: list[int] = []

    for long_index in range(num_longs):
        long_val = 0
        for i in range(entries_per_long):
            entry_index = long_index * entries_per_long + i
            if entry_index >= len(entries):
                break
            long_val |= (entries[entry_index] & entry_mask) << (i * bits_per_entry)
        if long_val >= (1 << 63):
            long_val -= (1 << 64)
        longs.append(long_val)
    return longs


def _unpack_palette_indices(longs: list[int], bits_per_entry: int,
                            total_entries: int) -> list[int]:
    if bits_per_entry <= 0:
        return [0] * total_entries

    entry_mask = (1 << bits_per_entry) - 1
    entries_per_long = 64 // bits_per_entry
    values: list[int] = []

    for long_val in longs:
        if long_val < 0:
            long_val += 1 << 64
        for i in range(entries_per_long):
            values.append((long_val >> (i * bits_per_entry)) & entry_mask)
            if len(values) >= total_entries:
                return values

    if len(values) < total_entries:
        values.extend([0] * (total_entries - len(values)))
    return values


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


def _palette_entry_to_state_id(entry: dict) -> int:
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

    state_id = BLOCK_KEY_TO_STATE_ID.get((name, normalized))
    if state_id is not None:
        return state_id
    return BLOCK_NAME_TO_DEFAULT_STATE.get(name, 0)


def _build_section_nbt(section_blocks: list[list[list[int]]], section_y: int,
                       biome_ids: list[int] | None = None) -> dict:
    palette_map: dict[int, int] = {}
    palette_state_ids: list[int] = []
    entries: list[int] = []
    non_air_count = 0

    for local_y in range(16):
        for z in range(16):
            for x in range(16):
                state_id = int(section_blocks[local_y][z][x])
                if state_id != 0:
                    non_air_count += 1
                if state_id not in palette_map:
                    palette_map[state_id] = len(palette_state_ids)
                    palette_state_ids.append(state_id)
                entries.append(palette_map[state_id])

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


def _decode_section_blocks(section: dict, target: list[list[list[int]]]):
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

    palette_ids = [_palette_entry_to_state_id(entry) for entry in palette]
    if len(palette_ids) == 1:
        entries = [0] * 4096
    else:
        data = block_states.get("data")
        raw_longs = data.values if hasattr(data, "values") else list(data or [])
        bits = max(4, math.ceil(math.log2(len(palette_ids))))
        entries = _unpack_palette_indices(list(raw_longs), bits, 4096)

    y_start = section_index * 16
    idx = 0
    for local_y in range(16):
        for z in range(16):
            for x in range(16):
                palette_index = entries[idx]
                idx += 1
                state_id = palette_ids[palette_index] if palette_index < len(palette_ids) else 0
                target[y_start + local_y][z][x] = state_id


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

    for section in sections:
        _decode_section_blocks(section, blocks)

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
