"""
Vanilla 1.21.1 explosions (net.minecraft.world.level.Explosion):

* 1352 rays from a 16x16x16 cube, intensity power*(0.7..1.3), stepping
  0.3 blocks and losing (resistance + 0.3) * 0.3 per block and 0.225 per step;
* destroyed blocks drop through their loot tables with the explosion radius
  (each item survives with chance 1/power), TNT in the blast is primed with
  a 10-29 tick fuse;
* entities within 2*power take ((i*i + i)/2 * 7 * 2*power + 1) damage where
  i = (1 - distance/(2*power)) * exposure, and are pushed away by i;
* the 1.21.1 Explosion packet carries each player's knockback.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import random
from functools import lru_cache

EXPLOSION_PARTICLE = 22          # minecraft:explosion
EXPLOSION_EMITTER_PARTICLE = 21  # minecraft:explosion_emitter


@lru_cache(maxsize=1)
def _block_resistance() -> dict[int, float]:
    from .chunk_io import _find_blocks_json
    table: dict[int, float] = {}
    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        for block in json.load(f):
            resistance = float(block.get("resistance") or 0.0)
            if resistance:
                for state in range(block["minStateId"], block["maxStateId"] + 1):
                    table[state] = resistance
    return table


@lru_cache(maxsize=1)
def _rays() -> list[tuple[float, float, float]]:
    rays = []
    for i in range(16):
        for j in range(16):
            for k in range(16):
                if i not in (0, 15) and j not in (0, 15) and k not in (0, 15):
                    continue
                dx, dy, dz = i / 15.0 * 2 - 1, j / 15.0 * 2 - 1, k / 15.0 * 2 - 1
                length = math.sqrt(dx * dx + dy * dy + dz * dz)
                rays.append((dx / length, dy / length, dz / length))
    return rays


def affected_blocks(get_block, x: float, y: float, z: float, power: float,
                    rng: random.Random) -> list[tuple[int, int, int]]:
    """Explosion.explode(): the block positions the explosion destroys."""
    resistance = _block_resistance()
    hit: set[tuple[int, int, int]] = set()
    for dx, dy, dz in _rays():
        intensity = power * (0.7 + rng.random() * 0.6)
        px, py, pz = x, y, z
        while intensity > 0.0:
            bx, by, bz = math.floor(px), math.floor(py), math.floor(pz)
            state = get_block(bx, by, bz)
            if state is None:          # outside the world
                break
            if state != 0:
                intensity -= (resistance.get(state, 0.0) + 0.3) * 0.3
                if intensity > 0.0:
                    hit.add((bx, by, bz))
            px += dx * 0.3
            py += dy * 0.3
            pz += dz * 0.3
            intensity -= 0.22500001
    return list(hit)


def _exposure(get_block, center, box) -> float:
    """Explosion.getSeenPercent: share of sample points of a box with a clear line to the centre."""
    from .block_shapes import no_collision_states
    passable = no_collision_states()
    (x0, y0, z0), (x1, y1, z1) = box
    sx = 1.0 / ((x1 - x0) * 2.0 + 1.0)
    sy = 1.0 / ((y1 - y0) * 2.0 + 1.0)
    sz = 1.0 / ((z1 - z0) * 2.0 + 1.0)
    ox = (1.0 - math.floor(1.0 / sx) * sx) / 2.0
    oz = (1.0 - math.floor(1.0 / sz) * sz) / 2.0
    seen = total = 0
    fx = 0.0
    while fx <= 1.0:
        fy = 0.0
        while fy <= 1.0:
            fz = 0.0
            while fz <= 1.0:
                px = x0 + (x1 - x0) * fx + ox
                py = y0 + (y1 - y0) * fy
                pz = z0 + (z1 - z0) * fz + oz
                if _clear_line(get_block, passable, (px, py, pz), center):
                    seen += 1
                total += 1
                fz += sz
            fy += sy
        fx += sx
    return seen / total if total else 0.0


def _clear_line(get_block, passable, start, end) -> bool:
    dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    steps = max(1, int(length / 0.25))
    last = None
    for n in range(steps):
        t = n / steps
        cell = (math.floor(start[0] + dx * t), math.floor(start[1] + dy * t), math.floor(start[2] + dz * t))
        if cell == last:
            continue
        last = cell
        state = get_block(*cell)
        if state is not None and state not in passable:
            return False
    return True


# Explosions are computed off the event loop, whether or not the server's
# multithreaded chunk generation is enabled: rays, exposure and loot rolls only
# read the world; applying the result happens back on the server thread.
_EXPLOSION_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="Explosion")


def _plan_explosion(server, x, y, z, power, destroy, targets, seed):
    """Worker thread: what the explosion destroys, drops and does to each target (read only)."""
    from .block_behavior import get_block_drops
    from .chunk_io import STATE_ID_TO_BLOCK
    from .editing import _get_block_from_cache
    rng = random.Random(seed)
    cache: dict = {}

    def get_block(bx, by, bz):
        return _get_block_from_cache(server, cache, bx, by, bz)

    positions = affected_blocks(get_block, x, y, z, power, rng) if destroy else []
    rng.shuffle(positions)
    blocks = []
    for pos in positions:
        state = get_block(*pos)
        if not state:
            continue
        name, props = STATE_ID_TO_BLOCK.get(state, ("minecraft:air", {}))
        drops = [] if name == "minecraft:tnt" else [
            (stack.item_id, stack.count) for stack in get_block_drops(name, None, props, explosion_radius=power)]
        blocks.append((pos, state, name, drops, rng.randrange(20) + 10))
    reach = power * 2.0
    impacts = []
    for key, box_min, box_max, eye in targets:
        impact, direction = _impact(get_block, (x, y, z), reach, box_min, box_max, eye)
        if impact > 0:
            impacts.append((key, impact, direction))
    return blocks, impacts


async def explode(server, x: float, y: float, z: float, power: float = 4.0,
                  source=None, destroy_blocks: bool = True):
    """Run a vanilla explosion at (x, y, z)."""
    from handlers.play.blocks import _broadcast_multi_block_changes
    from .editing import _get_block_from_cache, _save_dirty_chunks, _set_block_in_cache

    mob_griefing = server.gamerules.get("mobGriefing", True) if hasattr(server, "gamerules") else True
    from_creeper = getattr(source, "mob_type", None) == "creeper"
    destroy = destroy_blocks and (mob_griefing or not from_creeper)

    # snapshot of who can be hit (positions as of now)
    players = [p for p in server.get_online_players()
               if not getattr(p, "_dead", False) and p.gamemode != "spectator"]
    entities = [e for e in server.entity_manager.list_entities()
                if e is not source and getattr(e, "alive", True)]
    targets = []
    for i, player in enumerate(players):
        targets.append((("player", i), (player.x - 0.3, player.y, player.z - 0.3),
                        (player.x + 0.3, player.y + 1.8, player.z + 0.3), (player.x, player.y + 1.62, player.z)))
    for i, entity in enumerate(entities):
        height = float(getattr(entity, "profile", {}).get("height", 0.98 if entity.kind == "tnt" else 0.25))
        half = 0.49 if entity.kind == "tnt" else 0.3
        eye = entity.y if entity.kind == "tnt" else entity.y + height * 0.85
        targets.append((("entity", i), (entity.x - half, entity.y, entity.z - half),
                        (entity.x + half, entity.y + height, entity.z + half), (entity.x, eye, entity.z)))

    loop = asyncio.get_running_loop()
    blocks, impacts = await loop.run_in_executor(
        _EXPLOSION_POOL, _plan_explosion, server, x, y, z, power, destroy, targets, random.getrandbits(48))

    # --- entities: damage + knockback (server thread) ----------------------
    reach = power * 2.0
    knockback: dict = {}
    from handlers.play.combat import damage_mob, _broadcast_entity_hurt
    from handlers.play.join import _damage_player
    for (kind, index), impact, direction in impacts:
        damage = (impact * impact + impact) / 2.0 * 7.0 * reach + 1.0
        if kind == "player":
            player = players[index]
            if getattr(player, "_dead", False):
                continue
            await _damage_player(player, damage, "爆炸", server)
            if player.gamemode != "creative" or not getattr(player, "flying", False):
                blast = sum(_blast_protection(item) for item in (player.inventory_obj.slots[36:40]
                                                                   if getattr(player, "inventory_obj", None) else ()))
                factor = impact * max(0.0, 1.0 - blast * 0.15)
                knockback[player] = tuple(d * factor for d in direction)
            continue
        entity = entities[index]
        if not getattr(entity, "alive", True):
            continue
        if entity.kind == "mob":
            killed = damage_mob(server, entity, damage)
            await _broadcast_entity_hurt(server, entity.entity_id, entity.x, entity.z,
                                         damage_type="minecraft:explosion", dead=killed)
        elif entity.kind in ("item", "orb"):
            entity.alive = False  # items and orbs are destroyed by explosions
            continue
        entity.vx += direction[0] * impact
        entity.vy += direction[1] * impact
        entity.vz += direction[2] * impact
        entity.on_ground = False

    # --- blocks (server thread) ---------------------------------------------
    cache: dict = {}
    dirty: set = set()
    changes = []
    drops = []
    destroyed = []
    for (bx, by, bz), state, name, block_drops, fuse in blocks:
        if _get_block_from_cache(server, cache, bx, by, bz) != state:
            continue          # changed while the explosion was being computed
        destroyed.append((bx, by, bz))
        if name == "minecraft:tnt":
            # chain reaction: primed with a short random fuse
            server.entity_manager.create_tnt(bx + 0.5, by, bz + 0.5, fuse=fuse)
        else:
            drops.extend((bx, by, bz, item_id, count) for item_id, count in block_drops)
        if _set_block_in_cache(server, cache, dirty, bx, by, bz, 0):
            changes.append((bx, by, bz, 0))
    _save_dirty_chunks(server, cache, dirty)   # also notifies the redstone engine

    # vanilla merges identical drops (up to a full stack) before popping them
    merged: list[list] = []          # [x, y, z, item_id, count]
    for bx, by, bz, item_id, count in drops:
        for pile in merged:
            if pile[3] == item_id and pile[4] + count <= 64:
                pile[4] += count
                break
        else:
            merged.append([bx, by, bz, item_id, count])
    from handlers.play.entities import broadcast_entity_spawn
    rng = random.Random()
    for bx, by, bz, item_id, count in merged:
        item = server.entity_manager.create_item(bx + 0.5, by + 0.25, bz + 0.5, item_id, count)
        item.vx, item.vy, item.vz = rng.uniform(-0.1, 0.1), 0.2, rng.uniform(-0.1, 0.1)
        item.pickup_delay = 10
        await broadcast_entity_spawn(server, item)

    # --- packets ------------------------------------------------------------
    await _send_explosion_packets(server, x, y, z, power, destroyed, knockback)
    if changes:
        await _broadcast_multi_block_changes(server, changes)
    return destroyed


def _blast_protection(item) -> int:
    if item is None or getattr(item, "is_empty", True):
        return 0
    enchantments = (getattr(item, "nbt", None) or {}).get("enchantments", {}) or {}
    return int(enchantments.get("blast_protection", enchantments.get("minecraft:blast_protection", 0)) or 0)


def _impact(get_block, center, reach, box_min, box_max, eye):
    dx, dy, dz = box_min[0] + 0.3 - center[0], box_min[1] - center[1], box_min[2] + 0.3 - center[2]
    feet_dist = math.sqrt(dx * dx + dy * dy + dz * dz) / reach
    if feet_dist > 1.0:
        return 0.0, (0.0, 0.0, 0.0)
    ex, ey, ez = eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]
    length = math.sqrt(ex * ex + ey * ey + ez * ez)
    if length == 0:
        return 0.0, (0.0, 0.0, 0.0)
    exposure = _exposure(get_block, center, (box_min, box_max))
    impact = (1.0 - feet_dist) * exposure
    return impact, (ex / length, ey / length, ez / length)


async def _send_explosion_packets(server, x, y, z, power, blocks, knockback):
    from protocol.data_types import write_double, write_float, write_varint, write_string, write_boolean
    from protocol.packet_map import get_clientbound_packet
    base = bytearray()
    base.extend(write_double(x))
    base.extend(write_double(y))
    base.extend(write_double(z))
    base.extend(write_float(power))
    records = bytearray(write_varint(len(blocks)))
    cx, cy, cz = math.floor(x), math.floor(y), math.floor(z)
    for bx, by, bz in blocks:
        for delta in (bx - cx, by - cy, bz - cz):
            records.append(delta & 0xFF)
    for player in server.get_online_players():
        if player.protocol_version != 767:
            continue
        if (player.x - x) ** 2 + (player.y - y) ** 2 + (player.z - z) ** 2 > 4096:
            continue
        motion = knockback.get(player, (0.0, 0.0, 0.0))
        payload = bytearray(base)
        payload.extend(records)
        for value in motion:
            payload.extend(write_float(value))
        payload.extend(write_varint(2))  # block interaction: DESTROY_WITH_DECAY
        large = power >= 2.0 and bool(blocks)
        payload.extend(write_varint(EXPLOSION_PARTICLE))           # small particle
        payload.extend(write_varint(EXPLOSION_EMITTER_PARTICLE if large else EXPLOSION_PARTICLE))
        payload.extend(write_varint(0))                            # inline sound event
        payload.extend(write_string("minecraft:entity.generic.explode"))
        payload.extend(write_boolean(False))                       # no fixed range
        pid = get_clientbound_packet(player.protocol_version, "explosion")
        if pid is not None:
            await player.send_packet(pid, bytes(payload))
