# ============================================================
# PyMC - Full Inventory System
# ItemStack-based player and container inventories
# Minecraft 1.21.1 protocol
# ============================================================

"""
Complete inventory system with ItemStack representation,
player inventory management, and protocol serialization.

Slot layout (Java Edition 1.21.1):
  0-8:   Hotbar
  9-35:  Main inventory (3 rows of 9)
  36-39: Armor (boots, leggings, chestplate, helmet)
  40:    Offhand
  41-44: Crafting grid (2x2, client-side only)
  45:    Crafting result (client-side only)
"""

import copy
import logging
from typing import Optional

from protocol.data_types import (
    write_varint, write_boolean, write_byte, write_short,
)

logger = logging.getLogger("PyMC.物品栏")


# --------------------------------------------------
# Item ID to protocol numeric ID mapping
# --------------------------------------------------

_ITEM_PROTOCOL_IDS: dict[str, int] = {
    # Blocks (as items)
    "minecraft:stone": 1,
    "minecraft:granite": 2,
    "minecraft:polished_granite": 3,
    "minecraft:diorite": 4,
    "minecraft:polished_diorite": 5,
    "minecraft:andesite": 6,
    "minecraft:polished_andesite": 7,
    "minecraft:grass_block": 8,
    "minecraft:dirt": 9,
    "minecraft:coarse_dirt": 10,
    "minecraft:podzol": 12,
    "minecraft:cobblestone": 11,
    "minecraft:oak_planks": 12,
    "minecraft:spruce_planks": 13,
    "minecraft:birch_planks": 14,
    "minecraft:jungle_planks": 15,
    "minecraft:acacia_planks": 16,
    "minecraft:dark_oak_planks": 17,
    "minecraft:mangrove_planks": 18,
    "minecraft:bamboo_planks": 19,
    "minecraft:glass": 25,
    "minecraft:sand": 28,
    "minecraft:red_sand": 29,
    "minecraft:gravel": 30,
    "minecraft:oak_log": 36,
    "minecraft:spruce_log": 37,
    "minecraft:birch_log": 38,
    "minecraft:jungle_log": 39,
    "minecraft:acacia_log": 40,
    "minecraft:dark_oak_log": 41,
    "minecraft:mangrove_log": 42,
    "minecraft:chest": 54,
    "minecraft:crafting_table": 55,
    "minecraft:furnace": 56,
    "minecraft:oak_sign": 62,
    "minecraft:oak_door": 66,
    "minecraft:ladder": 87,
    "minecraft:torch": 79,
    "minecraft:snow": 80,
    "minecraft:ice": 81,
    "minecraft:cactus": 88,
    "minecraft:clay": 94,
    "minecraft:jukebox": 99,
    "minecraft:oak_fence": 101,
    "minecraft:pumpkin": 111,
    "minecraft:netherrack": 115,
    "minecraft:soul_sand": 116,
    "minecraft:glowstone": 117,
    "minecraft:anvil": 133,
    "minecraft:trapped_chest": 134,
    "minecraft:ender_chest": 135,
    "minecraft:bed": 140,
    # Ores / Materials
    "minecraft:coal_ore": 43,
    "minecraft:iron_ore": 44,
    "minecraft:gold_ore": 45,
    "minecraft:diamond_ore": 56,
    "minecraft:lapis_ore": 46,
    "minecraft:redstone_ore": 47,
    "minecraft:emerald_ore": 129,
    "minecraft:copper_ore": 130,
    "minecraft:deepslate_coal_ore": 48,
    "minecraft:deepslate_iron_ore": 49,
    "minecraft:deepslate_gold_ore": 50,
    "minecraft:deepslate_diamond_ore": 57,
    "minecraft:deepslate_lapis_ore": 51,
    "minecraft:deepslate_redstone_ore": 52,
    "minecraft:deepslate_emerald_ore": 131,
    "minecraft:deepslate_copper_ore": 132,
    # Ingots / Gems
    "minecraft:coal": 104,
    "minecraft:diamond": 110,
    "minecraft:iron_ingot": 112,
    "minecraft:gold_ingot": 113,
    "minecraft:emerald": 120,
    "minecraft:lapis_lazuli": 121,
    "minecraft:quartz": 122,
    "minecraft:amethyst_shard": 123,
    "minecraft:copper_ingot": 124,
    "minecraft:netherite_ingot": 125,
    "minecraft:netherite_scrap": 126,
    # Tools
    "minecraft:wooden_pickaxe": 200,
    "minecraft:stone_pickaxe": 201,
    "minecraft:iron_pickaxe": 202,
    "minecraft:golden_pickaxe": 203,
    "minecraft:diamond_pickaxe": 204,
    "minecraft:netherite_pickaxe": 205,
    "minecraft:wooden_axe": 206,
    "minecraft:stone_axe": 207,
    "minecraft:iron_axe": 208,
    "minecraft:golden_axe": 209,
    "minecraft:diamond_axe": 210,
    "minecraft:netherite_axe": 211,
    "minecraft:wooden_shovel": 212,
    "minecraft:stone_shovel": 213,
    "minecraft:iron_shovel": 214,
    "minecraft:golden_shovel": 215,
    "minecraft:diamond_shovel": 216,
    "minecraft:netherite_shovel": 217,
    "minecraft:wooden_sword": 218,
    "minecraft:stone_sword": 219,
    "minecraft:iron_sword": 220,
    "minecraft:golden_sword": 221,
    "minecraft:diamond_sword": 222,
    "minecraft:netherite_sword": 223,
    "minecraft:wooden_hoe": 224,
    "minecraft:stone_hoe": 225,
    "minecraft:iron_hoe": 226,
    "minecraft:golden_hoe": 227,
    "minecraft:diamond_hoe": 228,
    "minecraft:netherite_hoe": 229,
    # Armor
    "minecraft:leather_helmet": 250,
    "minecraft:leather_chestplate": 251,
    "minecraft:leather_leggings": 252,
    "minecraft:leather_boots": 253,
    "minecraft:iron_helmet": 254,
    "minecraft:iron_chestplate": 255,
    "minecraft:iron_leggings": 256,
    "minecraft:iron_boots": 257,
    "minecraft:golden_helmet": 258,
    "minecraft:golden_chestplate": 259,
    "minecraft:golden_leggings": 260,
    "minecraft:golden_boots": 261,
    "minecraft:diamond_helmet": 262,
    "minecraft:diamond_chestplate": 263,
    "minecraft:diamond_leggings": 264,
    "minecraft:diamond_boots": 265,
    "minecraft:netherite_helmet": 266,
    "minecraft:netherite_chestplate": 267,
    "minecraft:netherite_leggings": 268,
    "minecraft:netherite_boots": 269,
    # Food
    "minecraft:apple": 300,
    "minecraft:bread": 301,
    "minecraft:cooked_beef": 302,
    "minecraft:cooked_porkchop": 303,
    "minecraft:cooked_chicken": 304,
    "minecraft:raw_beef": 305,
    "minecraft:raw_porkchop": 306,
    "minecraft:raw_chicken": 307,
    "minecraft:wheat": 308,
    "minecraft:melon_slice": 309,
    "minecraft:golden_apple": 310,
    "minecraft:enchanted_golden_apple": 311,
    "minecraft:cooked_cod": 312,
    "minecraft:cooked_salmon": 313,
    "minecraft:raw_cod": 314,
    "minecraft:raw_salmon": 315,
    "minecraft:baked_potato": 316,
    "minecraft:carrot": 317,
    "minecraft:golden_carrot": 318,
    "minecraft:potato": 319,
    "minecraft:beetroot": 320,
    "minecraft:sweet_berries": 321,
    "minecraft:glow_berries": 322,
    # Misc
    "minecraft:stick": 114,
    "minecraft:bucket": 350,
    "minecraft:water_bucket": 351,
    "minecraft:lava_bucket": 352,
    "minecraft:milk_bucket": 353,
    "minecraft:bow": 354,
    "minecraft:arrow": 355,
    "minecraft:crossbow": 356,
    "minecraft:trident": 357,
    "minecraft:shield": 358,
    "minecraft:flint": 359,
    "minecraft:flint_and_steel": 360,
    "minecraft:iron_nugget": 361,
    "minecraft:gold_nugget": 362,
    "minecraft:string": 363,
    "minecraft:feather": 364,
    "minecraft:leather": 365,
    "minecraft:paper": 366,
    "minecraft:book": 367,
    "minecraft:slime_ball": 368,
    "minecraft:ender_pearl": 369,
    "minecraft:blaze_rod": 370,
    "minecraft:blaze_powder": 371,
    "minecraft:magma_cream": 372,
    "minecraft:bone": 373,
    "minecraft:sugar": 374,
    "minecraft:egg": 375,
    "minecraft:glowstone_dust": 376,
    "minecraft:redstone": 377,
    "minecraft:gunpowder": 378,
    "minecraft:spider_eye": 379,
    "minecraft:ink_sac": 380,
    "minecraft:glow_ink_sac": 381,
    "minecraft:wheat_seeds": 382,
    "minecraft:beetroot_seeds": 383,
    "minecraft:melon_seeds": 384,
    "minecraft:pumpkin_seeds": 385,
    "minecraft:bone_meal": 386,
    "minecraft:dye": 387,
    # Redstone components
    "minecraft:redstone_torch": 400,
    "minecraft:repeater": 401,
    "minecraft:comparator": 402,
    "minecraft:piston": 403,
    "minecraft:sticky_piston": 404,
    "minecraft:observer": 405,
    "minecraft:hopper": 406,
    "minecraft:dropper": 407,
    "minecraft:dispenser": 408,
    "minecraft:tripwire_hook": 409,
    "minecraft:daylight_detector": 410,
    "minecraft:lever": 411,
    "minecraft:button": 412,
    "minecraft:pressure_plate": 413,
    "minecraft:tnt": 414,
    "minecraft:minecart": 415,
    "minecraft:boat": 416,
    "minecraft:compass": 417,
    "minecraft:clock": 418,
    "minecraft:spyglass": 419,
    "minecraft:shears": 420,
    "minecraft:writable_book": 421,
    "minecraft:written_book": 422,
    "minecraft:map": 423,
    "minecraft:fire_charge": 424,
    "minecraft:painting": 425,
    "minecraft:item_frame": 426,
    "minecraft:name_tag": 428,
    "minecraft:lead": 429,
    "minecraft:saddle": 430,
    "minecraft:totem_of_undying": 431,
    "minecraft:elytra": 432,
    "minecraft:experience_bottle": 433,
    "minecraft:debug_stick": 434,
    "minecraft:knowledge_book": 435,
    # Farmland / Agricultural
    "minecraft:wheat": 308,
    "minecraft:farmland": 440,
    # Dyes
    "minecraft:white_dye": 450,
    "minecraft:orange_dye": 451,
    "minecraft:magenta_dye": 452,
    "minecraft:light_blue_dye": 453,
    "minecraft:yellow_dye": 454,
    "minecraft:lime_dye": 455,
    "minecraft:pink_dye": 456,
    "minecraft:gray_dye": 457,
    "minecraft:light_gray_dye": 458,
    "minecraft:cyan_dye": 459,
    "minecraft:purple_dye": 460,
    "minecraft:blue_dye": 461,
    "minecraft:brown_dye": 462,
    "minecraft:green_dye": 463,
    "minecraft:red_dye": 464,
    "minecraft:black_dye": 465,
    # Additional blocks
    "minecraft:oak_slab": 470,
    "minecraft:spruce_slab": 471,
    "minecraft:birch_slab": 472,
    "minecraft:jungle_slab": 473,
    "minecraft:acacia_slab": 474,
    "minecraft:dark_oak_slab": 475,
    "minecraft:mangrove_slab": 476,
    "minecraft:bamboo_slab": 477,
    "minecraft:stone_slab": 478,
    "minecraft:cobblestone_slab": 479,
    "minecraft:stone_brick_slab": 480,
    "minecraft:brick_slab": 481,
    "minecraft:smooth_stone_slab": 482,
    "minecraft:granite_slab": 483,
    "minecraft:polished_granite_slab": 484,
    "minecraft:diorite_slab": 485,
    "minecraft:polished_diorite_slab": 486,
    "minecraft:andesite_slab": 487,
    "minecraft:polished_andesite_slab": 488,
    # Stone variants
    "minecraft:stone_bricks": 490,
    "minecraft:mossy_stone_bricks": 491,
    "minecraft:cracked_stone_bricks": 492,
    "minecraft:chiseled_stone_bricks": 493,
    "minecraft:smooth_stone": 494,
    "minecraft:bricks": 495,
    # Additional
    "minecraft:raw_iron": 500,
    "minecraft:raw_gold": 501,
    "minecraft:raw_copper": 502,
    "minecraft:bowl": 503,
    "minecraft:mushroom_stew": 504,
    "minecraft:cocoa_beans": 505,
    "minecraft:brown_mushroom": 506,
    "minecraft:red_mushroom": 507,
    "minecraft:pumpkin_pie": 508,
    "minecraft:sugar_cane": 509,
    "minecraft:white_wool": 510,
    "minecraft:white_carpet": 511,
    "minecraft:white_banner": 512,
    "minecraft:brick": 513,
    "minecraft:clay_ball": 514,
    "minecraft:oak_sapling": 515,
    "minecraft:iron_horse_armor": 520,
    "minecraft:golden_horse_armor": 521,
    "minecraft:diamond_horse_armor": 522,
    "minecraft:enchanted_book": 530,
    "minecraft:glass_bottle": 531,
    "minecraft:potion": 532,
    "minecraft:smithing_template": 540,
    "minecraft:netherite_upgrade_smithing_template": 541,
    "minecraft:armor_trim_smithing_template": 542,
}

