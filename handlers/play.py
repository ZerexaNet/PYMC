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
import json
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
from world.terrain_native import NativeTerrainGenerator
from world.chunk_io import serialize_chunk, deserialize_chunk

logger = logging.getLogger("PyMC.游戏")


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

    # 初始化地形生成器 (如果还没有)
    if not hasattr(server, 'terrain_generator'):
        seed = server.config.get("level-seed", 0)
        if isinstance(seed, str):
            try:
                seed = int(seed)
            except ValueError:
                seed = hash(seed)

        # 优先使用 C++ 原生生成器
        native_gen = NativeTerrainGenerator(seed)
        if native_gen.available:
            server.terrain_generator = native_gen
            server._use_native_terrain = True
            logger.info(f"使用 C++ 原生地形生成器 (种子: {seed})")
        else:
            server.terrain_generator = TerrainGenerator(seed)
            server._use_native_terrain = False
            logger.info(f"使用纯 Python 地形生成器 (种子: {seed})")

    terrain = server.terrain_generator
    use_native = getattr(server, '_use_native_terrain', False)

    # --- 1. Login (Join Game) 数据包 ---
    await _send_login_play(conn, server)

    # --- 2. 计算出生点高度 ---
    if use_native:
        # 原生生成器: 通过生成 (0,0) 区块获取高度
        _, hmap = terrain.generate_chunk_with_heightmap(0, 0)
        spawn_height = hmap[0][0] + 2
    else:
        spawn_height = terrain.get_terrain_height(0, 0) + 2
    await _send_spawn_position(conn, spawn_height)

    # --- 3. 发送游戏事件: 等待区块 ---
    await _send_game_event(conn, 13, 0.0)  # 事件13: Start waiting for chunks

    # --- 4. 设置区块中心 ---
    await _send_center_chunk(conn, 0, 0)

    # --- 5. 发送区块数据 (使用 Chunk Batch 协议) ---
    # 发送 Chunk Batch Start (0x0D)
    await conn.send_packet(0x0D, b'')

    view_distance = server.view_distance
    chunk_coords = [(cx, cz)
                    for cx in range(-view_distance, view_distance + 1)
                    for cz in range(-view_distance, view_distance + 1)]

    # 在线程池中预生成所有区块数据 (避免阻塞事件循环)
    loop = asyncio.get_event_loop()
    logger.info(f"正在生成 {len(chunk_coords)} 个区块 (视距={view_distance}, "
                f"引擎={'C++' if use_native else 'Python'})...")
    gen_start = time.time()

    storage = server.world_storage

    def _generate_all_chunks():
        """在工作线程中批量生成区块数据 (优先从存档加载)。"""
        results = []
        loaded = 0
        generated = 0
        for cx, cz in chunk_coords:
            # 先尝试从存档加载
            saved = storage.load_chunk(cx, cz)
            if saved is not None:
                chunk_blocks = deserialize_chunk(saved)
                if chunk_blocks is not None:
                    loaded += 1
                    motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
                    world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
                    chunk_data = build_chunk_column_from_terrain(chunk_blocks)
                    results.append((cx, cz, motion_blocking, world_surface, chunk_data))
                    continue

            # 存档中没有，使用生成器生成
            if use_native:
                chunk_blocks, _ = terrain.generate_chunk_with_heightmap(cx, cz)
            else:
                chunk_blocks = terrain.generate_chunk(cx, cz)

            motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
            world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
            chunk_data = build_chunk_column_from_terrain(chunk_blocks)
            results.append((cx, cz, motion_blocking, world_surface, chunk_data))

            # 保存到存档
            storage.save_chunk(cx, cz, serialize_chunk(chunk_blocks))
            generated += 1

        if loaded > 0:
            logger.info(f"从存档加载 {loaded} 个区块")
        if generated > 0:
            logger.info(f"新生成 {generated} 个区块")
            # 批量写入磁盘
            storage.flush()

        return results

    chunk_results = await loop.run_in_executor(None, _generate_all_chunks)
    gen_elapsed = time.time() - gen_start
    logger.info(f"区块生成完成: {len(chunk_results)} 个, 耗时 {gen_elapsed:.1f}s")

    # 依次发送预生成的区块
    for cx, cz, motion_blocking, world_surface, chunk_data in chunk_results:
        await _send_prebuilt_chunk(conn, cx, cz, motion_blocking, world_surface, chunk_data)

    # 发送 Chunk Batch Finished (0x0C)
    await conn.send_packet(0x0C, write_varint(len(chunk_results)))

    # --- 6. 同步玩家位置 ---
    conn.x = 0.5
    conn.y = float(spawn_height)
    conn.z = 0.5
    await _send_synchronize_position(conn)

    # --- 7. 通知其他玩家 ---
    await _broadcast_player_join(conn, server)

    load_elapsed = time.time() - load_start
    logger.info(f"加载完成，用时 {load_elapsed:.1f}s")
    logger.info(f"玩家 {conn.username} 已成功加入游戏 (出生高度: {spawn_height})")


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
    payload.extend(write_ubyte(1))  # 创造模式

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


