# ============================================================
# PyMC - 世界编辑基础能力
# 用于方块查询、单点改块、区域填充、区域复制
# ============================================================

from .chunk_io import BLOCK_NAME_TO_DEFAULT_STATE
from .blocks import AIR

MIN_Y = -64
MAX_Y = 319


def normalize_block_name(spec: str) -> str:
    spec = spec.strip().lower()
    if not spec:
        return "minecraft:air"
    if ":" not in spec:
        spec = f"minecraft:{spec}"
    return spec


def resolve_block_state(spec: str) -> int | None:
    return BLOCK_NAME_TO_DEFAULT_STATE.get(normalize_block_name(spec))


def get_world_block(server, x: int, y: int, z: int) -> int | None:
    if y < MIN_Y or y > MAX_Y:
        return None
    chunk_x = x >> 4
    chunk_z = z >> 4
    chunk_blocks = server.world_storage.load_generated_chunk(chunk_x, chunk_z)
    if chunk_blocks is None:
        return None
    local_x = x & 15
    local_z = z & 15
    return int(chunk_blocks[y - MIN_Y][local_z][local_x])


def _load_chunk_for_edit(server, chunk_x: int, chunk_z: int):
    chunk_blocks = server.world_storage.load_generated_chunk(chunk_x, chunk_z)
    if chunk_blocks is None:
        if getattr(server, "_use_native_terrain", False) and hasattr(server.terrain_generator, "generate_chunk_with_heightmap"):
            chunk_blocks, _ = server.terrain_generator.generate_chunk_with_heightmap(chunk_x, chunk_z)
        else:
            chunk_blocks = server.terrain_generator.generate_chunk(chunk_x, chunk_z)
    return chunk_blocks


def _get_edit_chunk(
    server,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]]],
    chunk_x: int,
    chunk_z: int,
):
    key = (chunk_x, chunk_z)
    if key not in chunk_cache:
        chunk_cache[key] = _load_chunk_for_edit(server, chunk_x, chunk_z)
    return chunk_cache[key]


def _save_dirty_chunks(
    server,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]]],
    dirty_chunks: set[tuple[int, int]],
):
    for chunk_x, chunk_z in dirty_chunks:
        chunk_blocks = chunk_cache[(chunk_x, chunk_z)]
        chunk_biomes = server.biome_sampler.build_chunk_biome_sections(chunk_x, chunk_z, chunk_blocks)
        server.world_storage.save_generated_chunk(chunk_x, chunk_z, chunk_blocks, chunk_biomes)


def _set_block_in_cache(
    server,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]]],
    dirty_chunks: set[tuple[int, int]],
    x: int,
    y: int,
    z: int,
    block_state: int,
) -> bool:
    if y < MIN_Y or y > MAX_Y:
        return False
    chunk_x = x >> 4
    chunk_z = z >> 4
    chunk_blocks = _get_edit_chunk(server, chunk_cache, chunk_x, chunk_z)
    local_x = x & 15
    local_z = z & 15
    y_index = y - MIN_Y
    if y_index < 0 or y_index >= len(chunk_blocks):
        return False
    if chunk_blocks[y_index][local_z][local_x] == int(block_state):
        return False
    chunk_blocks[y_index][local_z][local_x] = int(block_state)
    dirty_chunks.add((chunk_x, chunk_z))
    return True


def _get_block_from_cache(
    server,
    chunk_cache: dict[tuple[int, int], list[list[list[int]]]],
    x: int,
    y: int,
    z: int,
) -> int | None:
    if y < MIN_Y or y > MAX_Y:
        return None
    chunk_x = x >> 4
    chunk_z = z >> 4
    chunk_blocks = _get_edit_chunk(server, chunk_cache, chunk_x, chunk_z)
    local_x = x & 15
    local_z = z & 15
    return int(chunk_blocks[y - MIN_Y][local_z][local_x])


def set_world_block(server, x: int, y: int, z: int, block_state: int) -> set[tuple[int, int]]:
    chunk_cache: dict[tuple[int, int], list[list[list[int]]]] = {}
    dirty_chunks: set[tuple[int, int]] = set()
    if not _set_block_in_cache(server, chunk_cache, dirty_chunks, x, y, z, block_state):
        return set()
    _save_dirty_chunks(server, chunk_cache, dirty_chunks)
    return dirty_chunks


def fill_box(server, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, block_state: int) -> tuple[int, set[tuple[int, int]]]:
    changed_positions, changed_chunks, _ = fill_box_detailed(
        server, x1, y1, z1, x2, y2, z2, block_state
    )
    return changed_positions, changed_chunks


