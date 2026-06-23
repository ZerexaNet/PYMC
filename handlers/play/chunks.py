# ============================================================
# PyMC - 区块数据发送
# 处理区块数据包的构建和发送
# ============================================================

"""
区块数据包构建与发送。

包括:
  - 区块数据包构建 (_send_chunk_data, _send_chunk_data_terrain)
  - 光照数据构建 (_build_chunk_light_data)
  - 预生成区块发送 (_send_prebuilt_chunk)
  - 批量区块发送 (_send_chunk_batch, _send_chunk_results_streamed)
  - 延迟区块发送 (_send_deferred_chunks)
  - 动态区块流式补发 (_stream_chunks_around_player)
  - 区块坐标排序 (_sorted_chunk_coords)
"""

import asyncio
import logging
import time

from protocol.data_types import (
    write_varint, write_int, write_long,
)
from protocol.nbt import encode_nbt, NbtLongArray
from network.connection import Connection
from world.chunk import (
    build_chunk_column_from_terrain, build_heightmap_from_terrain,
    build_flat_chunk_column, build_heightmap_data,
)
from world.terrain import TerrainGenerator
from world.blocks import AIR, WATER

logger = logging.getLogger("PyMC.区块")

CHUNK_STREAM_BATCH_SIZE = 32


def _sorted_chunk_coords(center_cx: int, center_cz: int, view_distance: int) -> list[tuple[int, int]]:
    """按与出生点区块的 Chebyshev 距离从近到远排序。"""
    coords = [
        (cx, cz)
        for cx in range(center_cx - view_distance, center_cx + view_distance + 1)
        for cz in range(center_cz - view_distance, center_cz + view_distance + 1)
    ]
    coords.sort(key=lambda pos: (max(abs(pos[0] - center_cx), abs(pos[1] - center_cz)),
                                 abs(pos[0] - center_cx) + abs(pos[1] - center_cz),
                                 pos[0], pos[1]))
    return coords


async def _send_chunk_data(conn: Connection, chunk_x: int, chunk_z: int):
    """
    发送 Chunk Data and Update Light 数据包 (0x27)。
    (平坦世界版本)
    """
    from protocol.data_types import write_varint as _wv
    payload = bytearray()

    # Chunk X, Z (Int)
    payload.extend(write_int(chunk_x))
    payload.extend(write_int(chunk_z))

    # Heightmaps (NBT Compound)
    heightmap_longs = build_heightmap_data()
    heightmap_nbt = {
        "MOTION_BLOCKING": NbtLongArray(heightmap_longs),
        "WORLD_SURFACE": NbtLongArray(heightmap_longs),
    }
    payload.extend(encode_nbt(heightmap_nbt, with_type=True))

    # Chunk Data (Byte Array: VarInt 长度 + 数据)
    chunk_data = build_flat_chunk_column()
    payload.extend(write_varint(len(chunk_data)))
    payload.extend(chunk_data)

    # Block Entities (VarInt 数量 = 0)
    payload.extend(write_varint(0))

    # --- 光照数据 ---
    all_bits = (1 << 26) - 1
    payload.extend(write_varint(1))  # BitSet 长度
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(0))
    payload.extend(write_varint(0))

    # Sky Light Arrays
    sky_light_section = bytes([0xFF] * 2048)
    light_section_count = 26
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(sky_light_section)

    # Block Light Arrays
    block_light_section = bytes([0x00] * 2048)
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(block_light_section)

    await conn.send_packet(0x27, bytes(payload))


async def _send_chunk_data_terrain(conn: Connection, chunk_x: int, chunk_z: int, terrain: TerrainGenerator):
    """
    使用噪声地形生成器发送 Chunk Data and Update Light 数据包 (0x27)。
    """
    payload = bytearray()

    # Chunk X, Z (Int)
    payload.extend(write_int(chunk_x))
    payload.extend(write_int(chunk_z))

    # 生成地形数据
    chunk_blocks = terrain.generate_chunk(chunk_x, chunk_z)

    # Heightmaps
    heightmap_longs = build_heightmap_from_terrain(chunk_blocks)
    heightmap_nbt = {
        "MOTION_BLOCKING": NbtLongArray(heightmap_longs),
        "WORLD_SURFACE": NbtLongArray(heightmap_longs),
    }
    payload.extend(encode_nbt(heightmap_nbt, with_type=True))

    # Chunk Data
    chunk_data = build_chunk_column_from_terrain(chunk_blocks)
    payload.extend(write_varint(len(chunk_data)))
    payload.extend(chunk_data)

    # Block Entities
    payload.extend(write_varint(0))

    # --- 光照数据 ---
    all_bits = (1 << 26) - 1
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(0))
    payload.extend(write_varint(0))

    sky_light_section = bytes([0xFF] * 2048)
    light_section_count = 26
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(sky_light_section)

    block_light_section = bytes([0x00] * 2048)
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(block_light_section)

    await conn.send_packet(0x27, bytes(payload))


