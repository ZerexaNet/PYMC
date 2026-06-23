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
    在出生点附近选择一个更安全、更平坦的落脚点。
    优先选择草地/泥土/沙地等自然地表，并要求头顶有足够空间。
    """
    search_radius = 8
    preferred_blocks = {
        GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL, MOSS_BLOCK,
        SAND, RED_SAND, GRAVEL, SNOW_BLOCK, CLAY,
    }
    chunk_cache: dict[tuple[int, int], list[list[list[int]]] | None] = {}

    def _column_top(world_x: int, world_z: int):
        chunk_x = int(world_x) >> 4
        chunk_z = int(world_z) >> 4
        chunk_blocks = _load_or_generate_spawn_chunk(server, chunk_x, chunk_z, chunk_cache)
        if chunk_blocks is None:
            return None

        local_x = int(world_x) & 15
        local_z = int(world_z) & 15
        return _spawn_candidate_from_column(chunk_blocks, local_x, local_z)

    def _surface_slope(world_x: int, world_z: int) -> int:
        center = _column_top(world_x, world_z)
        if center is None:
            return 999
        deltas = []
        for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = _column_top(world_x + dx, world_z + dz)
            if neighbor is None:
                continue
            deltas.append(abs(center["world_y"] - neighbor["world_y"]))
        return max(deltas) if deltas else 0

    best_choice = None
    best_score = None
    fallback_choice = None
    fallback_score = None
    fallback_y = int(server.spawn_position[1])

    for dz in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            world_x = int(block_x) + dx
            world_z = int(block_z) + dz
            column = _column_top(world_x, world_z)
            if column is None:
                continue

            if dx == 0 and dz == 0:
                fallback_y = column["spawn_y"]

            slope = _surface_slope(world_x, world_z)
            distance = abs(dx) + abs(dz)
            score = distance * 6 + slope * 10
            if column["world_y"] < 62:
                score += 20

            if fallback_score is None or score < fallback_score:
                fallback_score = score
                fallback_choice = (world_x, column["spawn_y"], world_z)

            if column["block_id"] not in preferred_blocks:
                continue

            if column["block_id"] in preferred_blocks:
                score -= 40

            if best_score is None or score < best_score:
                best_score = score
                best_choice = (world_x, column["spawn_y"], world_z)

    if best_choice is not None:
        return best_choice
    if fallback_choice is not None:
        return fallback_choice
    return int(block_x), fallback_y, int(block_z)


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


def _is_suffocating_block(block_id: int | None) -> bool:
    """是否为会造成窒息的实体方块。"""
    return block_id is not None and block_id not in PASSABLE_BLOCKS


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


def _resolve_initial_player_location(server, player_state: dict | None) -> tuple[int, int, int]:
    """优先使用玩家存档位置，位置无效时回退到安全出生点。"""
    if player_state is not None:
        saved_x = math.floor(float(player_state.get("x", server.spawn_position[0])))
        saved_y = math.floor(float(player_state.get("y", server.spawn_position[1])))
        saved_z = math.floor(float(player_state.get("z", server.spawn_position[2])))
        if _is_safe_player_location(server, saved_x, saved_y, saved_z):
            return saved_x, saved_y, saved_z
        return _resolve_spawn_location(server, saved_x, saved_z)

    spawn_x, _, spawn_z = server.spawn_position
    resolved = _resolve_spawn_location(server, spawn_x, spawn_z)
    server.spawn_position = (int(resolved[0]), int(resolved[1]), int(resolved[2]))
    return resolved


def _resolve_player_respawn_location(conn: Connection, server) -> tuple[int, int, int]:
    """优先使用玩家个人出生点，否则回退到世界出生点。"""
    if conn.personal_spawn is not None:
        spawn_x, spawn_y, spawn_z = conn.personal_spawn
        if _is_safe_player_location(server, spawn_x, spawn_y, spawn_z):
            return spawn_x, spawn_y, spawn_z
        return _resolve_spawn_location(server, spawn_x, spawn_z)

    spawn_x, _, spawn_z = server.spawn_position
    respawn_x, respawn_y, respawn_z = _resolve_spawn_location(server, spawn_x, spawn_z)
    server.spawn_position = (int(respawn_x), int(respawn_y), int(respawn_z))
    return respawn_x, respawn_y, respawn_z
