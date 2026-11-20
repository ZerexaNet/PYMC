"""Enchanting table, anvil, enchanted books and their slot encoding (1.21.1 rules)."""

import random
import unittest
from types import SimpleNamespace

from handlers.play import _handle_click_container
from protocol.data_types import write_byte, write_short, write_varint
from world import enchanting
from world.block_behavior import container_manager
from world.inventory import ItemStack, PlayerInventory, decode_slot_entry, encode_slot_entry


class FakeConnection(SimpleNamespace):
    async def send_packet(self, packet_id, payload=b""):
        self.sent_packets.append((packet_id, payload))


def make_conn(window_id=1, **overrides):
    fields = dict(protocol_version=767, inventory_obj=PlayerInventory(), inventory_state_id=0,
                  sent_packets=[], x=0.0, y=64.0, z=0.0, yaw=0.0, entity_id=1, gamemode="survival",
                  experience_level=30, experience_total=0, experience_progress=0.0, version_handler=None,
                  _open_window_id=window_id, _open_container_pos=(0, 64, 0), _open_container_type="block")
    fields.update(overrides)
    return FakeConnection(**fields)


def click(slot, button=0, mode=0):
    return b"".join((write_varint(1), write_varint(0), write_short(slot), write_byte(button),
                     write_varint(mode), write_varint(0), encode_slot_entry(None)))


class SlotEncodingTests(unittest.TestCase):
    def test_enchanted_sword_round_trips(self):
        sword = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 5, "unbreaking": 3}})
        data = encode_slot_entry(sword) + b"\x00"
        item, offset = decode_slot_entry(data, 0)
        self.assertEqual(item.nbt, {"enchantments": {"sharpness": 5, "unbreaking": 3}})
        self.assertEqual(offset, len(data) - 1)

    def test_enchanted_book_round_trips_with_damage_first(self):
        book = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"mending": 1}})
        item, _ = decode_slot_entry(encode_slot_entry(book), 0)
        self.assertEqual(item.item_id, "minecraft:enchanted_book")
        self.assertEqual(item.nbt, {"stored_enchantments": {"mending": 1}})

    def test_plain_items_are_unchanged(self):
        self.assertEqual(encode_slot_entry(ItemStack("minecraft:stone", 3)),
                         enchanting_bytes_without_components(ItemStack("minecraft:stone", 3)))


def enchanting_bytes_without_components(item):
    from protocol.data_types import write_varint as wv
    from world.inventory import item_name_to_protocol_id
    return wv(item.count) + wv(item_name_to_protocol_id(item.item_id)) + wv(0) + wv(0)


class DataTests(unittest.TestCase):
    def test_registry_ids_follow_the_synced_order(self):
        self.assertEqual(enchanting.protocol_id("sharpness"), 32)
        self.assertEqual(enchanting.name_of_protocol_id(32), "sharpness")
        self.assertEqual(enchanting.protocol_id("minecraft:sharpness"), 32)

    def test_levels_and_exclusive_sets(self):
        sharp = enchanting.enchantment("sharpness")
        self.assertEqual(enchanting.level_cost(sharp, 3, "min_cost"), 23)
        self.assertFalse(enchanting.compatible("smite", ["sharpness"]))           # damage exclusive set
        self.assertTrue(enchanting.compatible("unbreaking", ["sharpness"]))
        self.assertFalse(enchanting.compatible("bane_of_arthropods", ["sharpness"]))

    def test_enchantability(self):
        self.assertEqual(enchanting.item_enchantability("minecraft:golden_sword"), 22)
        self.assertEqual(enchanting.item_enchantability("minecraft:stone"), 0)
        self.assertEqual(enchanting.item_enchantability("minecraft:book"), 1)

    def test_accepts_by_item(self):
        self.assertTrue(enchanting.accepts("minecraft:diamond_sword", "sharpness"))
        self.assertFalse(enchanting.accepts("minecraft:diamond_pickaxe", "sharpness"))
        self.assertTrue(enchanting.accepts("minecraft:book", "sharpness"))


