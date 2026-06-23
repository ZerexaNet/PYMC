# ============================================================
# PyMC - Block Behavior System
# Block interaction behaviors, container management,
# and block hardness/mining properties
# Minecraft 1.21.1
# ============================================================

"""
Block behavior system implementing interactions for all block types.

Key classes:
  - BlockBehavior: Base class for block interaction behaviors
  - ContainerData: Data for block-based containers
  - ContainerManager: Manages all block-based containers
  - BLOCK_BEHAVIORS: Registry of block name -> behavior

Key behaviors:
  - ChestBehavior: Open chest inventory
  - CraftingTableBehavior: Open 3x3 crafting grid
  - FurnaceBehavior: Open furnace interface
  - AnvilBehavior: Open anvil interface
  - EnchantingTableBehavior: Open enchanting interface
  - DoorBehavior: Toggle door open/closed
  - TrapdoorBehavior: Toggle trapdoor open/closed
  - FenceGateBehavior: Toggle fence gate open/closed
  - BedBehavior: Set respawn / skip night
  - SignBehavior: Open sign editor
  - CakeBehavior: Consume slice
  - FarmlandBehavior: Trample on jump
  - TNTBehavior: Ignite on use with flint & steel
  - NoteBlockBehavior: Cycle note pitch on use
  - WaterBehavior / LavaBehavior: Fluid behaviors
"""

import logging
import random
from typing import Optional
from dataclasses import dataclass, field

from .blocks import (
    AIR, STONE, GRANITE, DIORITE, ANDESITE, GRASS_BLOCK, DIRT,
    COBBLESTONE, OAK_PLANKS, GLASS, SAND, OAK_LOG, TORCH,
    BEDROCK, WATER, LAVA, CHEST, CRAFTING_TABLE, FURNACE,
    FARMLAND, ANVIL, ENDER_CHEST, CAKE, OAK_DOOR, IRON_DOOR,
    OAK_SIGN, OAK_TRAPDOOR, IRON_TRAPDOOR, TRAPPED_CHEST,
    BLAST_FURNACE, REDSTONE_TORCH, CACTUS, WHITE_BED,
    OBSIDIAN,
)
from .chunk_io import STATE_ID_TO_BLOCK
from .inventory import ItemStack, encode_slot_entry

logger = logging.getLogger("PyMC.方块行为")


# --------------------------------------------------
# Block Hardness & Tool Requirements
# --------------------------------------------------

