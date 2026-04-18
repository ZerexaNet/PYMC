# ============================================================
# PyMC - 握手阶段处理器
# 处理客户端的初始握手数据包
# ============================================================

import logging
from protocol.data_types import read_varint, read_string, read_ushort
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

    logger.info(f"握手: 协议版本={protocol_version}, "
                f"地址={server_address}:{server_port}, "
                f"下一状态={next_state}")

    if next_state == 1:
        conn.state = ConnectionState.STATUS
    elif next_state == 2:
        conn.state = ConnectionState.LOGIN
    else:
        logger.warning(f"未知的下一状态: {next_state}")
        await conn.disconnect(f"不支持的握手状态: {next_state}")
