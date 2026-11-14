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


def _restore_player_state(conn: Connection, server, player_state: dict | None):
    """把存档中的玩家状态恢复到连接对象上 (在发送 Login 包之前调用)。"""
    from handlers.play.state import normalize_gamemode
    default_mode = normalize_gamemode(server.config.get("gamemode", "survival"))
    force_mode = bool(server.config.get("force-gamemode", False))

    if player_state:
        conn.yaw = float(player_state.get("yaw", conn.yaw))
        conn.pitch = float(player_state.get("pitch", conn.pitch))
        conn.health = float(player_state.get("health", conn.health))
        conn.food = int(player_state.get("food", conn.food))
        conn.saturation = float(player_state.get("saturation", conn.saturation))
        conn.experience_total = int(player_state.get("experience_total", conn.experience_total))
        conn.experience_level = int(player_state.get("experience_level", conn.experience_level))
        conn.experience_progress = float(player_state.get("experience_progress", conn.experience_progress))
        conn.gamemode = normalize_gamemode(player_state.get("gamemode"), default_mode)
        conn.on_ground = bool(player_state.get("on_ground", True))
        conn.air_supply = int(player_state.get("air_supply", 300))
        conn.fire_ticks = int(player_state.get("fire_ticks", 0))
        conn.freeze_ticks = int(player_state.get("freeze_ticks", 0))
        conn.flying = bool(player_state.get("flying", False))
        slot = int(player_state.get("selected_slot", 0))
        conn.selected_hotbar_slot = slot if 0 <= slot < 9 else 0
        personal_spawn = player_state.get("personal_spawn")
        conn.personal_spawn = None
        if isinstance(personal_spawn, (list, tuple)) and len(personal_spawn) == 3:
            try:
                conn.personal_spawn = tuple(int(v) for v in personal_spawn)
            except (TypeError, ValueError):
                conn.personal_spawn = None
        if conn.health <= 0:
            # 死亡状态下退出的玩家: 重新进入时在出生点满血复活
            conn.health, conn.food, conn.saturation = 20.0, 20, 5.0
            player_state.pop("x", None)
    else:
        conn.gamemode = default_mode
        conn.personal_spawn = None

    if force_mode:
        conn.gamemode = default_mode
    if conn.gamemode not in ("creative", "spectator"):
        conn.flying = False


