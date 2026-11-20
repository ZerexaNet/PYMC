"""
Enchanting table and anvil windows: offers, the enchant button, anvil output,
experience and lapis costs, and returning the inputs when the window closes.

Window layouts:
  enchanting table  slot 0 = item, slot 1 = lapis lazuli
  anvil             slot 0 = left item, slot 1 = right item, slot 2 = result (take only)
"""

from __future__ import annotations

import logging
import random
import struct

from . import enchanting
from .inventory import ItemStack

logger = logging.getLogger("PyMC.附魔")

ENCHANT_TABLE = "enchanting_table"
ANVIL = "anvil"
ANVIL_RESULT_SLOT = 2
TOO_EXPENSIVE = enchanting.TOO_EXPENSIVE

# "Too Expensive!": the anvil refuses results from TOO_EXPENSIVE levels up (vanilla). Servers can
# switch the limit off with the anvil-too-expensive-limit property.
_limit_too_expensive = True


def set_too_expensive_limit(enabled: bool):
    global _limit_too_expensive
    _limit_too_expensive = bool(enabled)


def too_expensive_limit() -> bool:
    return _limit_too_expensive

# clientbound "Container Set Data" (craft_progress_bar, 0x14 in 1.21.1)
_PROPERTY_PACKET = "craft_progress_bar"


def _is_creative(conn) -> bool:
    return getattr(conn, "gamemode", "") == "creative"


def _block_reader(x: int, y: int, z: int):
    from .block_behavior import container_manager
    reader = getattr(container_manager, "block_reader", None)
    return reader(x, y, z) if reader is not None else None


def refresh(conn, container, pos) -> dict:
    """Recompute the offers (table) or the result (anvil); returns the property values to send."""
    if container.type == ENCHANT_TABLE:
        item = container.items[0]
        power = enchanting.bookshelf_power(_block_reader, *pos)
        if item is None or item.is_empty:
            container.enchant_offers = [None, None, None]
            costs = [0, 0, 0]
        else:
            container.enchant_offers = enchanting.enchanting_offers(container.enchant_seed, item.item_id, power)
            costs = enchanting.offer_costs(container.enchant_seed, item.item_id, power)
        props = {0: costs[0], 1: costs[1], 2: costs[2], 3: container.enchant_seed & 0xFFFF}
        for slot, offer in enumerate(container.enchant_offers):
            first = offer["enchants"][0] if offer and offer["enchants"] else None
            props[4 + slot] = enchanting.protocol_id(first[0]) if first else -1
            props[7 + slot] = first[1] if first else 0
        return props
    if container.type == ANVIL:
        result, cost = enchanting.anvil_merge(container.items[0], container.items[1])
        if result is not None and _limit_too_expensive and cost >= TOO_EXPENSIVE and not _is_creative(conn):
            result = None
        container.items[ANVIL_RESULT_SLOT] = result
        container.anvil_cost = cost if result is not None else 0
        return {0: container.anvil_cost}
    return {}


async def send_properties(conn, window_id: int, props: dict):
    from protocol.data_types import write_short, write_ubyte
    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, _PROPERTY_PACKET)
    if pid is None:
        return
    for prop, value in props.items():
        value = int(value)
        value = value - 0x10000 if value > 0x7FFF else value
        await conn.send_packet(pid, write_ubyte(window_id) + write_short(prop) + write_short(value))


async def open_window(conn, window_id: int, container, pos):
    """Refresh a freshly opened table/anvil and send its properties and contents."""
    from world.inventory_interactions import _sync_open_container
    await send_properties(conn, window_id, refresh(conn, container, pos))
    await _sync_open_container(conn, window_id)


async def after_click(conn, window_id: int):
    """Called after every click in one of these windows."""
    from world.inventory_interactions import _open_container
    from world.inventory_interactions import _sync_open_container
    opened = _open_container(conn, window_id)
    if opened is None or opened[0] != "block":
        return
    container = opened[1]
    pos = getattr(conn, "_open_container_pos", None)
    if container.type not in (ENCHANT_TABLE, ANVIL) or pos is None:
        return
    props = refresh(conn, container, pos)
    await send_properties(conn, window_id, props)
    await _sync_open_container(conn, window_id)


