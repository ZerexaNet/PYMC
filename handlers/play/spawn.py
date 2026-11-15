# ============================================================
# PyMC - 出生点安全系统
# 处理出生点选择、安全位置检测和玩家重生
# ============================================================

"""
出生点安全检测与位置选择。

包括:
  - 安全位置判断 (_is_safe_player_location)
  - 出生点搜索 (_resolve_spawn_location)
  - 玩家初始位置解析 (_resolve_initial_player_location)
  - 玩家重生位置解析 (_resolve_player_respawn_location)
"""

import math
import logging

from network.connection import Connection
from world.blocks import (
    AIR, WATER, LAVA, GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL,
    MOSS_BLOCK, SAND, RED_SAND, GRAVEL, SNOW_BLOCK, CLAY, STONE,
    FIRE, SOUL_FIRE, CACTUS, WATER_CAULDRON, LAVA_CAULDRON,
    MAGMA_BLOCK, CAMPFIRE, SOUL_CAMPFIRE, SWEET_BERRY_BUSH,
    POWDER_SNOW, POWDER_SNOW_CAULDRON, SNOW,
    SHORT_GRASS, TALL_GRASS, FERN, LARGE_FERN, DEAD_BUSH,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT, SUGAR_CANE, BAMBOO,
    OAK_LEAVES, SPRUCE_LEAVES, BIRCH_LEAVES, JUNGLE_LEAVES,
    ACACIA_LEAVES, CHERRY_LEAVES, DARK_OAK_LEAVES, MANGROVE_LEAVES,
    OAK_LOG, SPRUCE_LOG, BIRCH_LOG, JUNGLE_LOG, ACACIA_LOG,
    CHERRY_LOG, DARK_OAK_LOG, MANGROVE_LOG,
)

logger = logging.getLogger("PyMC.出生点")

# --- 可穿过方块 (玩家可以站立的空气/流体) ---
PASSABLE_BLOCKS = {
    AIR, WATER, LAVA, FIRE, SOUL_FIRE, WATER_CAULDRON, LAVA_CAULDRON,
    POWDER_SNOW, POWDER_SNOW_CAULDRON,
    SNOW, SHORT_GRASS, TALL_GRASS, FERN, LARGE_FERN, DEAD_BUSH,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT, SUGAR_CANE, BAMBOO,
}

# --- 出生点需要清除的方块 (头部/脚部空间) ---
SPAWN_CLEAR_BLOCKS = {
    AIR, SNOW, SHORT_GRASS, TALL_GRASS, FERN, LARGE_FERN, DEAD_BUSH,
}

# --- 不安全的地面方块 ---
SPAWN_UNSAFE_GROUND_BLOCKS = {
    AIR, WATER, LAVA, FIRE, SOUL_FIRE, WATER_CAULDRON, LAVA_CAULDRON,
    POWDER_SNOW, POWDER_SNOW_CAULDRON, CACTUS, MAGMA_BLOCK,
    CAMPFIRE, SOUL_CAMPFIRE, SWEET_BERRY_BUSH,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT, SUGAR_CANE, BAMBOO,
}

# --- 树冠方块 (不作为地面但也不阻碍) ---
SPAWN_CANOPY_BLOCKS = {
    OAK_LEAVES, SPRUCE_LEAVES, BIRCH_LEAVES, JUNGLE_LEAVES,
    ACACIA_LEAVES, CHERRY_LEAVES, DARK_OAK_LEAVES, MANGROVE_LEAVES,
    OAK_LOG, SPRUCE_LOG, BIRCH_LOG, JUNGLE_LOG, ACACIA_LOG,
    CHERRY_LOG, DARK_OAK_LOG, MANGROVE_LOG,
}


