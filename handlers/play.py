# ============================================================
# PyMC - 游戏阶段 (Play) 处理器
# 处理玩家在游戏中的所有交互
# ============================================================

"""
Play 阶段数据包处理器。
包括: 玩家加入、区块发送、位置同步、聊天、KeepAlive 等。

数据包 ID 参考 (1.21.1, 协议 767):
--- 服务端发送 (Clientbound) ---
  0x22  - Game Event (game_state_change)
  0x26  - Keep Alive
  0x27  - Chunk Data (map_chunk)
  0x2B  - Login / Join Game (login)
  0x3D  - Player Remove (player_remove)
  0x3E  - Player Info Update (player_info)
  0x40  - Synchronize Player Position (position)
  0x42  - Remove Entities (entity_destroy)
  0x54  - Set Center Chunk (update_view_position)
  0x56  - Set Default Spawn Position (spawn_position)
  0x6C  - System Chat Message (system_chat)

--- 客户端发送 (Serverbound) ---
  0x00  - Confirm Teleportation
  0x04  - Chat Command
  0x05  - Chat Message
  0x18  - Keep Alive
  0x1A  - Player Position
  0x1B  - Player Position and Rotation
  0x1C  - Player Rotation
  0x1D  - Player On Ground
"""

import logging
import struct
import time
import uuid
import asyncio
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double, write_short,
    write_uuid, write_identifier, write_position,
    read_varint, read_string, read_double, read_float, read_boolean,
    read_long, read_byte
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray
from network.connection import Connection, ConnectionState
from world.chunk import (
    build_chunk_column_from_terrain, build_heightmap_from_terrain,
    build_flat_chunk_column, build_heightmap_data
)
from world.terrain import TerrainGenerator
from world.blocks import (
    AIR, WATER, LAVA, GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL,
    MOSS_BLOCK, SAND, RED_SAND, GRAVEL, SNOW_BLOCK, CLAY, STONE,
)

logger = logging.getLogger("PyMC.游戏")

COMMAND_ALIASES = {
    "teleport": "tp",
    "experience": "xp",
    "tell": "msg",
    "w": "msg",
    "tm": "teammsg",
}

RECOGNIZED_BUT_UNSUPPORTED = {
    "advancement", "attribute", "bossbar", "clear", "clone", "damage", "data",
    "datapack", "debug", "effect", "enchant", "execute", "fill", "fillbiome",
    "forceload", "function", "gamerule", "give", "item", "jfr", "locate",
    "loot", "particle", "perf", "place", "playsound", "publish", "random",
    "recipe", "return", "ride", "schedule", "scoreboard", "setblock",
    "setidletimeout", "spawnpoint", "spectate", "spreadplayers", "summon",
    "tag", "team", "teammsg", "tellraw", "title", "transfer", "trigger",
    "worldborder", "xp", "kill",
}

ALL_VANILLA_COMMAND_NAMES = sorted({
    "advancement", "attribute", "ban", "ban-ip", "banlist", "bossbar", "clear",
    "clone", "damage", "data", "datapack", "debug", "defaultgamemode", "deop",
    "difficulty", "effect", "enchant", "execute", "experience", "fill",
    "fillbiome", "forceload", "function", "gamemode", "gamerule", "give",
    "help", "item", "jfr", "kick", "kill", "list", "locate", "loot", "me",
    "msg", "op", "pardon", "pardon-ip", "particle", "perf", "place",
    "playsound", "publish", "random", "recipe", "reload", "return", "ride",
    "save-all", "save-off", "save-on", "say", "schedule", "scoreboard",
    "seed", "setblock", "setidletimeout", "setworldspawn", "spawnpoint",
    "spectate", "spreadplayers", "stop", "summon", "tag", "team", "teammsg",
    "teleport", "tell", "tellraw", "time", "title", "tm", "tp", "transfer",
    "trigger", "w", "weather", "whitelist", "worldborder", "xp",
    # PyMC 扩展
    "group", "perm", "save-status",
})


# ============================================================
# Play 阶段数据包分发
# ============================================================

async def handle_play(conn: Connection, packet_id: int, payload: bytes,
                      server):
    """分发 Play 阶段的客户端数据包。"""

    if packet_id == 0x00:
        # Confirm Teleportation
        _handle_confirm_teleportation(conn, payload)

    elif packet_id == 0x03:
        # Chat Command (聊天命令, 带签名)
        await _handle_chat_command(conn, payload, server)

    elif packet_id == 0x04:
        # Chat Command (聊天命令, 无签名)
        await _handle_chat_command(conn, payload, server)

    elif packet_id == 0x05:
        # Chat Message (聊天消息)
        await _handle_chat_message(conn, payload, server)

    elif packet_id == 0x07:
        # Chunk Batch Received (客户端确认区块批次)
        pass  # 不需要特殊处理

    elif packet_id == 0x18:
        # Keep Alive
        _handle_keepalive(conn, payload)

    elif packet_id == 0x1A:
        # Player Position
        await _handle_player_position(conn, payload, server)

    elif packet_id == 0x1B:
        # Player Position and Rotation
        await _handle_player_position_rotation(conn, payload, server)

    elif packet_id == 0x1C:
        # Player Rotation
        await _handle_player_rotation(conn, payload, server)

    elif packet_id == 0x1D:
        # Player On Ground
        _handle_player_on_ground(conn, payload)

    else:
        # 忽略未处理的数据包
        pass


