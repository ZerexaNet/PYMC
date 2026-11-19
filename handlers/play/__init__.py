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
  0x49  - Multi Block Change
  0x54  - Set Center Chunk (update_view_position)
  0x56  - Set Default Spawn Position (spawn_position)
  0x5C  - Set Experience
  0x5D  - Update Health
  0x64  - Update Time
  0x6C  - System Chat Message (system_chat)
  0x70  - Entity Teleport

--- 客户端发送 (Serverbound) ---
  0x00  - Confirm Teleportation
  0x05  - Chat Command
  0x06  - Signed Chat Command
  0x07  - Chat Message
  0x09  - Chunk Batch Received
  0x0C  - Click Container (window click)
  0x0D  - Close Container
  0x0E  - Plugin Message (serverbound)
  0x11  - Edit Message
  0x14  - Interact
  0x1A  - Keep Alive
  0x1C  - Player Position
  0x1D  - Player Position and Rotation
  0x1E  - Player Rotation
  0x1F  - Player On Ground
  0x22  - Set Creative Mode Slot (creative inventory action)
  0x26  - Block Dig
  0x28  - Use Item On
  0x29  - Use Item
  0x31  - Held Item Slot
"""

import logging

from network.connection import Connection

# 从子模块重新导出所有公共 API，确保外部导入路径不变
from handlers.play.join import (
    send_join_game,
    _send_login_play,
    _send_spawn_position,
    _send_game_event,
    _send_center_chunk,
    _send_synchronize_position,
    _send_update_health,
    _send_set_experience,
    _send_time_update,
    _damage_player,
    _update_player_motion_state,
    _tick_damage_effects,
    _broadcast_player_join,
    _add_player_experience,
    _send_collect_entity,
    _player_block_position,
    _get_block_at,
)

from handlers.play.chunks import (
    _send_chunk_data,
    _send_chunk_data_terrain,
    _build_chunk_light_data,
    _send_prebuilt_chunk,
    _send_chunk_batch,
    _send_chunk_results_streamed,
    _send_deferred_chunks,
    _stream_chunks_around_player,
    _schedule_chunk_stream_update,
    _sorted_chunk_coords,
    CHUNK_STREAM_BATCH_SIZE,
)

from handlers.play.movement import (
    _handle_confirm_teleportation,
    _handle_keepalive,
    _handle_player_position,
    _handle_player_position_rotation,
    _handle_player_rotation,
    _handle_player_on_ground,
    _handle_held_item_slot,
    _read_movement_on_ground,
)

from handlers.play.blocks import (
    _handle_block_dig,
    _handle_block_place,
    _send_block_change,
    _broadcast_block_change,
    _send_multi_block_change,
    _broadcast_multi_block_changes,
    _sync_world_edit,
    _refresh_chunks_for_players,
    HOTBAR_PLACEABLES,
    BLOCK_DROPS,
    FACE_OFFSETS,
)

from handlers.play.chat import (
    _handle_chat_message,
    _handle_chat_command,
    build_system_message_payload,
    send_system_message,
    execute_server_command,
    build_player_info_update,
    build_player_info_remove,
    COMMAND_ALIASES,
    RECOGNIZED_BUT_UNSUPPORTED,
    ALL_VANILLA_COMMAND_NAMES,
)

from handlers.play.entities import (
    _send_entity_teleport,
    _send_entity_remove,
    _send_experience_orb_spawn,
    _send_generic_entity_spawn,
    _send_visible_entities_to_player,
    broadcast_entity_spawn,
    broadcast_entity_remove,
    build_remove_entities,
    _entity_within_tracking_range,
    ENTITY_TYPE_IDS,
)

from handlers.play.combat import (
    _handle_interact,
    damage_mob,
    get_attack_damage,
)

from handlers.play.spawn import (
    _resolve_spawn_location,
    _is_safe_player_location,
    _resolve_initial_player_location,
    _resolve_player_respawn_location,
    _load_or_generate_spawn_chunk,
    _is_spawn_clear_block,
    _is_spawn_ground_block,
    _is_suffocating_block,
    PASSABLE_BLOCKS,
    SPAWN_CLEAR_BLOCKS,
    SPAWN_UNSAFE_GROUND_BLOCKS,
    SPAWN_CANOPY_BLOCKS,
)

from handlers.play.weather import (
    build_game_event_payload,
    send_weather_state,
    broadcast_weather_change,
    rain_strength,
    thunder_strength,
    GAME_EVENT_END_RAINING,
    GAME_EVENT_BEGIN_RAINING,
    GAME_EVENT_RAIN_LEVEL,
    GAME_EVENT_THUNDER_LEVEL,
)

from handlers.play.players import (
    build_spawn_player_payload,
    build_player_metadata_payload,
    build_rotate_head_payload,
    send_player_spawn,
    sync_player_visibility,
    relay_player_movement,
    remove_player_entity,
    PLAYER_ENTITY_TYPE,
)

logger = logging.getLogger("PyMC.游戏")


def _is_serverbound_packet(conn: Connection, packet_id: int,
                           packet_name: str,
                           native_packet_id: int | None = None) -> bool:
    """Match a packet without leaking native IDs into older protocols."""
    from protocol.packet_map import get_serverbound_packet
    from protocol.versions import NATIVE_PROTOCOL_VERSION

    mapped_id = get_serverbound_packet(conn.protocol_version, packet_name)
    if mapped_id is not None:
        return packet_id == mapped_id
    return (conn.protocol_version == NATIVE_PROTOCOL_VERSION
            and native_packet_id is not None
            and packet_id == native_packet_id)


def _player_window_slot_to_inventory(slot: int) -> int | None:
    """Translate protocol window-0 slots to PlayerInventory indices."""
    from world.inventory import window_slot_to_inventory
    return window_slot_to_inventory(slot)


_REVERSE_MAPS: dict[int, dict[int, str]] = {}


def _serverbound_name(conn: Connection, packet_id: int) -> str | None:
    """把客户端数据包 ID 解析为逻辑名称 (按连接协商的协议版本)。"""
    from protocol.packet_map import SERVERBOUND_PACKETS, build_serverbound_reverse_map
    version = conn.protocol_version
    if version not in SERVERBOUND_PACKETS:
        return None
    reverse = _REVERSE_MAPS.get(version)
    if reverse is None:
        reverse = _REVERSE_MAPS[version] = build_serverbound_reverse_map(version)
    return reverse.get(packet_id)


async def handle_play(conn: Connection, packet_id: int, payload: bytes,
                      server):
    """分发 Play 阶段的客户端数据包。"""
    name = _serverbound_name(conn, packet_id)
    if name is None:
        return

    if name == "keep_alive":
        _handle_keepalive(conn, payload)
        return
    if name == "confirm_teleportation":
        _handle_confirm_teleportation(conn, payload)
        return
    if name == "client_command":
        await _handle_client_command(conn, payload, server)
        return
    if name == "client_settings":
        await _handle_client_settings(conn, payload, server)
        return
    if name == "custom_payload":
        from handlers.configuration import _handle_plugin_message
        _handle_plugin_message(conn, payload)
        return
    if name == "ping_request":
        from protocol.packet_map import get_clientbound_packet
        pid = get_clientbound_packet(conn.protocol_version, "ping_response")
        if pid is not None:
            await conn.send_packet(pid, payload[:8])
        return
    if name in ("chunk_batch_received", "pong", "chat_session_update",
                "configuration_acknowledged"):
        return

    # 死亡后只接受重生请求和聊天/命令; 忽略移动、交互等动作
    if getattr(conn, '_dead', False) and name not in (
            "chat_message", "chat_command", "signed_chat_command", "tab_complete"):
        return

    import time as _time
    if name not in ("player_on_ground",):
        conn.last_active = _time.monotonic()

    if name in ("chat_command", "signed_chat_command"):
        await _handle_chat_command(conn, payload, server)
    elif name == "chat_message":
        await _handle_chat_message(conn, payload, server)
    elif name == "tab_complete":
        await _handle_tab_complete(conn, payload, server)
    elif name == "player_position":
        await _handle_player_position(conn, payload, server)
    elif name == "player_position_rotation":
        await _handle_player_position_rotation(conn, payload, server)
    elif name == "player_rotation":
        await _handle_player_rotation(conn, payload, server)
    elif name == "player_on_ground":
        await _handle_player_on_ground(conn, payload, server)
    elif name == "block_dig":
        await _handle_block_dig(conn, payload, server)
    elif name == "held_item_slot":
        _handle_held_item_slot(conn, payload)
        from handlers.play.players import broadcast_player_equipment
        await broadcast_player_equipment(server, conn)
    elif name == "block_place":
        await _handle_block_place(conn, payload, server)
    elif name == "click_container":
        await _handle_click_container(conn, payload, server)
        from handlers.play.players import broadcast_player_equipment
        await broadcast_player_equipment(server, conn)
    elif name == "close_container":
        await _handle_close_container(conn, payload, server)
    elif name == "interact":
        await _handle_interact(conn, payload, server)
    elif name == "steer_vehicle":
        await _handle_steer_vehicle(conn, payload, server)
    elif name == "enchant_item":
        from world.enchanting_window import handle_enchant_button
        await handle_enchant_button(conn, payload, server)
    elif name == "set_creative_mode_slot":
        await _handle_creative_inventory_action(conn, payload, server)
        from handlers.play.players import broadcast_player_equipment
        await broadcast_player_equipment(server, conn)
    elif name == "entity_action":
        await _handle_entity_action(conn, payload, server)
    elif name == "arm_animation":
        await _handle_arm_animation(conn, payload, server)
    elif name == "player_abilities":
        _handle_player_abilities(conn, payload)
    elif name == "use_item":
        pass  # TODO: item use in air (eating, bows, ...)


async def _handle_client_command(conn: Connection, payload: bytes, server):
    """Client Command: 0 = Perform Respawn, 1 = Request Stats。"""
    from protocol.data_types import read_varint, write_varint
    action, _ = read_varint(payload, 0)
    if action == 0:
        if getattr(conn, '_dead', False):
            await _handle_respawn(conn, server)
    elif action == 1:
        from protocol.packet_map import get_clientbound_packet
        pid = get_clientbound_packet(conn.protocol_version, "statistics")
        if pid is not None:
            await conn.send_packet(pid, write_varint(0))


async def _handle_client_settings(conn: Connection, payload: bytes, server):
    """游戏内修改设置 (视距/皮肤层/主手): 重新同步给其他玩家。"""
    from handlers.configuration import parse_client_information
    old_parts = conn.skin_parts
    parse_client_information(conn, payload)
    if conn.skin_parts != old_parts:
        from handlers.play.players import broadcast_player_metadata
        await broadcast_player_metadata(server, conn)


async def _handle_tab_complete(conn: Connection, payload: bytes, server):
    """Command Suggestions Request -> Command Suggestions Response。"""
    from protocol.data_types import read_varint, read_string, write_varint, write_string, write_boolean
    from protocol.packet_map import get_clientbound_packet
    transaction_id, offset = read_varint(payload, 0)
    text, _ = read_string(payload, offset)
    manager = getattr(server, "command_manager", None)
    pid = get_clientbound_packet(conn.protocol_version, "tab_complete")
    if manager is None or pid is None:
        return

    body = text[1:] if text.startswith("/") else text
    try:
        suggestions = manager.get_suggestions(conn, body) or []
    except Exception as e:
        logger.debug(f"命令补全失败 ({text!r}): {e}")
        suggestions = []

    # 被替换的范围: 最后一个参数 (命令名补全时为整个命令名)
    last_space = text.rfind(" ")
    start = last_space + 1 if last_space >= 0 else (1 if text.startswith("/") else 0)
    prefix = text[start:].lower()
    cleaned = []
    for suggestion in suggestions:
        suggestion = str(suggestion)
        if last_space < 0:
            suggestion = suggestion.lstrip("/")
        if suggestion and suggestion.lower().startswith(prefix) and suggestion not in cleaned:
            cleaned.append(suggestion)
    cleaned.sort()

    out = bytearray()
    out.extend(write_varint(transaction_id))
    out.extend(write_varint(start))
    out.extend(write_varint(len(text) - start))
    out.extend(write_varint(len(cleaned)))
    for suggestion in cleaned:
        out.extend(write_string(suggestion))
        out.extend(write_boolean(False))  # no tooltip
    await conn.send_packet(pid, bytes(out))


async def _handle_steer_vehicle(conn: Connection, payload: bytes, server):
    """Player Input while riding: forward/sideways movement, sneak (0x02) gets off."""
    import struct
    if len(payload) < 9 or getattr(conn, "vehicle", None) is None:
        return
    sideways, forward = struct.unpack(">ff", payload[:8])
    flags = payload[8]
    conn.vehicle_input = (forward, sideways)
    if flags & 0x02:
        from world.minecart import dismount
        from handlers.play.entities import broadcast_passengers
        cart = dismount(conn)
        if cart is not None:
            await broadcast_passengers(server, cart)
            from commands.vanilla.essentials import teleport
            await teleport(server, conn, cart.x, cart.y + 0.7, cart.z)


async def _handle_entity_action(conn: Connection, payload: bytes, server):
    """Player Command: 潜行/疾跑状态变化, 同步给其他玩家。"""
    from protocol.data_types import read_varint
    _entity_id, offset = read_varint(payload, 0)
    action, offset = read_varint(payload, offset)
    if action == 0:
        conn.sneaking = True
    elif action == 1:
        conn.sneaking = False
    elif action == 3:
        conn.sprinting = True
    elif action == 4:
        conn.sprinting = False
    else:
        return
    from handlers.play.players import broadcast_player_metadata
    await broadcast_player_metadata(server, conn)


async def _handle_arm_animation(conn: Connection, payload: bytes, server):
    """Swing Arm: 把挥手动画转发给其他玩家。"""
    from protocol.data_types import read_varint
    hand, _ = read_varint(payload, 0) if payload else (0, 0)
    from handlers.play.players import broadcast_player_animation
    await broadcast_player_animation(server, conn, 0 if hand == 0 else 3)


def _handle_player_abilities(conn: Connection, payload: bytes):
    """Player Abilities (serverbound): 仅允许有飞行能力的模式切换飞行。"""
    if not payload:
        return
    flying = bool(payload[0] & 0x02)
    conn.flying = flying and conn.gamemode in ("creative", "spectator")
    if conn.flying:
        conn.fall_start_y = conn.y


async def _handle_click_container(conn: Connection, payload: bytes, server):
    """Handle Click Container packet (0x0C).

    Delegates to the server-authoritative interaction engine so the same
    logic covers both the player inventory and opened block containers.
    """
    from world.inventory_interactions import handle_container_click
    await handle_container_click(conn, payload, server, _player_window_slot_to_inventory)


async def _handle_close_container(conn: Connection, payload: bytes, server=None):
    """Handle Close Container packet (0x0D)."""
    from protocol.data_types import read_varint
    offset = 0
    window_id, offset = read_varint(payload, offset)

    if window_id == 0 or getattr(conn, '_open_container_type', None) == 'crafting':
        await return_crafting_grid(conn, server, window_id)

    if getattr(conn, '_open_window_id', None) != window_id:
        return

    from world.block_behavior import container_manager, container_view
    pos = getattr(conn, '_open_container_pos', None)
    if pos is not None and getattr(conn, '_open_container_type', 'block') == 'block':
        view = container_view(*pos)
        for part in getattr(view, "positions", (pos,)):
            container_manager.remove_viewer(*part, conn.entity_id)

    from world.enchanting_window import return_inputs
    for stack in return_inputs(conn, window_id):
        await _drop_stack(conn, server, stack, stack.count)
    conn._open_entity_container = None
    conn._open_window_id = None
    conn._open_container_pos = None
    conn._open_container_type = None


async def return_crafting_grid(conn: Connection, server, window_id: int):
    """Closing a crafting grid hands its items back (dropped when the inventory is full)."""
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return
    from world.crafting_window import return_grid_items
    from world.inventory_interactions import _drop_stack
    from world.inventory import send_inventory_sync
    leftovers = []

    def give(stack):
        left = inv.add_item(stack)
        if left > 0:
            extra = stack.copy()
            extra.count = left
            leftovers.append(extra)

    if window_id != 0 and getattr(conn, '_crafting_grid', None) is None:
        return
    if window_id == 0 and not any(inv.slots[i] for i in (41, 42, 43, 44)):
        inv.slots[45] = None
        return
    return_grid_items(conn, window_id, give)
    if window_id != 0:
        conn._crafting_grid = None
    for stack in leftovers:
        await _drop_stack(conn, server, stack, stack.count)
    await send_inventory_sync(conn)


async def _handle_respawn(conn: Connection, server):
    """Handle player respawn after death (Client Command: Perform Respawn)."""
    from handlers.play.join import respawn_player
    await respawn_player(conn, server)


async def _handle_creative_inventory_action(conn: Connection, payload: bytes, server):
    """Handle Set Creative Mode Slot packet (0x22)."""
    from protocol.data_types import read_short
    from world.inventory import ItemStack, decode_slot_entry

    if conn.gamemode != "creative":
        return  # Only allowed in creative mode

    offset = 0
    slot_idx, offset = read_short(payload, offset)
    clicked_item, offset = decode_slot_entry(payload, offset)

    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    inventory_slot = _player_window_slot_to_inventory(slot_idx)
    if inventory_slot is None:
        return  # Invalid slot

    if clicked_item is None or clicked_item.is_empty:
        inv.set_slot(inventory_slot, None)
    else:
        inv.set_slot(inventory_slot, clicked_item)

    conn.inventory_state_id += 1