# Block name -> (hardness, preferred_tool, tool_tier_required)
BLOCK_HARDNESS: dict[str, tuple[float, str | None, str | None]] = {
    # Unbreakable
    "minecraft:bedrock": (-1.0, None, None),
    "minecraft:command_block": (-1.0, None, None),
    "minecraft:barrier": (-1.0, None, None),
    "minecraft:end_portal_frame": (-1.0, None, None),
    "minecraft:reinforced_deepslate": (-1.0, None, None),

    # Instant break (hardness < 0.5)
    "minecraft:air": (0.0, None, None),
    "minecraft:torch": (0.0, None, None),
    "minecraft:short_grass": (0.0, None, None),
    "minecraft:tall_grass": (0.0, None, None),
    "minecraft:fern": (0.0, None, None),
    "minecraft:dead_bush": (0.0, None, None),
    "minecraft:dandelion": (0.0, None, None),
    "minecraft:poppy": (0.0, None, None),
    "minecraft:redstone": (0.0, None, None),
    "minecraft:redstone_torch": (0.0, None, None),
    "minecraft:sugar_cane": (0.0, None, None),
    "minecraft:flower_pot": (0.0, None, None),

    # Soft blocks (dirt, sand, etc.)
    "minecraft:dirt": (0.5, "shovel", None),
    "minecraft:grass_block": (0.6, "shovel", None),
    "minecraft:coarse_dirt": (0.5, "shovel", None),
    "minecraft:podzol": (0.5, "shovel", None),
    "minecraft:sand": (0.5, "shovel", None),
    "minecraft:red_sand": (0.5, "shovel", None),
    "minecraft:gravel": (0.6, "shovel", None),
    "minecraft:clay": (0.6, "shovel", None),
    "minecraft:snow": (0.2, "shovel", None),
    "minecraft:snow_block": (0.2, "shovel", None),
    "minecraft:soul_sand": (0.5, "shovel", None),
    "minecraft:mycelium": (0.6, "shovel", None),
    "minecraft:farmland": (0.6, "shovel", None),
    "minecraft:mud": (0.5, "shovel", None),
    "minecraft:muddy_mangrove_roots": (0.5, "shovel", None),

    # Wood blocks
    "minecraft:oak_planks": (2.0, "axe", None),
    "minecraft:spruce_planks": (2.0, "axe", None),
    "minecraft:birch_planks": (2.0, "axe", None),
    "minecraft:jungle_planks": (2.0, "axe", None),
    "minecraft:acacia_planks": (2.0, "axe", None),
    "minecraft:dark_oak_planks": (2.0, "axe", None),
    "minecraft:mangrove_planks": (2.0, "axe", None),
    "minecraft:bamboo_planks": (2.0, "axe", None),
    "minecraft:oak_log": (2.0, "axe", None),
    "minecraft:spruce_log": (2.0, "axe", None),
    "minecraft:birch_log": (2.0, "axe", None),
    "minecraft:jungle_log": (2.0, "axe", None),
    "minecraft:acacia_log": (2.0, "axe", None),
    "minecraft:dark_oak_log": (2.0, "axe", None),
    "minecraft:mangrove_log": (2.0, "axe", None),
    "minecraft:chest": (2.5, "axe", None),
    "minecraft:crafting_table": (2.5, "axe", None),
    "minecraft:oak_fence": (2.0, "axe", None),
    "minecraft:oak_fence_gate": (2.0, "axe", None),
    "minecraft:oak_door": (3.0, "axe", None),
    "minecraft:ladder": (0.4, None, None),
    "minecraft:bookshelf": (1.5, "axe", None),

    # Stone blocks (need pickaxe)
    "minecraft:stone": (1.5, "pickaxe", "wooden"),
    "minecraft:granite": (1.5, "pickaxe", "wooden"),
    "minecraft:polished_granite": (1.5, "pickaxe", "wooden"),
    "minecraft:diorite": (1.5, "pickaxe", "wooden"),
    "minecraft:polished_diorite": (1.5, "pickaxe", "wooden"),
    "minecraft:andesite": (1.5, "pickaxe", "wooden"),
    "minecraft:polished_andesite": (1.5, "pickaxe", "wooden"),
    "minecraft:cobblestone": (2.0, "pickaxe", "wooden"),
    "minecraft:mossy_cobblestone": (2.0, "pickaxe", "wooden"),
    "minecraft:stone_bricks": (1.5, "pickaxe", "wooden"),
    "minecraft:smooth_stone": (2.0, "pickaxe", "wooden"),
    "minecraft:furnace": (3.5, "pickaxe", "wooden"),
    "minecraft:blast_furnace": (3.5, "pickaxe", "wooden"),
    "minecraft:smoker": (3.5, "pickaxe", "wooden"),
    "minecraft:stonecutter": (3.5, "pickaxe", "wooden"),

    # Deepslate (harder, needs iron+ for ores)
    "minecraft:deepslate": (3.0, "pickaxe", "wooden"),
    "minecraft:cobbled_deepslate": (3.5, "pickaxe", "wooden"),
    "minecraft:polished_deepslate": (3.5, "pickaxe", "wooden"),
    "minecraft:deepslate_bricks": (3.5, "pickaxe", "wooden"),
    "minecraft:deepslate_tiles": (3.5, "pickaxe", "wooden"),

    # Ores
    "minecraft:coal_ore": (3.0, "pickaxe", "wooden"),
    "minecraft:deepslate_coal_ore": (4.5, "pickaxe", "wooden"),
    "minecraft:iron_ore": (3.0, "pickaxe", "stone"),
    "minecraft:deepslate_iron_ore": (4.5, "pickaxe", "stone"),
    "minecraft:copper_ore": (3.0, "pickaxe", "stone"),
    "minecraft:deepslate_copper_ore": (4.5, "pickaxe", "stone"),
    "minecraft:gold_ore": (3.0, "pickaxe", "iron"),
    "minecraft:deepslate_gold_ore": (4.5, "pickaxe", "iron"),
    "minecraft:redstone_ore": (3.0, "pickaxe", "iron"),
    "minecraft:deepslate_redstone_ore": (4.5, "pickaxe", "iron"),
    "minecraft:lapis_ore": (3.0, "pickaxe", "stone"),
    "minecraft:deepslate_lapis_ore": (4.5, "pickaxe", "stone"),
    "minecraft:diamond_ore": (3.0, "pickaxe", "iron"),
    "minecraft:deepslate_diamond_ore": (4.5, "pickaxe", "iron"),
    "minecraft:emerald_ore": (3.0, "pickaxe", "iron"),
    "minecraft:deepslate_emerald_ore": (4.5, "pickaxe", "iron"),

    # Metal blocks
    "minecraft:iron_block": (5.0, "pickaxe", "stone"),
    "minecraft:gold_block": (3.0, "pickaxe", "iron"),
    "minecraft:diamond_block": (5.0, "pickaxe", "iron"),
    "minecraft:netherite_block": (50.0, "pickaxe", "diamond"),
    "minecraft:emerald_block": (5.0, "pickaxe", "iron"),
    "minecraft:lapis_block": (3.0, "pickaxe", "stone"),
    "minecraft:redstone_block": (5.0, "pickaxe", "wooden"),
    "minecraft:copper_block": (3.0, "pickaxe", "stone"),

    # Obsidian
    "minecraft:obsidian": (50.0, "pickaxe", "diamond"),
    "minecraft:crying_obsidian": (50.0, "pickaxe", "diamond"),

    # Functional blocks
    "minecraft:anvil": (5.0, "pickaxe", "wooden"),
    "minecraft:chipped_anvil": (5.0, "pickaxe", "wooden"),
    "minecraft:damaged_anvil": (5.0, "pickaxe", "wooden"),
    "minecraft:ender_chest": (22.5, "pickaxe", "wooden"),
    "minecraft:cauldron": (2.0, "pickaxe", "wooden"),
    "minecraft:hopper": (3.0, "pickaxe", "wooden"),
    "minecraft:piston": (1.5, "pickaxe", "wooden"),
    "minecraft:sticky_piston": (1.5, "pickaxe", "wooden"),
    "minecraft:dispenser": (3.5, "pickaxe", "wooden"),
    "minecraft:dropper": (3.5, "pickaxe", "wooden"),
    "minecraft:observer": (3.5, "pickaxe", "wooden"),
    "minecraft:repeater": (0.0, None, None),
    "minecraft:comparator": (0.0, None, None),
    "minecraft:enchanting_table": (5.0, "pickaxe", "wooden"),

    # Misc
    "minecraft:glass": (0.3, None, None),
    "minecraft:glowstone": (0.3, None, None),
    "minecraft:ice": (0.5, "pickaxe", None),
    "minecraft:packed_ice": (0.5, "pickaxe", None),
    "minecraft:blue_ice": (2.8, "pickaxe", None),
    "minecraft:iron_door": (5.0, "pickaxe", "wooden"),
    "minecraft:iron_trapdoor": (5.0, "pickaxe", "wooden"),

    # Nether blocks
    "minecraft:netherrack": (0.4, "pickaxe", "wooden"),
    "minecraft:nether_bricks": (2.0, "pickaxe", "wooden"),
    "minecraft:basalt": (1.25, "pickaxe", "wooden"),
    "minecraft:blackstone": (1.5, "pickaxe", "wooden"),
    "minecraft:ancient_debris": (30.0, "pickaxe", "diamond"),
    "minecraft:quartz_ore": (3.0, "pickaxe", "wooden"),

    # End blocks
    "minecraft:end_stone": (3.0, "pickaxe", "wooden"),
    "minecraft:end_stone_bricks": (3.0, "pickaxe", "wooden"),

    # Organic / plants
    "minecraft:oak_leaves": (0.2, "hoe", None),
    "minecraft:cactus": (0.4, None, None),
    "minecraft:pumpkin": (1.0, "axe", None),
    "minecraft:melon_block": (1.0, None, None),

    # Wool (shears)
    "minecraft:white_wool": (0.8, "shears", None),

    # Cake
    "minecraft:cake": (0.5, None, None),

    # Beds
    "minecraft:white_bed": (0.2, None, None),

    # TNT
    "minecraft:tnt": (0.0, None, None),

    # Fluids
    "minecraft:water": (100.0, None, None),
    "minecraft:lava": (100.0, None, None),

    # Sponge
    "minecraft:sponge": (0.6, "hoe", None),
    "minecraft:wet_sponge": (0.6, "hoe", None),

    # Rails
    "minecraft:rail": (0.7, "pickaxe", None),
    "minecraft:powered_rail": (0.7, "pickaxe", None),
    "minecraft:detector_rail": (0.7, "pickaxe", None),
    "minecraft:activator_rail": (0.7, "pickaxe", None),

    # Sign
    "minecraft:oak_sign": (1.0, "axe", None),
    "minecraft:oak_wall_sign": (1.0, "axe", None),

    # Trapdoor
    "minecraft:oak_trapdoor": (3.0, "axe", None),
    "minecraft:iron_trapdoor": (5.0, "pickaxe", "wooden"),

    # Note block
    "minecraft:note_block": (0.8, "axe", None),

    # Jukebox
    "minecraft:jukebox": (0.8, "axe", None),
}


# Tool tier ordering for tier requirements
_TIER_ORDER = {"wooden": 0, "stone": 1, "iron": 2, "diamond": 3, "golden": 0, "netherite": 4}


def get_block_hardness(block_name: str) -> float:
    """Get the hardness of a block. Returns 1.0 as default."""
    info = BLOCK_HARDNESS.get(block_name)
    if info is not None:
        return info[0]
    return 1.5  # Default for unknown blocks


def get_block_tool(block_name: str) -> str | None:
    """Get the preferred tool type for a block."""
    info = BLOCK_HARDNESS.get(block_name)
    if info is not None:
        return info[1]
    return None


def get_block_tier_required(block_name: str) -> str | None:
    """Get the minimum tool tier required to mine a block."""
    info = BLOCK_HARDNESS.get(block_name)
    if info is not None:
        return info[2]
    return None