def fill_box_detailed(
    server,
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    block_state: int,
) -> tuple[int, set[tuple[int, int]], list[tuple[int, int, int, int]]]:
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    min_z, max_z = sorted((z1, z2))

    chunk_cache: dict[tuple[int, int], list[list[list[int]]]] = {}
    dirty_chunks: set[tuple[int, int]] = set()
    changed_positions = 0
    changed_blocks: list[tuple[int, int, int, int]] = []

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if y < MIN_Y or y > MAX_Y:
                continue
            for z in range(min_z, max_z + 1):
                if _set_block_in_cache(server, chunk_cache, dirty_chunks, x, y, z, block_state):
                    changed_positions += 1
                    changed_blocks.append((x, y, z, int(block_state)))

    _save_dirty_chunks(server, chunk_cache, dirty_chunks)
    return changed_positions, dirty_chunks, changed_blocks


def _ranges_overlap(a_min: int, a_max: int, b_min: int, b_max: int) -> bool:
    return not (a_max < b_min or b_max < a_min)


def clone_box(
    server,
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    dest_x: int,
    dest_y: int,
    dest_z: int,
    *,
    mask_mode: str = "replace",
    clone_mode: str = "normal",
    filter_block_state: int | None = None,
) -> tuple[int, set[tuple[int, int]]]:
    changed_positions, changed_chunks, _ = clone_box_detailed(
        server,
        x1, y1, z1, x2, y2, z2,
        dest_x, dest_y, dest_z,
        mask_mode=mask_mode,
        clone_mode=clone_mode,
        filter_block_state=filter_block_state,
    )
    return changed_positions, changed_chunks


def clone_box_detailed(
    server,
    x1: int,
    y1: int,
    z1: int,
    x2: int,
    y2: int,
    z2: int,
    dest_x: int,
    dest_y: int,
    dest_z: int,
    *,
    mask_mode: str = "replace",
    clone_mode: str = "normal",
    filter_block_state: int | None = None,
) -> tuple[int, set[tuple[int, int]], list[tuple[int, int, int, int]]]:
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    min_z, max_z = sorted((z1, z2))

    size_x = max_x - min_x + 1
    size_y = max_y - min_y + 1
    size_z = max_z - min_z + 1

    dest_max_x = dest_x + size_x - 1
    dest_max_y = dest_y + size_y - 1
    dest_max_z = dest_z + size_z - 1

    overlaps = (
        _ranges_overlap(min_x, max_x, dest_x, dest_max_x)
        and _ranges_overlap(min_y, max_y, dest_y, dest_max_y)
        and _ranges_overlap(min_z, max_z, dest_z, dest_max_z)
    )
    if overlaps and clone_mode == "normal":
        raise ValueError("source and destination overlap")

    chunk_cache: dict[tuple[int, int], list[list[list[int]]]] = {}
    dirty_chunks: set[tuple[int, int]] = set()
    source_snapshot: list[tuple[int, int, int, int]] = []
    for offset_y in range(size_y):
        src_y = min_y + offset_y
        if src_y < MIN_Y or src_y > MAX_Y:
            continue
        for offset_z in range(size_z):
            src_z = min_z + offset_z
            for offset_x in range(size_x):
                src_x = min_x + offset_x
                block_state = _get_block_from_cache(server, chunk_cache, src_x, src_y, src_z)
                if block_state is None:
                    block_state = AIR
                source_snapshot.append((offset_x, offset_y, offset_z, int(block_state)))

    changed_positions = 0
    written_destinations: set[tuple[int, int, int]] = set()
    changed_blocks: list[tuple[int, int, int, int]] = []

    for offset_x, offset_y, offset_z, block_state in source_snapshot:
        if mask_mode == "masked" and block_state == AIR:
            continue
        if mask_mode == "filtered" and block_state != int(filter_block_state or AIR):
            continue

        target_x = dest_x + offset_x
        target_y = dest_y + offset_y
        target_z = dest_z + offset_z
        if _set_block_in_cache(server, chunk_cache, dirty_chunks, target_x, target_y, target_z, block_state):
            changed_positions += 1
            written_destinations.add((target_x, target_y, target_z))
            changed_blocks.append((target_x, target_y, target_z, int(block_state)))

    if clone_mode == "move":
        for offset_x, offset_y, offset_z, block_state in source_snapshot:
            if mask_mode == "masked" and block_state == AIR:
                continue
            if mask_mode == "filtered" and block_state != int(filter_block_state or AIR):
                continue

            source_x = min_x + offset_x
            source_y = min_y + offset_y
            source_z = min_z + offset_z
            if (source_x, source_y, source_z) in written_destinations:
                continue
            if _set_block_in_cache(server, chunk_cache, dirty_chunks, source_x, source_y, source_z, AIR):
                changed_positions += 1
                changed_blocks.append((source_x, source_y, source_z, AIR))

    _save_dirty_chunks(server, chunk_cache, dirty_chunks)
    return changed_positions, dirty_chunks, changed_blocks
