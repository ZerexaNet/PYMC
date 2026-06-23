# ============================================================
# PyMC - 方块交互处理
# 处理方块挖掘、放置和世界编辑同步
# 集成物品栏、合成系统、方块行为
# ============================================================

"""
方块交互数据包处理。

包括:
  - _handle_block_dig (0x26)
  - _handle_block_place (0x3A)
  - 方块变更广播 (_send_block_change, _broadcast_block_change)
  - 批量方块变更 (_send_multi_block_change, _broadcast_multi_block_changes)
  - 世界编辑同步 (_sync_world_edit, _refresh_chunks_for_players)
  - 方块行为交互 (BlockBehavior.on_use)
  - 物品栏感知的放置/破坏
"""

import logging

from protocol.data_types import (
    write_varint, write_position, write_long, write_varlong,
    read_varint, read_position, read_byte, read_float, read_boolean,
)
from network.connection import Connection
from world.blocks import (
    AIR, STONE, GRASS_BLOCK, DIRT, COBBLESTONE, OAK_PLANKS,
    GLASS, SAND, OAK_LOG, TORCH,
)
from world.editing import (
    get_world_block, set_world_block, fill_box_detailed,
    clone_box_detailed, resolve_block_state,
)

logger = logging.getLogger("PyMC.方块")

# --- 热键栏方块映射 (fallback for creative mode without inventory) ---
HOTBAR_PLACEABLES = [
    STONE, GRASS_BLOCK, DIRT, COBBLESTONE, OAK_PLANKS,
    GLASS, SAND, OAK_LOG, TORCH,
]

# --- 旧版方块掉落物映射 (kept for backward compat) ---
BLOCK_DROPS = {
    STONE: "minecraft:cobblestone",
    COBBLESTONE: "minecraft:cobblestone",
    GRASS_BLOCK: "minecraft:dirt",
    DIRT: "minecraft:dirt",
    3: "minecraft:dirt",     # COARSE_DIRT
    4: "minecraft:dirt",     # PODZOL
    SAND: "minecraft:sand",
    12: "minecraft:red_sand",  # RED_SAND
    13: "minecraft:gravel",    # GRAVEL
    GLASS: "minecraft:glass",
    OAK_LOG: "minecraft:oak_log",
    OAK_PLANKS: "minecraft:oak_planks",
}

# --- 面偏移量 ---
FACE_OFFSETS = {
    0: (0, -1, 0),
    1: (0, 1, 0),
    2: (0, 0, -1),
    3: (0, 0, 1),
    4: (-1, 0, 0),
    5: (1, 0, 0),
}


async def _send_block_change(conn: Connection, x: int, y: int, z: int, block_state: int):
    from protocol.packet_map import get_clientbound_packet
    payload = bytearray()
    payload.extend(write_position(x, y, z))
    payload.extend(write_varint(block_state))
    pid = get_clientbound_packet(conn.protocol_version, "block_update")
    if pid is not None:
        await conn.send_packet(pid, bytes(payload))


def _pack_section_position(section_x: int, section_y: int, section_z: int) -> int:
    packed = (
        ((section_x & 0x3FFFFF) << 42)
        | ((section_z & 0x3FFFFF) << 20)
        | (section_y & 0xFFFFF)
    )
    if packed >= (1 << 63):
        packed -= (1 << 64)
    return packed


async def _send_multi_block_change(
    conn: Connection,
    section_x: int,
    section_y: int,
    section_z: int,
    changes: list[tuple[int, int, int, int]],
):
    from protocol.packet_map import get_clientbound_packet
    payload = bytearray()
    payload.extend(write_long(_pack_section_position(section_x, section_y, section_z)))
    payload.extend(write_varint(len(changes)))
    for x, y, z, block_state in changes:
        local_pos = ((x & 15) << 8) | ((z & 15) << 4) | (y & 15)
        payload.extend(write_varlong((int(block_state) << 12) | local_pos))
    pid = get_clientbound_packet(conn.protocol_version, "multi_block_change")
    if pid is not None:
        await conn.send_packet(pid, bytes(payload))


async def _broadcast_block_change(server, x: int, y: int, z: int, block_state: int):
    for player in server.get_online_players():
        if abs(player.x - x) > server.view_distance * 16 or abs(player.z - z) > server.view_distance * 16:
            continue
        await _send_block_change(player, x, y, z, block_state)


