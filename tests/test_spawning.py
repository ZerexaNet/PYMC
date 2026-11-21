"""Natural spawning and despawning: the light and ground rules and the cycle."""

import types
import unittest

from world import spawning as sp
from world.blocks import AIR, GRASS_BLOCK, STONE, WATER


def _passable(block_id):
    from world.entities import _is_passable
    return _is_passable(block_id)


class RuleTests(unittest.TestCase):

    def test_sky_darkness_by_time(self):
        self.assertEqual(sp.sky_darkness(6000), 0)
        self.assertEqual(sp.sky_darkness(18000), 11)
        self.assertEqual(sp.sky_darkness(24000 + 18000), 11)     # the day wraps

    def test_brightness_takes_the_larger(self):
        self.assertEqual(sp.brightness(3, 15, 0), 15)
        self.assertEqual(sp.brightness(3, 15, 11), 4)
        self.assertEqual(sp.brightness(9, 2, 11), 9)

    def test_hostile_needs_darkness(self):
        ok = lambda light, mob="zombie": sp.can_spawn("hostile", mob, AIR, AIR, STONE, light, 0, 0, _passable)
        self.assertTrue(ok(0))
        self.assertTrue(ok(7))
        self.assertFalse(ok(8))
        self.assertFalse(ok(0, mob="pig"))

    def test_passive_needs_grass_and_light(self):
        ok = lambda ground, raw: sp.can_spawn("passive", "pig", AIR, AIR, ground, 0, 12, 0, _passable) if raw is None \
            else sp.can_spawn("passive", "pig", AIR, AIR, ground, 0, raw, 0, _passable)
        self.assertTrue(ok(GRASS_BLOCK, 9))
        self.assertFalse(ok(GRASS_BLOCK, 8))
        self.assertFalse(ok(STONE, 15))

    def test_never_in_liquid_or_without_ground(self):
        self.assertFalse(sp.can_spawn("hostile", "zombie", WATER, AIR, STONE, 0, 0, 0, _passable))
        self.assertFalse(sp.can_spawn("hostile", "zombie", AIR, AIR, AIR, 0, 0, 0, _passable))
        self.assertFalse(sp.can_spawn("hostile", "zombie", AIR, AIR, None, 0, 0, 0, _passable))


class FlatWorld:
    """Stone below y=63, grass at y=63, air above; the same chunk everywhere."""

    def __init__(self):
        self.chunk = [[[STONE] * 16 for _ in range(16)] if y < 127 else
                      ([[GRASS_BLOCK] * 16 for _ in range(16)] if y == 127 else
                       [[AIR] * 16 for _ in range(16)])
                      for y in range(384)]

    def get_block_at(self, x, y, z):
        if y < -64 or y >= 320:
            return None
        if y < 63:
            return STONE
        return GRASS_BLOCK if y == 63 else AIR

    def load_generated_chunk(self, cx, cz):
        return self.chunk


class _Manager:
    def __init__(self):
        self.created = []
        self.removed = []
        self.mobs = []

    def of_kind(self, kind):
        return list(self.mobs) if kind == "mob" else []

    def create_mob(self, x, y, z, mob_type="pig"):
        mob = types.SimpleNamespace(x=x, y=y, z=z, mob_type=mob_type, entity_id=len(self.created) + 1000,
                                    profile={"category": "hostile" if mob_type in sp.HOSTILE else "passive"})
        self.created.append(mob)
        self.mobs.append(mob)
        return mob

    def remove_entity(self, entity_id):
        self.removed.append(entity_id)
        self.mobs = [m for m in self.mobs if m.entity_id != entity_id]


def _server(world_time=6000, players=None, difficulty="easy"):
    world = FlatWorld()
    players = players if players is not None else [
        types.SimpleNamespace(x=0.5, y=64.0, z=0.5, gamemode="survival")]
    return types.SimpleNamespace(
        world_storage=world, get_block_at=world.get_block_at,
        get_online_players=lambda: players, world_time=world_time,
        config={"difficulty": difficulty, "spawn-monsters": True, "spawn-animals": True},
        entity_manager=_Manager(), next_entity_id=1,
    )


class CycleTests(unittest.TestCase):

    def run_cycles(self, server, cycles=30):
        for i in range(cycles):
            sp.run_spawning(server, sp.SPAWN_INTERVAL * (i + 1))

    def test_daytime_spawns_only_animals(self):
        server = _server(world_time=6000)
        self.run_cycles(server)
        kinds = {m.mob_type for m in server.entity_manager.created}
        self.assertTrue(kinds, "nothing spawned in daylight")
        self.assertTrue(kinds <= set(sp.PASSIVE), kinds)

    def test_night_spawns_hostile_mobs(self):
        server = _server(world_time=18000)
        self.run_cycles(server)
        kinds = {m.mob_type for m in server.entity_manager.created}
        self.assertTrue(kinds, "nothing spawned at night")
        self.assertTrue(kinds <= set(sp.HOSTILE) | set(sp.PASSIVE))
        self.assertTrue(kinds & set(sp.HOSTILE))

    def test_peaceful_has_no_hostile_mobs(self):
        server = _server(world_time=18000, difficulty="peaceful")
        self.run_cycles(server)
        self.assertFalse([m for m in server.entity_manager.created if m.mob_type in sp.HOSTILE])

    def test_nothing_spawns_within_24_blocks(self):
        server = _server(world_time=6000)
        self.run_cycles(server, cycles=40)
        for mob in server.entity_manager.created:
            self.assertGreaterEqual(((mob.x - 0.5) ** 2 + (mob.z - 0.5) ** 2) ** 0.5, sp.MIN_DISTANCE - 1)

    def test_caps_per_player(self):
        server = _server(world_time=6000)
        self.run_cycles(server, cycles=200)
        self.assertLessEqual(len(server.entity_manager.created), sp.PASSIVE_CAP)

    def test_spawn_turned_off_by_config(self):
        server = _server(world_time=6000)
        server.config["spawn-animals"] = False
        self.run_cycles(server)
        self.assertEqual(server.entity_manager.created, [])


class DespawnTests(unittest.TestCase):

    def test_far_mobs_are_removed_near_ones_kept(self):
        server = _server()
        manager = server.entity_manager
        far = manager.create_mob(500.0, 64.0, 500.0, mob_type="pig")
        near = manager.create_mob(3.0, 64.0, 3.0, mob_type="pig")
        sp.run_despawning(server, sp.DESPAWN_INTERVAL)
        self.assertIn(far.entity_id, manager.removed)
        self.assertNotIn(near.entity_id, manager.removed)

    def test_hostile_beyond_32_may_go_but_not_always(self):
        import random as _random
        removed_any = kept_any = False
        for seed in range(40):
            server = _server()
            server.entity_manager.create_mob(60.0, 64.0, 0.0, mob_type="zombie")
            sp.run_despawning(server, sp.DESPAWN_INTERVAL + seed * sp.DESPAWN_INTERVAL)
            if server.entity_manager.removed:
                removed_any = True
            else:
                kept_any = True
        self.assertTrue(removed_any and kept_any)


if __name__ == "__main__":
    unittest.main()
