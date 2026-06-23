# ============================================================
# PyMC - 玩家加入游戏流程
# 处理 Login (Join Game) 数据包及相关初始化
# ============================================================

"""
玩家加入游戏流程。

包括:
  - send_join_game: 主入口，发送所有初始化数据包
  - _send_login_play: Login (Join Game) 数据包 (0x2B)
  - _send_spawn_position: 出生点位置 (0x56)
  - _send_game_event: 游戏事件 (0x22)
  - _send_center_chunk: 区块中心 (0x54)
  - _send_synchronize_position: 位置同步 (0x40)
  - _send_update_health: 生命值同步 (0x5D)
  - _send_set_experience: 经验同步 (0x5C)
  - _send_time_update: 时间同步 (0x64)
  - _broadcast_player_join: 广播玩家加入
  - 伤害处理: _damage_player, _update_player_motion_state
  - 环境伤害: _tick_damage_effects
"""

import logging
import struct
import time
import asyncio
import math

from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double, write_short,
    write_uuid, write_identifier, write_position, write_angle,
)
from protocol.nbt import encode_nbt, NbtLongArray
from network.connection import Connection
from world.blocks import (
    AIR, WATER, LAVA, GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL,
    MOSS_BLOCK, SAND, RED_SAND, GRAVEL, SNOW_BLOCK, CLAY, STONE,
    FIRE, SOUL_FIRE, CACTUS, WATER_CAULDRON, LAVA_CAULDRON,
    MAGMA_BLOCK, CAMPFIRE, SOUL_CAMPFIRE, SWEET_BERRY_BUSH,
    POWDER_SNOW, POWDER_SNOW_CAULDRON, SNOW,
    SHORT_GRASS, TALL_GRASS, FERN, LARGE_FERN, DEAD_BUSH,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT, SUGAR_CANE, BAMBOO,
)
from world.editing import get_world_block

from handlers.play.chunks import (
    _sorted_chunk_coords, _send_chunk_batch, _send_deferred_chunks,
)
from handlers.play.spawn import (
    _resolve_initial_player_location, _resolve_player_respawn_location,
    _is_suffocating_block, PASSABLE_BLOCKS,
)
from handlers.play.entities import (
    _send_visible_entities_to_player, _entity_within_tracking_range,
    _send_experience_orb_spawn, _send_generic_entity_spawn,
    broadcast_entity_spawn, broadcast_entity_remove,
)
from handlers.play.chat import (
    build_system_message_payload, send_system_message,
    build_player_info_update, build_player_info_remove,
)

logger = logging.getLogger("PyMC.游戏")