async def _broadcast_block_changes(server, changes: list[tuple[int, int, int, int]]):
    for x, y, z, block_state in changes:
        await _broadcast_block_change(server, x, y, z, block_state)


async def _broadcast_multi_block_changes(server, changes: list[tuple[int, int, int, int]]):
    section_changes: dict[tuple[int, int, int], list[tuple[int, int, int, int]]] = {}
    for x, y, z, block_state in changes:
        key = (x >> 4, y >> 4, z >> 4)
        section_changes.setdefault(key, []).append((x, y, z, block_state))

    for player in server.get_online_players():
        for (section_x, section_y, section_z), section_records in section_changes.items():
            if (section_x, section_z) not in player.loaded_chunks:
                continue
            await _send_multi_block_change(
                player, section_x, section_y, section_z, section_records
            )


def _load_chunk_for_edit(server, chunk_x: int, chunk_z: int):
    from world.editing import _load_chunk_for_edit as _load_chunk_for_edit_impl
    return _load_chunk_for_edit_impl(server, chunk_x, chunk_z)


def _set_world_block(server, x: int, y: int, z: int, block_state: int) -> bool:
    return bool(set_world_block(server, x, y, z, block_state))


async def _refresh_chunks_for_players(server, chunk_coords: list[tuple[int, int]]):
    """将受影响区块重新编码并发给已加载这些区块的玩家。"""
    if not chunk_coords:
        return

    from handlers.play.chunks import _send_chunk_batch

    unique_coords = list(dict.fromkeys(chunk_coords))
    chunk_results, _, _ = server.generate_chunk_results(unique_coords)
    chunk_map = {(cx, cz): (cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks)
                 for cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks in chunk_results}

    for player in server.get_online_players():
        visible_results = [
            chunk_map[(cx, cz)]
            for cx, cz in unique_coords
            if (cx, cz) in player.loaded_chunks
        ]
        if visible_results:
            await _send_chunk_batch(player, visible_results)


async def _sync_world_edit(
    server,
    changed_chunks: set[tuple[int, int]],
    changed_blocks: list[tuple[int, int, int, int]],
):
    """小范围改单点，中范围走 Multi Block Change，大范围整区块重刷。"""
    if not changed_blocks:
        return
    if len(changed_blocks) <= 64:
        await _broadcast_block_changes(server, changed_blocks)
        return
    if len(changed_blocks) <= 512:
        await _broadcast_multi_block_changes(server, changed_blocks)
        return
    await _refresh_chunks_for_players(server, list(changed_chunks))


def _get_block_at(server, world_x: int, world_y: int, world_z: int) -> int | None:
    """读取世界坐标处的方块 ID。"""
    return get_world_block(server, int(world_x), int(world_y), int(world_z))


def _get_held_item_for_placement(conn: Connection) -> tuple[int, str | None]:
    """
    Get the block state ID the player is trying to place based on held item.
    Returns (block_state_id, item_name) or (0, None) if nothing to place.
    """
    from world.inventory import ItemStack
    from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE

    inv = getattr(conn, 'inventory_obj', None)
    if inv is not None:
        held = inv.get_held_item_from_slot(conn.selected_hotbar_slot)
        if held is not None and not held.is_empty():
            # Check if this item corresponds to a placeable block
            block_state = BLOCK_NAME_TO_DEFAULT_STATE.get(held.item_id)
            if block_state is not None:
                return (block_state, held.item_id)

    # Fallback to hotbar mapping for creative mode without inventory
    block_state = HOTBAR_PLACEABLES[conn.selected_hotbar_slot % len(HOTBAR_PLACEABLES)]
    # Map back to item name
    _STATE_TO_ITEM = {
        STONE: "minecraft:stone",
        GRASS_BLOCK: "minecraft:grass_block",
        DIRT: "minecraft:dirt",
        COBBLESTONE: "minecraft:cobblestone",
        OAK_PLANKS: "minecraft:oak_planks",
        GLASS: "minecraft:glass",
        SAND: "minecraft:sand",
        OAK_LOG: "minecraft:oak_log",
        TORCH: "minecraft:torch",
    }
    return (block_state, _STATE_TO_ITEM.get(block_state))


