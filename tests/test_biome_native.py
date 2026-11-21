"""The native biome sampler (native/vanilla/biome.h) must pick exactly the Python biomes."""

import random
import unittest

from world.biomes import BiomeSampler


def _native_or_skip(sampler: BiomeSampler):
    if sampler._native_handle() is None:
        raise unittest.SkipTest("native engine not available")


def _random_terrain(rng: random.Random):
    """Columns with random tops (-64..300) so every surface branch is reached."""
    blocks = [[[0] * 16 for _ in range(16)] for _ in range(384)]
    for z in range(16):
        for x in range(16):
            top = rng.randint(-64, 300) + 64          # index of the top block
            for y in range(min(top, 384)):
                blocks[y][z][x] = 1
    return blocks


class NativeBiomesMatchPython(unittest.TestCase):

    def assertSameBiomes(self, sampler, cx, cz, blocks):
        native = sampler.build_chunk_biome_sections(cx, cz, blocks)
        python = sampler._build_python(cx, cz, blocks)
        self.assertEqual(len(native), len(python))
        for section, (a, b) in enumerate(zip(native, python)):
            self.assertEqual(a, b, f"section {section} differs")

    def test_random_surfaces_many_seeds(self):
        for seed in range(6):
            sampler = BiomeSampler(seed)
            _native_or_skip(sampler)
            rng = random.Random(seed)
            for _ in range(3):
                cx, cz = rng.randint(-400, 400), rng.randint(-400, 400)
                with self.subTest(seed=seed, chunk=(cx, cz)):
                    self.assertSameBiomes(sampler, cx, cz, _random_terrain(rng))

    def test_generated_terrain(self):
        from world.terrain import TerrainGenerator
        for seed in (3, 7):
            sampler = BiomeSampler(seed)
            _native_or_skip(sampler)
            gen = TerrainGenerator(seed)
            for cx, cz in ((0, 0), (-5, 9), (40, -33)):
                with self.subTest(seed=seed, chunk=(cx, cz)):
                    self.assertSameBiomes(sampler, cx, cz, gen.generate_chunk(cx, cz))

    def test_biome_variety(self):
        """Across seeds and places the random terrain must reach many biomes, or the
        comparison above proves little."""
        seen = set()
        for seed in range(4):
            sampler = BiomeSampler(seed)
            _native_or_skip(sampler)
            rng = random.Random(seed)
            for _ in range(6):
                cx, cz = rng.randint(-2000, 2000), rng.randint(-2000, 2000)
                for section in sampler.build_chunk_biome_sections(cx, cz, _random_terrain(rng)):
                    seen.update(section)
        self.assertGreater(len(seen), 10)   # the random terrain reaches about a dozen biomes


if __name__ == "__main__":
    unittest.main()
