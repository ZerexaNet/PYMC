# ============================================================
# PyMC - 状态查询处理器
# 处理服务器列表 Ping (SLP) 请求
# 现在包含多版本协议支持
# ============================================================

import json
import logging
from protocol.data_types import write_string, read_long, write_long
from protocol.versions import get_version_name, NATIVE_PROTOCOL_VERSION
from network.connection import Connection

logger = logging.getLogger("PyMC.状态")


async def handle_status(conn: Connection, packet_id: int, payload: bytes,
                        server):
    """处理状态查询阶段的数据包。"""

    if packet_id == 0x00:
        # Status Request - 客户端请求服务器信息
        await _handle_status_request(conn, server)

    elif packet_id == 0x01:
        # Ping Request - 客户端发送 Ping
        await _handle_ping_request(conn, payload)

    else:
        logger.warning(f"状态阶段收到未知数据包: 0x{packet_id:02X}")


async def _handle_status_request(conn: Connection, server):
    """
    处理 Status Request 数据包 (0x00)。
    返回服务器信息 JSON，包含客户端的协议版本信息。
    """
    # 构建服务器状态响应
    online_players = server.get_online_players()
    
    # Use the client's protocol version in the response
    client_version = get_version_name(conn.protocol_version)
    
    # Build supported versions list for display
    supported_versions = server.config.get("support-protocol-versions", "all")
    if supported_versions == "all":
        version_name = f"PyMC 1.8-1.21"
    else:
        version_name = f"PyMC Multi-Version"
    
    response = {
        "version": {
            "name": version_name,
            "protocol": conn.protocol_version
        },
        "players": {
            "max": server.max_players,
            "online": len(online_players),
            "sample": [
                {"name": p.username, "id": str(p.uuid)}
                for p in online_players[:10]
            ]
        },
        "description": {
            "text": server.motd
        },
        "enforcesSecureChat": False,
        "previewsChat": False
    }

    # 1.19+ clients expect optional fields
    if conn.protocol_version >= 759:
        response["enforcesSecureChat"] = False

    json_str = json.dumps(response, ensure_ascii=False)
    response_payload = write_string(json_str)
    await conn.send_packet(0x00, response_payload)
    logger.info(f"已发送状态响应给 {conn.address} (协议 {conn.protocol_version}, {client_version})")


async def _handle_ping_request(conn: Connection, payload: bytes):
    """
    处理 Ping Request 数据包 (0x01)。
    原样返回客户端发送的 Long 值。
    """
    # 客户端发送 8 字节时间戳，原样返回
    if len(payload) >= 8:
        await conn.send_packet(0x01, payload[:8])
    else:
        # 兼容处理
        await conn.send_packet(0x01, payload)
    await conn.disconnect("状态查询完成")
