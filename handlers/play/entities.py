# ============================================================
# PyMC - 实体管理数据包
# 处理实体的生成、传送和移除
# ============================================================

"""
实体相关的数据包构建与发送。

包括:
  - _send_entity_teleport
  - _send_entity_remove / build_remove_entities
  - _send_experience_orb_spawn
  - _send_generic_entity_spawn
  - _send_visible_entities_to_player
  - broadcast_entity_spawn
  - broadcast_entity_remove
  - _entity_within_tracking_range
  - ENTITY_TYPE_IDS
"""

import logging

from protocol.data_types import (
    write_varint, write_double, write_short,
    write_uuid, write_angle, write_boolean,
)
from network.connection import Connection

logger = logging.getLogger("PyMC.实体")

# --- 实体类型 ID 映射 ---
ENTITY_TYPE_IDS = {
    "item": 71,
    "cow": 30,
    "pig": 100,
    "sheep": 111,
    "zombie": 150,
}


def _encode_entity_velocity_component(value: float) -> int:
    scaled = int(max(-3.9, min(3.9, value)) * 8000.0)
    return max(-32768, min(32767, scaled))


def _entity_within_tracking_range(entity, conn: Connection, range_chunks: int = 10) -> bool:
    max_distance = (range_chunks * 16) ** 2
    return entity.distance_squared_to(conn.x, conn.y, conn.z) <= max_distance


async def _send_experience_orb_spawn(conn: Connection, entity):
    payload = bytearray()
    payload.extend(write_varint(entity.entity_id))
    payload.extend(write_double(entity.x))
    payload.extend(write_double(entity.y))
    payload.extend(write_double(entity.z))
    payload.extend(write_short(int(entity.metadata.get("count", 1))))
    await conn.send_packet(0x02, bytes(payload))


async def _send_generic_entity_spawn(conn: Connection, entity):
    entity_type_id = ENTITY_TYPE_IDS.get(entity.metadata.get("mob_type", entity.kind))
    if entity_type_id is None:
        return

    payload = bytearray()
    payload.extend(write_varint(entity.entity_id))
    payload.extend(write_uuid(entity.uuid_value))
    payload.extend(write_varint(entity_type_id))
    payload.extend(write_double(entity.x))
    payload.extend(write_double(entity.y))
    payload.extend(write_double(entity.z))
    payload.extend(write_angle(entity.pitch))
    payload.extend(write_angle(entity.yaw))
    payload.extend(write_angle(entity.yaw))
    payload.extend(write_varint(0))
    payload.extend(write_short(_encode_entity_velocity_component(entity.vx)))
    payload.extend(write_short(_encode_entity_velocity_component(entity.vy)))
    payload.extend(write_short(_encode_entity_velocity_component(entity.vz)))
    await conn.send_packet(0x01, bytes(payload))


async def _send_entity_teleport(conn: Connection, entity):
    from protocol.packet_map import get_clientbound_packet
    payload = bytearray()
    payload.extend(write_varint(entity.entity_id))
    payload.extend(write_double(entity.x))
    payload.extend(write_double(entity.y))
    payload.extend(write_double(entity.z))
    payload.extend(write_angle(entity.yaw))
    payload.extend(write_angle(entity.pitch))
    payload.extend(write_boolean(entity.on_ground))
    pid = get_clientbound_packet(conn.protocol_version, "entity_teleport")
    if pid is not None:
        await conn.send_packet(pid, bytes(payload))


def build_remove_entities(entity_ids: list[int]) -> bytes:
    """构建 Remove Entities 数据包负载 (0x42)。"""
    payload = bytearray()
    payload.extend(write_varint(len(entity_ids)))
    for eid in entity_ids:
        payload.extend(write_varint(eid))
    return bytes(payload)


async def _send_entity_remove(conn: Connection, entity_ids: list[int]):
    from protocol.packet_map import get_clientbound_packet
    if not entity_ids:
        return
    payload = build_remove_entities(entity_ids)
    pid = get_clientbound_packet(conn.protocol_version, "remove_entities")
    if pid is not None:
        await conn.send_packet(pid, payload)


async def _send_visible_entities_to_player(conn: Connection, server):
    for entity in server.entity_manager.list_entities():
        if not _entity_within_tracking_range(entity, conn, server.view_distance):
            continue
        if entity.kind == "orb":
            await _send_experience_orb_spawn(conn, entity)
            conn.tracked_entities.add(entity.entity_id)
        elif entity.kind in {"item", "mob"}:
            await _send_generic_entity_spawn(conn, entity)
            conn.tracked_entities.add(entity.entity_id)


async def broadcast_entity_spawn(server, entity):
    for conn in server.get_online_players():
        if not _entity_within_tracking_range(entity, conn, server.view_distance):
            continue
        if entity.kind == "orb":
            await _send_experience_orb_spawn(conn, entity)
            conn.tracked_entities.add(entity.entity_id)
        elif entity.kind in {"item", "mob"}:
            await _send_generic_entity_spawn(conn, entity)
            conn.tracked_entities.add(entity.entity_id)


async def broadcast_entity_remove(server, entity_ids: list[int]):
    for conn in server.get_online_players():
        conn.tracked_entities.difference_update(entity_ids)
        await _send_entity_remove(conn, entity_ids)
