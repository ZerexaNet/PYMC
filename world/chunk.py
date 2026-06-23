# ============================================================
# PyMC - 区块数据格式
# 实现区块 Section 的调色板编码和区块数据打包
# 支持多方块混合区块 (间接调色板)
# ============================================================

"""
Minecraft 区块数据格式实现。

区块列 (Chunk Column): 16x384x16 (主世界, 24 个 Section)
区块段 (Chunk Section): 16x16x16

每个 Section 包含:
  - 方块计数 (Short): 非空气方块数量
  - 方块状态 (Paletted Container, 4096 条目)
  - 生物群系 (Paletted Container, 64 条目)

调色板编码策略:
  - 单值调色板: bits_per_entry=0, 整个 Section 同一种方块
  - 间接调色板: bits_per_entry=4~8, 最多 256 种不同方块
  - 直接调色板: bits_per_entry=15, 直接使用全局 ID (超过 256 种时)
"""

import struct
import math
from protocol.data_types import write_varint
from .blocks import AIR
from .biomes import BIOME_NAME_TO_ID


# 生物群系 ID
BIOME_PLAINS = BIOME_NAME_TO_ID["minecraft:plains"]

# 世界参数
MIN_Y = -64
WORLD_HEIGHT = 384
NUM_SECTIONS = 24


def encode_paletted_container_single(value: int) -> bytes:
    """
    编码单值调色板容器 (整个 Section 只有一种方块/生物群系)。

    格式:
        - Byte: bits_per_entry = 0
        - VarInt: 唯一值的全局 ID
        - VarInt: 数据数组长度 = 0 (无需数据)
    """
    result = bytearray()
    result.append(0)                    # bits_per_entry = 0 (单值)
    result.extend(write_varint(value))  # 全局调色板 ID
    result.extend(write_varint(0))      # 数据数组长度 = 0
    return bytes(result)


def encode_paletted_container_indirect(entries: list[int], palette: list[int],
                                        total_entries: int) -> bytes:
    """
    编码间接调色板容器。

    参数:
        entries: 每个位置对应的调色板索引列表 (长度=total_entries)
        palette: 调色板 (全局状态ID列表)
        total_entries: 总条目数 (方块=4096, 生物群系=64)

    返回:
        编码后的字节
    """
    palette_size = len(palette)
    if palette_size <= 1:
        return encode_paletted_container_single(palette[0] if palette else 0)

    # 计算 bits_per_entry
    bits_per_entry = max(4, math.ceil(math.log2(palette_size)))

    # 方块调色板: 最小 4, 最大 8
    if total_entries == 4096:
        bits_per_entry = max(4, min(8, bits_per_entry))
        # 如果调色板太大 (>256), 使用直接调色板
        if palette_size > (1 << 8):
            return _encode_direct_palette(entries, palette, total_entries)
    # 生物群系调色板: 最小 1, 最大 3
    elif total_entries == 64:
        bits_per_entry = max(1, min(3, bits_per_entry))

    result = bytearray()
    result.append(bits_per_entry)

    # 写入调色板
    result.extend(write_varint(palette_size))
    for pid in palette:
        result.extend(write_varint(pid))

    # 打包数据数组到 Long 数组
    entries_per_long = 64 // bits_per_entry
    num_longs = math.ceil(total_entries / entries_per_long)
    result.extend(write_varint(num_longs))

    entry_mask = (1 << bits_per_entry) - 1
    for long_index in range(num_longs):
        long_val = 0
        for i in range(entries_per_long):
            entry_index = long_index * entries_per_long + i
            if entry_index < len(entries):
                value = entries[entry_index] & entry_mask
                long_val |= value << (i * bits_per_entry)
        # 转为有符号 64 位
        if long_val >= (1 << 63):
            long_val -= (1 << 64)
        result.extend(struct.pack('>q', long_val))

    return bytes(result)


def _encode_direct_palette(entries: list[int], palette: list[int],
                            total_entries: int) -> bytes:
    """
    编码直接调色板 (不使用调色板映射，直接存储全局 ID)。
    bits_per_entry = 15 (for blocks)。
    """
    bits_per_entry = 15
    result = bytearray()
    result.append(bits_per_entry)
    # 直接调色板没有调色板数据

    # 将调色板索引转回全局 ID
    entries_per_long = 64 // bits_per_entry  # 4
    num_longs = math.ceil(total_entries / entries_per_long)
    result.extend(write_varint(num_longs))

    entry_mask = (1 << bits_per_entry) - 1
    for long_index in range(num_longs):
        long_val = 0
        for i in range(entries_per_long):
            entry_index = long_index * entries_per_long + i
            if entry_index < len(entries):
                # 将调色板索引转回全局 ID
                palette_idx = entries[entry_index]
                global_id = palette[palette_idx] if palette_idx < len(palette) else 0
                long_val |= (global_id & entry_mask) << (i * bits_per_entry)
        if long_val >= (1 << 63):
            long_val -= (1 << 64)
        result.extend(struct.pack('>q', long_val))

    return bytes(result)


