# ============================================================
# PyMC - 区块数据序列化/反序列化
# 将区块方块数据保存到文件 / 从文件加载
# ============================================================

"""
区块存储格式 (PyMC 私有格式):

每个区块存储为一段字节数据:
  头部 8 字节:
    [0:4]   uint32  魔数 (0x50794D43, "PyMC")
    [4:6]   uint16  版本号 (1)
    [6:8]   uint16  世界高度 (384)
  方块数据:
    98304 个 uint16 (小端序), 按 y*256+z*16+x 顺序
    共 196608 字节

总计: 196616 字节/区块 (未压缩)
存入 Linear 文件时由 Linear 容器统一进行 zstd 压缩。
"""

import struct
import array
import logging

logger = logging.getLogger("pymc.chunk_io")

# 常量
CHUNK_MAGIC = 0x50794D43  # "PyMC"
CHUNK_VERSION = 1
WORLD_HEIGHT = 384
BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16  # 98304
HEADER_SIZE = 8
DATA_SIZE = BLOCKS_COUNT * 2  # 196608
TOTAL_SIZE = HEADER_SIZE + DATA_SIZE  # 196616


def serialize_chunk(chunk_blocks: list[list[list[int]]]) -> bytes:
    """
    将区块方块 3D 数组序列化为字节数据。

    参数:
        chunk_blocks: [y][z][x] 方块 state ID 数组, 384x16x16

    返回:
        序列化后的字节数据
    """
    buf = bytearray(TOTAL_SIZE)

    # 写入头部
    struct.pack_into('<IHH', buf, 0, CHUNK_MAGIC, CHUNK_VERSION, WORLD_HEIGHT)

    # 写入方块数据 (uint16 小端序, y*256+z*16+x 顺序)
    offset = HEADER_SIZE
    for y in range(WORLD_HEIGHT):
        for z in range(16):
            row = chunk_blocks[y][z]
            for x in range(16):
                struct.pack_into('<H', buf, offset, row[x])
                offset += 2

    return bytes(buf)


def deserialize_chunk(data: bytes) -> list[list[list[int]]] | None:
    """
    从字节数据反序列化区块方块数组。

    参数:
        data: 序列化的区块数据

    返回:
        [y][z][x] 方块 state ID 数组, 或 None (数据无效)
    """
    if len(data) < HEADER_SIZE:
        logger.warning(f"区块数据过小: {len(data)} 字节")
        return None

    # 读取头部
    magic, version, height = struct.unpack_from('<IHH', data, 0)

    if magic != CHUNK_MAGIC:
        logger.warning(f"无效的区块魔数: {hex(magic)}")
        return None

    if version != CHUNK_VERSION:
        logger.warning(f"不支持的区块版本: {version}")
        return None

    expected_size = HEADER_SIZE + height * 16 * 16 * 2
    if len(data) < expected_size:
        logger.warning(f"区块数据不完整: 期望 {expected_size}, 实际 {len(data)}")
        return None

    # 使用 array 高效解包
    flat = array.array('H')
    flat.frombytes(data[HEADER_SIZE:HEADER_SIZE + BLOCKS_COUNT * 2])

    # 转为 3D 数组 [y][z][x]
    blocks = []
    offset = 0
    for y in range(WORLD_HEIGHT):
        layer = []
        for z in range(16):
            layer.append(list(flat[offset:offset + 16]))
            offset += 16
        blocks.append(layer)

    return blocks


def serialize_chunk_fast(flat_blocks: array.array, height_map: list[list[int]] | None = None) -> bytes:
    """
    从扁平 uint16 数组快速序列化 (跳过 3D 转换开销)。
    用于 C++ 生成器直接产出的数据。

    参数:
        flat_blocks: uint16 array, 98304 个元素 (y*256+z*16+x 顺序)
        height_map: 可选的高度图 [z][x]

    返回:
        序列化后的字节数据
    """
    header = struct.pack('<IHH', CHUNK_MAGIC, CHUNK_VERSION, WORLD_HEIGHT)
    return header + flat_blocks.tobytes()
