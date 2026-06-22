# ============================================================
# PyMC - Crafting System
# Complete Minecraft 1.21.1 crafting recipe implementation
# ============================================================

"""
Crafting system supporting:
  - Shaped recipes (pattern + key mapping)
  - Shapeless recipes (ingredient list, order-independent)
  - Smelting recipes (input + fuel -> output, with XP and cook time)
  - Stonecutting recipes (1 input -> output)
  - Smithing recipes (template + base + addition -> output)

Recipe format:
  Shaped:
    {
      "type": "shaped",
      "pattern": ["###", " | ", " | "],
      "key": {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
      "result": ("minecraft:stone_pickaxe", 1)
    }

  Shapeless:
    {
      "type": "shapeless",
      "ingredients": ["minecraft:iron_ingot", "minecraft:flint"],
      "result": ("minecraft:flint_and_steel", 1)
    }

  Smelting:
    {
      "type": "smelting",
      "ingredient": "minecraft:iron_ore",
      "result": ("minecraft:iron_ingot", 1),
      "xp": 0.7,
      "cook_time": 200
    }

  Stonecutting:
    {
      "type": "stonecutting",
      "ingredient": "minecraft:stone",
      "result": ("minecraft:stone_bricks", 1)
    }

  Smithing:
    {
      "type": "smithing",
      "template": "minecraft:netherite_upgrade_smithing_template",
      "base": "minecraft:diamond_sword",
      "addition": "minecraft:netherite_ingot",
      "result": ("minecraft:netherite_sword", 1)
    }
"""

import logging
from typing import Optional

logger = logging.getLogger("PyMC.合成")


# --------------------------------------------------
# Recipe Registries
# --------------------------------------------------

CRAFTING_RECIPES: dict[str, dict] = {}
SMELTING_RECIPES: dict[str, dict] = {}
STONECUTTING_RECIPES: dict[str, dict] = {}
SMITHING_RECIPES: dict[str, dict] = {}


def _register_shaped(name: str, pattern: list[str], key: dict[str, str],
                     result_item: str, result_count: int = 1):
    """Register a shaped crafting recipe."""
    CRAFTING_RECIPES[name] = {
        "type": "shaped",
        "pattern": pattern,
        "key": key,
        "result": (result_item, result_count),
    }


def _register_shapeless(name: str, ingredients: list[str],
                        result_item: str, result_count: int = 1):
    """Register a shapeless crafting recipe."""
    CRAFTING_RECIPES[name] = {
        "type": "shapeless",
        "ingredients": ingredients,
        "result": (result_item, result_count),
    }


def _register_smelting(name: str, ingredient: str, result_item: str,
                       result_count: int = 1, xp: float = 0.0,
                       cook_time: int = 200):
    """Register a smelting recipe."""
    SMELTING_RECIPES[name] = {
        "type": "smelting",
        "ingredient": ingredient,
        "result": (result_item, result_count),
        "xp": xp,
        "cook_time": cook_time,
    }


def _register_stonecutting(name: str, ingredient: str, result_item: str,
                           result_count: int = 1):
    """Register a stonecutting recipe."""
    STONECUTTING_RECIPES[name] = {
        "type": "stonecutting",
        "ingredient": ingredient,
        "result": (result_item, result_count),
    }


def _register_smithing(name: str, template: str, base: str, addition: str,
                       result_item: str, result_count: int = 1):
    """Register a smithing recipe."""
    SMITHING_RECIPES[name] = {
        "type": "smithing",
        "template": template,
        "base": base,
        "addition": addition,
        "result": (result_item, result_count),
    }


# --------------------------------------------------
# Shaped Recipes - Building Blocks
# --------------------------------------------------

_register_shaped("minecraft:crafting_table",
    ["##", "##"],
    {"#": "minecraft:oak_planks"},
    "minecraft:crafting_table")

_register_shaped("minecraft:chest",
    ["###", "# #", "###"],
    {"#": "minecraft:oak_planks"},
    "minecraft:chest")

_register_shaped("minecraft:barrel",
    ["#S#", "# #", "#S#"],
    {"#": "minecraft:oak_planks", "S": "minecraft:oak_slab"},
    "minecraft:barrel")

# --- Stairs & Slabs ---
_register_shaped("minecraft:oak_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:oak_planks"},
    "minecraft:oak_stairs", 4)

_register_shaped("minecraft:cobblestone_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:cobblestone"},
    "minecraft:cobblestone_stairs", 4)

_register_shaped("minecraft:stone_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:stone"},
    "minecraft:stone_stairs", 4)

_register_shaped("minecraft:brick_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:bricks"},
    "minecraft:brick_stairs", 4)

_register_shaped("minecraft:stone_brick_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:stone_bricks"},
    "minecraft:stone_brick_stairs", 4)

_register_shaped("minecraft:granite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:granite"},
    "minecraft:granite_stairs", 4)

_register_shaped("minecraft:polished_granite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:polished_granite"},
    "minecraft:polished_granite_stairs", 4)

_register_shaped("minecraft:diorite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:diorite"},
    "minecraft:diorite_stairs", 4)

_register_shaped("minecraft:polished_diorite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:polished_diorite"},
    "minecraft:polished_diorite_stairs", 4)

_register_shaped("minecraft:andesite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:andesite"},
    "minecraft:andesite_stairs", 4)

_register_shaped("minecraft:polished_andesite_stairs",
    ["#  ", "## ", "###"],
    {"#": "minecraft:polished_andesite"},
    "minecraft:polished_andesite_stairs", 4)

_register_shaped("minecraft:oak_slab",
    ["###"],
    {"#": "minecraft:oak_planks"},
    "minecraft:oak_slab", 6)

_register_shaped("minecraft:cobblestone_slab",
    ["###"],
    {"#": "minecraft:cobblestone"},
    "minecraft:cobblestone_slab", 6)

_register_shaped("minecraft:stone_slab",
    ["###"],
    {"#": "minecraft:stone"},
    "minecraft:stone_slab", 6)

_register_shaped("minecraft:brick_slab",
    ["###"],
    {"#": "minecraft:bricks"},
    "minecraft:brick_slab", 6)

_register_shaped("minecraft:stone_brick_slab",
    ["###"],
    {"#": "minecraft:stone_bricks"},
    "minecraft:stone_brick_slab", 6)

_register_shaped("minecraft:granite_slab",
    ["###"],
    {"#": "minecraft:granite"},
    "minecraft:granite_slab", 6)

_register_shaped("minecraft:polished_granite_slab",
    ["###"],
    {"#": "minecraft:polished_granite"},
    "minecraft:polished_granite_slab", 6)

_register_shaped("minecraft:diorite_slab",
    ["###"],
    {"#": "minecraft:diorite"},
    "minecraft:diorite_slab", 6)

_register_shaped("minecraft:polished_diorite_slab",
    ["###"],
    {"#": "minecraft:polished_diorite"},
    "minecraft:polished_diorite_slab", 6)

_register_shaped("minecraft:andesite_slab",
    ["###"],
    {"#": "minecraft:andesite"},
    "minecraft:andesite_slab", 6)

_register_shaped("minecraft:polished_andesite_slab",
    ["###"],
    {"#": "minecraft:polished_andesite"},
    "minecraft:polished_andesite_slab", 6)


# --------------------------------------------------
# Shaped Recipes - Wooden Tools
# --------------------------------------------------