def _load_or_generate_spawn_chunk(
    server,
    cx: int,
    cz: int,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]] | None],
):
    """Load a chunk for spawn checks, generating it when it is not on disk yet."""
    key = (int(cx), int(cz))
    if key in chunk_cache:
        return chunk_cache[key]

    storage = server.world_storage
    chunk_blocks = None
    chunk_biomes = None
    if hasattr(storage, "load_generated_chunk_with_biomes"):
        loaded = storage.load_generated_chunk_with_biomes(*key)
        if loaded is not None:
            chunk_blocks, chunk_biomes = loaded
    if chunk_blocks is None and hasattr(storage, "load_generated_chunk"):
        chunk_blocks = storage.load_generated_chunk(*key)

    if chunk_blocks is None:
        if getattr(server, "terrain_generator", None) is None and hasattr(server, "_initialize_terrain_generator"):
            server._initialize_terrain_generator()
        terrain = getattr(server, "terrain_generator", None)
        if terrain is not None:
            if getattr(server, "_use_native_terrain", False) and hasattr(terrain, "generate_chunk_with_metadata"):
                chunk_blocks, _, chunk_biomes = terrain.generate_chunk_with_metadata(*key)
            elif getattr(server, "_use_native_terrain", False) and hasattr(terrain, "generate_chunk_with_heightmap"):
                chunk_blocks, _ = terrain.generate_chunk_with_heightmap(*key)
            elif hasattr(terrain, "generate_chunk"):
                chunk_blocks = terrain.generate_chunk(*key)

        if chunk_blocks is not None:
            biome_sampler = getattr(server, "biome_sampler", None)
            if chunk_biomes is None and biome_sampler is not None:
                chunk_biomes = biome_sampler.build_chunk_biome_sections(*key, chunk_blocks)
            if hasattr(storage, "save_generated_chunk"):
                storage.save_generated_chunk(*key, chunk_blocks, chunk_biomes)

    chunk_cache[key] = chunk_blocks
    return chunk_blocks


def _is_spawn_clear_block(block_id: int | None) -> bool:
    return block_id in SPAWN_CLEAR_BLOCKS


def _is_spawn_ground_block(block_id: int | None) -> bool:
    return (
        block_id is not None
        and block_id not in SPAWN_UNSAFE_GROUND_BLOCKS
        and block_id not in SPAWN_CLEAR_BLOCKS
        and block_id not in SPAWN_CANOPY_BLOCKS
    )


def _spawn_candidate_from_column(chunk_blocks, local_x: int, local_z: int):
    for y_index in range(len(chunk_blocks) - 3, 0, -1):
        ground = chunk_blocks[y_index][local_z][local_x]
        foot = chunk_blocks[y_index + 1][local_z][local_x]
        head = chunk_blocks[y_index + 2][local_z][local_x]
        if not _is_spawn_ground_block(ground):
            continue
        if not _is_spawn_clear_block(foot) or not _is_spawn_clear_block(head):
            continue
        return {
            "block_id": ground,
            "world_y": y_index - 64,
            "spawn_y": y_index + 1 - 64,
        }
    return None


def _resolve_spawn_location(server, block_x: int, block_z: int) -> tuple[int, int, int]:
    """
    The nearest column around (x, z) where a player can stand safely
    (used when a saved position is no longer valid).
    """
    cache: dict = {}
    pos = overworld_respawn_pos(server, int(block_x), int(block_z), cache)
    if pos is not None:
        return pos
    for radius in range(1, 17):
        for dx in range(-radius, radius + 1):
            for dz in (-radius, radius) if abs(dx) != radius else range(-radius, radius + 1):
                pos = overworld_respawn_pos(server, int(block_x) + dx, int(block_z) + dz, cache)
                if pos is not None:
                    return pos
    pos = _search_safe_nearby(server, int(block_x), int(block_z), 256, cache)
    if pos is not None:
        return pos
    return int(block_x), int(server.spawn_position[1]), int(block_z)


def _get_spawn_check_block(
    server,
    world_x: int,
    world_y: int,
    world_z: int,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]] | None],
) -> int | None:
    if world_y < -64 or world_y >= 320:
        return None
    chunk_x = int(world_x) >> 4
    chunk_z = int(world_z) >> 4
    chunk_blocks = _load_or_generate_spawn_chunk(server, chunk_x, chunk_z, chunk_cache)
    if chunk_blocks is None:
        return None
    return int(chunk_blocks[int(world_y) + 64][int(world_z) & 15][int(world_x) & 15])


_SUFFOCATING_STATES: frozenset[int] | None = None