def _consume_placement_item(conn: Connection, item_name: str | None):
    """Consume one item from the held slot after placement (survival only)."""
    if item_name is None:
        return
    if conn.gamemode in ("creative", "spectator"):
        return  # Don't consume in creative

    inv = getattr(conn, 'inventory_obj', None)
    if inv is not None:
        held = inv.get_held_item_from_slot(conn.selected_hotbar_slot)
        if held is not None and not held.is_empty() and held.item_id == item_name:
            held.count -= 1
            if held.count <= 0:
                inv.set_slot(conn.selected_hotbar_slot, None)
            conn.inventory_state_id = getattr(conn, 'inventory_state_id', 0) + 1


async def _handle_block_dig(conn: Connection, payload: bytes, server):
    """处理挖方块。集成物品栏和方块行为系统。"""
    from handlers.play.entities import broadcast_entity_spawn
    from world.block_behavior import (
        get_block_drops, get_block_name_from_state, get_block_hardness,
        can_harvest_block, calculate_break_time, container_manager,
    )
    from world.inventory import ItemStack
    from world.chunk_io import STATE_ID_TO_BLOCK

    offset = 0
    status, offset = read_varint(payload, offset)
    (x, y, z), offset = read_position(payload, offset)
    _, offset = read_byte(payload, offset)  # face
    _, offset = read_varint(payload, offset)  # sequence

    # status 0 = started digging, 1 = cancelled, 2 = finished, 3 = drop item stack
    if status == 3:
        # Drop item stack from inventory
        _drop_held_item(conn, server)
        return

    if status == 1:
        # Cancelled digging - no action
        return

    if status != 2:
        return

    current = _get_block_at(server, x, y, z)
    if current is None or current == AIR:
        return

    # Check block hardness - unbreakable blocks can't be mined
    block_name, _ = STATE_ID_TO_BLOCK.get(current, ("minecraft:air", {}))
    hardness = get_block_hardness(block_name)
    if hardness < 0:
        # Unbreakable block (bedrock, etc.)
        return

    # Check if we should drop the container's contents
    container = container_manager.get_container(x, y, z)
    if container is not None:
        # Drop container contents before removing
        if conn.gamemode in ("survival", "adventure"):
            for item in container.items:
                if item is not None and not item.is_empty():
                    entity = server.entity_manager.create_item(
                        x + 0.5, y + 0.5, z + 0.5,
                        item_name=item.item_id, count=item.count
                    )
                    entity.vx = ((x * 734287 + z * 912931) % 100 - 50) / 2500.0
                    entity.vy = 0.12
                    entity.vz = ((z * 438289 + x * 193496) % 100 - 50) / 2500.0
                    await broadcast_entity_spawn(server, entity)
        container_manager.remove_container(x, y, z)

    # Remove the block from the world
    changed_chunks = set_world_block(server, x, y, z, AIR)
    if not changed_chunks:
        return
    await _broadcast_block_change(server, x, y, z, AIR)

    # Notify redstone engine of block change
    if server.redstone_engine:
        server.redstone_engine.on_block_change(x, y, z, current, AIR)

    # Notify fluid system
    if hasattr(server, 'fluid_system') and server.fluid_system:
        from world.fluids import _is_fluid
        if _is_fluid(current):
            server.fluid_system.on_fluid_remove(x, y, z)
        else:
            server.fluid_system.on_fluid_remove(x, y, z)

    # Generate drops
    if conn.gamemode in ("survival", "adventure"):
        # Get the held tool
        tool_item = None
        inv = getattr(conn, 'inventory_obj', None)
        if inv is not None:
            tool_item = inv.get_held_item_from_slot(conn.selected_hotbar_slot)

        # Use the new block drops system
        drops = get_block_drops(block_name, tool_item)

        if drops:
            for drop in drops:
                if drop.is_empty():
                    continue
                entity = server.entity_manager.create_item(
                    x + 0.5, y + 0.5, z + 0.5,
                    item_name=drop.item_id, count=drop.count
                )
                entity.vx = ((x * 734287 + z * 912931) % 100 - 50) / 2500.0
                entity.vy = 0.12
                entity.vz = ((z * 438289 + x * 193496) % 100 - 50) / 2500.0
                await broadcast_entity_spawn(server, entity)
        else:
            # Fallback to old drops table
            drop_name = BLOCK_DROPS.get(current)
            if drop_name:
                entity = server.entity_manager.create_item(
                    x + 0.5, y + 0.5, z + 0.5,
                    item_name=drop_name, count=1
                )
                entity.vx = ((x * 734287 + z * 912931) % 100 - 50) / 2500.0
                entity.vy = 0.12
                entity.vz = ((z * 438289 + x * 193496) % 100 - 50) / 2500.0
                await broadcast_entity_spawn(server, entity)

        # Damage tool on use
        if tool_item is not None and not tool_item.is_empty():
            tool_type = tool_item.get_tool_type()
            if tool_type is not None:
                tool_item.damage += 1
                max_damage = _get_tool_max_damage(tool_item.item_id)
                if max_damage > 0 and tool_item.damage >= max_damage:
                    inv.set_slot(conn.selected_hotbar_slot, None)
                    conn.inventory_state_id = getattr(conn, 'inventory_state_id', 0) + 1