async def send_join_game(conn: Connection, server):
    """
    发送 Login (Join Game) 数据包及相关初始化数据包。
    这是玩家进入 Play 阶段后收到的第一个数据包。
    使用版本处理器来发送正确的格式。
    """
    logger.info(f"正在发送游戏数据给 {conn.username} (版本 {conn.mc_version}, 协议 {conn.protocol_version})...")
    load_start = time.time()
    server._initialize_terrain_generator()

    terrain = server.terrain_generator
    use_native = getattr(server, '_use_native_terrain', False)

    # --- 1. Login (Join Game) 数据包 ---
    # Use version handler for version-specific Join Game format
    if conn.version_handler is not None:
        await conn.version_handler.send_join_game(conn, server)
    else:
        await _send_login_play(conn, server)

    # --- 2. 发送游戏事件: 等待区块 ---
    if conn.version_handler is not None:
        await conn.version_handler.send_game_event(conn, 13, 0.0)
    else:
        await _send_game_event(conn, 13, 0.0)

    # --- 3. 设置区块中心 ---
    center_cx = int(server.spawn_position[0]) >> 4
    center_cz = int(server.spawn_position[2]) >> 4
    conn.chunk_center = (center_cx, center_cz)
    if conn.version_handler is not None:
        await conn.version_handler.send_set_center_chunk(conn, center_cx, center_cz)
        await conn.version_handler.send_set_chunk_cache_radius(conn, server.view_distance)
    else:
        await _send_center_chunk(conn, center_cx, center_cz)
        await conn.send_packet(0x55, write_varint(server.view_distance))

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
    conn.loaded_chunks.update((cx, cz) for cx, cz, *_ in immediate_results)

    # Scan loaded chunks for redstone components
    if server.redstone_engine:
        for cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks in immediate_results:
            server.redstone_engine.scan_chunk(cx, cz, chunk_blocks)

    # --- 5. 恢复玩家存档位置，必要时回退到安全出生点 ---
    player_state = server.world_storage.load_player_data(str(conn.uuid))
    target_x, target_y, target_z = _resolve_initial_player_location(
        server, player_state
    )
    await _send_spawn_position(conn, *server.spawn_position)

    # --- 6. 同步玩家位置 ---
    conn.x = float(target_x) + 0.5
    conn.y = float(target_y)
    conn.z = float(target_z) + 0.5
    if player_state:
        conn.yaw = float(player_state.get("yaw", conn.yaw))
        conn.pitch = float(player_state.get("pitch", conn.pitch))
        conn.health = float(player_state.get("health", conn.health))
        conn.food = int(player_state.get("food", conn.food))
        conn.saturation = float(player_state.get("saturation", conn.saturation))
        conn.experience_total = int(player_state.get("experience_total", conn.experience_total))
        conn.experience_level = int(player_state.get("experience_level", conn.experience_level))
        conn.experience_progress = float(player_state.get("experience_progress", conn.experience_progress))
        conn.gamemode = str(player_state.get("gamemode", server.config.get("gamemode", "creative")))
        conn.on_ground = bool(player_state.get("on_ground", True))
        conn.air_supply = int(player_state.get("air_supply", 300))
        conn.fire_ticks = int(player_state.get("fire_ticks", 0))
        conn.freeze_ticks = int(player_state.get("freeze_ticks", 0))
        personal_spawn = player_state.get("personal_spawn")
        if (
            isinstance(personal_spawn, (list, tuple))
            and len(personal_spawn) == 3
        ):
            try:
                conn.personal_spawn = (
                    int(personal_spawn[0]),
                    int(personal_spawn[1]),
                    int(personal_spawn[2]),
                )
            except (TypeError, ValueError):
                conn.personal_spawn = None
        else:
            conn.personal_spawn = None
    else:
        conn.gamemode = server.config.get("gamemode", "creative")
        conn.personal_spawn = None
    conn.fall_start_y = conn.y

    # Use version handler for version-specific position/health/experience/time sync
    if conn.version_handler is not None:
        await conn.version_handler.send_synchronize_position(conn)
        await conn.version_handler.send_update_health(conn)
        await conn.version_handler.send_set_experience(conn)
        await conn.version_handler.send_update_time(conn, server.world_time)
    else:
        await _send_synchronize_position(conn)
        await _send_update_health(conn)
        await _send_set_experience(conn)
        await _send_time_update(conn, server)

    # --- 7. 通知其他玩家 ---
    await _broadcast_player_join(conn, server)
    await _send_visible_entities_to_player(conn, server)

    # Plugin hook: fire PlayerJoinEvent
    from plugins.bridge import hook_player_join
    hook_player_join(server, conn)

    load_elapsed = time.time() - load_start
    logger.info(f"加载完成，用时 {load_elapsed:.1f}s")
    logger.info(
        f"玩家 {conn.username} 已成功加入游戏 "
        f"(位置: {int(conn.x)}, {int(conn.y)}, {int(conn.z)})"
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


async def _send_synchronize_position(conn: Connection):
    """发送 Synchronize Player Position 数据包。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_synchronize_position(conn)
        return

    # Native 1.21.1 format
    payload = bytearray()
    payload.extend(write_double(conn.x))    # X
    payload.extend(write_double(conn.y))    # Y
    payload.extend(write_double(conn.z))    # Z
    payload.extend(write_double(0.0))       # Delta X
    payload.extend(write_double(0.0))       # Delta Y
    payload.extend(write_double(0.0))       # Delta Z
    payload.extend(write_float(conn.yaw))   # Yaw
    payload.extend(write_float(conn.pitch)) # Pitch
    payload.extend(write_varint(0))         # Flags
    conn.teleport_id = (conn.teleport_id + 1) & 0x7FFFFFFF
    payload.extend(write_varint(conn.teleport_id))  # Teleport ID
    await conn.send_packet(0x40, bytes(payload))


async def _send_update_health(conn: Connection):
    """发送基础生命值同步。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_update_health(conn)
        return

    payload = bytearray()
    payload.extend(write_float(float(conn.health)))
    payload.extend(write_varint(int(conn.food)))
    payload.extend(write_float(float(conn.saturation)))
    await conn.send_packet(0x5D, bytes(payload))


async def _send_set_experience(conn: Connection):
    """同步玩家经验条、等级与总经验。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_set_experience(conn)
        return

    payload = bytearray()
    payload.extend(write_float(max(0.0, min(1.0, float(conn.experience_progress)))))
    payload.extend(write_varint(max(0, int(conn.experience_level))))
    payload.extend(write_varint(max(0, int(conn.experience_total))))
    await conn.send_packet(0x5C, bytes(payload))


def _experience_needed_for_next_level(level: int) -> int:
    if level >= 30:
        return 112 + (level - 30) * 9
    if level >= 15:
        return 37 + (level - 15) * 5
    return 7 + level * 2


async def _add_player_experience(conn: Connection, amount: int):
    """增加玩家经验，并按原版等级曲线更新经验条。"""
    remaining = max(0, int(amount))
    conn.experience_total = max(0, int(conn.experience_total)) + remaining
    while remaining > 0:
        needed = _experience_needed_for_next_level(conn.experience_level)
        current_points = int(conn.experience_progress * needed)
        take = min(remaining, needed - current_points)
        current_points += take
        remaining -= take
        if current_points >= needed:
            conn.experience_level += 1
            conn.experience_progress = 0.0
        else:
            conn.experience_progress = current_points / max(1, needed)
    await _send_set_experience(conn)


async def _send_collect_entity(
    conn: Connection,
    collected_entity_id: int,
    collector_entity_id: int,
    count: int = 1,
):
    """播放实体被拾取的客户端动画。"""
    payload = bytearray()
    payload.extend(write_varint(int(collected_entity_id)))
    payload.extend(write_varint(int(collector_entity_id)))
    payload.extend(write_varint(max(1, int(count))))
    await conn.send_packet(0x6F, bytes(payload))


async def _send_time_update(conn: Connection, server):
    """发送世界时间。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_update_time(conn, server.world_time)
        return

    payload = bytearray()
    payload.extend(write_long(int(server.world_time)))
    payload.extend(write_long(int(server.world_time)))
    await conn.send_packet(0x64, bytes(payload))


async def _damage_player(conn: Connection, amount: float, reason: str, server):
    """对玩家造成基础伤害。死亡时回到出生点。"""
    if not conn.alive or conn.gamemode in {"creative", "spectator"}:
        return
    if conn.damage_cooldown_ticks > 0 and conn.last_damage_reason == reason:
        return

    conn.health = max(0.0, conn.health - amount)
    conn.damage_cooldown_ticks = 10
    conn.last_damage_reason = reason
    await _send_update_health(conn)

    if conn.health > 0:
        await send_system_message(conn, f"[PyMC] 你受到了 {amount:.1f} 点{reason}伤害")
        return

    await send_system_message(conn, "[PyMC] 你死亡了，已返回出生点")
    respawn_x, respawn_y, respawn_z = _resolve_player_respawn_location(conn, server)
    conn.x = float(respawn_x) + 0.5
    conn.y = float(respawn_y)
    conn.z = float(respawn_z) + 0.5
    conn.fall_start_y = conn.y
    conn.health = 20.0
    conn.food = 20
    conn.saturation = 5.0
    conn.air_supply = 300
    conn.fire_ticks = 0
    conn.freeze_ticks = 0
    conn.damage_cooldown_ticks = 0
    conn.last_damage_reason = ""
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


def _player_block_position(conn: Connection) -> tuple[int, int, int]:
    """将玩家坐标转换为脚部所在方块坐标。"""
    return math.floor(conn.x), math.floor(conn.y), math.floor(conn.z)


def _get_block_at(server, world_x: int, world_y: int, world_z: int) -> int | None:
    """读取世界坐标处的方块 ID。"""
    return get_world_block(server, int(world_x), int(world_y), int(world_z))


async def _tick_damage_effects(conn: Connection, server, tick_count: int):
    """结算基础环境伤害与简化生存回复。"""
    if not conn.alive or conn.gamemode in {"creative", "spectator"}:
        conn.air_supply = 300
        conn.fire_ticks = 0
        conn.freeze_ticks = 0
        conn.damage_cooldown_ticks = 0
        conn.last_damage_reason = ""
        return

    if conn.damage_cooldown_ticks > 0:
        conn.damage_cooldown_ticks -= 1
        if conn.damage_cooldown_ticks == 0:
            conn.last_damage_reason = ""

    block_x, block_y, block_z = _player_block_position(conn)
    foot_block = _get_block_at(server, block_x, block_y, block_z)
    head_block = _get_block_at(server, block_x, block_y + 1, block_z)
    below_block = _get_block_at(server, block_x, block_y - 1, block_z)

    side_blocks = {
        _get_block_at(server, block_x + 1, block_y, block_z),
        _get_block_at(server, block_x - 1, block_y, block_z),
        _get_block_at(server, block_x, block_y, block_z + 1),
        _get_block_at(server, block_x, block_y, block_z - 1),
        _get_block_at(server, block_x + 1, block_y + 1, block_z),
        _get_block_at(server, block_x - 1, block_y + 1, block_z),
        _get_block_at(server, block_x, block_y + 1, block_z + 1),
        _get_block_at(server, block_x, block_y + 1, block_z - 1),
    }

    if _is_suffocating_block(foot_block) or _is_suffocating_block(head_block):
        await _damage_player(conn, 1.0, "窒息", server)

    if head_block in {WATER, WATER_CAULDRON}:
        conn.air_supply = max(0, conn.air_supply - 1)
        if conn.air_supply == 0 and tick_count % 20 == 0:
            await _damage_player(conn, 2.0, "溺水", server)
    else:
        conn.air_supply = min(300, conn.air_supply + 5)

    in_lava = foot_block in {LAVA, LAVA_CAULDRON} or head_block in {LAVA, LAVA_CAULDRON}
    in_fire = foot_block in {FIRE, SOUL_FIRE} or head_block in {FIRE, SOUL_FIRE}
    on_hot_floor = conn.on_ground and below_block in {MAGMA_BLOCK, CAMPFIRE, SOUL_CAMPFIRE}
    touching_cactus = CACTUS in side_blocks or foot_block == CACTUS or head_block == CACTUS
    touching_berry = SWEET_BERRY_BUSH in side_blocks or foot_block == SWEET_BERRY_BUSH or head_block == SWEET_BERRY_BUSH
    in_powder_snow = foot_block in {POWDER_SNOW, POWDER_SNOW_CAULDRON} or head_block in {POWDER_SNOW, POWDER_SNOW_CAULDRON}

    if in_lava:
        conn.fire_ticks = max(conn.fire_ticks, 200)
        if tick_count % 10 == 0:
            await _damage_player(conn, 4.0, "岩浆", server)
    elif in_fire:
        conn.fire_ticks = max(conn.fire_ticks, 160)
        if tick_count % 10 == 0:
            await _damage_player(conn, 1.0, "火焰", server)
    elif on_hot_floor and tick_count % 20 == 0:
        await _damage_player(conn, 1.0, "高温地面", server)

    if touching_cactus and tick_count % 10 == 0:
        await _damage_player(conn, 1.0, "仙人掌", server)

    if touching_berry and tick_count % 10 == 0:
        await _damage_player(conn, 1.0, "甜浆果丛", server)

    if conn.fire_ticks > 0:
        conn.fire_ticks = max(0, conn.fire_ticks - 1)
        if tick_count % 20 == 0:
            await _damage_player(conn, 1.0, "燃烧", server)

    if in_powder_snow:
        conn.freeze_ticks = min(140, conn.freeze_ticks + 1)
        if conn.freeze_ticks >= 140 and tick_count % 40 == 0:
            await _damage_player(conn, 1.0, "冰冻", server)
    else:
        conn.freeze_ticks = max(0, conn.freeze_ticks - 4)

    if conn.food <= 0:
        if tick_count % 80 == 0 and conn.health > 1.0:
            await _damage_player(conn, 1.0, "饥饿", server)
    elif (
        server.gamerules.get("naturalRegeneration", True)
        and conn.health < 20.0
        and conn.food >= 18
        and tick_count % 80 == 0
    ):
        conn.health = min(20.0, conn.health + 1.0)
        await _send_update_health(conn)


async def _broadcast_player_join(conn: Connection, server):
    """向所有在线玩家广播新玩家加入。"""
    from protocol.packet_map import get_clientbound_packet

    # 发送新玩家的信息给所有人 (包括自己)
    player_info = build_player_info_update(conn)
    for other in server.get_online_players():
        pid = get_clientbound_packet(other.protocol_version, "player_info")
        if pid is not None:
            await other.send_packet(pid, player_info)

    # 发送所有已有玩家的信息给新玩家
    for other in server.get_online_players():
        if other != conn:
            other_info = build_player_info_update(other)
            pid = get_clientbound_packet(conn.protocol_version, "player_info")
            if pid is not None:
                await conn.send_packet(pid, other_info)
