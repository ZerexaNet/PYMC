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

# The full 1.21.1 item registry (1333 items) lives in
# protocol/data/items_767.json; list position is the protocol ID.

def _item_ids() -> dict[str, int]:
    from protocol.gamedata import item_ids
    return item_ids()


def _normalize_item_name(item_name: str) -> str:
    name = str(item_name or "minecraft:air")
    return name if ":" in name else f"minecraft:{name}"


def is_known_item(item_name: str) -> bool:
    """True if the identifier exists in the 1.21.1 item registry."""
    return _normalize_item_name(item_name) in _item_ids()


def item_name_to_protocol_id(item_name: str) -> int:
    """Convert a Minecraft item namespace ID to its protocol numeric ID."""
    return _item_ids().get(_normalize_item_name(item_name), 1)


def protocol_id_to_item_name(protocol_id: int) -> str:
    """Convert a protocol numeric ID to a Minecraft item namespace ID."""
    from protocol.gamedata import item_names
    names = item_names()
    if 0 <= protocol_id < len(names):
        return names[protocol_id]
    return "minecraft:stone"


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
        """Maximum stack size for this item type (vanilla 1.21.1 table)."""
        from protocol.gamedata import item_stack_sizes
        return item_stack_sizes().get(_normalize_item_name(self.item_id), 64)

    @property
    def max_durability(self) -> int:
        """Maximum durability (0 for items that cannot be damaged)."""
        from protocol.gamedata import item_durability
        return item_durability().get(_normalize_item_name(self.item_id), 0)

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
        max_stack = item.max_stack_size
        # 原版顺序: 先堆叠到已有的同类物品 (手持 -> 副手 -> 快捷栏 -> 背包),
        # 再放入空槽位 (快捷栏 0-8 -> 背包 9-35)。合成格/护甲栏不参与。
        storage = list(range(0, 36))
        if max_stack > 1:
            for i in [40] + storage:
                slot = self.slots[i]
                if (slot and not slot.is_empty and slot.can_stack_with(item)
                        and slot.count < max_stack):
                    add = min(max_stack - slot.count, remaining)
                    slot.count += add
                    remaining -= add
                    if remaining <= 0:
                        self.state_id += 1
                        return 0
        for i in storage:
            if self.slots[i] is None or self.slots[i].is_empty:
                add = min(max_stack, remaining)
                self.slots[i] = ItemStack(item.item_id, add, item.damage,
                                          dict(item.nbt) if item.nbt else {})
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

SLOT_COMPONENT_DAMAGE = 3  # minecraft:damage in the 1.21.1 data component registry
SLOT_COMPONENT_ENCHANTMENTS = 9          # minecraft:enchantments (ItemEnchantments)
SLOT_COMPONENT_STORED_ENCHANTMENTS = 23  # minecraft:stored_enchantments (enchanted books)


def _enchantments_payload(levels: dict) -> bytes | None:
    """ItemEnchantments: count, (registry id, level) pairs, show tooltip."""
    from protocol.data_types import write_boolean
    from world.enchanting import protocol_id
    entries = []
    for name, level in levels.items():
        registry_id = protocol_id(name)
        if registry_id is not None and int(level) > 0:
            entries.append((registry_id, int(level)))
    if not entries:
        return None
    out = bytearray(write_varint(len(entries)))
    for registry_id, level in entries:
        out.extend(write_varint(registry_id))
        out.extend(write_varint(level))
    out.extend(write_boolean(True))
    return bytes(out)