def _drop_held_item(conn: Connection, server):
    """Drop the currently held item (Q key press)."""
    from world.inventory import ItemStack

    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    held = inv.get_held_item_from_slot(conn.selected_hotbar_slot)
    if held is None or held.is_empty():
        return

    if conn.gamemode in ("creative", "spectator"):
        return  # Don't drop in creative for now

    # Schedule the drop as an async task
    import asyncio
    from handlers.play.entities import broadcast_entity_spawn

    async def _do_drop():
        entity = server.entity_manager.create_item(
            conn.x, conn.y + 0.5, conn.z,
            item_name=held.item_id, count=held.count
        )
        # Throw the item slightly forward
        import math
        rad = math.radians(conn.yaw)
        entity.vx = -math.sin(rad) * 0.3
        entity.vy = 0.2
        entity.vz = math.cos(rad) * 0.3
        entity.pickup_delay = 20  # Can't pick up immediately
        await broadcast_entity_spawn(server, entity)

        # Remove from inventory
        inv.set_slot(conn.selected_hotbar_slot, None)
        conn.inventory_state_id = getattr(conn, 'inventory_state_id', 0) + 1

    asyncio.create_task(_do_drop())


def _get_tool_max_damage(item_id: str) -> int:
    """Get the max damage (durability) for a tool."""
    _DURABILITY = {
        "wooden_pickaxe": 59, "wooden_axe": 59, "wooden_shovel": 59,
        "wooden_sword": 59, "wooden_hoe": 59,
        "stone_pickaxe": 131, "stone_axe": 131, "stone_shovel": 131,
        "stone_sword": 131, "stone_hoe": 131,
        "iron_pickaxe": 250, "iron_axe": 250, "iron_shovel": 250,
        "iron_sword": 250, "iron_hoe": 250,
        "golden_pickaxe": 32, "golden_axe": 32, "golden_shovel": 32,
        "golden_sword": 32, "golden_hoe": 32,
        "diamond_pickaxe": 1561, "diamond_axe": 1561, "diamond_shovel": 1561,
        "diamond_sword": 1561, "diamond_hoe": 1561,
        "netherite_pickaxe": 2031, "netherite_axe": 2031, "netherite_shovel": 2031,
        "netherite_sword": 2031, "netherite_hoe": 2031,
        "leather_helmet": 55, "leather_chestplate": 80, "leather_leggings": 75, "leather_boots": 65,
        "iron_helmet": 165, "iron_chestplate": 240, "iron_leggings": 225, "iron_boots": 195,
        "golden_helmet": 77, "golden_chestplate": 112, "golden_leggings": 105, "golden_boots": 91,
        "diamond_helmet": 363, "diamond_chestplate": 528, "diamond_leggings": 495, "diamond_boots": 429,
        "netherite_helmet": 407, "netherite_chestplate": 592, "netherite_leggings": 555, "netherite_boots": 481,
        "bow": 384, "crossbow": 326, "trident": 250, "shield": 336,
        "shears": 238, "flint_and_steel": 64, "fishing_rod": 64,
    }
    return _DURABILITY.get(item_id, 0)


