# ============================================================
# PyMC - 握手阶段处理器
# 处理客户端的初始握手数据包
# 现在包含多版本协议检测
# ============================================================

import logging
from protocol.data_types import read_varint, read_string, read_ushort
from protocol.versions import (
    is_supported, get_version_name, get_handler_version,
    has_configuration_phase, NATIVE_PROTOCOL_VERSION
)
from network.connection import Connection, ConnectionState

logger = logging.getLogger("PyMC.握手")


async def handle_handshake(conn: Connection, packet_id: int, payload: bytes):
    """
    处理握手数据包 (Packet ID: 0x00)。
    
    数据包格式:
        - VarInt: 协议版本号
        - String: 服务器地址
        - Unsigned Short: 服务器端口
        - VarInt: 下一状态 (1=Status, 2=Login, 3=Transfer)
    """
    if packet_id != 0x00:
        logger.warning(f"握手阶段收到非法数据包 ID: 0x{packet_id:02X}")
        await conn.disconnect("无效的握手数据包")
        return

    offset = 0
    protocol_version, offset = read_varint(payload, offset)
    server_address, offset = read_string(payload, offset)
    server_port, offset = read_ushort(payload, offset)
    next_state, offset = read_varint(payload, offset)

    # Store protocol version on the connection
    conn.protocol_version = protocol_version
    conn.mc_version = get_version_name(protocol_version)

    logger.info(f"握手: 协议版本={protocol_version} ({conn.mc_version}), "
                f"地址={server_address}:{server_port}, "
                f"下一状态={next_state}")

    # Preserve the requested protocol. Unsupported versions may query status,
    # but login rejects them instead of silently speaking a different protocol.
    if not is_supported(protocol_version):
        logger.warning(f"协议版本 {protocol_version} 不受支持")

    # Set up the version handler
    _setup_version_handler(conn)

    if next_state == 1:
        conn.state = ConnectionState.STATUS
    elif next_state == 2:
        conn.state = ConnectionState.LOGIN
    else:
        logger.warning(f"未知的下一状态: {next_state}")
        await conn.disconnect(f"不支持的握手状态: {next_state}")


def _setup_version_handler(conn: Connection):
    """Set up the version-specific handler for this connection."""
    from handlers.versioned import get_version_handler
    conn.version_handler = get_version_handler(conn.protocol_version)
    handler_name = conn.version_handler.__class__.__name__
    logger.info(f"已为 {conn.mc_version} (协议 {conn.protocol_version}) "
                f"加载版本处理器: {handler_name}")
