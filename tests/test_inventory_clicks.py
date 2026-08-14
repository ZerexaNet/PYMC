import unittest
from types import SimpleNamespace

from handlers.play import _handle_click_container
from network.server import MinecraftServer
from protocol.data_types import write_varint, write_short, write_byte
from world.entities import EntityManager
from world.inventory import ItemStack, PlayerInventory, encode_slot_entry


class FakeConnection(SimpleNamespace):
    async def send_packet(self, packet_id, payload=b""):
        self.sent_packets.append((packet_id, payload))


def click_payload(slot, button=0, state_id=0, mode=0):
    return b"".join((
        write_varint(0),
        write_varint(state_id),
        write_short(slot),
        write_byte(button),
        write_varint(mode),
        write_varint(0),
        encode_slot_entry(None),
    ))


class InventoryPrimitiveTests(unittest.TestCase):
    def test_item_stack_empty_is_a_property(self):
        self.assertTrue(ItemStack().is_empty)
        self.assertFalse(ItemStack("minecraft:stone", 1).is_empty)

    def test_slots_normalize_empty_stacks(self):
        inventory = PlayerInventory()
        inventory.set_slot(0, ItemStack())
        self.assertIsNone(inventory.get_slot(0))

    def test_stack_compatibility_includes_nbt_and_damage(self):
        stack = ItemStack("minecraft:stone", 1, damage=2, nbt={"key": "value"})
        self.assertTrue(stack.can_stack_with(stack.copy()))
        self.assertFalse(stack.can_stack_with(ItemStack("minecraft:stone", 1, damage=3)))

    def test_full_persistence_round_trip_preserves_all_item_data(self):
        inventory = PlayerInventory()
        inventory.set_slot(
            4, ItemStack("minecraft:diamond_pickaxe", 1, damage=17,
                         nbt={"custom_name": "Miner"})
        )
        inventory.ender_chest[2] = ItemStack(
            "minecraft:diamond", 7, nbt={"source": "test"}
        )
        inventory.set_held_slot(4)

        restored = PlayerInventory.deserialize_full(inventory.serialize_full())

        self.assertEqual(restored.get_slot(4), inventory.get_slot(4))
        self.assertEqual(restored.get_slot(4).nbt, {"custom_name": "Miner"})
        self.assertEqual(restored.ender_chest[2].nbt, {"source": "test"})
        self.assertEqual(restored.held_slot, 4)


class InventoryClickTests(unittest.IsolatedAsyncioTestCase):
    def make_connection(self):
        return FakeConnection(
            protocol_version=767,
            inventory_obj=PlayerInventory(),
            inventory_state_id=0,
            sent_packets=[],
        )

    async def test_left_click_picks_up_stack_and_syncs(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(0, ItemStack("minecraft:stone", 12))

        await _handle_click_container(conn, click_payload(0), None)

        self.assertIsNone(conn.inventory_obj.get_slot(0))
        self.assertEqual(conn.inventory_obj.carried_item, ItemStack("minecraft:stone", 12))
        self.assertEqual(conn.inventory_state_id, 1)
        self.assertEqual(conn.sent_packets[-1][0], 0x11)

    async def test_right_click_picks_up_rounded_half(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(0, ItemStack("minecraft:stone", 5))

        await _handle_click_container(conn, click_payload(0, button=1), None)

        self.assertEqual(conn.inventory_obj.get_slot(0).count, 2)
        self.assertEqual(conn.inventory_obj.carried_item.count, 3)

    async def test_stale_click_does_not_mutate_inventory(self):
        conn = self.make_connection()
        conn.inventory_obj.set_slot(0, ItemStack("minecraft:stone", 5))

        await _handle_click_container(conn, click_payload(0, state_id=9), None)

        self.assertEqual(conn.inventory_obj.get_slot(0).count, 5)
        self.assertIsNone(conn.inventory_obj.carried_item)
        self.assertEqual(len(conn.sent_packets), 1)


class ItemPickupTests(unittest.IsolatedAsyncioTestCase):
    def make_server(self, inventory):
        player = FakeConnection(
            username="Tester",
            x=0.0, y=64.0, z=0.0,
            entity_id=1,
            protocol_version=767,
            version_handler=None,
            inventory_obj=inventory,
            inventory_state_id=0,
            sent_packets=[],
        )
        server = SimpleNamespace()
        server.get_online_players = lambda: [player]
        next_entity_id = iter(range(2, 1000))
        server.get_next_entity_id = lambda: next(next_entity_id)
        server.entity_manager = EntityManager(server)
        return server, player

    async def test_item_pickup_adds_stack_before_removing_entity(self):
        server, player = self.make_server(PlayerInventory())
        entity = server.entity_manager.create_item(
            0.0, 64.0, 0.0, item_name="minecraft:diamond", count=3
        )
        entity.pickup_delay = 0

        await MinecraftServer._tick_entity_interactions(server)

        self.assertEqual(player.inventory_obj.count_item("minecraft:diamond"), 3)
        self.assertIsNone(server.entity_manager.get_entity(entity.entity_id))
        self.assertGreaterEqual(len(player.sent_packets), 2)

    async def test_partial_pickup_preserves_remainder_entity(self):
        inventory = PlayerInventory()
        for slot in list(range(9, 36)) + list(range(0, 9)) + [40]:
            inventory.set_slot(slot, ItemStack("minecraft:dirt", 64))
        inventory.set_slot(0, ItemStack("minecraft:diamond", 63))
        server, player = self.make_server(inventory)
        entity = server.entity_manager.create_item(
            0.0, 64.0, 0.0, item_name="minecraft:diamond", count=3
        )
        entity.pickup_delay = 0

        await MinecraftServer._tick_entity_interactions(server)

        self.assertEqual(player.inventory_obj.count_item("minecraft:diamond"), 64)
        self.assertEqual(entity.metadata["count"], 2)
        self.assertIs(server.entity_manager.get_entity(entity.entity_id), entity)

    async def test_full_inventory_does_not_delete_item(self):
        inventory = PlayerInventory()
        for slot in list(range(9, 36)) + list(range(0, 9)) + [40]:
            inventory.set_slot(slot, ItemStack("minecraft:dirt", 64))
        server, player = self.make_server(inventory)
        entity = server.entity_manager.create_item(
            0.0, 64.0, 0.0, item_name="minecraft:diamond", count=3
        )
        entity.pickup_delay = 0

        await MinecraftServer._tick_entity_interactions(server)

        self.assertEqual(player.inventory_obj.count_item("minecraft:diamond"), 0)
        self.assertIs(server.entity_manager.get_entity(entity.entity_id), entity)
        self.assertEqual(player.sent_packets, [])


if __name__ == "__main__":
    unittest.main()