def anvil_take_allowed(conn, container) -> bool:
    if _is_creative(conn):
        return True
    return int(getattr(conn, "experience_level", 0)) >= int(getattr(container, "anvil_cost", 0))


def take_anvil_result(conn, container):
    """The result was taken: spend the inputs and the levels (called from the window write)."""
    cost = int(getattr(container, "anvil_cost", 0))
    for slot in (0, 1):
        stack = container.items[slot]
        if stack is not None:
            stack.count -= 1
            if stack.count <= 0:
                container.items[slot] = None
    container.items[ANVIL_RESULT_SLOT] = None
    container.anvil_cost = 0
    if not _is_creative(conn):
        _take_levels(conn, cost)


def _take_levels(conn, levels: int):
    """Remove levels from the player (the experience bar restarts at the new level)."""
    from handlers.play.join import _experience_needed_for_next_level
    level = max(0, int(conn.experience_level) - levels)
    conn.experience_total = sum(_experience_needed_for_next_level(lv) for lv in range(level))
    conn.experience_level = level
    conn.experience_progress = 0.0


async def handle_enchant_button(conn, payload: bytes, server):
    """Serverbound Enchant Item: the enchanting table's button (0-2)."""
    from protocol.data_types import read_ubyte, read_varint
    from world.inventory_interactions import _open_container, _sync_open_container
    window_id, offset = read_ubyte(payload, 0)
    button, _ = read_varint(payload, offset)
    if getattr(conn, "_open_window_id", None) != window_id:
        return
    opened = _open_container(conn, window_id)
    if opened is None or opened[0] != "block" or opened[1].type != ENCHANT_TABLE:
        return
    container = opened[1]
    pos = conn._open_container_pos
    refresh(conn, container, pos)
    if not 0 <= button < 3:
        return
    offer = container.enchant_offers[button] if container.enchant_offers else None
    item, lapis = container.items[0], container.items[1]
    if offer is None or item is None or item.is_empty:
        return
    if lapis is None or lapis.count < offer["lapis"]:
        return
    if not _is_creative(conn) and int(conn.experience_level) < offer["requirement"]:
        return

    new_id, new_nbt = enchanting.with_enchantments(item.item_id, item.nbt, offer["enchants"])
    container.items[0] = ItemStack(new_id, 1, item.damage, new_nbt)
    lapis.count -= offer["lapis"]
    container.items[1] = None if lapis.count <= 0 else lapis
    if not _is_creative(conn):
        _take_levels(conn, offer["levels"])
    container.enchant_seed = random.getrandbits(31)

    props = refresh(conn, container, pos)
    await send_properties(conn, window_id, props)
    await _sync_open_container(conn, window_id)
    from handlers.play.join import _send_set_experience
    await _send_set_experience(conn)


def return_inputs(conn, window_id: int) -> list:
    """Closing the table or anvil gives its inputs back to the player (vanilla does).

    Returns the stacks that did not fit; the caller drops them."""
    from world.inventory_interactions import _open_container
    opened = _open_container(conn, window_id)
    if opened is None or opened[0] != "block" or opened[1].type not in (ENCHANT_TABLE, ANVIL):
        return []
    container = opened[1]
    leftovers = []
    for slot in range(2):
        stack = container.items[slot]
        container.items[slot] = None
        if stack is None or stack.is_empty or conn.inventory_obj is None:
            continue
        left = conn.inventory_obj.add_item(stack)
        if left > 0:
            extra = stack.copy()
            extra.count = left
            leftovers.append(extra)
    if len(container.items) > ANVIL_RESULT_SLOT:
        container.items[ANVIL_RESULT_SLOT] = None
    return leftovers
