# ============================================================
# PyMC - Fluid System
# Water and lava flow simulation
# Minecraft 1.21.1
# ============================================================

"""
Fluid system handling water and lava flow simulation.

Design:
  - Tick-based flow updates processed in the game loop
  - Source blocks create new flowing blocks
  - Flowing blocks spread horizontally and fall down
  - Water flows 7 blocks horizontally in overworld
  - Lava flows 3 blocks horizontally in overworld, 7 in nether
  - Water and lava interaction: create stone/cobblestone/obsidian
  - Flowing blocks without source above dry up over time

Fluid levels:
  - 0: Source block (infinite)
  - 1-7: Flowing (1 = furthest from source, 7 = closest)
  - For lava, levels are 0 (source) and 1-3 (flowing)

Dimension-aware:
  - Overworld: water flows 7, lava flows 3
  - Nether: water evaporates, lava flows 7
  - End: water flows 7, lava flows 3
"""

import logging
from collections import deque
from typing import Optional

from .blocks import (
    AIR, WATER, LAVA, STONE, COBBLESTONE, OBSIDIAN,
    BEDROCK,
)
from .chunk_io import STATE_ID_TO_BLOCK, BLOCK_KEY_TO_STATE_ID

logger = logging.getLogger("PyMC.流体")

# --------------------------------------------------
# Constants
# --------------------------------------------------

# Flow speeds in game ticks
WATER_FLOW_SPEED = 5      # 4 updates/second
LAVA_FLOW_SPEED = 30      # ~1.5 updates/second in overworld
LAVA_FLOW_SPEED_NETHER = 10  # Faster in nether

# Maximum horizontal flow distance
WATER_MAX_DISTANCE = 7
LAVA_MAX_DISTANCE = 3
LAVA_MAX_DISTANCE_NETHER = 7

# Maximum fluid levels
WATER_MAX_LEVEL = 7
LAVA_MAX_LEVEL = 3

# Drying up speed (ticks)
WATER_DRY_SPEED = 5
LAVA_DRY_SPEED = 30

# Minimum Y coordinate
MIN_Y = -64
MAX_Y = 319

# Blocks that water can flow through (non-solid, replaceable)
_WATER_PASSABLE = {
    "minecraft:air", "minecraft:water", "minecraft:lava",
    "minecraft:short_grass", "minecraft:tall_grass", "minecraft:fern",
    "minecraft:dandelion", "minecraft:poppy", "minecraft:blue_orchid",
    "minecraft:allium", "minecraft:azure_bluet", "minecraft:red_tulip",
    "minecraft:orange_tulip", "minecraft:white_tulip", "minecraft:pink_tulip",
    "minecraft:oxeye_daisy", "minecraft:cornflower", "minecraft:lily_of_the_valley",
    "minecraft:torch", "minecraft:sugar_cane", "minecraft:seagrass",
    "minecraft:tall_seagrass", "minecraft:kelp",
}

# Blocks that lava can flow through
_LAVA_PASSABLE = {
    "minecraft:air", "minecraft:water", "minecraft:lava",
    "minecraft:snow", "minecraft:short_grass", "minecraft:tall_grass",
    "minecraft:fern", "minecraft:dandelion", "minecraft:poppy",
    "minecraft:torch", "minecraft:sugar_cane",
}


# --------------------------------------------------
# Fluid Level Helpers
# --------------------------------------------------

def _get_fluid_level(state_id: int) -> int:
    """
    Get the fluid level from a block state ID.
    Returns 0 for source, 1-7 for flowing, -1 for no fluid.
    """
    block_name, props = STATE_ID_TO_BLOCK.get(state_id, ("minecraft:air", {}))

    if block_name == "minecraft:water":
        level = int(props.get("level", "0"))
        return level
    elif block_name == "minecraft:lava":
        level = int(props.get("level", "0"))
        return level

    return -1


def _is_water(state_id: int) -> bool:
    """Check if a block state is any water."""
    block_name, _ = STATE_ID_TO_BLOCK.get(state_id, ("minecraft:air", {}))
    return block_name == "minecraft:water"


def _is_lava(state_id: int) -> bool:
    """Check if a block state is any lava."""
    block_name, _ = STATE_ID_TO_BLOCK.get(state_id, ("minecraft:air", {}))
    return block_name == "minecraft:lava"


def _is_fluid(state_id: int) -> bool:
    """Check if a block state is any fluid."""
    return _is_water(state_id) or _is_lava(state_id)


