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
from protocol.versions import (
    filter_supported_versions, has_configuration_phase, is_supported,
)
from network.connection import Connection, ConnectionState

logger = logging.getLogger("PyMC.登录")


async def handle_login(conn: Connection, packet_id: int, payload: bytes,
                       server):
    """处理登录阶段的数据包。"""

    if packet_id == 0x00:
        # Login Start
        await _handle_login_start(conn, payload, server)

    elif packet_id == 0x01:
        # Encryption Response (online-mode)
        await _handle_encryption_response(conn, payload, server)

    elif packet_id == 0x03:
        # Login Acknowledged - 客户端确认登录成功，进入配置阶段
        # Only for 1.20.2+ (configuration phase)
        await _handle_login_acknowledged(conn, server)

    else:
        logger.debug(f"登录阶段忽略数据包: 0x{packet_id:02X}")


def _is_valid_username(username: str) -> bool:
    return 1 <= len(username) <= 16 and all(
        ch.isascii() and (ch.isalnum() or ch == "_") for ch in username)


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

    from protocol.text import translate
    from protocol.versions import NATIVE_PROTOCOL_VERSION, get_version_name
    auth_log = logging.getLogger("minecraft.auth")

    # 原版: 用户名必须是 1-16 位的 [A-Za-z0-9_]
    if not _is_valid_username(username):
        conn.username = ""
        await _send_disconnect_login(conn, translate("multiplayer.disconnect.invalid_player_data"))
        return

    conn.username = username
    logger.debug(f"玩家 {username} 正在登录... (来自 {conn.address}, "
                 f"版本 {conn.mc_version}, 协议 {conn.protocol_version})")

    if not getattr(server, "accepting_players", True):
        await _send_disconnect_login(conn, {"text": "Server is still starting! Please wait before reconnecting."})
        return

    # Check if this protocol version is allowed by server config
    min_version = int(server.config.get("min-protocol-version", 47))
    max_version = int(server.config.get("max-protocol-version", 770))
    allowed_versions = filter_supported_versions(
        server.config.get("support-protocol-versions", "all"),
        min_version,
        max_version,
    )
    if (not is_supported(conn.protocol_version)
            or conn.protocol_version not in allowed_versions):
        native_name = get_version_name(NATIVE_PROTOCOL_VERSION)
        key = ("multiplayer.disconnect.outdated_client"
               if conn.protocol_version < NATIVE_PROTOCOL_VERSION
               else "multiplayer.disconnect.incompatible")
        auth_log.info(f"Disconnecting {username} ({conn.address}): "
                      f"unsupported protocol version {conn.protocol_version}")
        await conn.disconnect(translate(key, native_name), log=False)
        return

    ip = conn.address.rsplit(":", 1)[0]
    deny_reason = server.permissions.check_login(username, ip)
    if deny_reason is None and len(server.get_online_players()) >= int(server.max_players) \
            and not server.permissions.is_op(username):
        deny_reason = translate("multiplayer.disconnect.server_full")
    if deny_reason is not None:
        from protocol.text import plain_text
        auth_log.info(f"Disconnecting {username} ({conn.address}): {plain_text(deny_reason)}")
        await conn.disconnect(deny_reason, log=False)
        return

    # 同名玩家已在线: 与原版一样踢掉旧连接
    existing = server.find_player(username)
    if existing is not None and existing is not conn:
        await existing.disconnect(translate("multiplayer.disconnect.duplicate_login"))

    if server.online_mode:
        # 正版验证: 发送 Encryption Request, 等待 Encryption Response
        await _send_encryption_request(conn, server)
        return

    # 离线模式: 根据用户名生成 UUID (与原版一致)
    conn.uuid = conn.generate_offline_uuid()
    await _complete_login(conn, server)


async def _send_encryption_request(conn: Connection, server):
    """Encryption Request (0x01): server id + RSA 公钥 + verify token。"""
    import os
    conn.verify_token = os.urandom(4)
    public_key = server.keypair.public_der
    payload = bytearray()
    payload.extend(write_string(""))                 # server id (空)
    payload.extend(write_varint(len(public_key)))
    payload.extend(public_key)
    payload.extend(write_varint(len(conn.verify_token)))
    payload.extend(conn.verify_token)
    if conn.protocol_version >= 766:
        payload.extend(write_boolean(True))          # should authenticate
    await conn.send_packet(0x01, bytes(payload))


