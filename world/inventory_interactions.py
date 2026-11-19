# ============================================================
# PyMC - Server-side inventory interaction engine
# ============================================================
"""Server-authoritative inventory click handling.

This module implements vanilla-style click modes for the player inventory
and for block containers opened by ``world.block_behavior``:

  0: left/right click
  1: shift-click transfer
  2: number-key swap
  3: creative pick block
  4: drop item
  5: drag painting (left/right/middle)
"""

from __future__ import annotations

import math
import logging

from .inventory import PlayerInventory, decode_slot_entry, send_inventory_sync

logger = logging.getLogger("PyMC.物品栏交互")


# --------------------------------------------------
# Window slot mapping
# --------------------------------------------------

def _open_container(conn, window_id: int):
    """Return (kind, data) for the window currently open on a connection."""
    if getattr(conn, '_open_window_id', None) != window_id:
        return None
    kind = getattr(conn, '_open_container_type', 'block')
    if kind == 'ender_chest':
        return ('ender_chest', getattr(conn, 'inventory_obj', None))
    if kind == 'crafting':
        return ('crafting', conn)

    if kind == 'entity':
        container = getattr(conn, '_open_entity_container', None)
        return None if container is None else ('block', container)

    from .block_behavior import container_view
    pos = getattr(conn, '_open_container_pos', None)
    if pos is None:
        return None
    container = container_view(*pos)
    if container is None:
        return None
    return ('block', container)


def _container_slots(conn, window_id: int):
    opened = _open_container(conn, window_id)
    if opened is None:
        return None
    kind, data = opened
    if kind == 'ender_chest':
        return data.ender_chest
    if kind == 'crafting':
        from .crafting_window import window_items
        return window_items(conn, window_id)
    return data.items


def window_slot_location(conn, window_id: int, slot_idx: int, player_slot_mapper):
    """Map a protocol window slot to ``(kind, index)``."""
    if window_id == 0:
        if slot_idx == 0:
            return ('craft_result', 0)
        inventory_slot = player_slot_mapper(slot_idx)
        if inventory_slot is None:
            return None
        return ('player', inventory_slot)

    opened = _open_container(conn, window_id)
    if opened is None or slot_idx < 0:
        return None
    if opened[0] == 'crafting':
        if slot_idx == 0:
            return ('craft_result', 0)
        if slot_idx <= 9:
            return ('craft', slot_idx - 1)
        if slot_idx <= 36:
            return ('player', slot_idx - 1)       # 10-36 -> main 9-35
        if slot_idx <= 45:
            return ('player', slot_idx - 37)      # 37-45 -> hotbar 0-8
        return None
    container_size = len(opened[1].items if opened[0] == 'block' else opened[1].ender_chest)
    if opened[0] == 'block' and getattr(opened[1], 'type', '') == 'anvil' and slot_idx == 2:
        return ('anvil_result', 0)              # take only; see world/enchanting_window.py
    if slot_idx < container_size:
        return (opened[0], slot_idx)
    if slot_idx < container_size + 27:
        return ('player', 9 + (slot_idx - container_size))
    if slot_idx < container_size + 36:
        return ('player', slot_idx - container_size - 27)
    return None


def _read_window_slot(conn, location):
    kind, idx = location
    inv = conn.inventory_obj
    if kind == 'player':
        return inv.get_slot(idx)
    if kind in ('craft', 'craft_result'):
        if kind == 'craft_result':
            return None  # never moved like a normal slot; see _click_result
        from .crafting_window import grid_slots
        store, _, _ = grid_slots(conn, getattr(conn, '_open_window_id', None))
        return store[idx]
    if kind == 'ender_chest':
        return inv.ender_chest[idx]
    if kind == 'anvil_result':
        opened = _open_container(conn, getattr(conn, '_open_window_id', -1))
        return opened[1].items[2] if opened is not None and opened[0] == 'block' else None
    opened = _open_container(conn, getattr(conn, '_open_window_id', -1))
    if opened is not None and opened[0] == 'block':
        return opened[1].items[idx]
    return None


