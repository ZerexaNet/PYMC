import unittest

from world.chunk_io import deserialize_chunk_with_biomes, serialize_chunk
from world.terrain_native import NativeTerrainGenerator, _find_native_binary


def _checksum(blocks):
    return sum(sum(sum(row) for row in layer) for layer in blocks)


class NativeWorldgenTests(unittest.TestCase):
    def setUp(self):
        if _find_native_binary() is None:
            self.skipTest("native terrain_gen binary is not available")

    def test_single_chunk_metadata_is_stable_and_seeded(self):
        gen = NativeTerrainGenerator(seed=12345, worker_count=2)
        try:
            blocks, heightmap, biomes = gen.generate_chunk_with_metadata(0, 0)
            blocks_again, heightmap_again, biomes_again = gen.generate_chunk_with_metadata(0, 0)
        finally:
            gen.shutdown()

        other_seed = NativeTerrainGenerator(seed=54321, worker_count=2)
        try:
            other_blocks, _, _ = other_seed.generate_chunk_with_metadata(0, 0)
        finally:
            other_seed.shutdown()

        self.assertEqual(blocks, blocks_again)
        self.assertEqual(heightmap, heightmap_again)
        self.assertEqual(biomes, biomes_again)
        self.assertNotEqual(_checksum(blocks), _checksum(other_blocks))
        self.assertEqual(len(blocks), 384)
        self.assertEqual(len(heightmap), 16)
        self.assertEqual(len(biomes), 24)
        self.assertTrue(all(len(section) == 64 for section in biomes))

    def test_batch_metadata_and_chunk_nbt_biome_roundtrip(self):
        gen = NativeTerrainGenerator(seed=12345, worker_count=2)
        try:
            results = gen.generate_chunks_with_metadata([(0, 0), (1, 0), (0, 1)])
        finally:
            gen.shutdown()

        self.assertEqual(len(results), 3)
        checksums = [_checksum(blocks) for blocks, _, _ in results]
        self.assertEqual(len(set(checksums)), 3)

        blocks, _, biomes = results[0]
        encoded = serialize_chunk(blocks, 0, 0, chunk_biomes=biomes)
        decoded = deserialize_chunk_with_biomes(encoded)
        self.assertIsNotNone(decoded)
        _, decoded_biomes = decoded
        self.assertEqual(decoded_biomes, biomes)

    def test_vanilla_terrain_layers_and_biomes(self):
        from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK
        from world.terrain_native import native_binary_version
        self.assertTrue(native_binary_version(_find_native_binary()).startswith("pymc-worldgen 2"))
        gen = NativeTerrainGenerator(seed=12345, worker_count=2)
        try:
            coords = [(x * 8, z * 8) for x in range(-3, 4) for z in range(-3, 4)]
            results = gen.generate_chunks_with_metadata(coords)
            spawn = gen.find_spawn()
            again = gen.find_spawn()
        finally:
            gen.shutdown()

        bedrock = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:bedrock"]
        names = set()
        biomes = set()
        for blocks, heightmap, chunk_biomes in results:
            # Vanilla bedrock floor: y=-64 is always bedrock, y=-59 never is.
            self.assertTrue(all(blocks[0][z][x] == bedrock for z in range(16) for x in range(16)))
            self.assertFalse(any(blocks[5][z][x] == bedrock for z in range(16) for x in range(16)))
            for y in (0, 40, 60, 62, 64, 80, 100):
                for z in range(0, 16, 5):
                    for x in range(0, 16, 5):
                        names.add(STATE_ID_TO_BLOCK.get(blocks[y][z][x], ("?", {}))[0])
            for section in chunk_biomes:
                biomes.update(section)
        # deepslate below y=0, stone above, oceans at sea level, a varied biome map
        self.assertIn("minecraft:deepslate", names)
        self.assertIn("minecraft:stone", names)
        self.assertIn("minecraft:water", names)
        self.assertGreaterEqual(len(biomes), 6)

        self.assertIsNotNone(spawn)
        self.assertEqual(spawn, again)
        self.assertLessEqual(max(abs(spawn[0]), abs(spawn[1])), 2560)


if __name__ == "__main__":
    unittest.main()
