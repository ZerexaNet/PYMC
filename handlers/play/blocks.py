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
        if held is not None and not held.is_empty:
            # Check if this item corresponds to a placeable block
            from world.placement import block_for_item
            block_name = block_for_item(held.item_id)
            if block_name is not None:
                return (BLOCK_NAME_TO_DEFAULT_STATE[block_name], held.item_id)

    return (0, None)


def _consume_placement_item(conn: Connection, item_name: str | None):
    """Consume one item from the held slot after placement (survival only)."""
    if item_name is None:
        return
    if conn.gamemode in ("creative", "spectator"):
        return  # Don't consume in creative

    inv = getattr(conn, 'inventory_obj', None)
    if inv is not None:
        held = inv.get_held_item_from_slot(conn.selected_hotbar_slot)
        if held is not None and not held.is_empty and held.item_id == item_name:
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
    sequence, offset = read_varint(payload, offset)

    # status: 0 = started digging, 1 = cancelled, 2 = finished,
    #         3 = drop item stack, 4 = drop item, 5 = release use item, 6 = swap hands
    if status in (3, 4):
        _drop_held_item(conn, server, whole_stack=(status == 3))
        return
    if status == 6:
        await _swap_hands(conn, server)
        return
    if status not in (0, 2):
        if status == 1:
            await _acknowledge_block_change(conn, sequence)
        return

    current = _get_block_at(server, x, y, z)
    block_name, _ = STATE_ID_TO_BLOCK.get(current or 0, ("minecraft:air", {}))
    hardness = get_block_hardness(block_name)

    # 创造模式和瞬间破坏的方块 (硬度 0: 花草、火把等) 只会收到 "开始挖掘";
    # 其余方块在 "完成挖掘" 时破坏。
    instant = conn.gamemode == "creative" or hardness == 0
    should_break = (status == 2) or (status == 0 and instant)

    if (not should_break or current is None or current == AIR
            or conn.gamemode in ("adventure", "spectator")
            or not _within_reach(conn, x, y, z)
            or _is_spawn_protected(conn, server, x, z)
            or (hardness < 0 and conn.gamemode != "creative")):
        if status == 2 and current is not None:
            # 拒绝破坏: 把真实方块发回去纠正客户端的预测
            await _send_block_change(conn, x, y, z, current)
        await _acknowledge_block_change(conn, sequence)
        return

    # Plugin hook: allow plugins to cancel block break
    from mods.bridge import hook_block_break
    if not hook_block_break(server, conn, x, y, z, current):
        await _send_block_change(conn, x, y, z, current)
        await _acknowledge_block_change(conn, sequence)
        return  # Cancelled by a plugin

    # Check if we should drop the container's contents
    container = container_manager.get_container(x, y, z)
    if container is not None:
        # Drop container contents before removing
        if conn.gamemode in ("survival", "adventure"):
            for item in container.items:
                if item is not None and not item.is_empty:
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
        await _acknowledge_block_change(conn, sequence)
        return
    await _broadcast_block_change(server, x, y, z, AIR)
    await _acknowledge_block_change(conn, sequence)
    await _broadcast_block_break_effect(server, conn, x, y, z, current)

    # 生存/冒险模式下消耗工具耐久
    if conn.gamemode in ("survival", "adventure"):
        from world.item_properties import damage_held_item
        await damage_held_item(conn, server)

    # (the redstone engine is notified by world.editing)
    if server.redstone_engine:
        for ux, uy, uz, new_state in server.redstone_engine.get_visual_updates():
            await _broadcast_block_change(server, ux, uy, uz, new_state)

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

        # Vanilla block loot table (uses the broken block's state, e.g. crop age)
        from world.chunk_io import STATE_ID_TO_BLOCK
        state_props = STATE_ID_TO_BLOCK.get(current, (block_name, {}))[1]
        drops = get_block_drops(block_name, tool_item, state_props)

        if drops:
            for drop in drops:
                if drop.is_empty:
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


REACH_DISTANCE_SQ = 7.0 * 7.0   # 原版服务端允许的交互距离 (略大于客户端的 4.5/5)


