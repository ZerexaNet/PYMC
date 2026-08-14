import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from network.server import MinecraftServer
from world.fluids import FluidSystem, _get_fluid_level, _get_water_state


class FluidTests(unittest.TestCase):
    def test_falling_water_is_not_encoded_as_source(self):
        falling = _get_water_state(0, falling=True)
        self.assertNotEqual(falling, _get_water_state(0))
        self.assertEqual(_get_fluid_level(falling), 8)


class FluidBroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_tick_broadcasts_final_state_once_per_position(self):
        fluid_system = SimpleNamespace(tick=lambda: None)
        server = SimpleNamespace(
            fluid_system=fluid_system,
            _fluid_updates=[(1, 2, 3, 4), (1, 2, 3, 5), (6, 7, 8, 9)],
        )
        broadcaster = AsyncMock()
        with patch("handlers.play._broadcast_block_change", broadcaster):
            await MinecraftServer._tick_fluids(server, 1)

        self.assertEqual(server._fluid_updates, [])
        self.assertEqual(broadcaster.await_count, 2)
        broadcaster.assert_any_await(server, 1, 2, 3, 5)
        broadcaster.assert_any_await(server, 6, 7, 8, 9)


if __name__ == "__main__":
    unittest.main()