import unittest
from types import SimpleNamespace

from handlers.play import _handle_click_container
from protocol.data_types import write_varint, write_short, write_byte
from world.block_behavior import ContainerData, ContainerManager, container_manager
from world.entities import EntityManager
from world.inventory import ItemStack, PlayerInventory, encode_slot_entry


class FakeConnection(SimpleNamespace):
    async def send_packet(self, packet_id, payload=b""):
        self.sent_packets.append((packet_id, payload))


def click_payload(slot, button=0, state_id=0, mode=0, changed_slots=None):
    changed_slots = changed_slots or []
    return b"".join((
        write_varint(1),
        write_varint(state_id),
        write_short(slot),
        write_byte(button),
        write_varint(mode),
        write_varint(len(changed_slots)),
        *[
            write_short(s) + encode_slot_entry(None)
            for s in changed_slots
        ],
        encode_slot_entry(None),
    ))


class ContainerClickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        container_manager.containers.clear()
        self.container = container_manager.create_container(0, 64, 0, "chest")

    def tearDown(self):
        container_manager.containers.clear()

    def make_connection(self, window_id=1, open_type="block"):
        conn = FakeConnection(
            protocol_version=767,
            inventory_obj=PlayerInventory(),
            inventory_state_id=0,
            sent_packets=[],
            x=0.0, y=64.0, z=0.0, yaw=0.0,
            entity_id=1,
            _open_window_id=window_id,
            _open_container_pos=(0, 64, 0),
            _open_container_type=open_type,
        )
        return conn

    async def test_shift_click_moves_container_stack_to_player(self):
        self.container.items[0] = ItemStack("minecraft:diamond", 5)
        conn = self.make_connection()

        await _handle_click_container(conn, click_payload(0, mode=1), None)

        self.assertIsNone(self.container.items[0])
        self.assertEqual(conn.inventory_obj.count_item("minecraft:diamond"), 5)

    async def test_shift_click_moves_player_stack_into_container(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(9, ItemStack("minecraft:iron_ingot", 7))
        # Window slot 27 is the first main-inventory slot (index 9).
        await _handle_click_container(conn, click_payload(27, mode=1), None)

        self.assertEqual(conn.inventory_obj.get_slot(9), None)
        self.assertEqual(self.container.items[0], ItemStack("minecraft:iron_ingot", 7))

    async def test_number_key_swaps_hotbar_and_container_slot(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(3, ItemStack("minecraft:stone", 12))
        self.container.items[0] = ItemStack("minecraft:oak_log", 4)

        await _handle_click_container(conn, click_payload(0, button=3, mode=2), None)

        self.assertEqual(self.container.items[0], ItemStack("minecraft:stone", 12))
        self.assertEqual(conn.inventory_obj.get_slot(3), ItemStack("minecraft:oak_log", 4))

    async def test_left_drag_distributes_cursor_evenly(self):
        conn = self.make_connection()
        conn.inventory_obj.carried_item = ItemStack("minecraft:dirt", 5)

        await _handle_click_container(
            conn, click_payload(-999, button=0, mode=5, changed_slots=[0, 1]), None
        )
        await _handle_click_container(
            conn, click_payload(-999, button=2, state_id=0,
                                mode=5, changed_slots=[0, 1]), None
        )

        self.assertEqual(self.container.items[0], ItemStack("minecraft:dirt", 3))
        self.assertEqual(self.container.items[1], ItemStack("minecraft:dirt", 2))
        self.assertIsNone(conn.inventory_obj.carried_item)

    async def test_right_drag_places_one_item_per_slot(self):
        conn = self.make_connection()
        conn.inventory_obj.carried_item = ItemStack("minecraft:stone", 3)

        await _handle_click_container(
            conn, click_payload(-999, button=4, mode=5, changed_slots=[0]), None
        )
        await _handle_click_container(
            conn, click_payload(-999, button=6, state_id=0,
                                mode=5, changed_slots=[0, 1, 2]), None
        )

        self.assertEqual(self.container.items[0], ItemStack("minecraft:stone", 1))
        self.assertEqual(self.container.items[1], ItemStack("minecraft:stone", 1))
        self.assertEqual(self.container.items[2], ItemStack("minecraft:stone", 1))
        self.assertIsNone(conn.inventory_obj.carried_item)

    async def test_drop_mode_removes_stack_and_spawns_entity(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(9, ItemStack("minecraft:cobblestone", 8))
        server = SimpleNamespace()
        next_id = iter(range(2, 1000))
        server.get_next_entity_id = lambda: next(next_id)
        server.entity_manager = EntityManager(server)

        await _handle_click_container(conn, click_payload(27, button=1, mode=4), server)

        self.assertIsNone(conn.inventory_obj.get_slot(9))
        self.assertTrue(any(
            entity.kind == "item" and entity.metadata.get("item_name") == "minecraft:cobblestone"
            for entity in server.entity_manager.list_entities()
        ))


class ContainerPersistenceTests(unittest.TestCase):
    def test_container_data_round_trip(self):
        data = ContainerData(type="chest")
        data.items[0] = ItemStack("minecraft:diamond", 7, nbt={"tag": "x"})
        data.items[1] = ItemStack("minecraft:stone", 3)
        data.burn_time = 4

        restored = ContainerData.from_dict(data.to_dict())

        self.assertEqual(restored.type, "chest")
        self.assertEqual(restored.items[0], data.items[0])
        self.assertEqual(restored.items[0].nbt, {"tag": "x"})
        self.assertEqual(restored.items[1], data.items[1])
        self.assertEqual(restored.burn_time, 4)

    def test_manager_persistence_file_round_trip(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manager = ContainerManager()
            manager.create_container(1, 2, 3, "chest").items[2] = ItemStack("minecraft:apple", 5)
            manager.create_container(-4, 64, 8, "dispenser").items[0] = ItemStack("minecraft:arrow", 2)

            manager.save(tmp)
            restored = ContainerManager()
            self.assertTrue(restored.load(tmp))

            self.assertEqual(restored.get_container(1, 2, 3).items[2], ItemStack("minecraft:apple", 5))
            self.assertEqual(restored.get_container(-4, 64, 8).items[0], ItemStack("minecraft:arrow", 2))


if __name__ == "__main__":
    unittest.main()