# Reverse mapping: protocol ID -> item name
_PROTOCOL_ID_TO_ITEM: dict[int, str] = {}
for _name, _pid in _ITEM_PROTOCOL_IDS.items():
    if _pid not in _PROTOCOL_ID_TO_ITEM:
        _PROTOCOL_ID_TO_ITEM[_pid] = _name


def item_name_to_protocol_id(item_name: str) -> int:
    """Convert a Minecraft item namespace ID to its protocol numeric ID."""
    return _ITEM_PROTOCOL_IDS.get(item_name, 1)


def protocol_id_to_item_name(protocol_id: int) -> str:
    """Convert a protocol numeric ID to a Minecraft item namespace ID."""
    return _PROTOCOL_ID_TO_ITEM.get(protocol_id, "minecraft:stone")


# --------------------------------------------------
# Tool types for mining speed calculation
# --------------------------------------------------

TOOL_TYPES: dict[str, str] = {
    # Pickaxes
    "minecraft:wooden_pickaxe": "pickaxe",
    "minecraft:stone_pickaxe": "pickaxe",
    "minecraft:iron_pickaxe": "pickaxe",
    "minecraft:golden_pickaxe": "pickaxe",
    "minecraft:diamond_pickaxe": "pickaxe",
    "minecraft:netherite_pickaxe": "pickaxe",
    # Axes
    "minecraft:wooden_axe": "axe",
    "minecraft:stone_axe": "axe",
    "minecraft:iron_axe": "axe",
    "minecraft:golden_axe": "axe",
    "minecraft:diamond_axe": "axe",
    "minecraft:netherite_axe": "axe",
    # Shovels
    "minecraft:wooden_shovel": "shovel",
    "minecraft:stone_shovel": "shovel",
    "minecraft:iron_shovel": "shovel",
    "minecraft:golden_shovel": "shovel",
    "minecraft:diamond_shovel": "shovel",
    "minecraft:netherite_shovel": "shovel",
    # Swords
    "minecraft:wooden_sword": "sword",
    "minecraft:stone_sword": "sword",
    "minecraft:iron_sword": "sword",
    "minecraft:golden_sword": "sword",
    "minecraft:diamond_sword": "sword",
    "minecraft:netherite_sword": "sword",
    # Hoes
    "minecraft:wooden_hoe": "hoe",
    "minecraft:stone_hoe": "hoe",
    "minecraft:iron_hoe": "hoe",
    "minecraft:golden_hoe": "hoe",
    "minecraft:diamond_hoe": "hoe",
    "minecraft:netherite_hoe": "hoe",
    # Shears
    "minecraft:shears": "shears",
}