def _is_air_or_fluid_passable(state_id: int | None, fluid_type: str = "water") -> bool:
    """Check if a block is air or can be replaced by fluid."""
    if state_id is None or state_id == AIR:
        return True

    if fluid_type == "water" and _is_water(state_id):
        return True
    if fluid_type == "lava" and _is_lava(state_id):
        return True

    # Check passable blocks
    block_name, _ = STATE_ID_TO_BLOCK.get(state_id, ("minecraft:air", {}))
    if fluid_type == "water":
        return block_name in _WATER_PASSABLE
    else:
        return block_name in _LAVA_PASSABLE


def _get_water_state(level: int, falling: bool = False) -> int:
    """Get the water block state ID for a given level."""
    if falling:
        level = 8
    if level == 0:
        return WATER  # Source
    # Look up flowing water state
    props = {"level": str(level)}
    key = ("minecraft:water", tuple(sorted(props.items())))
    state_id = BLOCK_KEY_TO_STATE_ID.get(key)
    if state_id is not None:
        return state_id
    # Fallback: return source if we can't find the state
    return WATER


def _get_lava_state(level: int, falling: bool = False) -> int:
    """Get the lava block state ID for a given level."""
    if falling:
        level = 8
    if level == 0:
        return LAVA  # Source
    props = {"level": str(level)}
    key = ("minecraft:lava", tuple(sorted(props.items())))
    state_id = BLOCK_KEY_TO_STATE_ID.get(key)
    if state_id is not None:
        return state_id
    return LAVA


def _is_solid(state_id: int | None) -> bool:
    """Check if a block state is solid (fluids can't flow through)."""
    if state_id is None or state_id == AIR:
        return False
    block_name, _ = STATE_ID_TO_BLOCK.get(state_id, ("minecraft:air", {}))
    # Fluids themselves are not solid
    if block_name in ("minecraft:water", "minecraft:lava"):
        return False
    # Most blocks are solid
    non_solid = {
        "minecraft:air", "minecraft:short_grass", "minecraft:tall_grass",
        "minecraft:fern", "minecraft:dandelion", "minecraft:poppy",
        "minecraft:torch", "minecraft:sugar_cane", "minecraft:seagrass",
        "minecraft:sign", "minecraft:oak_sign", "minecraft:wall_sign",
    }
    return block_name not in non_solid


# --------------------------------------------------
# Fluid System
# --------------------------------------------------

