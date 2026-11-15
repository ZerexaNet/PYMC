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


SERVER_ICON_FILE = "server-icon.png"
_icon_cache: tuple[float, str | None] | None = None


def load_server_icon(path: str = SERVER_ICON_FILE) -> str | None:
    """
    读取 server-icon.png (必须是 64x64 PNG) 并编码为 data URI。
    与原版一样: 文件不存在或尺寸不对时不发送图标。
    """
    global _icon_cache
    import base64
    import os
    import struct
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _icon_cache = None
        return None
    if _icon_cache is not None and _icon_cache[0] == mtime:
        return _icon_cache[1]
    icon = None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            if (width, height) == (64, 64):
                icon = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
            else:
                logger.warning("Couldn't load server icon: Must be 64 pixels wide and 64 pixels high")
        else:
            logger.warning("Couldn't load server icon: not a PNG file")
    except OSError as e:
        logger.warning(f"Couldn't load server icon: {e}")
    _icon_cache = (mtime, icon)
    return icon


def build_status_response(server, client_protocol: int) -> dict:
    """构建服务器列表 Ping 的 JSON 响应 (与原版字段一致)。"""
    from protocol.text import to_component
    from protocol.versions import filter_supported_versions, is_supported

    config = server.config
    allowed = filter_supported_versions(
        config.get("support-protocol-versions", "all"),
        int(config.get("min-protocol-version", 47)),
        int(config.get("max-protocol-version", 770)),
    )
    # 客户端版本受支持时回显其协议号 (显示为兼容); 否则报告原生协议号,
    # 客户端会显示 "过时的客户端/服务端" 并给出版本名。
    compatible = is_supported(client_protocol) and client_protocol in allowed
    protocol = client_protocol if compatible else NATIVE_PROTOCOL_VERSION

    response = {
        "version": {
            "name": get_version_name(NATIVE_PROTOCOL_VERSION),
            "protocol": protocol,
        },
        "description": to_component(server.motd),
        "enforcesSecureChat": False,
    }

    online_players = server.get_online_players()
    players = {"max": int(server.max_players), "online": len(online_players)}
    if not config.get("hide-online-players", False):
        listed = [p for p in online_players if getattr(p, "allow_server_listing", True)]
        if listed:
            import random
            sample = random.sample(listed, min(12, len(listed)))
            players["sample"] = [{"name": p.username, "id": str(p.uuid)} for p in sample]
    response["players"] = players

    icon = load_server_icon()
    if icon:
        response["favicon"] = icon
    return response


async def _handle_status_request(conn: Connection, server):
    """
    处理 Status Request 数据包 (0x00)。
    enable-status=false 时与原版一样不响应 (客户端显示无法连接)。
    """
    if not server.config.get("enable-status", True):
        await conn.disconnect()
        return

    response = build_status_response(server, conn.protocol_version)
    json_str = json.dumps(response, ensure_ascii=False)
    await conn.send_packet(0x00, write_string(json_str))
    logger.debug(f"已发送状态响应给 {conn.address} (协议 {conn.protocol_version})")


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
    await conn.disconnect()
