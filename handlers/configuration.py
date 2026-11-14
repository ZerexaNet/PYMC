# ============================================================
# PyMC - 配置阶段处理器
# 发送注册表数据、完成配置并进入游戏阶段
# 现在包含多版本协议支持 (仅 1.20.2+ 使用配置阶段)
# ============================================================

import logging
from protocol.data_types import (
    write_string, write_varint, write_boolean, write_identifier
)
from protocol.nbt import (
    encode_nbt, NbtByte, NbtFloat, NbtLong, NbtDouble
)
from protocol.versions import has_configuration_phase
from network.connection import Connection, ConnectionState
from world.biomes import build_biome_registry_entries

logger = logging.getLogger("PyMC.配置")


async def handle_configuration(conn: Connection, packet_id: int,
                                payload: bytes, server):
    """处理配置阶段的数据包 (serverbound, 1.20.5+ 编号)。"""

    if packet_id == 0x00:
        # Client Information - 客户端设置信息
        parse_client_information(conn, payload)

    elif packet_id == 0x02:
        # Custom Payload (Plugin Message) - 品牌信息等
        _handle_plugin_message(conn, payload)

    elif packet_id == 0x03:
        # Finish Configuration - 客户端确认配置完成
        await _handle_finish_configuration(conn, server)

    elif packet_id == 0x04:
        # Keep Alive
        pass

    elif packet_id == 0x07:
        # Known Packs
        logger.debug(f"收到已知数据包信息: {conn.username}")

    else:
        logger.debug(f"配置阶段忽略数据包: 0x{packet_id:02X}")


def parse_client_information(conn: Connection, payload: bytes) -> None:
    """
    解析 Client Information (配置阶段 0x00 / 游戏阶段 client_settings)。

    Locale(String) ViewDistance(Byte) ChatMode(VarInt) ChatColors(Bool)
    SkinParts(UByte) MainHand(VarInt) TextFiltering(Bool) AllowListing(Bool)
    """
    from protocol.data_types import read_string, read_varint
    try:
        offset = 0
        locale, offset = read_string(payload, offset)
        view_distance = payload[offset]
        if view_distance >= 128:
            view_distance -= 256
        offset += 1
        _chat_mode, offset = read_varint(payload, offset)
        offset += 1  # chat colors
        skin_parts = payload[offset]
        offset += 1
        main_hand, offset = read_varint(payload, offset)
        offset += 1  # text filtering
        allow_listing = bool(payload[offset]) if offset < len(payload) else True
    except (IndexError, ValueError) as e:
        logger.debug(f"无法解析客户端设置 [{conn.username}]: {e}")
        return
    conn.locale = locale
    conn.client_view_distance = max(0, int(view_distance))
    conn.skin_parts = skin_parts & 0x7F
    conn.main_hand = main_hand
    conn.allow_server_listing = allow_listing


def _handle_plugin_message(conn: Connection, payload: bytes) -> None:
    from protocol.data_types import read_string
    try:
        channel, offset = read_string(payload, 0)
        if channel == "minecraft:brand":
            conn.client_brand, _ = read_string(payload, offset)
    except (IndexError, ValueError, UnicodeDecodeError):
        pass


async def send_configuration_packets(conn: Connection, server):
    """
    发送配置阶段所需的所有数据包。
    仅在 1.20.2+ (配置阶段) 时调用。

    顺序与原版服务端一致:
      brand -> feature flags -> known packs -> registry data -> tags -> finish
    """
    if not has_configuration_phase(conn.protocol_version):
        logger.warning(f"尝试为不支持配置阶段的客户端 (协议 {conn.protocol_version}) 发送配置数据包")
        return

    # 1. 服务端品牌信息
    brand = server.config.get("server-brand", "PyMC") if server is not None else "PyMC"
    await _send_plugin_message(conn, "minecraft:brand", write_string(str(brand)))

    # 2. 启用的特性开关
    await _send_feature_flags(conn, ["minecraft:vanilla"])

    # 3. 已知数据包 (Known Packs)
    await _send_known_packs(conn)

    # 4. 注册表数据 (Registry Data)
    await _send_registry_data(conn)

    # 5. 标签 (Update Tags) —— 游泳、攀爬、工具挖掘速度等都依赖标签
    await _send_tags(conn)

    # 6. 完成配置
    await _send_finish_configuration(conn)


async def _send_plugin_message(conn: Connection, channel: str, data: bytes):
    """发送 Plugin Message 数据包 (配置阶段: 0x01)。"""
    payload = write_identifier(channel) + data
    await conn.send_packet(0x01, payload)