def _write_window_slot(conn, location, item):
    kind, idx = location
    if item is not None and item.is_empty:
        item = None
    if kind == 'player':
        conn.inventory_obj.set_slot(idx, item)
        return
    if kind == 'craft_result':
        return
    if kind == 'anvil_result':
        # the result is only ever taken: placing items on it is refused
        if item is None:
            opened = _open_container(conn, getattr(conn, '_open_window_id', -1))
            if opened is not None and opened[0] == 'block' and opened[1].items[2] is not None:
                from world.enchanting_window import take_anvil_result
                take_anvil_result(conn, opened[1])
        return
    if kind == 'craft':
        from .crafting_window import grid_slots
        store, _, _ = grid_slots(conn, getattr(conn, '_open_window_id', None))
        store[idx] = item
        return
    if kind == 'ender_chest':
        conn.inventory_obj.ender_chest[idx] = item
        return
    opened = _open_container(conn, getattr(conn, '_open_window_id', -1))
    if opened is not None and opened[0] == 'block':
        opened[1].items[idx] = item


# --------------------------------------------------
# Basic clicks
# --------------------------------------------------

def _click_basic(conn, location, button: int):
    """Mode 0 left/right click."""
    slot_item = _read_window_slot(conn, location)
    cursor = conn.inventory_obj.carried_item

    if button == 0:  # left click
        if cursor is None or cursor.is_empty:
            conn.inventory_obj.carried_item = slot_item
            _write_window_slot(conn, location, None)
        elif slot_item is None or slot_item.is_empty:
            _write_window_slot(conn, location, cursor)
            conn.inventory_obj.carried_item = None
        elif slot_item.can_stack_with(cursor) and slot_item.count < slot_item.max_stack_size:
            moved = min(cursor.count, slot_item.max_stack_size - slot_item.count)
            slot_item.count += moved
            cursor.count -= moved
            if cursor.count <= 0:
                conn.inventory_obj.carried_item = None
            conn.inventory_obj.state_id += 1
        else:
            _write_window_slot(conn, location, cursor)
            conn.inventory_obj.carried_item = slot_item
        return

    # right click
    if cursor is None or cursor.is_empty:
        if slot_item is not None and not slot_item.is_empty:
            take = (slot_item.count + 1) // 2
            picked = slot_item.copy()
            picked.count = take
            conn.inventory_obj.carried_item = picked
            slot_item.count -= take
            if slot_item.count <= 0:
                _write_window_slot(conn, location, None)
            else:
                conn.inventory_obj.state_id += 1
        return

    if slot_item is None or slot_item.is_empty:
        placed = cursor.copy()
        placed.count = 1
        _write_window_slot(conn, location, placed)
        cursor.count -= 1
        if cursor.count <= 0:
            conn.inventory_obj.carried_item = None
        return

    if slot_item.can_stack_with(cursor) and slot_item.count < slot_item.max_stack_size:
        slot_item.count += 1
        cursor.count -= 1
        if cursor.count <= 0:
            conn.inventory_obj.carried_item = None
        conn.inventory_obj.state_id += 1


def _insert_stack_into_slots(stack, slots: list, order: list[int]) -> int:
    """Insert a stack into selected slots. Returns the leftover count."""
    remaining = stack.count

    for idx in order:
        existing = slots[idx]
        if existing is None or existing.is_empty:
            continue
        if not stack.can_stack_with(existing):
            continue
        space = existing.max_stack_size - existing.count
        moved = min(space, remaining)
        existing.count += moved
        remaining -= moved
        if remaining <= 0:
            stack.count = 0
            return 0

    for idx in order:
        if slots[idx] is None or (slots[idx] is not None and slots[idx].is_empty):
            placed = stack.copy()
            placed.count = min(placed.max_stack_size, remaining)
            slots[idx] = placed
            remaining -= placed.count
            if remaining <= 0:
                stack.count = 0
                return 0

    stack.count = remaining
    return remaining


def _armor_slot_for_item(item_id: str):
    name = item_id.replace('minecraft:', '')
    if name.endswith('_helmet') or name == 'turtle_helmet':
        return 39
    if name.endswith('_chestplate'):
        return 38
    if name.endswith('_leggings'):
        return 37
    if name.endswith('_boots'):
        return 36
    return None