TOOL_TIER_SPEED: dict[str, float] = {
    "wooden": 2.0,
    "stone": 4.0,
    "iron": 6.0,
    "golden": 12.0,
    "diamond": 8.0,
    "netherite": 9.0,
}

TOOL_TIER_FROM_ITEM: dict[str, str] = {
    "minecraft:wooden_pickaxe": "wooden",
    "minecraft:wooden_axe": "wooden",
    "minecraft:wooden_shovel": "wooden",
    "minecraft:wooden_sword": "wooden",
    "minecraft:wooden_hoe": "wooden",
    "minecraft:stone_pickaxe": "stone",
    "minecraft:stone_axe": "stone",
    "minecraft:stone_shovel": "stone",
    "minecraft:stone_sword": "stone",
    "minecraft:stone_hoe": "stone",
    "minecraft:iron_pickaxe": "iron",
    "minecraft:iron_axe": "iron",
    "minecraft:iron_shovel": "iron",
    "minecraft:iron_sword": "iron",
    "minecraft:iron_hoe": "iron",
    "minecraft:golden_pickaxe": "golden",
    "minecraft:golden_axe": "golden",
    "minecraft:golden_shovel": "golden",
    "minecraft:golden_sword": "golden",
    "minecraft:golden_hoe": "golden",
    "minecraft:diamond_pickaxe": "diamond",
    "minecraft:diamond_axe": "diamond",
    "minecraft:diamond_shovel": "diamond",
    "minecraft:diamond_sword": "diamond",
    "minecraft:diamond_hoe": "diamond",
    "minecraft:netherite_pickaxe": "netherite",
    "minecraft:netherite_axe": "netherite",
    "minecraft:netherite_shovel": "netherite",
    "minecraft:netherite_sword": "netherite",
    "minecraft:netherite_hoe": "netherite",
}