class FluidSystem:
    """
    Water and lava flow simulation engine.

    Processes fluid updates every tick:
    1. Check pending flow updates
    2. Source blocks create new flowing blocks
    3. Flowing blocks spread horizontally and fall down
    4. Water meets lava -> stone/cobblestone/obsidian
    5. Flowing blocks without source dry up
    """

    def __init__(self, server):
        self.server = server
        # (x, y, z, scheduled_tick, fluid_type) -> fluid_type
        self.pending_flows: list[tuple[int, int, int, int, str]] = []
        # Track known fluid sources for efficient updates
        self.fluid_sources: set[tuple[int, int, int]] = set()
        self.tick_count: int = 0

        # Dimension context (affects flow speeds and interactions)
        self.dimension: str = "overworld"  # "overworld", "the_nether", "the_end"

    def on_fluid_place(self, x: int, y: int, z: int, fluid_type: str):
        """
        Called when fluid is placed (bucket use, world generation, etc.).
        Schedules initial flow updates.
        """
        if fluid_type == "water":
            speed = WATER_FLOW_SPEED
        else:
            speed = LAVA_FLOW_SPEED_NETHER if self.dimension == "the_nether" else LAVA_FLOW_SPEED

        self.pending_flows.append((x, y, z, self.tick_count + speed, fluid_type))
        self.fluid_sources.add((x, y, z))

    def on_fluid_remove(self, x: int, y: int, z: int):
        """Called when fluid is removed."""
        self.fluid_sources.discard((x, y, z))
        # Schedule a check for neighboring fluids that may dry up
        for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]:
            nx, ny, nz = x + dx, y + dy, z + dz
            block = self.server.get_block_at(nx, ny, nz)
            if block is not None and _is_fluid(block):
                n_type = "water" if _is_water(block) else "lava"
                speed = WATER_FLOW_SPEED if n_type == "water" else (LAVA_FLOW_SPEED_NETHER if self.dimension == "the_nether" else LAVA_FLOW_SPEED)
                self.pending_flows.append((nx, ny, nz, self.tick_count + speed, n_type))

    def tick(self):
        """Process fluid flow updates. Called every game tick."""
        self.tick_count += 1

        if not self.pending_flows:
            return

        # Process flows that are due
        remaining = []
        processed = set()

        for entry in self.pending_flows:
            x, y, z, scheduled_tick, fluid_type = entry

            if scheduled_tick > self.tick_count:
                remaining.append(entry)
                continue

            # Avoid processing the same position multiple times per tick
            pos_key = (x, y, z)
            if pos_key in processed:
                continue
            processed.add(pos_key)

            # Get current block at position
            current = self.server.get_block_at(x, y, z)
            if current is None or current == AIR:
                # Fluid was removed, skip
                continue

            is_water = _is_water(current)
            is_lava = _is_lava(current)

            if not is_water and not is_lava:
                # Not a fluid anymore, skip
                continue

            actual_type = "water" if is_water else "lava"
            self._process_flow(x, y, z, current, actual_type, remaining)

        self.pending_flows = remaining

    def _process_flow(self, x: int, y: int, z: int, current_state: int,
                       fluid_type: str, remaining: list):
        """Process flow for a single fluid block."""
        from world.editing import set_world_block
        from handlers.play.blocks import _broadcast_block_change

        level = _get_fluid_level(current_state)
        is_source = (level == 0)
        speed = WATER_FLOW_SPEED if fluid_type == "water" else (LAVA_FLOW_SPEED_NETHER if self.dimension == "the_nether" else LAVA_FLOW_SPEED)
        max_dist = WATER_MAX_DISTANCE if fluid_type == "water" else (LAVA_MAX_DISTANCE_NETHER if self.dimension == "the_nether" else LAVA_MAX_DISTANCE)

        # 1. Try flowing down first
        if y - 1 >= MIN_Y:
            below = self.server.get_block_at(x, y - 1, z)
            if below is not None:
                # Check for water-lava interaction
                if fluid_type == "water" and _is_lava(below):
                    lava_level = _get_fluid_level(below)
                    if lava_level == 0:
                        # Lava source -> obsidian
                        set_world_block(self.server, x, y - 1, z, OBSIDIAN)
                        self._notify_fluid_update(x, y - 1, z, OBSIDIAN)
                    else:
                        # Flowing lava -> cobblestone
                        set_world_block(self.server, x, y - 1, z, COBBLESTONE)
                        self._notify_fluid_update(x, y - 1, z, COBBLESTONE)
                elif fluid_type == "lava" and _is_water(below):
                    lava_level = _get_fluid_level(current_state)
                    if lava_level == 0:
                        set_world_block(self.server, x, y - 1, z, OBSIDIAN)
                        self._notify_fluid_update(x, y - 1, z, OBSIDIAN)
                    else:
                        set_world_block(self.server, x, y - 1, z, STONE)
                        self._notify_fluid_update(x, y - 1, z, STONE)
                elif _is_air_or_fluid_passable(below, fluid_type) and not _is_fluid(below):
                    # Downward flow is a falling state, never a new source.
                    if fluid_type == "water":
                        new_state = _get_water_state(0, falling=True)
                    else:
                        new_state = _get_lava_state(0, falling=True)

                    set_world_block(self.server, x, y - 1, z, new_state)
                    self._notify_fluid_update(x, y - 1, z, new_state)
                    remaining.append((x, y - 1, z, self.tick_count + speed, fluid_type))
                elif _is_fluid(below) and below != current_state:
                    # Different fluid below - schedule check
                    pass

        # 2. Horizontal flow (only if can't flow down OR is source)
        if level < max_dist or is_source:
            new_level = 1 if is_source else level + 1

            for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nx, nz = x + dx, z + dz
                neighbor = self.server.get_block_at(nx, y, nz)

                if neighbor is None:
                    continue

                # Check for water-lava interaction
                if fluid_type == "water" and _is_lava(neighbor):
                    lava_level = _get_fluid_level(neighbor)
                    if lava_level == 0:
                        # Lava source -> obsidian
                        set_world_block(self.server, nx, y, nz, OBSIDIAN)
                        self._notify_fluid_update(nx, y, nz, OBSIDIAN)
                    else:
                        # Flowing lava -> cobblestone
                        set_world_block(self.server, nx, y, nz, COBBLESTONE)
                        self._notify_fluid_update(nx, y, nz, COBBLESTONE)
                    continue

                if fluid_type == "lava" and _is_water(neighbor):
                    lava_level = _get_fluid_level(current_state)
                    if lava_level == 0:
                        set_world_block(self.server, nx, y, nz, OBSIDIAN)
                        self._notify_fluid_update(nx, y, nz, OBSIDIAN)
                    else:
                        set_world_block(self.server, nx, y, nz, STONE)
                        self._notify_fluid_update(nx, y, nz, STONE)
                    continue

                # Flow into air/passable blocks
                if _is_air_or_fluid_passable(neighbor, fluid_type):
                    # Check if there's already a same-type fluid with lower level
                    if _is_fluid(neighbor):
                        n_level = _get_fluid_level(neighbor)
                        n_type = "water" if _is_water(neighbor) else "lava"
                        if n_type == fluid_type and n_level <= new_level:
                            continue  # Already have equal or better flow

                    if fluid_type == "water":
                        new_state = _get_water_state(new_level)
                    else:
                        new_state = _get_lava_state(new_level)

                    set_world_block(self.server, nx, y, nz, new_state)
                    self._notify_fluid_update(nx, y, nz, new_state)
                    remaining.append((nx, y, nz, self.tick_count + speed, fluid_type))

        # 3. Check if this flowing block should dry up
        # A flowing block without a source feeding it should eventually dry up
        if not is_source:
            has_source_neighbor = False
            for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]:
                nx, ny, nz = x + dx, y + dy, z + dz
                if ny < MIN_Y or ny > MAX_Y:
                    continue
                neighbor = self.server.get_block_at(nx, ny, nz)
                if neighbor is not None:
                    if fluid_type == "water" and _is_water(neighbor):
                        n_level = _get_fluid_level(neighbor)
                        if n_level < level:
                            has_source_neighbor = True
                            break
                    elif fluid_type == "lava" and _is_lava(neighbor):
                        n_level = _get_fluid_level(neighbor)
                        if n_level < level:
                            has_source_neighbor = True
                            break

            if not has_source_neighbor:
                # This flowing block has no source feeding it - dry up
                set_world_block(self.server, x, y, z, AIR)
                self._notify_fluid_update(x, y, z, AIR)

                # Schedule neighbors to re-check
                for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, nz = x + dx, z + dz
                    neighbor = self.server.get_block_at(nx, y, nz)
                    if neighbor is not None and _is_fluid(neighbor):
                        n_type = "water" if _is_water(neighbor) else "lava"
                        n_speed = WATER_FLOW_SPEED if n_type == "water" else (LAVA_FLOW_SPEED_NETHER if self.dimension == "the_nether" else LAVA_FLOW_SPEED)
                        remaining.append((nx, y, nz, self.tick_count + n_speed, n_type))

    def _notify_fluid_update(self, x: int, y: int, z: int, new_state: int):
        """Record a fluid update for broadcasting."""
        self.server._fluid_updates = getattr(self.server, '_fluid_updates', [])
        self.server._fluid_updates.append((x, y, z, new_state))

    def get_fluid_level(self, x: int, y: int, z: int) -> int:
        """
        Get fluid level at position.
        Returns 0 for source, 1-7 for flowing, -1 for no fluid.
        """
        block = self.server.get_block_at(x, y, z)
        if block is None:
            return -1
        return _get_fluid_level(block)

    def is_fluid_source(self, x: int, y: int, z: int) -> bool:
        """Check if the fluid at a position is a source block."""
        level = self.get_fluid_level(x, y, z)
        return level == 0

    def scan_chunk_for_fluids(self, chunk_x: int, chunk_z: int,
                                chunk_blocks) -> list[tuple[int, int, int, str]]:
        """
        Scan a newly loaded chunk for fluid blocks.
        Returns list of (x, y, z, fluid_type) for all fluid blocks found.
        """
        fluids = []
        for local_y in range(len(chunk_blocks)):
            for local_z in range(16):
                for local_x in range(16):
                    state_id = chunk_blocks[local_y][local_z][local_x]
                    if _is_water(state_id):
                        world_x = chunk_x * 16 + local_x
                        world_y = local_y - 64  # Adjust for MIN_Y
                        world_z = chunk_z * 16 + local_z
                        fluids.append((world_x, world_y, world_z, "water"))
                    elif _is_lava(state_id):
                        world_x = chunk_x * 16 + local_x
                        world_y = local_y - 64
                        world_z = chunk_z * 16 + local_z
                        fluids.append((world_x, world_y, world_z, "lava"))
        return fluids

    def count_fluid_blocks(self) -> dict[str, int]:
        """Count total tracked fluid blocks by type."""
        water_count = 0
        lava_count = 0
        for x, y, z in self.fluid_sources:
            block = self.server.get_block_at(x, y, z)
            if block is not None:
                if _is_water(block):
                    water_count += 1
                elif _is_lava(block):
                    lava_count += 1
        return {"water": water_count, "lava": lava_count}

    def get_pending_count(self) -> int:
        """Get number of pending flow updates."""
        return len(self.pending_flows)
