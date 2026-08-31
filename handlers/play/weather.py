# ============================================================
# PyMC - 天气客户端同步
# 通过 Game Event 数据包向客户端同步天气变化
# ============================================================

"""
天气状态同步。

Minecraft 客户端通过 Game Event 数据包感知天气:
  - reason 1: End Raining (停止下雨)
  - reason 2: Begin Raining (开始下雨)
  - reason 7: Change Rain Strength (雨强度 0.0-1.0)
  - reason 8: Change Thunder Strength (雷暴强度 0.0-1.0)

入服时发送当前天气状态，天气变化时向全体在线玩家广播。
"""

import logging

from protocol.data_types import write_ubyte, write_float
from protocol.packet_map import get_clientbound_packet
from network.connection import Connection

logger = logging.getLogger("PyMC.天气")

GAME_EVENT_END_RAINING = 1
GAME_EVENT_BEGIN_RAINING = 2
GAME_EVENT_RAIN_LEVEL = 7
GAME_EVENT_THUNDER_LEVEL = 8

_RAINING_STATES = ("rain", "thunder")


def build_game_event_payload(event: int, value: float) -> bytes:
    """构建 Game Event 数据包负载 (Unsigned Byte reason + Float value)。"""
    payload = bytearray()
    payload.extend(write_ubyte(event))
    payload.extend(write_float(value))
    return bytes(payload)


def rain_strength(weather: str) -> float:
    """雨强度: 下雨或雷暴时为 1.0。"""
    return 1.0 if weather in _RAINING_STATES else 0.0


def thunder_strength(weather: str) -> float:
    """雷暴强度: 仅雷暴时为 1.0。"""
    return 1.0 if weather == "thunder" else 0.0


async def _send_game_event(conn: Connection, event: int, value: float):
    """按客户端协议版本发送 Game Event 数据包。"""
    if conn.version_handler is not None:
        await conn.version_handler.send_game_event(conn, event, value)
        return
    pid = get_clientbound_packet(conn.protocol_version, "game_event")
    if pid is not None:
        await conn.send_packet(pid, build_game_event_payload(event, value))


async def send_weather_state(conn: Connection, server):
    """
    入服时向玩家同步当前天气。

    晴天无需发送任何数据包 (客户端默认晴天)。
    """
    weather = server.weather
    if weather not in _RAINING_STATES:
        return
    await _send_game_event(conn, GAME_EVENT_BEGIN_RAINING, 0.0)
    await _send_game_event(conn, GAME_EVENT_RAIN_LEVEL, rain_strength(weather))
    await _send_game_event(conn, GAME_EVENT_THUNDER_LEVEL, thunder_strength(weather))


async def broadcast_weather_change(server, old_weather: str, new_weather: str):
    """
    向全体在线玩家广播天气变化。

    - 晴 -> 雨/雷暴: Begin Raining + 强度
    - 雨/雷暴 -> 晴: End Raining + 强度归零
    - 雨 <-> 雷暴: 仅更新强度 (保持下雨状态)
    """
    if old_weather == new_weather:
        return

    was_raining = old_weather in _RAINING_STATES
    is_raining = new_weather in _RAINING_STATES

    for conn in server.get_online_players():
        if is_raining and not was_raining:
            await _send_game_event(conn, GAME_EVENT_BEGIN_RAINING, 0.0)
        elif was_raining and not is_raining:
            await _send_game_event(conn, GAME_EVENT_END_RAINING, 0.0)
        await _send_game_event(conn, GAME_EVENT_RAIN_LEVEL, rain_strength(new_weather))
        await _send_game_event(conn, GAME_EVENT_THUNDER_LEVEL, thunder_strength(new_weather))

    logger.info(f"天气已变更: {old_weather} -> {new_weather}")