def _build_chunk_light_data(chunk_blocks: list[list[list[int]]]) -> tuple[int, int, int, int, list[bytes], list[bytes]]:
    """
    为 24 个世界 section + 上下边界构建简化版光照数据。
    规则:
      - 露天列保持 15 级天光
      - 遇到第一个非空气/非流体方块后，下面不再有天光
      - 方块光当前仍为 0
    """
    section_count = 26  # 24 world sections + bottom/top boundary
    section_bytes = [bytearray(2048) for _ in range(section_count)]

    for z in range(16):
        for x in range(16):
            sky_open = True
            for y_index in range(len(chunk_blocks) - 1, -1, -1):
                block_id = chunk_blocks[y_index][z][x]
                transparent = block_id in (AIR, WATER)
                if sky_open and transparent:
                    world_section = y_index // 16
                    section_idx = world_section + 1
                    local_y = y_index % 16
                    nibble_index = (local_y * 16 * 16) + (z * 16) + x
                    byte_index = nibble_index // 2
                    shift = 0 if (nibble_index % 2) == 0 else 4
                    section_bytes[section_idx][byte_index] |= 0xF << shift
                elif not transparent:
                    sky_open = False

    # 顶部边界 section 作为天空光源，保持全亮；底部边界置空。
    section_bytes[-1] = bytearray([0xFF] * 2048)

    sky_mask = 0
    empty_sky_mask = 0
    sky_arrays: list[bytes] = []
    for idx, data in enumerate(section_bytes):
        if any(data):
            sky_mask |= 1 << idx
            sky_arrays.append(bytes(data))
        else:
            empty_sky_mask |= 1 << idx

    block_mask = 0
    empty_block_mask = (1 << section_count) - 1
    block_arrays: list[bytes] = []
    return sky_mask, block_mask, empty_sky_mask, empty_block_mask, sky_arrays, block_arrays


async def _send_prebuilt_chunk(conn: Connection, chunk_x: int, chunk_z: int,
                                motion_blocking: list[int], world_surface: list[int],
                                chunk_data: bytes, chunk_blocks: list[list[list[int]]]):
    """
    发送已预生成的区块数据包。
    区块生成和编码已在线程池中完成，此处仅组装协议数据包并发送。
    使用版本处理器来发送正确的格式。
    """
    if conn.version_handler is not None and conn.protocol_version < 767:
        # For older versions, we may need to re-encode the chunk data
        await _send_versioned_chunk(conn, chunk_x, chunk_z,
                                     motion_blocking, world_surface,
                                     chunk_data, chunk_blocks)
        return

    # Native 1.21.1 chunk data format
    payload = bytearray()

    # Chunk X, Z (Int)
    payload.extend(write_int(chunk_x))
    payload.extend(write_int(chunk_z))

    # Heightmaps (NBT Compound)
    heightmap_nbt = {
        "MOTION_BLOCKING": NbtLongArray(motion_blocking),
        "WORLD_SURFACE": NbtLongArray(world_surface),
    }
    payload.extend(encode_nbt(heightmap_nbt, with_type=True))

    # Chunk Data
    payload.extend(write_varint(len(chunk_data)))
    payload.extend(chunk_data)

    # Block Entities (无)
    payload.extend(write_varint(0))

    # --- 光照数据 ---
    sky_mask, block_mask, empty_sky_mask, empty_block_mask, sky_arrays, block_arrays = (
        _build_chunk_light_data(chunk_blocks)
    )
    payload.extend(write_varint(1))
    payload.extend(write_long(sky_mask))
    payload.extend(write_varint(1))
    payload.extend(write_long(block_mask))
    payload.extend(write_varint(1))
    payload.extend(write_long(empty_sky_mask))
    payload.extend(write_varint(1))
    payload.extend(write_long(empty_block_mask))

    payload.extend(write_varint(len(sky_arrays)))
    for sky_light_section in sky_arrays:
        payload.extend(write_varint(2048))
        payload.extend(sky_light_section)

    payload.extend(write_varint(len(block_arrays)))
    for block_light_section in block_arrays:
        payload.extend(write_varint(2048))
        payload.extend(block_light_section)

    chunk_pid = conn.version_handler.get_packet_id("chunk_data") if conn.version_handler else 0x27
    if chunk_pid is not None:
        await conn.send_packet(chunk_pid, bytes(payload))