def _suffocating_states() -> frozenset[int]:
    """
    会让玩家窒息的方块状态: 完整的不透光实心方块 (石头、泥土、木板...)。
    台阶、楼梯、树叶、玻璃、花草、火把、箱子等都不会 (与原版一致)。
    数据来自 world/blocks.json 的 boundingBox / filterLight。
    """
    global _SUFFOCATING_STATES
    if _SUFFOCATING_STATES is None:
        import json
        from world.chunk_io import _find_blocks_json
        states: set[int] = set()
        try:
            with open(_find_blocks_json(), "r", encoding="utf-8") as f:
                for block in json.load(f):
                    if (block.get("boundingBox") == "block"
                            and int(block.get("filterLight", 0)) >= 15
                            and not block.get("transparent", False)):
                        states.update(range(block["minStateId"], block["maxStateId"] + 1))
        except Exception:
            states = set()
        _SUFFOCATING_STATES = frozenset(states)
    return _SUFFOCATING_STATES


def _is_suffocating_block(block_id: int | None) -> bool:
    """是否为会造成窒息的完整实心方块。"""
    if block_id is None:
        return False
    states = _suffocating_states()
    if states:
        return block_id in states
    return block_id not in PASSABLE_BLOCKS


def _is_safe_player_location(server, world_x: int, world_y: int, world_z: int) -> bool:
    """判断一个玩家站立位置是否安全。"""
    chunk_cache: dict[tuple[int, int], list[list[list[int]]] | None] = {}
    foot_block = _get_spawn_check_block(server, world_x, world_y, world_z, chunk_cache)
    head_block = _get_spawn_check_block(server, world_x, world_y + 1, world_z, chunk_cache)
    below_block = _get_spawn_check_block(server, world_x, world_y - 1, world_z, chunk_cache)
    if foot_block is None or head_block is None or below_block is None:
        return False
    if not _is_spawn_clear_block(foot_block) or not _is_spawn_clear_block(head_block):
        return False
    return _is_spawn_ground_block(below_block)


# ------------------------------------------------------------------
# Vanilla spawn logic (PlayerRespawnLogic / MinecraftServer.setInitialSpawn)
# ------------------------------------------------------------------

def _block_tables():
    """(fluid ids, full-top-face ids, hazard ids, non-blocking ids) from blocks.json."""
    global _TABLES
    try:
        return _TABLES
    except NameError:
        pass
    import json
    from world.chunk_io import _find_blocks_json
    fluids, full, hazards, passable, leaves = set(), set(), set(), set(), set()
    partial_names = ("_slab", "_stairs", "carpet", "pressure_plate", "_wall", "fence", "_pane", "bars",
                     "snow", "cactus", "farmland", "dirt_path", "soul_sand", "honey_block", "bed",
                     "chest", "lantern", "cake", "candle", "head", "skull", "pot", "anvil", "hopper",
                     "cauldron", "lectern", "enchanting", "brewing", "dripstone", "amethyst_cluster",
                     "bud", "scaffolding", "door", "trapdoor", "chain", "rod", "rail", "button", "lever",
                     "torch", "sign", "banner", "campfire", "composter", "stonecutter", "grindstone",
                     "bell", "conduit", "sea_pickle", "turtle_egg", "sniffer_egg", "frogspawn")
    hazard_names = ("lava", "fire", "magma_block", "campfire", "cactus", "sweet_berry_bush",
                    "powder_snow", "wither_rose", "pointed_dripstone")
    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        for block in json.load(f):
            name = block["name"]
            ids = range(block["minStateId"], block["maxStateId"] + 1)
            if name in ("water", "lava", "bubble_column"):
                fluids.update(ids)
            if any(h in name for h in hazard_names):
                hazards.update(ids)
            if block.get("boundingBox") == "block" and not any(p in name for p in partial_names):
                full.update(ids)
            if block.get("boundingBox") == "empty" or name in ("snow",):
                passable.update(ids)
            if name.endswith("_leaves"):
                leaves.update(ids)
    fluids_f, full_f, hazards_f, passable_f = map(frozenset, (fluids, full, hazards, passable))
    _TABLES = (fluids_f, full_f, hazards_f, passable_f, frozenset(leaves))
    return _TABLES


