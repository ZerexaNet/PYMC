# ============================================================
# PyMC - 玩家状态管理
# 物品栏、装备、末影箱等玩家状态管理
# 集成新的 ItemStack 物品栏系统
# ============================================================

"""
玩家状态与物品栏管理。

此模块现在使用 world/inventory.py 中的 ItemStack-based 物品栏系统。
保留旧的 PlayerInventory 类作为向后兼容包装器。

包括:
  - PlayerInventory: 物品栏数据结构 (向后兼容包装器)
  - 物品栏数据包构建 (Set Container Content, Set Slot)
  - 装备同步
  - 物品序列化/反序列化
"""

import logging
from typing import Optional

from protocol.data_types import (
    write_varint, write_boolean, write_short, write_byte,
)

logger = logging.getLogger("PyMC.玩家状态")

# Import the new ItemStack-based system
from world.inventory import (
    ItemStack,
    PlayerInventory as NewPlayerInventory,
    encode_slot_entry,
    build_set_container_content_payload as new_build_container_payload,
    build_set_slot_payload as new_build_slot_payload,
    build_open_screen_payload,
    item_name_to_protocol_id,
    protocol_id_to_item_name,
    send_inventory_sync as new_send_inventory_sync,
    send_slot_update as new_send_slot_update,
    send_hotbar_update as new_send_hotbar_update,
    send_open_container as new_send_open_container,
    send_container_content as new_send_container_content,
    initialize_player_inventory as new_initialize_inventory,
)


# Re-export new functions for external use
send_inventory_sync = new_send_inventory_sync
send_slot_update = new_send_slot_update
send_hotbar_update = new_send_hotbar_update
send_open_container = new_send_open_container
send_container_content = new_send_container_content
initialize_player_inventory = new_initialize_inventory


class PlayerInventory:
    """
    Legacy PlayerInventory wrapper that delegates to the new ItemStack-based system.

    This class provides backward compatibility for code that still uses the
    old tuple-based API (item_name, count). It wraps the new system internally.

    The new system (world.inventory.PlayerInventory) uses ItemStack objects
    and should be preferred for new code.
    """

    WINDOW_PLAYER = 0
    WINDOW_ENDER_CHEST = 13

    def __init__(self):
        self._inv = NewPlayerInventory()
        self._selected_slot = 0

    @property
    def slots(self) -> dict:
        """
        Legacy slots dict accessor.
        Returns a dict[int, tuple[str, int]] for backward compatibility.
        """
        result = {}
        for i in range(NewPlayerInventory.TOTAL_SLOTS):
            item = self._inv.get_slot(i)
            if item is not None and not item.is_empty():
                result[i] = (item.item_id, item.count)
        return result

    @slots.setter
    def slots(self, value):
        """Set slots from legacy dict format."""
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, tuple) and len(v) == 2:
                    self._inv.set_slot(int(k), ItemStack(v[0], v[1]))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                if v is not None:
                    if isinstance(v, tuple) and len(v) == 2:
                        self._inv.set_slot(i, ItemStack(v[0], v[1]))
                    elif isinstance(v, ItemStack):
                        self._inv.set_slot(i, v)
                else:
                    self._inv.set_slot(i, None)

    @property
    def ender_chest(self) -> dict:
        """Legacy ender chest dict accessor."""
        result = {}
        for i in range(27):
            item = self._inv.ender_chest[i]
            if item is not None and not item.is_empty():
                result[i] = (item.item_id, item.count)
        return result

    @ender_chest.setter
    def ender_chest(self, value):
        """Set ender chest from legacy dict format."""
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, tuple) and len(v) == 2:
                    self._inv.ender_chest[int(k)] = ItemStack(v[0], v[1])

    @property
    def selected_slot(self) -> int:
        return self._selected_slot

    @selected_slot.setter
    def selected_slot(self, value: int):
        self._selected_slot = value

    @property
    def carried_item(self):
        """Legacy carried item accessor."""
        if self._inv.carried_item is not None and not self._inv.carried_item.is_empty():
            return (self._inv.carried_item.item_id, self._inv.carried_item.count)
        return None

    @carried_item.setter
    def carried_item(self, value):
        if value is None:
            self._inv.carried_item = None
        elif isinstance(value, tuple) and len(value) == 2:
            self._inv.carried_item = ItemStack(value[0], value[1])

    @property
    def state_id(self) -> int:
        return self._inv.state_id

    @state_id.setter
    def state_id(self, value: int):
        self._inv.state_id = value

    def get_slot(self, slot: int) -> Optional[tuple[str, int]]:
        """获取指定槽位的物品 (legacy tuple format)."""
        item = self._inv.get_slot(slot)
        if item is not None and not item.is_empty():
            return (item.item_id, item.count)
        return None

    def set_slot(self, slot: int, item_name: str, count: int):
        """设置指定槽位的物品."""
        if count <= 0:
            self._inv.set_slot(slot, None)
        else:
            self._inv.set_slot(slot, ItemStack(item_name, count))

    def set_item_in_slot(self, slot: int, data: dict):
        """Set item in slot from dict (for /item command)."""
        item_name = data.get("item", "minecraft:air")
        count = data.get("count", 1)
        self.set_slot(slot, item_name, count)

    def get_item_in_slot(self, slot: int) -> dict | None:
        """Get item in slot as dict (for /item command)."""
        item = self._inv.get_slot(slot)
        if item is not None and not item.is_empty():
            return {"item": item.item_id, "count": item.count}
        return None

    def clear_slot(self, slot: int):
        """清除指定槽位。"""
        self._inv.set_slot(slot, None)

    def add_item(self, item_name: str, count: int = 1) -> int:
        """
        尝试添加物品到物品栏，返回无法添加的数量。
        优先堆叠到已有的同类物品，再放到空位。
        """
        return self._inv.add_item(ItemStack(item_name, count))

    def remove_item(self, item_name: str, count: int = 1) -> int:
        """
        尝试从物品栏移除物品，返回实际移除的数量。
        """
        result = self._inv.remove_item(item_name, count)
        return count if result else 0

    def count_item(self, item_name: str) -> int:
        """计算物品栏中某物品的总数。"""
        return self._inv.count_item(item_name)

    def get_held_item(self) -> Optional[tuple[str, int]]:
        """获取当前手持的物品。"""
        return self.get_slot(self._selected_slot)

    def get_armor(self) -> dict[int, tuple[str, int]]:
        """获取装备栏内容。"""
        armor = self._inv.get_armor()
        result = {}
        for i, item in enumerate(armor):
            if item is not None and not item.is_empty():
                slot = 36 + i  # Armor slots start at 36
                result[slot] = (item.item_id, item.count)
        return result

    def clear_items(self, item_filter: str | None = None,
                     max_count: int = -1) -> int:
        """Clear items, optionally filtered. Returns count cleared."""
        return self._inv.clear_items(item_filter=item_filter, max_count=max_count)

    def serialize(self) -> dict:
        """序列化物品栏数据用于存档。"""
        return self._inv.serialize()

    @classmethod
    def deserialize(cls, data: dict) -> 'PlayerInventory':
        """从存档数据反序列化物品栏。"""
        inv = cls()
        inv._inv = NewPlayerInventory.from_legacy(data)
        inv._selected_slot = data.get("selected_slot", 0)
        return inv

    # --- New API access ---

    def get_new_inventory(self) -> NewPlayerInventory:
        """Get the underlying new ItemStack-based inventory."""
        return self._inv

    def get_held_item_stack(self) -> ItemStack | None:
        """Get the currently held item as an ItemStack."""
        return self._inv.get_held_item_from_slot(self._selected_slot)


