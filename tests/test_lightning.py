import unittest
from types import SimpleNamespace

from network.server import MinecraftServer
from world.entities import LightningBoltEntity, MobEntity


class LightningEntityTests(unittest.TestCase):
    def test_expires_after_lifetime(self):
        bolt = LightningBoltEntity(entity_id=1, x=0.0, y=64.0, z=0.0)
        server = SimpleNamespace()
        for _ in range(4):
            bolt.tick(server)
        self.assertFalse(bolt.alive)

    def test_kind_maps_to_verified_type_id(self):
        from handlers.play.entities import ENTITY_TYPE_IDS
        bolt = LightningBoltEntity(entity_id=1, x=0.0, y=64.0, z=0.0)
        self.assertEqual(ENTITY_TYPE_IDS[bolt.kind], 64)


class FakeEntityManager:
    def __init__(self):
        self.entities = {}
        self._next = 100

    def create_lightning(self, x, y, z):
        self._next += 1
        bolt = LightningBoltEntity(self._next, x, y, z)
        self.entities[bolt.entity_id] = bolt
        return bolt

    def list_entities(self):
        return list(self.entities.values())


class FakePlayer:
    def __init__(self, x=0.0, y=64.0, z=0.0, gamemode="survival"):
        self.x, self.y, self.z = x, y, z
        self.gamemode = gamemode
        self.username = "Steve"
        self.health = 20.0
        self.damage_cooldown_ticks = 0
        self.last_damage_reason = ""
        self.alive = True


class LightningStrikeTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_strike_when_not_thunder(self):
        server = SimpleNamespace(
            weather="rain",
            entity_manager=FakeEntityManager(),
            get_online_players=lambda: [FakePlayer()],
        )
        await MinecraftServer._tick_lightning(server)
        self.assertEqual(server.entity_manager.entities, {})

    async def test_strike_spawns_bolt_and_damages_nearby(self):
        from unittest.mock import patch, AsyncMock
        player = FakePlayer()
        manager = FakeEntityManager()
        server = SimpleNamespace(
            weather="thunder",
            entity_manager=manager,
            get_online_players=lambda: [player],
        )
        with patch("handlers.play.broadcast_entity_spawn", new=AsyncMock()), \
             patch("handlers.play._damage_player", new=AsyncMock()) as dmg, \
             patch("handlers.play._send_update_health", new=AsyncMock()):
            await MinecraftServer._tick_lightning(server)

        bolts = [e for e in manager.entities.values()
                 if isinstance(e, LightningBoltEntity)]
        self.assertEqual(len(bolts), 1)

        # 落点在玩家 24 格范围内
        bolt = bolts[0]
        self.assertLessEqual(abs(bolt.x - player.x), 24.0)
        self.assertLessEqual(abs(bolt.z - player.z), 24.0)


if __name__ == "__main__":
    unittest.main()