class OfferTests(unittest.TestCase):
    def test_offers_need_items_and_power(self):
        self.assertEqual(enchanting.offer_costs(1, "minecraft:stone", 15), [0, 0, 0])
        costs = enchanting.offer_costs(99, "minecraft:diamond_sword", 0)
        self.assertEqual(costs[0], max(1, costs[0]))
        self.assertLessEqual(costs[0], costs[1])                                    # first offer is the cheapest

    def test_offers_are_reproducible_and_only_valid_enchantments(self):
        first = enchanting.enchanting_offers(12345, "minecraft:diamond_sword", 15)
        self.assertEqual(first, enchanting.enchanting_offers(12345, "minecraft:diamond_sword", 15))
        for offer in first:
            if offer is None:
                continue
            for name, level in offer["enchants"]:
                entry = enchanting.enchantment(name)
                self.assertTrue(entry["in_enchanting_table"] and not entry["treasure"])
                self.assertTrue(enchanting.accepts("minecraft:diamond_sword", name))
                self.assertLessEqual(level, entry["max_level"])

    def test_books_get_stored_enchantments(self):
        item_id, nbt = enchanting.with_enchantments("minecraft:book", {}, [("sharpness", 2)])
        self.assertEqual((item_id, nbt), ("minecraft:enchanted_book", {"stored_enchantments": {"sharpness": 2}}))
        item_id, nbt = enchanting.with_enchantments("minecraft:iron_pickaxe", {}, [("efficiency", 3)])
        self.assertEqual((item_id, nbt), ("minecraft:iron_pickaxe", {"enchantments": {"efficiency": 3}}))

    def test_power_counts_bookshelves_with_air_between(self):
        shelves = enchanting.bookshelf_states()
        shelf = next(iter(shelves))
        blocks = {}
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                if abs(dx) < 2 and abs(dz) < 2:
                    continue
                blocks[(10 + dx, 64, 10 + dz)] = shelf
        self.assertEqual(enchanting.bookshelf_power(lambda x, y, z: blocks.get((x, y, z), 0), 10, 64, 10), 15)
        blocks[(12, 64, 10)] = 1                       # a shelf that is not there any more
        blocks[(12, 64, 11)] = 1
        self.assertEqual(enchanting.bookshelf_power(lambda x, y, z: blocks.get((x, y, z), 0), 10, 64, 10), 14)


class AnvilTests(unittest.TestCase):
    def test_book_adds_enchantment_and_costs_levels(self):
        sword = ItemStack("minecraft:diamond_sword", 1, 0, {})
        book = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"sharpness": 3}})
        result, cost = enchanting.anvil_merge(sword, book)
        self.assertEqual(result.nbt["enchantments"], {"sharpness": 3})
        self.assertEqual(cost, enchanting.enchantment("sharpness")["anvil_cost"] * 3)

    def test_same_level_books_raise_the_level(self):
        sword = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 2}})
        book = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"sharpness": 2}})
        result, _ = enchanting.anvil_merge(sword, book)
        self.assertEqual(result.nbt["enchantments"], {"sharpness": 3})

    def test_exclusive_enchantments_are_refused(self):
        sword = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 1}})
        book = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"smite": 1}})
        self.assertEqual(enchanting.anvil_merge(sword, book), (None, 0))

    def test_book_onto_book_stays_a_book(self):
        left = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"unbreaking": 1}})
        right = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"mending": 1}})
        result, _ = enchanting.anvil_merge(left, right)
        self.assertEqual(result.item_id, "minecraft:enchanted_book")
        self.assertEqual(result.nbt["stored_enchantments"], {"unbreaking": 1, "mending": 1})


class WindowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        container_manager.containers.clear()
        container_manager.block_reader = lambda x, y, z: 0

    def tearDown(self):
        container_manager.containers.clear()
        container_manager.block_reader = None

    async def test_enchanting_table_applies_an_offer(self):
        from world.enchanting_window import handle_enchant_button
        table = container_manager.get_or_create(0, 64, 0, "enchanting_table")
        table.items[0] = ItemStack("minecraft:diamond_sword", 1)
        table.items[1] = ItemStack("minecraft:lapis_lazuli", 3)
        table.enchant_seed = 12345
        conn = make_conn(window_id=1)
        from world.enchanting_window import refresh
        offers = refresh(conn, table, (0, 64, 0)) and table.enchant_offers
        choice = next(i for i, o in enumerate(offers) if o is not None)
        expected = offers[choice]
        await handle_enchant_button(conn, bytes([1]) + write_varint(choice), None)
        result = table.items[0]
        self.assertIn(result.item_id, ("minecraft:diamond_sword",))
        for name, level in expected["enchants"]:
            self.assertEqual(result.nbt["enchantments"][name.split(":")[-1]], level)
        self.assertEqual(table.items[1].count, 3 - expected["lapis"])
        self.assertEqual(conn.experience_level, 30 - expected["levels"])
        self.assertNotEqual(table.enchant_seed, 12345)

    async def test_enchanting_refuses_without_lapis_or_levels(self):
        from world.enchanting_window import handle_enchant_button, refresh
        table = container_manager.get_or_create(0, 64, 0, "enchanting_table")
        table.items[0] = ItemStack("minecraft:diamond_sword", 1)
        table.enchant_seed = 12345
        refresh(make_conn(), table, (0, 64, 0))
        choice = next(i for i, o in enumerate(table.enchant_offers) if o is not None)
        conn = make_conn(window_id=1, experience_level=0)
        await handle_enchant_button(conn, bytes([1]) + write_varint(choice), None)
        self.assertEqual(table.items[0].nbt, {})                                  # no lapis: nothing happens
        table.items[1] = ItemStack("minecraft:lapis_lazuli", 3)
        await handle_enchant_button(conn, bytes([1]) + write_varint(choice), None)
        self.assertEqual(table.items[0].nbt, {})                                  # no levels: nothing happens

    async def test_anvil_result_is_taken_with_its_inputs_and_levels(self):
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1)
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"sharpness": 2}})
        from world.enchanting_window import refresh
        refresh(make_conn(), anvil, (0, 64, 0))
        self.assertIsNotNone(anvil.items[2])
        cost = anvil.anvil_cost
        conn = make_conn(window_id=1, container_type="block")
        await _handle_click_container(conn, click(2, button=0, mode=0), None)      # take the result
        self.assertEqual(conn.inventory_obj.carried_item.nbt,
                         {"enchantments": {"sharpness": 2}, "repair_cost": 1})
        self.assertIsNone(anvil.items[0])
        self.assertIsNone(anvil.items[1])
        self.assertEqual(conn.experience_level, 30 - cost)

    async def test_anvil_result_cannot_be_taken_without_levels(self):
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1)
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"sharpness": 5}})
        from world.enchanting_window import refresh
        refresh(make_conn(), anvil, (0, 64, 0))
        conn = make_conn(window_id=1, experience_level=0)
        await _handle_click_container(conn, click(2, button=0, mode=0), None)
        self.assertIsNotNone(anvil.items[2])
        self.assertIsNone(conn.inventory_obj.carried_item)

    async def test_number_key_cannot_swap_into_the_anvil_result(self):
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1)
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"sharpness": 2}})
        from world.enchanting_window import refresh
        refresh(make_conn(), anvil, (0, 64, 0))
        result = anvil.items[2]
        conn = make_conn(window_id=1)
        conn.inventory_obj.set_slot(0, ItemStack("minecraft:dirt", 4))
        await _handle_click_container(conn, click(2, button=0, mode=2), None)
        self.assertIs(anvil.items[2], result)
        self.assertEqual(conn.inventory_obj.get_slot(0).item_id, "minecraft:dirt")

    async def test_closing_returns_the_inputs(self):
        from world.enchanting_window import return_inputs
        table = container_manager.get_or_create(0, 64, 0, "enchanting_table")
        table.items[0] = ItemStack("minecraft:diamond_sword", 1)
        table.items[1] = ItemStack("minecraft:lapis_lazuli", 2)
        conn = make_conn(window_id=1)
        return_inputs(conn, 1)
        self.assertEqual(table.items[0], None)
        self.assertEqual(table.items[1], None)
        slots = [conn.inventory_obj.get_slot(i) for i in range(36)]
        self.assertTrue(any(s is not None and s.item_id == "minecraft:diamond_sword" for s in slots))
        self.assertTrue(any(s is not None and s.item_id == "minecraft:lapis_lazuli" for s in slots))


if __name__ == "__main__":
    unittest.main()


