# ============================================================
# PyMC - 聊天与命令系统
# 处理聊天消息、系统消息和命令执行
# ============================================================

"""
聊天消息与命令处理。

包括:
  - _handle_chat_message (0x07)
  - _handle_chat_command (0x05, 0x06)
  - build_system_message_payload
  - send_system_message
  - execute_server_command (通过 CommandManager 分发)
  - build_player_info_update / build_player_info_remove
"""

import logging

from protocol.data_types import (
    write_varint, write_string, write_boolean,
    write_uuid,
)
from network.connection import Connection

logger = logging.getLogger("PyMC.聊天")

# --- 命令别名映射 (保留用于兼容性，实际别名解析已迁移至 CommandManager) ---
COMMAND_ALIASES = {
    "teleport": "tp",
    "experience": "xp",
    "tell": "msg",
    "w": "msg",
    "tm": "teammsg",
    "?": "help",
    "gm": "gamemode",
}

# --- 已识别但不支持的命令 ---
RECOGNIZED_BUT_UNSUPPORTED = {
    "debug", "jfr", "loot", "perf", "publish", "random",
    "return", "setidletimeout", "spectate", "teammsg", "transfer",
}

# --- 所有原版命令名 ---
ALL_VANILLA_COMMAND_NAMES = sorted({
    "advancement", "attribute", "ban", "ban-ip", "banlist", "bossbar", "clear",
    "clone", "damage", "data", "datapack", "debug", "defaultgamemode", "deop",
    "difficulty", "effect", "enchant", "execute", "experience", "fill",
    "fillbiome", "forceload", "function", "gamemode", "gamerule", "give",
    "help", "item", "jfr", "kick", "kill", "list", "locate", "loot", "me",
    "msg", "op", "pardon", "pardon-ip", "particle", "perf", "place",
    "playsound", "publish", "random", "recipe", "reload", "return", "ride",
    "save-all", "save-off", "save-on", "say", "schedule", "scoreboard",
    "seed", "setblock", "setidletimeout", "setworldspawn", "spawnpoint",
    "spectate", "spreadplayers", "stop", "summon", "tag", "team", "teammsg",
    "teleport", "tell", "tellraw", "time", "title", "tm", "tp", "transfer",
    "trigger", "w", "weather", "whitelist", "worldborder", "xp",
    # PyMC 扩展
    "group", "perm", "save-status", "entities",
})


def build_system_message_payload(message: str | dict, overlay: bool = False,
                                 protocol_version: int = 767) -> bytes:
    """构建 system_chat 负载 (文本组件 + overlay 标志)。"""
    from protocol.text import encode_component
    payload = bytearray()
    payload.extend(encode_component(message, protocol_version))
    payload.extend(write_boolean(overlay))
    return bytes(payload)


