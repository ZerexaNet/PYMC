"""
Crafting grids: the 2x2 grid of the player inventory (window 0) and the 3x3
grid of a crafting table.

Window slot layouts (vanilla):
    inventory (window 0): 0 result, 1-4 grid (stored in PlayerInventory 41-44,
                          result mirror in 45)
    crafting table:       0 result, 1-9 grid, 10-36 main inventory, 37-45 hotbar
"""

from __future__ import annotations

from .crafting import CRAFTING_REMAINDERS, match_crafting_grid
from .inventory import ItemStack

PLAYER_GRID = (41, 42, 43, 44)
PLAYER_RESULT = 45


def is_crafting_window(conn, window_id: int) -> bool:
    if window_id == 0:
        return True
    return (getattr(conn, '_open_window_id', None) == window_id
            and getattr(conn, '_open_container_type', None) == 'crafting')


def grid_slots(conn, window_id: int) -> tuple[list, list[int] | None, int]:
    """(grid storage list, storage indices or None, width)."""
    if window_id == 0:
        return conn.inventory_obj.slots, list(PLAYER_GRID), 2
    grid = getattr(conn, '_crafting_grid', None)
    if grid is None:
        grid = conn._crafting_grid = [None] * 9
    return grid, None, 3


def _grid_items(conn, window_id: int) -> list:
    store, indices, _ = grid_slots(conn, window_id)
    return [store[i] for i in indices] if indices is not None else list(store)


def _set_grid_item(conn, window_id: int, index: int, item):
    store, indices, _ = grid_slots(conn, window_id)
    if item is not None and item.is_empty:
        item = None
    store[indices[index] if indices is not None else index] = item


def current_result(conn, window_id: int) -> ItemStack | None:
    """The item the grid would craft right now."""
    _, _, width = grid_slots(conn, window_id)
    items = _grid_items(conn, window_id)
    names = ["" if item is None or item.is_empty else item.item_id for item in items]
    found = match_crafting_grid(names, width)
    if found is None:
        return None
    item_id, count = found
    return ItemStack(item_id, int(count))


def refresh_result(conn, window_id: int) -> ItemStack | None:
    """Recompute the result; window 0 keeps it in PlayerInventory slot 45 for syncing."""
    result = current_result(conn, window_id)
    if window_id == 0:
        conn.inventory_obj.slots[PLAYER_RESULT] = result
    return result


def _consume_grid(conn, window_id: int, give_back) -> None:
    """Use up one item from every filled cell, leaving crafting remainders behind."""
    for index, item in enumerate(_grid_items(conn, window_id)):
        if item is None or item.is_empty:
            continue
        remainder = CRAFTING_REMAINDERS.get(item.item_id)
        item.count -= 1
        if item.count <= 0:
            _set_grid_item(conn, window_id, index, ItemStack(remainder, 1) if remainder else None)
        elif remainder:
            give_back(ItemStack(remainder, 1))


def take_result(conn, window_id: int, give_back) -> ItemStack | None:
    """Craft once: returns the crafted stack (or None) and consumes the grid."""
    result = current_result(conn, window_id)
    if result is None:
        return None
    _consume_grid(conn, window_id, give_back)
    refresh_result(conn, window_id)
    return result


def window_items(conn, window_id: int) -> list:
    """Result + grid, the leading part of a crafting window."""
    return [current_result(conn, window_id)] + _grid_items(conn, window_id)


def return_grid_items(conn, window_id: int, give_back) -> None:
    """Closing the window: the grid's contents go back to the player."""
    for index, item in enumerate(_grid_items(conn, window_id)):
        if item is not None and not item.is_empty:
            _set_grid_item(conn, window_id, index, None)
            give_back(item)
    if window_id == 0:
        conn.inventory_obj.slots[PLAYER_RESULT] = None
