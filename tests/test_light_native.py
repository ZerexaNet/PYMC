"""The native chunk light (native/vanilla/light.h) must give exactly the Python result."""

import random
import unittest
from array import array
from itertools import chain

from world import lighting


def _native():
    lib = lighting._native_lib()
    if lib is None:
        raise unittest.SkipTest("native engine not available")
    return lib


def _random_chunk(rng: random.Random, size: int, height: int = 384):
    """A [y][z][x] array with a mix of air, solid, and every kind of state id."""
    air_share = rng.uniform(0.3, 0.9)
    chunk = []
    for y in range(height):
        layer_air = air_share if y > height // 3 else 0.05
        layer = []
        for _z in range(16):
            row = []
            for _x in range(16):
                if rng.random() < layer_air:
                    row.append(0)
                elif rng.random() < 0.5:
                    row.append(rng.randrange(1, min(size, 400)))   # common blocks
                else:
                    row.append(rng.randrange(size))                # any state id
            layer.append(row)
        chunk.append(layer)
    return chunk


class NativeLightMatchesPython(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _native()
        cls.size = len(lighting._light_tables()[0])

    def assertSameLight(self, blocks):
        native = lighting._compute_native(_native(), blocks)
        python = lighting._compute_python(blocks)
        self.assertEqual(bytes(native[0]), bytes(python[0]), "sky light differs")
        self.assertEqual(bytes(native[1]), bytes(python[1]), "block light differs")

    def test_random_chunks(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                self.assertSameLight(_random_chunk(random.Random(seed), self.size))

    def test_all_air_and_all_solid(self):
        self.assertSameLight([[[0] * 16 for _ in range(16)] for _ in range(384)])
        stone = [[[1] * 16 for _ in range(16)] for _ in range(64)]
        self.assertSameLight(stone)

    def test_generated_terrain_chunks(self):
        from world.terrain import TerrainGenerator
        for seed in (1, 2):
            gen = TerrainGenerator(seed)
            for cx, cz in ((0, 0), (3, -2)):
                with self.subTest(seed=seed, chunk=(cx, cz)):
                    self.assertSameLight(gen.generate_chunk(cx, cz))

    def test_public_entry_point_matches_python(self):
        blocks = _random_chunk(random.Random(99), self.size, height=64)
        sky, block_light = lighting.compute_light(blocks)
        ref_sky, ref_block = lighting._compute_python(blocks)
        self.assertEqual(bytes(sky), bytes(ref_sky))
        self.assertEqual(bytes(block_light), bytes(ref_block))


    def test_flat_entry_point_matches(self):
        blocks = _random_chunk(random.Random(7), self.size, height=96)
        flat = array("H", chain.from_iterable(chain.from_iterable(blocks)))
        sky, block_light = lighting.compute_light_flat(flat, 96)
        ref_sky, ref_block = lighting._compute_python(blocks)
        self.assertEqual(bytes(sky), bytes(ref_sky))
        self.assertEqual(bytes(block_light), bytes(ref_block))


if __name__ == "__main__":
    unittest.main()
