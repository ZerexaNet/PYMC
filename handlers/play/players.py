# ============================================================
# PyMC - 玩家实体可见性
# 玩家实体的生成、移动转发和头部旋转同步
# ============================================================

"""
玩家互相可见性同步。

包括:
  - send_player_spawn: 向观察者生成玩家实体 (Spawn Entity + Set Entity Data)
  - sync_player_visibility: 入服时双向生成所有在线玩家
  - relay_player_movement: 将玩家移动/视角转发给视距内的其他玩家
    (Entity Teleport + Rotate Head, 经网络优化器限频)

协议说明 (1.21.1, 协议 767):
  - Spawn Entity (0x01): 玩家实体类型 ID = 128
    (来源: PrismarineJS/minecraft-data pc/1.20.5 entities.json,
     dataPaths 将 1.21/1.21.1 映射到该注册表)
  - Set Entity Data (0x57): 玩家皮肤层 metadata (index 17, byte)
  - Rotate Head (0x47): 头部朝向
  - Entity Teleport (0x70): 位置与身体朝向 (ID 走 packet_map)

限制: 仅原生 1.21.1 路径 (version_handler 为 None 的客户端)。
旧版本客户端的玩家实体生成需要各版本独立的 Spawn Player 包,
当前跳过,不影响其它功能。
"""

import logging

from protocol.data_types import (
    write_varint, write_double, write_short,
    write_uuid, write_angle, write_ubyte,
)
from protocol.packet_map import get_clientbound_packet
from network.connection import Connection

logger = logging.getLogger("PyMC.玩家")

# --- 1.21.1 (协议 767) 客户端包 ID ---
SPAWN_ENTITY_PID = 0x01
SET_ENTITY_DATA_PID = 0x57
ROTATE_HEAD_PID = 0x47

# minecraft:player 实体类型 ID (1.21.1 注册表)
PLAYER_ENTITY_TYPE = 128

# 玩家 metadata: 皮肤层 (index 17, Byte, 0x7F = 全部显示)
SKIN_PARTS_INDEX = 17
SKIN_PARTS_ALL = 0x7F


def _supports_player_spawn(conn: Connection) -> bool:
    """仅原生 1.21.1 路径支持玩家实体生成。"""
    return conn.version_handler is None


def build_spawn_player_payload(player: Connection) -> bytes:
    """构建 Spawn Entity (玩家) 数据包负载。"""
    payload = bytearray()
    payload.extend(write_varint(player.entity_id))
    payload.extend(write_uuid(player.uuid))
    payload.extend(write_varint(PLAYER_ENTITY_TYPE))
    payload.extend(write_double(player.x))
    payload.extend(write_double(player.y))
    payload.extend(write_double(player.z))
    payload.extend(write_angle(player.pitch))
    payload.extend(write_angle(player.yaw))
    payload.extend(write_angle(player.yaw))  # head yaw
    payload.extend(write_varint(0))          # data
    payload.extend(write_short(0))           # velocity X
    payload.extend(write_short(0))           # velocity Y
    payload.extend(write_short(0))           # velocity Z
    return bytes(payload)


def build_player_metadata_payload(player: Connection) -> bytes:
    """构建 Set Entity Data 负载: 显示全部皮肤层 (披风/帽子/袖子等)。"""
    payload = bytearray()
    payload.extend(write_varint(player.entity_id))
    payload.extend(write_ubyte(SKIN_PARTS_INDEX))
    payload.extend(write_varint(0))  # metadata type 0 = Byte
    payload.extend(write_ubyte(SKIN_PARTS_ALL))
    payload.extend(write_ubyte(0xFF))  # terminator
    return bytes(payload)


def build_rotate_head_payload(player: Connection) -> bytes:
    """构建 Rotate Head 数据包负载。"""
    payload = bytearray()
    payload.extend(write_varint(player.entity_id))
    payload.extend(write_angle(player.yaw))
    return bytes(payload)


async def send_player_spawn(observer: Connection, player: Connection):
    """
    向观察者生成一个玩家实体。

    必须在 Player Info Update 之后发送 (客户端需要列表项渲染皮肤)。
    """
    if not _supports_player_spawn(observer):
        return
    if player.entity_id in observer.tracked_players:
        return
    await observer.send_packet(SPAWN_ENTITY_PID, build_spawn_player_payload(player))
    await observer.send_packet(SET_ENTITY_DATA_PID, build_player_metadata_payload(player))
    observer.tracked_players.add(player.entity_id)


async def sync_player_visibility(server, new_conn: Connection):
    """
    入服时双向同步玩家实体:
      - 向新玩家生成所有已有玩家
      - 向所有已有玩家生成新玩家
    """
    for other in server.get_online_players():
        if other == new_conn:
            continue
        await send_player_spawn(new_conn, other)
        await send_player_spawn(other, new_conn)


def _player_within_tracking_range(player: Connection, observer: Connection,
                                  view_distance: int) -> bool:
    max_distance = (view_distance * 16) ** 2
    dx = player.x - observer.x
    dz = player.z - observer.z
    return dx * dx + dz * dz <= max_distance


async def relay_player_movement(server, moved: Connection):
    """
    将玩家的位置和视角转发给视距内的其他玩家。

    经网络优化器限频 (network-movement-rate-hz, 默认 20Hz)。
    位置使用 Entity Teleport (简单可靠), 头部朝向使用 Rotate Head。
    """
    if not moved.username:
        return

    optimizer = getattr(server, "network_optimizer", None)
    if optimizer is not None and not optimizer.should_send_movement(moved):
        return

    rotate_payload = build_rotate_head_payload(moved)

    for observer in server.get_online_players():
        if observer == moved or not observer.alive:
            continue
        if not _supports_player_spawn(observer):
            continue
        if moved.entity_id not in observer.tracked_players:
            continue
        if not _player_within_tracking_range(moved, observer, server.view_distance):
            continue

        teleport_pid = get_clientbound_packet(
            observer.protocol_version, "entity_teleport")

        # Entity Teleport: 位置 + 身体朝向
        payload = bytearray()
        payload.extend(write_varint(moved.entity_id))
        payload.extend(write_double(moved.x))
        payload.extend(write_double(moved.y))
        payload.extend(write_double(moved.z))
        payload.extend(write_angle(moved.yaw))
        payload.extend(write_angle(moved.pitch))
        payload.extend(b"\x01" if moved.on_ground else b"\x00")
        if teleport_pid is not None:
            await observer.send_packet(teleport_pid, bytes(payload))
        await observer.send_packet(ROTATE_HEAD_PID, rotate_payload)


async def remove_player_entity(observer: Connection, entity_id: int):
    """从观察者处移除玩家实体并清理跟踪状态。"""
    observer.tracked_players.discard(entity_id)
