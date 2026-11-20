"""
Vanilla 1.21.1 redstone core: a port of the parts of Level / LevelChunk /
BlockBehaviour that redstone depends on.

* setBlock with update flags: onRemove/onPlace, block updates
  (updateNeighborsAt in W,E,D,U,N,S order), shape updates (W,E,N,S,D,U)
  and indirect shape updates;
* signals: getSignal / getDirectSignal / hasNeighborSignal /
  getBestNeighborSignal / getControlInputSignal, where the direction passed
  to a block points from the querying block to the emitter;
* scheduled block ticks ordered by (trigger tick, priority, sub-tick order);
* block events (pistons, note blocks) processed after the ticks, and block
  entities (moving pistons) after that, like ServerLevel.tick.

Behaviour that technical players rely on (quasi-connectivity, BUD, 0-tick
pistons, update order) is not special-cased: it falls out of doing the same
updates in the same order as the vanilla server.
"""

from __future__ import annotations

import heapq
import logging
import sys

from ..chunk_io import BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK

logger = logging.getLogger("PyMC.红石")

if sys.getrecursionlimit() < 20000:
    sys.setrecursionlimit(20000)

# --- directions ------------------------------------------------------------

VEC = {"down": (0, -1, 0), "up": (0, 1, 0), "north": (0, 0, -1), "south": (0, 0, 1),
       "west": (-1, 0, 0), "east": (1, 0, 0)}
OPP = {"down": "up", "up": "down", "north": "south", "south": "north", "west": "east", "east": "west"}
DIRECTIONS = ("down", "up", "north", "south", "west", "east")          # Direction.values()
UPDATE_ORDER = ("west", "east", "down", "up", "north", "south")        # NeighborUpdater.UPDATE_ORDER
SHAPE_ORDER = ("west", "east", "north", "south", "down", "up")         # UPDATE_SHAPE_ORDER
HORIZONTAL = ("north", "east", "south", "west")                         # Direction.Plane.HORIZONTAL
VERTICAL = ("up", "down")                                               # Direction.Plane.VERTICAL
CLOCKWISE = {"north": "east", "east": "south", "south": "west", "west": "north"}
COUNTER_CLOCKWISE = {v: k for k, v in CLOCKWISE.items()}
AXIS = {"down": "y", "up": "y", "north": "z", "south": "z", "west": "x", "east": "x"}
DATA_3D = {"down": 0, "up": 1, "north": 2, "south": 3, "west": 4, "east": 5}
FROM_3D = {v: k for k, v in DATA_3D.items()}


def rel(pos, direction, n=1):
    dx, dy, dz = VEC[direction]
    return (pos[0] + dx * n, pos[1] + dy * n, pos[2] + dz * n)


# --- update flags (Block.UPDATE_*) -----------------------------------------

UPDATE_NEIGHBORS = 1
UPDATE_CLIENTS = 2
UPDATE_INVISIBLE = 4
UPDATE_KNOWN_SHAPE = 16
UPDATE_SUPPRESS_DROPS = 32
UPDATE_MOVE_BY_PISTON = 64
UPDATE_ALL = 3

# tick priorities (TickPriority)
EXTREMELY_HIGH, VERY_HIGH, HIGH, NORMAL = -3, -2, -1, 0

AIR = 0


# --- Java hash ordering ----------------------------------------------------

def _i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def blockpos_hash(pos) -> int:
    """BlockPos.hashCode (Vec3i): (y + z * 31) * 31 + x, as a Java int."""
    x, y, z = pos
    return _i32(_i32(_i32(y + _i32(z * 31)) * 31) + x)


def java_hash_order(positions) -> list:
    """
    Iteration order of a java.util.HashSet/HashMap that had ``positions``
    added in this order (duplicates ignored): buckets by spread hash, then
    insertion order within a bucket.
    """
    seen = list(dict.fromkeys(positions))
    capacity = 16
    while len(seen) > capacity * 0.75:
        capacity *= 2
    mask = capacity - 1

    def bucket(pos):
        h = blockpos_hash(pos) & 0xFFFFFFFF
        return (h ^ (h >> 16)) & mask

    indexed = sorted(enumerate(seen), key=lambda item: (bucket(item[1]), item[0]))
    return [pos for _, pos in indexed]


# --- block states ----------------------------------------------------------

