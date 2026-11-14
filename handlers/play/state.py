# ============================================================
# PyMC - 玩家状态同步
# 游戏模式、能力、难度、权限等级等客户端状态数据包
# ============================================================

"""
玩家状态同步辅助函数 (1.21.1 原生路径)。

  - send_abilities:        Player Abilities (飞行/无敌/创造)
  - send_difficulty:       Change Difficulty
  - send_op_level:         Entity Event 24-28 (客户端据此显示命令补全/F3+F4)
  - send_held_slot:        Set Held Item
  - send_ticking_state:    Set Ticking State + Step Tick
  - set_player_gamemode:   切换游戏模式并同步给所有相关客户端
"""

from __future__ import annotations

import logging

from protocol.data_types import (
    write_boolean, write_byte, write_float, write_int, write_ubyte, write_varint,
)
from protocol.packet_map import get_clientbound_packet

logger = logging.getLogger("PyMC.游戏")

GAMEMODE_IDS = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
GAMEMODE_NAMES = {v: k for k, v in GAMEMODE_IDS.items()}
DIFFICULTY_IDS = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}

ABILITY_INVULNERABLE = 0x01
ABILITY_FLYING = 0x02
ABILITY_ALLOW_FLYING = 0x04
ABILITY_CREATIVE = 0x08


def normalize_gamemode(value, default: str = "survival") -> str:
    """Accept names, vanilla abbreviations and numeric ids."""
    if isinstance(value, int):
        return GAMEMODE_NAMES.get(value, default)
    text = str(value or "").strip().lower()
    if text in GAMEMODE_IDS:
        return text
    aliases = {"s": "survival", "c": "creative", "a": "adventure", "sp": "spectator",
               "0": "survival", "1": "creative", "2": "adventure", "3": "spectator"}
    return aliases.get(text, default)


def ability_flags(conn) -> int:
    mode = getattr(conn, "gamemode", "survival")
    flags = 0
    if mode == "creative":
        flags = ABILITY_INVULNERABLE | ABILITY_ALLOW_FLYING | ABILITY_CREATIVE
    elif mode == "spectator":
        flags = ABILITY_INVULNERABLE | ABILITY_ALLOW_FLYING | ABILITY_FLYING
    if getattr(conn, "flying", False) and flags & ABILITY_ALLOW_FLYING:
        flags |= ABILITY_FLYING
    return flags


async def _send(conn, name: str, payload: bytes) -> bool:
    pid = get_clientbound_packet(conn.protocol_version, name)
    if pid is None:
        return False
    await conn.send_packet(pid, payload)
    return True


async def send_abilities(conn):
    payload = bytearray()
    payload.extend(write_byte(ability_flags(conn)))
    payload.extend(write_float(0.05))   # flying speed
    payload.extend(write_float(0.1))    # FOV modifier (walk speed)
    await _send(conn, "player_abilities", bytes(payload))


async def send_difficulty(conn, server):
    difficulty = DIFFICULTY_IDS.get(str(server.config.get("difficulty", "normal")).lower(), 2)
    payload = write_ubyte(difficulty) + write_boolean(False)
    await _send(conn, "difficulty", payload)


def op_level(server, conn) -> int:
    """Vanilla permission level (0-4) of a player."""
    permissions = getattr(server, "permissions", None)
    if permissions is None:
        return 0
    getter = getattr(permissions, "get_op_level", None)
    if getter is not None:
        return int(getter(conn.username))
    return 4 if permissions.has_permission(conn.username, "command.*") else 0


async def send_op_level(conn, server):
    """Entity Event 24 + level: tells the client its permission level."""
    level = max(0, min(4, op_level(server, conn)))
    payload = write_int(conn.entity_id) + write_byte(24 + level)
    await _send(conn, "entity_status", payload)


async def send_held_slot(conn):
    await _send(conn, "held_item_change", write_byte(int(getattr(conn, "selected_hotbar_slot", 0))))


async def send_ticking_state(conn, tick_rate: float = 20.0, frozen: bool = False):
    await _send(conn, "set_ticking_state", write_float(tick_rate) + write_boolean(frozen))
    await _send(conn, "step_tick", write_varint(0))


async def send_game_event(conn, event: int, value: float = 0.0):
    await _send(conn, "game_event", write_ubyte(event) + write_float(value))


async def send_simulation_distance(conn, distance: int):
    await _send(conn, "simulation_distance", write_varint(distance))


async def set_player_gamemode(server, conn, mode: str) -> bool:
    """
    切换玩家游戏模式并同步:
      - Game Event 3 (Change game mode) 给玩家本人
      - Player Abilities 给玩家本人
      - Player Info Update (Update Game Mode) 给所有人 (Tab 列表/旁观者显示)
    返回游戏模式是否发生变化。
    """
    mode = normalize_gamemode(mode, getattr(conn, "gamemode", "survival"))
    changed = getattr(conn, "gamemode", None) != mode
    conn.gamemode = mode
    if mode not in ("creative", "spectator"):
        conn.flying = False
    elif mode == "spectator":
        conn.flying = True

    await send_game_event(conn, 3, float(GAMEMODE_IDS[mode]))
    await send_abilities(conn)

    from handlers.play.chat import build_player_info_update, INFO_GAMEMODE
    info = build_player_info_update(conn, INFO_GAMEMODE)
    for other in server.get_online_players():
        pid = get_clientbound_packet(other.protocol_version, "player_info")
        if pid is not None and other.protocol_version >= 761:
            await other.send_packet(pid, info)
    return changed