async def send_system_message(conn: Connection, text, overlay: bool = False):
    """发送系统聊天消息给单个玩家 (字符串或文本组件)。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_system_chat(conn, text, overlay)
    else:
        from protocol.packet_map import get_clientbound_packet
        pid = get_clientbound_packet(conn.protocol_version, "system_chat") or 0x6C
        await conn.send_packet(
            pid, build_system_message_payload(text, overlay, conn.protocol_version))


MAX_CHAT_LENGTH = 256


def _is_legal_chat(message: str) -> bool:
    return all(ch != "\u00a7" and ord(ch) >= 32 and ch != "\x7f" for ch in message)


async def _handle_chat_message(conn: Connection, payload: bytes, server):
    """
    处理 Chat Message。

    离线模式下忽略签名字段，按原版 ``chat.type.text`` 格式 (``<名字> 消息``)
    广播给所有玩家，并在控制台输出 ``<名字> 消息``。
    """
    from protocol.data_types import read_string
    from protocol.text import player_name, translate
    message, _ = read_string(payload, 0)
    message = message.strip()
    if not message:
        return
    if len(message) > MAX_CHAT_LENGTH or not _is_legal_chat(message):
        await conn.disconnect(translate("multiplayer.disconnect.illegal_characters"))
        return
    if message.startswith("/"):
        await execute_server_command(server, message[1:], source_conn=conn)
        return

    # Plugin hook: allow plugins to cancel or modify chat
    from mods.bridge import hook_player_chat
    if not hook_player_chat(server, conn, message):
        return  # Cancelled by a plugin

    logging.getLogger("minecraft.chat").info(f"<{conn.username}> {message}")
    server.broadcast_system_message(
        translate("chat.type.text", player_name(conn), {"text": message}))


async def _handle_chat_command(conn: Connection, payload: bytes, server):
    """处理 Chat Command (0x05/0x06)。"""
    from protocol.data_types import read_string
    offset = 0
    command, offset = read_string(payload, offset)

    # Plugin hook: allow plugins to intercept commands
    from plugins.bridge import hook_player_command
    if not hook_player_command(server, conn, command):
        return  # Cancelled by a plugin

    logging.getLogger("minecraft.command").info(
        f"{conn.username} issued server command: /{command}")
    await execute_server_command(server, command, source_conn=conn)


GAMEMODE_IDS = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}

# Player Info Update action bits (1.19.3+)
INFO_ADD_PLAYER = 0x01
INFO_INIT_CHAT = 0x02
INFO_GAMEMODE = 0x04
INFO_LISTED = 0x08
INFO_LATENCY = 0x10
INFO_DISPLAY_NAME = 0x20


def _player_latency(conn: Connection) -> int:
    rtt = getattr(conn, "keepalive_rtt_ms", None)
    return int(rtt) if rtt is not None else 0


def build_player_info_update(conn: Connection, actions: int | None = None) -> bytes:
    """
    构建 Player Info Update 数据包负载。

    默认动作: Add Player + Update Game Mode + Update Listed + Update Latency，
    与原版服务端在玩家加入时发送的内容一致 (Tab 列表显示延迟和游戏模式)。
    """
    if actions is None:
        actions = INFO_ADD_PLAYER | INFO_GAMEMODE | INFO_LISTED | INFO_LATENCY

    payload = bytearray()
    payload.append(actions)
    payload.extend(write_varint(1))          # 玩家数量
    payload.extend(write_uuid(conn.uuid))

    if actions & INFO_ADD_PLAYER:
        payload.extend(write_string(conn.username))
        properties = getattr(conn, "profile_properties", None) or []
        payload.extend(write_varint(len(properties)))
        for prop in properties:
            payload.extend(write_string(prop.get("name", "")))
            payload.extend(write_string(prop.get("value", "")))
            signature = prop.get("signature")
            payload.extend(write_boolean(signature is not None))
            if signature is not None:
                payload.extend(write_string(signature))
    if actions & INFO_GAMEMODE:
        payload.extend(write_varint(GAMEMODE_IDS.get(getattr(conn, "gamemode", "survival"), 0)))
    if actions & INFO_LISTED:
        payload.extend(write_boolean(True))
    if actions & INFO_LATENCY:
        payload.extend(write_varint(_player_latency(conn)))

    return bytes(payload)


def build_player_info_remove(conn: Connection) -> bytes:
    """构建 Player Info Remove 数据包负载 (0x3D)。"""
    payload = bytearray()
    payload.extend(write_varint(1))          # 玩家数量
    payload.extend(write_uuid(conn.uuid))    # 玩家 UUID
    return bytes(payload)


async def execute_server_command(server, command: str,
                                 source_conn: Connection | None = None) -> bool:
    """
    执行玩家或控制台命令。

    所有命令通过 CommandManager 框架分发，不再使用旧的 if-elif 链。
    CommandManager 处理:
      - 命令名解析与别名映射
      - 权限检查
      - 参数解析
      - 命令执行
      - 未知命令反馈
      - 已识别但不支持命令的反馈

    返回:
        True 表示识别并处理了命令
        False 表示命令为空
    """
    command = command.strip()
    if not command:
        return False

    # Let Java Bukkit/Paper plugins handle matching commands first.
    java_bridge = getattr(server, 'java_plugin_bridge', None)
    if java_bridge is not None:
        try:
            if java_bridge.dispatch_command(command):
                if source_conn is not None:
                    await send_system_message(
                        source_conn,
                        f"[PyMC] 已转交 Java 插件命令: /{command.split()[0]}"
                    )
                return True
        except Exception as e:
            logger.debug(f"Java plugin command bridge failed: {e}")

    # All commands go through the CommandManager framework
    if hasattr(server, 'command_manager') and server.command_manager is not None:
        result = await server.command_manager.execute(source_conn, command)
        return True

    # Fallback if command_manager not initialized (should not happen in normal operation)
    cmd_name = command.split()[0].lower() if command else ""
    if source_conn is not None:
        await send_system_message(source_conn, f"[PyMC] 命令系统未初始化: /{cmd_name}")
    else:
        logger.warning(f"[PyMC] 命令系统未初始化: /{cmd_name}")
    return False