def _column_block(chunk_blocks, x: int, y: int, z: int) -> int:
    if y < -64 or y > 319:
        return AIR
    return int(chunk_blocks[y + 64][z & 15][x & 15])


def overworld_respawn_pos(server, x: int, z: int, chunk_cache: dict | None = None,
                          allow_tree_tops: bool = False):
    """
    PlayerRespawnLogic.getOverworldRespawnPos plus safety checks.

    Returns the block position the player's feet go into, or None when the
    column's top is a fluid (ocean, lake, lava pool), when there is no full
    block to stand on, or when the spot is next to something harmful.
    """
    if chunk_cache is None:
        chunk_cache = {}
    chunk = _load_or_generate_spawn_chunk(server, x >> 4, z >> 4, chunk_cache)
    if chunk is None:
        return None
    fluids, full, hazards, passable, leaves = _block_tables()
    top = None
    for y in range(319, -65, -1):
        block = _column_block(chunk, x, y, z)
        if block == AIR or block in passable and block not in fluids:
            continue
        if block in leaves and not allow_tree_tops:
            continue  # look for the ground below the canopy (MOTION_BLOCKING_NO_LEAVES)
        top = y
        break
    if top is None or _column_block(chunk, x, top, z) in fluids:
        return None
    ground = _column_block(chunk, x, top, z)
    if ground not in full or ground in hazards:
        return None
    feet, head = top + 1, top + 2
    if head > 319:
        return None
    for y in (feet, head):
        block = _column_block(chunk, x, y, z)
        if block in fluids or block in hazards or not (block == AIR or block in passable):
            return None
    # nothing harmful next to the player's body
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        neighbour = _load_or_generate_spawn_chunk(server, (x + dx) >> 4, (z + dz) >> 4, chunk_cache)
        if neighbour is None:
            continue
        for y in (top, feet, head):
            if _column_block(neighbour, x + dx, y, z + dz) in hazards:
                return None
    return int(x), int(feet), int(z)


def spawn_pos_in_chunk(server, chunk_x: int, chunk_z: int, chunk_cache: dict | None = None,
                       allow_tree_tops: bool = False):
    """PlayerRespawnLogic.getSpawnPosInChunk: first valid column, scanning x then z."""
    for x in range(chunk_x * 16, chunk_x * 16 + 16):
        for z in range(chunk_z * 16, chunk_z * 16 + 16):
            pos = overworld_respawn_pos(server, x, z, chunk_cache, allow_tree_tops)
            if pos is not None:
                return pos
    return None