async def _send_spawn_position(conn: Connection, y: int):
    """发送 Set Default Spawn Position 数据包 (0x56)。"""
    payload = bytearray()
    payload.extend(write_position(0, y, 0))  # 出生点位置
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


async def _send_prebuilt_chunk(conn: Connection, chunk_x: int, chunk_z: int,
                                motion_blocking: list[int], world_surface: list[int], 
                                chunk_data: bytes):
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
    all_bits = (1 << 26) - 1
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(1))
    payload.extend(write_long(all_bits))
    payload.extend(write_varint(0))
    payload.extend(write_varint(0))

    # Sky Light (全亮)
    sky_light_section = bytes([0xFF] * 2048)
    light_section_count = 26
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(sky_light_section)

    # Block Light (全黑)
    block_light_section = bytes([0x00] * 2048)
    payload.extend(write_varint(light_section_count))
    for _ in range(light_section_count):
        payload.extend(write_varint(2048))
        payload.extend(block_light_section)

    await conn.send_packet(0x27, bytes(payload))


async def _send_synchronize_position(conn: Connection):
    """发送 Synchronize Player Position 数据包 (0x40)。"""
    payload = bytearray()
    payload.extend(write_varint(0))        # Teleport ID
    payload.extend(write_double(conn.x))    # X
    payload.extend(write_double(conn.y))    # Y
    payload.extend(write_double(conn.z))    # Z
    payload.extend(write_double(0.0))       # Velocity X
    payload.extend(write_double(0.0))       # Velocity Y
    payload.extend(write_double(0.0))       # Velocity Z
    payload.extend(write_float(conn.yaw))   # Yaw
    payload.extend(write_float(conn.pitch)) # Pitch
    payload.extend(write_int(0))            # Flags (都是绝对值)
    await conn.send_packet(0x40, bytes(payload))


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

    # 构建系统聊天消息并广播
    chat_json = json.dumps({
        "translate": "chat.type.text",
        "with": [
            {"text": conn.username, "color": "yellow"},
            {"text": message}
        ]
    }, ensure_ascii=False)

    chat_payload = bytearray()
    chat_payload.extend(write_string(chat_json))
    chat_payload.extend(write_boolean(False))  # overlay = false (聊天栏)

    server.broadcast_packet(0x6C, bytes(chat_payload))


async def _handle_chat_command(conn: Connection, payload: bytes, server):
    """处理 Chat Command (0x04)。"""
    offset = 0
    command, offset = read_string(payload, offset)

    logger.info(f"{conn.username} 执行命令: /{command}")

    parts = command.strip().split()
    if not parts:
        return

    cmd = parts[0].lower()

    if cmd == "help":
        await _send_system_message(conn, "[PyMC] 可用命令: /help, /list, /tp, /gamemode, /stop")

    elif cmd == "list":
        players = server.get_online_players()
        names = ", ".join(p.username for p in players)
        await _send_system_message(conn,
            f"[PyMC] 在线玩家 ({len(players)}/{server.max_players}): {names}")

    elif cmd == "tp" and len(parts) >= 4:
        try:
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])
            conn.x, conn.y, conn.z = x, y, z
            await _send_synchronize_position(conn)
            await _send_system_message(conn, f"[PyMC] 已传送到 ({x}, {y}, {z})")
        except ValueError:
            await _send_system_message(conn, "[PyMC] 用法: /tp <x> <y> <z>")

    elif cmd == "gamemode" and len(parts) >= 2:
        mode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3,
                    "0": 0, "1": 1, "2": 2, "3": 3}
        mode_name = parts[1].lower()
        if mode_name in mode_map:
            mode = mode_map[mode_name]
            # Game Event: 变更游戏模式 (事件 3)
            await _send_game_event(conn, 3, float(mode))
            mode_names = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
            await _send_system_message(conn,
                f"[PyMC] 游戏模式已切换为 {mode_names.get(mode, '未知')}")
        else:
            await _send_system_message(conn,
                "[PyMC] 用法: /gamemode <survival|creative|adventure|spectator>")

    elif cmd == "stop":
        await _send_system_message(conn, "[PyMC] 正在关闭服务器...")
        logger.info(f"{conn.username} 执行了关闭服务器命令")
        import asyncio
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(server.stop()))

    else:
        await _send_system_message(conn, f"[PyMC] 未知命令: /{cmd}")


async def _send_system_message(conn: Connection, text: str):
    """发送系统聊天消息给单个玩家。"""
    chat_json = json.dumps({"text": text, "color": "gray"}, ensure_ascii=False)
    payload = bytearray()
    payload.extend(write_string(chat_json))
    payload.extend(write_boolean(False))  # overlay
    await conn.send_packet(0x6C, bytes(payload))


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

    conn.yaw = yaw
    conn.pitch = pitch
    conn.on_ground = on_ground


def _handle_player_on_ground(conn: Connection, payload: bytes):
    """处理 Player On Ground (0x1D)。"""
    if payload:
        conn.on_ground = payload[0] != 0
