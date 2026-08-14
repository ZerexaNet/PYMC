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


async def handle_play(conn: Connection, packet_id: int, payload: bytes,
                      server):
    """分发 Play 阶段的客户端数据包。"""

    if _is_serverbound_packet(conn, packet_id, "confirm_teleportation", 0x00):
        # Confirm Teleportation
        _handle_confirm_teleportation(conn, payload)

    elif _is_serverbound_packet(conn, packet_id, "chat_command", 0x05):
        # Chat Command
        await _handle_chat_command(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "signed_chat_command", 0x06):
        # Signed Chat Command
        await _handle_chat_command(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "chat_message", 0x07):
        # Chat Message (聊天消息)
        await _handle_chat_message(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "chunk_batch_received", 0x09):
        # Chunk Batch Received (客户端确认区块批次)
        pass  # 不需要特殊处理

    elif _is_serverbound_packet(conn, packet_id, "keep_alive", 0x1A):
        # Keep Alive
        _handle_keepalive(conn, payload)

    elif _is_serverbound_packet(conn, packet_id, "player_position", 0x1C):
        # Player Position
        await _handle_player_position(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "player_position_rotation", 0x1D):
        # Player Position and Rotation
        await _handle_player_position_rotation(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "player_rotation", 0x1E):
        # Player Rotation
        await _handle_player_rotation(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "player_on_ground", 0x1F):
        # Player On Ground
        await _handle_player_on_ground(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "block_dig", 0x26):
        # Block Dig
        await _handle_block_dig(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "held_item_slot", 0x31):
        # Held Item Slot
        _handle_held_item_slot(conn, payload)

    elif _is_serverbound_packet(conn, packet_id, "block_place", 0x3A):
        # Use Item On / Block Place
        await _handle_block_place(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "click_container", 0x0C):
        # Click Container (window click)
        await _handle_click_container(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "close_container", 0x0D):
        # Close Container
        _handle_close_container(conn, payload)

    elif _is_serverbound_packet(conn, packet_id, "interact", 0x14):
        # Interact (Entity)
        pass  # TODO: entity interaction

    elif _is_serverbound_packet(conn, packet_id, "set_creative_mode_slot", 0x22):
        # Set Creative Mode Slot
        await _handle_creative_inventory_action(conn, payload, server)

    elif _is_serverbound_packet(conn, packet_id, "use_item", 0x29):
        # Use Item (right-click air)
        pass  # TODO: item use in air

    else:
        # 忽略未处理的数据包
        pass


async def _handle_click_container(conn: Connection, payload: bytes, server):
    """Handle Click Container packet (0x0C)."""
    from protocol.data_types import read_varint, read_short, read_byte
    from world.inventory import decode_slot_entry, send_inventory_sync

    offset = 0
    window_id, offset = read_varint(payload, offset)
    state_id, offset = read_varint(payload, offset)
    slot_idx, offset = read_short(payload, offset)
    button, offset = read_byte(payload, offset)
    mode, offset = read_varint(payload, offset)

    # Only the player inventory is currently backed by server-side storage.
    if window_id != 0:
        return

    # Reject stale client actions and restore the authoritative state.
    if state_id != conn.inventory_state_id:
        await send_inventory_sync(conn)
        return

    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    # Consume, but do not trust, the client-predicted slot changes.
    changed_count, offset = read_varint(payload, offset)
    if changed_count < 0 or changed_count > 128:
        await send_inventory_sync(conn)
        return
    for _ in range(changed_count):
        _, offset = read_short(payload, offset)
        _, offset = decode_slot_entry(payload, offset)
    _, offset = decode_slot_entry(payload, offset)

    if mode == 0 and 0 <= slot_idx < inv.TOTAL_SLOTS and button in (0, 1):
        slot_item = inv.get_slot(slot_idx)
        cursor = inv.carried_item
        if button == 0:  # left click: pick up, place, merge, or swap
            if cursor is None or cursor.is_empty:
                inv.carried_item = slot_item
                inv.set_slot(slot_idx, None)
            elif slot_item is None or slot_item.is_empty:
                inv.set_slot(slot_idx, cursor)
                inv.carried_item = None
            elif slot_item.can_stack_with(cursor) and slot_item.count < slot_item.max_stack_size:
                moved = min(cursor.count, slot_item.max_stack_size - slot_item.count)
                slot_item.count += moved
                cursor.count -= moved
                if cursor.count <= 0:
                    inv.carried_item = None
                inv.state_id += 1
            else:
                inv.set_slot(slot_idx, cursor)
                inv.carried_item = slot_item
        else:  # right click: pick up half or place one
            if cursor is None or cursor.is_empty:
                if slot_item is not None and not slot_item.is_empty:
                    take = (slot_item.count + 1) // 2
                    inv.carried_item = slot_item.copy()
                    inv.carried_item.count = take
                    slot_item.count -= take
                    if slot_item.count <= 0:
                        inv.set_slot(slot_idx, None)
                    else:
                        inv.state_id += 1
            elif slot_item is None or slot_item.is_empty:
                placed = cursor.copy()
                placed.count = 1
                inv.set_slot(slot_idx, placed)
                cursor.count -= 1
                if cursor.count <= 0:
                    inv.carried_item = None
            elif slot_item.can_stack_with(cursor) and slot_item.count < slot_item.max_stack_size:
                slot_item.count += 1
                cursor.count -= 1
                if cursor.count <= 0:
                    inv.carried_item = None
                inv.state_id += 1

    conn.inventory_state_id += 1
    await send_inventory_sync(conn)


def _handle_close_container(conn: Connection, payload: bytes):
    """Handle Close Container packet (0x0D)."""
    from protocol.data_types import read_varint
    offset = 0
    window_id, offset = read_varint(payload, offset)
    # No server-side action needed for now


async def _handle_creative_inventory_action(conn: Connection, payload: bytes, server):
    """Handle Set Creative Mode Slot packet (0x22)."""
    from protocol.data_types import read_short
    from world.inventory import ItemStack, decode_slot_entry

    if conn.gamemode != "creative":
        return  # Only allowed in creative mode

    offset = 0
    slot_idx, offset = read_short(payload, offset)
    clicked_item = decode_slot_entry(payload, offset)

    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    if slot_idx < 0 or slot_idx >= 46:
        return  # Invalid slot

    if clicked_item is None or clicked_item.is_empty:
        inv.set_slot(slot_idx, None)
    else:
        inv.set_slot(slot_idx, clicked_item)

    conn.inventory_state_id += 1
