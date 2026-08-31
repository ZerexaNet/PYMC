import unittest
from types import SimpleNamespace
from unittest.mock import patch

from world.blocks import AIR, WATER, LAVA, STONE
from world.fluids import (
    FluidSystem,
    _get_fluid_level,
    _get_water_state,
    _is_solid,
)


class GridWorld:
    """基于字典的简易方块世界。"""

    def __init__(self):
        self.blocks = {}
        self._fluid_updates = []

    def get_block_at(self, x, y, z):
        return self.blocks.get((x, y, z), AIR)

    def set_block(self, x, y, z, state):
        self.blocks[(x, y, z)] = state
        return {(x // 16, z // 16)}


def make_fluid_system(world):
    server = SimpleNamespace(
        get_block_at=world.get_block_at,
        _fluid_updates=world._fluid_updates,
    )
    fs = FluidSystem(server)
    return fs


def run_flow(fs, world, x, y, z, fluid_type="water", ticks=1):
    """放置流体并推进指定 tick 数。"""
    fs.on_fluid_place(x, y, z, fluid_type)
    with patch("world.editing.set_world_block",
               lambda server, bx, by, bz, state: world.set_block(bx, by, bz, state)):
        for _ in range(ticks):
            fs.tick()


class FallingWaterTests(unittest.TestCase):
    def test_falling_water_does_not_dry_up(self):
        """下落水柱的中间段不应被误判为无源而干涸。"""
        world = GridWorld()
        world.set_block(0, 64, 0, WATER)          # 源头
        world.set_block(0, 63, 0, _get_water_state(0, falling=True))
        world.set_block(0, 62, 0, _get_water_state(0, falling=True))
        world.set_block(0, 61, 0, STONE)          # 地面
        fs = make_fluid_system(world)

        # 直接处理中间下落段: 上方是下落水 (level 8), 不应干涸
        with patch("world.editing.set_world_block",
                   lambda s, bx, by, bz, st: world.set_block(bx, by, bz, st)):
            fs._process_flow(0, 63, 0, world.get_block_at(0, 63, 0), "water", [])
        self.assertNotEqual(world.get_block_at(0, 63, 0), AIR)

    def test_falling_water_spreads_on_landing(self):
        """下落到地面的水应能向四周扩散 (此前 level=8 永远不扩散)。"""
        world = GridWorld()
        world.set_block(0, 64, 0, WATER)
        world.set_block(0, 63, 0, _get_water_state(0, falling=True))
        world.set_block(0, 62, 0, STONE)  # 落点地面
        fs = make_fluid_system(world)

        with patch("world.editing.set_world_block",
                   lambda s, bx, by, bz, st: world.set_block(bx, by, bz, st)):
            fs._process_flow(0, 63, 0, world.get_block_at(0, 63, 0), "water", [])

        # 下落水下方是固体, 应向水平方向扩散 level 1
        spread = any(
            world.get_block_at(dx, 63, dz) != AIR
            for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]
        )
        self.assertTrue(spread)


class InfiniteSourceTests(unittest.TestCase):
    def test_two_sources_plus_solid_below_form_source(self):
        world = GridWorld()
        world.set_block(0, 63, 0, STONE)   # 下方固体
        world.set_block(-1, 64, 0, WATER)  # 西侧水源
        world.set_block(1, 64, 0, WATER)   # 东侧水源
        fs = make_fluid_system(world)
        self.assertTrue(fs._can_form_infinite_source(0, 64, 0))

    def test_single_source_does_not_form(self):
        world = GridWorld()
        world.set_block(0, 63, 0, STONE)
        world.set_block(-1, 64, 0, WATER)
        fs = make_fluid_system(world)
        self.assertFalse(fs._can_form_infinite_source(0, 64, 0))

    def test_no_solid_below_does_not_form(self):
        world = GridWorld()
        world.set_block(-1, 64, 0, WATER)
        world.set_block(1, 64, 0, WATER)
        fs = make_fluid_system(world)
        self.assertFalse(fs._can_form_infinite_source(0, 64, 0))

    def test_flow_creates_source_block(self):
        """两个水源之间的空位流入水时应直接变成水源。"""
        world = GridWorld()
        world.set_block(0, 63, 0, STONE)
        world.set_block(-1, 64, 0, WATER)
        world.set_block(1, 64, 0, WATER)
        fs = make_fluid_system(world)

        with patch("world.editing.set_world_block",
                   lambda s, bx, by, bz, st: world.set_block(bx, by, bz, st)):
            fs._process_flow(-1, 64, 0, WATER, "water", [])

        self.assertEqual(world.get_block_at(0, 64, 0), WATER)
        self.assertEqual(_get_fluid_level(world.get_block_at(0, 64, 0)), 0)


if __name__ == "__main__":
    unittest.main()
