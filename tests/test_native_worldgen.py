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


if __name__ == "__main__":
    unittest.main()