# Block name to item name mapping
BLOCK_TO_ITEM_OVERRIDES: dict[str, str] = {
    "minecraft:grass_block": "minecraft:grass_block",
    "minecraft:stone": "minecraft:cobblestone",
}


def block_name_to_item_name(block_name: str) -> str:
    """Convert a block name to the item it drops when mined without silk touch."""
    return BLOCK_TO_ITEM_OVERRIDES.get(block_name, block_name)


# --------------------------------------------------
# ItemStack
# --------------------------------------------------

class ItemStack:
    """A stack of items."""

    __slots__ = ('item_id', 'count', 'damage', 'nbt')

    def __init__(self, item_id: str = "minecraft:air", count: int = 0,
                 damage: int = 0, nbt: dict = None):
        self.item_id = item_id
        self.count = count
        self.damage = damage
        self.nbt = nbt or {}

    @property
    def is_empty(self) -> bool:
        return self.count <= 0 or self.item_id == "minecraft:air"

    @property
    def max_stack_size(self) -> int:
        """Get the maximum stack size for this item type."""
        MAX_STACK_OVERRIDES = {
            "minecraft:ender_pearl": 16, "minecraft:snowball": 16,
            "minecraft:egg": 16, "minecraft:honey_bottle": 16,
            "minecraft:sign": 16, "minecraft:bucket": 16,
            "minecraft:saddle": 1, "minecraft:totem_of_undying": 1,
            "minecraft:writable_book": 1, "minecraft:written_book": 1,
        }
        if self.item_id in MAX_STACK_OVERRIDES:
            return MAX_STACK_OVERRIDES[self.item_id]
        # Tools, weapons, armor and other non-stackable equipment = 1.
        # Match by suffix rather than material prefix so materials such as
        # iron_ingot, golden_apple, diamond_block and netherite_scrap keep
        # their normal 64-stack behaviour.
        for suffix in ("_sword", "_pickaxe", "_axe", "_shovel", "_hoe",
                       "_helmet", "_chestplate", "_leggings", "_boots",
                       "_bow", "_crossbow", "_trident", "_shield",
                       "_fishing_rod", "_shears", "_horse_armor",
                       "_elytra"):
            if self.item_id.endswith(suffix):
                return 1
        # Additional single-item overrides
        single_items = {
            "minecraft:bow", "minecraft:crossbow", "minecraft:trident",
            "minecraft:shield", "minecraft:shears", "minecraft:flint_and_steel",
            "minecraft:spyglass", "minecraft:elytra", "minecraft:carrot_on_a_stick",
            "minecraft:warped_fungus_on_a_stick", "minecraft:enchanted_book",
        }
        if self.item_id in single_items:
            return 1
        return 64

    def copy(self) -> 'ItemStack':
        """Create a deep copy of this item stack."""
        return ItemStack(self.item_id, self.count, self.damage, dict(self.nbt) if self.nbt else {})

    def to_dict(self) -> dict:
        """Serialize to a dictionary for storage."""
        return {"id": self.item_id, "count": self.count, "damage": self.damage, "nbt": self.nbt}

    @staticmethod
    def from_dict(d: dict) -> 'ItemStack':
        """Deserialize from a dictionary."""
        if not d:
            return ItemStack()
        return ItemStack(d.get("id", "minecraft:air"), d.get("count", 0),
                         d.get("damage", 0), d.get("nbt", {}))

    # --- Backward compatibility methods ---

    def is_empty_method(self) -> bool:
        """Check if this stack is empty (method version for backward compat)."""
        return self.is_empty

    def max_stack_size_method(self) -> int:
        """Get max stack size (method version for backward compat)."""
        return self.max_stack_size

    def can_stack_with(self, other: 'ItemStack | None') -> bool:
        """Check if this stack can be combined with another."""
        if other is None or other.is_empty:
            return False
        if self.is_empty:
            return True
        return (self.item_id == other.item_id
                and self.damage == other.damage
                and self.nbt == other.nbt)

    def shrink(self, amount: int = 1) -> int:
        """Remove items from the stack. Returns the number actually removed."""
        removed = min(amount, self.count)
        self.count -= removed
        return removed

    def grow(self, amount: int = 1) -> int:
        """Add items to the stack, respecting max stack size. Returns number added."""
        max_size = self.max_stack_size
        can_add = min(amount, max_size - self.count)
        self.count += can_add
        return can_add

    def get_tool_type(self) -> str | None:
        """Get the tool type if this item is a tool."""
        return TOOL_TYPES.get(self.item_id)

    def get_tool_tier(self) -> str | None:
        """Get the tool tier if this item is a tiered tool."""
        return TOOL_TIER_FROM_ITEM.get(self.item_id)

    def get_mining_speed(self) -> float:
        """Get the mining speed multiplier for this tool."""
        tier = self.get_tool_tier()
        if tier:
            return TOOL_TIER_SPEED.get(tier, 1.0)
        if self.item_id == "minecraft:shears":
            return 1.0
        return 1.0

    def __repr__(self) -> str:
        if self.is_empty:
            return "ItemStack(empty)"
        return f"ItemStack({self.item_id}, x{self.count})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, ItemStack):
            return False
        return (self.item_id == other.item_id
                and self.count == other.count
                and self.damage == other.damage)

    def __hash__(self) -> int:
        return hash((self.item_id, self.count, self.damage))


