"""Save/load: Anvil regions, Linear -> Anvil migration, vanilla playerdata, block state order."""

import gzip
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from world.chunk_io import (
    BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE, PYMC_STATE_ORDER_TAG, STATE_ID_TO_BLOCK,
    _palette_entry_to_state_id, _state_id_to_palette_entry, _uses_legacy_state_order,
    deserialize_chunk, serialize_chunk,
)
from world.level_data import _plain
from world.storage import HAS_ZSTD, WorldStorage, player_nbt_to_state, player_state_to_nbt

STONE = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:stone"]


def _empty_chunk():
    return [[[0] * 16 for _ in range(16)] for _ in range(384)]


def _state(name, **props):
    for state_id, (block, values) in STATE_ID_TO_BLOCK.items():
        if block == name and all(values.get(k) == v for k, v in props.items()):
            return state_id
    raise KeyError(name)


class BlockStateOrderTests(unittest.TestCase):
    def test_vanilla_state_ids_last_property_fastest(self):
        # Vanilla: oak_stairs facing=north, half=top, shape=straight, waterlogged=true is the
        # first state; waterlogged (the last property) varies fastest.
        base = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:oak_stairs"]
        first = _state("minecraft:oak_stairs", facing="north", half="top",
                       shape="straight", waterlogged="true")
        second = _state("minecraft:oak_stairs", facing="north", half="top",
                        shape="straight", waterlogged="false")
        self.assertEqual(second, first + 1)
        self.assertEqual(base, first + 11)  # vanilla default: bottom, straight, not waterlogged

    def test_palette_entry_roundtrip_with_properties(self):
        for name in ("minecraft:oak_stairs", "minecraft:redstone_wire", "minecraft:chest"):
            state_id = BLOCK_NAME_TO_DEFAULT_STATE[name] + 3
            entry = _state_id_to_palette_entry(state_id)
            self.assertEqual(_palette_entry_to_state_id(entry), state_id)

    def test_new_chunks_are_tagged_and_old_ones_detected(self):
        blocks = _empty_chunk()
        blocks[70][1][2] = _state("minecraft:oak_stairs", facing="east", half="bottom",
                                  shape="straight", waterlogged="false")
        raw = serialize_chunk(blocks, chunk_x=3, chunk_z=-2)
        from protocol.nbt import decode_nbt
        root, _ = decode_nbt(raw, 0, with_type=True, with_name=True)
        self.assertIn(PYMC_STATE_ORDER_TAG, root)
        self.assertFalse(_uses_legacy_state_order(root))
        self.assertTrue(_uses_legacy_state_order({"DataVersion": 3955, "LastUpdate": 0}))
        self.assertEqual(deserialize_chunk(raw), blocks)


class AnvilStorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pymc-world-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_chunks_survive_reopen_as_mca(self):
        storage = WorldStorage(str(self.dir), region_format="anvil")
        storage.initialize()
        blocks = _empty_chunk()
        blocks[0][0][0] = STONE
        blocks[200][15][15] = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:gold_block"]
        storage.save_generated_chunk(-33, 40, blocks)
        storage.flush()
        storage.close()

        self.assertTrue((self.dir / "region" / "r.-2.1.mca").exists())
        with open(self.dir / "region" / "r.-2.1.mca", "rb") as f:
            header = f.read(8192)
        self.assertEqual(len(header), 8192)
        index = (-33 & 31) + (40 & 31) * 32
        offset = struct.unpack(">I", header[index * 4:index * 4 + 4])[0] >> 8
        self.assertGreaterEqual(offset, 2)

        reopened = WorldStorage(str(self.dir), region_format="anvil")
        reopened.initialize()
        self.assertEqual(reopened.load_generated_chunk(-33, 40), blocks)
        self.assertIsNone(reopened.load_generated_chunk(0, 0))

    def test_built_chunk_cache_invalidated_by_saves(self):
        storage = WorldStorage(str(self.dir), region_format="anvil")
        storage.initialize()
        blocks = _empty_chunk()
        storage.save_generated_chunk(1, 1, blocks)
        storage.put_built_chunk(1, 1, [0], [0], b"data")
        self.assertEqual(storage.get_built_chunk(1, 1), ([0], [0], b"data"))
        blocks[100][0][0] = STONE
        storage.save_generated_chunk(1, 1, blocks)
        self.assertIsNone(storage.get_built_chunk(1, 1))
        lazy = storage.lazy_chunk_blocks(1, 1)
        self.assertEqual(lazy[100][0][0], STONE)
        self.assertEqual(len(lazy), 384)

    @unittest.skipUnless(HAS_ZSTD, "zstandard is not installed")
    def test_linear_world_is_migrated_to_anvil(self):
        linear = WorldStorage(str(self.dir), region_format="linear")
        linear.initialize()
        blocks = _empty_chunk()
        blocks[64][4][4] = STONE
        linear.save_generated_chunk(5, 6, blocks)
        linear.flush()
        linear.close()
        self.assertTrue((self.dir / "region" / "r.0.0.linear").exists())

        anvil = WorldStorage(str(self.dir), region_format="anvil")
        anvil.initialize()
        self.assertTrue((self.dir / "region" / "r.0.0.mca").exists())
        self.assertFalse((self.dir / "region" / "r.0.0.linear").exists())
        self.assertEqual(anvil.load_generated_chunk(5, 6), blocks)