_register_shaped("minecraft:wooden_pickaxe",
    ["###", " | ", " | "],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:wooden_pickaxe")

_register_shaped("minecraft:wooden_axe",
    ["##", "#|", " |"],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:wooden_axe")

_register_shaped("minecraft:wooden_shovel",
    [" # ", " | ", " | "],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:wooden_shovel")

_register_shaped("minecraft:wooden_sword",
    [" # ", " # ", " | "],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:wooden_sword")

_register_shaped("minecraft:wooden_hoe",
    ["##", " |", " |"],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:wooden_hoe")


# --------------------------------------------------
# Shaped Recipes - Stone Tools
# --------------------------------------------------

_register_shaped("minecraft:stone_pickaxe",
    ["###", " | ", " | "],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:stone_pickaxe")

_register_shaped("minecraft:stone_axe",
    ["##", "#|", " |"],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:stone_axe")

_register_shaped("minecraft:stone_shovel",
    [" # ", " | ", " | "],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:stone_shovel")

_register_shaped("minecraft:stone_sword",
    [" # ", " # ", " | "],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:stone_sword")

_register_shaped("minecraft:stone_hoe",
    ["##", " |", " |"],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:stone_hoe")


# --------------------------------------------------
# Shaped Recipes - Iron Tools
# --------------------------------------------------

_register_shaped("minecraft:iron_pickaxe",
    ["###", " | ", " | "],
    {"#": "minecraft:iron_ingot", "|": "minecraft:stick"},
    "minecraft:iron_pickaxe")

_register_shaped("minecraft:iron_axe",
    ["##", "#|", " |"],
    {"#": "minecraft:iron_ingot", "|": "minecraft:stick"},
    "minecraft:iron_axe")

_register_shaped("minecraft:iron_shovel",
    [" # ", " | ", " | "],
    {"#": "minecraft:iron_ingot", "|": "minecraft:stick"},
    "minecraft:iron_shovel")

_register_shaped("minecraft:iron_sword",
    [" # ", " # ", " | "],
    {"#": "minecraft:iron_ingot", "|": "minecraft:stick"},
    "minecraft:iron_sword")

_register_shaped("minecraft:iron_hoe",
    ["##", " |", " |"],
    {"#": "minecraft:iron_ingot", "|": "minecraft:stick"},
    "minecraft:iron_hoe")


# --------------------------------------------------
# Shaped Recipes - Golden Tools
# --------------------------------------------------

_register_shaped("minecraft:golden_pickaxe",
    ["###", " | ", " | "],
    {"#": "minecraft:gold_ingot", "|": "minecraft:stick"},
    "minecraft:golden_pickaxe")

_register_shaped("minecraft:golden_axe",
    ["##", "#|", " |"],
    {"#": "minecraft:gold_ingot", "|": "minecraft:stick"},
    "minecraft:golden_axe")

_register_shaped("minecraft:golden_shovel",
    [" # ", " | ", " | "],
    {"#": "minecraft:gold_ingot", "|": "minecraft:stick"},
    "minecraft:golden_shovel")

_register_shaped("minecraft:golden_sword",
    [" # ", " # ", " | "],
    {"#": "minecraft:gold_ingot", "|": "minecraft:stick"},
    "minecraft:golden_sword")

_register_shaped("minecraft:golden_hoe",
    ["##", " |", " |"],
    {"#": "minecraft:gold_ingot", "|": "minecraft:stick"},
    "minecraft:golden_hoe")


# --------------------------------------------------
# Shaped Recipes - Diamond Tools
# --------------------------------------------------

_register_shaped("minecraft:diamond_pickaxe",
    ["###", " | ", " | "],
    {"#": "minecraft:diamond", "|": "minecraft:stick"},
    "minecraft:diamond_pickaxe")

_register_shaped("minecraft:diamond_axe",
    ["##", "#|", " |"],
    {"#": "minecraft:diamond", "|": "minecraft:stick"},
    "minecraft:diamond_axe")

_register_shaped("minecraft:diamond_shovel",
    [" # ", " | ", " | "],
    {"#": "minecraft:diamond", "|": "minecraft:stick"},
    "minecraft:diamond_shovel")

_register_shaped("minecraft:diamond_sword",
    [" # ", " # ", " | "],
    {"#": "minecraft:diamond", "|": "minecraft:stick"},
    "minecraft:diamond_sword")

_register_shaped("minecraft:diamond_hoe",
    ["##", " |", " |"],
    {"#": "minecraft:diamond", "|": "minecraft:stick"},
    "minecraft:diamond_hoe")


# --------------------------------------------------
# Shaped Recipes - Armor
# --------------------------------------------------

# Leather Armor
_register_shaped("minecraft:leather_helmet",
    ["###", "# #"],
    {"#": "minecraft:leather"},
    "minecraft:leather_helmet")

_register_shaped("minecraft:leather_chestplate",
    ["# #", "###", "###"],
    {"#": "minecraft:leather"},
    "minecraft:leather_chestplate")

_register_shaped("minecraft:leather_leggings",
    ["###", "# #", "# #"],
    {"#": "minecraft:leather"},
    "minecraft:leather_leggings")

_register_shaped("minecraft:leather_boots",
    ["# #", "# #"],
    {"#": "minecraft:leather"},
    "minecraft:leather_boots")

# Iron Armor
_register_shaped("minecraft:iron_helmet",
    ["###", "# #"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_helmet")

_register_shaped("minecraft:iron_chestplate",
    ["# #", "###", "###"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_chestplate")

_register_shaped("minecraft:iron_leggings",
    ["###", "# #", "# #"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_leggings")

_register_shaped("minecraft:iron_boots",
    ["# #", "# #"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_boots")

# Golden Armor
_register_shaped("minecraft:golden_helmet",
    ["###", "# #"],
    {"#": "minecraft:gold_ingot"},
    "minecraft:golden_helmet")

_register_shaped("minecraft:golden_chestplate",
    ["# #", "###", "###"],
    {"#": "minecraft:gold_ingot"},
    "minecraft:golden_chestplate")

_register_shaped("minecraft:golden_leggings",
    ["###", "# #", "# #"],
    {"#": "minecraft:gold_ingot"},
    "minecraft:golden_leggings")

_register_shaped("minecraft:golden_boots",
    ["# #", "# #"],
    {"#": "minecraft:gold_ingot"},
    "minecraft:golden_boots")

# Diamond Armor
_register_shaped("minecraft:diamond_helmet",
    ["###", "# #"],
    {"#": "minecraft:diamond"},
    "minecraft:diamond_helmet")

_register_shaped("minecraft:diamond_chestplate",
    ["# #", "###", "###"],
    {"#": "minecraft:diamond"},
    "minecraft:diamond_chestplate")

_register_shaped("minecraft:diamond_leggings",
    ["###", "# #", "# #"],
    {"#": "minecraft:diamond"},
    "minecraft:diamond_leggings")

_register_shaped("minecraft:diamond_boots",
    ["# #", "# #"],
    {"#": "minecraft:diamond"},
    "minecraft:diamond_boots")


# --------------------------------------------------
# Shaped Recipes - Utility
# --------------------------------------------------

_register_shaped("minecraft:furnace",
    ["###", "# #", "###"],
    {"#": "minecraft:cobblestone"},
    "minecraft:furnace")

_register_shaped("minecraft:lever",
    [" |", "# "],
    {"#": "minecraft:cobblestone", "|": "minecraft:stick"},
    "minecraft:lever")

_register_shaped("minecraft:oak_door",
    ["##", "##", "##"],
    {"#": "minecraft:oak_planks"},
    "minecraft:oak_door", 3)

_register_shaped("minecraft:iron_door",
    ["##", "##", "##"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_door", 3)

_register_shaped("minecraft:ladder",
    ["| |", "|#|", "| |"],
    {"#": "minecraft:stick", "|": "minecraft:stick"},
    "minecraft:ladder", 3)

_register_shaped("minecraft:oak_fence",
    ["#|#", "#|#"],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:oak_fence", 3)

_register_shaped("minecraft:oak_fence_gate",
    ["|#|", "|#|"],
    {"#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:oak_fence_gate")

_register_shaped("minecraft:bucket",
    ["# #", " # "],
    {"#": "minecraft:iron_ingot"},
    "minecraft:bucket")

_register_shaped("minecraft:shears",
    [" #", "# "],
    {"#": "minecraft:iron_ingot"},
    "minecraft:shears")

_register_shaped("minecraft:bow",
    [" |#", "| #", " |#"],
    {"|": "minecraft:stick", "#": "minecraft:string"},
    "minecraft:bow")

_register_shaped("minecraft:shield",
    ["#|#", "###", " # "],
    {"#": "minecraft:oak_planks", "|": "minecraft:iron_ingot"},
    "minecraft:shield")

_register_shaped("minecraft:tnt",
    ["#X#", "#X#", "#X#"],
    {"#": "minecraft:gunpowder", "X": "minecraft:sand"},
    "minecraft:tnt")

_register_shaped("minecraft:anvil",
    ["III", " I ", "SSS"],
    {"I": "minecraft:iron_block", "S": "minecraft:iron_ingot"},
    "minecraft:anvil")

_register_shaped("minecraft:enchanting_table",
    [" B ", "D#D", "###"],
    {"B": "minecraft:book", "D": "minecraft:diamond", "#": "minecraft:obsidian"},
    "minecraft:enchanting_table")

_register_shaped("minecraft:note_block",
    ["###", "XRX", "###"],
    {"#": "minecraft:oak_planks", "X": "minecraft:redstone", "R": "minecraft:stick"},
    "minecraft:note_block")

_register_shaped("minecraft:jukebox",
    ["###", "#D#", "###"],
    {"#": "minecraft:oak_planks", "D": "minecraft:diamond"},
    "minecraft:jukebox")


# --------------------------------------------------
# Shaped Recipes - Redstone
# --------------------------------------------------

_register_shaped("minecraft:repeater",
    ["| |", "###", "R "],
    {"#": "minecraft:stone", "|": "minecraft:redstone_torch", "R": "minecraft:redstone"},
    "minecraft:repeater")

_register_shaped("minecraft:comparator",
    ["| |", "###", " R "],
    {"#": "minecraft:stone", "|": "minecraft:redstone_torch", "R": "minecraft:quartz"},
    "minecraft:comparator")

_register_shaped("minecraft:hopper",
    ["I I", "ICI", " I "],
    {"I": "minecraft:iron_ingot", "C": "minecraft:chest"},
    "minecraft:hopper")

_register_shaped("minecraft:dropper",
    ["###", "# #", "###"],
    {"#": "minecraft:cobblestone"},
    "minecraft:dropper")

_register_shaped("minecraft:dispenser",
    ["###", "#R#", "###"],
    {"#": "minecraft:cobblestone", "R": "minecraft:bow"},
    "minecraft:dispenser")

_register_shaped("minecraft:observer",
    ["CCC", "RRD", "CCC"],
    {"C": "minecraft:cobblestone", "R": "minecraft:redstone", "D": "minecraft:quartz"},
    "minecraft:observer")

_register_shaped("minecraft:piston",
    ["WWW", "#C#", "#R#"],
    {"W": "minecraft:oak_planks", "#": "minecraft:cobblestone", "C": "minecraft:iron_ingot", "R": "minecraft:redstone"},
    "minecraft:piston")

_register_shaped("minecraft:stone_button",
    ["#"],
    {"#": "minecraft:stone"},
    "minecraft:stone_button")

_register_shaped("minecraft:oak_pressure_plate",
    ["##"],
    {"#": "minecraft:oak_planks"},
    "minecraft:oak_pressure_plate")

_register_shaped("minecraft:stone_pressure_plate",
    ["##"],
    {"#": "minecraft:stone"},
    "minecraft:stone_pressure_plate")

_register_shaped("minecraft:tripwire_hook",
    ["I", "#", "|"],
    {"I": "minecraft:iron_ingot", "#": "minecraft:oak_planks", "|": "minecraft:stick"},
    "minecraft:tripwire_hook")


# --------------------------------------------------
# Shaped Recipes - Decorative
# --------------------------------------------------

_register_shaped("minecraft:bookshelf",
    ["###", "BBB", "###"],
    {"#": "minecraft:oak_planks", "B": "minecraft:book"},
    "minecraft:bookshelf")

_register_shaped("minecraft:torch",
    ["C", "|"],
    {"C": "minecraft:coal", "|": "minecraft:stick"},
    "minecraft:torch", 4)

_register_shaped("minecraft:glowstone",
    ["##", "##"],
    {"#": "minecraft:glowstone_dust"},
    "minecraft:glowstone")

_register_shaped("minecraft:white_bed",
    ["###", "|||"],
    {"#": "minecraft:white_wool", "|": "minecraft:oak_planks"},
    "minecraft:white_bed")

_register_shaped("minecraft:painting",
    ["###", "#X#", "###"],
    {"#": "minecraft:stick", "X": "minecraft:white_wool"},
    "minecraft:painting")

_register_shaped("minecraft:item_frame",
    ["###", "#X#", "###"],
    {"#": "minecraft:stick", "X": "minecraft:leather"},
    "minecraft:item_frame")

_register_shaped("minecraft:flower_pot",
    ["# #", " # "],
    {"#": "minecraft:brick"},
    "minecraft:flower_pot")

_register_shaped("minecraft:glass_pane",
    ["###", "###"],
    {"#": "minecraft:glass"},
    "minecraft:glass_pane", 16)


# --------------------------------------------------
# Shaped Recipes - Materials / Blocks
# --------------------------------------------------

_register_shaped("minecraft:stick",
    ["|", "|"],
    {"|": "minecraft:oak_planks"},
    "minecraft:stick", 4)

_register_shaped("minecraft:paper",
    ["###"],
    {"#": "minecraft:sugar_cane"},
    "minecraft:paper", 3)

_register_shaped("minecraft:book",
    [" # ", " P ", " W "],
    {"#": "minecraft:leather", "P": "minecraft:paper", "W": "minecraft:ink_sac"},
    "minecraft:book")

_register_shaped("minecraft:iron_block",
    ["###", "###", "###"],
    {"#": "minecraft:iron_ingot"},
    "minecraft:iron_block")

_register_shaped("minecraft:gold_block",
    ["###", "###", "###"],
    {"#": "minecraft:gold_ingot"},
    "minecraft:gold_block")

_register_shaped("minecraft:diamond_block",
    ["###", "###", "###"],
    {"#": "minecraft:diamond"},
    "minecraft:diamond_block")

_register_shaped("minecraft:emerald_block",
    ["###", "###", "###"],
    {"#": "minecraft:emerald"},
    "minecraft:emerald_block")

_register_shaped("minecraft:lapis_block",
    ["###", "###", "###"],
    {"#": "minecraft:lapis_lazuli"},
    "minecraft:lapis_block")

_register_shaped("minecraft:redstone_block",
    ["###", "###", "###"],
    {"#": "minecraft:redstone"},
    "minecraft:redstone_block")

_register_shaped("minecraft:coal_block",
    ["###", "###", "###"],
    {"#": "minecraft:coal"},
    "minecraft:coal_block")

_register_shaped("minecraft:quartz_block",
    ["##", "##"],
    {"#": "minecraft:quartz"},
    "minecraft:quartz_block")

_register_shaped("minecraft:hay_block",
    ["###", "###", "###"],
    {"#": "minecraft:wheat"},
    "minecraft:hay_block")

_register_shaped("minecraft:melon_block",
    ["###", "###", "###"],
    {"#": "minecraft:melon_slice"},
    "minecraft:melon_block")

_register_shaped("minecraft:gold_ingot_from_nuggets",
    ["###", "###", "###"],
    {"#": "minecraft:gold_nugget"},
    "minecraft:gold_ingot")

_register_shaped("minecraft:iron_ingot_from_nuggets",
    ["###", "###", "###"],
    {"#": "minecraft:iron_nugget"},
    "minecraft:iron_ingot")


# --------------------------------------------------
# Shaped Recipes - Food
# --------------------------------------------------

_register_shaped("minecraft:bread",
    ["###"],
    {"#": "minecraft:wheat"},
    "minecraft:bread")

_register_shaped("minecraft:golden_apple",
    ["###", "#X#", "###"],
    {"#": "minecraft:gold_ingot", "X": "minecraft:apple"},
    "minecraft:golden_apple")

_register_shaped("minecraft:cookie",
    ["#X#"],
    {"#": "minecraft:wheat", "X": "minecraft:cocoa_beans"},
    "minecraft:cookie", 8)

_register_shaped("minecraft:pumpkin_pie",
    ["#X", "Y "],
    {"#": "minecraft:pumpkin", "X": "minecraft:egg", "Y": "minecraft:sugar"},
    "minecraft:pumpkin_pie")

_register_shaped("minecraft:mushroom_stew",
    [" # ", " X ", " Y "],
    {"#": "minecraft:red_mushroom", "X": "minecraft:brown_mushroom", "Y": "minecraft:bowl"},
    "minecraft:mushroom_stew")


# --------------------------------------------------
# Shapeless Recipes
# --------------------------------------------------

_register_shapeless("minecraft:flint_and_steel",
    ["minecraft:iron_ingot", "minecraft:flint"],
    "minecraft:flint_and_steel")

_register_shapeless("minecraft:fire_charge",
    ["minecraft:blaze_powder", "minecraft:coal", "minecraft:gunpowder"],
    "minecraft:fire_charge", 3)

_register_shapeless("minecraft:magma_cream",
    ["minecraft:blaze_powder", "minecraft:slime_ball"],
    "minecraft:magma_cream")

_register_shapeless("minecraft:bone_meal",
    ["minecraft:bone"],
    "minecraft:bone_meal", 3)

_register_shapeless("minecraft:sugar",
    ["minecraft:sugar_cane"],
    "minecraft:sugar")

_register_shapeless("minecraft:blaze_powder",
    ["minecraft:blaze_rod"],
    "minecraft:blaze_powder", 2)

# Dye recipes
_register_shapeless("minecraft:black_dye",
    ["minecraft:ink_sac"],
    "minecraft:black_dye")

_register_shapeless("minecraft:brown_dye",
    ["minecraft:cocoa_beans"],
    "minecraft:brown_dye")

_register_shapeless("minecraft:white_dye",
    ["minecraft:bone_meal"],
    "minecraft:white_dye")

_register_shapeless("minecraft:blue_dye",
    ["minecraft:lapis_lazuli"],
    "minecraft:blue_dye")

_register_shapeless("minecraft:red_dye",
    ["minecraft:rose_bush"],
    "minecraft:red_dye", 2)

_register_shapeless("minecraft:yellow_dye",
    ["minecraft:dandelion"],
    "minecraft:yellow_dye")

_register_shapeless("minecraft:green_dye",
    ["minecraft:cactus"],
    "minecraft:green_dye")

_register_shapeless("minecraft:orange_dye",
    ["minecraft:red_dye", "minecraft:yellow_dye"],
    "minecraft:orange_dye", 2)

_register_shapeless("minecraft:light_blue_dye",
    ["minecraft:blue_dye", "minecraft:white_dye"],
    "minecraft:light_blue_dye", 2)

_register_shapeless("minecraft:cyan_dye",
    ["minecraft:blue_dye", "minecraft:green_dye"],
    "minecraft:cyan_dye", 2)

_register_shapeless("minecraft:magenta_dye",
    ["minecraft:blue_dye", "minecraft:red_dye", "minecraft:white_dye"],
    "minecraft:magenta_dye", 3)

_register_shapeless("minecraft:purple_dye",
    ["minecraft:blue_dye", "minecraft:red_dye"],
    "minecraft:purple_dye", 2)

_register_shapeless("minecraft:pink_dye",
    ["minecraft:red_dye", "minecraft:white_dye"],
    "minecraft:pink_dye", 2)

_register_shapeless("minecraft:light_gray_dye",
    ["minecraft:black_dye", "minecraft:white_dye", "minecraft:white_dye"],
    "minecraft:light_gray_dye", 3)

_register_shapeless("minecraft:gray_dye",
    ["minecraft:black_dye", "minecraft:white_dye"],
    "minecraft:gray_dye", 2)

_register_shapeless("minecraft:lime_dye",
    ["minecraft:green_dye", "minecraft:white_dye"],
    "minecraft:lime_dye", 2)

# Wood from logs
_register_shapeless("minecraft:oak_planks_from_log",
    ["minecraft:oak_log"],
    "minecraft:oak_planks", 4)

_register_shapeless("minecraft:spruce_planks_from_log",
    ["minecraft:spruce_log"],
    "minecraft:spruce_planks", 4)

_register_shapeless("minecraft:birch_planks_from_log",
    ["minecraft:birch_log"],
    "minecraft:birch_planks", 4)

_register_shapeless("minecraft:jungle_planks_from_log",
    ["minecraft:jungle_log"],
    "minecraft:jungle_planks", 4)

_register_shapeless("minecraft:acacia_planks_from_log",
    ["minecraft:acacia_log"],
    "minecraft:acacia_planks", 4)

_register_shapeless("minecraft:dark_oak_planks_from_log",
    ["minecraft:dark_oak_log"],
    "minecraft:dark_oak_planks", 4)

_register_shapeless("minecraft:mangrove_planks_from_log",
    ["minecraft:mangrove_log"],
    "minecraft:mangrove_planks", 4)

_register_shapeless("minecraft:bamboo_planks_from_log",
    ["minecraft:bamboo_block"],
    "minecraft:bamboo_planks", 2)

# Unpacking blocks to items
_register_shapeless("minecraft:wheat_from_hay",
    ["minecraft:hay_block"],
    "minecraft:wheat", 9)

_register_shapeless("minecraft:iron_nugget_from_ingot",
    ["minecraft:iron_ingot"],
    "minecraft:iron_nugget", 9)

_register_shapeless("minecraft:gold_nugget_from_ingot",
    ["minecraft:gold_ingot"],
    "minecraft:gold_nugget", 9)

_register_shapeless("minecraft:iron_ingot_from_nuggets",
    ["minecraft:iron_nugget"] * 9,
    "minecraft:iron_ingot")

_register_shapeless("minecraft:gold_ingot_from_nuggets",
    ["minecraft:gold_nugget"] * 9,
    "minecraft:gold_ingot")

_register_shapeless("minecraft:coal_from_block",
    ["minecraft:coal_block"],
    "minecraft:coal", 9)

_register_shapeless("minecraft:iron_ingot_from_block",
    ["minecraft:iron_block"],
    "minecraft:iron_ingot", 9)

_register_shapeless("minecraft:gold_ingot_from_block",
    ["minecraft:gold_block"],
    "minecraft:gold_ingot", 9)

_register_shapeless("minecraft:diamond_from_block",
    ["minecraft:diamond_block"],
    "minecraft:diamond", 9)

_register_shapeless("minecraft:emerald_from_block",
    ["minecraft:emerald_block"],
    "minecraft:emerald", 9)

_register_shapeless("minecraft:lapis_from_block",
    ["minecraft:lapis_block"],
    "minecraft:lapis_lazuli", 9)

_register_shapeless("minecraft:redstone_from_block",
    ["minecraft:redstone_block"],
    "minecraft:redstone", 9)

_register_shapeless("minecraft:quartz_from_block",
    ["minecraft:quartz_block"],
    "minecraft:quartz", 4)

# Seeds
_register_shapeless("minecraft:melon_seeds",
    ["minecraft:melon_slice"],
    "minecraft:melon_seeds")

_register_shapeless("minecraft:pumpkin_seeds",
    ["minecraft:pumpkin"],
    "minecraft:pumpkin_seeds", 4)

_register_shapeless("minecraft:beetroot_seeds",
    ["minecraft:beetroot"],
    "minecraft:beetroot_seeds")

# Misc
_register_shapeless("minecraft:charcoal_from_log",
    ["minecraft:oak_log", "minecraft:coal"],
    "minecraft:charcoal")

_register_shapeless("minecraft:melon_seeds_from_slice",
    ["minecraft:melon_slice"],
    "minecraft:melon_seeds")

_register_shapeless("minecraft:ink_sac_from_black_dye",
    ["minecraft:black_dye"],
    "minecraft:ink_sac")


# --------------------------------------------------
# Smelting Recipes - Ores -> Ingots
# --------------------------------------------------

_register_smelting("minecraft:iron_ingot_from_smelting",
    "minecraft:iron_ore", "minecraft:iron_ingot", xp=0.7, cook_time=200)

_register_smelting("minecraft:gold_ingot_from_smelting",
    "minecraft:gold_ore", "minecraft:gold_ingot", xp=1.0, cook_time=200)

_register_smelting("minecraft:copper_ingot_from_smelting",
    "minecraft:copper_ore", "minecraft:copper_ingot", xp=0.7, cook_time=200)

_register_smelting("minecraft:iron_ingot_from_deepslate",
    "minecraft:deepslate_iron_ore", "minecraft:iron_ingot", xp=0.7, cook_time=200)

_register_smelting("minecraft:gold_ingot_from_deepslate",
    "minecraft:deepslate_gold_ore", "minecraft:gold_ingot", xp=1.0, cook_time=200)

_register_smelting("minecraft:copper_ingot_from_deepslate",
    "minecraft:deepslate_copper_ore", "minecraft:copper_ingot", xp=0.7, cook_time=200)

_register_smelting("minecraft:iron_ingot_from_raw",
    "minecraft:raw_iron", "minecraft:iron_ingot", xp=0.7, cook_time=200)

_register_smelting("minecraft:gold_ingot_from_raw",
    "minecraft:raw_gold", "minecraft:gold_ingot", xp=1.0, cook_time=200)

_register_smelting("minecraft:copper_ingot_from_raw",
    "minecraft:raw_copper", "minecraft:copper_ingot", xp=0.7, cook_time=200)


# --------------------------------------------------
# Smelting Recipes - Food
# --------------------------------------------------

_register_smelting("minecraft:cooked_beef_from_smelting",
    "minecraft:raw_beef", "minecraft:cooked_beef", xp=0.35, cook_time=200)

_register_smelting("minecraft:cooked_porkchop_from_smelting",
    "minecraft:raw_porkchop", "minecraft:cooked_porkchop", xp=0.35, cook_time=200)

_register_smelting("minecraft:cooked_chicken_from_smelting",
    "minecraft:raw_chicken", "minecraft:cooked_chicken", xp=0.35, cook_time=200)

_register_smelting("minecraft:cooked_cod_from_smelting",
    "minecraft:raw_cod", "minecraft:cooked_cod", xp=0.35, cook_time=200)

_register_smelting("minecraft:cooked_salmon_from_smelting",
    "minecraft:raw_salmon", "minecraft:cooked_salmon", xp=0.35, cook_time=200)

_register_smelting("minecraft:baked_potato_from_smelting",
    "minecraft:potato", "minecraft:baked_potato", xp=0.35, cook_time=200)

_register_smelting("minecraft:dried_kelp_from_smelting",
    "minecraft:kelp", "minecraft:dried_kelp", xp=0.1, cook_time=200)


# --------------------------------------------------
# Smelting Recipes - Blocks
# --------------------------------------------------

_register_smelting("minecraft:stone_from_cobblestone",
    "minecraft:cobblestone", "minecraft:stone", xp=0.1, cook_time=200)

_register_smelting("minecraft:smooth_stone",
    "minecraft:stone", "minecraft:smooth_stone", xp=0.1, cook_time=200)

_register_smelting("minecraft:glass_from_sand",
    "minecraft:sand", "minecraft:glass", xp=0.1, cook_time=200)

_register_smelting("minecraft:brick",
    "minecraft:clay_ball", "minecraft:brick", xp=0.3, cook_time=200)

_register_smelting("minecraft:charcoal_from_smelting",
    "minecraft:oak_log", "minecraft:charcoal", xp=0.15, cook_time=200)

_register_smelting("minecraft:terracotta",
    "minecraft:clay", "minecraft:terracotta", xp=0.35, cook_time=200)

_register_smelting("minecraft:cracked_stone_bricks",
    "minecraft:stone_bricks", "minecraft:cracked_stone_bricks", xp=0.1, cook_time=200)

_register_smelting("minecraft:cracked_deepslate_bricks",
    "minecraft:deepslate_bricks", "minecraft:cracked_deepslate_bricks", xp=0.1, cook_time=200)

_register_smelting("minecraft:cracked_deepslate_tiles",
    "minecraft:deepslate_tiles", "minecraft:cracked_deepslate_tiles", xp=0.1, cook_time=200)

_register_smelting("minecraft:smooth_sandstone",
    "minecraft:sandstone", "minecraft:smooth_sandstone", xp=0.1, cook_time=200)

_register_smelting("minecraft:smooth_quartz",
    "minecraft:quartz_block", "minecraft:smooth_quartz", xp=0.1, cook_time=200)

_register_smelting("minecraft:smooth_red_sandstone",
    "minecraft:red_sandstone", "minecraft:smooth_red_sandstone", xp=0.1, cook_time=200)

_register_smelting("minecraft:glass_from_red_sand",
    "minecraft:red_sand", "minecraft:glass", xp=0.1, cook_time=200)

_register_smelting("minecraft:cracked_nether_bricks",
    "minecraft:nether_bricks", "minecraft:cracked_nether_bricks", xp=0.1, cook_time=200)

_register_smelting("minecraft:cracked_polished_blackstone_bricks",
    "minecraft:polished_blackstone_bricks", "minecraft:cracked_polished_blackstone_bricks",
    xp=0.1, cook_time=200)

# Nether
_register_smelting("minecraft:netherite_ingot_from_smelting",
    "minecraft:ancient_debris", "minecraft:netherite_scrap", xp=2.0, cook_time=200)

_register_smelting("minecraft:netherite_ingot_from_ancient",
    "minecraft:ancient_debris", "minecraft:netherite_scrap", xp=2.0, cook_time=200)


# --------------------------------------------------
# Smelting Recipes - Blast Furnace (2x faster)
# --------------------------------------------------

# Same recipes as furnace but cook_time halved
_register_smelting("minecraft:blast_iron_ingot",
    "minecraft:iron_ore", "minecraft:iron_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_gold_ingot",
    "minecraft:gold_ore", "minecraft:gold_ingot", xp=1.0, cook_time=100)

_register_smelting("minecraft:blast_copper_ingot",
    "minecraft:copper_ore", "minecraft:copper_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_deepslate_iron",
    "minecraft:deepslate_iron_ore", "minecraft:iron_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_deepslate_gold",
    "minecraft:deepslate_gold_ore", "minecraft:gold_ingot", xp=1.0, cook_time=100)

_register_smelting("minecraft:blast_deepslate_copper",
    "minecraft:deepslate_copper_ore", "minecraft:copper_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_raw_iron",
    "minecraft:raw_iron", "minecraft:iron_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_raw_gold",
    "minecraft:raw_gold", "minecraft:gold_ingot", xp=1.0, cook_time=100)

_register_smelting("minecraft:blast_raw_copper",
    "minecraft:raw_copper", "minecraft:copper_ingot", xp=0.7, cook_time=100)

_register_smelting("minecraft:blast_netherite_scrap",
    "minecraft:ancient_debris", "minecraft:netherite_scrap", xp=2.0, cook_time=100)


# --------------------------------------------------
# Smelting Recipes - Smoker (2x faster food)
# --------------------------------------------------

_register_smelting("minecraft:smoker_cooked_beef",
    "minecraft:raw_beef", "minecraft:cooked_beef", xp=0.35, cook_time=100)

_register_smelting("minecraft:smoker_cooked_porkchop",
    "minecraft:raw_porkchop", "minecraft:cooked_porkchop", xp=0.35, cook_time=100)

_register_smelting("minecraft:smoker_cooked_chicken",
    "minecraft:raw_chicken", "minecraft:cooked_chicken", xp=0.35, cook_time=100)

_register_smelting("minecraft:smoker_cooked_cod",
    "minecraft:raw_cod", "minecraft:cooked_cod", xp=0.35, cook_time=100)

_register_smelting("minecraft:smoker_cooked_salmon",
    "minecraft:raw_salmon", "minecraft:cooked_salmon", xp=0.35, cook_time=100)

_register_smelting("minecraft:smoker_baked_potato",
    "minecraft:potato", "minecraft:baked_potato", xp=0.35, cook_time=100)


# --------------------------------------------------
# Stonecutting Recipes
# --------------------------------------------------

# Stone variants
_register_stonecutting("minecraft:stone_to_stone_bricks",
    "minecraft:stone", "minecraft:stone_bricks")

_register_stonecutting("minecraft:stone_to_chiseled_stone_bricks",
    "minecraft:stone", "minecraft:chiseled_stone_bricks")

_register_stonecutting("minecraft:stone_to_smooth_stone",
    "minecraft:stone", "minecraft:smooth_stone")

_register_stonecutting("minecraft:stone_to_stone_slab",
    "minecraft:stone", "minecraft:stone_slab", 2)

_register_stonecutting("minecraft:stone_to_stone_brick_slab",
    "minecraft:stone", "minecraft:stone_brick_slab", 2)

_register_stonecutting("minecraft:stone_to_stone_stairs",
    "minecraft:stone", "minecraft:stone_stairs")

_register_stonecutting("minecraft:stone_to_stone_brick_stairs",
    "minecraft:stone", "minecraft:stone_brick_stairs")

# Cobblestone
_register_stonecutting("minecraft:cobblestone_to_stone",
    "minecraft:cobblestone", "minecraft:stone")

_register_stonecutting("minecraft:cobblestone_to_stone_bricks",
    "minecraft:cobblestone", "minecraft:stone_bricks")

_register_stonecutting("minecraft:cobblestone_to_cobblestone_slab",
    "minecraft:cobblestone", "minecraft:cobblestone_slab", 2)

_register_stonecutting("minecraft:cobblestone_to_cobblestone_stairs",
    "minecraft:cobblestone", "minecraft:cobblestone_stairs")

_register_stonecutting("minecraft:cobblestone_to_stone_brick_stairs",
    "minecraft:cobblestone", "minecraft:stone_brick_stairs")

# Granite
_register_stonecutting("minecraft:granite_to_polished_granite",
    "minecraft:granite", "minecraft:polished_granite")

_register_stonecutting("minecraft:granite_to_granite_slab",
    "minecraft:granite", "minecraft:granite_slab", 2)

_register_stonecutting("minecraft:granite_to_granite_stairs",
    "minecraft:granite", "minecraft:granite_stairs")

_register_stonecutting("minecraft:granite_to_polished_granite_slab",
    "minecraft:granite", "minecraft:polished_granite_slab", 2)

_register_stonecutting("minecraft:granite_to_polished_granite_stairs",
    "minecraft:granite", "minecraft:polished_granite_stairs")

# Diorite
_register_stonecutting("minecraft:diorite_to_polished_diorite",
    "minecraft:diorite", "minecraft:polished_diorite")

_register_stonecutting("minecraft:diorite_to_diorite_slab",
    "minecraft:diorite", "minecraft:diorite_slab", 2)

_register_stonecutting("minecraft:diorite_to_diorite_stairs",
    "minecraft:diorite", "minecraft:diorite_stairs")

_register_stonecutting("minecraft:diorite_to_polished_diorite_slab",
    "minecraft:diorite", "minecraft:polished_diorite_slab", 2)

_register_stonecutting("minecraft:diorite_to_polished_diorite_stairs",
    "minecraft:diorite", "minecraft:polished_diorite_stairs")

# Andesite
_register_stonecutting("minecraft:andesite_to_polished_andesite",
    "minecraft:andesite", "minecraft:polished_andesite")

_register_stonecutting("minecraft:andesite_to_andesite_slab",
    "minecraft:andesite", "minecraft:andesite_slab", 2)

_register_stonecutting("minecraft:andesite_to_andesite_stairs",
    "minecraft:andesite", "minecraft:andesite_stairs")

_register_stonecutting("minecraft:andesite_to_polished_andesite_slab",
    "minecraft:andesite", "minecraft:polished_andesite_slab", 2)

_register_stonecutting("minecraft:andesite_to_polished_andesite_stairs",
    "minecraft:andesite", "minecraft:polished_andesite_stairs")

# Stone Bricks
_register_stonecutting("minecraft:stone_bricks_to_stone_brick_slab",
    "minecraft:stone_bricks", "minecraft:stone_brick_slab", 2)

_register_stonecutting("minecraft:stone_bricks_to_stone_brick_stairs",
    "minecraft:stone_bricks", "minecraft:stone_brick_stairs")

_register_stonecutting("minecraft:stone_bricks_to_chiseled_stone_bricks",
    "minecraft:stone_bricks", "minecraft:chiseled_stone_bricks")

# Deepslate
_register_stonecutting("minecraft:deepslate_to_cobbled_deepslate",
    "minecraft:deepslate", "minecraft:cobbled_deepslate")

_register_stonecutting("minecraft:deepslate_to_polished_deepslate",
    "minecraft:deepslate", "minecraft:polished_deepslate")

_register_stonecutting("minecraft:deepslate_to_deepslate_bricks",
    "minecraft:deepslate", "minecraft:deepslate_bricks")

_register_stonecutting("minecraft:deepslate_to_deepslate_tiles",
    "minecraft:deepslate", "minecraft:deepslate_tiles")

_register_stonecutting("minecraft:deepslate_to_deepslate_slab",
    "minecraft:deepslate", "minecraft:deepslate_slab", 2)

_register_stonecutting("minecraft:deepslate_to_deepslate_brick_slab",
    "minecraft:deepslate", "minecraft:deepslate_brick_slab", 2)

_register_stonecutting("minecraft:deepslate_to_deepslate_tile_slab",
    "minecraft:deepslate", "minecraft:deepslate_tile_slab", 2)

_register_stonecutting("minecraft:deepslate_to_deepslate_stairs",
    "minecraft:deepslate", "minecraft:deepslate_stairs")

_register_stonecutting("minecraft:deepslate_to_deepslate_brick_stairs",
    "minecraft:deepslate", "minecraft:deepslate_brick_stairs")

_register_stonecutting("minecraft:deepslate_to_deepslate_tile_stairs",
    "minecraft:deepslate", "minecraft:deepslate_tile_stairs")

_register_stonecutting("minecraft:deepslate_to_chiseled_deepslate",
    "minecraft:deepslate", "minecraft:chiseled_deepslate")

# Bricks
_register_stonecutting("minecraft:bricks_to_brick_slab",
    "minecraft:bricks", "minecraft:brick_slab", 2)

_register_stonecutting("minecraft:bricks_to_brick_stairs",
    "minecraft:bricks", "minecraft:brick_stairs")

# Sandstone
_register_stonecutting("minecraft:sandstone_to_sandstone_slab",
    "minecraft:sandstone", "minecraft:sandstone_slab", 2)

_register_stonecutting("minecraft:sandstone_to_sandstone_stairs",
    "minecraft:sandstone", "minecraft:sandstone_stairs")

_register_stonecutting("minecraft:sandstone_to_cut_sandstone",
    "minecraft:sandstone", "minecraft:cut_sandstone")

_register_stonecutting("minecraft:sandstone_to_chiseled_sandstone",
    "minecraft:sandstone", "minecraft:chiseled_sandstone")

# Quartz
_register_stonecutting("minecraft:quartz_block_to_quartz_slab",
    "minecraft:quartz_block", "minecraft:quartz_slab", 2)

_register_stonecutting("minecraft:quartz_block_to_quartz_stairs",
    "minecraft:quartz_block", "minecraft:quartz_stairs")

_register_stonecutting("minecraft:quartz_block_to_chiseled_quartz",
    "minecraft:quartz_block", "minecraft:chiseled_quartz_block")

_register_stonecutting("minecraft:quartz_block_to_quartz_pillar",
    "minecraft:quartz_block", "minecraft:quartz_pillar")

_register_stonecutting("minecraft:quartz_block_to_smooth_quartz",
    "minecraft:quartz_block", "minecraft:smooth_quartz")

# Nether Bricks
_register_stonecutting("minecraft:nether_bricks_to_nether_brick_slab",
    "minecraft:nether_bricks", "minecraft:nether_brick_slab", 2)

_register_stonecutting("minecraft:nether_bricks_to_nether_brick_stairs",
    "minecraft:nether_bricks", "minecraft:nether_brick_stairs")

# Blackstone
_register_stonecutting("minecraft:blackstone_to_polished_blackstone",
    "minecraft:blackstone", "minecraft:polished_blackstone")

_register_stonecutting("minecraft:blackstone_to_blackstone_slab",
    "minecraft:blackstone", "minecraft:blackstone_slab", 2)

_register_stonecutting("minecraft:blackstone_to_blackstone_stairs",
    "minecraft:blackstone", "minecraft:blackstone_stairs")

_register_stonecutting("minecraft:blackstone_to_polished_blackstone_slab",
    "minecraft:blackstone", "minecraft:polished_blackstone_slab", 2)

_register_stonecutting("minecraft:blackstone_to_polished_blackstone_stairs",
    "minecraft:blackstone", "minecraft:polished_blackstone_stairs")

_register_stonecutting("minecraft:blackstone_to_polished_blackstone_bricks",
    "minecraft:blackstone", "minecraft:polished_blackstone_bricks")

_register_stonecutting("minecraft:blackstone_to_chiseled_polished_blackstone",
    "minecraft:blackstone", "minecraft:chiseled_polished_blackstone")

# End Stone
_register_stonecutting("minecraft:end_stone_to_end_stone_bricks",
    "minecraft:end_stone", "minecraft:end_stone_bricks")

_register_stonecutting("minecraft:end_stone_to_end_stone_brick_slab",
    "minecraft:end_stone", "minecraft:end_stone_brick_slab", 2)

_register_stonecutting("minecraft:end_stone_to_end_stone_brick_stairs",
    "minecraft:end_stone", "minecraft:end_stone_brick_stairs")

# Copper
_register_stonecutting("minecraft:copper_block_to_cut_copper",
    "minecraft:copper_block", "minecraft:cut_copper")

_register_stonecutting("minecraft:copper_block_to_cut_copper_stairs",
    "minecraft:copper_block", "minecraft:cut_copper_stairs")

_register_stonecutting("minecraft:copper_block_to_cut_copper_slab",
    "minecraft:copper_block", "minecraft:cut_copper_slab", 2)


# --------------------------------------------------
# Smithing Recipes - Netherite Upgrade
# --------------------------------------------------

_register_smithing("minecraft:netherite_sword",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_sword",
    "minecraft:netherite_ingot",
    "minecraft:netherite_sword")

_register_smithing("minecraft:netherite_pickaxe",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_pickaxe",
    "minecraft:netherite_ingot",
    "minecraft:netherite_pickaxe")

_register_smithing("minecraft:netherite_axe",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_axe",
    "minecraft:netherite_ingot",
    "minecraft:netherite_axe")

_register_smithing("minecraft:netherite_shovel",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_shovel",
    "minecraft:netherite_ingot",
    "minecraft:netherite_shovel")

_register_smithing("minecraft:netherite_hoe",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_hoe",
    "minecraft:netherite_ingot",
    "minecraft:netherite_hoe")

_register_smithing("minecraft:netherite_helmet",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_helmet",
    "minecraft:netherite_ingot",
    "minecraft:netherite_helmet")

_register_smithing("minecraft:netherite_chestplate",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_chestplate",
    "minecraft:netherite_ingot",
    "minecraft:netherite_chestplate")

_register_smithing("minecraft:netherite_leggings",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_leggings",
    "minecraft:netherite_ingot",
    "minecraft:netherite_leggings")

_register_smithing("minecraft:netherite_boots",
    "minecraft:netherite_upgrade_smithing_template",
    "minecraft:diamond_boots",
    "minecraft:netherite_ingot",
    "minecraft:netherite_boots")


# --------------------------------------------------
# Smithing Recipes - Armor Trims (template-based)
# --------------------------------------------------

# Armor trim recipes use the armor trim smithing template
_ARMOR_PIECES = ["helmet", "chestplate", "leggings", "boots"]
_ARMOR_MATERIALS = ["iron", "golden", "diamond", "netherite"]
_TRIM_MATERIALS = [
    "minecraft:amethyst_shard", "minecraft:copper_ingot", "minecraft:diamond",
    "minecraft:emerald", "minecraft:gold_ingot", "minecraft:iron_ingot",
    "minecraft:lapis_lazuli", "minecraft:netherite_ingot", "minecraft:quartz",
    "minecraft:redstone",
]

# Register representative armor trim recipes (simplified - one per armor piece)
for _piece in _ARMOR_PIECES:
    for _material in _ARMOR_MATERIALS:
        _base = f"minecraft:{_material}_{_piece}"
        _name = f"minecraft:trimmed_{_material}_{_piece}"
        # Use first trim material as representative
        _register_smithing(_name,
            "minecraft:armor_trim_smithing_template",
            _base,
            "minecraft:amethyst_shard",
            _base)  # Result is same item with trim NBT


# --------------------------------------------------
# Fuel Values (burn time in ticks)
# --------------------------------------------------

FUEL_VALUES: dict[str, int] = {
    "minecraft:coal": 1600,
    "minecraft:charcoal": 1600,
    "minecraft:coal_block": 16000,
    "minecraft:stick": 100,
    "minecraft:oak_planks": 300,
    "minecraft:spruce_planks": 300,
    "minecraft:birch_planks": 300,
    "minecraft:jungle_planks": 300,
    "minecraft:acacia_planks": 300,
    "minecraft:dark_oak_planks": 300,
    "minecraft:mangrove_planks": 300,
    "minecraft:bamboo_planks": 300,
    "minecraft:oak_log": 300,
    "minecraft:spruce_log": 300,
    "minecraft:birch_log": 300,
    "minecraft:jungle_log": 300,
    "minecraft:acacia_log": 300,
    "minecraft:dark_oak_log": 300,
    "minecraft:mangrove_log": 300,
    "minecraft:oak_slab": 150,
    "minecraft:spruce_slab": 150,
    "minecraft:birch_slab": 150,
    "minecraft:jungle_slab": 150,
    "minecraft:acacia_slab": 150,
    "minecraft:dark_oak_slab": 150,
    "minecraft:mangrove_slab": 150,
    "minecraft:bamboo_slab": 150,
    "minecraft:oak_fence": 300,
    "minecraft:oak_fence_gate": 300,
    "minecraft:oak_door": 300,
    "minecraft:crafting_table": 300,
    "minecraft:chest": 300,
    "minecraft:bookshelf": 300,
    "minecraft:jukebox": 300,
    "minecraft:note_block": 300,
    "minecraft:wooden_pickaxe": 200,
    "minecraft:wooden_axe": 200,
    "minecraft:wooden_shovel": 200,
    "minecraft:wooden_sword": 200,
    "minecraft:wooden_hoe": 200,
    "minecraft:blaze_rod": 2400,
    "minecraft:lava_bucket": 20000,
    "minecraft:dried_kelp_block": 4000,
    "minecraft:bamboo": 50,
    "minecraft:carpet": 67,
    "minecraft:wool": 100,
    "minecraft:banner": 300,
    "minecraft:azalea": 100,
    "minecraft:flowering_azalea": 100,
    "minecraft:mangrove_roots": 300,
}


# --------------------------------------------------
# Crafting System Engine
# --------------------------------------------------

class CraftingSystem:
    """
    Handles crafting recipe matching and ingredient consumption.
    Supports 2x2 (inventory) and 3x3 (crafting table) grids,
    stonecutting, and smithing.
    """

    def check_crafting(self, grid: list[list[str]]) -> tuple[str, int] | None:
        """
        Check a crafting grid against all recipes.
        Grid is a 2D list of item IDs (empty cells = "minecraft:air" or "").
        Returns (result_item, result_count) or None if no match.
        """
        if not grid or not grid[0]:
            return None

        # Normalize grid: replace empty strings with air
        normalized = []
        for row in grid:
            normalized_row = []
            for cell in row:
                if not cell or cell == "minecraft:air":
                    normalized_row.append("")
                else:
                    normalized_row.append(cell)
            normalized.append(normalized_row)

        # Try shaped recipes first
        result = self._check_shaped(normalized)
        if result is not None:
            return result

        # Try shapeless recipes
        return self._check_shapeless(normalized)

    def _check_shaped(self, grid: list[list[str]]) -> tuple[str, int] | None:
        """Check against shaped recipes."""
        for recipe_name, recipe in CRAFTING_RECIPES.items():
            if recipe["type"] != "shaped":
                continue
            result = self._match_shaped_recipe(grid, recipe)
            if result is not None:
                return result
        return None

    def _match_shaped_recipe(self, grid: list[list[str]],
                              recipe: dict) -> tuple[str, int] | None:
        """Try to match a specific shaped recipe against the grid."""
        pattern = recipe["pattern"]
        key = recipe["key"]

        # Get grid dimensions
        grid_rows = len(grid)
        grid_cols = max(len(row) for row in grid) if grid else 0
        pattern_rows = len(pattern)
        pattern_cols = max(len(row) for row in pattern) if pattern else 0

        # Grid must be at least as large as pattern
        if grid_rows < pattern_rows or grid_cols < pattern_cols:
            return None

        # Try all possible offsets
        for offset_y in range(grid_rows - pattern_rows + 1):
            for offset_x in range(grid_cols - pattern_cols + 1):
                if self._try_shaped_at(grid, pattern, key, offset_x, offset_y,
                                        grid_rows, grid_cols):
                    return recipe["result"]

        return None

    def _try_shaped_at(self, grid: list[list[str]], pattern: list[str],
                        key: dict[str, str], offset_x: int, offset_y: int,
                        grid_rows: int, grid_cols: int) -> bool:
        """Try matching a shaped recipe at a specific offset."""
        # Check that all cells match the pattern
        for py, pattern_row in enumerate(pattern):
            for px, ch in enumerate(pattern_row):
                gx = offset_x + px
                gy = offset_y + py
                expected = key.get(ch, "") if ch != ' ' else ""
                actual = ""
                if gy < len(grid) and gx < len(grid[gy]):
                    actual = grid[gy][gx]
                if actual != expected:
                    return False

        # Check that cells outside the pattern are empty
        for gy in range(len(grid)):
            for gx in range(len(grid[gy])):
                # Is this cell covered by the pattern?
                py = gy - offset_y
                px = gx - offset_x
                if 0 <= py < len(pattern) and 0 <= px < len(pattern[py]):
                    continue  # Covered by pattern, already checked
                # Not covered by pattern - must be empty
                if grid[gy][gx] != "":
                    return False

        return True

    def _check_shapeless(self, grid: list[list[str]]) -> tuple[str, int] | None:
        """Check against shapeless recipes."""
        # Collect all non-empty items from the grid
        grid_items: list[str] = []
        for row in grid:
            for cell in row:
                if cell and cell != "minecraft:air":
                    grid_items.append(cell)

        if not grid_items:
            return None

        # Sort for comparison
        grid_items_sorted = sorted(grid_items)

        for recipe_name, recipe in CRAFTING_RECIPES.items():
            if recipe["type"] != "shapeless":
                continue
            ingredients = sorted(recipe["ingredients"])
            if ingredients == grid_items_sorted:
                return recipe["result"]

        return None

    def check_smelting(self, ingredient: str) -> tuple[str, float, int] | None:
        """
        Check a smelting recipe.
        Returns (result_item, xp, cook_time) or None.
        """
        for recipe_name, recipe in SMELTING_RECIPES.items():
            if recipe["ingredient"] == ingredient:
                result_item, result_count = recipe["result"]
                return (result_item, recipe["xp"], recipe["cook_time"])
        return None

    def check_stonecutting(self, ingredient: str) -> list[tuple[str, int]]:
        """
        Check stonecutting recipes for a given ingredient.
        Returns list of (result_item, result_count) tuples (multiple possible).
        """
        results = []
        for recipe_name, recipe in STONECUTTING_RECIPES.items():
            if recipe["ingredient"] == ingredient:
                result_item, result_count = recipe["result"]
                results.append((result_item, result_count))
        return results

    def check_smithing(self, template: str, base: str, addition: str) -> tuple[str, int] | None:
        """
        Check a smithing recipe.
        Returns (result_item, result_count) or None if no match.
        """
        for recipe_name, recipe in SMITHING_RECIPES.items():
            if (recipe["template"] == template and
                recipe["base"] == base and
                recipe["addition"] == addition):
                return recipe["result"]
        return None

    def get_fuel_burn_time(self, fuel_item: str) -> int:
        """Get the burn time in ticks for a fuel item."""
        return FUEL_VALUES.get(fuel_item, 0)

    def consume_ingredients(self, grid: list[list[str]]) -> list[list[str]]:
        """
        Consume one of each ingredient from the crafting grid.
        Returns the updated grid with consumed items removed.
        """
        result = []
        for row in grid:
            result_row = []
            for cell in row:
                # Each ingredient is consumed (replaced with air)
                if cell and cell != "minecraft:air":
                    result_row.append("")
                else:
                    result_row.append(cell)
            result.append(result_row)
        return result

    def check_2x2_crafting(self, slots: list[str]) -> tuple[str, int] | None:
        """
        Check a 2x2 crafting grid from the player inventory.
        slots is a list of 4 item IDs: [top-left, top-right, bottom-left, bottom-right]
        """
        grid = [
            [slots[0] if len(slots) > 0 else "", slots[1] if len(slots) > 1 else ""],
            [slots[2] if len(slots) > 2 else "", slots[3] if len(slots) > 3 else ""],
        ]
        return self.check_crafting(grid)

    def check_3x3_crafting(self, slots: list[str]) -> tuple[str, int] | None:
        """
        Check a 3x3 crafting grid from a crafting table.
        slots is a list of 9 item IDs in row-major order.
        """
        grid = [
            [slots[0] if len(slots) > 0 else "", slots[1] if len(slots) > 1 else "", slots[2] if len(slots) > 2 else ""],
            [slots[3] if len(slots) > 3 else "", slots[4] if len(slots) > 4 else "", slots[5] if len(slots) > 5 else ""],
            [slots[6] if len(slots) > 6 else "", slots[7] if len(slots) > 7 else "", slots[8] if len(slots) > 8 else ""],
        ]
        return self.check_crafting(grid)


# Global crafting system instance
crafting_system = CraftingSystem()