# Empty stack singleton
EMPTY_ITEM_STACK = ItemStack("minecraft:air", 0)


# --------------------------------------------------
# PlayerInventory
# --------------------------------------------------

class PlayerInventory:
    """Full player inventory - 46 slots matching vanilla layout.
    0-8: Hotbar, 9-35: Main (3x9), 36-39: Armor, 40: Offhand, 41-45: Crafting"""

    SLOT_HOTBAR_START = 0
    SLOT_HOTBAR_END = 8
    SLOT_MAIN_START = 9
    SLOT_MAIN_END = 35
    SLOT_ARMOR_START = 36  # boots, leggings, chestplate, helmet
    SLOT_ARMOR_END = 39
    SLOT_OFFHAND = 40

    TOTAL_SLOTS = 46

    def __init__(self):
        self.slots: list[ItemStack | None] = [None] * self.TOTAL_SLOTS
        self.state_id: int = 0
        self.held_slot: int = 0  # Currently selected hotbar slot

        # Ender chest (per-player)
        self.ender_chest: list[ItemStack | None] = [None] * 27

        # Cursor item (carried while dragging)
        self.carried_item: ItemStack | None = None

        # Internal selected slot tracking
        self._selected_slot: int = 0

    def set_slot(self, idx: int, item: ItemStack | None):
        """Set a slot to the given item (or None for empty)."""
        if 0 <= idx < len(self.slots):
            if item is not None and item.is_empty:
                item = None
            self.slots[idx] = item
            self.state_id += 1

    def get_slot(self, idx: int) -> ItemStack | None:
        """Get the item in a slot, or None if empty."""
        if 0 <= idx < len(self.slots):
            return self.slots[idx]
        return None

    def get_held_item(self) -> ItemStack | None:
        """Get the currently held item based on held_slot."""
        return self.get_slot(self.held_slot)

    def add_item(self, item: ItemStack) -> int:
        """Add item to inventory, returns leftover count that couldn't fit."""
        if item.is_empty:
            return 0
        remaining = item.count
        # First try to stack with existing items
        for i in range(self.TOTAL_SLOTS):
            if i == 41:
                continue  # Skip crafting result
            slot = self.slots[i]
            if slot and slot.item_id == item.item_id and slot.count < slot.max_stack_size:
                space = slot.max_stack_size - slot.count
                add = min(space, remaining)
                slot.count += add
                remaining -= add
                if remaining <= 0:
                    self.state_id += 1
                    return 0
        # Then try empty slots (hotbar last for convenience)
        for i in list(range(9, 36)) + list(range(0, 9)) + [40]:
            if self.slots[i] is None or (self.slots[i] is not None and self.slots[i].is_empty):
                add = min(item.max_stack_size, remaining)
                self.slots[i] = ItemStack(item.item_id, add, item.damage, dict(item.nbt) if item.nbt else {})
                remaining -= add
                if remaining <= 0:
                    self.state_id += 1
                    return 0
        self.state_id += 1
        return remaining

    def remove_item(self, item_id: str, count: int = 1) -> bool:
        """Remove items from inventory. Returns True if enough were removed."""
        available = 0
        for slot in self.slots:
            if slot and slot.item_id == item_id:
                available += slot.count
        if available < count:
            return False
        remaining = count
        for i in range(self.TOTAL_SLOTS):
            slot = self.slots[i]
            if slot and slot.item_id == item_id:
                remove = min(slot.count, remaining)
                slot.count -= remove
                remaining -= remove
                if slot.count <= 0:
                    self.slots[i] = None
                if remaining <= 0:
                    break
        self.state_id += 1
        return True

    def contains(self, item_id: str, min_count: int = 1) -> bool:
        """Check if the inventory contains at least min_count of an item."""
        total = sum(s.count for s in self.slots if s and s.item_id == item_id)
        return total >= min_count

    def count_item(self, item_id: str) -> int:
        """Count total number of a specific item in the inventory."""
        total = 0
        for slot in self.slots:
            if slot and slot.item_id == item_id:
                total += slot.count
        return total

    def swap_slots(self, a: int, b: int):
        """Swap the contents of two slots."""
        if 0 <= a < self.TOTAL_SLOTS and 0 <= b < self.TOTAL_SLOTS:
            self.slots[a], self.slots[b] = self.slots[b], self.slots[a]
            self.state_id += 1

    def clear(self):
        """Clear all inventory slots."""
        self.slots = [None] * self.TOTAL_SLOTS
        self.state_id += 1

    def clear_items(self, item_filter: str | None = None, max_count: int = -1) -> int:
        """Clear items, optionally filtered by item name. Returns count of items cleared."""
        cleared = 0
        for slot_idx in range(self.TOTAL_SLOTS):
            slot = self.slots[slot_idx]
            if slot is None:
                continue
            if item_filter is not None and slot.item_id != item_filter:
                continue
            if max_count >= 0:
                to_clear = min(slot.count, max_count - cleared)
                slot.count -= to_clear
                cleared += to_clear
                if slot.count <= 0:
                    self.slots[slot_idx] = None
                if cleared >= max_count:
                    break
            else:
                cleared += slot.count
                self.slots[slot_idx] = None
        if cleared > 0:
            self.state_id += 1
        return cleared

    def get_armor(self) -> list[ItemStack | None]:
        """Get the 4 armor slots (boots, leggings, chestplate, helmet)."""
        return list(self.slots[36:40])

    def get_offhand(self) -> ItemStack | None:
        """Get the offhand item."""
        return self.slots[40]

    def get_hotbar_slot(self, index: int) -> ItemStack | None:
        """Get an item from the hotbar (0-8)."""
        if 0 <= index < 9:
            return self.slots[index]
        return None

    def set_held_slot(self, slot: int):
        """Set the currently selected hotbar slot (0-8)."""
        if 0 <= slot < 9:
            self.held_slot = slot
            self._selected_slot = slot

    def get_held_item_from_slot(self, hotbar_slot: int) -> ItemStack | None:
        """Get the item at a specific hotbar slot."""
        if 0 <= hotbar_slot < 9:
            return self.slots[hotbar_slot]
        return None

    # --- Serialization ---

    def serialize(self) -> list[dict]:
        """Serialize inventory slots to a list of dicts (compact format)."""
        return [s.to_dict() if s else None for s in self.slots]

    def serialize_full(self) -> dict:
        """Serialize inventory data for world storage."""
        slots_data = {}
        for i, slot in enumerate(self.slots):
            if slot is not None and not slot.is_empty:
                slots_data[str(i)] = {
                    "item": slot.item_id,
                    "count": slot.count,
                    "damage": slot.damage,
                    "nbt": slot.nbt,
                }

        ender_data = {}
        for i, slot in enumerate(self.ender_chest):
            if slot is not None and not slot.is_empty:
                ender_data[str(i)] = {
                    "item": slot.item_id,
                    "count": slot.count,
                    "damage": slot.damage,
                    "nbt": slot.nbt,
                }

        return {
            "slots": slots_data,
            "ender_chest": ender_data,
            "selected_slot": getattr(self, '_selected_slot', 0),
            "held_slot": self.held_slot,
        }

    def deserialize(self, data: list[dict]):
        """Deserialize inventory slots from a list of dicts."""
        self.slots = [ItemStack.from_dict(d) if d else None for d in data]
        # Pad to 46 slots
        while len(self.slots) < self.TOTAL_SLOTS:
            self.slots.append(None)
        self.state_id += 1

    @classmethod
    def deserialize_full(cls, data: dict) -> 'PlayerInventory':
        """Deserialize inventory from world storage data."""
        inv = cls()
        for k, v in data.get("slots", {}).items():
            slot_idx = int(k)
            if 0 <= slot_idx < cls.TOTAL_SLOTS:
                inv.slots[slot_idx] = ItemStack(
                    item_id=v.get("item", "minecraft:air"),
                    count=v.get("count", 1),
                    damage=v.get("damage", 0),
                    nbt=v.get("nbt", {}),
                )
        for k, v in data.get("ender_chest", {}).items():
            slot_idx = int(k)
            if 0 <= slot_idx < 27:
                inv.ender_chest[slot_idx] = ItemStack(
                    item_id=v.get("item", "minecraft:air"),
                    count=v.get("count", 1),
                    damage=v.get("damage", 0),
                    nbt=v.get("nbt", {}),
                )
        inv._selected_slot = data.get("selected_slot", 0)
        inv.held_slot = data.get("held_slot", 0)
        return inv

    @classmethod
    def from_legacy(cls, data: dict) -> 'PlayerInventory':
        """Create from legacy serialization format."""
        return cls.deserialize_full(data)

    def to_legacy_tuple(self, slot: int) -> tuple[str, int] | None:
        """Convert a slot to legacy tuple format for old code compatibility."""
        item = self.get_slot(slot)
        if item is None or item.is_empty:
            return None
        return (item.item_id, item.count)


