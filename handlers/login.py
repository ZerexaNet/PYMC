# ============================================================
# PyMC - 登录阶段处理器
# 处理玩家登录、压缩协商和进入配置阶段
# 现在包含多版本协议支持
# ============================================================

import logging
import uuid
from protocol.data_types import (
    read_string, read_varint, write_string, write_varint,
    write_uuid, write_boolean, read_uuid
)
from protocol.versions import has_configuration_phase, is_supported
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
        # Only for 1.20.2+ (configuration phase)
        await _handle_login_acknowledged(conn, server)

    else:
        logger.debug(f"登录阶段忽略数据包: 0x{packet_id:02X}")


async def _handle_login_start(conn: Connection, payload: bytes, server):
    """
    处理 Login Start 数据包 (0x00)。
    
    数据包格式 varies by version:
    - 1.8-1.15: String(16): username
    - 1.16-1.19: String(16): username
    - 1.19.3+: String(16): username + UUID
    """
    offset = 0
    username, offset = read_string(payload, offset)

    # Try to read UUID (1.19.3+ sends it in Login Start)
    player_uuid = None
    if offset < len(payload) and conn.protocol_version >= 761:
        try:
            player_uuid, offset = read_uuid(payload, offset)
        except (ValueError, IndexError):
            player_uuid = None

    conn.username = username
    logger.info(f"玩家 {username} 正在登录... (来自 {conn.address}, "
                f"版本 {conn.mc_version}, 协议 {conn.protocol_version})")

    # Check if this protocol version is allowed by server config
    min_version = int(server.config.get("min-protocol-version", 47))
    max_version = int(server.config.get("max-protocol-version", 770))
    if (not is_supported(conn.protocol_version)
            or conn.protocol_version < min_version
            or conn.protocol_version > max_version):
        logger.info(f"拒绝玩家 {username}: 协议版本 {conn.protocol_version} "
                    f"不在允许范围 [{min_version}, {max_version}]")
        await _send_disconnect_login(conn, f"Your protocol version ({conn.protocol_version}) is not supported.")
        return

    ip = conn.address.split(":", 1)[0]
    deny_reason = server.permissions.check_login_allowed(username, ip)
    if deny_reason:
        logger.info(f"拒绝玩家 {username} 登录: {deny_reason}")
        await conn.disconnect(deny_reason)
        return

    # 离线模式: 根据用户名生成 UUID
    if not server.online_mode:
        conn.uuid = conn.generate_offline_uuid()
    else:
        if player_uuid is not None:
            conn.uuid = player_uuid
        else:
            conn.uuid = conn.generate_offline_uuid()

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

    # Handle post-login transition based on version
    if has_configuration_phase(conn.protocol_version):
        # 1.20.2+: Wait for Login Acknowledged, then go to configuration phase
        # The state change happens in _handle_login_acknowledged
        pass
    else:
        # Pre-1.20.2: Go directly to play phase
        conn.state = ConnectionState.PLAY
        logger.info(f"玩家 {username} 直接进入游戏阶段 (无配置阶段)")

        # Send join game directly
        from handlers.play import send_join_game
        await send_join_game(conn, server)


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
    
    Format varies by protocol family:
    - 1.8-1.15: String(UUID) + String(username)
    - 1.16-1.19.1: UUID + String(username)
    - 1.19.3-1.20.6: UUID + String(username) + properties
    - 1.21.1: same plus strict error handling
    - 1.21.4: strict error handling was removed
    """
    payload = bytearray()
    if conn.protocol_version <= 578:
        payload.extend(write_string(str(conn.uuid)))
    else:
        payload.extend(write_uuid(conn.uuid))
    payload.extend(write_string(conn.username))

    if conn.protocol_version >= 761:
        payload.extend(write_varint(0))  # Empty profile properties

    if conn.protocol_version == 767:
        payload.extend(write_boolean(True))

    await conn.send_packet(0x02, bytes(payload))


async def _send_disconnect_login(conn: Connection, reason: str):
    """Send a Login Disconnect packet (0x00)."""
    import json
    chat_json = json.dumps({"text": reason}, ensure_ascii=False)
    payload = write_string(chat_json)
    await conn.send_packet(0x00, payload)
    await conn.disconnect(reason)


async def _handle_login_acknowledged(conn: Connection, server):
    """
    处理 Login Acknowledged 数据包 (0x03)。
    客户端确认收到 Login Success，切换到配置阶段。
    Only for 1.20.2+ (configuration phase).
    """
    if not has_configuration_phase(conn.protocol_version):
        # This packet shouldn't arrive for pre-1.20.2 clients
        logger.warning(f"收到意外的 Login Acknowledged (协议 {conn.protocol_version})")
        return

    conn.state = ConnectionState.CONFIGURATION
    logger.info(f"玩家 {conn.username} 进入配置阶段")

    # 发送配置阶段所需的数据包
    from handlers.configuration import send_configuration_packets
    await send_configuration_packets(conn, server)
