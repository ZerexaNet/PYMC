"""
Composter (ComposterBlock): compostable items raise the level with their
vanilla chance, level 7 turns ready (8) after 20 ticks (redstone engine),
using a ready composter - or a hopper below it - takes the bone meal out.
Hoppers fill and empty composters in the native hopper code.
"""

from __future__ import annotations

import random

_rng = random.Random()

_CHANCES = {
    0.3: ("jungle_leaves", "oak_leaves", "spruce_leaves", "dark_oak_leaves", "acacia_leaves", "cherry_leaves",
          "birch_leaves", "azalea_leaves", "mangrove_leaves", "oak_sapling", "spruce_sapling", "birch_sapling",
          "jungle_sapling", "acacia_sapling", "cherry_sapling", "dark_oak_sapling", "mangrove_propagule",
          "beetroot_seeds", "dried_kelp", "short_grass", "kelp", "melon_seeds", "pumpkin_seeds",
          "torchflower_seeds", "pitcher_pod", "wheat_seeds", "sweet_berries", "glow_berries", "seagrass",
          "small_dripleaf", "hanging_roots", "mangrove_roots", "moss_carpet", "pink_petals"),
    0.5: ("dried_kelp_block", "tall_grass", "flowering_azalea_leaves", "cactus", "sugar_cane", "vine",
          "nether_sprouts", "weeping_vines", "twisting_vines", "melon_slice", "glow_lichen"),
    0.65: ("sea_pickle", "lily_pad", "pumpkin", "carved_pumpkin", "melon", "apple", "beetroot", "carrot",
           "cocoa_beans", "potato", "wheat", "brown_mushroom", "red_mushroom", "mushroom_stem", "crimson_fungus",
           "warped_fungus", "nether_wart", "crimson_roots", "warped_roots", "shroomlight", "dandelion", "poppy",
           "blue_orchid", "allium", "azure_bluet", "red_tulip", "orange_tulip", "white_tulip", "pink_tulip",
           "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose", "fern", "sunflower", "lilac",
           "rose_bush", "peony", "large_fern", "spore_blossom", "azalea", "moss_block", "big_dripleaf",
           "torchflower", "pitcher_plant"),
    0.85: ("hay_block", "brown_mushroom_block", "red_mushroom_block", "nether_wart_block", "warped_wart_block",
           "flowering_azalea", "bread", "baked_potato", "cookie"),
    1.0: ("cake", "pumpkin_pie"),
}
COMPOSTABLES = {"minecraft:" + name: chance for chance, names in _CHANCES.items() for name in names}


def compost_chance(item_id: str) -> float:
    return COMPOSTABLES.get(item_id if ":" in item_id else "minecraft:" + item_id, 0.0)


def insert_item(level: int, item_id: str, rng=_rng) -> int:
    """ComposterBlock.addItem: the new level after composting one item (level < 7)."""
    chance = compost_chance(item_id)
    if (level == 0 and chance > 0.0) or rng.random() < chance:
        return level + 1
    return level
