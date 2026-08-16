# ============================================================
# PyMC - Redstone Engine
# Tick-based redstone simulation for Minecraft 1.21.1
# ============================================================

"""
Redstone simulation engine that handles all redstone components
including wires, torches, repeaters, comparators, pistons,
power sources, and mechanical block activations.

Design:
  - Runs every 2 game ticks (0.1s = 1 redstone tick)
  - Uses dirty-flag system for efficiency
  - BFS-based signal propagation from power sources
  - Scheduled updates for delayed components (repeaters, torches)
  - Integrates with the world block system via server.get_block_at / set_world_block
  - Optional C++ native acceleration via NativeCore
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .chunk_io import BLOCK_KEY_TO_STATE_ID, STATE_ID_TO_BLOCK, BLOCK_NAME_TO_DEFAULT_STATE
from .blocks import AIR

logger = logging.getLogger("PyMC.Redstone")

# --------------------------------------------------
# Direction helpers
# --------------------------------------------------

# Facing directions used by many redstone components
FACING_DX = {
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
}

# Reverse facing
FACING_OPPOSITE = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}

# 6 cardinal neighbors
SIX_DIRS = [(0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0)]

# 4 horizontal neighbors
HORIZONTAL_DIRS = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0)]

# Button durations in redstone ticks (1 redstone tick = 2 game ticks)
BUTTON_DURATIONS = {
    "stone": 10,                # 10 redstone ticks (1s)
    "polished_blackstone": 10,
}
WOOD_BUTTON_DURATION = 15  # 15 redstone ticks (1.5s) for all wood buttons

# Torches burn out after toggling this many times within the burnout window
TORCH_BURNOUT_THRESHOLD = 8
TORCH_BURNOUT_DURATION = 160  # 160 redstone ticks (8 seconds) burnout

# World constants
MIN_Y = -64
MAX_Y = 319

# Piston push limit
PISTON_PUSH_LIMIT = 12


# --------------------------------------------------
# Block name classification
# --------------------------------------------------

def _get_block_name(block_state_id: int) -> str:
    """Get the minecraft block name from a block state ID."""
    if block_state_id in STATE_ID_TO_BLOCK:
        return STATE_ID_TO_BLOCK[block_state_id][0]
    return ""


def _get_block_props(block_state_id: int) -> dict[str, str]:
    """Get block state properties from a block state ID."""
    if block_state_id in STATE_ID_TO_BLOCK:
        return STATE_ID_TO_BLOCK[block_state_id][1]
    return {}


def resolve_state_id(block_name: str, **properties) -> int:
    """Resolve a block name + properties to a block state ID.

    Returns the default state ID if the exact combination is not found.
    """
    key = (block_name, tuple(sorted(properties.items())))
    if key in BLOCK_KEY_TO_STATE_ID:
        return BLOCK_KEY_TO_STATE_ID[key]
    # Fallback: try default state
    return BLOCK_NAME_TO_DEFAULT_STATE.get(block_name, 0)


# --------------------------------------------------
# Component classification sets
# --------------------------------------------------

# Blocks that are redstone power sources (tracked by the engine)
REDSTONE_POWER_SOURCES = {
    "minecraft:lever",
    "minecraft:stone_button", "minecraft:oak_button", "minecraft:spruce_button",
    "minecraft:birch_button", "minecraft:jungle_button", "minecraft:acacia_button",
    "minecraft:cherry_button", "minecraft:dark_oak_button", "minecraft:mangrove_button",
    "minecraft:bamboo_button", "minecraft:crimson_button", "minecraft:warped_button",
    "minecraft:polished_blackstone_button",
    "minecraft:stone_pressure_plate", "minecraft:oak_pressure_plate",
    "minecraft:spruce_pressure_plate", "minecraft:birch_pressure_plate",
    "minecraft:jungle_pressure_plate", "minecraft:acacia_pressure_plate",
    "minecraft:cherry_pressure_plate", "minecraft:dark_oak_pressure_plate",
    "minecraft:mangrove_pressure_plate", "minecraft:bamboo_pressure_plate",
    "minecraft:crimson_pressure_plate", "minecraft:warped_pressure_plate",
    "minecraft:polished_blackstone_pressure_plate",
    "minecraft:light_weighted_pressure_plate", "minecraft:heavy_weighted_pressure_plate",
    "minecraft:redstone_block",
    "minecraft:daylight_detector",
    "minecraft:tripwire_hook",
    "minecraft:target",
    "minecraft:detector_rail",
}

REDSTONE_WIRE_NAMES = {"minecraft:redstone_wire"}

REDSTONE_TORCH_NAMES = {"minecraft:redstone_torch", "minecraft:redstone_wall_torch"}

REDSTONE_REPEATER_NAMES = {"minecraft:repeater"}

REDSTONE_COMPARATOR_NAMES = {"minecraft:comparator"}

REDSTONE_OBSERVER_NAMES = {"minecraft:observer"}

PISTON_NAMES = {"minecraft:piston", "minecraft:sticky_piston"}

# Container blocks that comparators can read
CONTAINER_NAMES = {
    "minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel",
    "minecraft:hopper", "minecraft:dropper", "minecraft:dispenser",
    "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
    "minecraft:brewing_stand", "minecraft:shulker_box",
    "minecraft:white_shulker_box", "minecraft:orange_shulker_box",
    "minecraft:magenta_shulker_box", "minecraft:light_blue_shulker_box",
    "minecraft:yellow_shulker_box", "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box", "minecraft:gray_shulker_box",
    "minecraft:light_gray_shulker_box", "minecraft:cyan_shulker_box",
    "minecraft:purple_shulker_box", "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box", "minecraft:green_shulker_box",
    "minecraft:red_shulker_box", "minecraft:black_shulker_box",
    "minecraft:ender_chest", "minecraft:lectern",
}

# Blocks that react to redstone signals
REDSTONE_ACTIVATABLE = {
    "minecraft:oak_door", "minecraft:spruce_door", "minecraft:birch_door",
    "minecraft:jungle_door", "minecraft:acacia_door", "minecraft:cherry_door",
    "minecraft:dark_oak_door", "minecraft:mangrove_door", "minecraft:bamboo_door",
    "minecraft:iron_door", "minecraft:crimson_door", "minecraft:warped_door",
    "minecraft:oak_trapdoor", "minecraft:spruce_trapdoor", "minecraft:birch_trapdoor",
    "minecraft:jungle_trapdoor", "minecraft:acacia_trapdoor", "minecraft:cherry_trapdoor",
    "minecraft:dark_oak_trapdoor", "minecraft:mangrove_trapdoor", "minecraft:bamboo_trapdoor",
    "minecraft:iron_trapdoor", "minecraft:crimson_trapdoor", "minecraft:warped_trapdoor",
    "minecraft:oak_fence_gate", "minecraft:spruce_fence_gate", "minecraft:birch_fence_gate",
    "minecraft:jungle_fence_gate", "minecraft:acacia_fence_gate", "minecraft:cherry_fence_gate",
    "minecraft:dark_oak_fence_gate", "minecraft:mangrove_fence_gate", "minecraft:bamboo_fence_gate",
    "minecraft:crimson_fence_gate", "minecraft:warped_fence_gate",
    "minecraft:redstone_lamp",
    "minecraft:tnt",
    "minecraft:note_block",
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:hopper",
    "minecraft:powered_rail",
    "minecraft:activator_rail",
}

ALL_REDSTONE_NAMES = (
    REDSTONE_POWER_SOURCES | REDSTONE_WIRE_NAMES | REDSTONE_TORCH_NAMES |
    REDSTONE_REPEATER_NAMES | REDSTONE_COMPARATOR_NAMES | REDSTONE_OBSERVER_NAMES |
    PISTON_NAMES | REDSTONE_ACTIVATABLE
)


def is_redstone_block(block_name: str) -> bool:
    """Check if a block name is any kind of redstone component."""
    return block_name in ALL_REDSTONE_NAMES


def _is_wood_button(name: str) -> bool:
    return name.endswith("_button") and "stone" not in name


def _is_stone_button(name: str) -> bool:
    return name in {"minecraft:stone_button", "minecraft:polished_blackstone_button"}


# --------------------------------------------------
# Non-solid block set for wire connection logic
# --------------------------------------------------

_NON_SOLID_BLOCKS = {
    "minecraft:air", "minecraft:redstone_wire", "minecraft:redstone_torch",
    "minecraft:redstone_wall_torch", "minecraft:torch", "minecraft:wall_torch",
    "minecraft:tripwire", "minecraft:tripwire_hook",
    "minecraft:oak_sign", "minecraft:spruce_sign", "minecraft:birch_sign",
    "minecraft:jungle_sign", "minecraft:acacia_sign", "minecraft:cherry_sign",
    "minecraft:dark_oak_sign", "minecraft:mangrove_sign", "minecraft:bamboo_sign",
    "minecraft:crimson_sign", "minecraft:warped_sign",
    "minecraft:oak_hanging_sign", "minecraft:spruce_hanging_sign",
    "minecraft:glass_pane", "minecraft:white_stained_glass_pane",
    "minecraft:iron_bars",
    "minecraft:tall_grass", "minecraft:fern",
    "minecraft:dead_bush", "minecraft:vine", "minecraft:glow_lichen",
    "minecraft:sugar_cane", "minecraft:wheat",
    "minecraft:poppy", "minecraft:dandelion",
    "minecraft:flower_pot",
    "minecraft:ladder",
    "minecraft:snow",
}


# --------------------------------------------------
# Component data structures
# --------------------------------------------------

@dataclass
class RedstoneComponent:
    """Tracks the state of a single redstone component in the world."""
    pos: tuple[int, int, int]
    block_name: str
    power: int = 0            # Current power output (0-15)
    prev_power: int = 0       # Previous tick power (for edge detection)
    facing: str = "north"     # Facing direction
    powered: bool = False     # Is this component currently powered/active
    prev_powered: bool = False
    # Repeater-specific
    delay: int = 1            # Repeater delay (1-4 redstone ticks)
    locked: bool = False      # Is this repeater locked
    # Comparator-specific
    mode: str = "compare"     # Comparator mode: compare/subtract
    # Observer-specific
    observer_cooldown: int = 0
    # Button/pressure plate specific
    active_timer: int = 0     # Ticks remaining for temporary activation
    # Lever-specific
    lever_on: bool = False
    # Torch burnout
    torch_burnout_timer: int = 0
    torch_toggle_count: int = 0
    torch_toggle_window_start: float = 0.0
    # Tripwire hook
    attached: bool = False
    # Daylight detector
    inverted: bool = False
    # Sticky piston flag
    is_sticky: bool = False
    # Target block
    target_power: int = 0
    target_timer: int = 0
    # Piston
    extended: bool = False
    # Note block
    note: int = 0  # 0-24 pitch
    # TNT fuse (redstone ticks; 40 = 80 game ticks = 4 seconds)
    fuse_ticks: int = 0
    # Dirty flag - needs recalculation
    dirty: bool = True
    # Wire connections (computed)
    wire_connections: list[tuple[int, int, int]] = field(default_factory=list)


# --------------------------------------------------
# Scheduled update entry
# --------------------------------------------------

@dataclass
class ScheduledUpdate:
    """A scheduled redstone update to be processed at a future tick."""
    tick: int
    pos: tuple[int, int, int]
    target_powered: bool  # What state to transition to


# --------------------------------------------------
# Redstone Engine
# --------------------------------------------------

class RedstoneEngine:
    """Tick-based redstone simulation engine integrated with the world."""

    REDSTONE_TICK_RATE = 2  # 1 redstone tick = 2 game ticks

    def __init__(self, server):
        self.server = server
        # All tracked redstone components: pos -> RedstoneComponent
        self.components: dict[tuple[int, int, int], RedstoneComponent] = {}
        # Power levels at each block position (0-15)
        self.power_levels: dict[tuple[int, int, int], int] = {}
        # Strong power levels (from power sources strongly powering blocks)
        self.strong_power: dict[tuple[int, int, int], int] = {}
        # Scheduled updates
        self.scheduled_updates: list[ScheduledUpdate] = []
        # Current redstone tick counter
        self.current_tick: int = 0
        # Positions that need recalculation this tick
        self.dirty_positions: set[tuple[int, int, int]] = set()
        # Positions whose block state needs updating for clients
        self.visual_updates: list[tuple[int, int, int, int]] = []  # (x, y, z, new_state_id)
        # Async effects emitted by the sync tick (explosions, sounds, item drops)
        self.pending_effects: list[tuple[str, dict]] = []
        # Native engine reference (optional C++ acceleration)
        self._native_engine = None
        # Performance tracking
        self._tick_time_ms: float = 0.0
        self._component_count_at_last_log: int = 0

        # Try to initialize native engine
        self._init_native_engine()

    def _init_native_engine(self):
        """Attempt to initialize the C++ native redstone engine."""
        try:
            from native import NativeCore
            core = NativeCore()
            if core.is_available():
                self._native_engine = core.get_redstone_engine()
                if self._native_engine:
                    logger.info("Redstone: C++ native engine initialized successfully")
                else:
                    logger.info("Redstone: Native core available but redstone engine not ready, using Python fallback")
            else:
                logger.info("Redstone: Native core not available, using Python implementation")
        except Exception as e:
            logger.debug(f"Redstone: Native engine init failed ({e}), using Python fallback")
            self._native_engine = None

    # --------------------------------------------------
    # Component registration
    # --------------------------------------------------

    def register_component(self, x: int, y: int, z: int, block_state_id: int):
        """Register a redstone component when a block is placed."""
        pos = (x, y, z)
        name = _get_block_name(block_state_id)
        if not name or not is_redstone_block(name):
            return

        props = _get_block_props(block_state_id)
        comp = RedstoneComponent(pos=pos, block_name=name)

        # Extract facing from properties
        comp.facing = props.get("facing", props.get("face", "north"))
        if comp.facing not in ("north", "south", "east", "west", "up", "down"):
            comp.facing = "north"

        # Component-specific initialization
        if name in REDSTONE_WIRE_NAMES:
            comp.power = int(props.get("power", "0"))
        elif name in REDSTONE_TORCH_NAMES:
            comp.powered = props.get("lit", "true") == "true"
            comp.prev_powered = comp.powered
            comp.power = 15 if comp.powered else 0
        elif name in REDSTONE_REPEATER_NAMES:
            comp.delay = int(props.get("delay", "1"))
            comp.powered = props.get("powered", "false") == "true"
            comp.locked = props.get("locked", "false") == "true"
            comp.power = 15 if comp.powered else 0
        elif name in REDSTONE_COMPARATOR_NAMES:
            comp.mode = props.get("mode", "compare")
            comp.powered = props.get("powered", "false") == "true"
            comp.power = int(props.get("output_power", "0")) if comp.powered else 0
        elif name in REDSTONE_OBSERVER_NAMES:
            comp.powered = props.get("powered", "false") == "true"
            comp.power = 15 if comp.powered else 0
        elif name == "minecraft:lever":
            comp.lever_on = props.get("powered", "false") == "true"
            comp.power = 15 if comp.lever_on else 0
        elif name.endswith("_button"):
            comp.powered = props.get("powered", "false") == "true"
            if comp.powered:
                if _is_wood_button(name):
                    comp.active_timer = WOOD_BUTTON_DURATION
                else:
                    comp.active_timer = BUTTON_DURATIONS.get(
                        name.replace("minecraft:", "").replace("_button", ""), 10
                    )
        elif name.endswith("_pressure_plate"):
            if name in ("minecraft:light_weighted_pressure_plate",
                        "minecraft:heavy_weighted_pressure_plate"):
                comp.power = int(props.get("power", "0"))
            else:
                comp.powered = props.get("powered", "false") == "true"
                comp.power = 15 if comp.powered else 0
        elif name == "minecraft:redstone_block":
            comp.power = 15
        elif name == "minecraft:daylight_detector":
            comp.inverted = props.get("inverted", "false") == "true"
            comp.power = int(props.get("power", "0"))
        elif name == "minecraft:target":
            comp.power = int(props.get("power", "0"))
        elif name == "minecraft:tripwire_hook":
            comp.powered = props.get("powered", "false") == "true"
            comp.attached = props.get("attached", "false") == "true"
            comp.power = 15 if comp.powered else 0
        elif name == "minecraft:detector_rail":
            comp.powered = props.get("powered", "false") == "true"
            comp.power = 15 if comp.powered else 0
        elif name in PISTON_NAMES:
            comp.is_sticky = name == "minecraft:sticky_piston"
            comp.extended = props.get("extended", "false") == "true"
        elif name == "minecraft:redstone_lamp":
            comp.powered = props.get("lit", "false") == "true"
        elif name == "minecraft:note_block":
            comp.note = int(props.get("note", "0"))
            comp.powered = props.get("powered", "false") == "true"
        elif name == "minecraft:tnt":
            comp.powered = props.get("unstable", "false") == "true"
        elif name in REDSTONE_ACTIVATABLE:
            comp.powered = props.get("powered", "false") == "true" or props.get("open", "false") == "true"

        self.components[pos] = comp
        self.dirty_positions.add(pos)
        # Mark neighbors as dirty since a new component was added
        self._mark_neighbors_dirty(x, y, z)

        # Register with native engine if available
        if self._native_engine:
            try:
                component_type = self._name_to_native_type(name)
                if component_type is not None:
                    facing_id = self._facing_to_native(comp.facing)
                    self._native_engine.add_component(x, y, z, component_type, facing_id)
            except Exception as e:
                logger.debug(f"Native engine add_component failed: {e}")

    def unregister_component(self, x: int, y: int, z: int):
        """Unregister a redstone component when a block is broken."""
        pos = (x, y, z)
        if pos in self.components:
            del self.components[pos]
        if pos in self.power_levels:
            del self.power_levels[pos]
        if pos in self.strong_power:
            del self.strong_power[pos]
        # Mark neighbors as dirty
        self._mark_neighbors_dirty(x, y, z)

        # Unregister from native engine if available
        if self._native_engine:
            try:
                self._native_engine.remove_component(x, y, z)
            except Exception as e:
                logger.debug(f"Native engine remove_component failed: {e}")

    def _mark_neighbors_dirty(self, x: int, y: int, z: int):
        """Mark all neighboring positions as needing recalculation."""
        for dx, dy, dz in SIX_DIRS:
            npos = (x + dx, y + dy, z + dz)
            if npos in self.components:
                self.components[npos].dirty = True
                self.dirty_positions.add(npos)
            # Also mark 2-block radius for wire connections
            for dx2, dy2, dz2 in SIX_DIRS:
                npos2 = (x + dx + dx2, y + dy + dy2, z + dz + dz2)
                if npos2 in self.components:
                    self.components[npos2].dirty = True
                    self.dirty_positions.add(npos2)

    # --------------------------------------------------
    # Native engine helpers
    # --------------------------------------------------

    def _name_to_native_type(self, name: str) -> int | None:
        """Convert a block name to a native component type ID."""
        from native import (COMPONENT_WIRE, COMPONENT_TORCH, COMPONENT_REPEATER,
                           COMPONENT_COMPARATOR, COMPONENT_PISTON, COMPONENT_STICKY_PISTON,
                           COMPONENT_OBSERVER, COMPONENT_LEVER, COMPONENT_BUTTON,
                           COMPONENT_PRESSURE_PLATE, COMPONENT_WEIGHTED_PRESSURE_PLATE)
        mapping = {
            "minecraft:redstone_wire": COMPONENT_WIRE,
            "minecraft:redstone_torch": COMPONENT_TORCH,
            "minecraft:redstone_wall_torch": COMPONENT_TORCH,
            "minecraft:repeater": COMPONENT_REPEATER,
            "minecraft:comparator": COMPONENT_COMPARATOR,
            "minecraft:piston": COMPONENT_PISTON,
            "minecraft:sticky_piston": COMPONENT_STICKY_PISTON,
            "minecraft:observer": COMPONENT_OBSERVER,
            "minecraft:lever": COMPONENT_LEVER,
        }
        if name in mapping:
            return mapping[name]
        if name.endswith("_button"):
            return COMPONENT_BUTTON
        if name.endswith("_pressure_plate"):
            if name in ("minecraft:light_weighted_pressure_plate",
                        "minecraft:heavy_weighted_pressure_plate"):
                return COMPONENT_WEIGHTED_PRESSURE_PLATE
            return COMPONENT_PRESSURE_PLATE
        return None

    def _facing_to_native(self, facing: str) -> int:
        """Convert a facing string to a native facing ID."""
        from native import (FACING_DOWN, FACING_UP, FACING_NORTH,
                           FACING_SOUTH, FACING_WEST, FACING_EAST)
        mapping = {
            "down": FACING_DOWN, "up": FACING_UP,
            "north": FACING_NORTH, "south": FACING_SOUTH,
            "west": FACING_WEST, "east": FACING_EAST,
        }
        return mapping.get(facing, FACING_NORTH)

    # --------------------------------------------------
    # Block access helpers
    # --------------------------------------------------

    def _get_block_at(self, x: int, y: int, z: int) -> int:
        """Get block state ID at a world position."""
        return self.server.get_block_at(x, y, z) or 0

    def _get_block_name_at(self, x: int, y: int, z: int) -> str:
        """Get block name at a world position."""
        return _get_block_name(self._get_block_at(x, y, z))

    def _set_block_state(self, x: int, y: int, z: int, block_state_id: int):
        """Set a block in the world and queue visual update."""
        from world.editing import set_world_block
        set_world_block(self.server, x, y, z, block_state_id)
        self.visual_updates.append((x, y, z, block_state_id))

    def _is_solid_block(self, block_state_id: int) -> bool:
        """Check if a block is solid (opaque cube)."""
        if block_state_id == 0:  # Air
            return False
        name = _get_block_name(block_state_id)
        return name not in _NON_SOLID_BLOCKS

    # --------------------------------------------------
    # Power calculation
    # --------------------------------------------------

    def get_power_level(self, x: int, y: int, z: int) -> int:
        """Get redstone power at a position (0-15)."""
        return self.power_levels.get((x, y, z), 0)

    def get_strong_power(self, x: int, y: int, z: int) -> int:
        """Get strong power at a position (0-15)."""
        return self.strong_power.get((x, y, z), 0)

    def is_powered(self, x: int, y: int, z: int) -> bool:
        """Check if a position has any redstone power.

        Checks both stored power levels and dynamically computed strong power
        at any position (including non-component blocks).
        """
        if self.get_power_level(x, y, z) > 0:
            return True
        if self.get_strong_power(x, y, z) > 0:
            return True
        # Also dynamically check strong power (for non-component blocks)
        if self._get_strong_power_at(x, y, z) > 0:
            return True
        # Check if any adjacent power source directly powers this block
        for dx, dy, dz in SIX_DIRS:
            nx, ny, nz = x + dx, y + dy, z + dz
            ncomp = self.components.get((nx, ny, nz))
            if ncomp and self._get_direct_power_from_neighbor(x, y, z, nx, ny, nz) > 0:
                return True
            # Check wire power at neighbor
            wire_power = self.power_levels.get((nx, ny, nz), 0)
            if wire_power > 0:
                wire_comp = self.components.get((nx, ny, nz))
                if wire_comp and wire_comp.block_name in REDSTONE_WIRE_NAMES:
                    if wire_comp.power > 0:
                        return True
        return False

    def _is_block_powered_excluding(self, x: int, y: int, z: int,
                                     exclude_pos: tuple[int, int, int]) -> bool:
        """Check if a block is powered, excluding a specific component's output.

        This is used by torches to avoid circular dependency - a torch
        should not detect its own output as powering the attached block.
        """
        # Check stored power levels
        if self.power_levels.get((x, y, z), 0) > 0:
            return True
        if self.strong_power.get((x, y, z), 0) > 0:
            return True

        # Check strong power at this position (excluding excluded component)
        strong = self._get_strong_power_at(x, y, z)
        if strong > 0:
            return True

        # Check adjacent components for direct power (excluding excluded)
        for dx, dy, dz in SIX_DIRS:
            nx, ny, nz = x + dx, y + dy, z + dz
            if (nx, ny, nz) == exclude_pos:
                continue
            ncomp = self.components.get((nx, ny, nz))
            if ncomp and self._get_direct_power_from_neighbor(x, y, z, nx, ny, nz) > 0:
                return True
            # Check wire power
            if self.power_levels.get((nx, ny, nz), 0) > 0:
                wire_comp = self.components.get((nx, ny, nz))
                if wire_comp and wire_comp.block_name in REDSTONE_WIRE_NAMES and wire_comp.power > 0:
                    return True
        return False

    def _get_direct_power_from_neighbor(self, x: int, y: int, z: int,
                                         from_x: int, from_y: int, from_z: int) -> int:
        """Get the power that a neighbor block provides to this position.

        Power sources provide power directly:
        - Lever/button/pressure plate: 15 when active
        - Redstone torch: 15 when lit
        - Repeater: 15 at its output face when powered
        - Comparator: power level at its output face
        - Redstone block: 15 to all adjacent blocks
        - Redstone wire: its power level (degraded by 1) to connected blocks
        """
        npos = (from_x, from_y, from_z)
        comp = self.components.get(npos)
        if comp is None:
            return 0

        name = comp.block_name
        power = 0

        if name == "minecraft:redstone_block":
            power = 15
        elif name == "minecraft:lever":
            if comp.lever_on:
                power = 15
        elif name.endswith("_button"):
            if comp.powered and comp.active_timer > 0:
                power = 15
        elif name.endswith("_pressure_plate"):
            if name in ("minecraft:light_weighted_pressure_plate",
                        "minecraft:heavy_weighted_pressure_plate"):
                power = comp.power
            else:
                power = 15 if comp.powered else 0
        elif name in REDSTONE_TORCH_NAMES:
            if comp.powered:
                power = 15
        elif name in REDSTONE_REPEATER_NAMES:
            # Repeater only outputs from its facing direction
            if comp.powered:
                fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
                output_pos = (from_x + fdx, from_y + fdy, from_z + fdz)
                if output_pos == (x, y, z):
                    power = 15
        elif name in REDSTONE_COMPARATOR_NAMES:
            # Comparator outputs from its facing direction
            fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
            output_pos = (from_x + fdx, from_y + fdy, from_z + fdz)
            if output_pos == (x, y, z):
                power = comp.power
        elif name in REDSTONE_OBSERVER_NAMES:
            # Observer outputs from its facing direction
            if comp.powered:
                fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
                output_pos = (from_x + fdx, from_y + fdy, from_z + fdz)
                if output_pos == (x, y, z):
                    power = 15
        elif name == "minecraft:daylight_detector":
            power = comp.power
        elif name == "minecraft:target":
            power = comp.power
        elif name == "minecraft:tripwire_hook":
            if comp.powered:
                power = 15
        elif name == "minecraft:detector_rail":
            if comp.powered:
                power = 15
        elif name in REDSTONE_WIRE_NAMES:
            # Wire provides power - 1 to connected blocks
            if comp.power > 0:
                power = max(power, comp.power - 1)

        return power

    def _get_strong_power_at(self, x: int, y: int, z: int) -> int:
        """Calculate strong power at a position.

        A block is strongly powered if a power source is directly attached
        and pointing at it. Strongly powered blocks power adjacent redstone
        wire to 15 (no degradation).

        Note: Redstone torches provide WEAK power only, not strong power.
        Only levers, buttons, pressure plates, repeaters, and comparators
        produce strong power.
        """
        max_power = 0
        for dx, dy, dz in SIX_DIRS:
            nx, ny, nz = x + dx, y + dy, z + dz
            npos = (nx, ny, nz)
            comp = self.components.get(npos)
            if comp is None:
                continue

            name = comp.block_name
            # These components strongly power the block they're attached to
            if name == "minecraft:redstone_block":
                max_power = max(max_power, 15)
            elif name == "minecraft:lever" and comp.lever_on:
                max_power = max(max_power, 15)
            elif name.endswith("_button") and comp.powered and comp.active_timer > 0:
                max_power = max(max_power, 15)
            elif name.endswith("_pressure_plate"):
                if name in ("minecraft:light_weighted_pressure_plate",
                            "minecraft:heavy_weighted_pressure_plate"):
                    pp = comp.power
                else:
                    pp = 15 if comp.powered else 0
                # Pressure plates strongly power the block below them
                if dy == 1:  # This block is below the pressure plate
                    max_power = max(max_power, pp)
            elif name in REDSTONE_REPEATER_NAMES and comp.powered:
                # Repeater strongly powers the block at its output face
                fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
                output_pos = (nx + fdx, ny + fdy, nz + fdz)
                if output_pos == (x, y, z):
                    max_power = max(max_power, 15)
            elif name in REDSTONE_COMPARATOR_NAMES and comp.power > 0:
                # Comparator strongly powers the block at its output face
                fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
                output_pos = (nx + fdx, ny + fdy, nz + fdz)
                if output_pos == (x, y, z):
                    max_power = max(max_power, comp.power)

        return max_power

    # --------------------------------------------------
    # Wire connection calculation
    # --------------------------------------------------

    def calculate_wire_connections(self, x: int, y: int, z: int) -> list[tuple[int, int, int]]:
        """Calculate which blocks a redstone wire connects to.

        Wires connect:
        - Horizontally to adjacent redstone-compatible blocks
        - Up/down one block if the adjacent block is not solid
        - To any redstone component that can provide/receive power

        Follows vanilla Minecraft wire connection rules:
        1. Wires connect to any redstone component on the same Y level
        2. Wires connect up over non-solid blocks to wires above
        3. Wires connect down through non-solid blocks below to wires below
        4. If a wire has no connections, it shows as a cross (dot)
        """
        connections = []

        for dx, dz in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, nz = x + dx, z + dz

            # Check same level
            neighbor_name = self._get_block_name_at(nx, y, nz)
            if self._can_wire_connect_to(neighbor_name):
                connections.append((nx, y, nz))
            else:
                # Check if the adjacent block is solid (wire can go up over it)
                adj_block = self._get_block_at(nx, y, nz)
                if self._is_solid_block(adj_block):
                    # Wire can connect up over the solid block
                    up_name = self._get_block_name_at(nx, y + 1, nz)
                    if up_name == "minecraft:redstone_wire":
                        connections.append((nx, y + 1, nz))

                # Check one block down (wire going down when adjacent block is not solid)
                if not self._is_solid_block(adj_block) and adj_block != 0:
                    # Non-solid, non-air block: check below
                    down_name = self._get_block_name_at(nx, y - 1, nz)
                    if down_name == "minecraft:redstone_wire":
                        connections.append((nx, y - 1, nz))

                # Also check direct up connection when adjacent is air/non-solid
                if not self._is_solid_block(adj_block):
                    up_name = self._get_block_name_at(nx, y + 1, nz)
                    if up_name == "minecraft:redstone_wire":
                        # Only connect up if the block above the wire-above is not solid
                        # (vanilla: wire can go up if no solid block blocks it)
                        above_above = self._get_block_at(nx, y + 2, nz)
                        if not self._is_solid_block(above_above):
                            connections.append((nx, y + 1, nz))

        # Also connect to any redstone component directly adjacent (6 directions)
        for dx, dy, dz in SIX_DIRS:
            npos = (x + dx, y + dy, z + dz)
            comp = self.components.get(npos)
            if comp and comp.block_name not in REDSTONE_WIRE_NAMES:
                if npos not in connections:
                    connections.append(npos)

        return connections

    def _can_wire_connect_to(self, block_name: str) -> bool:
        """Check if redstone wire can connect to a block."""
        if not block_name:
            return False
        return block_name in ALL_REDSTONE_NAMES or block_name == "minecraft:redstone_wire"

    # --------------------------------------------------
    # Signal propagation (BFS)
    # --------------------------------------------------

    def _propagate_wire_signals(self):
        """Propagate redstone signals through all wire networks using BFS.

        Uses a multi-source BFS from all power sources. Wire signal
        degrades by 1 per block from the source.

        This implements the vanilla Minecraft algorithm:
        1. For each wire, find the maximum power it receives from non-wire sources
        2. Propagate through the wire network, degrading by 1 per block
        3. A wire can only receive power if a connected source provides it
        """
        # Reset wire power levels - start fresh each tick
        wire_powers: dict[tuple[int, int, int], int] = {}

        # Queue: (position, incoming_power)
        queue: deque[tuple[tuple[int, int, int], int]] = deque()

        # Step 1: Seed the queue with all wires that receive power from non-wire sources
        for pos, comp in self.components.items():
            if comp.block_name not in REDSTONE_WIRE_NAMES:
                continue

            x, y, z = pos
            max_input = 0

            # Check power from non-wire adjacent sources
            for dx, dy, dz in SIX_DIRS:
                nx, ny, nz = x + dx, y + dy, z + dz
                ncomp = self.components.get((nx, ny, nz))
                if ncomp is None:
                    # Check if the neighbor block is strongly powered
                    strong = self._get_strong_power_at(nx, ny, nz)
                    if strong > 0:
                        max_input = max(max_input, strong)
                    continue

                # Direct power from neighbor component (but not from wires)
                if ncomp.block_name not in REDSTONE_WIRE_NAMES:
                    power = self._get_direct_power_from_neighbor(x, y, z, nx, ny, nz)
                    max_input = max(max_input, power)

            # Also check if this wire's block is strongly powered
            strong = self._get_strong_power_at(x, y, z)
            max_input = max(max_input, strong)

            if max_input > 0:
                wire_powers[pos] = max_input
                queue.append((pos, max_input))

        # Step 2: BFS propagation through wire network
        visited: set[tuple[int, int, int]] = set()
        while queue:
            pos, power = queue.popleft()
            if pos in visited:
                continue
            visited.add(pos)

            comp = self.components.get(pos)
            if comp is None or comp.block_name not in REDSTONE_WIRE_NAMES:
                continue

            current = wire_powers.get(pos, 0)
            if power > current:
                wire_powers[pos] = power
                current = power

            if current <= 1:
                continue  # Signal too weak to propagate further

            # Propagate to connected wires (using wire connections)
            x, y, z = pos
            connections = self.calculate_wire_connections(x, y, z)
            for npos in connections:
                ncomp = self.components.get(npos)
                if ncomp is None or ncomp.block_name not in REDSTONE_WIRE_NAMES:
                    continue
                new_power = current - 1
                existing = wire_powers.get(npos, 0)
                if new_power > existing:
                    wire_powers[npos] = new_power
                    queue.append((npos, new_power))

        # Step 3: Apply wire power levels
        for pos, power in wire_powers.items():
            self.power_levels[pos] = power

        # Set unvisited wires to 0
        for pos, comp in self.components.items():
            if comp.block_name in REDSTONE_WIRE_NAMES and pos not in wire_powers:
                self.power_levels[pos] = 0

    # --------------------------------------------------
    # Component-specific update logic
    # --------------------------------------------------

    def _update_lever(self, comp: RedstoneComponent):
        """Update lever power output."""
        comp.power = 15 if comp.lever_on else 0

    def _update_button(self, comp: RedstoneComponent):
        """Update button state - deactivate when timer expires."""
        if comp.active_timer > 0:
            comp.active_timer -= 1
            if comp.active_timer <= 0:
                comp.powered = False
                comp.power = 0
                comp.dirty = True

    def _update_pressure_plate(self, comp: RedstoneComponent):
        """Update pressure plate state based on entities standing on it.

        For now, we use a simplified model: check if any player is nearby.
        Weighted plates output signal based on entity count.
        """
        x, y, z = comp.pos
        name = comp.block_name

        # Count entities on the pressure plate
        entity_count = 0
        for player in self.server.get_online_players():
            px, py, pz = player.x, player.y, player.z
            if (abs(px - (x + 0.5)) < 0.75 and
                abs(pz - (z + 0.5)) < 0.75 and
                abs(py - y) < 0.5):
                entity_count += 1

        # Also check mobs
        if hasattr(self.server, 'entity_manager'):
            try:
                for entity in self.server.entity_manager.list_entities():
                    if entity.kind != "mob":
                        continue
                    ex, ey, ez = entity.x, entity.y, entity.z
                    if (abs(ex - (x + 0.5)) < 0.75 and
                        abs(ez - (z + 0.5)) < 0.75 and
                        abs(ey - y) < 0.5):
                        entity_count += 1
            except Exception:
                pass

        was_powered = comp.powered

        if name in ("minecraft:light_weighted_pressure_plate",
                     "minecraft:heavy_weighted_pressure_plate"):
            if name == "minecraft:light_weighted_pressure_plate":
                # Gold: 1 entity = signal 1, scales linearly
                comp.power = min(15, entity_count)
                comp.powered = entity_count > 0
            else:
                # Iron: 1 signal per 10 entities
                comp.power = min(15, entity_count // 10)
                comp.powered = entity_count >= 10
        else:
            # Standard pressure plates: on/off
            comp.powered = entity_count > 0
            comp.power = 15 if comp.powered else 0

        if was_powered != comp.powered:
            comp.dirty = True

    def _update_redstone_torch(self, comp: RedstoneComponent):
        """Update redstone torch state.

        A redstone torch is OFF when the block it's attached to is powered,
        and ON when it's not. Has burnout protection.

        Important: When checking if the attached block is powered, we must
        exclude this torch's own output to avoid circular dependency.
        """
        x, y, z = comp.pos
        name = comp.block_name

        # Determine the attached block position
        if name == "minecraft:redstone_torch":
            # Floor torch: attached to block below
            attach_x, attach_y, attach_z = x, y - 1, z
        elif name == "minecraft:redstone_wall_torch":
            # Wall torch: attached to block opposite facing
            fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
            attach_x, attach_y, attach_z = x - fdx, y, z - fdz
        else:
            return

        # Check if the attached block is powered by sources OTHER than this torch.
        # We temporarily save and clear this torch's power to avoid circular dependency.
        saved_powered = comp.powered
        saved_power = comp.power
        comp.powered = False
        comp.power = 0

        attached_powered = self._is_block_powered_excluding(attach_x, attach_y, attach_z, comp.pos)

        # Restore torch state
        comp.powered = saved_powered
        comp.power = saved_power

        was_powered = comp.powered

        if comp.torch_burnout_timer > 0:
            comp.torch_burnout_timer -= 1
            comp.powered = False
            comp.power = 0
        else:
            # Torch inverts: OFF when attached block is powered
            new_powered = not attached_powered
            comp.powered = new_powered
            comp.power = 15 if new_powered else 0

            # Burnout detection: if toggling too rapidly
            if was_powered != new_powered:
                now = time.monotonic()
                if now - comp.torch_toggle_window_start > 4.0:
                    # Reset the window
                    comp.torch_toggle_count = 1
                    comp.torch_toggle_window_start = now
                else:
                    comp.torch_toggle_count += 1
                    if comp.torch_toggle_count >= TORCH_BURNOUT_THRESHOLD:
                        comp.torch_burnout_timer = TORCH_BURNOUT_DURATION
                        comp.torch_toggle_count = 0
                        comp.powered = False
                        comp.power = 0
                        logger.debug(f"Redstone torch burnout at {comp.pos}")

        if was_powered != comp.powered:
            comp.dirty = True

    def _update_repeater(self, comp: RedstoneComponent):
        """Update repeater state.

        A repeater:
        - Receives input from its back face
        - Outputs to its front face with a delay
        - Can be locked by a powered repeater from the side
        """
        x, y, z = comp.pos

        # Check if locked by side repeater
        facing = comp.facing
        # Get perpendicular directions
        if facing in ("north", "south"):
            side_dirs = [(1, 0, 0), (-1, 0, 0)]
        else:
            side_dirs = [(0, 0, 1), (0, 0, -1)]

        comp.locked = False
        for sdx, sdy, sdz in side_dirs:
            snpos = (x + sdx, y + sdy, z + sdz)
            scomp = self.components.get(snpos)
            if scomp and scomp.block_name in REDSTONE_REPEATER_NAMES:
                # Check if the side repeater is pointing at us and powered
                sfdx, sfdy, sfdz = FACING_DX.get(scomp.facing, (0, 0, 1))
                # The side repeater must be facing perpendicular AND pointing toward us
                # i.e. the side repeater's output faces this repeater
                s_output = (snpos[0] + sfdx, snpos[1] + sfdy, snpos[2] + sfdz)
                if s_output == comp.pos and scomp.powered:
                    comp.locked = True
                    break

        if comp.locked:
            # Locked repeater holds its current output state
            return

        # Get input from back face
        back_facing = FACING_OPPOSITE.get(facing, "south")
        bdx, bdy, bdz = FACING_DX.get(back_facing, (0, 0, -1))
        input_x, input_y, input_z = x + bdx, y + bdy, z + bdz

        input_power = 0
        # Check direct power from input block
        icomp = self.components.get((input_x, input_y, input_z))
        if icomp:
            input_power = self._get_direct_power_from_neighbor(
                x, y, z, input_x, input_y, input_z
            )
        # Check strong power at input position
        strong = self._get_strong_power_at(input_x, input_y, input_z)
        input_power = max(input_power, strong)
        # Check wire power
        wire_power = self.power_levels.get((input_x, input_y, input_z), 0)
        input_power = max(input_power, wire_power)

        # Check if block behind is powered (indirect power)
        if input_power == 0:
            if self.is_powered(input_x, input_y, input_z):
                input_power = 15

        should_power = input_power > 0
        was_powered = comp.powered

        if should_power != was_powered:
            # Schedule the change after the delay
            schedule_tick = self.current_tick + comp.delay
            self.scheduled_updates.append(ScheduledUpdate(
                tick=schedule_tick,
                pos=comp.pos,
                target_powered=should_power,
            ))

    def _update_comparator(self, comp: RedstoneComponent):
        """Update comparator state.

        Comparator modes:
        - Compare: output = back_input if back_input >= max(side_inputs), else 0
        - Subtract: output = max(0, back_input - max(side_inputs))

        Can also read container signal strength.
        """
        x, y, z = comp.pos
        facing = comp.facing

        # Get back input
        back_facing = FACING_OPPOSITE.get(facing, "south")
        bdx, bdy, bdz = FACING_DX.get(back_facing, (0, 0, -1))
        input_x, input_y, input_z = x + bdx, y + bdy, z + bdz

        back_input = 0
        icomp = self.components.get((input_x, input_y, input_z))
        if icomp:
            back_input = self._get_direct_power_from_neighbor(
                x, y, z, input_x, input_y, input_z
            )
        strong = self._get_strong_power_at(input_x, input_y, input_z)
        back_input = max(back_input, strong)
        wire_power = self.power_levels.get((input_x, input_y, input_z), 0)
        back_input = max(back_input, wire_power)

        # Check if block behind is powered (indirect power)
        if back_input == 0 and self.is_powered(input_x, input_y, input_z):
            back_input = 15

        # Try to read container signal strength first (takes priority over redstone)
        container_signal = self._read_container_signal(input_x, input_y, input_z)
        if container_signal > 0 and back_input == 0:
            back_input = container_signal

        # Get side inputs
        if facing in ("north", "south"):
            side_dirs = [(1, 0, 0), (-1, 0, 0)]
        else:
            side_dirs = [(0, 0, 1), (0, 0, -1)]

        side_inputs = []
        for sdx, sdy, sdz in side_dirs:
            snx, sny, snz = x + sdx, y + sdy, z + sdz
            sp = 0
            scomp = self.components.get((snx, sny, snz))
            if scomp:
                sp = self._get_direct_power_from_neighbor(x, y, z, snx, sny, snz)
            strong = self._get_strong_power_at(snx, sny, snz)
            sp = max(sp, strong)
            wire_power = self.power_levels.get((snx, sny, snz), 0)
            sp = max(sp, wire_power)
            side_inputs.append(sp)

        max_side = max(side_inputs) if side_inputs else 0

        # Calculate output based on mode
        if comp.mode == "compare":
            new_power = back_input if back_input >= max_side else 0
        else:  # subtract
            new_power = max(0, back_input - max_side)

        was_powered = comp.powered
        old_power = comp.power

        comp.power = new_power
        comp.powered = new_power > 0

        if was_powered != comp.powered or old_power != comp.power:
            comp.dirty = True

    def _read_container_signal(self, x: int, y: int, z: int) -> int:
        """Read signal strength from a container (chest, hopper, etc.).

        Signal = floor(16 * full_slots / total_slots) for most containers.
        Returns 0 if no container is present or if it's empty.
        """
        block_name = self._get_block_name_at(x, y, z)
        if block_name not in CONTAINER_NAMES:
            return 0

        # Prefer the real block-container inventory when it exists.
        from .block_behavior import container_manager

        container = container_manager.get_container(x, y, z)
        if container is not None:
            total = 0
            for stack in container.items:
                if stack is None or stack.is_empty:
                    continue
                max_size = max(1, stack.max_stack_size)
                # Vanilla comparator formula:
                # floor(1 + (count / max_stack_size) * 14).
                total += 1 + (stack.count * 14) // max_size
            return min(15, total)

        # Compatibility fallback for older callers that populated
        # ``server._block_inventories`` directly.
        inventory_data = getattr(self.server, '_block_inventories', {}).get((x, y, z))
        if inventory_data is None:
            return 0

        try:
            # inventory_data should be a dict with 'used' and 'total' slots
            used = inventory_data.get('used', 0)
            total = inventory_data.get('total', 27)
            if total == 0:
                return 0
            # Calculate signal strength
            # Signal 0 if empty, 1-15 based on fill level, 15 if full
            if used == 0:
                return 0
            # Each slot is 1/total of the signal range
            signal = min(15, max(1, (used * 16) // total))
            return signal
        except Exception:
            return 0

    def _update_observer(self, comp: RedstoneComponent):
        """Update observer state.

        An observer detects block state changes in front of it and
        emits a 2-tick pulse when a change is detected.
        The observer monitors the block it's facing, not the block behind it.
        """
        if comp.observer_cooldown > 0:
            comp.observer_cooldown -= 1
            if comp.observer_cooldown <= 0:
                comp.powered = False
                comp.power = 0
                comp.dirty = True

    def _update_daylight_detector(self, comp: RedstoneComponent):
        """Update daylight detector based on sky light level.

        The signal strength depends on the sun angle:
        - Maximum at noon (time 6000)
        - Zero at night (13000-23000)
        - Inverted mode reverses the output
        """
        time_of_day = self.server.world_time % 24000

        if comp.inverted:
            # Inverted: maximum at night, minimum at day
            if 13000 <= time_of_day <= 23000:
                # Night time - peak at 18000
                angle = 1.0 - abs(time_of_day - 18000) / 5000.0
                angle = max(0, min(1, angle))
                comp.power = int(angle * 15)
            else:
                # Day time - very low
                if time_of_day < 13000:
                    comp.power = max(0, int((1.0 - time_of_day / 13000.0) * 3))
                else:
                    comp.power = max(0, int(((time_of_day - 23000) / 1000.0) * 3))
        else:
            # Normal: maximum at noon, minimum at night
            if 0 <= time_of_day <= 12000:
                # Day - peak at 6000
                angle = 1.0 - abs(time_of_day - 6000) / 6000.0
                angle = max(0, min(1, angle))
                comp.power = int(angle * 15)
            elif 12000 < time_of_day < 13000:
                comp.power = 0
            elif 23000 <= time_of_day:
                angle = (time_of_day - 23000) / 1000.0
                comp.power = int(angle * 10)
            else:
                comp.power = 0

        comp.powered = comp.power > 0
        comp.dirty = True

    def _update_target(self, comp: RedstoneComponent):
        """Update target block - activated by projectile hits."""
        if comp.target_timer > 0:
            comp.target_timer -= 1
            if comp.target_timer <= 0:
                comp.power = 0
                comp.powered = False
                comp.dirty = True

    def _update_tripwire_hook(self, comp: RedstoneComponent):
        """Update tripwire hook - detects entity crossing tripwire."""
        x, y, z = comp.pos
        fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
        entity_detected = False

        for dist in range(1, 41):  # Max 40 blocks
            tx, ty, tz = x + fdx * dist, y, z + fdz * dist
            tname = self._get_block_name_at(tx, ty, tz)
            if tname == "minecraft:tripwire":
                # Check for entities on this tripwire
                for player in self.server.get_online_players():
                    if (abs(player.x - (tx + 0.5)) < 0.75 and
                        abs(player.z - (tz + 0.5)) < 0.75 and
                        abs(player.y - ty) < 0.5):
                        entity_detected = True
                        break
                if entity_detected:
                    break
                comp.attached = True
            else:
                break

        was_powered = comp.powered
        comp.powered = entity_detected
        comp.power = 15 if entity_detected else 0
        if was_powered != comp.powered:
            comp.dirty = True

    def _update_detector_rail(self, comp: RedstoneComponent):
        """Update detector rail - detects an entity riding on the rail.

        PyMC does not have a dedicated minecart entity yet, so this checks
        every tracked entity/player overlapping the rail block. That covers
        minecarts once they are represented as ordinary entities.
        """
        x, y, z = comp.pos
        detected = False

        for player in self.server.get_online_players():
            if (abs(player.x - (x + 0.5)) < 0.75
                    and abs(player.z - (z + 0.5)) < 0.75
                    and abs(player.y - y) < 0.6):
                detected = True
                break

        if not detected and hasattr(self.server, 'entity_manager'):
            try:
                for entity in self.server.entity_manager.list_entities():
                    if (abs(entity.x - (x + 0.5)) < 0.75
                            and abs(entity.z - (z + 0.5)) < 0.75
                            and abs(entity.y - y) < 0.6):
                        detected = True
                        break
            except Exception:
                pass

        was_powered = comp.powered
        comp.powered = detected
        comp.power = 15 if detected else 0
        if was_powered != comp.powered:
            comp.dirty = True

    # --------------------------------------------------
    # Mechanical block activation
    # --------------------------------------------------

    def _activate_mechanical_blocks(self):
        """Activate/deactivate blocks that respond to redstone signals."""
        for pos, comp in list(self.components.items()):
            name = comp.block_name
            if name not in REDSTONE_ACTIVATABLE:
                continue

            x, y, z = pos
            powered = self.is_powered(x, y, z) or self._get_strong_power_at(x, y, z) > 0

            if name == "minecraft:redstone_lamp":
                if powered != comp.powered:
                    comp.powered = powered
                    comp.dirty = True

            elif name == "minecraft:tnt":
                if powered:
                    if not comp.powered:
                        comp.powered = True
                        comp.fuse_ticks = 40
                        comp.dirty = True
                        logger.info(f"TNT ignited by redstone at {pos}")
                    elif comp.fuse_ticks > 0:
                        comp.fuse_ticks -= 1
                        if comp.fuse_ticks <= 0:
                            self._detonate_tnt(pos, comp)
                elif comp.powered:
                    comp.powered = False
                    comp.fuse_ticks = 0
                    comp.dirty = True

            elif name == "minecraft:note_block":
                # Note blocks play on rising edge.
                if powered and not comp.powered:
                    comp.powered = True
                    comp.dirty = True
                    self._queue_effect("note", {"x": x, "y": y, "z": z, "note": comp.note})
                elif not powered and comp.powered:
                    comp.powered = False
                    comp.dirty = True

            elif name == "minecraft:hopper":
                if powered != comp.powered:
                    comp.powered = powered
                    comp.dirty = True

            elif name.endswith("_door") or name.endswith("_trapdoor") or name.endswith("_fence_gate"):
                # Toggle on rising edge
                if powered and not comp.powered:
                    comp.powered = True
                    comp.dirty = True
                    self._toggle_openable(pos, comp, True)
                elif not powered and comp.powered:
                    comp.powered = False
                    comp.dirty = True
                    self._toggle_openable(pos, comp, False)

            elif name in ("minecraft:dispenser", "minecraft:dropper"):
                if powered and not comp.powered:
                    comp.powered = True
                    comp.dirty = True
                    self._activate_dispenser_or_dropper(pos, comp)
                elif not powered and comp.powered:
                    comp.powered = False
                    comp.dirty = True

            elif name == "minecraft:powered_rail":
                if powered != comp.powered:
                    comp.powered = powered
                    comp.dirty = True

            elif name == "minecraft:activator_rail":
                if powered != comp.powered:
                    comp.powered = powered
                    comp.dirty = True

    def _detonate_tnt(self, pos: tuple[int, int, int], comp: RedstoneComponent):
        """Remove lit TNT and queue the explosion for the async server tick."""
        x, y, z = pos
        tnt_state = self._get_block_at(x, y, z)

        # Remove the block from the world synchronously so further redstone
        # ticks do not double-trigger it. The actual explosion is async.
        self._set_block_state(x, y, z, AIR)
        self.on_block_change(x, y, z, tnt_state, AIR)
        self.visual_updates.append((x, y, z, AIR))
        self._queue_effect("explosion", {"x": x, "y": y, "z": z})

    def _activate_dispenser_or_dropper(self, pos: tuple[int, int, int],
                                       comp: RedstoneComponent):
        """Drop/dispense the first non-empty item on a rising redstone edge."""
        from .block_behavior import container_manager

        x, y, z = pos
        container = container_manager.get_container(x, y, z)
        if container is None:
            logger.debug(f"No container data for {comp.block_name} at {pos}")
            return

        # Find the first occupied slot.
        for slot_idx, stack in enumerate(container.items):
            if stack is None or stack.is_empty:
                continue

            item_name = stack.item_id
            stack.count -= 1
            if stack.count <= 0:
                container.items[slot_idx] = None

            fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))
            out_x = x + fdx * 1.0
            out_y = y + fdy * 0.5
            out_z = z + fdz * 1.0

            entity_manager = getattr(self.server, 'entity_manager', None)
            if entity_manager is not None:
                try:
                    entity = entity_manager.create_item(
                        out_x + 0.5, out_y + 0.3, out_z + 0.5,
                        item_name=item_name, count=1
                    )
                    entity.vx = fdx * 0.16
                    entity.vy = 0.06
                    entity.vz = fdz * 0.16
                    self._queue_effect("entity_spawn", {"entity_id": entity.entity_id})
                except Exception as e:
                    logger.warning(f"Failed to drop item from {comp.block_name}: {e}")
            return

    def _queue_effect(self, kind: str, payload: dict):
        """Queue an effect that must be broadcast/awaited outside the sync tick."""
        self.pending_effects.append((kind, payload))

    def drain_pending_effects(self) -> list[tuple[str, dict]]:
        """Return and clear queued async effects (sounds, explosions, drops)."""
        effects = self.pending_effects
        self.pending_effects = []
        return effects

    def _toggle_openable(self, pos: tuple[int, int, int], comp: RedstoneComponent,
                          should_open: bool):
        """Toggle a door/trapdoor/fence gate open/closed state."""
        x, y, z = pos
        block_id = self._get_block_at(x, y, z)
        props = _get_block_props(block_id)
        current_open = props.get("open", "false") == "true"

        if should_open != current_open:
            new_props = dict(props)
            new_props["open"] = "true" if should_open else "false"
            new_state = resolve_state_id(comp.block_name, **new_props)
            if new_state != block_id:
                self._set_block_state(x, y, z, new_state)

    # --------------------------------------------------
    # Piston logic
    # --------------------------------------------------

    def _update_pistons(self):
        """Process piston extend/retract operations."""
        for pos, comp in list(self.components.items()):
            if comp.block_name not in PISTON_NAMES:
                continue

            x, y, z = pos
            powered = self.is_powered(x, y, z) or self._get_strong_power_at(x, y, z) > 0

            if powered and not comp.extended:
                # Extend piston
                self._piston_extend(comp)
            elif not powered and comp.extended:
                # Retract piston
                self._piston_retract(comp)

    def _piston_extend(self, comp: RedstoneComponent):
        """Extend a piston, pushing blocks in its path."""
        x, y, z = comp.pos
        fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))

        # Find blocks to push (up to 12)
        blocks_to_push: list[tuple[int, int, int, int]] = []
        for i in range(1, PISTON_PUSH_LIMIT + 2):
            bx, by, bz = x + fdx * i, y + fdy * i, z + fdz * i
            block_id = self._get_block_at(bx, by, bz)
            if block_id == 0:  # Air
                break
            name = _get_block_name(block_id)
            # Cannot push certain blocks
            unpushable = {
                "minecraft:obsidian", "minecraft:bedrock", "minecraft:command_block",
                "minecraft:end_portal_frame", "minecraft:barrier", "minecraft:spawner",
                "minecraft:reinforced_deepslate", "minecraft:piston_head",
                "minecraft:moving_piston",
            }
            if name in unpushable:
                return
            if len(blocks_to_push) >= PISTON_PUSH_LIMIT:
                return  # Too many blocks
            blocks_to_push.append((bx, by, bz, block_id))

        # Check that the destination for the last block is clear
        if blocks_to_push:
            last_bx, last_by, last_bz, _ = blocks_to_push[-1]
            dest_x = last_bx + fdx
            dest_y = last_by + fdy
            dest_z = last_bz + fdz
            dest_id = self._get_block_at(dest_x, dest_y, dest_z)
            if dest_id != 0:
                return  # Can't push into non-air
        else:
            # No blocks to push, just extend the piston head
            head_x, head_y, head_z = x + fdx, y + fdy, z + fdz
            head_id = self._get_block_at(head_x, head_y, head_z)
            if head_id != 0:
                return  # Can't extend into non-air

        # Execute push: move blocks from far to near (preserve order)
        for bx, by, bz, bid in reversed(blocks_to_push):
            new_x, new_y, new_z = bx + fdx, by + fdy, bz + fdz
            self._set_block_state(new_x, new_y, new_z, bid)
            self._set_block_state(bx, by, bz, AIR)
            # Notify engine of block changes
            self.on_block_change(bx, by, bz, bid, AIR)
            self.on_block_change(new_x, new_y, new_z, AIR, bid)

        # Place piston head
        head_x, head_y, head_z = x + fdx, y + fdy, z + fdz
        piston_head_name = "minecraft:piston_head"
        head_props = {"facing": comp.facing, "type": "sticky" if comp.is_sticky else "normal"}
        head_state = resolve_state_id(piston_head_name, **head_props)
        self._set_block_state(head_x, head_y, head_z, head_state)

        # Update piston block to extended state
        comp.extended = True
        piston_props = {"facing": comp.facing, "extended": "true"}
        piston_state = resolve_state_id(comp.block_name, **piston_props)
        self._set_block_state(x, y, z, piston_state)

    def _piston_retract(self, comp: RedstoneComponent):
        """Retract a piston, pulling the attached block if sticky."""
        x, y, z = comp.pos
        fdx, fdy, fdz = FACING_DX.get(comp.facing, (0, 0, 1))

        # Remove piston head
        head_x, head_y, head_z = x + fdx, y + fdy, z + fdz
        head_id = self._get_block_at(head_x, head_y, head_z)
        head_name = _get_block_name(head_id)
        if head_name == "minecraft:piston_head":
            self._set_block_state(head_x, head_y, head_z, AIR)
            self.on_block_change(head_x, head_y, head_z, head_id, AIR)

        # Sticky piston pulls one block
        if comp.is_sticky:
            pull_x, pull_y, pull_z = x + fdx * 2, y + fdy * 2, z + fdz * 2
            pull_id = self._get_block_at(pull_x, pull_y, pull_z)
            pull_name = _get_block_name(pull_id)
            if pull_id and pull_id != 0 and pull_name not in {
                "minecraft:obsidian", "minecraft:bedrock",
                "minecraft:piston_head", "minecraft:moving_piston",
            }:
                # Move the block
                self._set_block_state(head_x, head_y, head_z, pull_id)
                self._set_block_state(pull_x, pull_y, pull_z, AIR)
                self.on_block_change(pull_x, pull_y, pull_z, pull_id, AIR)
                self.on_block_change(head_x, head_y, head_z, AIR, pull_id)

        # Update piston block to retracted state
        comp.extended = False
        piston_props = {"facing": comp.facing, "extended": "false"}
        piston_state = resolve_state_id(comp.block_name, **piston_props)
        self._set_block_state(x, y, z, piston_state)

    # --------------------------------------------------
    # Main tick loop
    # --------------------------------------------------

    def tick(self):
        """Process one redstone tick (2 game ticks = 0.1s).

        Steps:
        1. Process scheduled updates
        2. Update power sources (levers, buttons, plates, etc.)
        3. Propagate wire signals (BFS) - do this before signal processors
           so that components can read current wire power levels
        4. Update signal processors (torches, repeaters, comparators)
        5. Re-propagate wire signals if processors changed
        6. Calculate block power levels
        7. Activate mechanical blocks
        8. Update pistons
        9. Apply visual updates
        """
        tick_start = time.monotonic()
        self.current_tick += 1
        self.visual_updates.clear()

        # If native engine is available and has enough components, delegate
        if self._native_engine and len(self.components) > 100:
            try:
                self._tick_native()
                self._tick_time_ms = (time.monotonic() - tick_start) * 1000
                return
            except Exception as e:
                logger.debug(f"Native tick failed, falling back: {e}")

        # 1. Process scheduled updates
        self._process_scheduled_updates()

        # 2. Update all power sources
        for pos, comp in list(self.components.items()):
            name = comp.block_name

            if name == "minecraft:lever":
                self._update_lever(comp)
            elif name.endswith("_button"):
                self._update_button(comp)
            elif name.endswith("_pressure_plate"):
                self._update_pressure_plate(comp)
            elif name == "minecraft:daylight_detector":
                self._update_daylight_detector(comp)
            elif name == "minecraft:target":
                self._update_target(comp)
            elif name == "minecraft:tripwire_hook":
                self._update_tripwire_hook(comp)
            elif name == "minecraft:detector_rail":
                self._update_detector_rail(comp)

        # 3. First wire propagation pass - so signal processors can read wire levels
        self._propagate_wire_signals()

        # 4. Update signal processors (torches first, then repeaters, then comparators)
        for pos, comp in list(self.components.items()):
            if comp.block_name in REDSTONE_TORCH_NAMES:
                self._update_redstone_torch(comp)

        for pos, comp in list(self.components.items()):
            if comp.block_name in REDSTONE_REPEATER_NAMES:
                self._update_repeater(comp)

        for pos, comp in list(self.components.items()):
            if comp.block_name in REDSTONE_COMPARATOR_NAMES:
                self._update_comparator(comp)

        for pos, comp in list(self.components.items()):
            if comp.block_name in REDSTONE_OBSERVER_NAMES:
                self._update_observer(comp)

        # 5. Second wire propagation pass - capture changes from signal processors
        self._propagate_wire_signals()

        # 6. Calculate power levels for all component positions
        self._calculate_power_levels()

        # 7. Activate mechanical blocks
        self._activate_mechanical_blocks()

        # 8. Update pistons
        self._update_pistons()

        # 9. Apply visual updates for dirty components
        self._apply_visual_updates()

        # Performance tracking
        self._tick_time_ms = (time.monotonic() - tick_start) * 1000

        # Periodic logging
        if self.current_tick % 200 == 0:  # Every 20 seconds
            comp_count = len(self.components)
            if comp_count != self._component_count_at_last_log:
                logger.info(
                    f"Redstone: {comp_count} components, "
                    f"tick={self._tick_time_ms:.1f}ms"
                )
                self._component_count_at_last_log = comp_count

    def _tick_native(self):
        """Delegate tick processing to the native C++ engine."""
        if not self._native_engine:
            return

        # Process scheduled updates in Python first
        self._process_scheduled_updates()

        # Sync component states to native engine
        for pos, comp in self.components.items():
            try:
                self._native_engine.set_power_level(
                    pos[0], pos[1], pos[2], comp.power
                )
            except Exception:
                pass

        # Run native tick
        updates = self._native_engine.tick()

        # Apply updates from native engine
        self.visual_updates.clear()
        for update in updates:
            x, y, z, new_state, flags = update.x, update.y, update.z, update.new_block_state, update.flags
            # Update component power levels
            pos = (x, y, z)
            comp = self.components.get(pos)
            if comp:
                comp.power = new_state & 0xF
                comp.powered = comp.power > 0
                comp.dirty = False
            # Queue visual update
            self._set_block_state(x, y, z, new_state)

    def _process_scheduled_updates(self):
        """Process scheduled updates that have reached their execution tick."""
        remaining: list[ScheduledUpdate] = []
        for update in self.scheduled_updates:
            if update.tick <= self.current_tick:
                comp = self.components.get(update.pos)
                if comp is None:
                    continue

                if comp.block_name in REDSTONE_REPEATER_NAMES:
                    # Apply the scheduled state change
                    comp.powered = update.target_powered
                    comp.power = 15 if comp.powered else 0
                    comp.dirty = True
                elif comp.block_name in REDSTONE_TORCH_NAMES:
                    comp.powered = update.target_powered
                    comp.power = 15 if comp.powered else 0
                    comp.dirty = True
            else:
                remaining.append(update)

        self.scheduled_updates = remaining

    def _calculate_power_levels(self):
        """Calculate power levels at all tracked positions."""
        for pos, comp in self.components.items():
            x, y, z = pos
            if comp.block_name in REDSTONE_WIRE_NAMES:
                # Wire power is already set by propagation
                continue

            # For other components, calculate the power they receive
            max_power = 0
            for dx, dy, dz in SIX_DIRS:
                nx, ny, nz = x + dx, y + dy, z + dz
                # Get power from wire
                wire_power = self.power_levels.get((nx, ny, nz), 0)
                max_power = max(max_power, wire_power)

                # Get power from components
                ncomp = self.components.get((nx, ny, nz))
                if ncomp:
                    dp = self._get_direct_power_from_neighbor(x, y, z, nx, ny, nz)
                    max_power = max(max_power, dp)

            # Check strong power at this position
            strong = self._get_strong_power_at(x, y, z)
            max_power = max(max_power, strong)

            self.power_levels[pos] = max_power
            self.strong_power[pos] = strong

    def _apply_visual_updates(self):
        """Apply visual block state changes for dirty components."""
        for pos, comp in list(self.components.items()):
            if not comp.dirty:
                continue

            comp.dirty = False
            x, y, z = pos

            # Compute the correct block state ID for this component
            new_state = self._compute_visual_state(comp)
            current_state = self._get_block_at(x, y, z)

            if new_state != current_state:
                self._set_block_state(x, y, z, new_state)

    def _compute_visual_state(self, comp: RedstoneComponent) -> int:
        """Compute the correct block state ID for a component's current state."""
        name = comp.block_name

        try:
            if name in REDSTONE_WIRE_NAMES:
                # Redstone wire: power 0-15 + connection directions
                connections = self.calculate_wire_connections(*comp.pos)
                conn_dirs: dict[str, str] = {"north": "none", "south": "none", "east": "none", "west": "none"}
                cx, cy, cz = comp.pos
                for nx, ny, nz in connections:
                    dx, dz = nx - cx, nz - cz
                    if dx == 1:
                        conn_dirs["east"] = "side"
                    elif dx == -1:
                        conn_dirs["west"] = "side"
                    if dz == 1:
                        conn_dirs["south"] = "side"
                    elif dz == -1:
                        conn_dirs["north"] = "side"

                # Check up connections
                for nx, ny, nz in connections:
                    if ny > cy:
                        dx, dz = nx - cx, nz - cz
                        if dx == 1:
                            conn_dirs["east"] = "up"
                        elif dx == -1:
                            conn_dirs["west"] = "up"
                        if dz == 1:
                            conn_dirs["south"] = "up"
                        elif dz == -1:
                            conn_dirs["north"] = "up"

                # If no connections, show as cross (dot shape)
                if all(v == "none" for v in conn_dirs.values()):
                    conn_dirs = {"north": "side", "south": "side", "east": "side", "west": "side"}

                return resolve_state_id(name,
                    power=str(comp.power),
                    north=conn_dirs["north"],
                    south=conn_dirs["south"],
                    east=conn_dirs["east"],
                    west=conn_dirs["west"])

            elif name in REDSTONE_TORCH_NAMES:
                if name == "minecraft:redstone_torch":
                    return resolve_state_id(name, lit="true" if comp.powered else "false")
                else:
                    return resolve_state_id(name,
                        facing=comp.facing,
                        lit="true" if comp.powered else "false")

            elif name in REDSTONE_REPEATER_NAMES:
                return resolve_state_id(name,
                    facing=comp.facing,
                    delay=str(comp.delay),
                    powered="true" if comp.powered else "false",
                    locked="true" if comp.locked else "false")

            elif name in REDSTONE_COMPARATOR_NAMES:
                return resolve_state_id(name,
                    facing=comp.facing,
                    mode=comp.mode,
                    powered="true" if comp.powered else "false")

            elif name in REDSTONE_OBSERVER_NAMES:
                return resolve_state_id(name,
                    facing=comp.facing,
                    powered="true" if comp.powered else "false")

            elif name == "minecraft:lever":
                # Lever has face, facing, and powered properties
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    face=props.get("face", "wall"),
                    facing=props.get("facing", "north"),
                    powered="true" if comp.lever_on else "false")

            elif name.endswith("_button"):
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    face=props.get("face", "wall"),
                    facing=props.get("facing", "north"),
                    powered="true" if comp.powered else "false")

            elif name == "minecraft:redstone_block":
                return resolve_state_id(name)

            elif name == "minecraft:redstone_lamp":
                return resolve_state_id(name, lit="true" if comp.powered else "false")

            elif name == "minecraft:daylight_detector":
                return resolve_state_id(name,
                    power=str(comp.power),
                    inverted="true" if comp.inverted else "false")

            elif name == "minecraft:target":
                return resolve_state_id(name, power=str(comp.power))

            elif name.endswith("_pressure_plate"):
                if name in ("minecraft:light_weighted_pressure_plate",
                            "minecraft:heavy_weighted_pressure_plate"):
                    return resolve_state_id(name, power=str(comp.power))
                else:
                    return resolve_state_id(name,
                        powered="true" if comp.powered else "false")

            elif name == "minecraft:tripwire_hook":
                return resolve_state_id(name,
                    facing=comp.facing,
                    attached="true" if comp.attached else "false",
                    powered="true" if comp.powered else "false")

            elif name in PISTON_NAMES:
                return resolve_state_id(name,
                    facing=comp.facing,
                    extended="true" if comp.extended else "false")

            elif name in ("minecraft:dispenser", "minecraft:dropper"):
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    facing=props.get("facing", "north"),
                    triggered="true" if comp.powered else "false")

            elif name == "minecraft:hopper":
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    facing=props.get("facing", "down"),
                    enabled="false" if comp.powered else "true")

            elif name == "minecraft:powered_rail":
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    shape=props.get("shape", "north_south"),
                    powered="true" if comp.powered else "false",
                    waterlogged=props.get("waterlogged", "false"))

            elif name == "minecraft:activator_rail":
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    shape=props.get("shape", "north_south"),
                    powered="true" if comp.powered else "false",
                    waterlogged=props.get("waterlogged", "false"))

            elif name == "minecraft:detector_rail":
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    shape=props.get("shape", "north_south"),
                    powered="true" if comp.powered else "false",
                    waterlogged=props.get("waterlogged", "false"))

            elif name == "minecraft:note_block":
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    instrument=props.get("instrument", "harp"),
                    note=str(max(0, min(24, int(comp.note)))),
                    powered="true" if comp.powered else "false")

            elif name == "minecraft:tnt":
                return resolve_state_id(name,
                    unstable="true" if comp.powered else "false")

            elif name.endswith("_door"):
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    facing=props.get("facing", "north"),
                    half=props.get("half", "lower"),
                    hinge=props.get("hinge", "left"),
                    open="true" if comp.powered else props.get("open", "false"),
                    powered="true" if comp.powered else "false")

            elif name.endswith("_trapdoor"):
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    facing=props.get("facing", "north"),
                    half=props.get("half", "bottom"),
                    open="true" if comp.powered else props.get("open", "false"),
                    powered="true" if comp.powered else "false",
                    waterlogged=props.get("waterlogged", "false"))

            elif name.endswith("_fence_gate"):
                block_id = self._get_block_at(*comp.pos)
                props = _get_block_props(block_id)
                return resolve_state_id(name,
                    facing=props.get("facing", "north"),
                    in_wall=props.get("in_wall", "false"),
                    open="true" if comp.powered else props.get("open", "false"),
                    powered="true" if comp.powered else "false")

        except Exception as e:
            logger.debug(f"Error computing visual state for {name} at {comp.pos}: {e}")

        # Fallback: return the default state for this block
        return BLOCK_NAME_TO_DEFAULT_STATE.get(name, 0)

    # --------------------------------------------------
    # Event handlers
    # --------------------------------------------------

    def on_block_change(self, x: int, y: int, z: int, old_block: int, new_block: int):
        """Called when a block is placed/broken/moved.

        Re-registers components and marks neighbors dirty.
        """
        old_name = _get_block_name(old_block)
        new_name = _get_block_name(new_block)

        # Unregister old component if it was redstone
        if old_name and is_redstone_block(old_name):
            self.unregister_component(x, y, z)

        # Register new component if it is redstone
        if new_name and is_redstone_block(new_name):
            self.register_component(x, y, z, new_block)

        # Mark neighbors dirty
        self._mark_neighbors_dirty(x, y, z)

        # Check if an observer should detect this change
        for dx, dy, dz in SIX_DIRS:
            npos = (x + dx, y + dy, z + dz)
            ncomp = self.components.get(npos)
            if ncomp and ncomp.block_name in REDSTONE_OBSERVER_NAMES:
                # Check if the observer is facing this block
                fdx, fdy, fdz = FACING_DX.get(ncomp.facing, (0, 0, 1))
                observed_pos = (npos[0] + fdx, npos[1] + fdy, npos[2] + fdz)
                if observed_pos == (x, y, z):
                    # Observer detects this change
                    if ncomp.observer_cooldown <= 0:
                        ncomp.powered = True
                        ncomp.power = 15
                        ncomp.observer_cooldown = 2  # 2 redstone ticks pulse
                        ncomp.dirty = True

    def on_player_interact(self, x: int, y: int, z: int, player) -> bool:
        """Handle player interaction with a redstone component.

        Returns True if the interaction was handled.
        """
        pos = (x, y, z)
        comp = self.components.get(pos)
        if comp is None:
            return False

        name = comp.block_name

        if name == "minecraft:lever":
            comp.lever_on = not comp.lever_on
            comp.power = 15 if comp.lever_on else 0
            comp.dirty = True
            self._mark_neighbors_dirty(x, y, z)
            return True

        elif name in REDSTONE_REPEATER_NAMES:
            # Right-click cycles delay 1->2->3->4->1
            comp.delay = (comp.delay % 4) + 1
            comp.dirty = True
            return True

        elif name in REDSTONE_COMPARATOR_NAMES:
            # Right-click toggles mode
            comp.mode = "subtract" if comp.mode == "compare" else "compare"
            comp.dirty = True
            return True

        elif name == "minecraft:daylight_detector":
            # Right-click toggles inverted
            comp.inverted = not comp.inverted
            comp.dirty = True
            return True

        elif name.endswith("_button"):
            if not comp.powered:
                comp.powered = True
                comp.power = 15
                if _is_wood_button(name):
                    comp.active_timer = WOOD_BUTTON_DURATION
                else:
                    btn_type = name.replace("minecraft:", "").replace("_button", "")
                    comp.active_timer = BUTTON_DURATIONS.get(btn_type, 10)
                comp.dirty = True
                self._mark_neighbors_dirty(x, y, z)
            return True

        elif name == "minecraft:note_block":
            # Right-click changes note pitch 0 -> 24 -> 0.
            comp.note = (comp.note + 1) % 25
            comp.dirty = True
            self._queue_effect("note", {"x": x, "y": y, "z": z, "note": comp.note})
            return True

        return False

    def on_projectile_hit(self, x: int, y: int, z: int):
        """Handle a projectile hitting a block (for target blocks)."""
        pos = (x, y, z)
        comp = self.components.get(pos)
        if comp and comp.block_name == "minecraft:target":
            comp.power = 15
            comp.powered = True
            comp.target_timer = 20  # 20 redstone ticks (2 seconds)
            comp.dirty = True
            self._mark_neighbors_dirty(x, y, z)

    def on_entity_move(self, x: int, y: int, z: int):
        """Called when an entity moves (for pressure plates/tripwires)."""
        # Check if any pressure plate at this position
        for dy in range(-1, 2):
            pos = (x, y + dy, z)
            comp = self.components.get(pos)
            if comp and comp.block_name.endswith("_pressure_plate"):
                comp.dirty = True
                self.dirty_positions.add(pos)

    # --------------------------------------------------
    # Scan existing world for redstone components
    # --------------------------------------------------

    def scan_chunk(self, chunk_x: int, chunk_z: int, chunk_blocks):
        """Scan a chunk for redstone components and register them."""
        if chunk_blocks is None:
            return

        for y_idx in range(len(chunk_blocks)):
            for lz in range(16):
                for lx in range(16):
                    block_id = int(chunk_blocks[y_idx][lz][lx])
                    name = _get_block_name(block_id)
                    if name and is_redstone_block(name):
                        world_y = y_idx + MIN_Y  # MIN_Y = -64, y_idx 0 -> y=-64
                        world_x = chunk_x * 16 + lx
                        world_z = chunk_z * 16 + lz
                        pos = (world_x, world_y, world_z)
                        if pos not in self.components:
                            self.register_component(world_x, world_y, world_z, block_id)

    # --------------------------------------------------
    # Get visual updates for client sync
    # --------------------------------------------------

    def get_visual_updates(self) -> list[tuple[int, int, int, int]]:
        """Get the list of block state changes that need to be sent to clients.

        Returns list of (x, y, z, new_block_state_id).
        """
        return list(self.visual_updates)

    # --------------------------------------------------
    # Debug / admin utilities
    # --------------------------------------------------

    def get_status(self) -> dict:
        """Get engine status for admin/debug display."""
        return {
            "tick": self.current_tick,
            "components": len(self.components),
            "scheduled_updates": len(self.scheduled_updates),
            "tick_time_ms": round(self._tick_time_ms, 2),
            "native_engine": self._native_engine is not None,
            "wires": sum(1 for c in self.components.values() if c.block_name in REDSTONE_WIRE_NAMES),
            "torches": sum(1 for c in self.components.values() if c.block_name in REDSTONE_TORCH_NAMES),
            "repeaters": sum(1 for c in self.components.values() if c.block_name in REDSTONE_REPEATER_NAMES),
            "comparators": sum(1 for c in self.components.values() if c.block_name in REDSTONE_COMPARATOR_NAMES),
            "observers": sum(1 for c in self.components.values() if c.block_name in REDSTONE_OBSERVER_NAMES),
            "pistons": sum(1 for c in self.components.values() if c.block_name in PISTON_NAMES),
            "activatables": sum(1 for c in self.components.values() if c.block_name in REDSTONE_ACTIVATABLE),
        }

    def force_update_all(self):
        """Force all components to recalculate. Useful after world edits."""
        for pos, comp in self.components.items():
            comp.dirty = True
        self.dirty_positions.update(self.components.keys())
