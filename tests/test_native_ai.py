import unittest
from dataclasses import dataclass

from world.ai_native import NativeMobAiEngine, _find_native_binary
from world.entities import MobEntity


@dataclass
class DummyPlayer:
    username: str
    x: float
    y: float
    z: float
    gamemode: str = "survival"


class DummyServer:
    def __init__(self, players):
        self._players = players

    def get_online_players(self):
        return self._players


class NativeAiTests(unittest.TestCase):
    def setUp(self):
        if _find_native_binary() is None:
            self.skipTest("native mob_ai binary is not available")

    def test_zombie_chases_attackable_player(self):
        ai = NativeMobAiEngine()
        try:
            mob = MobEntity(77, 0.0, 64.0, 0.0, mob_type="zombie")
            mob.age_ticks = 40
            server = DummyServer([DummyPlayer("Steve", 6.0, 64.0, 0.0)])

            self.assertTrue(ai.tick_mob(mob, server))
            self.assertGreater(mob.vx, 0.0)
            self.assertAlmostEqual(mob.vz, 0.0, places=6)
            self.assertEqual(mob.target_username, "Steve")
            self.assertGreater(mob.aggressive_ticks, 0)
        finally:
            ai.shutdown()

    def test_skeleton_keeps_distance_from_close_player(self):
        ai = NativeMobAiEngine()
        try:
            mob = MobEntity(78, 0.0, 64.0, 0.0, mob_type="skeleton")
            mob.age_ticks = 40
            server = DummyServer([DummyPlayer("Alex", 4.0, 64.0, 0.0)])

            self.assertTrue(ai.tick_mob(mob, server))
            self.assertLess(mob.vx, 0.0)
            self.assertEqual(mob.target_username, "Alex")
            self.assertGreater(mob.aggressive_ticks, 0)
        finally:
            ai.shutdown()


if __name__ == "__main__":
    unittest.main()
