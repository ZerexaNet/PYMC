# ============================================================
# PyMC - 登录阶段处理器
# 处理玩家登录、压缩协商和进入配置阶段
# ============================================================

import logging
import uuid
from protocol.data_types import (
    read_string, read_varint, write_string, write_varint,
    write_uuid, write_boolean, read_uuid
)
from network.connection import Connection, ConnectionState

logger = logging.getLogger("PyMC.登录")


async def handle_login(conn: Connection, packet_id: int, payload: bytes,
                       server):
    """处理登录阶段的数据包。"""

    if packet_id == 0x00:
        # Login Start
        await _handle_login_start(conn, payload, server)

    elif packet_id == 0x03:
        # Login Acknowledged - 客户端确认登录成功，进入配置阶段
        await _handle_login_acknowledged(conn, server)

    else:
        logger.debug(f"登录阶段忽略数据包: 0x{packet_id:02X}")


async def _handle_login_start(conn: Connection, payload: bytes, server):
    """
    处理 Login Start 数据包 (0x00)。
    
    数据包格式:
        - String(16): 玩家名称
        - UUID: 玩家 UUID
    """
    offset = 0
    username, offset = read_string(payload, offset)
    player_uuid, offset = read_uuid(payload, offset)

    conn.username = username
    logger.info(f"玩家 {username} 正在登录... (来自 {conn.address})")

    # 离线模式: 根据用户名生成 UUID
    if not server.online_mode:
        conn.uuid = conn.generate_offline_uuid()
    else:
        conn.uuid = player_uuid

    # 分配实体 ID
    conn.entity_id = server.get_next_entity_id()

    # 启用压缩
    if server.compression_threshold >= 0:
        await _send_set_compression(conn, server.compression_threshold)
        conn.compression_threshold = server.compression_threshold
        logger.info(f"已为 {username} 启用压缩 (阈值: {server.compression_threshold} 字节)")

    # 发送 Login Success
    await _send_login_success(conn)
    logger.info(f"玩家 {username} 登录成功 (UUID: {conn.uuid}, 实体ID: {conn.entity_id})")


async def _send_set_compression(conn: Connection, threshold: int):
    """
    发送 Set Compression 数据包 (0x03)。
    通知客户端启用数据包压缩。
    """
    payload = write_varint(threshold)
    await conn.send_packet(0x03, payload)


async def _send_login_success(conn: Connection):
    """
    发送 Login Success 数据包 (0x02)。
    
    格式:
        - UUID: 玩家 UUID
        - String(16): 用户名
        - VarInt: 属性数量 (0)
        - Boolean: 严格错误处理
    """
    payload = bytearray()
    payload.extend(write_uuid(conn.uuid))
    payload.extend(write_string(conn.username))
    payload.extend(write_varint(0))     # 属性数量 = 0
    payload.extend(write_boolean(True))  # 严格错误处理
    await conn.send_packet(0x02, bytes(payload))


async def _handle_login_acknowledged(conn: Connection, server):
    """
    处理 Login Acknowledged 数据包 (0x03)。
    客户端确认收到 Login Success，切换到配置阶段。
    """
    conn.state = ConnectionState.CONFIGURATION
    logger.info(f"玩家 {conn.username} 进入配置阶段")

    # 发送配置阶段所需的数据包
    from handlers.configuration import send_configuration_packets
    await send_configuration_packets(conn, server)