async def send_join_game(conn: Connection, server):
    """
    玩家进入 Play 阶段后的完整进服流程，数据包顺序与原版服务端一致:

      Login -> Difficulty -> Abilities -> Held Slot -> Op Level -> Commands
      -> 区块中心/视距 -> 出生点区块 -> Spawn Position -> 位置同步
      -> 生命/经验/时间/天气/物品栏 -> Player Info -> 加入消息 -> 实体
    """
    load_start = time.time()
    server._initialize_terrain_generator()
    use_native = getattr(server, '_use_native_terrain', False)
    native_path = conn.protocol_version >= 767

    # --- 0. 读取玩家存档 (Login 包需要正确的游戏模式) ---
    player_state = server.world_storage.load_player_data(str(conn.uuid))
    first_join = player_state is None
    _restore_player_state(conn, server, player_state)

    from world.inventory import PlayerInventory, initialize_player_inventory
    inventory_data = player_state.get("inventory") if player_state else None
    if isinstance(inventory_data, list):
        # Compatibility with compact saves written by earlier releases.
        conn.inventory_obj = PlayerInventory()
        conn.inventory_obj.deserialize(inventory_data)
    elif isinstance(inventory_data, dict):
        conn.inventory_obj = PlayerInventory.deserialize_full(inventory_data)
    else:
        initialize_player_inventory(conn)
    conn.inventory_state_id = 0

    # --- 1. Login (Join Game) 数据包 ---
    if conn.version_handler is not None:
        await conn.version_handler.send_join_game(conn, server)
    else:
        await _send_login_play(conn, server)

    if native_path:
        from handlers.play.state import (
            send_abilities, send_difficulty, send_held_slot, send_op_level,
        )
        await send_difficulty(conn, server)
        await send_abilities(conn)
        await send_held_slot(conn)
        await send_op_level(conn, server)
        from commands.brigadier import send_commands
        await send_commands(conn, server)

    # --- 2. 解析出生位置 (存档位置不安全时回退到安全出生点) ---
    target_x, target_y, target_z = _resolve_initial_player_location(
        server, player_state
    )
    if player_state and all(k in player_state for k in ("x", "y", "z")):
        # 保留方块内的小数坐标, 仅当安全位置与存档方块一致时
        px, py, pz = (float(player_state["x"]), float(player_state["y"]),
                      float(player_state["z"]))
        if (math.floor(px), math.floor(pz)) == (int(target_x), int(target_z)) \
                and abs(py - float(target_y)) < 1.0:
            conn.x, conn.y, conn.z = px, py, pz
        else:
            conn.x, conn.y, conn.z = float(target_x) + 0.5, float(target_y), float(target_z) + 0.5
    else:
        conn.x, conn.y, conn.z = float(target_x) + 0.5, float(target_y), float(target_z) + 0.5
    conn.fall_start_y = conn.y

    # --- 3. 等待区块 + 区块中心 ---
    if conn.version_handler is not None:
        await conn.version_handler.send_game_event(conn, 13, 0.0)
    else:
        await _send_game_event(conn, 13, 0.0)

    center_cx = math.floor(conn.x) >> 4
    center_cz = math.floor(conn.z) >> 4
    conn.chunk_center = (center_cx, center_cz)
    view_distance = effective_view_distance(conn, server)
    if conn.version_handler is not None:
        await conn.version_handler.send_set_center_chunk(conn, center_cx, center_cz)
    else:
        await _send_center_chunk(conn, center_cx, center_cz)

    chunk_coords = _sorted_chunk_coords(center_cx, center_cz, view_distance)
    immediate_radius = min(server.join_immediate_radius, view_distance)
    immediate_count = (immediate_radius * 2 + 1) ** 2
    immediate_coords = chunk_coords[:immediate_count]
    deferred_coords = chunk_coords[immediate_count:]

    # 在线程池中准备区块数据 (避免阻塞事件循环)
    loop = asyncio.get_event_loop()
    logger.debug(f"正在为 {conn.username} 准备 {len(chunk_coords)} 个区块 (视距={view_distance}, "
                 f"引擎={'C++' if use_native else 'Python'})...")

    def _generate_chunks(coords):
        return server.generate_chunk_results(coords)[0]

    immediate_results = await loop.run_in_executor(None, _generate_chunks, immediate_coords)
    await _send_chunk_batch(conn, immediate_results)
    conn.loaded_chunks.update((cx, cz) for cx, cz, *_ in immediate_results)

    # Scan loaded chunks for redstone components
    if server.redstone_engine:
        for cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks in immediate_results:
            server.redstone_engine.scan_chunk(cx, cz, chunk_blocks)

    # --- 4. 出生点 + 位置同步 ---
    await _send_spawn_position(conn, *server.spawn_position)

    if conn.version_handler is not None:
        await conn.version_handler.send_synchronize_position(conn)
        await conn.version_handler.send_update_health(conn)
        await conn.version_handler.send_set_experience(conn)
    else:
        await _send_synchronize_position(conn)
        await _send_update_health(conn)
        await _send_set_experience(conn)
    await _send_time_update(conn, server)

    # 同步当前天气状态 (晴天时为空操作)
    from handlers.play.weather import send_weather_state
    await send_weather_state(conn, server)

    from world.inventory import send_inventory_sync
    await send_inventory_sync(conn)

    if native_path:
        from handlers.play.state import send_ticking_state
        await send_ticking_state(conn)

    # --- 5. Tab 列表页眉/页脚 (可选, 由 server.properties 配置) ---
    await send_tab_header_footer(conn, server)

    # --- 6. 通知其他玩家 + 加入消息 ---
    conn.joined = True
    conn.last_active = time.monotonic()
    await _broadcast_player_join(conn, server)
    await _send_visible_entities_to_player(conn, server)

    from protocol.text import translate, player_name
    logging.getLogger("minecraft.server").info(
        f"{conn.username}[/{conn.address}] logged in with entity id {conn.entity_id} "
        f"at ({conn.x:.1f}, {conn.y:.1f}, {conn.z:.1f})"
    )
    server.broadcast_system_message(
        translate("multiplayer.player.joined", player_name(conn), color="yellow"),
        log=True,
    )
    usercache = getattr(server, "usercache", None)
    if usercache is not None:
        usercache.record(conn.username, conn.uuid)

    # Plugin hook: fire PlayerJoinEvent
    from mods.bridge import hook_player_join
    hook_player_join(server, conn)

    logger.debug(f"{conn.username} 进服流程完成, 用时 {time.time() - load_start:.2f}s"
                 f"{' (首次进入)' if first_join else ''}")

    if deferred_coords:
        asyncio.create_task(_send_deferred_chunks(
            conn, server, deferred_coords, len(chunk_coords)
        ))