def _within_reach(conn: Connection, x: int, y: int, z: int) -> bool:
    dx = conn.x - (x + 0.5)
    dy = (conn.y + 1.5) - (y + 0.5)
    dz = conn.z - (z + 0.5)
    return dx * dx + dy * dy + dz * dz <= REACH_DISTANCE_SQ


def _is_spawn_protected(conn: Connection, server, x: int, z: int) -> bool:
    """spawn-protection: 出生点周围只有 OP 能改动方块 (没有任何 OP 时不生效)。"""
    radius = int(getattr(server, "config", {}).get("spawn-protection", 0) or 0)
    permissions = getattr(server, "permissions", None)
    if radius <= 0 or permissions is None or not permissions.data.get("ops"):
        return False
    if permissions.is_op(conn.username):
        return False
    spawn_x, _, spawn_z = server.spawn_position
    return max(abs(x - spawn_x), abs(z - spawn_z)) <= radius


async def _acknowledge_block_change(conn: Connection, sequence: int):
    """
    Acknowledge Block Change: 客户端在收到与其操作序号对应的确认之前,
    会一直保留自己预测的方块状态 (1.19+)。
    """
    from protocol.packet_map import get_clientbound_packet
    if conn.protocol_version < 759:
        return
    pid = get_clientbound_packet(conn.protocol_version, "acknowledge_player_digging")
    if pid is not None:
        await conn.send_packet(pid, write_varint(sequence))


async def _broadcast_block_break_effect(server, breaker: Connection,
                                        x: int, y: int, z: int, block_state: int):
    """World Event 2001: 其他玩家看到/听到方块破坏的粒子和音效。"""
    from protocol.packet_map import get_clientbound_packet
    from protocol.data_types import write_int, write_boolean
    payload = (write_int(2001) + write_position(x, y, z)
               + write_int(int(block_state)) + write_boolean(False))
    for other in server.get_online_players():
        if other is breaker or other.protocol_version != 767:
            continue
        if (x >> 4, z >> 4) not in other.loaded_chunks:
            continue
        pid = get_clientbound_packet(other.protocol_version, "world_event")
        if pid is not None:
            await other.send_packet(pid, payload)


async def _swap_hands(conn: Connection, server):
    """F 键: 交换主手与副手物品。"""
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return
    slot = conn.selected_hotbar_slot
    main, off = inv.get_slot(slot), inv.get_slot(40)
    inv.set_slot(slot, off)
    inv.set_slot(40, main)
    conn.inventory_state_id += 1
    from world.inventory import send_slot_update
    await send_slot_update(conn, slot)
    await send_slot_update(conn, 40)
    from handlers.play.players import broadcast_player_equipment
    await broadcast_player_equipment(server, conn)


def _drop_held_item(conn: Connection, server, whole_stack: bool = True):
    """Drop the held item (Q = one item, Ctrl+Q = the whole stack)."""
    inv = getattr(conn, 'inventory_obj', None)
    if inv is None:
        return

    held = inv.get_held_item_from_slot(conn.selected_hotbar_slot)
    if held is None or held.is_empty:
        return
    if conn.gamemode == "spectator":
        return

    import asyncio
    import math
    from handlers.play.entities import broadcast_entity_spawn

    count = held.count if whole_stack else 1

    async def _do_drop():
        entity = server.entity_manager.create_item(
            conn.x, conn.y + 1.3, conn.z,
            item_name=held.item_id, count=count
        )
        # 朝视线方向抛出
        yaw = math.radians(conn.yaw)
        pitch = math.radians(conn.pitch)
        entity.vx = -math.sin(yaw) * math.cos(pitch) * 0.3
        entity.vy = -math.sin(pitch) * 0.3 + 0.1
        entity.vz = math.cos(yaw) * math.cos(pitch) * 0.3
        entity.pickup_delay = 40  # 原版: 丢出的物品 2 秒内不能拾取
        await broadcast_entity_spawn(server, entity)

        held.count -= count
        if held.count <= 0:
            inv.set_slot(conn.selected_hotbar_slot, None)
        conn.inventory_state_id = getattr(conn, 'inventory_state_id', 0) + 1
        from world.inventory import send_slot_update
        await send_slot_update(conn, conn.selected_hotbar_slot)
        from handlers.play.players import broadcast_player_equipment
        await broadcast_player_equipment(server, conn)

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


