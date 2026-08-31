import unittest
from types import SimpleNamespace

from handlers.play.combat import (
    INTERACT_TYPE_ATTACK,
    damage_mob,
    get_attack_damage,
    parse_interact,
    WEAPON_DAMAGE,
)
from protocol.data_types import write_varint
from world.entities import MOB_PROFILES, MobEntity


def build_interact_packet(entity_id: int, action_type: int) -> bytes:
    payload = bytearray()
    payload.extend(write_varint(entity_id))
    payload.extend(write_varint(action_type))
    payload.extend(b"\x00")  # sneaking = false
    return bytes(payload)


class FakeEntityManager:
    def __init__(self):
        self.entities = {}
        self.removed = []
        self.created_items = []
        self.created_orbs = []
        self._next_id = 1000

    def add(self, entity):
        self.entities[entity.entity_id] = entity

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def remove_entity(self, entity_id):
        self.removed.append(entity_id)
        return self.entities.pop(entity_id, None)

    def create_item(self, x, y, z, item_name, count):
        self.created_items.append((item_name, count))
        return SimpleNamespace(pickup_delay=0)

    def create_experience_orb(self, x, y, z, count):
        self.created_orbs.append(count)


class ParseInteractTests(unittest.TestCase):
    def test_parse_attack(self):
        payload = build_interact_packet(42, INTERACT_TYPE_ATTACK)
        self.assertEqual(parse_interact(payload), (42, INTERACT_TYPE_ATTACK))

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(parse_interact(b""))
        self.assertIsNone(parse_interact(b"\xff"))


class WeaponDamageTests(unittest.TestCase):
    def test_fist_damage(self):
        conn = SimpleNamespace(inventory_obj=None, selected_hotbar_slot=0)
        self.assertEqual(get_attack_damage(conn), 1.0)

    def test_sword_damage(self):
        held = SimpleNamespace(item_id="minecraft:diamond_sword", is_empty=False)
        inventory = SimpleNamespace(get_held_item_from_slot=lambda slot: held)
        conn = SimpleNamespace(inventory_obj=inventory, selected_hotbar_slot=0)
        self.assertEqual(
            get_attack_damage(conn), WEAPON_DAMAGE["minecraft:diamond_sword"])


class DamageMobTests(unittest.TestCase):
    def make_mob(self, mob_type="zombie"):
        return MobEntity(entity_id=7, x=0.0, y=64.0, z=0.0, mob_type=mob_type)

    def test_non_lethal_hit(self):
        manager = FakeEntityManager()
        mob = self.make_mob()
        manager.add(mob)
        server = SimpleNamespace(entity_manager=manager)
        killed = damage_mob(server, mob, 5.0)
        self.assertFalse(killed)
        self.assertEqual(mob.health, MOB_PROFILES["zombie"]["health"] - 5.0)
        self.assertEqual(manager.removed, [])

    def test_kill_spawns_drops_and_xp(self):
        manager = FakeEntityManager()
        mob = self.make_mob("cow")
        manager.add(mob)
        server = SimpleNamespace(entity_manager=manager)
        killed = damage_mob(server, mob, 999.0)
        self.assertTrue(killed)
        self.assertEqual(manager.removed, [7])
        item_names = [name for name, _ in manager.created_items]
        self.assertIn("minecraft:beef", item_names)
        self.assertTrue(all(c >= 1 for _, c in manager.created_items))
        self.assertEqual(len(manager.created_orbs), 1)
        self.assertTrue(1 <= manager.created_orbs[0] <= 3)

    def test_zero_roll_drops_may_be_empty(self):
        manager = FakeEntityManager()
        mob = self.make_mob("zombie")  # rotten_flesh 0-2
        manager.add(mob)
        server = SimpleNamespace(entity_manager=manager)
        damage_mob(server, mob, 999.0)
        for name, count in manager.created_items:
            self.assertEqual(name, "minecraft:rotten_flesh")
            self.assertGreaterEqual(count, 1)

    def test_mob_profiles_have_drops_and_xp(self):
        for mob_type, profile in MOB_PROFILES.items():
            self.assertIn("drops", profile, mob_type)
            self.assertIn("xp", profile, mob_type)


if __name__ == "__main__":
    unittest.main()