def effective_view_distance(conn: Connection, server) -> int:
    """服务端视距与客户端请求视距取较小值 (原版行为)。"""
    view_distance = int(server.view_distance)
    client = int(getattr(conn, "client_view_distance", 0) or 0)
    if client >= 2:
        view_distance = min(view_distance, client)
    return max(2, view_distance)


async def send_tab_header_footer(conn: Connection, server):
    """发送 Tab 列表页眉/页脚; 未配置时不发送 (原版默认没有)。"""
    header = str(server.config.get("tab-list-header", "") or "")
    footer = str(server.config.get("tab-list-footer", "") or "")
    if not header and not footer:
        return
    from protocol.packet_map import get_clientbound_packet
    from protocol.text import encode_component
    tab_pid = get_clientbound_packet(conn.protocol_version, "playerlist_header")
    if tab_pid is None:
        return
    payload = (encode_component(header, conn.protocol_version)
               + encode_component(footer, conn.protocol_version))
    await conn.send_packet(tab_pid, payload)


def hashed_seed(server) -> int:
    """SHA-256(seed) 的前 8 字节 (客户端用于生物群系噪声), 与原版一致。"""
    import hashlib
    from network.server import parse_vanilla_seed
    seed = parse_vanilla_seed(server.config.get("level-seed", 0))
    digest = hashlib.sha256(struct.pack(">q", seed)).digest()
    return struct.unpack(">q", digest[:8])[0]


async def _send_login_play(conn: Connection, server):
    """
    发送 Login (Join Game) 数据包 (0x2B)。
    这是一个包含大量字段的复杂数据包。
    """
    payload = bytearray()

    # Entity ID (Int)
    payload.extend(write_int(conn.entity_id))

    # Is Hardcore (Boolean)
    payload.extend(write_boolean(bool(server.config.get("hardcore", False))))

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
    payload.extend(write_varint(int(getattr(server, "simulation_distance", server.view_distance))))

    # Reduced Debug Info (Boolean)
    payload.extend(write_boolean(bool(server.gamerules.get("reducedDebugInfo", False))))

    # Enable Respawn Screen (Boolean)
    payload.extend(write_boolean(not server.gamerules.get("doImmediateRespawn", False)))

    # Do Limited Crafting (Boolean)
    payload.extend(write_boolean(bool(server.gamerules.get("doLimitedCrafting", False))))

    # Dimension Type (VarInt - 注册表索引)
    payload.extend(write_varint(0))  # 0 = overworld

    # Dimension Name (Identifier)
    payload.extend(write_identifier("minecraft:overworld"))

    # Hashed Seed (Long)
    payload.extend(write_long(hashed_seed(server)))

    # Game Mode (Unsigned Byte) - 0=生存, 1=创造, 2=冒险, 3=旁观
    gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
    payload.extend(write_ubyte(gamemode_map.get(conn.gamemode, 0)))

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
    """发送 Synchronize Player Position 数据包 (1.21.1 native 格式)。

    1.21.1 (protocol 767) 格式:
      Double  X
      Double  Y
      Double  Z
      Float   Yaw
      Float   Pitch
      Byte    Flags       (signed 8-bit, NOT VarInt)
      VarInt  Teleport ID

    1.21+ 没有 Delta X/Y/Z 字段 (它们在 1.20 被移除)。
    """
    if conn.version_handler is not None:
        await conn.version_handler.send_synchronize_position(conn)
        return

    # Native 1.21.1 format — NO delta coordinates, Flags is Byte
    payload = bytearray()
    payload.extend(write_double(conn.x))    # X
    payload.extend(write_double(conn.y))    # Y
    payload.extend(write_double(conn.z))    # Z
    payload.extend(write_float(conn.yaw))  # Yaw
    payload.extend(write_float(conn.pitch)) # Pitch
    payload.extend(write_byte(0))           # Flags (Byte, not VarInt)
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


def world_time_fields(server) -> tuple[int, int]:
    """
    (世界总刻数, 昼夜时间) —— Update Time 数据包的两个字段。
    doDaylightCycle=false 时昼夜时间取负值, 客户端据此停止本地推进太阳。
    """
    manager = getattr(server, "_time_manager", None)
    if manager is None:
        value = int(getattr(server, "world_time", 0))
        return value, value
    day_time = int(manager.day_time_total)
    if not server.gamerules.get("doDaylightCycle", True):
        day_time = -day_time if day_time > 0 else -1
    return int(manager.age), day_time