# ============================================================
# 玩家加入游戏
# ============================================================

async def send_join_game(conn: Connection, server):
    """
    发送 Login (Join Game) 数据包 (0x2B) 及相关初始化数据包。
    这是玩家进入 Play 阶段后收到的第一个数据包。
    """
    logger.info(f"正在发送游戏数据给 {conn.username}...")
    load_start = time.time()
    server._initialize_terrain_generator()

    terrain = server.terrain_generator
    use_native = getattr(server, '_use_native_terrain', False)

    # --- 1. Login (Join Game) 数据包 ---
    await _send_login_play(conn, server)

    # --- 2. 发送游戏事件: 等待区块 ---
    await _send_game_event(conn, 13, 0.0)  # 事件13: Start waiting for chunks

    # --- 3. 设置区块中心 ---
    center_cx = int(server.spawn_position[0]) >> 4
    center_cz = int(server.spawn_position[2]) >> 4
    await _send_center_chunk(conn, center_cx, center_cz)
    await conn.send_packet(0x55, write_varint(server.view_distance))  # Set Chunk Cache Radius

    view_distance = server.view_distance
    chunk_coords = _sorted_chunk_coords(center_cx, center_cz, view_distance)
    immediate_radius = min(server.join_immediate_radius, view_distance)
    immediate_count = (immediate_radius * 2 + 1) ** 2
    immediate_coords = chunk_coords[:immediate_count]
    deferred_coords = chunk_coords[immediate_count:]

    # 在线程池中预生成所有区块数据 (避免阻塞事件循环)
    loop = asyncio.get_event_loop()
    logger.info(f"正在准备 {len(chunk_coords)} 个区块 (视距={view_distance}, "
                f"引擎={'C++' if use_native else 'Python'})...")
    gen_start = time.time()

    def _generate_chunks(coords):
        """在工作线程中批量准备区块数据。"""
        results, loaded, generated = server.generate_chunk_results(coords)
        if loaded > 0:
            logger.info(f"从存档加载 {loaded} 个区块")
        if generated > 0:
            logger.info(f"新生成 {generated} 个区块")
        return results

    immediate_results = await loop.run_in_executor(None, _generate_chunks, immediate_coords)
    gen_elapsed = time.time() - gen_start
    logger.info(f"出生点附近区块已准备完成: {len(immediate_results)} 个, 耗时 {gen_elapsed:.1f}s")

    await _send_chunk_batch(conn, immediate_results)

    # --- 5. 基于实际出生区块修正出生点 ---
    spawn_x, _, spawn_z = server.spawn_position
    actual_spawn_x, actual_spawn_y, actual_spawn_z = _resolve_spawn_location(
        server, spawn_x, spawn_z
    )
    server.spawn_position = (
        int(actual_spawn_x), int(actual_spawn_y), int(actual_spawn_z)
    )
    await _send_spawn_position(conn, *server.spawn_position)

    # --- 6. 同步玩家位置 ---
    conn.x = float(server.spawn_position[0]) + 0.5
    conn.y = float(actual_spawn_y)
    conn.z = float(server.spawn_position[2]) + 0.5
    conn.fall_start_y = conn.y
    conn.gamemode = server.config.get("gamemode", "creative")
    await _send_synchronize_position(conn)
    await _send_update_health(conn)
    await _send_time_update(conn, server)

    # --- 7. 通知其他玩家 ---
    await _broadcast_player_join(conn, server)

    load_elapsed = time.time() - load_start
    logger.info(f"加载完成，用时 {load_elapsed:.1f}s")
    logger.info(
        f"玩家 {conn.username} 已成功加入游戏 "
        f"(出生点: {server.spawn_position[0]}, {server.spawn_position[1]}, {server.spawn_position[2]})"
    )

    if deferred_coords:
        asyncio.create_task(_send_deferred_chunks(
            conn, server, deferred_coords, len(chunk_coords)
        ))


async def _send_login_play(conn: Connection, server):
    """
    发送 Login (Join Game) 数据包 (0x2B)。
    这是一个包含大量字段的复杂数据包。
    """
    payload = bytearray()

    # Entity ID (Int)
    payload.extend(write_int(conn.entity_id))

    # Is Hardcore (Boolean)
    payload.extend(write_boolean(False))

    # Dimension Count + Dimension Names (VarInt + Array of Identifier)
    dimension_names = [
        "minecraft:overworld",
        "minecraft:the_nether",
        "minecraft:the_end"
    ]
    payload.extend(write_varint(len(dimension_names)))
    for dim in dimension_names:
        payload.extend(write_identifier(dim))

    # Max Players (VarInt)
    payload.extend(write_varint(server.max_players))

    # View Distance (VarInt)
    payload.extend(write_varint(server.view_distance))

    # Simulation Distance (VarInt)
    payload.extend(write_varint(server.view_distance))

    # Reduced Debug Info (Boolean)
    payload.extend(write_boolean(False))

    # Enable Respawn Screen (Boolean)
    payload.extend(write_boolean(True))

    # Do Limited Crafting (Boolean)
    payload.extend(write_boolean(False))

    # Dimension Type (VarInt - 注册表索引)
    payload.extend(write_varint(0))  # 0 = overworld

    # Dimension Name (Identifier)
    payload.extend(write_identifier("minecraft:overworld"))

    # Hashed Seed (Long)
    payload.extend(write_long(0))

    # Game Mode (Unsigned Byte) - 0=生存, 1=创造, 2=冒险, 3=旁观
    gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
    payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

    # Previous Game Mode (Byte) - -1 表示无
    payload.extend(write_byte(-1))

    # Is Debug (Boolean)
    payload.extend(write_boolean(False))

    # Is Flat (Boolean)
    payload.extend(write_boolean(False))  # 使用噪声地形，不再是平坦世界

    # Has Death Location (Boolean)
    payload.extend(write_boolean(False))

    # Portal Cooldown (VarInt)
    payload.extend(write_varint(0))

    # Enforces Secure Chat (Boolean)
    payload.extend(write_boolean(False))

    await conn.send_packet(0x2B, bytes(payload))