async def _send_versioned_chunk(conn: Connection, chunk_x: int, chunk_z: int,
                                 motion_blocking: list[int], world_surface: list[int],
                                 native_chunk_data: bytes, chunk_blocks: list[list[list[int]]]):
    """
    Send chunk data using the version-specific format for older clients.
    This handles the translation from 384-height to 256-height for pre-1.17 clients.
    """
    handler = conn.version_handler

    # Build version-specific chunk data
    versioned_chunk_data = handler.build_chunk_data_for_version(chunk_blocks)
    versioned_heightmap = handler.build_heightmap_for_version(chunk_blocks)

    # Build the chunk packet using the version handler
    packet_data = handler.build_chunk_packet(
        chunk_x, chunk_z,
        versioned_chunk_data,
        versioned_heightmap,
        chunk_blocks=chunk_blocks,
    )

    chunk_pid = handler.get_packet_id("chunk_data")
    if chunk_pid is not None:
        await conn.send_packet(chunk_pid, packet_data)


async def _send_chunk_batch(conn: Connection, chunk_results):
    """发送一批区块。"""
    if not chunk_results or not conn.alive:
        return

    await conn.send_packet(0x0D, b'')
    for cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks in chunk_results:
        if not conn.alive:
            break
        await _send_prebuilt_chunk(
            conn, cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks
        )
    await conn.send_packet(0x0C, write_varint(len(chunk_results)))


async def _send_chunk_results_streamed(conn: Connection, chunk_results,
                                       batch_size: int = CHUNK_STREAM_BATCH_SIZE):
    """将大量区块按小批次流式发送，减少客户端一次性吃包压力。"""
    if not chunk_results or not conn.alive:
        return

    for index in range(0, len(chunk_results), batch_size):
        if not conn.alive:
            break
        batch = chunk_results[index:index + batch_size]
        await _send_chunk_batch(conn, batch)
        await asyncio.sleep(0)


async def _send_deferred_chunks(conn: Connection, server, chunk_coords, total_count: int):
    """后台发送出生点外圈区块。"""
    if not conn.alive or not chunk_coords:
        return

    loop = asyncio.get_event_loop()
    start = time.time()

    def _generate_deferred():
        return server.generate_chunk_results(chunk_coords)[0]

    chunk_results = await loop.run_in_executor(None, _generate_deferred)
    await _send_chunk_results_streamed(conn, chunk_results)
    conn.loaded_chunks.update((cx, cz) for cx, cz, *_ in chunk_results)
    logger.info(
        f"已向 {conn.username} 补发远距离区块 {len(chunk_results)} 个 "
        f"(总计 {total_count} 个, 用时 {time.time() - start:.1f}s)"
    )


async def _stream_chunks_around_player(conn: Connection, server):
    """在玩家跨区块移动时，继续补发新进入视距的区块。"""
    while conn.alive:
        center_cx = int(conn.x) >> 4
        center_cz = int(conn.z) >> 4
        if conn.chunk_center == (center_cx, center_cz):
            return

        conn.chunk_center = (center_cx, center_cz)
        from handlers.play.join import _send_center_chunk
        await _send_center_chunk(conn, center_cx, center_cz)

        desired_coords = set(_sorted_chunk_coords(center_cx, center_cz, server.view_distance))
        missing_coords = [
            coord for coord in _sorted_chunk_coords(center_cx, center_cz, server.view_distance)
            if coord not in conn.loaded_chunks
        ]
        if not missing_coords:
            conn.loaded_chunks.intersection_update(desired_coords)
            continue

        loop = asyncio.get_event_loop()
        start = time.time()
        logger.info(
            f"玩家 {conn.username} 进入新区块中心 {center_cx},{center_cz}，"
            f"正在补发 {len(missing_coords)} 个新区块..."
        )

        def _generate_missing():
            return server.generate_chunk_results(missing_coords)[0]

        chunk_results = await loop.run_in_executor(None, _generate_missing)
        if not conn.alive:
            return

        await _send_chunk_results_streamed(conn, chunk_results)
        conn.loaded_chunks.update((cx, cz) for cx, cz, *_ in chunk_results)
        conn.loaded_chunks.intersection_update(desired_coords)

        logger.info(
            f"已向 {conn.username} 动态补发新区块 {len(chunk_results)} 个 "
            f"(中心={center_cx},{center_cz}, 用时 {time.time() - start:.1f}s)"
        )


def _schedule_chunk_stream_update(conn: Connection, server):
    """串行调度区块流式补发，避免玩家连续移动时重复并发补块。"""
    if not conn.alive:
        return
    if conn.chunk_stream_task is not None and not conn.chunk_stream_task.done():
        return
    conn.chunk_stream_task = asyncio.create_task(_stream_chunks_around_player(conn, server))
