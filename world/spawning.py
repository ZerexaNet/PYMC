# ============================================================
# PyMC - natural mob spawning and despawning
#
# Rules follow vanilla 1.21.1 for the mobs the server has:
#   * hostile mobs (zombie, skeleton, creeper, spider) spawn where the light a
#     mob sees is 7 or less: max(block light, sky light - sky darkness), where
#     the sky darkness is 11 at night and 0 by day; they never spawn in peaceful;
#   * passive mobs (pig, cow, sheep) spawn on grass in light 9 or more;
#   * no spawn within 24 blocks of a player, no spawn in water or lava;
#   * caps: 70 hostile and 10 passive mobs per online player;
#   * despawn: any mob with no player within 128 blocks is removed; a hostile
#     mob further than 32 blocks from every player is removed with a small chance.
#
# Approximations: spawn positions are on the surface of the ring around a player
# (vanilla also spawns in caves), there is no group spawning, and the sky darkness
# ignores weather. The light of a chunk comes from world.lighting (per chunk).
# ============================================================

from __future__ import annotations

import math
import random

from .blocks import AIR, GRASS_BLOCK, LAVA, WATER

HOSTILE = ("zombie", "skeleton", "creeper", "spider")
PASSIVE = ("pig", "cow", "sheep")

SPAWN_INTERVAL = 10         # ticks between spawn cycles
DESPAWN_INTERVAL = 200      # ticks between despawn checks
ATTEMPTS = 6                # spawn attempts per player per category and cycle
MIN_DISTANCE = 24.0         # no spawns closer than this to any player
MAX_RING = 96              # spawn attempts land this far (at most) from the player
HOSTILE_CAP = 70            # per online player
PASSIVE_CAP = 10            # per online player
DESPAWN_FAR = 128.0         # removed at once beyond this
DESPAWN_SOFT = 32.0         # hostile mobs beyond this may be removed
DESPAWN_CHANCE = 0.25       # chance per check for a hostile mob beyond DESPAWN_SOFT
CHUNK_LIGHT_TTL = 200       # ticks a chunk's light is reused for
CHUNK_LIGHT_LIMIT = 256
_LIQUIDS = frozenset({WATER, LAVA})


def sky_darkness(world_time: int) -> int:
    """How much the sky light is darkened at this time of day (vanilla: 11 at night)."""
    return 11 if 13000 <= int(world_time) % 24000 <= 23000 else 0


def brightness(block_light: int, sky_light: int, darkness: int) -> int:
    """The light a mob sees (vanilla's getBrightness)."""
    return max(block_light, sky_light - darkness)


def can_spawn(category: str, mob_type: str, feet: int | None, head: int | None,
              ground: int | None, light: int, sky_raw: int, block_raw: int, passable) -> bool:
    """Whether a mob of this kind can stand at the position (pure function, tested)."""
    if feet is None or head is None or ground is None:
        return False
    if not passable(feet) or not passable(head) or feet in _LIQUIDS or head in _LIQUIDS:
        return False
    if passable(ground) or ground == AIR:
        return False
    if category == "hostile":
        return mob_type in HOSTILE and light <= 7
    if category == "passive":
        return mob_type in PASSIVE and ground == GRASS_BLOCK and max(block_raw, sky_raw) >= 9
    return False


# ------------------------------------------------------------ light of a chunk

def _chunk_light(server, cx: int, cz: int, stamp: int):
    """(sky, block) light arrays of a chunk, cached for CHUNK_LIGHT_TTL ticks."""
    cache = server.__dict__.setdefault("_spawn_light_cache", {})
    cached = cache.get((cx, cz))
    if cached is not None and stamp - cached[0] < CHUNK_LIGHT_TTL:
        return cached[1], cached[2]
    blocks = server.world_storage.load_generated_chunk(cx, cz)
    if blocks is None:
        return None
    from .lighting import compute_light
    sky, block = compute_light(blocks)
    if len(cache) >= CHUNK_LIGHT_LIMIT:
        cache.clear()
    cache[(cx, cz)] = (stamp, sky, block)
    return sky, block


def _light_at(server, x: int, y: int, z: int, stamp: int):
    """(block light, sky light) at a block position, or None when its chunk is not loaded."""
    chunk = _chunk_light(server, x >> 4, z >> 4, stamp)
    if chunk is None:
        return None
    index = (y + 64) * 256 + (z & 15) * 16 + (x & 15)
    sky, block = chunk
    return block[index], sky[index]