async def _send_spawn_position(conn: Connection, x: int, y: int, z: int):
    """发送 Set Default Spawn Position 数据包 (0x56)。"""
    payload = bytearray()
    payload.extend(write_position(x, y, z))  # 出生点位置
    payload.extend(write_float(0.0))         # 角度
    await conn.send_packet(0x56, bytes(payload))


async def _send_game_event(conn: Connection, event: int, value: float):
    """发送 Game Event 数据包 (0x22)。"""
    payload = bytearray()
    payload.extend(write_ubyte(event))
    payload.extend(write_float(value))
    await conn.send_packet(0x22, bytes(payload))


async def _send_center_chunk(conn: Connection, chunk_x: int, chunk_z: int):
    """发送 Set Center Chunk 数据包 (0x54, update_view_position)。"""
    payload = bytearray()
    payload.extend(write_varint(chunk_x))
    payload.extend(write_varint(chunk_z))
    await conn.send_packet(0x54, bytes(payload))


async def _send_chunk_data(conn: Connection, chunk_x: int, chunk_z: int):
    """
    发送 Chunk Data and Update Light 数据包 (0x27)。
    """
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
    # Sky Light Mask (BitSet: VarInt 长度 + Long 数组)
    # 25 个 Section (24 + 2 边界) -> 需要 1 个 Long
    # 全亮: 所有位设为 1
    all_bits = (1 << 26) - 1  # 26 位全 1
    payload.extend(write_varint(1))  # BitSet 长度
    payload.extend(write_long(all_bits))

    # Block Light Mask
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))

    # Empty Sky Light Mask
    payload.extend(write_varint(0))

    # Empty Block Light Mask
    payload.extend(write_varint(0))

    # Sky Light Arrays (每个 Section 2048 字节，全亮 = 0xFF)
    sky_light_section = bytes([0xFF] * 2048)
    light_section_count = 26  # 24 + 2 边界
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

    # Heightmaps (NBT Compound)
    # 计算运动阻塞和世界表面高度图
    heightmap_longs = build_heightmap_from_terrain(chunk_blocks)
    heightmap_nbt = {
        "MOTION_BLOCKING": NbtLongArray(heightmap_longs),
        "WORLD_SURFACE": NbtLongArray(heightmap_longs),
    }
    payload.extend(encode_nbt(heightmap_nbt, with_type=True))

    # Chunk Data (Byte Array: VarInt 长度 + 数据)
    # 从地形方块数据构建区块列
    chunk_data = build_chunk_column_from_terrain(chunk_blocks)
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

    # Sky Light Arrays (全亮)
    sky_light_section = bytes([0xFF] * 2048)
    light_section_count = 26
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(sky_light_section)

    # Block Light Arrays (全黑)
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
    发送已预生成的区块数据包 (0x27)。
    区块生成和编码已在线程池中完成，此处仅组装协议数据包并发送。
    """
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

    await conn.send_packet(0x27, bytes(payload))


def _resolve_spawn_location(server, block_x: int, block_z: int) -> tuple[int, int, int]:
    """
    在出生点附近选择一个更安全、更平坦的落脚点。
    优先选择草地/泥土/沙地等自然地表，并要求头顶有足够空间。
    """
    search_radius = 8
    preferred_blocks = {
        GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL, MOSS_BLOCK,
        SAND, RED_SAND, GRAVEL, SNOW_BLOCK, CLAY,
    }
    chunk_cache: dict[tuple[int, int], list[list[list[int]]] | None] = {}

    def _load_chunk(cx: int, cz: int):
        key = (cx, cz)
        if key not in chunk_cache:
            chunk_cache[key] = server.world_storage.load_generated_chunk(cx, cz)
        return chunk_cache[key]

    def _column_top(world_x: int, world_z: int):
        chunk_x = int(world_x) >> 4
        chunk_z = int(world_z) >> 4
        chunk_blocks = _load_chunk(chunk_x, chunk_z)
        if chunk_blocks is None:
            return None

        local_x = int(world_x) & 15
        local_z = int(world_z) & 15
        for y_index in range(len(chunk_blocks) - 1, -1, -1):
            block_id = chunk_blocks[y_index][local_z][local_x]
            if block_id in (AIR, WATER, LAVA):
                continue

            above_1 = chunk_blocks[y_index + 1][local_z][local_x] if y_index + 1 < len(chunk_blocks) else AIR
            above_2 = chunk_blocks[y_index + 2][local_z][local_x] if y_index + 2 < len(chunk_blocks) else AIR
            return {
                "block_id": block_id,
                "world_y": y_index - 64,
                "clear": above_1 == AIR and above_2 == AIR,
            }
        return None

    def _surface_slope(world_x: int, world_z: int) -> int:
        center = _column_top(world_x, world_z)
        if center is None:
            return 999
        deltas = []
        for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = _column_top(world_x + dx, world_z + dz)
            if neighbor is None:
                continue
            deltas.append(abs(center["world_y"] - neighbor["world_y"]))
        return max(deltas) if deltas else 0

    best_choice = None
    best_score = None
    fallback_y = int(server.spawn_position[1])

    for dz in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            world_x = int(block_x) + dx
            world_z = int(block_z) + dz
            column = _column_top(world_x, world_z)
            if column is None:
                continue

            if dx == 0 and dz == 0:
                fallback_y = column["world_y"] + 1

            if not column["clear"]:
                continue
            if column["block_id"] not in preferred_blocks:
                continue

            slope = _surface_slope(world_x, world_z)
            distance = abs(dx) + abs(dz)
            score = distance * 6 + slope * 10

            if column["block_id"] in preferred_blocks:
                score -= 40
            if column["world_y"] < 62:
                score += 20

            if best_score is None or score < best_score:
                best_score = score
                best_choice = (world_x, column["world_y"] + 1, world_z)

    if best_choice is not None:
        return best_choice
    return int(block_x), fallback_y, int(block_z)


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


async def _damage_player(conn: Connection, amount: float, reason: str, server):
    """对玩家造成基础伤害。死亡时回到出生点。"""
    if not conn.alive or conn.gamemode in {"creative", "spectator"}:
        return

    conn.health = max(0.0, conn.health - amount)
    await _send_update_health(conn)

    if conn.health > 0:
        await send_system_message(conn, f"[PyMC] 你受到了 {amount:.1f} 点{reason}伤害")
        return

    await send_system_message(conn, "[PyMC] 你死亡了，已返回出生点")
    spawn_x, _, spawn_z = server.spawn_position
    respawn_x, respawn_y, respawn_z = _resolve_spawn_location(server, spawn_x, spawn_z)
    server.spawn_position = (int(respawn_x), int(respawn_y), int(respawn_z))
    conn.x = float(respawn_x) + 0.5
    conn.y = float(respawn_y)
    conn.z = float(respawn_z) + 0.5
    conn.fall_start_y = conn.y
    conn.health = 20.0
    conn.food = 20
    conn.saturation = 5.0
    await _send_synchronize_position(conn)
    await _send_update_health(conn)


async def _update_player_motion_state(conn: Connection, new_y: float, new_on_ground: bool, server):
    """更新玩家移动状态并处理最基础的摔落伤害。"""
    previous_on_ground = conn.on_ground
    previous_y = conn.y

    if previous_on_ground and not new_on_ground:
        conn.fall_start_y = previous_y

    if (not previous_on_ground) and new_on_ground:
        fall_distance = conn.fall_start_y - new_y
        if fall_distance > 3.0:
            await _damage_player(conn, max(0.0, fall_distance - 3.0), "摔落", server)
        conn.fall_start_y = new_y

    if new_on_ground:
        conn.fall_start_y = new_y


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


async def _send_deferred_chunks(conn: Connection, server, chunk_coords, total_count: int):
    """后台发送出生点外圈区块。"""
    if not conn.alive or not chunk_coords:
        return

    loop = asyncio.get_event_loop()
    start = time.time()

    def _generate_deferred():
        return server.generate_chunk_results(chunk_coords)[0]

    chunk_results = await loop.run_in_executor(None, _generate_deferred)
    await _send_chunk_batch(conn, chunk_results)
    logger.info(
        f"已向 {conn.username} 补发远距离区块 {len(chunk_results)} 个 "
        f"(总计 {total_count} 个, 用时 {time.time() - start:.1f}s)"
    )


async def _send_synchronize_position(conn: Connection):
    """发送 Synchronize Player Position 数据包 (0x40)。"""
    payload = bytearray()
    payload.extend(write_double(conn.x))    # X
    payload.extend(write_double(conn.y))    # Y
    payload.extend(write_double(conn.z))    # Z
    payload.extend(write_float(conn.yaw))   # Yaw
    payload.extend(write_float(conn.pitch)) # Pitch
    payload.extend(write_ubyte(0))          # Flags (全部绝对坐标)
    conn.teleport_id += 1
    payload.extend(write_varint(conn.teleport_id))  # Teleport ID
    await conn.send_packet(0x40, bytes(payload))


async def _send_update_health(conn: Connection):
    """发送基础生命值同步。"""
    payload = bytearray()
    payload.extend(write_float(float(conn.health)))
    payload.extend(write_varint(int(conn.food)))
    payload.extend(write_float(float(conn.saturation)))
    await conn.send_packet(0x62, bytes(payload))


async def _send_time_update(conn: Connection, server):
    """发送世界时间。"""
    payload = bytearray()
    payload.extend(write_long(int(server.world_time)))
    payload.extend(write_long(int(server.world_time)))
    payload.extend(write_boolean(True))
    await conn.send_packet(0x6B, bytes(payload))


# ============================================================
# 玩家信息 (Player Info) 构建
# ============================================================

def build_player_info_update(conn: Connection) -> bytes:
    """
    构建 Player Info Update 数据包负载 (0x3E)。
    Action: Add Player + Listed
    """
    payload = bytearray()

    # Actions BitSet: 0x01 (Add Player) | 0x08 (Update Listed)
    actions = 0x01 | 0x08
    payload.append(actions)

    # 玩家数量
    payload.extend(write_varint(1))

    # 玩家 UUID
    payload.extend(write_uuid(conn.uuid))

    # --- Action: Add Player ---
    payload.extend(write_string(conn.username))  # 名称
    payload.extend(write_varint(0))              # 属性数量 = 0

    # --- Action: Update Listed ---
    payload.extend(write_boolean(True))          # 是否在列表中

    return bytes(payload)


def build_player_info_remove(conn: Connection) -> bytes:
    """构建 Player Info Remove 数据包负载 (0x3D)。"""
    payload = bytearray()
    payload.extend(write_varint(1))          # 玩家数量
    payload.extend(write_uuid(conn.uuid))    # 玩家 UUID
    return bytes(payload)


def build_remove_entities(entity_ids: list[int]) -> bytes:
    """构建 Remove Entities 数据包负载 (0x42)。"""
    payload = bytearray()
    payload.extend(write_varint(len(entity_ids)))
    for eid in entity_ids:
        payload.extend(write_varint(eid))
    return bytes(payload)


async def _broadcast_player_join(conn: Connection, server):
    """向所有在线玩家广播新玩家加入。"""
    # 发送新玩家的信息给所有人 (包括自己)
    player_info = build_player_info_update(conn)
    for other in server.get_online_players():
        await other.send_packet(0x3E, player_info)

    # 发送所有已有玩家的信息给新玩家
    for other in server.get_online_players():
        if other != conn:
            other_info = build_player_info_update(other)
            await conn.send_packet(0x3E, other_info)


# ============================================================
# 客户端数据包处理
# ============================================================

def _handle_confirm_teleportation(conn: Connection, payload: bytes):
    """处理 Confirm Teleportation (0x00)。"""
    teleport_id, _ = read_varint(payload, 0)
    logger.debug(f"{conn.username} 确认传送 ID={teleport_id}")


async def _handle_chat_message(conn: Connection, payload: bytes, server):
    """
    处理 Chat Message (0x05)。
    在 1.21.1 中，聊天消息使用签名系统，但离线模式下我们简化处理。
    """
    offset = 0
    message, offset = read_string(payload, offset)

    logger.info(f"<{conn.username}> {message}")

    # 1.21.1 的 system_chat.content 是匿名 NBT 文本组件，不是 JSON 字符串。
    chat_component = {
        "translate": "chat.type.text",
        "with": [
            {"text": conn.username, "color": "yellow"},
            {"text": message}
        ]
    }
    server.broadcast_packet(0x6C, build_system_message_payload(chat_component))


async def _handle_chat_command(conn: Connection, payload: bytes, server):
    """处理 Chat Command (0x04)。"""
    offset = 0
    command, offset = read_string(payload, offset)

    logger.info(f"{conn.username} 执行命令: /{command}")
    await execute_server_command(server, command, source_conn=conn)


def build_system_message_payload(message: str | dict) -> bytes:
    """构建 1.21.1 system_chat 负载。"""
    if isinstance(message, dict):
        component = message
    else:
        component = {"text": message, "color": "gray"}

    payload = bytearray()
    payload.extend(encode_nbt(component, with_type=True))
    payload.extend(write_boolean(False))  # overlay
    return bytes(payload)


async def send_system_message(conn: Connection, text: str):
    """发送系统聊天消息给单个玩家。"""
    await conn.send_packet(0x6C, build_system_message_payload(text))


async def execute_server_command(server, command: str,
                                 source_conn: Connection | None = None) -> bool:
    """
    执行玩家或控制台命令。

    返回:
        True 表示识别并处理了命令
        False 表示命令为空或未知
    """
    parts = command.strip().split()
    if not parts:
        return False

    original_cmd = parts[0].lower()
    cmd = COMMAND_ALIASES.get(original_cmd, original_cmd)
    source_name = source_conn.username if source_conn else "控制台"
    mode_map = {
        "survival": 0, "creative": 1, "adventure": 2, "spectator": 3,
        "0": 0, "1": 1, "2": 2, "3": 3,
    }
    mode_names = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}

    async def reply(text: str):
        if source_conn is not None:
            await send_system_message(source_conn, text)
        else:
            logger.info(text)

    if source_conn is not None:
        permission_node = f"command.{cmd}"
        if not server.permissions.has_permission(source_conn.username, permission_node):
            await reply(f"[PyMC] 你没有权限执行该命令: /{original_cmd}")
            return True

    if cmd == "help":
        if source_conn is not None:
            level = server.permissions.get_permission_level(source_conn.username)
            await reply(f"[PyMC] 你的权限组: {level}")
            await reply("[PyMC] 已识别原版指令: /help, /list, /msg, /me, /tp, /gamemode, /kick, /ban, /op, /whitelist, /time, /weather, /stop 等")
        else:
            await reply("[PyMC] 控制台命令: help, list, say, tp, gamemode, kick, ban, ban-ip, op, deop, whitelist, group, perm, stop")
        return True

    if cmd == "list":
        players = server.get_online_players()
        names = ", ".join(p.username for p in players) if players else "无"
        await reply(f"[PyMC] 在线玩家 ({len(players)}/{server.max_players}): {names}")
        return True

    if cmd == "say":
        if len(parts) < 2:
            await reply("[PyMC] 用法: say <消息>")
            return True
        message = command.strip()[len(parts[0]):].strip()
        full_text = f"[Server] {message}"
        server.broadcast_system_message(full_text)
        logger.info(f"[控制台广播] {message}")
        return True

    if cmd == "me":
        if len(parts) < 2:
            await reply("[PyMC] 用法: /me <动作>")
            return True
        action = command.strip()[len(parts[0]):].strip()
        server.broadcast_system_message(f"* {source_name} {action}")
        logger.info(f"* {source_name} {action}")
        return True

    if cmd == "msg":
        if len(parts) < 3:
            await reply("[PyMC] 用法: /msg <玩家> <消息>")
            return True
        target = server.find_player(parts[1])
        if target is None:
            await reply(f"[PyMC] 未找到玩家: {parts[1]}")
            return True
        message = command.strip().split(maxsplit=2)[2]
        await send_system_message(target, f"[私聊] {source_name}: {message}")
        if source_conn is not None and target != source_conn:
            await send_system_message(source_conn, f"[私聊 -> {target.username}] {message}")
        else:
            logger.info(f"[私聊 -> {target.username}] {message}")
        return True

    if cmd == "tp":
        target = source_conn
        coord_index = 1
        if source_conn is None:
            if len(parts) < 5:
                await reply("[PyMC] 用法: tp <玩家> <x> <y> <z>")
                return True
            target = server.find_player(parts[1])
            coord_index = 2
            if target is None:
                await reply(f"[PyMC] 未找到玩家: {parts[1]}")
                return True
        elif len(parts) < 4:
            await reply("[PyMC] 用法: /tp <x> <y> <z>")
            return True

        try:
            x = float(parts[coord_index])
            y = float(parts[coord_index + 1])
            z = float(parts[coord_index + 2])
        except (ValueError, IndexError):
            await reply("[PyMC] 坐标格式无效")
            return True

        target.x, target.y, target.z = x, y, z
        await _send_synchronize_position(target)
        await send_system_message(target, f"[PyMC] 已传送到 ({x}, {y}, {z})")
        if source_conn is None:
            await reply(f"[PyMC] 已将 {target.username} 传送到 ({x}, {y}, {z})")
        return True

    if cmd == "gamemode":
        target = source_conn
        mode_name = parts[1].lower() if len(parts) >= 2 else None

        if source_conn is None:
            if len(parts) < 3:
                await reply("[PyMC] 用法: gamemode <玩家> <survival|creative|adventure|spectator>")
                return True
            target = server.find_player(parts[1])
            mode_name = parts[2].lower()
            if target is None:
                await reply(f"[PyMC] 未找到玩家: {parts[1]}")
                return True
        elif mode_name is None:
            await reply("[PyMC] 用法: /gamemode <survival|creative|adventure|spectator>")
            return True

        if mode_name not in mode_map:
            await reply("[PyMC] 无效模式，可用值: survival, creative, adventure, spectator")
            return True

        mode = mode_map[mode_name]
        await _send_game_event(target, 3, float(mode))
        await send_system_message(target, f"[PyMC] 游戏模式已切换为 {mode_names.get(mode, '未知')}")
        if source_conn is None:
            await reply(f"[PyMC] 已将 {target.username} 的游戏模式切换为 {mode_names.get(mode, '未知')}")
        return True

    if cmd == "seed":
        seed = server.config.get("level-seed", "")
        text = f"[PyMC] 世界种子: {seed if seed != '' else 0}"
        await reply(text)
        return True

    if cmd == "difficulty":
        if len(parts) == 1:
            await reply(f"[PyMC] 当前难度: {server.config.get('difficulty', 'normal')}")
            return True
        value = parts[1].lower()
        if value not in {"peaceful", "easy", "normal", "hard"}:
            await reply("[PyMC] 用法: difficulty <peaceful|easy|normal|hard>")
            return True
        server.config["difficulty"] = value
        server.save_runtime_config()
        await reply(f"[PyMC] 难度已设置为 {value}")
        return True

    if cmd == "defaultgamemode":
        if len(parts) < 2:
            await reply("[PyMC] 用法: defaultgamemode <survival|creative|adventure|spectator>")
            return True
        value = parts[1].lower()
        if value not in mode_map:
            await reply("[PyMC] 无效模式")
            return True
        normalized = {
            0: "survival",
            1: "creative",
            2: "adventure",
            3: "spectator",
        }[mode_map[value]]
        server.config["gamemode"] = normalized
        server.save_runtime_config()
        await reply(f"[PyMC] 默认游戏模式已设置为 {normalized}")
        return True

    if cmd == "time":
        if len(parts) < 2:
            await reply(f"[PyMC] 当前时间: {server.world_time}")
            return True
        action = parts[1].lower()
        if action == "set" and len(parts) >= 3:
            presets = {"day": 1000, "noon": 6000, "night": 13000, "midnight": 18000}
            try:
                server.world_time = presets.get(parts[2].lower(), int(parts[2]))
            except ValueError:
                await reply("[PyMC] 用法: time set <day|noon|night|midnight|ticks>")
                return True
            await reply(f"[PyMC] 世界时间已设置为 {server.world_time}")
            return True
        if action == "add" and len(parts) >= 3:
            try:
                server.world_time += int(parts[2])
            except ValueError:
                await reply("[PyMC] 用法: time add <ticks>")
                return True
            await reply(f"[PyMC] 世界时间已变更为 {server.world_time}")
            return True
        if action == "query":
            await reply(f"[PyMC] 世界时间: {server.world_time}")
            return True
        await reply("[PyMC] 用法: time <set|add|query> ...")
        return True

    if cmd == "weather":
        if len(parts) == 1:
            await reply(f"[PyMC] 当前天气: {server.weather}")
            return True
        value = parts[1].lower()
        if value not in {"clear", "rain", "thunder"}:
            await reply("[PyMC] 用法: weather <clear|rain|thunder>")
            return True
        server.weather = value
        await reply(f"[PyMC] 天气已设置为 {value}")
        return True

    if cmd == "setworldspawn":
        if len(parts) >= 4:
            try:
                x = int(float(parts[1]))
                y = int(float(parts[2]))
                z = int(float(parts[3]))
            except ValueError:
                await reply("[PyMC] 用法: setworldspawn <x> <y> <z>")
                return True
        else:
            x = int(server.spawn_position[0])
            y = int(server.spawn_position[1])
            z = int(server.spawn_position[2])
        server.spawn_position = (x, y, z)
        server.save_runtime_config()
        await reply(f"[PyMC] 世界出生点已设置为 ({x}, {y}, {z})")
        return True

    if cmd == "kick":
        if len(parts) < 2:
            await reply("[PyMC] 用法: kick <玩家> [原因]")
            return True
        target = server.find_player(parts[1])
        if target is None:
            await reply(f"[PyMC] 未找到玩家: {parts[1]}")
            return True
        reason = command.strip().split(maxsplit=2)[2] if len(parts) >= 3 else "已被管理员移出服务器"
        await target.disconnect(reason)
        await reply(f"[PyMC] 已踢出 {target.username}: {reason}")
        return True

    if cmd == "ban":
        if len(parts) < 2:
            await reply("[PyMC] 用法: ban <玩家> [原因]")
            return True
        reason = command.strip().split(maxsplit=2)[2] if len(parts) >= 3 else ""
        server.permissions.ban_player(parts[1], reason)
        target = server.find_player(parts[1])
        if target is not None:
            await target.disconnect(reason or "你已被封禁")
        await reply(f"[PyMC] 已封禁玩家: {parts[1]}")
        return True

    if cmd == "pardon":
        if len(parts) < 2:
            await reply("[PyMC] 用法: pardon <玩家>")
            return True
        server.permissions.pardon_player(parts[1])
        await reply(f"[PyMC] 已解除封禁: {parts[1]}")
        return True

    if cmd == "ban-ip":
        if len(parts) < 2:
            await reply("[PyMC] 用法: ban-ip <IP> [原因]")
            return True
        reason = command.strip().split(maxsplit=2)[2] if len(parts) >= 3 else ""
        server.permissions.ban_ip(parts[1], reason)
        for player in server.get_online_players():
            address = player.address.split(":")[0]
            if address == parts[1]:
                await player.disconnect(reason or "你的 IP 已被封禁")
        await reply(f"[PyMC] 已封禁 IP: {parts[1]}")
        return True

    if cmd == "pardon-ip":
        if len(parts) < 2:
            await reply("[PyMC] 用法: pardon-ip <IP>")
            return True
        server.permissions.pardon_ip(parts[1])
        await reply(f"[PyMC] 已解除 IP 封禁: {parts[1]}")
        return True

    if cmd == "banlist":
        banlist = server.permissions.get_banlist()
        players = ", ".join(sorted(entry["name"] for entry in banlist["players"].values())) or "无"
        ips = ", ".join(sorted(banlist["ips"].keys())) or "无"
        await reply(f"[PyMC] 玩家封禁: {players}")
        await reply(f"[PyMC] IP 封禁: {ips}")
        return True

    if cmd == "op":
        if len(parts) < 2:
            await reply("[PyMC] 用法: op <玩家>")
            return True
        server.permissions.op(parts[1])
        server.permissions.set_user_group(parts[1], "admin")
        await reply(f"[PyMC] 已授予 OP: {parts[1]}")
        return True

    if cmd == "deop":
        if len(parts) < 2:
            await reply("[PyMC] 用法: deop <玩家>")
            return True
        server.permissions.deop(parts[1])
        server.permissions.set_user_group(parts[1], "default")
        await reply(f"[PyMC] 已移除 OP: {parts[1]}")
        return True

    if cmd == "whitelist":
        if len(parts) < 2:
            whitelist = server.permissions.get_whitelist()
            status = "开启" if whitelist["enabled"] else "关闭"
            players = ", ".join(whitelist["players"]) or "无"
            await reply(f"[PyMC] 白名单状态: {status}")
            await reply(f"[PyMC] 白名单玩家: {players}")
            return True
        action = parts[1].lower()
        if action == "on":
            server.permissions.set_whitelist_enabled(True)
            await reply("[PyMC] 白名单已开启")
            return True
        if action == "off":
            server.permissions.set_whitelist_enabled(False)
            await reply("[PyMC] 白名单已关闭")
            return True
        if action == "list":
            whitelist = server.permissions.get_whitelist()
            players = ", ".join(whitelist["players"]) or "无"
            await reply(f"[PyMC] 白名单玩家: {players}")
            return True
        if action == "add" and len(parts) >= 3:
            server.permissions.add_whitelist(parts[2])
            await reply(f"[PyMC] 已加入白名单: {parts[2]}")
            return True
        if action == "remove" and len(parts) >= 3:
            server.permissions.remove_whitelist(parts[2])
            await reply(f"[PyMC] 已移除白名单: {parts[2]}")
            return True
        if action == "reload":
            server.permissions.load()
            await reply("[PyMC] 白名单与权限文件已重载")
            return True
        await reply("[PyMC] 用法: whitelist <on|off|list|add|remove|reload>")
        return True

    if cmd == "reload":
        server.permissions.load()
        await reply("[PyMC] 已重载权限与白名单配置")
        return True

    if cmd == "save-all":
        server.world_storage.flush()
        await reply("[PyMC] 世界数据已保存")
        return True

    if cmd in {"save-on", "save-off"}:
        server.autosave_enabled = (cmd == "save-on")
        await reply(f"[PyMC] 自动保存已{'开启' if server.autosave_enabled else '关闭'}")
        return True

    if cmd == "save-status":
        await reply(f"[PyMC] 自动保存状态: {'开启' if server.autosave_enabled else '关闭'}")
        return True

    if cmd == "group":
        if len(parts) == 1:
            groups = ", ".join(sorted(server.permissions.list_groups().keys()))
            await reply(f"[PyMC] 权限组: {groups}")
            return True
        if len(parts) >= 3:
            server.permissions.set_user_group(parts[1], parts[2])
            await reply(f"[PyMC] 已将 {parts[1]} 设置为权限组 {parts[2]}")
            return True
        await reply("[PyMC] 用法: group <玩家> <组名>")
        return True

    if cmd == "perm":
        if len(parts) < 2:
            await reply("[PyMC] 用法: perm <玩家>")
            return True
        level = server.permissions.get_permission_level(parts[1])
        await reply(f"[PyMC] {parts[1]} 的权限组: {level}")
        return True

    if cmd == "stop":
        if source_conn is not None:
            await send_system_message(source_conn, "[PyMC] 正在关闭服务器...")
        server.broadcast_system_message("[PyMC] 服务器正在关闭...")
        logger.info(f"{source_name} 执行了关闭服务器命令")
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(server.stop()))
        return True

    if cmd in RECOGNIZED_BUT_UNSUPPORTED or original_cmd in RECOGNIZED_BUT_UNSUPPORTED:
        await reply(f"[PyMC] 已识别原版指令 /{original_cmd}，但当前 PyMC 尚未实现其所需游戏系统")
        return True

    await reply(f"[PyMC] 未知命令: {parts[0]}")
    return False


def _handle_keepalive(conn: Connection, payload: bytes):
    """处理 Keep Alive (0x18) 响应。"""
    if len(payload) >= 8:
        keepalive_id = struct.unpack('>q', payload[:8])[0]
        logger.debug(f"{conn.username} KeepAlive 响应: {keepalive_id}")


async def _handle_player_position(conn: Connection, payload: bytes, server):
    """处理 Player Position (0x1A)。"""
    offset = 0
    x, offset = read_double(payload, offset)
    y, offset = read_double(payload, offset)
    z, offset = read_double(payload, offset)
    on_ground, offset = read_boolean(payload, offset)

    await _update_player_motion_state(conn, y, on_ground, server)
    conn.x = x
    conn.y = y
    conn.z = z
    conn.on_ground = on_ground


async def _handle_player_position_rotation(conn: Connection, payload: bytes,
                                            server):
    """处理 Player Position and Rotation (0x1B)。"""
    offset = 0
    x, offset = read_double(payload, offset)
    y, offset = read_double(payload, offset)
    z, offset = read_double(payload, offset)
    yaw, offset = read_float(payload, offset)
    pitch, offset = read_float(payload, offset)
    on_ground, offset = read_boolean(payload, offset)

    await _update_player_motion_state(conn, y, on_ground, server)
    conn.x = x
    conn.y = y
    conn.z = z
    conn.yaw = yaw
    conn.pitch = pitch
    conn.on_ground = on_ground


async def _handle_player_rotation(conn: Connection, payload: bytes, server):
    """处理 Player Rotation (0x1C)。"""
    offset = 0
    yaw, offset = read_float(payload, offset)
    pitch, offset = read_float(payload, offset)
    on_ground, offset = read_boolean(payload, offset)

    await _update_player_motion_state(conn, conn.y, on_ground, server)
    conn.yaw = yaw
    conn.pitch = pitch
    conn.on_ground = on_ground


def _handle_player_on_ground(conn: Connection, payload: bytes):
    """处理 Player On Ground (0x1D)。"""
    if payload:
        conn.on_ground = payload[0] != 0