def calculate_break_time(block_name: str, tool_item: ItemStack | None,
                          in_water: bool = False, on_ground: bool = True) -> float:
    """
    Calculate the time in seconds to break a block.

    Args:
        block_name: The block being mined
        tool_item: The tool being used (or None for bare hands)
        in_water: Whether the player is in water (5x slower)
        on_ground: Whether the player is on ground (affects mining)

    Returns:
        Time in seconds to break the block, or -1 if unbreakable
    """
    hardness = get_block_hardness(block_name)
    if hardness < 0:
        return -1.0  # Unbreakable

    preferred_tool = get_block_tool(block_name)
    tier_required = get_block_tier_required(block_name)

    # Base speed
    if hardness == 0:
        return 0.0

    speed_multiplier = 1.0

    # Tool bonus
    if tool_item is not None and not tool_item.is_empty:
        tool_type = tool_item.get_tool_type()
        tool_tier = tool_item.get_tool_tier()

        if tool_type == preferred_tool:
            # Correct tool: apply speed bonus
            speed_multiplier = tool_item.get_mining_speed()

            # Check tier requirement
            if tier_required is not None:
                tool_tier_level = _TIER_ORDER.get(tool_tier, 0) if tool_tier else 0
                required_tier_level = _TIER_ORDER.get(tier_required, 0)
                if tool_tier_level < required_tier_level:
                    # Can't mine with this tier - very slow
                    speed_multiplier = 1.0
        elif tool_type is not None:
            # Wrong tool type but still a tool
            speed_multiplier = 1.0

    # Calculate break time
    # Formula: break_time = hardness * 1.5 / speed_multiplier (simplified vanilla)
    if speed_multiplier > 1.0:
        break_time = hardness * 1.5 / speed_multiplier
    else:
        break_time = hardness * 5.0  # Without correct tool, 5x penalty

    # Water penalty
    if in_water:
        break_time *= 5.0

    # Not on ground penalty (slight)
    if not on_ground:
        break_time *= 1.5

    return max(0.05, break_time)


def can_harvest_block(block_name: str, tool_item: ItemStack | None) -> bool:
    """
    Check if a block can be harvested (drops items) with the given tool.
    Returns True if the block will drop items when broken.
    """
    if block_name == "minecraft:air":
        return False

    preferred_tool = get_block_tool(block_name)
    tier_required = get_block_tier_required(block_name)

    if preferred_tool is None:
        return True  # No tool required

    if tool_item is None or tool_item.is_empty:
        return False  # Needs a tool but has none

    tool_type = tool_item.get_tool_type()
    if tool_type != preferred_tool:
        return False  # Wrong tool type

    if tier_required is not None:
        tool_tier = tool_item.get_tool_tier()
        tool_tier_level = _TIER_ORDER.get(tool_tier, 0) if tool_tier else 0
        required_tier_level = _TIER_ORDER.get(tier_required, 0)
        if tool_tier_level < required_tier_level:
            return False  # Tier too low

    return True


# --------------------------------------------------
# Block Drop Table
# --------------------------------------------------

# Block name -> list of (item_name, count_min, count_max, requires_tool)
BLOCK_DROPS: dict[str, list[tuple[str, int, int, bool]]] = {
    # Stone-type blocks drop themselves or cobblestone
    "minecraft:stone": [("minecraft:cobblestone", 1, 1, True)],
    "minecraft:cobblestone": [("minecraft:cobblestone", 1, 1, True)],
    "minecraft:granite": [("minecraft:granite", 1, 1, True)],
    "minecraft:polished_granite": [("minecraft:polished_granite", 1, 1, True)],
    "minecraft:diorite": [("minecraft:diorite", 1, 1, True)],
    "minecraft:polished_diorite": [("minecraft:polished_diorite", 1, 1, True)],
    "minecraft:andesite": [("minecraft:andesite", 1, 1, True)],
    "minecraft:polished_andesite": [("minecraft:polished_andesite", 1, 1, True)],
    "minecraft:grass_block": [("minecraft:dirt", 1, 1, False)],
    "minecraft:dirt": [("minecraft:dirt", 1, 1, False)],
    "minecraft:coarse_dirt": [("minecraft:coarse_dirt", 1, 1, False)],
    "minecraft:podzol": [("minecraft:podzol", 1, 1, False)],
    "minecraft:oak_planks": [("minecraft:oak_planks", 1, 1, False)],
    "minecraft:sand": [("minecraft:sand", 1, 1, False)],
    "minecraft:red_sand": [("minecraft:red_sand", 1, 1, False)],
    "minecraft:gravel": [("minecraft:gravel", 1, 1, False)],
    "minecraft:glass": [],  # Drops nothing
    "minecraft:torch": [("minecraft:torch", 1, 1, False)],

    # Ores
    "minecraft:coal_ore": [("minecraft:coal", 1, 1, True)],
    "minecraft:deepslate_coal_ore": [("minecraft:coal", 1, 1, True)],
    "minecraft:iron_ore": [("minecraft:raw_iron", 1, 1, True)],
    "minecraft:deepslate_iron_ore": [("minecraft:raw_iron", 1, 1, True)],
    "minecraft:gold_ore": [("minecraft:raw_gold", 1, 1, True)],
    "minecraft:deepslate_gold_ore": [("minecraft:raw_gold", 1, 1, True)],
    "minecraft:diamond_ore": [("minecraft:diamond", 1, 1, True)],
    "minecraft:deepslate_diamond_ore": [("minecraft:diamond", 1, 1, True)],
    "minecraft:emerald_ore": [("minecraft:emerald", 1, 1, True)],
    "minecraft:deepslate_emerald_ore": [("minecraft:emerald", 1, 1, True)],
    "minecraft:lapis_ore": [("minecraft:lapis_lazuli", 4, 9, True)],
    "minecraft:deepslate_lapis_ore": [("minecraft:lapis_lazuli", 4, 9, True)],
    "minecraft:redstone_ore": [("minecraft:redstone", 4, 5, True)],
    "minecraft:deepslate_redstone_ore": [("minecraft:redstone", 4, 5, True)],
    "minecraft:copper_ore": [("minecraft:raw_copper", 2, 3, True)],
    "minecraft:deepslate_copper_ore": [("minecraft:raw_copper", 2, 3, True)],
    "minecraft:nether_gold_ore": [("minecraft:gold_nugget", 2, 6, True)],
    "minecraft:quartz_ore": [("minecraft:quartz", 1, 1, True)],

    # Metal blocks
    "minecraft:iron_block": [("minecraft:iron_block", 1, 1, True)],
    "minecraft:gold_block": [("minecraft:gold_block", 1, 1, True)],
    "minecraft:diamond_block": [("minecraft:diamond_block", 1, 1, True)],
    "minecraft:emerald_block": [("minecraft:emerald_block", 1, 1, True)],
    "minecraft:lapis_block": [("minecraft:lapis_block", 1, 1, True)],
    "minecraft:redstone_block": [("minecraft:redstone_block", 1, 1, True)],
    "minecraft:copper_block": [("minecraft:copper_block", 1, 1, True)],

    # Functional blocks
    "minecraft:chest": [("minecraft:chest", 1, 1, False)],
    "minecraft:crafting_table": [("minecraft:crafting_table", 1, 1, False)],
    "minecraft:furnace": [("minecraft:furnace", 1, 1, True)],
    "minecraft:blast_furnace": [("minecraft:blast_furnace", 1, 1, True)],
    "minecraft:anvil": [("minecraft:anvil", 1, 1, True)],
    "minecraft:ender_chest": [("minecraft:ender_chest", 1, 1, True)],
    "minecraft:cauldron": [("minecraft:cauldron", 1, 1, True)],
    "minecraft:hopper": [("minecraft:hopper", 1, 1, True)],
    "minecraft:piston": [("minecraft:piston", 1, 1, True)],
    "minecraft:sticky_piston": [("minecraft:sticky_piston", 1, 1, True)],
    "minecraft:dispenser": [("minecraft:dispenser", 1, 1, True)],
    "minecraft:dropper": [("minecraft:dropper", 1, 1, True)],
    "minecraft:observer": [("minecraft:observer", 1, 1, True)],
    "minecraft:enchanting_table": [("minecraft:enchanting_table", 1, 1, True)],

    # Decorative
    "minecraft:bookshelf": [("minecraft:book", 0, 3, False)],
    "minecraft:ice": [],  # Drops nothing without silk touch
    "minecraft:packed_ice": [("minecraft:packed_ice", 1, 1, True)],
    "minecraft:blue_ice": [("minecraft:blue_ice", 1, 1, True)],

    # Nether
    "minecraft:netherrack": [("minecraft:netherrack", 1, 1, True)],
    "minecraft:nether_bricks": [("minecraft:nether_bricks", 1, 1, True)],
    "minecraft:basalt": [("minecraft:basalt", 1, 1, True)],
    "minecraft:blackstone": [("minecraft:blackstone", 1, 1, True)],
    "minecraft:ancient_debris": [("minecraft:ancient_debris", 1, 1, True)],

    # End
    "minecraft:end_stone": [("minecraft:end_stone", 1, 1, True)],

    # Organic
    "minecraft:oak_leaves": [("minecraft:oak_sapling", 1, 1, False)],  # 5% chance
    "minecraft:white_wool": [("minecraft:white_wool", 1, 1, False)],
    "minecraft:cactus": [("minecraft:cactus", 1, 1, False)],

    # Beds drop themselves
    "minecraft:white_bed": [("minecraft:white_bed", 1, 1, False)],

    # TNT
    "minecraft:tnt": [("minecraft:tnt", 1, 1, False)],

    # Rails
    "minecraft:rail": [("minecraft:rail", 1, 1, True)],
    "minecraft:powered_rail": [("minecraft:powered_rail", 1, 1, True)],
    "minecraft:detector_rail": [("minecraft:detector_rail", 1, 1, True)],
    "minecraft:activator_rail": [("minecraft:activator_rail", 1, 1, True)],

    # Signs
    "minecraft:oak_sign": [("minecraft:oak_sign", 1, 1, False)],
    "minecraft:oak_wall_sign": [("minecraft:oak_sign", 1, 1, False)],

    # Deepslate
    "minecraft:deepslate": [("minecraft:cobbled_deepslate", 1, 1, True)],
    "minecraft:cobbled_deepslate": [("minecraft:cobbled_deepslate", 1, 1, True)],
    "minecraft:polished_deepslate": [("minecraft:polished_deepslate", 1, 1, True)],
    "minecraft:deepslate_bricks": [("minecraft:deepslate_bricks", 1, 1, True)],
    "minecraft:deepslate_tiles": [("minecraft:deepslate_tiles", 1, 1, True)],

    # Note block
    "minecraft:note_block": [("minecraft:note_block", 1, 1, False)],

    # Jukebox
    "minecraft:jukebox": [("minecraft:jukebox", 1, 1, False)],
}