async def _send_time_update(conn: Connection, server):
    """发送世界时间。"""
    age, day_time = world_time_fields(server)
    if conn.version_handler is not None:
        await conn.version_handler.send_update_time(conn, age, day_time)
        return

    payload = bytearray()
    payload.extend(write_long(age))
    payload.extend(write_long(day_time))
    await conn.send_packet(0x64, bytes(payload))


# 伤害原因 -> (原版 damage_type, 死亡消息翻译键)
DAMAGE_SOURCES = {
    "摔落": ("minecraft:fall", "death.attack.fall"),
    "虚空": ("minecraft:out_of_world", "death.attack.outOfWorld"),
    "窒息": ("minecraft:in_wall", "death.attack.inWall"),
    "溺水": ("minecraft:drown", "death.attack.drown"),
    "岩浆": ("minecraft:lava", "death.attack.lava"),
    "火焰": ("minecraft:in_fire", "death.attack.inFire"),
    "燃烧": ("minecraft:on_fire", "death.attack.onFire"),
    "高温地面": ("minecraft:hot_floor", "death.attack.hotFloor"),
    "仙人掌": ("minecraft:cactus", "death.attack.cactus"),
    "甜浆果丛": ("minecraft:sweet_berry_bush", "death.attack.sweetBerryBush"),
    "冰冻": ("minecraft:freeze", "death.attack.freeze"),
    "饥饿": ("minecraft:starve", "death.attack.starve"),
    "闪电": ("minecraft:lightning_bolt", "death.attack.lightningBolt"),
    "爆炸": ("minecraft:explosion", "death.attack.explosion"),
    "魔法": ("minecraft:magic", "death.attack.magic"),
    "kill": ("minecraft:generic_kill", "death.attack.genericKill"),
    "generic": ("minecraft:generic", "death.attack.generic"),
}

# 原版 damage_type 名称 (/damage 命令) 也可直接作为原因传入
for _key, _msg in (
    ("fall", "fall"), ("out_of_world", "outOfWorld"), ("in_wall", "inWall"),
    ("drown", "drown"), ("lava", "lava"), ("in_fire", "inFire"), ("on_fire", "onFire"),
    ("hot_floor", "hotFloor"), ("cactus", "cactus"), ("sweet_berry_bush", "sweetBerryBush"),
    ("freeze", "freeze"), ("starve", "starve"), ("lightning_bolt", "lightningBolt"),
    ("explosion", "explosion"), ("magic", "magic"), ("generic_kill", "genericKill"),
    ("generic", "generic"), ("wither", "wither"), ("cramming", "cramming"),
    ("fly_into_wall", "flyIntoWall"), ("dragon_breath", "dragonBreath"),
    ("dry_out", "dryout"), ("stalagmite", "stalagmite"), ("thorns", "thorns"),
):
    DAMAGE_SOURCES.setdefault(_key, (f"minecraft:{_key}", f"death.attack.{_msg}"))
    DAMAGE_SOURCES.setdefault(f"minecraft:{_key}", (f"minecraft:{_key}", f"death.attack.{_msg}"))


def resolve_damage_source(conn: Connection, reason: str):
    """
    把内部伤害原因解析为 (damage_type, 死亡消息组件)。

    支持: 环境原因 (见 DAMAGE_SOURCES)、生物类型名 ("zombie")、
    远程生物 ("skeleton的箭") 以及玩家攻击 ("player:<名字>")。
    """
    from protocol.gamedata import entity_type_ids
    from protocol.text import translate, player_name
    victim = player_name(conn)
    reason = str(reason or "generic")

    if reason in DAMAGE_SOURCES:
        damage_type, key = DAMAGE_SOURCES[reason]
        return damage_type, translate(key, victim)
    if reason.startswith("player:"):
        return "minecraft:player_attack", translate(
            "death.attack.player", victim, {"text": reason[7:]})
    ranged = reason.endswith("的箭")
    mob = reason[:-2] if ranged else reason
    mob = mob.split(":")[-1]
    if f"minecraft:{mob}" in entity_type_ids():
        mob_component = {"translate": f"entity.minecraft.{mob}"}
        if ranged:
            return "minecraft:arrow", translate("death.attack.arrow", victim, mob_component)
        return "minecraft:mob_attack", translate("death.attack.mob", victim, mob_component)
    return "minecraft:generic", translate("death.attack.generic", victim)