def encode_slot_entry(item: ItemStack | None) -> bytes:
    """
    Encode a single inventory slot for the Minecraft 1.20.5+ protocol.

    1.20.5+ Slot format (from PrismarineJS minecraft-data 1.21.1/protocol.json):

        VarInt  itemCount   (0 = empty slot; non-zero = stack size)
        IF itemCount != 0:
            VarInt  itemId               (index into minecraft:item registry)
            VarInt  addedComponentCount  (number of present slot components)
            VarInt  removedComponentCount (number of default-removed components)
            SlotComponent[addedComponentCount]   (each: VarInt type + typed data)
            VarInt[removedComponentCount]         (each: a SlotComponentType id)

    For a vanilla item with no component overrides (which is what we currently
    send), addedComponentCount=0 and removedComponentCount=0 — so a non-empty
    slot is just 4 bytes: itemCount + itemId + 0 + 0.

    PREVIOUSLY this function used the legacy 1.20.4-and-earlier format
    (Boolean present + VarInt itemId + Byte count + NBT). That format was
    REMOVED in 1.20.5 and caused client error:
      "Failed to decode packet 'clientbound/minecraft:container_set_content' /
       No value with id 64"
    because the client misread the count byte as a component count.
    """
    if item is None or item.is_empty:
        # Empty slot: just a VarInt 0
        return write_varint(0)

    payload = bytearray()
    # itemCount (non-zero = stack size, sent FIRST in 1.20.5+)
    payload.extend(write_varint(max(1, min(127, item.count))))

    # itemId: index into the minecraft:item registry
    # (which is BUILT-IN to the client, NOT sent via Registry Data)
    item_id = item_name_to_protocol_id(item.item_id)
    payload.extend(write_varint(item_id))

    # Data components. Only the ones PyMC tracks are sent:
    #   3 = minecraft:damage (VarInt) -> durability bar on tools/armor
    components = bytearray()
    component_count = 0
    damage = int(getattr(item, "damage", 0) or 0)
    if damage > 0 and item.max_durability > 0:
        components.extend(write_varint(SLOT_COMPONENT_DAMAGE))
        components.extend(write_varint(min(damage, item.max_durability)))
        component_count += 1
    nbt = getattr(item, "nbt", None) or {}
    for key, component in (("enchantments", SLOT_COMPONENT_ENCHANTMENTS),
                           ("stored_enchantments", SLOT_COMPONENT_STORED_ENCHANTMENTS)):
        enchant_data = _enchantments_payload(nbt.get(key) or {})
        if enchant_data is not None:
            components.extend(write_varint(component))
            components.extend(enchant_data)
            component_count += 1

    payload.extend(write_varint(component_count))  # addedComponentCount
    payload.extend(write_varint(0))                # removedComponentCount
    payload.extend(components)

    # NOTE: If we ever need to send custom NBT (custom_name, enchantments,
    # durability, etc.), it must be encoded as a SlotComponent with the
    # appropriate SlotComponentType VarInt followed by the typed payload,
    # NOT as a raw trailing NBT blob. The legacy "trailing NBT" format was
    # removed in 1.20.5. For now we send zero components, which means the
    # client uses the item's default components from its built-in registry.

    return bytes(payload)


def decode_slot_entry(data: bytes, offset: int = 0) -> tuple[ItemStack | None, int]:
    """
    Decode a single inventory slot from the Minecraft 1.20.5+ protocol.

    Returns (ItemStack or None, new_offset).
    """
    from protocol.data_types import read_varint

    # itemCount (VarInt, 0 = empty)
    item_count, offset = read_varint(data, offset)
    if item_count == 0:
        return (None, offset)

    # itemId
    item_id_raw, offset = read_varint(data, offset)
    item_name = protocol_id_to_item_name(item_id_raw)
    if item_name is None:
        item_name = f"minecraft:unknown_{item_id_raw}"

    # addedComponentCount, removedComponentCount, then the component data
    added_count, offset = read_varint(data, offset)
    removed_count, offset = read_varint(data, offset)
    damage = 0
    nbt: dict = {}
    for index in range(added_count):
        component_type, offset = read_varint(data, offset)
        if component_type == SLOT_COMPONENT_DAMAGE:
            damage, offset = read_varint(data, offset)
        elif component_type in (1, 2):      # max_stack_size / max_damage: VarInt
            _value, offset = read_varint(data, offset)
        elif component_type in (SLOT_COMPONENT_ENCHANTMENTS, SLOT_COMPONENT_STORED_ENCHANTMENTS):
            from world.enchanting import name_of_protocol_id
            from protocol.data_types import read_boolean
            count, offset = read_varint(data, offset)
            levels = {}
            for _ in range(count):
                registry_id, offset = read_varint(data, offset)
                level, offset = read_varint(data, offset)
                name = name_of_protocol_id(registry_id)
                if name is not None:
                    levels[name.split(":", 1)[-1]] = level
            _show_tooltip, offset = read_boolean(data, offset)
            key = "enchantments" if component_type == SLOT_COMPONENT_ENCHANTMENTS else "stored_enchantments"
            if levels:
                nbt[key] = levels
        else:
            # Other component payloads (names, enchantments, potion contents...)
            # are not decoded; the rest of this slot cannot be parsed reliably.
            offset = len(data)
            removed_count = 0
            break
    for _ in range(removed_count):
        _removed_type, offset = read_varint(data, offset)

    item = ItemStack(item_id=item_name, count=max(1, item_count), damage=damage, nbt=nbt)
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
    payload.append(window_id & 0xFF)            # Window ID (unsigned byte in 1.21.1)
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
    payload.append(window_id & 0xFF)            # Window ID (signed byte; -2 = player inventory)
    payload.extend(write_varint(state_id))      # State ID
    payload.extend(write_short(slot))           # Slot index (short in 1.21.1)
    payload.extend(encode_slot_entry(item))      # Slot data
    return bytes(payload)