def _climate_spawn_column(server) -> tuple[int, int]:
    """The column vanilla starts from: Climate.findSpawnPosition (native) or a land search."""
    terrain = getattr(server, "terrain_generator", None)
    finder = getattr(terrain, "find_spawn", None)
    if finder is not None:
        try:
            found = finder()
            if found is not None:
                return int(found[0]), int(found[1])
        except Exception as e:
            logger.warning(f"Native spawn search failed: {e}")
    # Fallback for the Python generators: nearest land on a coarse spiral.
    height = getattr(terrain, "get_terrain_height", None)
    if height is not None:
        for radius in range(0, 2049, 64):
            steps = max(1, radius // 16)
            for i in range(steps * 4 if radius else 1):
                angle = (i / (steps * 4)) * 6.283185307179586 if radius else 0.0
                x = int(math.sin(angle) * radius)
                z = int(math.cos(angle) * radius)
                try:
                    if height(x, z) > 64:
                        return x, z
                except Exception:
                    break
    return 0, 0


def find_world_spawn(server) -> tuple[int, int, int]:
    """
    Pick the spawn point of a new world like MinecraftServer.setInitialSpawn:
    climate-based search for land, then an 11x11 chunk spiral for the first
    column a player can safely stand on.
    """
    x, z = _climate_spawn_column(server)
    center_cx, center_cz = x >> 4, z >> 4
    cache: dict = {}
    for allow_tree_tops in (False, True):
        j = k = l = 0
        m = -1
        for _ in range(11 * 11):
            if -5 <= j <= 5 and -5 <= k <= 5:
                pos = spawn_pos_in_chunk(server, center_cx + j, center_cz + k, cache, allow_tree_tops)
                if pos is not None:
                    return pos
            if j == k or (j < 0 and j == -k) or (j > 0 and j == 1 - k):
                l, m = -m, l
            j += l
            k += m
    # nothing safe in 11x11 chunks (e.g. a mushroom island in the ocean): widen the search
    pos = _search_safe_nearby(server, center_cx * 16 + 8, center_cz * 16 + 8, 256, cache)
    if pos is not None:
        return pos
    return center_cx * 16 + 8, 100, center_cz * 16 + 8


def _search_safe_nearby(server, x: int, z: int, radius: int, cache: dict):
    for r in range(0, radius + 1, 4):
        for dx in range(-r, r + 1, 4):
            for dz in (-r, r) if abs(dx) != r else range(-r, r + 1, 4):
                pos = overworld_respawn_pos(server, x + dx, z + dz, cache)
                if pos is not None:
                    return pos
    return None


def _spawn_radius(server) -> int:
    rules = getattr(server, "gamerules", None)
    try:
        return max(0, int(rules.get("spawnRadius", 10))) if rules is not None else 10
    except (TypeError, ValueError):
        return 10


def fudge_spawn_location(server, base: tuple[int, int, int], radius: int | None = None):
    """
    ServerPlayer.fudgeSpawnLocation: a random safe column within the
    spawnRadius gamerule around the world spawn (visits every column once,
    in a random coprime order, like vanilla).
    """
    import random
    bx, by, bz = (int(v) for v in base)
    r = _spawn_radius(server) if radius is None else radius
    if r <= 0:
        r = 0
    side = r * 2 + 1
    total = side * side
    step = _coprime(total)
    start = random.randrange(total)
    cache: dict = {}
    for allow_tree_tops in (False, True):
        for p in range(total):
            q = (start + step * p) % total
            x = bx + q % side - r
            z = bz + q // side - r
            pos = overworld_respawn_pos(server, x, z, cache, allow_tree_tops)
            if pos is not None:
                return pos
    pos = overworld_respawn_pos(server, bx, bz, cache) or _search_safe_nearby(server, bx, bz, 128, cache)
    return pos if pos is not None else (bx, by, bz)


def _coprime(n: int) -> int:
    return 17 if n <= 16 else 17 if n % 17 else 31 if n % 31 else 1


def _resolve_initial_player_location(server, player_state: dict | None) -> tuple[int, int, int]:
    """
    Returning players: their saved position, unless it would trap them in a
    solid block or below the world. New players: a random safe column near
    the world spawn.
    """
    if player_state is not None and all(k in player_state for k in ("x", "y", "z")):
        saved_x = math.floor(float(player_state["x"]))
        saved_y = math.floor(float(player_state["y"]))
        saved_z = math.floor(float(player_state["z"]))
        if -64 <= saved_y < 320:
            cache: dict = {}
            foot = _get_spawn_check_block(server, saved_x, saved_y, saved_z, cache)
            head = _get_spawn_check_block(server, saved_x, min(319, saved_y + 1), saved_z, cache)
            if (foot is not None and head is not None
                    and not _is_suffocating_block(foot) and not _is_suffocating_block(head)):
                return saved_x, saved_y, saved_z
        return _resolve_spawn_location(server, saved_x, saved_z)

    if not getattr(server, "_spawn_resolved", True):
        server.spawn_position = find_world_spawn(server)
        server._spawn_resolved = True
    return fudge_spawn_location(server, server.spawn_position)


def _resolve_player_respawn_location(conn: Connection, server) -> tuple[int, int, int]:
    """Personal spawn point (bed / /spawnpoint) if still usable, else near world spawn."""
    if conn.personal_spawn is not None:
        spawn_x, spawn_y, spawn_z = conn.personal_spawn
        if _is_safe_player_location(server, spawn_x, spawn_y, spawn_z):
            return spawn_x, spawn_y, spawn_z
    return fudge_spawn_location(server, server.spawn_position)