def name_of(state: int | None) -> str:
    if not state:
        return "minecraft:air"
    return STATE_ID_TO_BLOCK.get(state, ("minecraft:air", {}))[0]


def props_of(state: int | None) -> dict:
    if not state:
        return {}
    return STATE_ID_TO_BLOCK.get(state, ("minecraft:air", {}))[1]


def prop(state: int, key: str, default=None):
    return props_of(state).get(key, default)


def with_props(state: int, **changes) -> int:
    name, props = STATE_ID_TO_BLOCK.get(state, (None, None))
    if name is None:
        return state
    merged = dict(props)
    for key, value in changes.items():
        if key in merged:
            merged[key] = str(value).lower() if not isinstance(value, str) else value
    return BLOCK_KEY_TO_STATE_ID.get((name, tuple(sorted(merged.items()))), state)


_BLOCK_IDS: dict = {}


def block_registry_id(name: str) -> int:
    """Index of a block in the minecraft:block registry (for Block Action packets)."""
    if not _BLOCK_IDS:
        import json
        from ..chunk_io import _find_blocks_json
        with open(_find_blocks_json(), "r", encoding="utf-8") as f:
            for block in json.load(f):
                _BLOCK_IDS["minecraft:" + block["name"]] = int(block["id"])
    return _BLOCK_IDS.get(name, 0)


def default_state(name: str) -> int:
    return BLOCK_NAME_TO_DEFAULT_STATE.get(name, 0)


