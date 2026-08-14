import unittest
from types import SimpleNamespace

from handlers.play import _handle_click_container
from protocol.data_types import write_varint, write_short, write_byte
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


if __name__ == "__main__":
    unittest.main()