def _shift_player_stack(inv, idx: int):
    item = inv.get_slot(idx)
    if item is None or item.is_empty or not (0 <= idx < PlayerInventory.TOTAL_SLOTS):
        return

    inv.set_slot(idx, None)

    armor_idx = _armor_slot_for_item(item.item_id)
    if armor_idx is not None and idx not in (36, 37, 38, 39):
        target = inv.get_slot(armor_idx)
        if target is None or target.is_empty:
            inv.set_slot(armor_idx, item)
            return
        if item.can_stack_with(target) and target.count < target.max_stack_size:
            moved = min(item.count, target.max_stack_size - target.count)
            target.count += moved
            item.count -= moved
            if item.count <= 0:
                inv.state_id += 1
                return

    if 0 <= idx <= 8:
        order = list(range(9, 36))
    elif 9 <= idx <= 35:
        order = list(range(0, 9)) + list(range(9, 36))
    elif idx == 40:
        order = list(range(9, 36)) + list(range(0, 9))
    else:
        order = list(range(9, 36)) + list(range(0, 9)) + [40]

    leftover = _insert_stack_into_slots(item, inv.slots, order)
    if leftover > 0:
        inv.set_slot(idx, item)
    else:
        inv.state_id += 1


def _click_shift(conn, window_id: int, location):
    kind, idx = location
    inv = conn.inventory_obj
    item = _read_window_slot(conn, location)
    if item is None or item.is_empty:
        return

    if window_id == 0:
        _shift_player_stack(inv, idx)
        return

    opened = _open_container(conn, window_id)
    if opened is not None and opened[0] == 'crafting':
        # vanilla CraftingMenu: grid -> inventory; inventory <-> hotbar
        if kind == 'craft':
            order = list(range(9, 36)) + list(range(0, 9))
        elif 9 <= idx <= 35:
            order = list(range(0, 9))
        else:
            order = list(range(9, 36))
        _write_window_slot(conn, location, None)
        leftover = _insert_stack_into_slots(item, inv.slots, order)
        if leftover > 0:
            _write_window_slot(conn, location, item)
        else:
            inv.state_id += 1
        return

    if kind == 'player':
        opened = _open_container(conn, window_id)
        if opened is None:
            return
        dest = opened[1].ender_chest if opened[0] == 'ender_chest' else opened[1].items
        _write_window_slot(conn, location, None)
        leftover = _insert_stack_into_slots(item, dest, list(range(len(dest))))
        if leftover > 0:
            _write_window_slot(conn, location, item)
        else:
            inv.state_id += 1
        return

    # Container/ender slot -> player inventory.
    _write_window_slot(conn, location, None)
    order = list(range(9, 36)) + list(range(0, 9)) + [40]
    leftover = _insert_stack_into_slots(item, inv.slots, order)
    if leftover > 0:
        _write_window_slot(conn, location, item)
    else:
        inv.state_id += 1


def _click_number_key(conn, location, hotbar_slot: int):
    clicked = _read_window_slot(conn, location)
    hotbar_item = conn.inventory_obj.get_slot(hotbar_slot)
    _write_window_slot(conn, location, hotbar_item)
    conn.inventory_obj.set_slot(hotbar_slot, clicked)


def _click_pick_block(conn, location):
    if getattr(conn, 'gamemode', 'survival') != 'creative':
        return
    item = _read_window_slot(conn, location)
    if item is None or item.is_empty:
        return
    if conn.inventory_obj.carried_item is None:
        picked = item.copy()
        picked.count = max(1, item.max_stack_size)
        conn.inventory_obj.carried_item = picked


# --------------------------------------------------
# Drop and drag
# --------------------------------------------------

async def _drop_stack(conn, server, stack, count: int) -> int:
    """Drop up to *count* items. Returns the number actually dropped."""
    if stack is None or stack.is_empty or count <= 0:
        return 0
    if server is None or not hasattr(server, 'entity_manager'):
        return 0

    count = min(count, stack.count)
    stack.count -= count

    try:
        entity = server.entity_manager.create_item(
            getattr(conn, 'x', 0.0) + 0.5,
            getattr(conn, 'y', 0.0) + 1.2,
            getattr(conn, 'z', 0.0) + 0.5,
            item_name=stack.item_id,
            count=count,
        )
        yaw = math.radians(getattr(conn, 'yaw', 0.0))
        entity.vx = -math.sin(yaw) * 0.25
        entity.vy = 0.12
        entity.vz = math.cos(yaw) * 0.25
        entity.pickup_delay = 20

        from handlers.play.entities import broadcast_entity_spawn
        await broadcast_entity_spawn(server, entity)
        return count
    except Exception as e:
        logger.debug(f"Failed to spawn dropped inventory item: {e}")
        return 0


def _drag_start(conn, slot_idx: int, changed_slots: list[int]):
    inv = conn.inventory_obj
    inv._drag_slots = set(changed_slots)
    if slot_idx != -999:
        inv._drag_slots.add(slot_idx)