# --- Legacy encoding functions (kept for backward compat) ---

def _encode_slot_entry(item: Optional[tuple[str, int]]) -> bytes:
    """
    编码单个物品栏槽位 (legacy tuple format).
    新代码应使用 world.inventory.encode_slot_entry
    """
    if item is None:
        return write_boolean(False)

    item_name, count = item
    stack = ItemStack(item_name, count)
    return encode_slot_entry(stack)


def _item_name_to_protocol_id(item_name: str) -> int:
    """
    将物品命名空间 ID 转换为协议数值 ID。
    新代码应使用 world.inventory.item_name_to_protocol_id
    """
    return item_name_to_protocol_id(item_name)


def build_set_container_content_payload(
    window_id: int,
    state_id: int,
    slots: list,
    carried_item=None,
) -> bytes:
    """
    构建 Set Container Content 数据包负载 (legacy format).
    新代码应使用 world.inventory.build_set_container_content_payload
    """
    # Convert legacy tuples to ItemStacks
    new_slots = []
    for slot in slots:
        if slot is None:
            new_slots.append(None)
        elif isinstance(slot, tuple) and len(slot) == 2:
            new_slots.append(ItemStack(slot[0], slot[1]))
        elif isinstance(slot, ItemStack):
            new_slots.append(slot)
        else:
            new_slots.append(None)

    new_carried = None
    if carried_item is not None:
        if isinstance(carried_item, tuple) and len(carried_item) == 2:
            new_carried = ItemStack(carried_item[0], carried_item[1])
        elif isinstance(carried_item, ItemStack):
            new_carried = carried_item

    return new_build_container_payload(window_id, state_id, new_slots, new_carried)


def build_set_slot_payload(
    window_id: int,
    state_id: int,
    slot: int,
    item=None,
) -> bytes:
    """
    构建 Set Slot 数据包负载 (legacy format).
    新代码应使用 world.inventory.build_set_slot_payload
    """
    new_item = None
    if item is not None:
        if isinstance(item, tuple) and len(item) == 2:
            new_item = ItemStack(item[0], item[1])
        elif isinstance(item, ItemStack):
            new_item = item

    return new_build_slot_payload(window_id, state_id, slot, new_item)