def build_open_screen_payload(
    window_id: int,
    window_type: str,
    window_title: str,
    protocol_version: int = 767,
) -> bytes:
    """
    Build Open Screen packet payload (0x3F in 1.21.1).
    Opens a container window on the client.
    """
    payload = bytearray()
    payload.extend(write_varint(window_id))     # Container ID
    # Window type as VarInt (inventory type registry)
    # minecraft:menu registry (1.21.1 protocol order)
    _WINDOW_TYPE_IDS = {
        "minecraft:generic_9x1": 0,
        "minecraft:generic_9x2": 1,
        "minecraft:generic_9x3": 2,
        "minecraft:container": 2,
        "minecraft:chest": 2,
        "minecraft:generic_9x4": 3,
        "minecraft:generic_9x5": 4,
        "minecraft:generic_9x6": 5,
        "minecraft:generic_3x3": 6,
        "minecraft:crafter_3x3": 7,
        "minecraft:anvil": 8,
        "minecraft:beacon": 9,
        "minecraft:blast_furnace": 10,
        "minecraft:brewing_stand": 11,
        "minecraft:crafting": 12,
        "minecraft:enchantment": 13,
        "minecraft:furnace": 14,
        "minecraft:grindstone": 15,
        "minecraft:hopper": 16,
        "minecraft:lectern": 17,
        "minecraft:loom": 18,
        "minecraft:merchant": 19,
        "minecraft:shulker_box": 20,
        "minecraft:smithing": 21,
        "minecraft:smoker": 22,
        "minecraft:cartography_table": 23,
        "minecraft:stonecutter": 24,
    }
    type_id = _WINDOW_TYPE_IDS.get(window_type, 2)
    payload.extend(write_varint(type_id))

    # Title: text component (NBT on 1.20.3+)
    from protocol.text import encode_component
    payload.extend(encode_component(window_title, protocol_version))

    return bytes(payload)


# --------------------------------------------------
# Inventory sync functions
# --------------------------------------------------

def window_slot_to_inventory(slot: int) -> int | None:
    """Player window (id 0) slot -> PlayerInventory index."""
    if slot == 0:        # crafting output
        return 45
    if 1 <= slot <= 4:   # 2x2 crafting input
        return 40 + slot
    if 5 <= slot <= 8:   # helmet, chestplate, leggings, boots
        return 44 - slot
    if 9 <= slot <= 35:  # main inventory
        return slot
    if 36 <= slot <= 44:  # hotbar
        return slot - 36
    if slot == 45:       # offhand
        return 40
    return None


PLAYER_WINDOW_SLOTS = 46