def _drag_add(conn, slot_idx: int, changed_slots: list[int]):
    inv = conn.inventory_obj
    if not hasattr(inv, '_drag_slots'):
        inv._drag_slots = set()
    inv._drag_slots.update(changed_slots)
    if slot_idx != -999:
        inv._drag_slots.add(slot_idx)


def _drag_end(conn, window_id: int, drag_button: int, player_slot_mapper,
             changed_slots=None):
    inv = conn.inventory_obj
    drag_slots = set(getattr(inv, '_drag_slots', set()))
    inv._drag_slots = set()
    # Some clients include the final affected-slot list on the end packet;
    # accept it as a fallback when start/add bookkeeping was incomplete.
    if changed_slots:
        drag_slots.update(changed_slots)
    cursor = inv.carried_item
    if cursor is None or cursor.is_empty or not drag_slots:
        return False

    valid = []
    for raw_slot in sorted(drag_slots):
        location = window_slot_location(conn, window_id, raw_slot, player_slot_mapper)
        if location is not None and location[0] != 'craft_result':
            valid.append(location)
    if not valid:
        return False

    total = cursor.count
    if drag_button == 0:  # left drag: distribute evenly
        per_slot = max(1, total // len(valid))
        remainder = total - per_slot * len(valid)
    else:  # right/middle drag: one item per slot
        per_slot = 1
        remainder = 0

    used = 0
    for i, location in enumerate(valid):
        amount = min(per_slot + (1 if i < remainder else 0), total - used)
        if amount <= 0:
            break
        slot_item = _read_window_slot(conn, location)
        if slot_item is None or slot_item.is_empty:
            placed = cursor.copy()
            placed.count = amount
            _write_window_slot(conn, location, placed)
            used += amount
        elif slot_item.can_stack_with(cursor) and slot_item.count < slot_item.max_stack_size:
            moved = min(amount, slot_item.max_stack_size - slot_item.count)
            slot_item.count += moved
            used += moved

    cursor.count -= used
    if cursor.count <= 0:
        inv.carried_item = None
    if used:
        inv.state_id += 1
    return used > 0


# --------------------------------------------------
# Crafting result slot
# --------------------------------------------------

def _give_back_into(inv, leftovers: list):
    def give(stack):
        left = inv.add_item(stack)
        if left > 0:
            extra = stack.copy()
            extra.count = left
            leftovers.append(extra)
    return give


def _click_result(conn, window_id: int, mode: int, button: int, leftovers: list) -> bool:
    """
    Click on a crafting result slot (vanilla ResultSlot semantics):
      mode 0  take one craft onto the cursor (if it fits there)
      mode 1  shift: craft as many times as fit into the inventory
      mode 2  number key: craft once into an empty hotbar slot
      mode 4  Q / ctrl+Q: craft once (or as often as possible) and drop it
    """
    from .crafting_window import current_result, take_result
    inv = conn.inventory_obj
    give = _give_back_into(inv, leftovers)
    result = current_result(conn, window_id)
    if result is None:
        return False

    if mode == 0:
        cursor = inv.carried_item
        if cursor is None or cursor.is_empty:
            inv.carried_item = take_result(conn, window_id, give)
        elif cursor.can_stack_with(result) and cursor.count + result.count <= cursor.max_stack_size:
            crafted = take_result(conn, window_id, give)
            cursor.count += crafted.count
        else:
            return False
        inv.state_id += 1
        return True

    if mode == 1:
        if window_id == 0:
            order = list(range(9, 36)) + list(range(0, 9))
        else:
            order = list(range(8, -1, -1)) + list(range(35, 8, -1))
        crafted_any = False
        first = result.item_id
        for _ in range(64 * 9):
            nxt = current_result(conn, window_id)
            if nxt is None or nxt.item_id != first:
                break
            # only craft when the whole result fits
            trial = [slot.copy() if slot is not None else None for slot in inv.slots]
            probe = nxt.copy()
            if _insert_stack_into_slots(probe, trial, order) > 0:
                break
            crafted = take_result(conn, window_id, give)
            _insert_stack_into_slots(crafted, inv.slots, order)
            crafted_any = True
        if crafted_any:
            inv.state_id += 1
        return crafted_any

    if mode == 2:
        if not (0 <= button < 9):
            return False
        target = inv.get_slot(button)
        if target is not None and not target.is_empty:
            return False
        inv.set_slot(button, take_result(conn, window_id, give))
        return True

    if mode == 4:
        times = 1 if button == 0 else 64
        for _ in range(times):
            nxt = current_result(conn, window_id)
            if nxt is None or nxt.item_id != result.item_id:
                break
            leftovers.append(take_result(conn, window_id, give))
        return True
    return False


# --------------------------------------------------
# Sync and main entry point
# --------------------------------------------------

def _window_contents(conn, window_id: int):
    """Every slot of a window in protocol order, as the server sees it."""
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return None
    if window_id == 0:
        from .inventory import player_window_slots
        return player_window_slots(inv)
    slots = _container_slots(conn, window_id)
    if slots is None:
        return None
    all_slots = list(slots)
    all_slots.extend(inv.get_slot(i) for i in range(9, 36))
    all_slots.extend(inv.get_slot(i) for i in range(0, 9))
    return all_slots


async def _sync_open_container(conn, window_id: int):
    from .inventory import send_container_content
    all_slots = _window_contents(conn, window_id)
    if all_slots is not None:
        await send_container_content(conn, window_id, all_slots)


async def handle_container_click(conn, payload: bytes, server, player_slot_mapper):
    """Apply one Click Container packet using server-authoritative state."""
    from protocol.data_types import read_varint, read_short, read_byte

    offset = 0
    window_id, offset = read_varint(payload, offset)
    state_id, offset = read_varint(payload, offset)
    slot_idx, offset = read_short(payload, offset)
    button, offset = read_byte(payload, offset)
    mode, offset = read_varint(payload, offset)

    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    if window_id != 0 and _open_container(conn, window_id) is None:
        return

    # 与原版一致: 状态序号不一致时仍然处理点击, 之后发送完整状态纠正客户端
    # (本函数结尾总是发送完整同步)。

    changed_count, offset = read_varint(payload, offset)
    if changed_count < 0 or changed_count > 128:
        if window_id == 0:
            await send_inventory_sync(conn)
        else:
            await _sync_open_container(conn, window_id)
        return

    changed_slots: list[int] = []
    predicted: list = []          # what the client says each changed slot now holds
    for _ in range(changed_count):
        changed_slot, offset = read_short(payload, offset)
        predicted_item, offset = decode_slot_entry(payload, offset)
        changed_slots.append(changed_slot)
        predicted.append((changed_slot, predicted_item))
    predicted_carried, offset = decode_slot_entry(payload, offset)

    # Vanilla only answers with the slots the client got wrong, as long as it
    # clicked on the state we last sent; full resync otherwise. Answering every
    # click with the whole window makes fast, pipelined clicks see stale data.
    remote = getattr(conn, '_remote_window', None)
    use_diff = (remote is not None and remote.get("window") == window_id
                and state_id == getattr(conn, 'inventory_state_id', 0))

    mutated = True
    crafting = False
    leftovers: list = []
    special = None
    opened_now = _open_container(conn, window_id) if window_id != 0 else None
    if opened_now is not None and opened_now[0] == 'block' and getattr(opened_now[1], 'type', '') == 'anvil':
        special = 'anvil'
        if slot_idx == 2 and mode == 2:
            # a hotbar key swap would put items on the result: refused
            await _sync_open_container(conn, window_id)
            return
        if slot_idx == 2 and mode in (0, 1, 4):
            from world.enchanting_window import anvil_take_allowed
            if inv.carried_item is not None or not anvil_take_allowed(conn, opened_now[1]):
                # no taking the result into a held item, or without the levels for it
                await _sync_open_container(conn, window_id)
                return
    elif opened_now is not None and opened_now[0] == 'block' and getattr(opened_now[1], 'type', '') == 'enchanting_table':
        special = 'enchanting'

    from .crafting_window import is_crafting_window, refresh_result
    grid_before = None
    if is_crafting_window(conn, window_id):
        crafting = True
        from .crafting_window import _grid_items
        from .inventory import slot_snapshot
        grid_before = [slot_snapshot(item) for item in _grid_items(conn, window_id)]
        if slot_idx == 0 and mode in (0, 1, 2, 4):
            mutated = _click_result(conn, window_id, mode, button, leftovers)
            mode = -1  # handled

    if mode == 0:
        if slot_idx == -999:
            if button == 0 and inv.carried_item is not None:
                dropped = await _drop_stack(conn, server, inv.carried_item,
                                            inv.carried_item.count)
                if dropped:
                    inv.carried_item = None
                    inv.state_id += 1
                else:
                    mutated = False
            else:
                mutated = False
        else:
            location = window_slot_location(conn, window_id, slot_idx, player_slot_mapper)
            if location is not None and button in (0, 1):
                _click_basic(conn, location, button)
            else:
                mutated = False

    elif mode == 1:
        if slot_idx != -999:
            location = window_slot_location(conn, window_id, slot_idx, player_slot_mapper)
            if location is not None:
                _click_shift(conn, window_id, location)

    elif mode == 2:
        if slot_idx != -999 and 0 <= button < 9:
            location = window_slot_location(conn, window_id, slot_idx, player_slot_mapper)
            if location is not None and not (location[0] == 'player' and location[1] == button):
                _click_number_key(conn, location, button)

    elif mode == 3:
        if slot_idx != -999:
            location = window_slot_location(conn, window_id, slot_idx, player_slot_mapper)
            if location is not None:
                _click_pick_block(conn, location)

    elif mode == 4:
        if slot_idx == -999:
            if inv.carried_item is not None:
                count = 1 if button == 0 else inv.carried_item.count
                await _drop_stack(conn, server, inv.carried_item, count)
                if inv.carried_item.count <= 0:
                    inv.carried_item = None
        else:
            location = window_slot_location(conn, window_id, slot_idx, player_slot_mapper)
            if location is not None:
                item = _read_window_slot(conn, location)
                if item is not None and not item.is_empty:
                    count = 1 if button == 0 else item.count
                    await _drop_stack(conn, server, item, count)
                    if item.count <= 0:
                        _write_window_slot(conn, location, None)

    elif mode == 5:
        # Drag operations: start (0/4/8), add (1/5/9), end (2/6/10).
        # Start/add only update bookkeeping and do not change the window state.
        if button in (0, 4, 8):
            _drag_start(conn, slot_idx, changed_slots)
            mutated = False
        elif button in (1, 5, 9):
            _drag_add(conn, slot_idx, changed_slots)
            mutated = False
        elif button in (2, 6, 10):
            mutated = _drag_end(conn, window_id, button - 2,
                                player_slot_mapper, changed_slots)

    for stack in leftovers:
        if stack is not None and not stack.is_empty:
            await _drop_stack(conn, server, stack, stack.count)

    if crafting:
        refresh_result(conn, window_id)
    if special is not None and window_id != 0:
        from world.enchanting_window import refresh, send_properties
        opened_after = _open_container(conn, window_id)
        if opened_after is not None and opened_after[0] == 'block':
            props = refresh(conn, opened_after[1], conn._open_container_pos)
            await send_properties(conn, window_id, props)

    contents = _window_contents(conn, window_id)
    if contents is None:
        return
    if use_diff and len(remote["slots"]) == len(contents):
        from .inventory import send_window_slot, slot_snapshot
        for changed_slot, item in predicted:
            if 0 <= changed_slot < len(remote["slots"]):
                remote["slots"][changed_slot] = slot_snapshot(item)
        remote["carried"] = slot_snapshot(predicted_carried)
        send = [i for i, item in enumerate(contents) if slot_snapshot(item) != remote["slots"][i]]
        if crafting and 0 not in send:
            # CraftingMenu.slotChangedCraftingGrid: any change to (or click in)
            # the crafting area re-sends the result slot, changed or not.
            from .crafting_window import _grid_items
            grid_after = [slot_snapshot(item) for item in _grid_items(conn, window_id)]
            if grid_after != grid_before or 0 <= slot_idx <= len(grid_after):
                send.insert(0, 0)
        cursor_wrong = slot_snapshot(inv.carried_item) != remote["carried"]
        if send or cursor_wrong:
            # one state id for the whole answer, so a client that already
            # clicked again on the first packet of it is still in sync
            conn.inventory_state_id += 1
            for i in send:
                await send_window_slot(conn, window_id, i, contents[i])
                remote["slots"][i] = slot_snapshot(contents[i])
            if cursor_wrong:
                await send_window_slot(conn, -1, -1, inv.carried_item)
                remote["carried"] = slot_snapshot(inv.carried_item)
        return

    conn.inventory_state_id += 1
    if window_id == 0:
        await send_inventory_sync(conn)
    else:
        await _sync_open_container(conn, window_id)