async def _broadcast_damage_event(conn: Connection, server, damage_type: str):
    """Damage Event + 受伤音效: 客户端据此播放受伤动画 (屏幕泛红/实体变红)。"""
    from protocol.gamedata import registry_index
    from protocol.packet_map import get_clientbound_packet
    type_id = registry_index("minecraft:damage_type").get(damage_type, 0)
    payload = bytearray()
    payload.extend(write_varint(conn.entity_id))
    payload.extend(write_varint(type_id))
    payload.extend(write_varint(0))       # source cause id + 1 (0 = none)
    payload.extend(write_varint(0))       # source direct id + 1 (0 = none)
    payload.extend(write_boolean(False))  # has source position
    data = bytes(payload)
    for other in server.get_online_players():
        if other.protocol_version < 767:
            continue
        if other is not conn and conn.entity_id not in other.tracked_players:
            continue
        pid = get_clientbound_packet(other.protocol_version, "damage_event")
        if pid is not None:
            await other.send_packet(pid, data)


async def _damage_player(conn: Connection, amount: float, reason: str, server):
    """对玩家造成伤害; 生命值归零时进入死亡流程 (死亡界面 + 死亡消息)。"""
    if not conn.alive or conn.gamemode in {"creative", "spectator"}:
        return
    if getattr(conn, "_dead", False) or amount <= 0:
        return
    if conn.damage_cooldown_ticks > 0 and conn.last_damage_reason == reason:
        return
    gamerules = server.gamerules
    if reason == "摔落" and not gamerules.get("fallDamage", True):
        return
    if reason in ("火焰", "燃烧", "岩浆", "高温地面") and not gamerules.get("fireDamage", True):
        return
    if reason == "溺水" and not gamerules.get("drowningDamage", True):
        return
    if reason == "冰冻" and not gamerules.get("freezeDamage", True):
        return

    damage_type, death_message = resolve_damage_source(conn, reason)

    conn.health = max(0.0, conn.health - amount)
    conn.damage_cooldown_ticks = 10
    conn.last_damage_reason = reason
    await _send_update_health(conn)
    await _broadcast_damage_event(conn, server, damage_type)

    if conn.health > 0:
        return
    await _kill_player(conn, server, death_message)


async def _kill_player(conn: Connection, server, death_message):
    """玩家死亡: 掉落物品/经验、显示死亡界面、广播死亡消息。"""
    from protocol.packet_map import get_clientbound_packet as _gcp
    from protocol.text import encode_component

    conn.health = 0.0
    conn._dead = True
    conn.fire_ticks = 0

    if not server.gamerules.get("keepInventory", False):
        await _drop_player_inventory(conn, server)

    pid = _gcp(conn.protocol_version, "death_combat_event")
    if pid is not None:
        payload = bytearray()
        payload.extend(write_varint(conn.entity_id))
        payload.extend(encode_component(death_message, conn.protocol_version))
        await conn.send_packet(pid, bytes(payload))

    # Entity Event 3 = 死亡动画 (其他玩家看到倒地)
    status_pid = _gcp(conn.protocol_version, "entity_status")
    for other in server.get_online_players():
        if other is conn or conn.entity_id not in other.tracked_players:
            continue
        opid = _gcp(other.protocol_version, "entity_status")
        if opid is not None:
            await other.send_packet(opid, write_int(conn.entity_id) + write_byte(3))

    from protocol.text import plain_text
    if server.gamerules.get("showDeathMessages", True):
        server.broadcast_system_message(death_message, log=True)
    else:
        logging.getLogger("minecraft.server").info(plain_text(death_message))

    from plugins.bridge import hook_player_death
    hook_player_death(server, conn, plain_text(death_message))

    if server.gamerules.get("doImmediateRespawn", False):
        await respawn_player(conn, server)


async def _drop_player_inventory(conn: Connection, server):
    """死亡时掉落全部物品和部分经验 (keepInventory=false)。"""
    inventory = getattr(conn, "inventory_obj", None)
    if inventory is not None:
        import random
        for index, stack in enumerate(list(inventory.slots)):
            if stack is None or stack.is_empty:
                continue
            item = server.entity_manager.create_item(
                conn.x + random.uniform(-0.5, 0.5), conn.y + 0.5,
                conn.z + random.uniform(-0.5, 0.5), stack.item_id, stack.count)
            item.pickup_delay = 40
            inventory.slots[index] = None
        inventory.carried_item = None
        conn.inventory_state_id += 1
        from world.inventory import send_inventory_sync
        await send_inventory_sync(conn)

    dropped_xp = min(100, conn.experience_level * 7)
    if dropped_xp > 0:
        server.entity_manager.create_experience_orb(conn.x, conn.y + 0.5, conn.z, dropped_xp)
    conn.experience_total = 0
    conn.experience_level = 0
    conn.experience_progress = 0.0