def build_section_from_blocks(section_blocks: list[list[list[int]]],
                               biome_data: list[int] | None = None,
                               biome_id: int = BIOME_PLAINS) -> bytes:
    """
    从 3D 方块数组构建区块段数据。

    参数:
        section_blocks: 16x16x16 方块数组 [y][z][x]，值为全局状态 ID
        biome_id: 生物群系 ID

    返回:
        编码后的区块段字节
    """
    result = bytearray()

    # --- 统计方块和构建调色板 ---
    palette_map = {}   # 全局ID -> 调色板索引
    palette = []       # 调色板列表 (全局ID)
    entries = []       # 4096 个调色板索引 (y*256 + z*16 + x 顺序)
    non_air_count = 0

    for y in range(16):
        for z in range(16):
            for x in range(16):
                block_id = section_blocks[y][z][x]

                if block_id != AIR:
                    non_air_count += 1

                if block_id not in palette_map:
                    palette_map[block_id] = len(palette)
                    palette.append(block_id)

                entries.append(palette_map[block_id])

    # 方块计数 (Short)
    result.extend(struct.pack('>h', non_air_count))

    # --- 编码方块状态 ---
    if len(palette) == 1:
        # 单值调色板 (整个 Section 只有一种方块)
        result.extend(encode_paletted_container_single(palette[0]))
    else:
        # 间接调色板
        result.extend(encode_paletted_container_indirect(
            entries, palette, 4096
        ))

    # --- 编码生物群系 (4x4x4 = 64 条目) ---
    if biome_data:
        biome_palette_map = {}
        biome_palette = []
        biome_entries = []
        for entry in biome_data:
            if entry not in biome_palette_map:
                biome_palette_map[entry] = len(biome_palette)
                biome_palette.append(entry)
            biome_entries.append(biome_palette_map[entry])

        if len(biome_palette) == 1:
            result.extend(encode_paletted_container_single(biome_palette[0]))
        else:
            result.extend(encode_paletted_container_indirect(
                biome_entries, biome_palette, 64
            ))
    else:
        result.extend(encode_paletted_container_single(biome_id))

    return bytes(result)


def build_chunk_column_from_terrain(chunk_blocks: list[list[list[int]]],
                                    chunk_biomes: list[list[int]] | None = None) -> bytes:
    """
    从完整的区块方块数据构建区块列。

    参数:
        chunk_blocks: 384 x 16 x 16 方块数组 [y_index][z][x]
                      y_index=0 对应 y=MIN_Y (-64)

    返回:
        编码后的所有 24 个 Section 数据
    """
    result = bytearray()

    for section_idx in range(NUM_SECTIONS):
        y_start = section_idx * 16  # 数组中的 y 起始索引

        # 提取这个 Section 的 16x16x16 方块数据
        section_blocks = chunk_blocks[y_start:y_start + 16]

        biome_section = None
        if chunk_biomes is not None and section_idx < len(chunk_biomes):
            biome_section = chunk_biomes[section_idx]

        result.extend(build_section_from_blocks(section_blocks, biome_section))

    return bytes(result)


def build_heightmap_from_terrain(chunk_blocks: list[list[list[int]]], 
                                 include_water: bool = False) -> list[int]:
    """
    从方块数据计算高度图。

    参数:
        chunk_blocks: 384 x 16 x 16 方块数组
        include_water: 是否包含水 (True 用于 WORLD_SURFACE, False 用于 MOTION_BLOCKING)

    返回:
        37 个 Long 值的列表 (256 个 9-bit 条目打包)
    """
    from .blocks import WATER

    bits_per_entry = 9
    entries_per_long = 64 // bits_per_entry  # 7
    num_longs = math.ceil(256 / entries_per_long)  # 37

    # 计算每列高度 (从上到下扫描)
    heights = [0] * 256  # x + z*16 顺序

    for z in range(16):
        for x in range(16):
            height = 0
            # 从顶部向下搜索
            for yi in range(WORLD_HEIGHT - 1, -1, -1):
                block = chunk_blocks[yi][z][x]
                if block != AIR:
                    if not include_water and block == WATER:
                        continue
                    height = yi + 1  # 高度是方块上方一格
                    break
            heights[x + z * 16] = height

    # 打包到 Long 数组
    longs = []
    for long_index in range(num_longs):
        long_val = 0
        for i in range(entries_per_long):
            entry_index = long_index * entries_per_long + i
            if entry_index < 256:
                long_val |= (heights[entry_index] & 0x1FF) << (i * bits_per_entry)
        
        # 补码处理 (Python 的 int 是无限精度的，需要模拟 64 位有符号整数)
        if long_val >= (1 << 63):
            long_val -= (1 << 64)
        longs.append(long_val)

    return longs


# --------------------------------------------------
# 兼容: 保留旧的平坦世界函数
# --------------------------------------------------

def build_flat_chunk_column() -> bytes:
    """构建平坦世界的区块列 (兼容旧代码)。"""
    from .blocks import BEDROCK, STONE, GRASS_BLOCK

    result = bytearray()
    for section_index in range(24):
        if section_index == 0:
            result.extend(_build_single_block_section(BEDROCK))
        elif section_index <= 3:
            result.extend(_build_single_block_section(STONE))
        elif section_index == 4:
            result.extend(_build_single_block_section(GRASS_BLOCK))
        else:
            result.extend(_build_single_block_section(AIR))
    return bytes(result)


def _build_single_block_section(block_id: int) -> bytes:
    """构建单一方块填充的 Section。"""
    result = bytearray()
    block_count = 0 if block_id == AIR else 4096
    result.extend(struct.pack('>h', block_count))
    result.extend(encode_paletted_container_single(block_id))
    result.extend(encode_paletted_container_single(BIOME_PLAINS))
    return bytes(result)


def build_heightmap_data() -> list[int]:
    """构建平坦世界高度图 (兼容旧代码)。"""
    bits_per_entry = 9
    entries_per_long = 64 // bits_per_entry
    num_longs = math.ceil(256 / entries_per_long)
    height_value = 80

    longs = []
    for long_index in range(num_longs):
        long_val = 0
        for i in range(entries_per_long):
            entry_index = long_index * entries_per_long + i
            if entry_index < 256:
                long_val |= (height_value & 0x1FF) << (i * bits_per_entry)
        if long_val >= (1 << 63):
            long_val -= (1 << 64)
        longs.append(long_val)

    return longs