# ------------------------------------------------------------ spawning

def _spawn_position(server, player, rng: random.Random):
    """A random surface position in a ring around the player, or None."""
    angle = rng.random() * math.tau
    radius = rng.uniform(MIN_DISTANCE, MAX_RING)
    x = math.floor(player.x + math.cos(angle) * radius)
    z = math.floor(player.z + math.sin(angle) * radius)
    top = min(318, int(player.y) + 24)
    bottom = max(-63, int(player.y) - 40)
    for y in range(top, bottom, -1):
        feet = server.get_block_at(x, y, z)
        if feet is None:
            return None
        ground = server.get_block_at(x, y - 1, z)
        if ground is not None and ground != AIR and not _passable(ground) and _passable(feet):
            return x, y, z
    return None


def _passable(block_id) -> bool:
    from .entities import _is_passable
    return _is_passable(block_id)


def _too_close(players, x: float, y: float, z: float) -> bool:
    limit = MIN_DISTANCE * MIN_DISTANCE
    for player in players:
        dx, dz = player.x - x, player.z - z
        if dx * dx + dz * dz < limit:
            return True
    return False


def run_spawning(server, tick_count: int) -> int:
    """One spawn cycle (every SPAWN_INTERVAL ticks). Returns how many mobs were spawned."""
    if tick_count % SPAWN_INTERVAL:
        return 0
    players = [p for p in server.get_online_players() if p.gamemode != "spectator"]
    if not players:
        return 0
    config = getattr(server, "config", {})
    peaceful = str(config.get("difficulty", "easy")).lower() == "peaceful"
    world_time = int(getattr(server, "world_time", 0))
    darkness = sky_darkness(world_time)
    rng = random.Random(tick_count ^ (server.next_entity_id * 2654435761))
    manager = server.entity_manager
    stamp = tick_count

    counts = {"hostile": 0, "passive": 0}
    for mob in manager.of_kind("mob"):
        category = mob.profile.get("category")
        if category in counts:
            counts[category] += 1
    caps = {"hostile": HOSTILE_CAP * len(players), "passive": PASSIVE_CAP * len(players)}
    enabled = {"hostile": config.get("spawn-monsters", True) and not peaceful,
               "passive": config.get("spawn-animals", True)}

    spawned = 0
    for player in players:
        for category in ("hostile", "passive"):
            if not enabled[category]:
                continue
            for _ in range(ATTEMPTS):
                if counts[category] >= caps[category]:
                    break
                pos = _spawn_position(server, player, rng)
                if pos is None:
                    continue
                x, y, z = pos
                if _too_close(players, x + 0.5, y, z + 0.5):
                    continue
                kinds = HOSTILE if category == "hostile" else PASSIVE
                mob_type = rng.choice(kinds)
                light = _light_at(server, x, y, z, stamp)
                if light is None:
                    continue
                block_light, sky_light = light
                feet = server.get_block_at(x, y, z)
                head = server.get_block_at(x, y + 1, z)
                ground = server.get_block_at(x, y - 1, z)
                level = brightness(block_light, sky_light, darkness)
                if not can_spawn(category, mob_type, feet, head, ground, level,
                                 sky_light, block_light, _passable):
                    continue
                manager.create_mob(x + 0.5, y, z + 0.5, mob_type=mob_type)
                counts[category] += 1
                spawned += 1
    return spawned


def run_despawning(server, tick_count: int) -> int:
    """Remove mobs that are too far from every player. Returns how many were removed."""
    if tick_count % DESPAWN_INTERVAL:
        return 0
    players = server.get_online_players()
    manager = server.entity_manager
    rng = random.Random(tick_count * 31 + server.next_entity_id)
    removed = 0
    for mob in list(manager.of_kind("mob")):
        category = mob.profile.get("category")
        if not players:
            continue
        nearest = min(math.hypot(p.x - mob.x, p.z - mob.z) for p in players)
        if nearest > DESPAWN_FAR or (category == "hostile" and nearest > DESPAWN_SOFT
                                     and rng.random() < DESPAWN_CHANCE):
            manager.remove_entity(mob.entity_id)
            removed += 1
    return removed
