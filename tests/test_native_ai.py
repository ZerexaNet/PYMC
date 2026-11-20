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


    def test_batch_gives_the_same_decisions_as_single_requests(self):
        import copy
        import random
        rng = random.Random(3)
        players = [DummyPlayer(f"P{i}", rng.uniform(-12, 12), 64.0, rng.uniform(-12, 12)) for i in range(3)]
        server = DummyServer(players)
        kinds = ["zombie", "skeleton", "pig", "cow", "creeper", "spider"]
        mobs = []
        for i in range(24):
            mob = MobEntity(500 + i, rng.uniform(-12, 12), 64.0, rng.uniform(-12, 12),
                            mob_type=kinds[i % len(kinds)])
            mob.age_ticks = 40 + i
            mobs.append(mob)
        singles = [copy.deepcopy(m) for m in mobs]
        batch = copy.deepcopy(mobs)

        ai_single = NativeMobAiEngine()
        ai_batch = NativeMobAiEngine()
        try:
            for mob in singles:
                self.assertTrue(ai_single.tick_mob(mob, server))
            done = ai_batch.tick_batch(batch, server)
            self.assertEqual(len(done), len(batch))
            for a, b in zip(singles, batch):
                self.assertEqual((a.vx, a.vz, a.yaw, a.pitch, a.wander_cooldown, a.aggressive_ticks, a.look_time,
                                  a.target_x, a.target_z, a.target_username),
                                 (b.vx, b.vz, b.yaw, b.pitch, b.wander_cooldown, b.aggressive_ticks, b.look_time,
                                  b.target_x, b.target_z, b.target_username))
        finally:
            ai_single.shutdown()
            ai_batch.shutdown()


if __name__ == "__main__":
    unittest.main()