def _is_replaceable(block_state: int) -> bool:
    """空气、流体和花草等可被直接替换的方块。"""
    if block_state == AIR:
        return True
    from world.chunk_io import STATE_ID_TO_BLOCK
    name, props = STATE_ID_TO_BLOCK.get(block_state, ("minecraft:stone", {}))
    if name == "minecraft:snow":
        return str(props.get("layers", "1")) == "1"
    return name in _REPLACEABLE_BLOCKS


_REPLACEABLE_BLOCKS = frozenset({
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:water", "minecraft:lava", "minecraft:short_grass", "minecraft:tall_grass",
    "minecraft:fern", "minecraft:large_fern", "minecraft:dead_bush", "minecraft:seagrass",
    "minecraft:tall_seagrass", "minecraft:snow", "minecraft:fire", "minecraft:soul_fire",
    "minecraft:vine", "minecraft:glow_lichen", "minecraft:hanging_roots",
    "minecraft:crimson_roots", "minecraft:warped_roots", "minecraft:nether_sprouts",
    "minecraft:bubble_column", "minecraft:light", "minecraft:structure_void",
})

_NON_SOLID_HINTS = ("torch", "flower", "sapling", "button", "lever", "sign", "rail",
                    "redstone_wire", "carpet", "pressure_plate", "ladder", "vine",
                    "tulip", "dandelion", "poppy", "mushroom", "banner", "tripwire",
                    "repeater", "comparator", "short_grass", "fern", "dead_bush")


def _collides_with_player(server, x: int, y: int, z: int, block_state: int) -> bool:
    """实心方块不能放在玩家身体所在的位置。"""
    from world.chunk_io import STATE_ID_TO_BLOCK
    name, _ = STATE_ID_TO_BLOCK.get(block_state, ("minecraft:stone", {}))
    if any(hint in name for hint in _NON_SOLID_HINTS):
        return False
    for player in server.get_online_players():
        if player.gamemode == "spectator" or getattr(player, "_dead", False):
            continue
        if (player.x + 0.3 > x and player.x - 0.3 < x + 1
                and player.z + 0.3 > z and player.z - 0.3 < z + 1
                and player.y + 1.8 > y and player.y < y + 1):
            return True
    return False


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
    cursor_x, offset = read_float(payload, offset)
    cursor_y, offset = read_float(payload, offset)
    cursor_z, offset = read_float(payload, offset)
    _, offset = read_boolean(payload, offset)  # insideBlock
    if conn.protocol_version >= 768:
        _, offset = read_boolean(payload, offset)  # worldBorderHit (1.21.2+)
    sequence, offset = read_varint(payload, offset)

    try:
        await _use_item_on(conn, server, hand, target_x, target_y, target_z, face,
                           (cursor_x, cursor_y, cursor_z))
    finally:
        await _acknowledge_block_change(conn, sequence)


