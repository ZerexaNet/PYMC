"""
Shared decoration helpers for the two Python terrain generators.

``TerrainGenerator`` (the plain fallback) and ``VanillaTerrainGenerator`` place
trees, surface plants and underwater decoration the same way, so these methods
live here once and both classes inherit them. They use ``self.seed`` only.
"""

import random as _random

from .blocks import (
    AIR, WATER, SHORT_GRASS, DANDELION, POPPY, KELP, KELP_PLANT, SEAGRASS,
    ALLIUM, AZURE_BLUET, BLUE_ORCHID, CORNFLOWER, LILY_OF_THE_VALLEY,
    ORANGE_TULIP, OXEYE_DAISY, PINK_TULIP, RED_TULIP, WHITE_TULIP,
    BRAIN_CORAL_BLOCK, BRAIN_CORAL_FAN, BUBBLE_CORAL_BLOCK, BUBBLE_CORAL_FAN,
    FIRE_CORAL_BLOCK, FIRE_CORAL_FAN, HORN_CORAL_BLOCK, HORN_CORAL_FAN,
    TUBE_CORAL_BLOCK, TUBE_CORAL_FAN,
)

WORLD_HEIGHT = 384  # MAX_Y - MIN_Y + 1


class DecorationMixin:
    """Tree, plant and underwater decoration placement shared by both generators."""

    def _block_hash(self, x: int, y: int, z: int) -> float:
        """
        简单的坐标哈希函数，返回 [0, 1) 的伪随机值。
        用于基岩层随机和其他确定性随机。
        """
        n = x * 374761393 + y * 668265263 + z * 1274126177 + self.seed
        n = (n ^ (n >> 13)) * 1103515245
        n = n ^ (n >> 16)
        return (n & 0x7FFFFFFF) / 0x7FFFFFFF

    def _is_clear_for_tree(self, blocks, lx: int, lz: int, trunk_base_y: int,
                           radius: int = 2, height: int = 7) -> bool:
        for y in range(trunk_base_y, min(trunk_base_y + height, WORLD_HEIGHT)):
            for dz in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, nz = lx + dx, lz + dz
                    if not (0 <= nx < 16 and 0 <= nz < 16):
                        return False
                    if blocks[y][nz][nx] not in (AIR, WATER):
                        return False
        return True

    def _place_surface_plant(self, blocks, biome: str, lx: int, lz: int, plant_y: int,
                             rng: _random.Random):
        flower_tables = {
            "minecraft:flower_forest": [DANDELION, POPPY, ALLIUM, AZURE_BLUET,
                                        RED_TULIP, ORANGE_TULIP, WHITE_TULIP,
                                        PINK_TULIP, OXEYE_DAISY, CORNFLOWER,
                                        LILY_OF_THE_VALLEY],
            "minecraft:cherry_grove": [PINK_TULIP, WHITE_TULIP, ALLIUM],
            "minecraft:meadow": [ALLIUM, AZURE_BLUET, CORNFLOWER, OXEYE_DAISY],
            "minecraft:swamp": [BLUE_ORCHID],
            "minecraft:mangrove_swamp": [BLUE_ORCHID],
            "minecraft:plains": [DANDELION, POPPY, CORNFLOWER],
            "minecraft:sunflower_plains": [DANDELION, POPPY, CORNFLOWER],
        }

        if biome in flower_tables and rng.random() < 0.18:
            blocks[plant_y][lz][lx] = rng.choice(flower_tables[biome])
        elif biome in {"minecraft:plains", "minecraft:forest", "minecraft:birch_forest",
                       "minecraft:flower_forest", "minecraft:meadow", "minecraft:taiga",
                       "minecraft:old_growth_pine_taiga", "minecraft:old_growth_spruce_taiga"} and rng.random() < 0.35:
            blocks[plant_y][lz][lx] = SHORT_GRASS

    def _place_underwater_decor(self, blocks, biome: str, lx: int, lz: int, floor_y: int,
                                rng: _random.Random):
        water_y = floor_y + 1
        if water_y >= WORLD_HEIGHT or blocks[water_y][lz][lx] != WATER:
            return

        if biome in {"minecraft:warm_ocean", "minecraft:lukewarm_ocean"} and rng.random() < 0.08:
            coral_blocks = [
                TUBE_CORAL_BLOCK, BRAIN_CORAL_BLOCK, BUBBLE_CORAL_BLOCK,
                FIRE_CORAL_BLOCK, HORN_CORAL_BLOCK,
            ]
            coral_fans = [
                TUBE_CORAL_FAN, BRAIN_CORAL_FAN, BUBBLE_CORAL_FAN,
                FIRE_CORAL_FAN, HORN_CORAL_FAN,
            ]
            blocks[floor_y][lz][lx] = rng.choice(coral_blocks)
            if water_y < WORLD_HEIGHT and blocks[water_y][lz][lx] == WATER:
                blocks[water_y][lz][lx] = rng.choice(coral_fans)
            return

        if biome in {"minecraft:ocean", "minecraft:deep_ocean", "minecraft:cold_ocean",
                     "minecraft:deep_cold_ocean", "minecraft:lukewarm_ocean",
                     "minecraft:warm_ocean"}:
            if rng.random() < 0.22:
                height = 1 + rng.randint(0, 4)
                for i in range(height):
                    y = water_y + i
                    if y >= WORLD_HEIGHT or blocks[y][lz][lx] != WATER:
                        break
                    blocks[y][lz][lx] = KELP if i == height - 1 else KELP_PLANT
            elif rng.random() < 0.35:
                blocks[water_y][lz][lx] = SEAGRASS

    def _should_place_tree(self, biome: str, surface_h: int, rng: _random.Random) -> bool:
        tree_chance = {
            "minecraft:plains": 0.015,
            "minecraft:forest": 0.08,
            "minecraft:flower_forest": 0.07,
            "minecraft:birch_forest": 0.08,
            "minecraft:dark_forest": 0.09,
            "minecraft:jungle": 0.10,
            "minecraft:bamboo_jungle": 0.08,
            "minecraft:sparse_jungle": 0.05,
            "minecraft:taiga": 0.07,
            "minecraft:old_growth_pine_taiga": 0.08,
            "minecraft:old_growth_spruce_taiga": 0.08,
            "minecraft:cherry_grove": 0.06,
            "minecraft:savanna": 0.035,
            "minecraft:savanna_plateau": 0.03,
            "minecraft:windswept_savanna": 0.025,
            "minecraft:mangrove_swamp": 0.04,
            "minecraft:swamp": 0.03,
        }.get(biome, 0.0)

        if surface_h > 130:
            tree_chance *= 0.3
        return rng.random() < tree_chance
