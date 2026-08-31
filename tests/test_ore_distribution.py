import random
import unittest

from world.blocks import STONE, AIR, DIAMOND_ORE, LAPIS_ORE
from world.vanilla_terrain import (
    MIN_Y,
    WORLD_HEIGHT,
    OreVeinGenerator,
)


class TrapezoidSamplerTests(unittest.TestCase):
    def test_within_bounds(self):
        rng = random.Random(42)
        for _ in range(5000):
            y = OreVeinGenerator._sample_trapezoid(rng, -64, -32)
            self.assertGreaterEqual(y, -64)
            self.assertLessEqual(y, -32)

    def test_concentrated_in_middle(self):
        """梯形分布中间 1/3 的采样密度应高于边缘。"""
        rng = random.Random(42)
        samples = [OreVeinGenerator._sample_trapezoid(rng, 0, 90)
                   for _ in range(20000)]
        middle = sum(1 for s in samples if 30 <= s <= 60)
        edge = sum(1 for s in samples if s < 15 or s > 75)
        self.assertGreater(middle, edge)


class OrePlacementTests(unittest.TestCase):
    def make_blocks(self, fill=STONE):
        return [[[fill] * 16 for _ in range(16)] for _ in range(WORLD_HEIGHT)]

    def count_block(self, blocks, block_id):
        return sum(
            1
            for y in range(WORLD_HEIGHT)
            for z in range(16)
            for x in range(16)
            if blocks[y][z][x] == block_id
        )

    def test_deterministic_per_seed_and_chunk(self):
        gen = OreVeinGenerator(999)
        a = self.make_blocks()
        b = self.make_blocks()
        gen.place(a, 3, 7)
        gen.place(b, 3, 7)
        self.assertEqual(a, b)

    def test_buried_lapis_never_exposed_to_air(self):
        """buried 批次 (air_discard=1.0) 贴着空气的矿脉必须全部丢弃。"""
        # 世界大部分为空气, 仅 y=0 一层石头: 任何矿石都贴着空气
        blocks = [[[AIR] * 16 for _ in range(16)] for _ in range(WORLD_HEIGHT)]
        yi = 0 - MIN_Y
        for z in range(16):
            for x in range(16):
                blocks[yi][z][x] = STONE
        gen = OreVeinGenerator(12345)
        gen.place(blocks, 0, 0)
        # buried lapis (air_discard=1.0) 不允许出现;
        # 其它无丢弃概率的矿种可能出现, 这里只验证 lapis
        self.assertEqual(self.count_block(blocks, LAPIS_ORE), 0)

    def test_diamond_respects_height_range(self):
        blocks = self.make_blocks()
        OreVeinGenerator(777).place(blocks, 1, 1)
        for y in range(WORLD_HEIGHT):
            wy = y + MIN_Y
            for z in range(16):
                for x in range(16):
                    if blocks[y][z][x] == DIAMOND_ORE:
                        self.assertGreaterEqual(wy, -64 - 1)  # 允许 vein 扩散 1 格
                        self.assertLessEqual(wy, 16 + 1)


if __name__ == "__main__":
    unittest.main()