async def _handle_encryption_response(conn: Connection, payload: bytes, server):
    """Encryption Response (0x01): 启用加密并向会话服务器验证玩家身份。"""
    from network import encryption
    from protocol.text import translate
    auth_log = logging.getLogger("minecraft.auth")

    if not server.online_mode or not conn.verify_token or not conn.username:
        await conn.disconnect(translate("multiplayer.disconnect.unexpected_query_response"))
        return
    try:
        offset = 0
        length, offset = read_varint(payload, offset)
        encrypted_secret = payload[offset:offset + length]
        offset += length
        length, offset = read_varint(payload, offset)
        encrypted_token = payload[offset:offset + length]
        shared_secret = server.keypair.decrypt(encrypted_secret)
        token = server.keypair.decrypt(encrypted_token)
    except Exception:
        await conn.disconnect(translate("multiplayer.disconnect.invalid_public_key_signature"))
        return
    if token != conn.verify_token or len(shared_secret) != 16:
        await conn.disconnect(translate("multiplayer.disconnect.invalid_public_key_signature"))
        return
    conn.verify_token = b""
    conn.enable_encryption(shared_secret)

    server_hash = encryption.server_id_hash("", shared_secret, server.keypair.public_der)
    try:
        profile = await encryption.has_joined(conn.username, server_hash)
    except Exception as e:
        auth_log.error(f"Couldn't verify username because servers are unavailable: {e}")
        await conn.disconnect(translate("multiplayer.disconnect.authservers_down"))
        return
    if not profile or not profile.get("id"):
        auth_log.error(f"Username '{conn.username}' tried to join with an invalid session")
        await conn.disconnect(translate("multiplayer.disconnect.unverified_username"))
        return

    conn.uuid = uuid.UUID(profile["id"])
    conn.username = profile.get("name", conn.username)
    conn.profile_properties = list(profile.get("properties", []))

    # 验证后的真实名字再做一次封禁/白名单检查
    ip = conn.address.rsplit(":", 1)[0]
    deny_reason = server.permissions.check_login(conn.username, ip)
    if deny_reason is not None:
        await conn.disconnect(deny_reason)
        return
    await _complete_login(conn, server)


async def _complete_login(conn: Connection, server):
    """分配实体 ID、启用压缩并发送 Login Success。"""
    username = conn.username
    auth_log = logging.getLogger("minecraft.auth")

    # 分配实体 ID
    conn.entity_id = server.get_next_entity_id()

    # 启用压缩
    if server.compression_threshold >= 0:
        await _send_set_compression(conn, server.compression_threshold)
        conn.compression_threshold = server.compression_threshold

    # 发送 Login Success
    await _send_login_success(conn)
    auth_log.info(f"UUID of player {username} is {conn.uuid}")

    # Handle post-login transition based on version
    if has_configuration_phase(conn.protocol_version):
        # 1.20.2+: Wait for Login Acknowledged, then go to configuration phase
        # The state change happens in _handle_login_acknowledged
        pass
    else:
        # Pre-1.20.2: Go directly to play phase
        conn.state = ConnectionState.PLAY

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
        # Profile properties (online-mode 下包含带签名的皮肤 textures)
        properties = getattr(conn, "profile_properties", None) or []
        payload.extend(write_varint(len(properties)))
        for prop in properties:
            payload.extend(write_string(prop.get("name", "")))
            payload.extend(write_string(prop.get("value", "")))
            signature = prop.get("signature")
            payload.extend(write_boolean(signature is not None))
            if signature is not None:
                payload.extend(write_string(signature))

    if conn.protocol_version == 767:
        payload.extend(write_boolean(True))

    await conn.send_packet(0x02, bytes(payload))


async def _send_disconnect_login(conn: Connection, reason):
    """Send a Login Disconnect packet (0x00) and close the connection."""
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
    logger.debug(f"玩家 {conn.username} 进入配置阶段")

    # 发送配置阶段所需的数据包
    from handlers.configuration import send_configuration_packets
    await send_configuration_packets(conn, server)