def player_window_slots(inv) -> list:
    """PlayerInventory contents in the client's window-0 slot order."""
    return [inv.slots[window_slot_to_inventory(w)] for w in range(PLAYER_WINDOW_SLOTS)]


def slot_snapshot(item) -> tuple | None:
    """Comparable view of a slot (what the client is believed to show)."""
    if item is None or item.is_empty:
        return None
    nbt = item.nbt or {}
    try:
        extra = repr(sorted(nbt.items())) if nbt else ""
    except TypeError:
        extra = repr(nbt)
    return (item.item_id, int(item.count), int(item.damage or 0), extra)


def remember_remote_window(conn, window_id: int, slots: list, carried) -> None:
    """
    Record what the client was just sent for a window, so later clicks can
    answer with only the slots that differ (vanilla remoteSlots).
    """
    conn._remote_window = {
        "window": window_id,
        "slots": [slot_snapshot(item) for item in slots],
        "carried": slot_snapshot(carried),
    }


def forget_remote_window(conn) -> None:
    conn._remote_window = None


async def send_inventory_sync(conn):
    """
    Send the full player inventory (Set Container Content, window 0).

    The client's inventory window has its own slot order (crafting 0-4, armor
    5-8, main 9-35, hotbar 36-44, offhand 45), which differs from
    PlayerInventory's storage order, so slots are remapped here.
    """
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    from protocol.packet_map import get_clientbound_packet

    slots = player_window_slots(inv)
    payload = build_set_container_content_payload(
        window_id=0,
        state_id=getattr(conn, 'inventory_state_id', 0),
        slots=slots,
        carried_item=inv.carried_item,
    )
    remember_remote_window(conn, 0, slots, inv.carried_item)

    pid = get_clientbound_packet(conn.protocol_version, "window_items")
    await conn.send_packet(pid if pid is not None else 0x13, payload)


async def send_slot_update(conn, slot: int):
    """
    Update one PlayerInventory slot on the client (Set Slot).

    Uses window id -2, which addresses the player inventory by storage index
    (0-8 hotbar, 9-35 main, 36-39 armor, 40 offhand) regardless of which
    window is currently open.
    """
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    payload = build_set_slot_payload(
        window_id=-2,
        state_id=getattr(conn, 'inventory_state_id', 0),
        slot=slot,
        item=inv.get_slot(slot),
    )
    forget_remote_window(conn)
    from protocol.packet_map import get_clientbound_packet
    set_slot_pid = get_clientbound_packet(conn.protocol_version, "set_slot")
    await conn.send_packet(set_slot_pid if set_slot_pid is not None else 0x15, payload)


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
    payload = build_open_screen_payload(window_id, window_type, window_title,
                                        getattr(conn, 'protocol_version', 767))
    # Open Screen is 0x33 in 1.21.1 (was incorrectly hardcoded as 0x3F which is face_player)
    from protocol.packet_map import get_clientbound_packet
    open_screen_pid = get_clientbound_packet(conn.protocol_version, "open_screen")
    if open_screen_pid is not None:
        await conn.send_packet(open_screen_pid, payload)
    else:
        await conn.send_packet(0x33, payload)


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
    remember_remote_window(conn, window_id, slots, inv.carried_item if inv else None)

    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "window_items")
    if pid is not None:
        await conn.send_packet(pid, payload)
    else:
        await conn.send_packet(0x13, payload)  # 0x13 = window_items in 1.21.1


async def send_window_slot(conn, window_id: int, slot: int, item) -> None:
    """Set Slot for one slot of a window (slot -1 with window -1: the cursor)."""
    payload = build_set_slot_payload(
        window_id=window_id,
        state_id=getattr(conn, 'inventory_state_id', 0),
        slot=slot,
        item=item,
    )
    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "set_slot")
    await conn.send_packet(pid if pid is not None else 0x15, payload)


def initialize_player_inventory(conn):
    """Give a first-time player an empty inventory, like the vanilla server."""
    if not hasattr(conn, 'inventory_obj') or conn.inventory_obj is None:
        conn.inventory_obj = PlayerInventory()
        conn.inventory_state_id = 0