# --------------------------------------------------
# Protocol Encoding
# --------------------------------------------------

def encode_slot_entry(item: ItemStack | None) -> bytes:
    """
    Encode a single inventory slot for the Minecraft protocol.
    Empty slot: write_boolean(False)
    Filled slot: write_boolean(True) + write_varint(item_id) + count + nbt
    """
    if item is None or item.is_empty:
        return write_boolean(False)

    payload = bytearray()
    payload.extend(write_boolean(True))

    # Item protocol ID
    item_id = item_name_to_protocol_id(item.item_id)
    payload.extend(write_varint(item_id))

    # Count (as VarInt in 1.21.1+)
    payload.extend(write_varint(max(1, min(127, item.count))))

    # NBT data: 0 byte means no NBT
    if item.nbt:
        from protocol.nbt import encode_nbt
        try:
            nbt_data = encode_nbt(item.nbt, with_type=True, root_name="")
            payload.extend(nbt_data)
        except Exception:
            payload.extend(write_byte(0))
    else:
        payload.extend(write_byte(0))

    return bytes(payload)


def decode_slot_entry(data: bytes, offset: int = 0) -> tuple[ItemStack | None, int]:
    """
    Decode a single inventory slot from the Minecraft protocol.
    
    Returns (ItemStack or None, new_offset).
    Empty slot: read_boolean(False) -> returns (None, offset+1)
    Filled slot: read_boolean(True) + read_varint(item_id) + count + nbt
    """
    from protocol.data_types import read_varint, read_boolean, read_byte, read_short

    present, offset = read_boolean(data, offset)
    if not present:
        return (None, offset)

    # Item protocol ID
    item_id_raw, offset = read_varint(data, offset)
    item_name = protocol_id_to_item_name(item_id_raw)
    if item_name is None:
        item_name = f"minecraft:unknown_{item_id_raw}"

    # Count (VarInt in 1.21.1+)
    count, offset = read_varint(data, offset)

    # NBT data: first byte tells us if there's NBT
    # 0x00 means no NBT, anything else is the start of an NBT compound
    nbt_start = data[offset] if offset < len(data) else 0
    if nbt_start == 0:
        # No NBT
        offset += 1
        nbt_data = None
    else:
        # NBT data present - skip it for now
        # (Proper NBT parsing would require reading the compound tag)
        # For simplicity, just note that NBT exists and skip it
        nbt_data = None
        try:
            from protocol.nbt import decode_nbt
            nbt_data, offset = decode_nbt(data, offset)
        except Exception:
            # If NBT parsing fails, we can't reliably skip it
            # Return the item without NBT
            pass

    item = ItemStack(item_id=item_name, count=max(1, count))
    if nbt_data and isinstance(nbt_data, dict):
        item.nbt = nbt_data

    return (item, offset)