class AnvilCostTests(unittest.IsolatedAsyncioTestCase):
    """Prior work penalty and the too-expensive switch."""

    def tearDown(self):
        from world.enchanting_window import set_too_expensive_limit
        set_too_expensive_limit(True)
        container_manager.containers.clear()

    def test_prior_work_penalty_grows_with_each_use(self):
        sword = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 1}})
        book = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"unbreaking": 1}})
        first, cost1 = enchanting.anvil_merge(sword, book)
        self.assertEqual(enchanting.repair_cost(first), 1)                       # max(0, 0) * 2 + 1
        book2 = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"mending": 1}})
        second, cost2 = enchanting.anvil_merge(first, book2)
        self.assertEqual(enchanting.repair_cost(second), 3)                      # max(1, 0) * 2 + 1
        self.assertEqual(cost2, enchanting.enchantment("mending")["anvil_cost"] + 1)  # the penalty is added
        self.assertEqual(cost1, enchanting.enchantment("unbreaking")["anvil_cost"])

    def test_limit_refuses_results_from_forty_levels(self):
        from world.enchanting_window import refresh, set_too_expensive_limit
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 5}, "repair_cost": 39})
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"unbreaking": 3}})
        set_too_expensive_limit(True)
        refresh(make_conn(), anvil, (0, 64, 0))
        self.assertIsNone(anvil.items[2])                                       # cost >= 40: refused
        set_too_expensive_limit(False)
        refresh(make_conn(), anvil, (0, 64, 0))
        self.assertIsNotNone(anvil.items[2])
        self.assertGreaterEqual(anvil.anvil_cost, 40)

    async def test_without_the_limit_the_expensive_result_can_be_taken(self):
        from world.enchanting_window import refresh, set_too_expensive_limit
        set_too_expensive_limit(False)
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 5}, "repair_cost": 39})
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"unbreaking": 3}})
        refresh(make_conn(), anvil, (0, 64, 0))
        cost = anvil.anvil_cost
        conn = make_conn(window_id=1, experience_level=cost)
        await _handle_click_container(conn, click(2, button=0, mode=0), None)
        self.assertIsNotNone(conn.inventory_obj.carried_item)
        self.assertEqual(conn.experience_level, 0)

    async def test_creative_ignores_the_limit_anyway(self):
        from world.enchanting_window import refresh
        anvil = container_manager.get_or_create(0, 64, 0, "anvil")
        anvil.items[0] = ItemStack("minecraft:diamond_sword", 1, 0, {"enchantments": {"sharpness": 5}, "repair_cost": 39})
        anvil.items[1] = ItemStack("minecraft:enchanted_book", 1, 0, {"stored_enchantments": {"unbreaking": 3}})
        refresh(make_conn(gamemode="creative"), anvil, (0, 64, 0))
        self.assertIsNotNone(anvil.items[2])

    def test_config_switch_is_read_from_server_properties(self):
        import tempfile
        from config import load_config
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/server.properties"
            with open(path, "w", encoding="utf-8") as f:
                f.write("anvil-too-expensive-limit=false\n")
            self.assertFalse(load_config(path)["anvil-too-expensive-limit"])
        self.assertTrue(load_config(f"{d}/missing.properties")["anvil-too-expensive-limit"])


class PotionContentsTests(unittest.TestCase):
    def test_potion_round_trips_with_its_registry_id(self):
        from world.potions import protocol_id
        bottle = ItemStack("minecraft:splash_potion", 1, 0, {"potion": "long_turtle_master"})
        data = encode_slot_entry(bottle) + b"\x00"
        item, offset = decode_slot_entry(data, 0)
        self.assertEqual(item.item_id, "minecraft:splash_potion")
        self.assertEqual(item.nbt, {"potion": "long_turtle_master"})
        self.assertEqual(offset, len(data) - 1)
        self.assertEqual(protocol_id("long_turtle_master"), 20)

    def test_water_bottle_has_the_water_potion(self):
        water = ItemStack("minecraft:potion", 1, 0, {"potion": "water"})
        item, _ = decode_slot_entry(encode_slot_entry(water), 0)
        self.assertEqual(item.nbt, {"potion": "water"})

    def test_potions_without_a_known_name_are_plain_items(self):
        item, _ = decode_slot_entry(encode_slot_entry(ItemStack("minecraft:potion", 1, 0, {})), 0)
        self.assertEqual(item.nbt, {})
