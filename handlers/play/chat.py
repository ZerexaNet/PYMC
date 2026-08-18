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

import asyncio
import json
import logging
import math

from protocol.data_types import (
    write_varint, write_string, write_boolean,
    write_uuid,
)
from protocol.nbt import encode_nbt
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


def build_system_message_payload(message: str | dict) -> bytes:
    """构建 1.21.1 system_chat 负载。"""
    if isinstance(message, dict):
        component = message
    else:
        component = {"text": message, "color": "gray"}

    payload = bytearray()
    payload.extend(encode_nbt(component, with_type=True))
    payload.extend(write_boolean(False))  # overlay
    return bytes(payload)


async def send_system_message(conn: Connection, text: str):
    """发送系统聊天消息给单个玩家，使用版本兼容的方式。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_system_chat(conn, text)
    else:
        # Fallback for native version
        await conn.send_packet(0x6C, build_system_message_payload(text))


async def _handle_chat_message(conn: Connection, payload: bytes, server):
    """
    处理 Chat Message (0x07)。
    在 1.21.1 中，聊天消息使用签名系统，但离线模式下我们简化处理。
    """
    from protocol.data_types import read_string
    offset = 0
    message, offset = read_string(payload, offset)

    # Plugin hook: allow plugins to cancel or modify chat
    from mods.bridge import hook_player_chat
    if not hook_player_chat(server, conn, message):
        return  # Cancelled by a plugin

    logger.info(f"<{conn.username}> {message}")

    chat_component = {
        "translate": "chat.type.text",
        "with": [
            {"text": conn.username, "color": "yellow"},
            {"text": message}
        ]
    }
    # Use version-aware broadcast for chat messages
    server.broadcast_system_message(json.dumps(chat_component, ensure_ascii=False))


async def _handle_chat_command(conn: Connection, payload: bytes, server):
    """处理 Chat Command (0x05/0x06)。"""
    from protocol.data_types import read_string
    offset = 0
    command, offset = read_string(payload, offset)

    # Plugin hook: allow plugins to intercept commands
    from plugins.bridge import hook_player_command
    if not hook_player_command(server, conn, command):
        return  # Cancelled by a plugin

    logger.info(f"{conn.username} 执行命令: /{command}")
    await execute_server_command(server, command, source_conn=conn)


def build_player_info_update(conn: Connection) -> bytes:
    """
    构建 Player Info Update 数据包负载 (0x3E)。
    Action: Add Player + Listed
    """
    payload = bytearray()

    # Actions BitSet: 0x01 (Add Player) | 0x08 (Update Listed)
    actions = 0x01 | 0x08
    payload.append(actions)

    # 玩家数量
    payload.extend(write_varint(1))

    # 玩家 UUID
    payload.extend(write_uuid(conn.uuid))

    # --- Action: Add Player ---
    payload.extend(write_string(conn.username))  # 名称
    payload.extend(write_varint(0))              # 属性数量 = 0

    # --- Action: Update Listed ---
    payload.extend(write_boolean(True))          # 是否在列表中

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