def get_block_drops(block_name: str, tool_item: ItemStack | None = None) -> list[ItemStack]:
    """
    Get the items dropped when a block is broken.
    Returns a list of ItemStack objects.
    """
    drops = BLOCK_DROPS.get(block_name, [])

    if not drops:
        # Default: block drops itself if it can be harvested
        if can_harvest_block(block_name, tool_item):
            return [ItemStack(block_name, 1)]
        return []

    result = []
    for item_name, min_count, max_count, requires_tool in drops:
        if requires_tool and not can_harvest_block(block_name, tool_item):
            continue
        count = random.randint(min_count, max_count) if min_count != max_count else min_count
        if count > 0:
            result.append(ItemStack(item_name, count))

    return result


# --------------------------------------------------
# Block Behavior Base Class
# --------------------------------------------------

class BlockBehavior:
    """Base class for block interaction behaviors."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        """
        Called when player right-clicks a block.
        Return True if action was taken (prevents block placement).
        """
        return False

    @staticmethod
    async def on_place(conn, server, x: int, y: int, z: int,
                       face: int) -> bool:
        """
        Called when a block is placed.
        Return True if placement succeeded.
        """
        return True

    @staticmethod
    async def on_break(conn, server, x: int, y: int, z: int) -> list[ItemStack]:
        """Called when a block is broken. Return list of drops."""
        return []

    @staticmethod
    async def on_step_on(conn, server, x: int, y: int, z: int) -> None:
        """Called when an entity steps on this block."""
        pass

    @staticmethod
    async def on_projectile_hit(conn, server, x: int, y: int, z: int) -> None:
        """Called when a projectile hits this block."""
        pass

    @staticmethod
    def is_solid() -> bool:
        """Whether this block is solid (entities can't pass through)."""
        return True

    @staticmethod
    def is_transparent() -> bool:
        """Whether light passes through this block."""
        return False

    @staticmethod
    def get_hardness() -> float:
        """Block hardness value."""
        return 1.5

    @staticmethod
    def is_interactive() -> bool:
        """Whether this block has a right-click interaction."""
        return False


# --------------------------------------------------
# Container System
# --------------------------------------------------

@dataclass
class ContainerData:
    """Data for a block-based container."""
    type: str  # "chest", "furnace", "hopper", etc.
    items: list[ItemStack | None] = field(default_factory=list)
    viewers: set[int] = field(default_factory=set)  # Entity IDs of viewers

    # Furnace-specific
    burn_time: int = 0       # Remaining fuel burn time
    cook_time: int = 0       # Current cook progress
    cook_time_total: int = 0 # Total cook time for current recipe

    def __post_init__(self):
        if not self.items:
            if self.type == "chest":
                self.items = [None] * 27
            elif self.type == "furnace":
                self.items = [None] * 3  # 0=input, 1=fuel, 2=output
            elif self.type == "blast_furnace":
                self.items = [None] * 3
            elif self.type == "smoker":
                self.items = [None] * 3
            elif self.type == "hopper":
                self.items = [None] * 5
            elif self.type == "dropper" or self.type == "dispenser":
                self.items = [None] * 9
            else:
                self.items = [None] * 27


class ContainerManager:
    """Manages all block-based containers in the world."""

    def __init__(self):
        self.containers: dict[tuple[int, int, int], ContainerData] = {}
        self._next_window_id = 1

    def get_container(self, x: int, y: int, z: int) -> ContainerData | None:
        """Get container data at a position."""
        return self.containers.get((x, y, z))

    def create_container(self, x: int, y: int, z: int,
                          container_type: str = "chest") -> ContainerData:
        """Create a new container at a position."""
        container = ContainerData(type=container_type)
        self.containers[(x, y, z)] = container
        return container

    def remove_container(self, x: int, y: int, z: int):
        """Remove a container when the block is broken."""
        container = self.containers.pop((x, y, z), None)
        if container is not None:
            container.viewers.clear()

    def get_or_create(self, x: int, y: int, z: int,
                       container_type: str = "chest") -> ContainerData:
        """Get existing container or create a new one."""
        container = self.get_container(x, y, z)
        if container is None:
            container = self.create_container(x, y, z, container_type)
        return container

    def allocate_window_id(self) -> int:
        """Allocate a new window ID for container interaction."""
        wid = self._next_window_id
        self._next_window_id = (self._next_window_id + 1) % 100
        if wid == 0:
            wid = 1
        return wid

    def add_viewer(self, x: int, y: int, z: int, entity_id: int):
        """Add a player as a viewer of a container."""
        container = self.get_container(x, y, z)
        if container is not None:
            container.viewers.add(entity_id)

    def remove_viewer(self, x: int, y: int, z: int, entity_id: int):
        """Remove a player from container viewers."""
        container = self.get_container(x, y, z)
        if container is not None:
            container.viewers.discard(entity_id)

    def tick_furnaces(self, server):
        """Tick all active furnaces (process smelting)."""
        from .crafting import crafting_system, FUEL_VALUES

        for (x, y, z), container in self.containers.items():
            if container.type not in ("furnace", "blast_furnace", "smoker"):
                continue

            # Furnace slot layout: 0=input, 1=fuel, 2=output
            input_item = container.items[0] if len(container.items) > 0 else None
            fuel_item = container.items[1] if len(container.items) > 1 else None
            output_item = container.items[2] if len(container.items) > 2 else None

            # Check if we can smelt
            can_smelt = False
            smelt_result = None

            if input_item is not None and not input_item.is_empty:
                smelt_result = crafting_system.check_smelting(input_item.item_id)
                if smelt_result is not None:
                    result_item = smelt_result[0]
                    # Check if output slot can accept the result
                    if output_item is None or output_item.is_empty:
                        can_smelt = True
                    elif output_item.item_id == result_item and output_item.count < 64:
                        can_smelt = True

            # Consume fuel if needed
            if can_smelt and container.burn_time <= 0:
                if fuel_item is not None and not fuel_item.is_empty:
                    burn_time = FUEL_VALUES.get(fuel_item.item_id, 0)
                    if burn_time > 0:
                        container.burn_time = burn_time
                        fuel_item.count -= 1
                        if fuel_item.count <= 0:
                            container.items[1] = None

            # Process smelting
            if can_smelt and container.burn_time > 0:
                container.burn_time -= 1

                # Speed multiplier for blast furnace / smoker
                speed = 1
                if container.type == "blast_furnace":
                    speed = 2
                elif container.type == "smoker":
                    speed = 2

                container.cook_time += speed

                if container.cook_time_total == 0 and smelt_result:
                    cook_time = smelt_result[2]
                    if container.type in ("blast_furnace", "smoker"):
                        cook_time = cook_time // 2
                    container.cook_time_total = cook_time

                if container.cook_time >= container.cook_time_total:
                    # Smelting complete
                    container.cook_time = 0
                    container.cook_time_total = 0

                    if input_item is not None:
                        input_item.count -= 1
                        if input_item.count <= 0:
                            container.items[0] = None

                    result_item_name = smelt_result[0] if smelt_result else "minecraft:air"
                    if output_item is None or output_item.is_empty:
                        container.items[2] = ItemStack(result_item_name, 1)
                    elif output_item.item_id == result_item_name:
                        output_item.count += 1
            else:
                # Not smelting - cool down
                if container.cook_time > 0:
                    container.cook_time = max(0, container.cook_time - 2)


# Global container manager
container_manager = ContainerManager()


# --------------------------------------------------
# Block Behavior Implementations
# --------------------------------------------------

class ChestBehavior(BlockBehavior):
    """Chest inventory interaction."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        container = container_manager.get_or_create(x, y, z, "chest")

        from world.inventory import send_open_container, send_container_content
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:generic_9x3", "Chest")

        # Send container contents: 27 chest slots + 36 player inventory slots
        all_slots = list(container.items) + [None] * (27 - len(container.items))
        inv = getattr(conn, 'inventory_obj', None)
        if inv is not None:
            for slot_idx in range(9, 36):
                all_slots.append(inv.get_slot(slot_idx))
            for slot_idx in range(9):
                all_slots.append(inv.get_slot(slot_idx))

        await send_container_content(conn, window_id, all_slots)

        container_manager.add_viewer(x, y, z, conn.entity_id)
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class CraftingTableBehavior(BlockBehavior):
    """3x3 crafting grid interaction."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.inventory import send_open_container
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:crafting", "Crafting Table")
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class FurnaceBehavior(BlockBehavior):
    """Furnace interface interaction."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        container = container_manager.get_or_create(x, y, z, "furnace")

        from world.inventory import send_open_container, send_container_content
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:furnace", "Furnace")

        # Send furnace contents: 3 furnace slots + 36 player inventory slots
        all_slots = list(container.items) + [None] * (3 - len(container.items))
        inv = getattr(conn, 'inventory_obj', None)
        if inv is not None:
            for slot_idx in range(9, 36):
                all_slots.append(inv.get_slot(slot_idx))
            for slot_idx in range(9):
                all_slots.append(inv.get_slot(slot_idx))

        await send_container_content(conn, window_id, all_slots)

        container_manager.add_viewer(x, y, z, conn.entity_id)
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class BlastFurnaceBehavior(BlockBehavior):
    """Blast furnace (smelts ores 2x faster)."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        container = container_manager.get_or_create(x, y, z, "blast_furnace")

        from world.inventory import send_open_container, send_container_content
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:blast_furnace", "Blast Furnace")

        all_slots = list(container.items) + [None] * (3 - len(container.items))
        inv = getattr(conn, 'inventory_obj', None)
        if inv is not None:
            for slot_idx in range(9, 36):
                all_slots.append(inv.get_slot(slot_idx))
            for slot_idx in range(9):
                all_slots.append(inv.get_slot(slot_idx))

        await send_container_content(conn, window_id, all_slots)
        container_manager.add_viewer(x, y, z, conn.entity_id)
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class AnvilBehavior(BlockBehavior):
    """Anvil repair/enchant interface."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.inventory import send_open_container
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:anvil", "Anvil")
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class EnchantingTableBehavior(BlockBehavior):
    """Enchanting table interface."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.inventory import send_open_container
        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:enchanting_table", "Enchanting Table")
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class EnderChestBehavior(BlockBehavior):
    """Open ender chest inventory (per-player)."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.inventory import send_open_container, send_container_content

        inv = getattr(conn, 'inventory_obj', None)
        if inv is None:
            return False

        window_id = container_manager.allocate_window_id()
        conn._open_window_id = window_id
        conn._open_container_pos = (x, y, z)

        await send_open_container(conn, window_id, "minecraft:generic_9x3", "Ender Chest")

        # Send ender chest contents
        all_slots = list(inv.ender_chest) + [None] * (27 - len(inv.ender_chest))
        # Add player inventory
        for slot_idx in range(9, 36):
            all_slots.append(inv.get_slot(slot_idx))
        for slot_idx in range(9):
            all_slots.append(inv.get_slot(slot_idx))

        await send_container_content(conn, window_id, all_slots)
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class DoorBehavior(BlockBehavior):
    """Toggle door open/closed state."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.editing import get_world_block, set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.chunk_io import BLOCK_KEY_TO_STATE_ID, STATE_ID_TO_BLOCK

        current_state = get_world_block(server, x, y, z)
        if current_state is None:
            return False

        block_name, props = STATE_ID_TO_BLOCK.get(current_state, ("minecraft:oak_door", {}))
        if "open" not in props and "half" not in props:
            return False

        # Toggle the 'open' property
        new_props = dict(props)
        is_open = new_props.get("open", "false") == "true"
        new_props["open"] = "false" if is_open else "true"

        # Look up the new state ID
        new_key = (block_name, tuple(sorted(new_props.items())))
        new_state = BLOCK_KEY_TO_STATE_ID.get(new_key)
        if new_state is None:
            # Try default
            new_state = BLOCK_KEY_TO_STATE_ID.get((block_name, tuple()))
        if new_state is not None:
            set_world_block(server, x, y, z, new_state)
            await _broadcast_block_change(server, x, y, z, new_state)

            # Also toggle the other half of the door
            other_y = y + 1 if props.get("half", "lower") == "lower" else y - 1
            other_state = get_world_block(server, x, other_y, z)
            if other_state is not None:
                other_name, other_props = STATE_ID_TO_BLOCK.get(other_state, (None, {}))
                if other_name == block_name:
                    other_new_props = dict(other_props)
                    other_new_props["open"] = "false" if is_open else "true"
                    other_key = (other_name, tuple(sorted(other_new_props.items())))
                    other_new_state = BLOCK_KEY_TO_STATE_ID.get(other_key)
                    if other_new_state is not None:
                        set_world_block(server, x, other_y, z, other_new_state)
                        await _broadcast_block_change(server, x, other_y, z, other_new_state)

        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class TrapdoorBehavior(BlockBehavior):
    """Toggle trapdoor open/closed state."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.editing import get_world_block, set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.chunk_io import BLOCK_KEY_TO_STATE_ID, STATE_ID_TO_BLOCK

        current_state = get_world_block(server, x, y, z)
        if current_state is None:
            return False

        block_name, props = STATE_ID_TO_BLOCK.get(current_state, ("minecraft:oak_trapdoor", {}))

        new_props = dict(props)
        is_open = new_props.get("open", "false") == "true"
        new_props["open"] = "false" if is_open else "true"

        new_key = (block_name, tuple(sorted(new_props.items())))
        new_state = BLOCK_KEY_TO_STATE_ID.get(new_key)
        if new_state is not None:
            set_world_block(server, x, y, z, new_state)
            await _broadcast_block_change(server, x, y, z, new_state)

        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class FenceGateBehavior(BlockBehavior):
    """Toggle fence gate open/closed state."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.editing import get_world_block, set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.chunk_io import BLOCK_KEY_TO_STATE_ID, STATE_ID_TO_BLOCK

        current_state = get_world_block(server, x, y, z)
        if current_state is None:
            return False

        block_name, props = STATE_ID_TO_BLOCK.get(current_state, ("minecraft:oak_fence_gate", {}))

        new_props = dict(props)
        is_open = new_props.get("open", "false") == "true"
        new_props["open"] = "false" if is_open else "true"

        new_key = (block_name, tuple(sorted(new_props.items())))
        new_state = BLOCK_KEY_TO_STATE_ID.get(new_key)
        if new_state is not None:
            set_world_block(server, x, y, z, new_state)
            await _broadcast_block_change(server, x, y, z, new_state)

        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class BedBehavior(BlockBehavior):
    """Set respawn point and skip night."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        # Set personal spawn point
        conn.personal_spawn = (x, y, z)

        # Check if all players are in bed (simplified: just set time to day)
        from handlers.play.chat import send_system_message
        await send_system_message(conn, "[PyMC] 出生点已设置！")

        # Skip to day if all players are in bed
        players = server.get_online_players()
        all_in_bed = True
        for player in players:
            if player.gamemode not in ("creative", "spectator"):
                all_in_bed = False
                break

        if all_in_bed or len(players) <= 1:
            # Skip to day
            server.world_time = 0
            from handlers.play.join import _send_time_update
            for player in players:
                await _send_time_update(player, server)

        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class SignBehavior(BlockBehavior):
    """Open sign editor."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from protocol.data_types import write_varint, write_position

        # Send Open Sign Editor packet (0x3E in 1.21.1)
        payload = bytearray()
        payload.extend(write_position(x, y, z))
        payload.extend(write_varint(1))  # is_front_text = True
        await conn.send_packet(0x3E, bytes(payload))
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class CakeBehavior(BlockBehavior):
    """Consume one slice, reduce bite count."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        from world.editing import get_world_block, set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.chunk_io import BLOCK_KEY_TO_STATE_ID, STATE_ID_TO_BLOCK

        current_state = get_world_block(server, x, y, z)
        if current_state is None:
            return False

        block_name, props = STATE_ID_TO_BLOCK.get(current_state, ("minecraft:cake", {}))
        if block_name != "minecraft:cake":
            return False

        bites = int(props.get("bites", "0"))
        new_bites = bites + 1

        # Restore hunger
        if conn.gamemode not in ("creative", "spectator"):
            conn.food = min(20, conn.food + 2)
            conn.saturation = min(conn.saturation + 0.4, conn.food)
            from handlers.play.join import _send_update_health
            await _send_update_health(conn)

        if new_bites >= 7:
            # All slices consumed - remove cake
            from world.blocks import AIR
            set_world_block(server, x, y, z, AIR)
            await _broadcast_block_change(server, x, y, z, AIR)
        else:
            # Update bite count
            new_props = dict(props)
            new_props["bites"] = str(new_bites)
            new_key = (block_name, tuple(sorted(new_props.items())))
            new_state = BLOCK_KEY_TO_STATE_ID.get(new_key)
            if new_state is not None:
                set_world_block(server, x, y, z, new_state)
                await _broadcast_block_change(server, x, y, z, new_state)

        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


class FarmlandBehavior(BlockBehavior):
    """Trample farmland if player jumps on it."""

    @staticmethod
    async def on_step_on(conn, server, x: int, y: int, z: int) -> None:
        # Farmland trampling: if player jumps (not on ground) and lands on farmland,
        # it may turn to dirt
        if not conn.on_ground and conn.gamemode not in ("creative", "spectator"):
            if random.random() < 0.6:  # 60% chance to trample
                from world.editing import set_world_block
                from handlers.play.blocks import _broadcast_block_change
                from world.blocks import DIRT
                set_world_block(server, x, y, z, DIRT)
                await _broadcast_block_change(server, x, y, z, DIRT)


class TNTBehavior(BlockBehavior):
    """TNT - ignites on use with flint and steel, or on redstone signal."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        # Check if player is holding flint and steel
        inv = getattr(conn, 'inventory_obj', None)
        if inv is None:
            return False

        held = inv.get_held_item()
        if held is None or held.item_id != "minecraft:flint_and_steel":
            return False

        # Ignite TNT
        await TNTBehavior._ignite(server, x, y, z)

        # Damage flint and steel
        held.damage += 1
        if held.damage >= 64:  # Simplified durability
            inv.set_slot(inv.held_slot, None)

        return True

    @staticmethod
    async def on_projectile_hit(conn, server, x: int, y: int, z: int) -> None:
        """Fire arrows can ignite TNT."""
        await TNTBehavior._ignite(server, x, y, z)

    @staticmethod
    async def _ignite(server, x: int, y: int, z: int):
        """Ignite TNT - replace with air and simulate explosion."""
        from world.editing import set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.blocks import AIR

        # Remove the TNT block
        set_world_block(server, x, y, z, AIR)
        await _broadcast_block_change(server, x, y, z, AIR)

        # Create explosion effect
        await TNTBehavior._create_explosion(server, x, y, z)

    @staticmethod
    async def _create_explosion(server, cx: int, cy: int, cz: int, radius: float = 4.0):
        """
        Create an explosion at the given position.
        Destroys blocks in radius, damages entities, creates particles.
        """
        from world.editing import get_world_block, set_world_block
        from handlers.play.blocks import _broadcast_block_change
        from world.blocks import AIR

        # Ray-trace explosion (simplified - vanilla uses 1352 rays)
        destroyed = set()
        for dx in range(-int(radius), int(radius) + 1):
            for dy in range(-int(radius), int(radius) + 1):
                for dz in range(-int(radius), int(radius) + 1):
                    bx, by, bz = cx + dx, cy + dy, cz + dz
                    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
                    if dist > radius:
                        continue

                    state = get_world_block(server, bx, by, bz)
                    if state is None or state == AIR:
                        continue

                    block_name, _ = STATE_ID_TO_BLOCK.get(state, ("minecraft:air", {}))

                    # Some blocks resist explosions
                    blast_resist = {
                        "minecraft:bedrock": 18000000,
                        "minecraft:obsidian": 1200,
                        "minecraft:ender_chest": 600,
                        "minecraft:anvil": 600,
                        "minecraft:reinforced_deepslate": 18000000,
                        "minecraft:command_block": 18000000,
                        "minecraft:barrier": 18000000,
                    }
                    if blast_resist.get(block_name, 0) > 1200:
                        continue

                    # Random chance based on distance (vanilla-like)
                    chance = (1.0 - dist / radius) * 0.7
                    if random.random() < chance:
                        destroyed.add((bx, by, bz))

        # Destroy blocks and drop some items
        for bx, by, bz in destroyed:
            state = get_world_block(server, bx, by, bz)
            if state is not None and state != AIR:
                block_name, _ = STATE_ID_TO_BLOCK.get(state, ("minecraft:air", {}))

                # 1/(power+1) chance to drop items (simplified)
                if random.random() < 1.0 / (radius + 1):
                    # Drop items at this location (simplified)
                    drops = get_block_drops(block_name, None)
                    # In a full implementation, we'd spawn item entities here

            set_world_block(server, bx, by, bz, AIR)
            await _broadcast_block_change(server, bx, by, bz, AIR)

        # Send explosion particle effect to all nearby players
        try:
            from protocol.data_types import write_float, write_varint
            payload = bytearray()
            payload.extend(write_float(float(cx)))
            payload.extend(write_float(float(cy)))
            payload.extend(write_float(float(cz)))
            payload.extend(write_float(radius))  # power
            # Number of records (affected blocks)
            payload.extend(write_varint(len(destroyed)))
            # Record positions (relative offsets)
            for bx, by, bz in destroyed:
                payload.extend(bytes([bx - cx & 0xFF]))
                payload.extend(bytes([by - cy & 0xFF]))
                payload.extend(bytes([bz - cz & 0xFF]))
            # Player motion (knockback)
            payload.extend(write_float(0.0))
            payload.extend(write_float(0.0))
            payload.extend(write_float(0.0))

            for player in server.get_online_players():
                await player.send_packet(0x24, bytes(payload))  # Explosion packet
        except Exception as e:
            logger.warning(f"Failed to send explosion packet: {e}")

    @staticmethod
    def is_interactive() -> bool:
        return True


class NoteBlockBehavior(BlockBehavior):
    """Note block - cycle note pitch on use, play on redstone activation."""

    # Note block state tracking: position -> note (0-24)
    _note_states: dict[tuple[int, int, int], int] = {}

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int) -> bool:
        """Right-click cycles the note pitch up by one."""
        current_note = NoteBlockBehavior._note_states.get((x, y, z), 0)
        new_note = (current_note + 1) % 25
        NoteBlockBehavior._note_states[(x, y, z)] = new_note

        # Play the note
        await NoteBlockBehavior._play_note(server, x, y, z, new_note)
        return True

    @staticmethod
    async def _play_note(server, x: int, y: int, z: int, note: int):
        """Play a note block sound at the given position."""
        # Note: 0-24 maps to F#3 to F#5
        # Instrument depends on block below
        instrument = NoteBlockBehavior._get_instrument(server, x, y, z)

        try:
            from protocol.data_types import write_varint
            # Send Sound Effect packet (0x26 in 1.21.1)
            # sound_id, category, x*8, y*8, z*8, volume, pitch
            sound_ids = {
                "harp": 0, "basedrum": 1, "snare": 2, "hat": 3,
                "bass": 4, "flute": 5, "bell": 6, "guitar": 7,
                "chime": 8, "xylophone": 9, "iron_xylophone": 10,
                "cow_bell": 11, "didgeridoo": 12, "bit": 13,
                "banjo": 14, "pling": 15,
            }
            sound_id = sound_ids.get(instrument, 0)

            payload = bytearray()
            payload.extend(write_varint(sound_id))
            payload.extend(write_varint(4))  # category: record
            payload.extend(write_varint(int(x * 8)))
            payload.extend(write_varint(int(y * 8)))
            payload.extend(write_varint(int(z * 8)))
            # Volume and pitch
            payload.extend(write_varint(0))  # volume fixed point
            payload.extend(write_varint(0))  # pitch fixed point

            # Simplified: send as a named sound effect
            for player in server.get_online_players():
                # Use play_named_sound packet instead
                pass
        except Exception:
            pass

    @staticmethod
    def _get_instrument(server, x: int, y: int, z: int) -> str:
        """Determine the instrument based on the block below the note block."""
        from world.editing import get_world_block
        below = get_world_block(server, x, y - 1, z)
        if below is None:
            return "harp"

        block_name, _ = STATE_ID_TO_BLOCK.get(below, ("minecraft:air", {}))

        instrument_map = {
            "minecraft:oak_planks": "bass", "minecraft:spruce_planks": "bass",
            "minecraft:birch_planks": "bass", "minecraft:jungle_planks": "bass",
            "minecraft:acacia_planks": "bass", "minecraft:dark_oak_planks": "bass",
            "minecraft:mangrove_planks": "bass", "minecraft:bamboo_planks": "bass",
            "minecraft:sand": "snare", "minecraft:gravel": "snare",
            "minecraft:soul_sand": "snare",
            "minecraft:glass": "hat", "minecraft:white_stained_glass": "hat",
            "minecraft:stone": "basedrum", "minecraft:cobblestone": "basedrum",
            "minecraft:obsidian": "basedrum",
            "minecraft:gold_block": "bell",
            "minecraft:clay": "flute",
            "minecraft:packed_ice": "chime",
            "minecraft:bone_block": "xylophone",
            "minecraft:iron_block": "iron_xylophone",
            "minecraft:soul_sand": "cow_bell",
            "minecraft:pumpkin": "didgeridoo",
            "minecraft:emerald_block": "bit",
            "minecraft:hay_block": "banjo",
            "minecraft:glowstone": "pling",
        }
        return instrument_map.get(block_name, "harp")

    @staticmethod
    def is_interactive() -> bool:
        return True


