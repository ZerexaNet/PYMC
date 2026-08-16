import unittest

from world.block_behavior import container_manager
from world.blocks import AIR
from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK
from world.entities import EntityManager
from world.inventory import ItemStack
from world.redstone import RedstoneEngine


class FakeServer:
    def __init__(self, *blocks):
        self.blocks = {(x, y, z): state for x, y, z, state in blocks}
        self.world_time = 6000
        self.players = []
        self._next_id = iter(range(10, 1000))

    def get_block_at(self, x, y, z):
        return self.blocks.get((x, y, z), AIR)

    def get_online_players(self):
        return self.players

    def get_next_entity_id(self):
        return next(self._next_id)


def make_engine(server):
    engine = RedstoneEngine(server)
    engine._native_engine = None
    engine._set_block_state = lambda x, y, z, state: server.blocks.__setitem__((x, y, z), state)
    return engine


class RedstoneCompletionTests(unittest.TestCase):
    def tearDown(self):
        container_manager.containers.clear()

    def test_note_block_interaction_cycles_pitch_and_queues_sound(self):
        server = FakeServer((0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:note_block"]))
        engine = make_engine(server)
        engine.register_component(0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:note_block"])
        engine.components[(0, 64, 0)].note = 24

        self.assertTrue(engine.on_player_interact(0, 64, 0, None))
        comp = engine.components[(0, 64, 0)]
        self.assertEqual(comp.note, 0)
        self.assertEqual(engine.drain_pending_effects(),
                         [("note", {"x": 0, "y": 64, "z": 0, "note": 0})])

        visual = STATE_ID_TO_BLOCK[engine._compute_visual_state(comp)]
        self.assertEqual(visual[1].get("note"), "0")

    def test_powered_tnt_detonates_after_fuse(self):
        server = FakeServer(
            (0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:tnt"]),
            (1, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:lever"]),
        )
        engine = make_engine(server)
        engine.register_component(0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:tnt"])
        engine.register_component(1, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:lever"])
        engine.components[(1, 64, 0)].lever_on = True
        engine._update_lever(engine.components[(1, 64, 0)])
        engine._calculate_power_levels()

        engine._activate_mechanical_blocks()
        tnt = engine.components[(0, 64, 0)]
        self.assertTrue(tnt.powered)
        self.assertEqual(tnt.fuse_ticks, 40)

        for _ in range(40):
            engine._activate_mechanical_blocks()

        self.assertEqual(server.blocks.get((0, 64, 0)), AIR)
        self.assertNotIn((0, 64, 0), engine.components)
        self.assertEqual(engine.drain_pending_effects(),
                         [("explosion", {"x": 0, "y": 64, "z": 0})])

    def test_dispenser_drops_first_item_on_rising_edge(self):
        server = FakeServer(
            (0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:dispenser"]),
            (1, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:lever"]),
        )
        server.entity_manager = EntityManager(server)
        engine = make_engine(server)

        container = container_manager.create_container(0, 64, 0, "dispenser")
        container.items[0] = ItemStack("minecraft:arrow", 3)

        engine.register_component(0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:dispenser"])
        engine.register_component(1, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:lever"])
        engine.components[(1, 64, 0)].lever_on = True
        engine._update_lever(engine.components[(1, 64, 0)])
        engine._calculate_power_levels()
        engine._activate_mechanical_blocks()

        self.assertEqual(container.items[0], ItemStack("minecraft:arrow", 2))
        items = [e for e in server.entity_manager.list_entities() if e.kind == "item"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metadata.get("item_name"), "minecraft:arrow")
        self.assertEqual(engine.drain_pending_effects(),
                         [("entity_spawn", {"entity_id": items[0].entity_id})])

    def test_comparator_reads_real_container_fill_level(self):
        server = FakeServer((0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:chest"]))
        engine = make_engine(server)
        engine.register_component(0, 64, 0, BLOCK_NAME_TO_DEFAULT_STATE["minecraft:chest"])

        container = container_manager.create_container(0, 64, 0, "chest")
        self.assertEqual(engine._read_container_signal(0, 64, 0), 0)

        container.items[0] = ItemStack("minecraft:stone", 64)
        self.assertEqual(engine._read_container_signal(0, 64, 0), 15)

        container.items[0].count = 32
        self.assertEqual(engine._read_container_signal(0, 64, 0), 8)


if __name__ == "__main__":
    unittest.main()