async def _use_item_on(conn: Connection, server, hand: int,
                       target_x: int, target_y: int, target_z: int, face: int,
                       cursor: tuple[float, float, float] = (0.5, 0.5, 0.5)):
    """Use Item On 的实际逻辑: 方块交互优先, 其次放置手持方块。"""
    from world.block_behavior import (
        get_block_behavior, get_block_name_from_state, container_manager,
    )
    from world.chunk_io import STATE_ID_TO_BLOCK

    if conn.gamemode == "spectator" or not _within_reach(conn, target_x, target_y, target_z):
        return

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
    #    潜行时跳过交互, 直接放置方块 (原版行为)
    behavior = get_block_behavior(target_name)
    if (behavior is not None and behavior.is_interactive()
            and not getattr(conn, "sneaking", False)):
        try:
            action_taken = await behavior.on_use(
                conn, server, target_x, target_y, target_z, face, hand
            )
            if action_taken:
                return  # Block handled the interaction, skip placement
        except Exception as e:
            logger.warning(f"Block behavior error for {target_name}: {e}")

    # 2b. Minecarts go onto rails (MinecartItem.useOn)
    inv = getattr(conn, "inventory_obj", None)
    held = inv.get_held_item_from_slot(conn.selected_hotbar_slot) if inv is not None else None
    if held is not None and not held.is_empty:
        from world.minecart import MINECART_ITEMS, RAIL_NAMES, spawn_minecart
        if held.item_id in MINECART_ITEMS:
            if target_name in RAIL_NAMES:
                cart = spawn_minecart(server, held.item_id, target_x, target_y, target_z, getattr(conn, "yaw", 0.0))
                if cart is not None:
                    from handlers.play.entities import broadcast_entity_spawn
                    await broadcast_entity_spawn(server, cart)
                    _consume_placement_item(conn, held.item_id)
                    from world.inventory import send_inventory_sync
                    await send_inventory_sync(conn)
            return

    # 3. Attempt block placement
    # Clicking a replaceable block (grass, fern, a single snow layer...) puts
    # the new block in its place, like vanilla BlockPlaceContext.
    if target_block != AIR and _is_replaceable(target_block):
        place_x, place_y, place_z = target_x, target_y, target_z
    else:
        dx, dy, dz = FACE_OFFSETS.get(face, (0, 1, 0))
        place_x = target_x + dx
        place_y = target_y + dy
        place_z = target_z + dz

    if place_y < -64 or place_y >= 320:
        return

    # Get the block to place from the player's held item
    block_state, item_name = _get_held_item_for_placement(conn)
    if (block_state == 0 and item_name is None) or hand != 0:
        return  # Nothing to place

    async def _reject():
        """拒绝放置: 纠正客户端预测的方块, 并把被扣掉的物品同步回去。"""
        real = _get_block_at(server, place_x, place_y, place_z)
        if real is not None:
            await _send_block_change(conn, place_x, place_y, place_z, real)
        from world.inventory import send_slot_update
        await send_slot_update(conn, conn.selected_hotbar_slot)

    existing = _get_block_at(server, place_x, place_y, place_z)
    if (existing is None or not _is_replaceable(existing)
            or conn.gamemode == "adventure"
            or _is_spawn_protected(conn, server, place_x, place_z)
            or _collides_with_player(server, place_x, place_y, place_z, block_state)):
        await _reject()
        return

    # vanilla getStateForPlacement: facing, attachment face, halves, doors, beds...
    from world.placement import placement_states
    placements = placement_states(
        item_name, face, cursor, getattr(conn, "yaw", 0.0), getattr(conn, "pitch", 0.0),
        (place_x, place_y, place_z), existing,
        lambda bx, by, bz: _get_block_at(server, bx, by, bz), getattr(conn, "sneaking", False))
    if not placements:
        await _reject()
        return
    block_state = placements[0][1]

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
    # Plugin hook: allow plugins to cancel block placement
    from mods.bridge import hook_block_place
    if not hook_block_place(server, conn, place_x, place_y, place_z, block_state):
        await _reject()
        return  # Cancelled by a plugin

    changed_chunks = set()
    for (bx, by, bz), state in placements:
        before = existing if (bx, by, bz) == (place_x, place_y, place_z) else _get_block_at(server, bx, by, bz)
        changed = set_world_block(server, bx, by, bz, state)
        if not changed:
            continue
        changed_chunks |= changed
        await _broadcast_block_change(server, bx, by, bz, state)
    if not changed_chunks:
        await _reject()
        return
    if server.redstone_engine:
        for ux, uy, uz, new_state in server.redstone_engine.get_visual_updates():
            await _broadcast_block_change(server, ux, uy, uz, new_state)

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
            from handlers.play.players import broadcast_player_equipment
            await broadcast_player_equipment(server, conn)