async def _handle_block_place(conn: Connection, payload: bytes, server):
    """处理方块放置和方块交互。集成物品栏和方块行为系统。"""
    from world.block_behavior import (
        get_block_behavior, get_block_name_from_state, container_manager,
    )
    from world.inventory import ItemStack
    from world.chunk_io import STATE_ID_TO_BLOCK

    offset = 0
    hand, offset = read_varint(payload, offset)
    (target_x, target_y, target_z), offset = read_position(payload, offset)
    face, offset = read_varint(payload, offset)
    _, offset = read_float(payload, offset)  # cursorX
    _, offset = read_float(payload, offset)  # cursorY
    _, offset = read_float(payload, offset)  # cursorZ
    _, offset = read_boolean(payload, offset)  # insideBlock
    _, offset = read_boolean(payload, offset)  # worldBorderHit
    _, offset = read_varint(payload, offset)  # sequence

    # Get the target block
    target_block = _get_block_at(server, target_x, target_y, target_z)
    if target_block is None:
        return

    target_name, _ = STATE_ID_TO_BLOCK.get(target_block, ("minecraft:air", {}))

    # 1. Check redstone component interaction (levers, buttons, etc.)
    if target_block and server.redstone_engine:
        from world.redstone import is_redstone_block, _get_block_name
        redstone_name = _get_block_name(target_block)
        if redstone_name and is_redstone_block(redstone_name):
            handled = server.redstone_engine.on_player_interact(
                target_x, target_y, target_z, conn
            )
            if handled:
                updates = server.redstone_engine.get_visual_updates()
                for ux, uy, uz, new_state in updates:
                    await _broadcast_block_change(server, ux, uy, uz, new_state)
                return

    # 2. Check block behavior (chest, crafting table, door, etc.)
    behavior = get_block_behavior(target_name)
    if behavior is not None and behavior.is_interactive():
        try:
            action_taken = await behavior.on_use(
                conn, server, target_x, target_y, target_z, face, hand
            )
            if action_taken:
                return  # Block handled the interaction, skip placement
        except Exception as e:
            logger.warning(f"Block behavior error for {target_name}: {e}")

    # 3. Attempt block placement
    dx, dy, dz = FACE_OFFSETS.get(face, (0, 1, 0))
    place_x = target_x + dx
    place_y = target_y + dy
    place_z = target_z + dz

    if place_y < -64 or place_y >= 320:
        return

    existing = _get_block_at(server, place_x, place_y, place_z)
    if existing is None or existing != AIR:
        return

    # Get the block to place from the player's held item
    block_state, item_name = _get_held_item_for_placement(conn)
    if block_state == 0:
        return  # Nothing to place

    # Call block behavior on_place if available
    placed_name, _ = STATE_ID_TO_BLOCK.get(block_state, ("minecraft:air", {}))
    place_behavior = get_block_behavior(placed_name)
    if place_behavior is not None:
        try:
            success = await place_behavior.on_place(
                conn, server, place_x, place_y, place_z, face
            )
            if not success:
                return  # Placement denied by behavior
        except Exception as e:
            logger.warning(f"Block place behavior error for {placed_name}: {e}")

    # Place the block
    changed_chunks = set_world_block(server, place_x, place_y, place_z, block_state)
    if not changed_chunks:
        return
    await _broadcast_block_change(server, place_x, place_y, place_z, block_state)

    # Notify redstone engine of block change
    if server.redstone_engine:
        server.redstone_engine.on_block_change(place_x, place_y, place_z, AIR, block_state)

    # Notify fluid system
    if hasattr(server, 'fluid_system') and server.fluid_system:
        from world.fluids import _is_water, _is_lava
        if _is_water(block_state):
            server.fluid_system.on_fluid_place(place_x, place_y, place_z, "water")
        elif _is_lava(block_state):
            server.fluid_system.on_fluid_place(place_x, place_y, place_z, "lava")

    # Create container for container blocks
    if placed_name in ("minecraft:chest", "minecraft:trapped_chest"):
        container_manager.get_or_create(place_x, place_y, place_z, "chest")
    elif placed_name == "minecraft:furnace":
        container_manager.get_or_create(place_x, place_y, place_z, "furnace")
    elif placed_name == "minecraft:blast_furnace":
        container_manager.get_or_create(place_x, place_y, place_z, "blast_furnace")
    elif placed_name == "minecraft:smoker":
        container_manager.get_or_create(place_x, place_y, place_z, "smoker")
    elif placed_name == "minecraft:hopper":
        container_manager.get_or_create(place_x, place_y, place_z, "hopper")
    elif placed_name in ("minecraft:dropper", "minecraft:dispenser"):
        container_manager.get_or_create(place_x, place_y, place_z, placed_name.split(":")[1])

    # Consume the item from inventory
    _consume_placement_item(conn, item_name)

    # Send inventory update if we consumed an item
    if conn.gamemode not in ("creative", "spectator"):
        inv = getattr(conn, 'inventory_obj', None)
        if inv is not None:
            from world.inventory import send_slot_update
            await send_slot_update(conn, conn.selected_hotbar_slot)
