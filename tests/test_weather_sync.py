import struct
import unittest
from types import SimpleNamespace

from handlers.play.weather import (
    GAME_EVENT_BEGIN_RAINING,
    GAME_EVENT_END_RAINING,
    GAME_EVENT_RAIN_LEVEL,
    GAME_EVENT_THUNDER_LEVEL,
    build_game_event_payload,
    broadcast_weather_change,
    rain_strength,
    send_weather_state,
    thunder_strength,
)
from network.managers.time import TimeManager
from network.server import MinecraftServer


class FakeConnection:
    """记录收到的 Game Event (event, value) 序列。"""

    def __init__(self, protocol_version=767):
        self.protocol_version = protocol_version
        self.version_handler = None
        self.events = []

    async def send_packet(self, packet_id, payload=b""):
        event = payload[0]
        (value,) = struct.unpack(">f", payload[1:5])
        self.events.append((packet_id, event, value))


def make_server(weather, conns):
    return SimpleNamespace(weather=weather, get_online_players=lambda: conns)


class GameEventPayloadTests(unittest.TestCase):
    def test_payload_layout(self):
        payload = build_game_event_payload(GAME_EVENT_BEGIN_RAINING, 1.0)
        self.assertEqual(payload[0], GAME_EVENT_BEGIN_RAINING)
        (value,) = struct.unpack(">f", payload[1:5])
        self.assertAlmostEqual(value, 1.0)
        self.assertEqual(len(payload), 5)

    def test_strength_helpers(self):
        self.assertEqual(rain_strength("clear"), 0.0)
        self.assertEqual(rain_strength("rain"), 1.0)
        self.assertEqual(rain_strength("thunder"), 1.0)
        self.assertEqual(thunder_strength("rain"), 0.0)
        self.assertEqual(thunder_strength("thunder"), 1.0)


class WeatherBroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_to_rain_begins_raining(self):
        conn = FakeConnection()
        server = make_server("rain", [conn])
        await broadcast_weather_change(server, "clear", "rain")
        events = [e for _, e, _ in conn.events]
        self.assertIn(GAME_EVENT_BEGIN_RAINING, events)
        self.assertNotIn(GAME_EVENT_END_RAINING, events)
        levels = dict((e, v) for _, e, v in conn.events)
        self.assertEqual(levels[GAME_EVENT_RAIN_LEVEL], 1.0)
        self.assertEqual(levels[GAME_EVENT_THUNDER_LEVEL], 0.0)

    async def test_rain_to_clear_ends_raining(self):
        conn = FakeConnection()
        server = make_server("clear", [conn])
        await broadcast_weather_change(server, "rain", "clear")
        events = [e for _, e, _ in conn.events]
        self.assertIn(GAME_EVENT_END_RAINING, events)
        self.assertNotIn(GAME_EVENT_BEGIN_RAINING, events)
        levels = dict((e, v) for _, e, v in conn.events)
        self.assertEqual(levels[GAME_EVENT_RAIN_LEVEL], 0.0)

    async def test_rain_to_thunder_keeps_rain_state(self):
        conn = FakeConnection()
        server = make_server("thunder", [conn])
        await broadcast_weather_change(server, "rain", "thunder")
        events = [e for _, e, _ in conn.events]
        self.assertNotIn(GAME_EVENT_BEGIN_RAINING, events)
        self.assertNotIn(GAME_EVENT_END_RAINING, events)
        levels = dict((e, v) for _, e, v in conn.events)
        self.assertEqual(levels[GAME_EVENT_THUNDER_LEVEL], 1.0)

    async def test_no_change_sends_nothing(self):
        conn = FakeConnection()
        server = make_server("rain", [conn])
        await broadcast_weather_change(server, "rain", "rain")
        self.assertEqual(conn.events, [])

    async def test_uses_version_mapped_packet_id(self):
        conn = FakeConnection(protocol_version=47)  # 1.8.9: game_event = 0x1B
        server = make_server("rain", [conn])
        await broadcast_weather_change(server, "clear", "rain")
        self.assertTrue(all(pid == 0x1B for pid, _, _ in conn.events))


class JoinWeatherStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_weather_sends_nothing_on_join(self):
        conn = FakeConnection()
        await send_weather_state(conn, make_server("clear", [conn]))
        self.assertEqual(conn.events, [])

    async def test_thunder_join_sends_state(self):
        conn = FakeConnection()
        await send_weather_state(conn, make_server("thunder", [conn]))
        events = [e for _, e, _ in conn.events]
        self.assertIn(GAME_EVENT_BEGIN_RAINING, events)
        levels = dict((e, v) for _, e, v in conn.events)
        self.assertEqual(levels[GAME_EVENT_RAIN_LEVEL], 1.0)
        self.assertEqual(levels[GAME_EVENT_THUNDER_LEVEL], 1.0)


class WeatherCycleGameruleTests(unittest.TestCase):
    def test_weather_duration_counts_down_by_default(self):
        mgr = TimeManager()
        mgr.set_weather("rain", duration=2)
        mgr.tick()
        self.assertEqual(mgr.weather, "rain")
        mgr.tick()
        self.assertEqual(mgr.weather, "clear")

    def test_do_weather_cycle_false_freezes_weather(self):
        mgr = TimeManager()
        mgr.do_weather_cycle = False
        mgr.set_weather("rain", duration=1)
        for _ in range(10):
            mgr.tick()
        self.assertEqual(mgr.weather, "rain")

    def test_serialize_roundtrip_keeps_weather_cycle_flag(self):
        mgr = TimeManager()
        mgr.do_weather_cycle = False
        mgr.set_weather("thunder", duration=100)
        restored = TimeManager.deserialize(mgr.serialize())
        self.assertFalse(restored.do_weather_cycle)
        self.assertEqual(restored.weather, "thunder")


class SetWeatherTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_weather_updates_duration_and_broadcasts(self):
        conn = FakeConnection()
        server = SimpleNamespace(
            weather="clear",
            _time_manager=TimeManager(),
            plugin_manager=None,
            get_online_players=lambda: [conn],
        )
        await MinecraftServer.set_weather(server, "rain", duration=1234)

        self.assertEqual(server.weather, "rain")
        self.assertEqual(server._time_manager._weather_duration, 1234)
        events = [e for _, e, _ in conn.events]
        self.assertIn(GAME_EVENT_BEGIN_RAINING, events)

    async def test_set_weather_noop_when_unchanged(self):
        conn = FakeConnection()
        server = SimpleNamespace(
            weather="clear",
            _time_manager=TimeManager(),
            plugin_manager=None,
            get_online_players=lambda: [conn],
        )
        await MinecraftServer.set_weather(server, "clear", duration=100)
        self.assertEqual(conn.events, [])


if __name__ == "__main__":
    unittest.main()