class WaterBehavior(BlockBehavior):
    """Water block behavior (non-solid, passable)."""

    @staticmethod
    def is_solid() -> bool:
        return False

    @staticmethod
    def is_transparent() -> bool:
        return True

    @staticmethod
    def get_hardness() -> float:
        return 100.0  # Can't really mine water


class LavaBehavior(BlockBehavior):
    """Lava block behavior (non-solid, passable, damaging)."""

    @staticmethod
    def is_solid() -> bool:
        return False

    @staticmethod
    def is_transparent() -> bool:
        return True

    @staticmethod
    def get_hardness() -> float:
        return 100.0


class JukeboxBehavior(BlockBehavior):
    """Jukebox - play/insert disc."""

    @staticmethod
    async def on_use(conn, server, x: int, y: int, z: int,
                     face: int, hand: int) -> bool:
        # Simplified: just acknowledge the interaction
        # In a full implementation, we'd insert/play music discs
        return True

    @staticmethod
    def is_interactive() -> bool:
        return True


# --------------------------------------------------
# Block Behavior Registry
# --------------------------------------------------

BLOCK_BEHAVIORS: dict[str, BlockBehavior] = {
    # Chests
    "minecraft:chest": ChestBehavior(),
    "minecraft:trapped_chest": ChestBehavior(),
    # Crafting
    "minecraft:crafting_table": CraftingTableBehavior(),
    # Furnaces
    "minecraft:furnace": FurnaceBehavior(),
    "minecraft:blast_furnace": BlastFurnaceBehavior(),
    "minecraft:smoker": FurnaceBehavior(),
    # Anvil
    "minecraft:anvil": AnvilBehavior(),
    "minecraft:chipped_anvil": AnvilBehavior(),
    "minecraft:damaged_anvil": AnvilBehavior(),
    # Enchanting
    "minecraft:enchanting_table": EnchantingTableBehavior(),
    # Ender chest
    "minecraft:ender_chest": EnderChestBehavior(),
    # Doors
    "minecraft:oak_door": DoorBehavior(),
    "minecraft:spruce_door": DoorBehavior(),
    "minecraft:birch_door": DoorBehavior(),
    "minecraft:jungle_door": DoorBehavior(),
    "minecraft:acacia_door": DoorBehavior(),
    "minecraft:dark_oak_door": DoorBehavior(),
    "minecraft:mangrove_door": DoorBehavior(),
    "minecraft:bamboo_door": DoorBehavior(),
    "minecraft:crimson_door": DoorBehavior(),
    "minecraft:warped_door": DoorBehavior(),
    "minecraft:iron_door": DoorBehavior(),
    # Trapdoors
    "minecraft:oak_trapdoor": TrapdoorBehavior(),
    "minecraft:spruce_trapdoor": TrapdoorBehavior(),
    "minecraft:birch_trapdoor": TrapdoorBehavior(),
    "minecraft:jungle_trapdoor": TrapdoorBehavior(),
    "minecraft:acacia_trapdoor": TrapdoorBehavior(),
    "minecraft:dark_oak_trapdoor": TrapdoorBehavior(),
    "minecraft:mangrove_trapdoor": TrapdoorBehavior(),
    "minecraft:bamboo_trapdoor": TrapdoorBehavior(),
    "minecraft:crimson_trapdoor": TrapdoorBehavior(),
    "minecraft:warped_trapdoor": TrapdoorBehavior(),
    "minecraft:iron_trapdoor": TrapdoorBehavior(),
    # Fence Gates
    "minecraft:oak_fence_gate": FenceGateBehavior(),
    "minecraft:spruce_fence_gate": FenceGateBehavior(),
    "minecraft:birch_fence_gate": FenceGateBehavior(),
    "minecraft:jungle_fence_gate": FenceGateBehavior(),
    "minecraft:acacia_fence_gate": FenceGateBehavior(),
    "minecraft:dark_oak_fence_gate": FenceGateBehavior(),
    "minecraft:mangrove_fence_gate": FenceGateBehavior(),
    "minecraft:bamboo_fence_gate": FenceGateBehavior(),
    "minecraft:crimson_fence_gate": FenceGateBehavior(),
    "minecraft:warped_fence_gate": FenceGateBehavior(),
    # Beds
    "minecraft:white_bed": BedBehavior(),
    "minecraft:orange_bed": BedBehavior(),
    "minecraft:magenta_bed": BedBehavior(),
    "minecraft:light_blue_bed": BedBehavior(),
    "minecraft:yellow_bed": BedBehavior(),
    "minecraft:lime_bed": BedBehavior(),
    "minecraft:pink_bed": BedBehavior(),
    "minecraft:gray_bed": BedBehavior(),
    "minecraft:light_gray_bed": BedBehavior(),
    "minecraft:cyan_bed": BedBehavior(),
    "minecraft:purple_bed": BedBehavior(),
    "minecraft:blue_bed": BedBehavior(),
    "minecraft:brown_bed": BedBehavior(),
    "minecraft:green_bed": BedBehavior(),
    "minecraft:red_bed": BedBehavior(),
    "minecraft:black_bed": BedBehavior(),
    # Signs
    "minecraft:oak_sign": SignBehavior(),
    "minecraft:spruce_sign": SignBehavior(),
    "minecraft:birch_sign": SignBehavior(),
    "minecraft:jungle_sign": SignBehavior(),
    "minecraft:acacia_sign": SignBehavior(),
    "minecraft:dark_oak_sign": SignBehavior(),
    "minecraft:mangrove_sign": SignBehavior(),
    "minecraft:bamboo_sign": SignBehavior(),
    "minecraft:crimson_sign": SignBehavior(),
    "minecraft:warped_sign": SignBehavior(),
    "minecraft:oak_wall_sign": SignBehavior(),
    "minecraft:spruce_wall_sign": SignBehavior(),
    "minecraft:birch_wall_sign": SignBehavior(),
    "minecraft:jungle_wall_sign": SignBehavior(),
    "minecraft:acacia_wall_sign": SignBehavior(),
    "minecraft:dark_oak_wall_sign": SignBehavior(),
    "minecraft:mangrove_wall_sign": SignBehavior(),
    "minecraft:bamboo_wall_sign": SignBehavior(),
    "minecraft:crimson_wall_sign": SignBehavior(),
    "minecraft:warped_wall_sign": SignBehavior(),
    # Cake
    "minecraft:cake": CakeBehavior(),
    # Farmland
    "minecraft:farmland": FarmlandBehavior(),
    # TNT
    "minecraft:tnt": TNTBehavior(),
    # Note Block
    "minecraft:note_block": NoteBlockBehavior(),
    # Jukebox
    "minecraft:jukebox": JukeboxBehavior(),
    # Fluids
    "minecraft:water": WaterBehavior(),
    "minecraft:lava": LavaBehavior(),
    # Lever / buttons (handled by redstone engine)
    "minecraft:lever": BlockBehavior(),
    "minecraft:stone_button": BlockBehavior(),
    "minecraft:oak_button": BlockBehavior(),
}


def get_block_behavior(block_name: str) -> BlockBehavior | None:
    """Get the behavior for a block, or None if no special behavior."""
    return BLOCK_BEHAVIORS.get(block_name)


def get_block_name_from_state(state_id: int) -> str:
    """Get block name from a block state ID."""
    if state_id in STATE_ID_TO_BLOCK:
        return STATE_ID_TO_BLOCK[state_id][0]
    return "minecraft:air"