async def _send_feature_flags(conn: Connection, flags: list[str]):
    """发送 Feature Flags 数据包 (配置阶段: 0x0C)。"""
    payload = bytearray(write_varint(len(flags)))
    for flag in flags:
        payload.extend(write_identifier(flag))
    await conn.send_packet(0x0C, bytes(payload))


async def _send_known_packs(conn: Connection):
    """
    发送 Known Packs 数据包 (0x0E)。
    告诉客户端服务器知道的数据包。
    """
    from protocol.versions import get_version_name
    version_str = get_version_name(conn.protocol_version)

    payload = bytearray()
    payload.extend(write_varint(1))
    payload.extend(write_string("minecraft"))   # 命名空间
    payload.extend(write_string("core"))        # ID
    payload.extend(write_string(version_str))   # 版本
    await conn.send_packet(0x0E, bytes(payload))


def build_registry_data_payloads() -> list[bytes]:
    """
    构建全部 Registry Data (0x07) 负载。

    内容来自原版 1.21.1 数据 (protocol/data/registries_767.json)，包含完整的
    维度类型、生物群系、聊天类型、伤害类型、附魔、画、狼变种、盔甲纹饰、
    旗帜图案和唱片注册表。条目顺序即客户端分配的数字 ID。
    """
    from protocol.gamedata import synced_registries

    payloads = []
    for registry_id, entries in synced_registries().items():
        payload = bytearray()
        payload.extend(write_identifier(registry_id))
        payload.extend(write_varint(len(entries)))
        for entry_id, nbt_bytes in entries:
            payload.extend(write_identifier(entry_id))
            payload.extend(write_boolean(True))  # 附带数据
            payload.extend(nbt_bytes)
        payloads.append(bytes(payload))
    return payloads


_REGISTRY_PAYLOAD_CACHE: list[bytes] | None = None
_TAGS_PAYLOAD_CACHE: bytes | None = None


async def _send_registry_data(conn: Connection):
    """逐个发送所有同步注册表 (Registry Data, 0x07)。"""
    global _REGISTRY_PAYLOAD_CACHE
    if _REGISTRY_PAYLOAD_CACHE is None:
        _REGISTRY_PAYLOAD_CACHE = build_registry_data_payloads()
    for payload in _REGISTRY_PAYLOAD_CACHE:
        await conn.send_packet(0x07, payload)


def build_tags_payload() -> bytes:
    """构建 Update Tags 负载: [registry -> [tag -> [numeric id]]]。"""
    from protocol.gamedata import tags

    all_tags = tags()
    payload = bytearray(write_varint(len(all_tags)))
    for registry_id, registry_tags in all_tags.items():
        payload.extend(write_identifier(registry_id))
        payload.extend(write_varint(len(registry_tags)))
        for tag_name, ids in registry_tags.items():
            payload.extend(write_identifier(tag_name))
            payload.extend(write_varint(len(ids)))
            for numeric_id in ids:
                payload.extend(write_varint(numeric_id))
    return bytes(payload)


async def _send_tags(conn: Connection):
    """发送 Update Tags 数据包 (配置阶段: 0x0D)。"""
    global _TAGS_PAYLOAD_CACHE
    if _TAGS_PAYLOAD_CACHE is None:
        _TAGS_PAYLOAD_CACHE = build_tags_payload()
    await conn.send_packet(0x0D, _TAGS_PAYLOAD_CACHE)


async def _send_single_registry(conn: Connection, registry_id: str,
                                 entries: dict):
    """
    发送单个注册表的 Registry Data 数据包 (0x07)，条目为 Python dict。
    供插件/Mod 追加自定义注册表条目使用。
    """
    payload = bytearray()
    payload.extend(write_identifier(registry_id))
    payload.extend(write_varint(len(entries)))

    for entry_id, entry_data in entries.items():
        payload.extend(write_identifier(entry_id))
        payload.extend(write_boolean(True))  # 有数据
        payload.extend(encode_nbt(entry_data, with_type=True))

    await conn.send_packet(0x07, bytes(payload))


async def _send_finish_configuration(conn: Connection):
    """发送 Finish Configuration 数据包 (0x03)。"""
    await conn.send_packet(0x03, b'')


async def _handle_finish_configuration(conn: Connection, server):
    """
    处理 Finish Configuration 数据包 (0x03)。
    客户端确认配置完成，进入游戏阶段。
    """
    conn.state = ConnectionState.PLAY
    logger.debug(f"玩家 {conn.username} 完成配置，进入游戏")

    # 发送 Play 阶段的初始数据包
    from handlers.play import send_join_game
    await send_join_game(conn, server)