async def respawn_player(conn: Connection, server):
    """
    玩家点击 "重生" 后的完整重生流程。

    客户端收到 Respawn 后会重建世界 (丢弃所有区块和实体), 因此需要重新发送
    区块、位置、生命值、物品栏以及周围的实体。
    """
    from handlers.play.spawn import _resolve_player_respawn_location
    from handlers.play.state import send_abilities, send_held_slot
    from protocol.packet_map import get_clientbound_packet

    respawn_x, respawn_y, respawn_z = _resolve_player_respawn_location(conn, server)
    conn.x = float(respawn_x) + 0.5
    conn.y = float(respawn_y)
    conn.z = float(respawn_z) + 0.5
    conn.fall_start_y = conn.y
    conn.on_ground = True
    conn.health = 20.0
    conn.food = 20
    conn.saturation = 5.0
    conn.air_supply = 300
    conn.fire_ticks = 0
    conn.freeze_ticks = 0
    conn.damage_cooldown_ticks = 60   # 重生保护
    conn.last_damage_reason = ""
    conn._dead = False

    respawn_pid = get_clientbound_packet(conn.protocol_version, "respawn")
    if respawn_pid is not None:
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload = bytearray()
        payload.extend(write_varint(0))  # Dimension type (overworld)
        payload.extend(write_identifier("minecraft:overworld"))
        payload.extend(write_long(hashed_seed(server)))
        payload.extend(write_ubyte(gamemode_map.get(conn.gamemode, 0)))
        payload.extend(write_byte(-1))        # Previous gamemode
        payload.extend(write_boolean(False))  # Is debug
        payload.extend(write_boolean(False))  # Is flat
        payload.extend(write_boolean(False))  # Has death location
        payload.extend(write_varint(0))       # Portal cooldown
        payload.extend(write_byte(0))         # Data kept (0 = nothing)
        await conn.send_packet(respawn_pid, bytes(payload))

    # 客户端世界已重建: 重新发送区块与实体
    conn.loaded_chunks.clear()
    conn.tracked_entities.clear()
    conn.tracked_players.clear()

    await send_abilities(conn)
    await send_held_slot(conn)
    await _send_spawn_position(conn, *server.spawn_position)
    await _send_game_event(conn, 13, 0.0)

    center_cx = math.floor(conn.x) >> 4
    center_cz = math.floor(conn.z) >> 4
    conn.chunk_center = (center_cx, center_cz)
    await _send_center_chunk(conn, center_cx, center_cz)
    view_distance = effective_view_distance(conn, server)
    chunk_coords = _sorted_chunk_coords(center_cx, center_cz, view_distance)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: server.generate_chunk_results(chunk_coords)[0])
    from handlers.play.chunks import _send_chunk_results_streamed
    await _send_chunk_results_streamed(conn, results)
    conn.loaded_chunks.update((cx, cz) for cx, cz, *_ in results)

    await _send_synchronize_position(conn)
    await _send_update_health(conn)
    await _send_set_experience(conn)
    await _send_time_update(conn, server)
    from handlers.play.weather import send_weather_state
    await send_weather_state(conn, server)
    from world.inventory import send_inventory_sync
    await send_inventory_sync(conn)

    # 其他玩家: 移除旧实体后重新生成
    from handlers.play.players import send_player_spawn, remove_player_entity
    remove_pid_payload = write_varint(1) + write_varint(conn.entity_id)
    for other in server.get_online_players():
        if other is conn:
            continue
        if conn.entity_id in other.tracked_players:
            rpid = get_clientbound_packet(other.protocol_version, "remove_entities")
            if rpid is not None:
                await other.send_packet(rpid, remove_pid_payload)
            await remove_player_entity(other, conn.entity_id)
        await send_player_spawn(other, conn)
        await send_player_spawn(conn, other)
    await _send_visible_entities_to_player(conn, server)

    from plugins.bridge import hook_player_respawn
    hook_player_respawn(server, conn)


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

    # 双向生成玩家实体 (必须在 Player Info 之后, 客户端需要列表项渲染皮肤)
    from handlers.play.players import sync_player_visibility
    await sync_player_visibility(server, conn)