class Level:
    """
    Block access + vanilla update machinery over PyMC's world storage. Chunk
    arrays are modified in place and saved by flush(); every client-visible
    change is recorded for broadcasting.
    """

    def __init__(self, server):
        self.server = server
        self.game_time = 0
        self._chunks: dict = {}
        self._dirty: set = set()
        self.client_changes: dict = {}          # pos -> state (last value wins)
        self.block_actions: list = []           # (pos, block name, id, param)
        self.effects: list = []                 # (kind, payload)
        # scheduled ticks
        self._tick_heap: list = []
        self._tick_keys: set = set()
        self._running_ticks: set = set()
        self._sub_tick = 0
        # block events
        self._events: list = []
        self._event_keys: set = set()
        # block entities
        self.moving_pistons: dict = {}          # pos -> MovingPiston
        self.comparator_output: dict = {}       # pos -> int
        self.blocks = None                      # set by the engine: name -> behaviour

    # ------------------------------------------------------------ storage

    def _chunk(self, cx: int, cz: int):
        key = (cx, cz)
        chunk = self._chunks.get(key)
        if chunk is None:
            storage = getattr(self.server, "world_storage", None)
            chunk = storage.load_generated_chunk(cx, cz) if storage is not None else None
            if chunk is None:
                return None
            self._chunks[key] = chunk
        return chunk

    def raw(self, pos) -> int | None:
        x, y, z = pos
        if y < -64 or y > 319:
            return None
        chunk = self._chunk(x >> 4, z >> 4)
        if chunk is None:
            return None
        return int(chunk[y + 64][z & 15][x & 15])

    def get(self, pos) -> int:
        state = self.raw(pos)
        return 0 if state is None else state

    def _write(self, pos, state: int) -> bool:
        x, y, z = pos
        if y < -64 or y > 319:
            return False
        chunk = self._chunk(x >> 4, z >> 4)
        if chunk is None:
            return False
        chunk[y + 64][z & 15][x & 15] = int(state)
        self._dirty.add((x >> 4, z >> 4))
        return True

    def flush(self):
        """Save modified chunks and forget the per-step chunk cache."""
        storage = getattr(self.server, "world_storage", None)
        if storage is not None:
            for cx, cz in self._dirty:
                chunk = self._chunks.get((cx, cz))
                if chunk is not None:
                    storage.save_generated_chunk(cx, cz, chunk)
        self._dirty.clear()
        self._chunks.clear()

    # ------------------------------------------------------------ helpers

    def block(self, state: int):
        return self.blocks.get(name_of(state))

    def is_conductor(self, state: int) -> bool:
        from .blocks import is_conductor
        return is_conductor(state)

    # ----------------------------------------------------------- setBlock

    def set_block(self, pos, state: int, flags: int = UPDATE_ALL, recursion: int = 512) -> bool:
        old = self.raw(pos)
        if old is None or old == state:
            return False
        moved = bool(flags & UPDATE_MOVE_BY_PISTON)
        self._write(pos, state)
        # LevelChunk.setBlockState: onRemove of the old state, onPlace of the new one
        self.block(old).on_remove(self, old, pos, state, moved)
        if self.raw(pos) != state:
            return True
        self.block(state).on_place(self, state, pos, old, moved)
        if self.raw(pos) != state:
            return True
        # clients always get the final state (vanilla flag 2 only changes when they hear of it)
        self.client_changes[pos] = state
        if flags & UPDATE_NEIGHBORS:
            self.update_neighbors_at(pos, name_of(old))
            if self.block(state).has_analog_output(state):
                self.update_neighbour_for_output_signal(pos, name_of(state))
        if not flags & UPDATE_KNOWN_SHAPE and recursion > 0:
            f = flags & ~(UPDATE_NEIGHBORS | UPDATE_SUPPRESS_DROPS)
            self.block(old).update_indirect_neighbour_shapes(self, old, pos, f, recursion - 1)
            self.update_neighbour_shapes(state, pos, f, recursion - 1)
            self.block(state).update_indirect_neighbour_shapes(self, state, pos, f, recursion - 1)
        return True

    def remove_block(self, pos, moved: bool = False) -> bool:
        return self.set_block(pos, AIR, UPDATE_ALL | (UPDATE_MOVE_BY_PISTON if moved else 0))

    def destroy_block(self, pos, drop: bool = True, recursion: int = 512) -> bool:
        state = self.get(pos)
        if state == AIR:
            return False
        if drop:
            self.drop_resources(state, pos)
        return self.set_block(pos, AIR, UPDATE_ALL, recursion)

    def drop_resources(self, state: int, pos):
        self.effects.append(("drop", {"pos": pos, "state": state}))

    # ------------------------------------------------------ block updates

    def neighbor_changed(self, pos, source_block: str, from_pos, moved: bool = False):
        state = self.raw(pos)
        if state is None:
            return
        self.block(state).neighbor_changed(self, state, pos, source_block, from_pos, moved)

    def update_neighbors_at(self, pos, source_block: str):
        for direction in UPDATE_ORDER:
            self.neighbor_changed(rel(pos, direction), source_block, pos)

    def update_neighbors_at_except(self, pos, source_block: str, skip: str):
        for direction in UPDATE_ORDER:
            if direction != skip:
                self.neighbor_changed(rel(pos, direction), source_block, pos)

    def update_neighbour_shapes(self, state: int, pos, flags: int, recursion: int = 512):
        for direction in SHAPE_ORDER:
            npos = rel(pos, direction)
            nstate = self.raw(npos)
            if nstate is None:
                continue
            new = self.block(nstate).update_shape(self, nstate, OPP[direction], state, npos, pos)
            self.update_or_destroy(nstate, new, npos, flags, recursion)

    def neighbor_shape_changed(self, direction: str, neighbor_state: int, pos, neighbor_pos,
                               flags: int, recursion: int):
        state = self.raw(pos)
        if state is None:
            return
        new = self.block(state).update_shape(self, state, direction, neighbor_state, pos, neighbor_pos)
        self.update_or_destroy(state, new, pos, flags, recursion)

    def update_or_destroy(self, old: int, new: int, pos, flags: int, recursion: int = 512):
        if new == old:
            return
        if new == AIR:
            if old != AIR:
                self.destroy_block(pos, not flags & UPDATE_SUPPRESS_DROPS, recursion)
        else:
            self.set_block(pos, new, flags & ~UPDATE_SUPPRESS_DROPS, recursion)

    def update_from_neighbour_shapes(self, state: int, pos) -> int:
        for direction in SHAPE_ORDER:
            npos = rel(pos, direction)
            state = self.block(state).update_shape(self, state, direction, self.get(npos), pos, npos)
        return state

    def update_neighbour_for_output_signal(self, pos, source_block: str):
        for direction in HORIZONTAL:
            npos = rel(pos, direction)
            nstate = self.raw(npos)
            if nstate is None:
                continue
            if name_of(nstate) == "minecraft:comparator":
                self.block(nstate).neighbor_changed(self, nstate, npos, source_block, pos, False)
            elif self.is_conductor(nstate):
                npos = rel(npos, direction)
                nstate = self.raw(npos)
                if nstate is not None and name_of(nstate) == "minecraft:comparator":
                    self.block(nstate).neighbor_changed(self, nstate, npos, source_block, pos, False)

    # ------------------------------------------------------------ signals

    def get_signal(self, pos, direction: str) -> int:
        state = self.get(pos)
        i = self.block(state).get_signal(self, state, pos, direction)
        if self.is_conductor(state):
            return max(i, self.get_direct_signal_to(pos))
        return i

    def get_direct_signal(self, pos, direction: str) -> int:
        state = self.get(pos)
        return self.block(state).get_direct_signal(self, state, pos, direction)

    def get_direct_signal_to(self, pos) -> int:
        best = 0
        for direction in DIRECTIONS:
            j = self.get_direct_signal(rel(pos, direction), direction)
            if j >= 15:
                return 15
            best = max(best, j)
        return best

    def has_signal(self, pos, direction: str) -> bool:
        return self.get_signal(pos, direction) > 0

    def has_neighbor_signal(self, pos) -> bool:
        for direction in DIRECTIONS:
            if self.get_signal(rel(pos, direction), direction) > 0:
                return True
        return False

    def get_best_neighbor_signal(self, pos) -> int:
        best = 0
        for direction in DIRECTIONS:
            j = self.get_signal(rel(pos, direction), direction)
            if j >= 15:
                return 15
            best = max(best, j)
        return best

    def get_control_input_signal(self, pos, direction: str, diodes_only: bool) -> int:
        state = self.get(pos)
        name = name_of(state)
        if diodes_only:
            return self.get_direct_signal(pos, direction) if name in ("minecraft:repeater", "minecraft:comparator") else 0
        if name == "minecraft:redstone_block":
            return 15
        if name == "minecraft:redstone_wire":
            return int(prop(state, "power", 0))
        if self.block(state).is_signal_source(state):
            return self.get_direct_signal(pos, direction)
        return 0

    # ------------------------------------------------------ scheduled ticks

    def schedule_tick(self, pos, block: str, delay: int, priority: int = NORMAL):
        key = (pos, block)
        if key in self._tick_keys:
            return
        self._tick_keys.add(key)
        self._sub_tick += 1
        heapq.heappush(self._tick_heap, (self.game_time + max(1, delay), priority, self._sub_tick, pos, block))

    def has_scheduled_tick(self, pos, block: str) -> bool:
        return (pos, block) in self._tick_keys

    def will_tick_this_tick(self, pos, block: str) -> bool:
        return (pos, block) in self._running_ticks

    def run_scheduled_ticks(self, limit: int = 65536):
        due = []
        while self._tick_heap and self._tick_heap[0][0] <= self.game_time and len(due) < limit:
            entry = heapq.heappop(self._tick_heap)
            self._tick_keys.discard((entry[3], entry[4]))
            due.append(entry)
        self._running_ticks = {(e[3], e[4]) for e in due}
        for _, _, _, pos, block in due:
            self._running_ticks.discard((pos, block))
            state = self.raw(pos)
            if state is None or name_of(state) != block:
                continue
            try:
                self.block(state).tick(self, state, pos)
            except RecursionError:
                logger.warning(f"Redstone update chain too deep at {pos}")
        self._running_ticks = set()

    def pending_ticks(self):
        return [(e[3], e[4], e[0] - self.game_time, e[1]) for e in self._tick_heap]

    # --------------------------------------------------------- block events

    def block_event(self, pos, block: str, event_id: int, param: int):
        key = (pos, block, event_id, param)
        if key in self._event_keys:
            return
        self._event_keys.add(key)
        self._events.append(key)

    def run_block_events(self):
        rounds = 0
        while self._events and rounds < 65536:
            rounds += 1
            key = self._events.pop(0)
            self._event_keys.discard(key)
            pos, block, event_id, param = key
            state = self.raw(pos)
            if state is None or name_of(state) != block:
                continue
            try:
                if self.block(state).trigger_event(self, state, pos, event_id, param):
                    self.block_actions.append((pos, block, event_id, param))
            except RecursionError:
                logger.warning(f"Redstone update chain too deep at {pos}")

    # -------------------------------------------------------- block entities

    def tick_block_entities(self):
        for pos in list(self.moving_pistons):
            entity = self.moving_pistons.get(pos)
            if entity is not None:
                entity.tick(self)