class PlayerDataTests(unittest.TestCase):
    STATE = {
        "username": "Alice", "x": 12.5, "y": 70.0, "z": -3.25, "yaw": 90.0, "pitch": -10.0,
        "health": 13.0, "food": 17, "saturation": 2.5, "experience_total": 55,
        "experience_level": 5, "experience_progress": 0.25, "gamemode": "creative",
        "on_ground": True, "air_supply": 300, "fire_ticks": 0, "freeze_ticks": 0,
        "flying": False, "selected_slot": 2,
        "inventory": {
            "slots": {
                "0": {"item": "minecraft:diamond_sword", "count": 1, "damage": 12, "nbt": {}},
                "8": {"item": "minecraft:stone", "count": 64, "damage": 0, "nbt": {}},
                "39": {"item": "minecraft:iron_helmet", "count": 1, "damage": 0, "nbt": {}},
                "40": {"item": "minecraft:shield", "count": 1, "damage": 0, "nbt": {"x": 1}},
            },
            "ender_chest": {"3": {"item": "minecraft:emerald", "count": 9, "damage": 0, "nbt": {}}},
            "selected_slot": 2, "held_slot": 0,
        },
        "personal_spawn": [10, 64, 20],
    }

    def test_nbt_uses_vanilla_slots(self):
        root = _plain(player_state_to_nbt(self.STATE))
        slots = sorted(int(item["Slot"]) for item in root["Inventory"])
        self.assertEqual(slots, [-106, 0, 8, 103])
        self.assertEqual(root["playerGameType"], 1)
        self.assertEqual((root["SpawnX"], root["SpawnY"], root["SpawnZ"]), (10, 64, 20))

    def test_dat_file_roundtrip(self):
        tmp = Path(tempfile.mkdtemp(prefix="pymc-player-"))
        try:
            storage = WorldStorage(str(tmp), region_format="anvil")
            storage.initialize()
            uuid = "11111111-2222-3333-4444-555555555555"
            storage.save_player_data(uuid, self.STATE)
            storage.save_player_data(uuid, self.STATE)
            path = tmp / "playerdata" / f"{uuid}.dat"
            self.assertTrue(path.exists())
            self.assertTrue((tmp / "playerdata" / f"{uuid}.dat_old").exists())
            with gzip.open(path, "rb") as f:
                self.assertEqual(f.read(1), b"\x0a")  # TAG_Compound root
            loaded = storage.load_player_data(uuid)
            self.assertEqual(loaded, player_nbt_to_state(_plain(player_state_to_nbt(self.STATE))))
            for key in ("x", "y", "z", "health", "food", "gamemode", "personal_spawn", "inventory"):
                self.assertEqual(loaded[key], self.STATE[key], key)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
