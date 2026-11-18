"""Vanilla crafting (recipes + crafting windows), leaf drops, fast chunk encoders."""

import random
import unittest
from collections import Counter
from types import SimpleNamespace

from handlers.play import _handle_click_container, return_crafting_grid
from protocol.data_types import write_byte, write_short, write_varint
from world.block_behavior import get_block_drops
from world.crafting import match_crafting_grid, vanilla_recipes
from world.inventory import ItemStack, PlayerInventory, encode_slot_entry


def P(name):
    return "minecraft:" + name


class FakeConnection(SimpleNamespace):
    async def send_packet(self, packet_id, payload=b""):
        self.sent_packets.append((packet_id, payload))


def click(window_id, slot, button=0, mode=0, state_id=0):
    return b"".join((
        write_varint(window_id), write_varint(state_id), write_short(slot),
        write_byte(button), write_varint(mode), write_varint(0), encode_slot_entry(None),
    ))


class RecipeMatchingTests(unittest.TestCase):
    def test_full_vanilla_recipe_set_is_loaded(self):
        self.assertTrue(vanilla_recipes.loaded)
        self.assertGreater(sum(len(v) for v in vanilla_recipes.shaped.values()), 600)
        self.assertGreater(sum(len(v) for v in vanilla_recipes.shapeless.values()), 200)

    def test_tags_mixed_planks_and_wood_variants(self):
        self.assertEqual(match_crafting_grid(
            [P("oak_planks"), P("birch_planks"), P("spruce_planks"), P("cherry_planks")], 2),
            (P("crafting_table"), 1))
        self.assertEqual(match_crafting_grid(["", P("stripped_oak_wood"), "", ""], 2),
                         (P("oak_planks"), 4))

    def test_shaped_position_and_mirroring(self):
        sticks = ["", "", "", "", "", P("oak_planks"), "", "", P("birch_planks")]
        self.assertEqual(match_crafting_grid(sticks, 3), (P("stick"), 4))
        c = P("cobblestone")
        stairs_left = [c, "", "", c, c, "", c, c, c]
        stairs_right = ["", "", c, "", c, c, c, c, c]
        self.assertEqual(match_crafting_grid(stairs_left, 3), (P("cobblestone_stairs"), 4))
        self.assertEqual(match_crafting_grid(stairs_right, 3), (P("cobblestone_stairs"), 4))

    def test_shapeless_any_order_and_no_match(self):
        self.assertEqual(match_crafting_grid([P("flint"), "", "", P("iron_ingot")], 2),
                         (P("flint_and_steel"), 1))
        self.assertIsNone(match_crafting_grid([P("dirt"), P("stone"), "", ""], 2))
        # a pickaxe does not fit in the 2x2 grid
        self.assertIsNone(match_crafting_grid([P("oak_planks"), P("oak_planks"), P("stick"), ""], 2))