def build_set_container_content_payload(
    window_id: int,
    state_id: int,
    slots: list[ItemStack | None],
    carried_item: ItemStack | None = None,
) -> bytes:
    """
    Build Set Container Content packet payload (0x11 in 1.21.1).
    Sends complete container contents.
    """
    payload = bytearray()
    payload.extend(write_varint(window_id))     # Window ID (VarInt in 1.21.1+)
    payload.extend(write_varint(state_id))      # State ID
    payload.extend(write_varint(len(slots)))    # Slot count

    for slot in slots:
        payload.extend(encode_slot_entry(slot))

    # Carried item (cursor)
    payload.extend(encode_slot_entry(carried_item))

    return bytes(payload)


def build_set_slot_payload(
    window_id: int,
    state_id: int,
    slot: int,
    item: ItemStack | None = None,
) -> bytes:
    """
    Build Set Slot packet payload (0x12 in 1.21.1).
    Updates a single inventory slot.
    """
    payload = bytearray()
    payload.extend(write_varint(window_id))     # Window ID
    payload.extend(write_varint(state_id))      # State ID
    payload.extend(write_varint(slot))           # Slot index (VarInt in 1.21.1+)
    payload.extend(encode_slot_entry(item))      # Slot data
    return bytes(payload)


def build_open_screen_payload(
    window_id: int,
    window_type: str,
    window_title: str,
) -> bytes:
    """
    Build Open Screen packet payload (0x3F in 1.21.1).
    Opens a container window on the client.
    """
    payload = bytearray()
    payload.extend(write_varint(window_id))     # Container ID
    # Window type as VarInt (inventory type registry)
    _WINDOW_TYPE_IDS = {
        "minecraft:container": 0,
        "minecraft:chest": 0,
        "minecraft:crafting": 1,
        "minecraft:furnace": 2,
        "minecraft:blast_furnace": 4,
        "minecraft:smoker": 5,
        "minecraft:anvil": 7,
        "minecraft:hopper": 9,
        "minecraft:generic_9x1": 10,
        "minecraft:generic_9x2": 11,
        "minecraft:generic_9x3": 12,
        "minecraft:generic_9x4": 13,
        "minecraft:generic_9x5": 14,
        "minecraft:generic_9x6": 15,
        "minecraft:generic_3x3": 16,
    }
    type_id = _WINDOW_TYPE_IDS.get(window_type, 0)
    payload.extend(write_varint(type_id))

    # Title as JSON chat component
    import json
    title_json = json.dumps({"text": window_title})
    from protocol.data_types import write_string
    payload.extend(write_string(title_json))

    return bytes(payload)


