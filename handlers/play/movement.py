# ============================================================
# PyMC - 玩家移动处理
# 处理位置/旋转/着地状态数据包
# ============================================================

"""
玩家移动数据包处理。

包括:
  - _handle_player_position (0x1C)
  - _handle_player_position_rotation (0x1D)
  - _handle_player_rotation (0x1E)
  - _handle_player_on_ground (0x1F)
  - _handle_confirm_teleportation (0x00)
  - _handle_keepalive (0x1A)
  - _handle_held_item_slot
"""

import struct
import logging

from protocol.data_types import (
    read_varint, read_double, read_float,
)
from network.connection import Connection

logger = logging.getLogger("PyMC.移动")


def _handle_confirm_teleportation(conn: Connection, payload: bytes):
    """处理 Confirm Teleportation (0x00)。"""
    teleport_id, _ = read_varint(payload, 0)
    logger.debug(f"{conn.username} 确认传送 ID={teleport_id}")


def _handle_keepalive(conn: Connection, payload: bytes):
    """处理 Keep Alive (0x18) 响应。"""
    if len(payload) >= 8:
        keepalive_id = struct.unpack('>q', payload[:8])[0]
        logger.debug(f"{conn.username} KeepAlive 响应: {keepalive_id}")


def _read_movement_on_ground(payload: bytes, offset: int) -> tuple[bool, int]:
    """
    读取 1.21.1 的 MovementFlags。

    低位 bit 0 表示 on_ground，其它位保留给水平碰撞等状态。
    旧协议这里是单独 boolean，1.21.1 已改成 flags。
    """
    if offset >= len(payload):
        return False, offset
    flags = payload[offset]
    return (flags & 0x01) != 0, offset + 1


async def _handle_player_position(conn: Connection, payload: bytes, server):
    """处理 Player Position (0x1C)。"""
    if len(payload) < 25:  # 3*double + byte
        return
    offset = 0
    x, offset = read_double(payload, offset)
    y, offset = read_double(payload, offset)
    z, offset = read_double(payload, offset)
    on_ground, offset = _read_movement_on_ground(payload, offset)

    from handlers.play.join import _update_player_motion_state
    await _update_player_motion_state(conn, y, on_ground, server)
    conn.x = x
    conn.y = y
    conn.z = z
    conn.on_ground = on_ground
    from handlers.play.chunks import _schedule_chunk_stream_update
    _schedule_chunk_stream_update(conn, server)


async def _handle_player_position_rotation(conn: Connection, payload: bytes,
                                            server):
    """处理 Player Position and Rotation (0x1D)。"""
    if len(payload) < 33:  # 3*double + 2*float + byte
        return
    offset = 0
    x, offset = read_double(payload, offset)
    y, offset = read_double(payload, offset)
    z, offset = read_double(payload, offset)
    yaw, offset = read_float(payload, offset)
    pitch, offset = read_float(payload, offset)
    on_ground, offset = _read_movement_on_ground(payload, offset)

    from handlers.play.join import _update_player_motion_state
    await _update_player_motion_state(conn, y, on_ground, server)
    conn.x = x
    conn.y = y
    conn.z = z
    conn.yaw = yaw
    conn.pitch = pitch
    conn.on_ground = on_ground
    from handlers.play.chunks import _schedule_chunk_stream_update
    _schedule_chunk_stream_update(conn, server)


async def _handle_player_rotation(conn: Connection, payload: bytes, server):
    """处理 Player Rotation (0x1E)。"""
    if len(payload) < 9:  # 2*float + byte
        return
    offset = 0
    yaw, offset = read_float(payload, offset)
    pitch, offset = read_float(payload, offset)
    on_ground, offset = _read_movement_on_ground(payload, offset)

    from handlers.play.join import _update_player_motion_state
    await _update_player_motion_state(conn, conn.y, on_ground, server)
    conn.yaw = yaw
    conn.pitch = pitch
    conn.on_ground = on_ground


async def _handle_player_on_ground(conn: Connection, payload: bytes, server):
    """处理 Player On Ground (0x1F / StatusOnly)。"""
    on_ground, _ = _read_movement_on_ground(payload, 0)
    from handlers.play.join import _update_player_motion_state
    await _update_player_motion_state(conn, conn.y, on_ground, server)
    conn.on_ground = on_ground


def _handle_held_item_slot(conn: Connection, payload: bytes):
    """处理热键栏选中槽位。"""
    if len(payload) < 2:
        return
    slot = struct.unpack_from(">h", payload, 0)[0]
    if 0 <= slot < 9:
        conn.selected_hotbar_slot = slot