class CraftingWindowTests(unittest.IsolatedAsyncioTestCase):
    def conn(self):
        return FakeConnection(protocol_version=767, inventory_obj=PlayerInventory(),
                              inventory_state_id=0, sent_packets=[], x=0.0, y=64.0, z=0.0, yaw=0.0)

    async def test_inventory_grid_result_and_take(self):
        conn = self.conn()
        inv = conn.inventory_obj
        inv.set_slot(0, ItemStack(P("oak_log"), 3))
        await _handle_click_container(conn, click(0, 36), None)        # pick up logs
        await _handle_click_container(conn, click(0, 1, button=1), None)  # one into the grid
        self.assertEqual(inv.slots[45], ItemStack(P("oak_planks"), 4))   # result shown
        await _handle_click_container(conn, click(0, 36), None)        # put the rest back
        await _handle_click_container(conn, click(0, 0), None)         # take the result
        self.assertEqual(inv.carried_item, ItemStack(P("oak_planks"), 4))
        self.assertIsNone(inv.slots[41])
        self.assertIsNone(inv.slots[45])

    async def test_shift_click_crafts_everything_that_fits(self):
        conn = self.conn()
        inv = conn.inventory_obj
        inv.slots[41] = ItemStack(P("oak_log"), 5)
        await _handle_click_container(conn, click(0, 0, mode=1), None)
        total = sum(s.count for s in inv.slots[:36] if s and s.item_id == P("oak_planks"))
        self.assertEqual(total, 20)
        self.assertIsNone(inv.slots[41])

    async def test_crafting_table_grid_remainders_and_close(self):
        conn = self.conn()
        conn._open_window_id = 5
        conn._open_container_type = 'crafting'
        conn._open_container_pos = (0, 64, 0)
        conn._crafting_grid = [None] * 9
        grid = conn._crafting_grid
        for i in range(3):
            grid[i] = ItemStack(P("milk_bucket"), 1)
        grid[3], grid[5] = ItemStack(P("sugar"), 1), ItemStack(P("sugar"), 1)
        grid[4] = ItemStack(P("egg"), 1)
        for i in range(6, 9):
            grid[i] = ItemStack(P("wheat"), 1)
        await _handle_click_container(conn, click(5, 0), None)
        self.assertEqual(conn.inventory_obj.carried_item, ItemStack(P("cake"), 1))
        self.assertEqual([g.item_id if g else None for g in grid[:3]], [P("bucket")] * 3)
        self.assertTrue(all(g is None for g in grid[3:]))
        # closing hands the buckets back
        await return_crafting_grid(conn, None, 5)
        buckets = sum(s.count for s in conn.inventory_obj.slots[:36] if s and s.item_id == P("bucket"))
        self.assertEqual(buckets, 3)

    async def test_matching_clicks_are_answered_with_slot_diffs_only(self):
        conn = self.conn()
        conn.inventory_obj.set_slot(0, ItemStack(P("stone"), 4))
        await _handle_click_container(conn, click(0, 36), None)  # full sync establishes state
        sent = len(conn.sent_packets)
        state = conn.inventory_state_id
        # client clicked on the state it was sent and predicted correctly
        payload = b"".join((
            write_varint(0), write_varint(state), write_short(37), write_byte(0), write_varint(0),
            write_varint(1), write_short(37), encode_slot_entry(ItemStack(P("stone"), 4)),
            encode_slot_entry(None),
        ))
        await _handle_click_container(conn, payload, None)
        self.assertEqual(len(conn.sent_packets), sent)   # nothing to correct
        self.assertEqual(conn.inventory_state_id, state)


class LeafDropTests(unittest.TestCase):
    def test_vanilla_chances_and_shears(self):
        random.seed(7)
        counts = Counter()
        n = 40000
        for _ in range(n):
            for drop in get_block_drops(P("oak_leaves"), None):
                counts[drop.item_id] += 1
        self.assertAlmostEqual(counts[P("oak_sapling")] / n, 0.05, delta=0.006)
        self.assertAlmostEqual(counts[P("stick")] / n, 0.02, delta=0.004)
        self.assertAlmostEqual(counts[P("apple")] / n, 0.005, delta=0.002)
        self.assertEqual(counts[P("oak_leaves")], 0)
        drops = get_block_drops(P("birch_leaves"), ItemStack(P("shears"), 1))
        self.assertEqual([d.item_id for d in drops], [P("birch_leaves")])


class FastEncoderTests(unittest.TestCase):
    def test_pack_unpack_roundtrip_every_width(self):
        from world.fastpack import pack_longs, to_signed, unpack_longs
        rng = random.Random(3)
        for bits in range(1, 16):
            entries = [rng.randrange(1 << bits) for _ in range(4096)]
            longs = to_signed(pack_longs(entries, bits))
            self.assertTrue(all(-(1 << 63) <= v < (1 << 63) for v in longs))
            self.assertEqual(unpack_longs(longs, bits, 4096), entries)
            per_long = 64 // bits
            first = sum(e << (i * bits) for i, e in enumerate(entries[:per_long]))
            self.assertEqual(longs[0] % (1 << 64), first)

    def test_heightmap_columns(self):
        from world.chunk import build_heightmap_from_terrain
        from world.blocks import WATER
        from world.fastpack import unpack_longs
        blocks = [[[0] * 16 for _ in range(16)] for _ in range(384)]
        blocks[100][2][3] = 1
        blocks[120][2][3] = WATER
        surface = unpack_longs(build_heightmap_from_terrain(blocks, True), 9, 256)
        motion = unpack_longs(build_heightmap_from_terrain(blocks, False), 9, 256)
        self.assertEqual(surface[2 * 16 + 3], 121)
        self.assertEqual(motion[2 * 16 + 3], 101)
        self.assertEqual(surface[0], 0)


if __name__ == "__main__":
    unittest.main()