# --------------------------------------------------
# Inventory sync functions
# --------------------------------------------------

async def send_inventory_sync(conn):
    """
    Send full inventory sync to the client.
    Uses Set Container Content packet (0x11 in 1.21.1).
    """
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    from protocol.packet_map import get_clientbound_packet

    # Build complete slot list (46 slots)
    slot_list: list[ItemStack | None] = []
    for i in range(PlayerInventory.TOTAL_SLOTS):
        slot_list.append(inv.slots[i] if i < len(inv.slots) else None)

    payload = build_set_container_content_payload(
        window_id=PlayerInventory.WINDOW_PLAYER if hasattr(PlayerInventory, 'WINDOW_PLAYER') else 0,
        state_id=getattr(conn, 'inventory_state_id', 0),
        slots=slot_list,
        carried_item=inv.carried_item,
    )

    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "window_items")
    if pid is not None:
        await conn.send_packet(pid, payload)
    else:
        # Fallback: use 1.21.1 native packet ID
        await conn.send_packet(0x11, payload)


async def send_slot_update(conn, slot: int):
    """
    Send a single slot update to the client.
    Uses Set Slot packet (0x12 in 1.21.1).
    """
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    item = inv.get_slot(slot)
    payload = build_set_slot_payload(
        window_id=0,  # Player inventory
        state_id=getattr(conn, 'inventory_state_id', 0),
        slot=slot,
        item=item,
    )
    # Set Slot is 0x12 in 1.21.1
    await conn.send_packet(0x12, payload)


async def send_hotbar_update(conn):
    """Send hotbar contents sync."""
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return
    for slot in range(9):
        await send_slot_update(conn, slot)


async def send_open_container(conn, window_id: int, window_type: str,
                               window_title: str):
    """Send the Open Screen packet to open a container window."""
    payload = build_open_screen_payload(window_id, window_type, window_title)
    # Open Screen is 0x3F in 1.21.1
    await conn.send_packet(0x3F, payload)


async def send_container_content(conn, window_id: int, slots: list[ItemStack | None]):
    """Send container contents for a specific window."""
    inv = getattr(conn, 'inventory_obj', None)

    # For non-player containers, send the container's own slots
    payload = build_set_container_content_payload(
        window_id=window_id,
        state_id=getattr(conn, 'inventory_state_id', 0),
        slots=slots,
        carried_item=inv.carried_item if inv else None,
    )

    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "window_items")
    if pid is not None:
        await conn.send_packet(pid, payload)
    else:
        await conn.send_packet(0x11, payload)


def initialize_player_inventory(conn):
    """Initialize a player's inventory with default creative hotbar items."""
    if not hasattr(conn, 'inventory_obj') or conn.inventory_obj is None:
        conn.inventory_obj = PlayerInventory()
        conn.inventory_state_id = 0

    # Default creative hotbar
    _DEFAULT_HOTBAR = [
        "minecraft:stone",
        "minecraft:grass_block",
        "minecraft:dirt",
        "minecraft:cobblestone",
        "minecraft:oak_planks",
        "minecraft:glass",
        "minecraft:sand",
        "minecraft:oak_log",
        "minecraft:torch",
    ]
    for i, item_name in enumerate(_DEFAULT_HOTBAR):
        conn.inventory_obj.set_slot(i, ItemStack(item_name, 64))
