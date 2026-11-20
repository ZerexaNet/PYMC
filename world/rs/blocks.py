"""
Vanilla 1.21.1 redstone components (ports of the corresponding Block classes).

Directions passed to get_signal/get_direct_signal point from the querying
block towards the emitter (vanilla convention): a torch standing on a block is
asked with "up" by the block below it and answers 0.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..chunk_io import STATE_ID_TO_BLOCK
from .core import (
    AIR, AXIS, CLOCKWISE, COUNTER_CLOCKWISE, DIRECTIONS, EXTREMELY_HIGH, HIGH, HORIZONTAL,
    NORMAL, OPP, UPDATE_ALL, UPDATE_CLIENTS, UPDATE_INVISIBLE, UPDATE_KNOWN_SHAPE,
    VERTICAL, VERY_HIGH, default_state, java_hash_order, name_of, prop, props_of, rel, with_props,
)

# --------------------------------------------------------------------------
# block classes from blocks.json
# --------------------------------------------------------------------------

_NEVER_CONDUCT = {
    "piston", "sticky_piston", "piston_head", "moving_piston", "observer", "redstone_block",
    "soul_sand", "glowstone", "mud", "farmland", "dirt_path", "barrier", "spawner", "trial_spawner",
    "vault", "beacon", "shulker_box",
}
_ALWAYS_CONDUCT = {"ice", "frosted_ice", "packed_ice", "blue_ice"}


@lru_cache(maxsize=1)
def _shape_tables():
    from ..chunk_io import _find_blocks_json
    conductors, full, hardness = set(), set(), {}
    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        for block in json.load(f):
            name = block["name"]
            ids = range(block["minStateId"], block["maxStateId"] + 1)
            is_full = block.get("boundingBox") == "block"
            if is_full:
                full.update(ids)
            short = name
            if ((is_full and not block.get("transparent", False)) or short in _ALWAYS_CONDUCT) \
                    and short not in _NEVER_CONDUCT and not short.endswith("shulker_box"):
                conductors.update(ids)
            for i in ids:
                hardness[i] = float(block.get("hardness") if block.get("hardness") is not None else 0.0)
    return frozenset(conductors), frozenset(full), hardness


def is_conductor(state: int) -> bool:
    return bool(state) and state in _shape_tables()[0]


def is_full_block(state: int) -> bool:
    return bool(state) and state in _shape_tables()[1]


def destroy_speed(state: int) -> float:
    return _shape_tables()[2].get(state, 0.0)


def is_face_sturdy(state: int, face: str) -> bool:
    """Block.isFaceSturdy (FULL support) for the shapes redstone cares about."""
    if not state:
        return False
    if is_full_block(state):
        return True
    name = name_of(state)
    p = props_of(state)
    if name.endswith("_slab"):
        return p.get("type") == "double" or (p.get("type") == "top" and face == "up") \
            or (p.get("type") == "bottom" and face == "down")
    if name.endswith("_stairs"):
        return (face == "up" and p.get("half") == "top") or (face == "down" and p.get("half") == "bottom") \
            or face == p.get("facing")
    return False


def is_diode(state: int) -> bool:
    return name_of(state) in ("minecraft:repeater", "minecraft:comparator")


# --------------------------------------------------------------------------
# base behaviour
# --------------------------------------------------------------------------

class Block:
    """BlockBehaviour defaults."""

    name = "minecraft:air"

    def neighbor_changed(self, level, state, pos, source, from_pos, moved): pass
    def on_place(self, level, state, pos, old, moved): pass
    def on_remove(self, level, state, pos, new, moved): pass
    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos): return state
    def update_indirect_neighbour_shapes(self, level, state, pos, flags, recursion): pass
    def tick(self, level, state, pos): pass
    def use(self, level, state, pos, player) -> bool: return False
    def trigger_event(self, level, state, pos, event_id, param) -> bool: return False
    def get_signal(self, level, state, pos, direction) -> int: return 0
    def get_direct_signal(self, level, state, pos, direction) -> int: return 0
    def is_signal_source(self, state) -> bool: return False
    def has_analog_output(self, state) -> bool: return False
    def analog_output(self, level, state, pos) -> int: return 0
    def can_survive(self, level, state, pos) -> bool: return True


DEFAULT = Block()


# --------------------------------------------------------------------------
# attached blocks (torches, levers, buttons): drop when the support goes
# --------------------------------------------------------------------------

def _support_ok(level, pos, direction_to_support: str) -> bool:
    support = rel(pos, direction_to_support)
    return is_face_sturdy(level.get(support), OPP[direction_to_support])


# --------------------------------------------------------------------------
# redstone wire
# --------------------------------------------------------------------------

class RedstoneWire(Block):
    name = "minecraft:redstone_wire"
    should_signal = True

    # -- shape ------------------------------------------------------------
    @staticmethod
    def _connected(side: str) -> bool:
        return side != "none"

    def is_dot(self, state):
        p = props_of(state)
        return all(p.get(d) == "none" for d in HORIZONTAL)

    def is_cross(self, state):
        p = props_of(state)
        return all(self._connected(p.get(d, "none")) for d in HORIZONTAL)

    def cross_state(self, power: int):
        return with_props(default_state(self.name), north="side", east="side", south="side",
                          west="side", power=str(power))

    @staticmethod
    def can_survive_on(level, pos, state):
        return is_face_sturdy(state, "up") or name_of(state) == "minecraft:hopper"

    def can_survive(self, level, state, pos):
        below = rel(pos, "down")
        return self.can_survive_on(level, below, level.get(below))

    @staticmethod
    def should_connect_to(state, direction=None) -> bool:
        name = name_of(state)
        if name == "minecraft:redstone_wire":
            return True
        if name == "minecraft:repeater":
            facing = prop(state, "facing")
            return direction is not None and (facing == direction or facing == OPP[direction])
        if name == "minecraft:observer":
            return direction == prop(state, "facing")
        return direction is not None and _is_signal_source_state(state)

    def connecting_side(self, level, pos, direction, non_conductor_above=None) -> str:
        if non_conductor_above is None:
            non_conductor_above = not is_conductor(level.get(rel(pos, "up")))
        npos = rel(pos, direction)
        nstate = level.get(npos)
        if non_conductor_above:
            trapdoor = name_of(nstate).endswith("_trapdoor")
            if (trapdoor or self.can_survive_on(level, npos, nstate)) \
                    and self.should_connect_to(level.get(rel(npos, "up"))):
                if is_face_sturdy(nstate, OPP[direction]):
                    return "up"
                return "side"
        if not self.should_connect_to(nstate, direction) and (
                is_conductor(nstate) or not self.should_connect_to(level.get(rel(npos, "down")))):
            return "none"
        return "side"

    def missing_connections(self, level, state, pos):
        non_conductor_above = not is_conductor(level.get(rel(pos, "up")))
        changes = {}
        p = props_of(state)
        for direction in HORIZONTAL:
            if not self._connected(p.get(direction, "none")):
                changes[direction] = self.connecting_side(level, pos, direction, non_conductor_above)
        return with_props(state, **changes) if changes else state

    def connection_state(self, level, state, pos):
        dot = self.is_dot(state)
        state = self.missing_connections(level, with_props(default_state(self.name), power=prop(state, "power", "0")), pos)
        if dot and self.is_dot(state):
            return state
        p = props_of(state)
        north, south = self._connected(p["north"]), self._connected(p["south"])
        east, west = self._connected(p["east"]), self._connected(p["west"])
        no_ns = not north and not south
        no_ew = not east and not west
        changes = {}
        if not west and no_ns:
            changes["west"] = "side"
        if not east and no_ns:
            changes["east"] = "side"
        if not north and no_ew:
            changes["north"] = "side"
        if not south and no_ew:
            changes["south"] = "side"
        return with_props(state, **changes) if changes else state

    def placement_state(self, level, pos):
        return self.connection_state(level, self.cross_state(0), pos)

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down":
            return state if self.can_survive_on(level, neighbor_pos, neighbor_state) else AIR
        if direction == "up":
            return self.connection_state(level, state, pos)
        side = self.connecting_side(level, pos, direction)
        if self._connected(side) == self._connected(prop(state, direction, "none")) and not self.is_cross(state):
            return with_props(state, **{direction: side})
        return self.connection_state(
            level, with_props(self.cross_state(int(prop(state, "power", 0))), **{direction: side}), pos)

    def update_indirect_neighbour_shapes(self, level, state, pos, flags, recursion):
        for direction in HORIZONTAL:
            if prop(state, direction, "none") == "none":
                continue
            if name_of(level.get(rel(pos, direction))) == self.name:
                continue
            for vertical in ("down", "up"):
                npos = rel(rel(pos, direction), vertical)
                if name_of(level.get(npos)) == self.name:
                    other = rel(npos, OPP[direction])
                    level.neighbor_shape_changed(OPP[direction], level.get(other), npos, other, flags, recursion)

    def use(self, level, state, pos, player) -> bool:
        if not (self.is_cross(state) or self.is_dot(state)):
            return False
        power = int(prop(state, "power", 0))
        new = with_props(default_state(self.name), power=str(power)) if self.is_cross(state) else self.cross_state(power)
        new = self.connection_state(level, new, pos)
        if new != state:
            level.set_block(pos, new, UPDATE_ALL)
            self._updates_on_shape_change(level, pos, state, new)
            return True
        return False

    def _updates_on_shape_change(self, level, pos, old, new):
        for direction in HORIZONTAL:
            npos = rel(pos, direction)
            if self._connected(prop(old, direction, "none")) != self._connected(prop(new, direction, "none")) \
                    and is_conductor(level.get(npos)):
                level.update_neighbors_at_except(npos, self.name, OPP[direction])

    # -- power ------------------------------------------------------------
    def wire_signal(self, state) -> int:
        return int(prop(state, "power", 0)) if name_of(state) == self.name else 0

    def calculate_target_strength(self, level, pos) -> int:
        RedstoneWire.should_signal = False
        i = level.get_best_neighbor_signal(pos)
        RedstoneWire.should_signal = True
        j = 0
        if i < 15:
            above_conducts = is_conductor(level.get(rel(pos, "up")))
            for direction in HORIZONTAL:
                npos = rel(pos, direction)
                nstate = level.get(npos)
                j = max(j, self.wire_signal(nstate))
                if is_conductor(nstate):
                    if not above_conducts:
                        j = max(j, self.wire_signal(level.get(rel(npos, "up"))))
                else:
                    j = max(j, self.wire_signal(level.get(rel(npos, "down"))))
        return max(i, j - 1)

    def update_power_strength(self, level, pos, state):
        i = self.calculate_target_strength(level, pos)
        if int(prop(state, "power", 0)) != i:
            if level.get(pos) == state:
                level.set_block(pos, with_props(state, power=str(i)), UPDATE_CLIENTS)
            positions = [pos] + [rel(pos, d) for d in DIRECTIONS]
            for p in java_hash_order(positions):
                level.update_neighbors_at(p, self.name)

    def check_corner_change_at(self, level, pos):
        if name_of(level.get(pos)) == self.name:
            level.update_neighbors_at(pos, self.name)
            for direction in DIRECTIONS:
                level.update_neighbors_at(rel(pos, direction), self.name)

    def update_neighbors_of_neighboring_wires(self, level, pos):
        for direction in HORIZONTAL:
            self.check_corner_change_at(level, rel(pos, direction))
        for direction in HORIZONTAL:
            npos = rel(pos, direction)
            if is_conductor(level.get(npos)):
                self.check_corner_change_at(level, rel(npos, "up"))
            else:
                self.check_corner_change_at(level, rel(npos, "down"))

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name:
            self.update_power_strength(level, pos, state)
            for direction in VERTICAL:
                level.update_neighbors_at(rel(pos, direction), self.name)
            self.update_neighbors_of_neighboring_wires(level, pos)

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name:
            for direction in DIRECTIONS:
                level.update_neighbors_at(rel(pos, direction), self.name)
            self.update_power_strength(level, pos, state)
            self.update_neighbors_of_neighboring_wires(level, pos)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if self.can_survive(level, state, pos):
            self.update_power_strength(level, pos, state)
        else:
            level.drop_resources(state, pos)
            level.remove_block(pos)

    def get_signal(self, level, state, pos, direction) -> int:
        if not RedstoneWire.should_signal or direction == "down":
            return 0
        power = int(prop(state, "power", 0))
        if power == 0:
            return 0
        if direction != "up" and not self._connected(
                prop(self.connection_state(level, state, pos), OPP[direction], "none")):
            return 0
        return power

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return self.get_signal(level, state, pos, direction) if RedstoneWire.should_signal else 0

    def is_signal_source(self, state) -> bool:
        return RedstoneWire.should_signal


# --------------------------------------------------------------------------
# redstone torches
# --------------------------------------------------------------------------

class RedstoneTorch(Block):
    name = "minecraft:redstone_torch"
    wall = False
    _toggles: dict = {}     # pos -> [game times], RedstoneTorchBlock.RECENT_TOGGLES

    def attached_direction(self, state) -> str:
        """Direction from the torch to the block it hangs on."""
        return OPP[prop(state, "facing")] if self.wall else "down"

    def can_survive(self, level, state, pos):
        return _support_ok(level, pos, self.attached_direction(state))

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == self.attached_direction(state) and not self.can_survive(level, state, pos):
            return AIR
        return state

    def has_neighbor_signal(self, level, pos, state) -> bool:
        d = self.attached_direction(state)
        return level.has_signal(rel(pos, d), d)

    def on_place(self, level, state, pos, old, moved):
        for direction in DIRECTIONS:
            level.update_neighbors_at(rel(pos, direction), self.name)

    def on_remove(self, level, state, pos, new, moved):
        if not moved:
            for direction in DIRECTIONS:
                level.update_neighbors_at(rel(pos, direction), self.name)

    def get_signal(self, level, state, pos, direction) -> int:
        if prop(state, "lit") != "true":
            return 0
        if self.wall:
            return 0 if prop(state, "facing") == direction else 15
        return 0 if direction == "up" else 15

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return self.get_signal(level, state, pos, direction) if direction == "down" else 0

    def is_signal_source(self, state) -> bool:
        return True

    def _toggled_too_often(self, level, pos, log: bool) -> bool:
        toggles = self._toggles.setdefault(pos, [])
        if log:
            toggles.append(level.game_time)
        return len(toggles) >= 8

    def tick(self, level, state, pos):
        powered = self.has_neighbor_signal(level, pos, state)
        toggles = self._toggles.get(pos)
        if toggles:
            while toggles and level.game_time - toggles[0] > 60:
                toggles.pop(0)
        if prop(state, "lit") == "true":
            if powered:
                level.set_block(pos, with_props(state, lit="false"), UPDATE_ALL)
                if self._toggled_too_often(level, pos, True):
                    level.effects.append(("torch_burnout", {"pos": pos}))
                    level.schedule_tick(pos, self.name, 160)
        elif not powered and not self._toggled_too_often(level, pos, False):
            level.set_block(pos, with_props(state, lit="true"), UPDATE_ALL)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if (prop(state, "lit") == "true") == self.has_neighbor_signal(level, pos, state) \
                and not level.will_tick_this_tick(pos, self.name):
            level.schedule_tick(pos, self.name, 2)


class RedstoneWallTorch(RedstoneTorch):
    name = "minecraft:redstone_wall_torch"
    wall = True


# --------------------------------------------------------------------------
# diodes: repeater and comparator
# --------------------------------------------------------------------------

class Diode(Block):
    side_inputs_diodes_only = True

    def can_survive(self, level, state, pos):
        return is_face_sturdy(level.get(rel(pos, "down")), "up")

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down" and not self.can_survive(level, state, pos):
            return AIR
        return state

    def delay(self, state) -> int:
        return 2

    def output_signal(self, level, pos, state) -> int:
        return 15

    def input_signal(self, level, pos, state) -> int:
        direction = prop(state, "facing")
        npos = rel(pos, direction)
        i = level.get_signal(npos, direction)
        if i >= 15:
            return i
        nstate = level.get(npos)
        return max(i, int(prop(nstate, "power", 0)) if name_of(nstate) == "minecraft:redstone_wire" else 0)

    def alternate_signal(self, level, pos, state) -> int:
        facing = prop(state, "facing")
        d1, d2 = CLOCKWISE[facing], COUNTER_CLOCKWISE[facing]
        only = self.side_inputs_diodes_only
        return max(level.get_control_input_signal(rel(pos, d1), d1, only),
                   level.get_control_input_signal(rel(pos, d2), d2, only))

    def is_locked(self, level, pos, state) -> bool:
        return False

    def should_turn_on(self, level, pos, state) -> bool:
        return self.input_signal(level, pos, state) > 0

    def should_prioritize(self, level, pos, state) -> bool:
        direction = OPP[prop(state, "facing")]
        front = level.get(rel(pos, direction))
        return is_diode(front) and prop(front, "facing") != direction

    def check_tick_on_neighbor(self, level, pos, state):
        if self.is_locked(level, pos, state):
            return
        powered = prop(state, "powered") == "true"
        on = self.should_turn_on(level, pos, state)
        if powered != on and not level.will_tick_this_tick(pos, self.name):
            priority = HIGH
            if self.should_prioritize(level, pos, state):
                priority = EXTREMELY_HIGH
            elif powered:
                priority = VERY_HIGH
            level.schedule_tick(pos, self.name, self.delay(state), priority)

    def tick(self, level, state, pos):
        if self.is_locked(level, pos, state):
            return
        powered = prop(state, "powered") == "true"
        on = self.should_turn_on(level, pos, state)
        if powered and not on:
            level.set_block(pos, with_props(state, powered="false"), UPDATE_CLIENTS)
        elif not powered:
            level.set_block(pos, with_props(state, powered="true"), UPDATE_CLIENTS)
            if not on:
                level.schedule_tick(pos, self.name, self.delay(state), VERY_HIGH)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if self.can_survive(level, state, pos):
            self.check_tick_on_neighbor(level, pos, state)
        else:
            level.drop_resources(state, pos)
            level.remove_block(pos)
            for direction in DIRECTIONS:
                level.update_neighbors_at(rel(pos, direction), self.name)

    def get_signal(self, level, state, pos, direction) -> int:
        if prop(state, "powered") != "true":
            return 0
        return self.output_signal(level, pos, state) if prop(state, "facing") == direction else 0

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return self.get_signal(level, state, pos, direction)

    def is_signal_source(self, state) -> bool:
        return True

    def update_neighbors_in_front(self, level, pos, state):
        facing = prop(state, "facing")
        front = rel(pos, OPP[facing])
        level.neighbor_changed(front, self.name, pos)
        level.update_neighbors_at_except(front, self.name, facing)

    def on_place(self, level, state, pos, old, moved):
        self.update_neighbors_in_front(level, pos, state)

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name:
            self.update_neighbors_in_front(level, pos, state)

    def on_placed_by_player(self, level, state, pos):
        if self.should_turn_on(level, pos, state):
            level.schedule_tick(pos, self.name, 1)


class Repeater(Diode):
    name = "minecraft:repeater"

    def delay(self, state) -> int:
        return int(prop(state, "delay", 1)) * 2

    def is_locked(self, level, pos, state) -> bool:
        return self.alternate_signal(level, pos, state) > 0

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down" and not self.can_survive(level, state, pos):
            return AIR
        if AXIS[direction] != AXIS[prop(state, "facing")]:
            return with_props(state, locked="true" if self.is_locked(level, pos, state) else "false")
        return state

    def use(self, level, state, pos, player) -> bool:
        delay = int(prop(state, "delay", 1)) % 4 + 1
        level.set_block(pos, with_props(state, delay=str(delay)), UPDATE_ALL)
        return True


class Comparator(Diode):
    name = "minecraft:comparator"
    side_inputs_diodes_only = False

    def output_signal(self, level, pos, state) -> int:
        return level.comparator_output.get(pos, 0)

    def input_signal(self, level, pos, state) -> int:
        i = super().input_signal(level, pos, state)
        direction = prop(state, "facing")
        npos = rel(pos, direction)
        nstate = level.get(npos)
        behaviour = level.block(nstate)
        if behaviour.has_analog_output(nstate):
            i = behaviour.analog_output(level, nstate, npos)
        elif i < 15 and is_conductor(nstate):
            npos = rel(npos, direction)
            nstate = level.get(npos)
            behaviour = level.block(nstate)
            if behaviour.has_analog_output(nstate):
                i = behaviour.analog_output(level, nstate, npos)
        return i

    def calculate_output(self, level, pos, state) -> int:
        i = self.input_signal(level, pos, state)
        if i == 0:
            return 0
        j = self.alternate_signal(level, pos, state)
        if j > i:
            return 0
        return i - j if prop(state, "mode") == "subtract" else i

    def should_turn_on(self, level, pos, state) -> bool:
        i = self.input_signal(level, pos, state)
        if i == 0:
            return False
        j = self.alternate_signal(level, pos, state)
        return i > j or (i == j and prop(state, "mode") == "compare")

    def check_tick_on_neighbor(self, level, pos, state):
        if level.will_tick_this_tick(pos, self.name):
            return
        i = self.calculate_output(level, pos, state)
        j = level.comparator_output.get(pos, 0)
        if i != j or (prop(state, "powered") == "true") != self.should_turn_on(level, pos, state):
            priority = HIGH if self.should_prioritize(level, pos, state) else NORMAL
            level.schedule_tick(pos, self.name, 2, priority)

    def refresh_output_state(self, level, pos, state):
        i = self.calculate_output(level, pos, state)
        j = level.comparator_output.get(pos, 0)
        level.comparator_output[pos] = i
        if j != i or prop(state, "mode") == "compare":
            on = self.should_turn_on(level, pos, state)
            powered = prop(state, "powered") == "true"
            if powered and not on:
                level.set_block(pos, with_props(state, powered="false"), UPDATE_CLIENTS)
            elif not powered and on:
                level.set_block(pos, with_props(state, powered="true"), UPDATE_CLIENTS)
            self.update_neighbors_in_front(level, pos, level.get(pos))

    def tick(self, level, state, pos):
        self.refresh_output_state(level, pos, state)

    def use(self, level, state, pos, player) -> bool:
        state = with_props(state, mode="compare" if prop(state, "mode") == "subtract" else "subtract")
        level.set_block(pos, state, UPDATE_CLIENTS)
        self.refresh_output_state(level, pos, state)
        return True

    def on_remove(self, level, state, pos, new, moved):
        super().on_remove(level, state, pos, new, moved)
        if name_of(new) != self.name:
            level.comparator_output.pop(pos, None)


# --------------------------------------------------------------------------
# observer
# --------------------------------------------------------------------------

class Observer(Block):
    name = "minecraft:observer"

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if prop(state, "facing") == direction and prop(state, "powered") != "true":
            self.start_signal(level, pos)
        return state

    def start_signal(self, level, pos):
        if not level.has_scheduled_tick(pos, self.name):
            level.schedule_tick(pos, self.name, 2)

    def tick(self, level, state, pos):
        if prop(state, "powered") == "true":
            state = with_props(state, powered="false")
            level.set_block(pos, state, UPDATE_CLIENTS)
        else:
            state = with_props(state, powered="true")
            level.set_block(pos, state, UPDATE_CLIENTS)
            level.schedule_tick(pos, self.name, 2)
        self.update_neighbors_in_front(level, pos, state)

    def update_neighbors_in_front(self, level, pos, state):
        facing = prop(state, "facing")
        behind = rel(pos, OPP[facing])
        level.neighbor_changed(behind, self.name, pos)
        level.update_neighbors_at_except(behind, self.name, facing)

    def get_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" and prop(state, "facing") == direction else 0

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return self.get_signal(level, state, pos, direction)

    def is_signal_source(self, state) -> bool:
        return True

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name and prop(state, "powered") == "true" \
                and not level.has_scheduled_tick(pos, self.name):
            new = with_props(state, powered="false")
            level.set_block(pos, new, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE)
            self.update_neighbors_in_front(level, pos, new)

    def on_remove(self, level, state, pos, new, moved):
        if name_of(new) != self.name and prop(state, "powered") == "true" \
                and level.has_scheduled_tick(pos, self.name):
            self.update_neighbors_in_front(level, pos, with_props(state, powered="false"))


# --------------------------------------------------------------------------
# levers, buttons, pressure plates, redstone block, target
# --------------------------------------------------------------------------

def _connected_direction(state) -> str:
    """FaceAttachedHorizontalDirectionalBlock.getConnectedDirection (towards the block in front)."""
    face = prop(state, "face")
    if face == "ceiling":
        return "down"
    if face == "floor":
        return "up"
    return prop(state, "facing")


class FaceAttached(Block):
    def can_survive(self, level, state, pos):
        return _support_ok(level, pos, OPP[_connected_direction(state)])

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if OPP[_connected_direction(state)] == direction and not self.can_survive(level, state, pos):
            return AIR
        return state

    def update_neighbours(self, level, state, pos):
        level.update_neighbors_at(pos, self.name)
        level.update_neighbors_at(rel(pos, OPP[_connected_direction(state)]), self.name)

    def get_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" else 0

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" and _connected_direction(state) == direction else 0

    def is_signal_source(self, state) -> bool:
        return True

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != name_of(state) and prop(state, "powered") == "true":
            self.update_neighbours(level, state, pos)


class Lever(FaceAttached):
    name = "minecraft:lever"

    def use(self, level, state, pos, player) -> bool:
        state = with_props(state, powered="false" if prop(state, "powered") == "true" else "true")
        level.set_block(pos, state, UPDATE_ALL)
        self.update_neighbours(level, state, pos)
        level.effects.append(("sound", {"pos": pos, "sound": "minecraft:block.lever.click",
                                        "pitch": 0.6 if prop(state, "powered") == "true" else 0.5}))
        return True


class Button(FaceAttached):
    def __init__(self, name: str, ticks: int):
        self.name = name
        self.ticks = ticks

    def use(self, level, state, pos, player) -> bool:
        if prop(state, "powered") == "true":
            return True
        state = with_props(state, powered="true")
        level.set_block(pos, state, UPDATE_ALL)
        self.update_neighbours(level, state, pos)
        level.schedule_tick(pos, self.name, self.ticks)
        level.effects.append(("sound", {"pos": pos, "sound": "minecraft:block.stone_button.click_on"
                                        if "stone" in self.name else "minecraft:block.wooden_button.click_on"}))
        return True

    def tick(self, level, state, pos):
        if prop(state, "powered") == "true":
            state = with_props(state, powered="false")
            level.set_block(pos, state, UPDATE_ALL)
            self.update_neighbours(level, state, pos)


class PressurePlate(Block):
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind      # wood (any entity), stone (living), light / heavy (weighted)

    def can_survive(self, level, state, pos):
        below = level.get(rel(pos, "down"))
        return is_face_sturdy(below, "up") or name_of(below).endswith("_fence")

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down" and not self.can_survive(level, state, pos):
            return AIR
        return state

    def signal_of(self, state) -> int:
        if "power" in props_of(state):
            return int(prop(state, "power", 0))
        return 15 if prop(state, "powered") == "true" else 0

    def with_signal(self, state, signal: int):
        if "power" in props_of(state):
            return with_props(state, power=str(signal))
        return with_props(state, powered="true" if signal > 0 else "false")

    def signal_strength(self, level, pos) -> int:
        count = 0
        server = level.server
        x, y, z = pos
        for player in server.get_online_players() if hasattr(server, "get_online_players") else ():
            if getattr(player, "gamemode", "") == "spectator" or getattr(player, "_dead", False):
                continue
            if x - 0.3 < player.x < x + 1.3 and z - 0.3 < player.z < z + 1.3 and y - 0.1 <= player.y < y + 0.3:
                count += 1
        manager = getattr(server, "entity_manager", None)
        if manager is not None:
            for entity in manager.list_entities():
                if self.kind == "stone" and entity.kind != "mob":
                    continue
                if x <= entity.x < x + 1 and z <= entity.z < z + 1 and y - 0.1 <= entity.y < y + 0.3:
                    count += int(entity.metadata.get("count", 1)) if entity.kind == "item" else 1
        if self.kind == "light":
            return min(count, 15)
        if self.kind == "heavy":
            return min((count + 9) // 10, 15) if count else 0
        return 15 if count else 0

    def check_pressed(self, level, pos, state, current: int):
        signal = self.signal_strength(level, pos)
        if signal != current:
            state = self.with_signal(state, signal)
            level.set_block(pos, state, UPDATE_CLIENTS)
            level.update_neighbors_at(pos, self.name)
            level.update_neighbors_at(rel(pos, "down"), self.name)
        if signal > 0:
            level.schedule_tick(pos, self.name, 10 if self.kind in ("light", "heavy") else 20)

    def entity_inside(self, level, state, pos):
        current = self.signal_of(state)
        if current == 0:
            self.check_pressed(level, pos, state, current)

    def tick(self, level, state, pos):
        current = self.signal_of(state)
        if current > 0:
            self.check_pressed(level, pos, state, current)

    def get_signal(self, level, state, pos, direction) -> int:
        return self.signal_of(state)

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return self.signal_of(state) if direction == "up" else 0

    def is_signal_source(self, state) -> bool:
        return True

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name and self.signal_of(state) > 0:
            level.update_neighbors_at(pos, self.name)
            level.update_neighbors_at(rel(pos, "down"), self.name)


class RedstoneBlock(Block):
    name = "minecraft:redstone_block"

    def get_signal(self, level, state, pos, direction) -> int:
        return 15

    def is_signal_source(self, state) -> bool:
        return True


class Target(Block):
    name = "minecraft:target"

    def get_signal(self, level, state, pos, direction) -> int:
        return int(prop(state, "power", 0))

    def is_signal_source(self, state) -> bool:
        return True

    def tick(self, level, state, pos):
        if int(prop(state, "power", 0)) != 0:
            level.set_block(pos, with_props(state, power="0"), UPDATE_ALL)


# --------------------------------------------------------------------------
# consumers: lamp, TNT, note block, doors, trapdoors, gates, dispensers, hoppers
# --------------------------------------------------------------------------

class RedstoneLamp(Block):
    name = "minecraft:redstone_lamp"

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        lit = prop(state, "lit") == "true"
        if lit != level.has_neighbor_signal(pos):
            if lit:
                level.schedule_tick(pos, self.name, 4)
            else:
                level.set_block(pos, with_props(state, lit="true"), UPDATE_CLIENTS)

    def tick(self, level, state, pos):
        if prop(state, "lit") == "true" and not level.has_neighbor_signal(pos):
            level.set_block(pos, with_props(state, lit="false"), UPDATE_CLIENTS)


class Tnt(Block):
    name = "minecraft:tnt"

    def _prime(self, level, pos):
        manager = getattr(level.server, "entity_manager", None)
        if manager is not None:
            manager.create_tnt(pos[0] + 0.5, pos[1], pos[2] + 0.5)
        level.remove_block(pos)

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name and level.has_neighbor_signal(pos):
            self._prime(level, pos)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if level.has_neighbor_signal(pos):
            self._prime(level, pos)


_INSTRUMENT_BELOW = (
    (("stone", "cobblestone", "deepslate", "andesite", "diorite", "granite", "netherrack", "basalt",
      "obsidian", "bricks", "terracotta", "concrete", "blackstone", "end_stone", "_ore", "quartz",
      "prismarine", "purpur", "tuff", "calcite", "sandstone"), "basedrum"),
    (("sand", "gravel", "concrete_powder", "suspicious"), "snare"),
    (("glass", "sea_lantern", "beacon"), "hat"),
    (("_planks", "_log", "_wood", "_stem", "_hyphae", "bookshelf", "chest", "crafting_table",
      "note_block", "jukebox", "barrel", "_fence", "_sign", "banner"), "bass"),
    (("clay",), "flute"), (("gold_block",), "bell"), (("_wool",), "guitar"),
    (("packed_ice",), "chime"), (("bone_block",), "xylophone"), (("iron_block",), "iron_xylophone"),
    (("soul_sand",), "cow_bell"), (("pumpkin",), "didgeridoo"), (("emerald_block",), "bit"),
    (("hay_block",), "banjo"), (("glowstone",), "pling"),
)


def _instrument(level, pos) -> str:
    below = name_of(level.get(rel(pos, "down"))).split(":")[1]
    for suffixes, instrument in _INSTRUMENT_BELOW:
        if any(s in below for s in suffixes):
            return instrument
    return "harp"


class NoteBlock(Block):
    name = "minecraft:note_block"

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down":
            return with_props(state, instrument=_instrument(level, pos))
        return state

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        powered = level.has_neighbor_signal(pos)
        if powered != (prop(state, "powered") == "true"):
            if powered:
                self.play(level, state, pos)
            level.set_block(pos, with_props(state, powered="true" if powered else "false"), UPDATE_ALL)

    def play(self, level, state, pos):
        if level.get(rel(pos, "up")) == AIR:
            level.block_event(pos, self.name, 0, 0)

    def use(self, level, state, pos, player) -> bool:
        state = with_props(state, note=str((int(prop(state, "note", 0)) + 1) % 25))
        level.set_block(pos, state, UPDATE_ALL)
        self.play(level, state, pos)
        return True

    def trigger_event(self, level, state, pos, event_id, param) -> bool:
        level.effects.append(("note", {"x": pos[0], "y": pos[1], "z": pos[2],
                                       "note": int(prop(state, "note", 0))}))
        return True


class Door(Block):
    def __init__(self, name: str):
        self.name = name

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        half = prop(state, "half")
        if AXIS[direction] == "y" and (half == "lower") == (direction == "up"):
            if name_of(neighbor_state) == self.name and prop(neighbor_state, "half") != half:
                return with_props(neighbor_state, half=half)
            return AIR
        if half == "lower" and direction == "down" and not is_face_sturdy(neighbor_state, "up"):
            return AIR
        return state

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        other = rel(pos, "up" if prop(state, "half") == "lower" else "down")
        powered = level.has_neighbor_signal(pos) or level.has_neighbor_signal(other)
        if source != self.name and powered != (prop(state, "powered") == "true"):
            level.set_block(pos, with_props(state, powered=str(powered).lower(), open=str(powered).lower()),
                            UPDATE_CLIENTS)


class Trapdoor(Block):
    def __init__(self, name: str):
        self.name = name

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        powered = level.has_neighbor_signal(pos)
        if powered != (prop(state, "powered") == "true"):
            changes = {"powered": str(powered).lower()}
            if (prop(state, "open") == "true") != powered:
                changes["open"] = str(powered).lower()
            level.set_block(pos, with_props(state, **changes), UPDATE_CLIENTS)


class FenceGate(Block):
    def __init__(self, name: str):
        self.name = name

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        powered = level.has_neighbor_signal(pos)
        if (prop(state, "powered") == "true") != powered:
            level.set_block(pos, with_props(state, powered=str(powered).lower(), open=str(powered).lower()),
                            UPDATE_CLIENTS)


class Dispenser(Block):
    def __init__(self, name: str):
        self.name = name

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        powered = level.has_neighbor_signal(pos) or level.has_neighbor_signal(rel(pos, "up"))
        triggered = prop(state, "triggered") == "true"
        if powered and not triggered:
            level.schedule_tick(pos, self.name, 4)
            level.set_block(pos, with_props(state, triggered="true"), UPDATE_INVISIBLE)
        elif not powered and triggered:
            level.set_block(pos, with_props(state, triggered="false"), UPDATE_INVISIBLE)

    def tick(self, level, state, pos):
        level.effects.append(("dispense", {"pos": pos, "facing": prop(state, "facing"), "block": self.name}))

    def has_analog_output(self, state) -> bool:
        return True

    def analog_output(self, level, state, pos) -> int:
        return container_signal(pos)


class Hopper(Block):
    name = "minecraft:hopper"

    def _check(self, level, state, pos):
        enabled = not level.has_neighbor_signal(pos)
        if enabled != (prop(state, "enabled") == "true"):
            level.set_block(pos, with_props(state, enabled=str(enabled).lower()), UPDATE_INVISIBLE)

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name:
            self._check(level, state, pos)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        self._check(level, state, pos)

    def has_analog_output(self, state) -> bool:
        return True

    def analog_output(self, level, state, pos) -> int:
        return container_signal(pos)


class Container(Block):
    def __init__(self, name: str):
        self.name = name

    def has_analog_output(self, state) -> bool:
        return True

    def analog_output(self, level, state, pos) -> int:
        return container_signal(pos)


_CHEST_CW = {"north": "east", "east": "south", "south": "west", "west": "north"}
_CHEST_CCW = {v: k for k, v in _CHEST_CW.items()}


class ChestBlock(Container):
    """ChestBlock.updateShape: double chests join and split through shape updates."""

    @staticmethod
    def connected_direction(state):
        facing = prop(state, "facing")
        if facing not in _CHEST_CW:
            return None
        return _CHEST_CW[facing] if prop(state, "type") == "left" else _CHEST_CCW[facing]

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if name_of(neighbor_state) == self.name and direction in _CHEST_CW:
            other = prop(neighbor_state, "type")
            if prop(state, "type") == "single" and other != "single" \
                    and prop(state, "facing") == prop(neighbor_state, "facing") \
                    and self.connected_direction(neighbor_state) == OPP[direction]:
                return with_props(state, type="right" if other == "left" else "left")
        elif self.connected_direction(state) == direction:
            return with_props(state, type="single")
        return state


class Composter(Block):
    """ComposterBlock: level 7 becomes ready (8) after 20 ticks; comparators read the level."""
    name = "minecraft:composter"

    def on_place(self, level, state, pos, old, moved):
        if prop(state, "level") == "7":
            level.schedule_tick(pos, self.name, 20)

    def tick(self, level, state, pos):
        if prop(state, "level") == "7":
            level.set_block(pos, with_props(state, level="8"), UPDATE_ALL)
            level.effects.append(("sound", {"pos": pos, "sound": "minecraft:block.composter.ready"}))

    def has_analog_output(self, state) -> bool:
        return True

    def analog_output(self, level, state, pos) -> int:
        return int(prop(state, "level", 0))


def container_signal(pos) -> int:
    """AbstractContainerMenu.getRedstoneSignalFromContainer (double chests count as one)."""
    from ..block_behavior import container_view
    container = container_view(*pos)
    if container is None or not len(container.items):
        return 0
    fill = 0.0
    any_items = False
    for stack in container.items:
        if stack is None or stack.is_empty:
            continue
        fill += stack.count / float(max(1, min(64, stack.max_stack_size)))
        any_items = True
    fill /= len(container.items)
    return int(fill * 14.0) + (1 if any_items else 0)


class LeveledAnalog(Block):
    """Cauldrons, composters, cake, respawn anchors: comparator output from a property."""

    def __init__(self, name: str, key: str, scale=None):
        self.name = name
        self.key = key
        self.scale = scale

    def has_analog_output(self, state) -> bool:
        return True

    def analog_output(self, level, state, pos) -> int:
        value = int(prop(state, self.key, 0))
        return self.scale(value) if self.scale else value


# --------------------------------------------------------------------------
# powered / activator rails
# --------------------------------------------------------------------------

class BaseRail(Block):
    """BaseRailBlock: rails pop without support; straight rails update their surroundings when removed."""

    def __init__(self, name: str, straight: bool):
        self.name = name
        self.straight = straight

    @staticmethod
    def _ascending_support(shape):
        return {"ascending_east": "east", "ascending_west": "west",
                "ascending_north": "north", "ascending_south": "south"}.get(shape)

    def should_be_removed(self, level, pos, state) -> bool:
        if not is_face_sturdy(level.get(rel(pos, "down")), "up"):
            return True
        side = self._ascending_support(prop(state, "shape", ""))
        return side is not None and not is_face_sturdy(level.get(rel(pos, side)), "up")

    def update_state(self, level, state, pos, source):
        if self.straight:
            level.neighbor_changed(pos, self.name, pos)

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name:
            self.update_state(level, state, pos, self.name)

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if name_of(level.get(pos)) != self.name:
            return
        if self.should_be_removed(level, pos, state):
            level.drop_resources(state, pos)
            level.remove_block(pos, moved)
        else:
            self.rail_neighbor_update(level, state, pos, source)

    def rail_neighbor_update(self, level, state, pos, source):
        pass

    def on_remove(self, level, state, pos, new, moved):
        if moved:
            return
        if prop(state, "shape", "").startswith("ascending"):
            level.update_neighbors_at(rel(pos, "up"), self.name)
        if self.straight:
            level.update_neighbors_at(pos, self.name)
            level.update_neighbors_at(rel(pos, "down"), self.name)


class PoweredRail(BaseRail):
    """PoweredRailBlock (powered and activator rails)."""

    def __init__(self, name: str):
        super().__init__(name, True)

    def _find_signal(self, level, pos, state, forward: bool, distance: int) -> bool:
        if distance >= 8:
            return False
        x, y, z = pos
        ascend = True
        shape = prop(state, "shape")
        if shape == "north_south":
            z += -1 if forward else 1
        elif shape == "east_west":
            x += 1 if not forward else -1
        elif shape == "ascending_east":
            if forward:
                x -= 1
            else:
                x += 1; y += 1; ascend = False
            shape = "east_west"
        elif shape == "ascending_west":
            if forward:
                x -= 1; y += 1; ascend = False
            else:
                x += 1
            shape = "east_west"
        elif shape == "ascending_north":
            if forward:
                z += 1
            else:
                z -= 1; y += 1; ascend = False
            shape = "north_south"
        elif shape == "ascending_south":
            if forward:
                z += 1; y += 1; ascend = False
            else:
                z -= 1
            shape = "north_south"
        else:
            return False
        if self._is_same_rail_with_power(level, (x, y, z), forward, distance, shape):
            return True
        return ascend and self._is_same_rail_with_power(level, (x, y - 1, z), forward, distance, shape)

    def _is_same_rail_with_power(self, level, pos, forward, distance, shape) -> bool:
        state = level.get(pos)
        if name_of(state) != self.name:
            return False
        other = prop(state, "shape")
        if shape == "east_west" and other in ("north_south", "ascending_north", "ascending_south"):
            return False
        if shape == "north_south" and other in ("east_west", "ascending_east", "ascending_west"):
            return False
        if prop(state, "powered") != "true":
            return False
        return level.has_neighbor_signal(pos) or self._find_signal(level, pos, state, forward, distance + 1)

    def rail_neighbor_update(self, level, state, pos, source):
        powered = prop(state, "powered") == "true"
        should = level.has_neighbor_signal(pos) or self._find_signal(level, pos, state, True, 0) \
            or self._find_signal(level, pos, state, False, 0)
        if should != powered:
            level.set_block(pos, with_props(state, powered=str(should).lower()), UPDATE_ALL)
            level.update_neighbors_at(rel(pos, "down"), self.name)
            if prop(state, "shape", "").startswith("ascending"):
                level.update_neighbors_at(rel(pos, "up"), self.name)


_RAIL_LINKS = {
    "north_south": ((0, 0, -1), (0, 0, 1)), "east_west": ((-1, 0, 0), (1, 0, 0)),
    "ascending_east": ((-1, 0, 0), (1, 1, 0)), "ascending_west": ((-1, 1, 0), (1, 0, 0)),
    "ascending_north": ((0, 1, -1), (0, 0, 1)), "ascending_south": ((0, 0, -1), (0, 1, 1)),
    "south_east": ((0, 0, 1), (1, 0, 0)), "south_west": ((0, 0, 1), (-1, 0, 0)),
    "north_west": ((0, 0, -1), (-1, 0, 0)), "north_east": ((0, 0, -1), (1, 0, 0)),
}


class DetectorRail(BaseRail):
    """DetectorRailBlock: powered while a minecart is on it; comparators read a container minecart."""

    def __init__(self, name: str):
        super().__init__(name, True)

    @staticmethod
    def _minecarts(level, pos) -> list:
        from ..minecart import detector_minecarts
        return detector_minecarts(level.server, *pos)

    def entity_inside(self, level, state, pos):
        if prop(state, "powered") != "true":
            self._check_pressed(level, pos, state)

    def tick(self, level, state, pos):
        if prop(state, "powered") == "true":
            self._check_pressed(level, pos, state)

    def _check_pressed(self, level, pos, state):
        if self.should_be_removed(level, pos, state):
            return
        powered = prop(state, "powered") == "true"
        found = bool(self._minecarts(level, pos))
        if found != powered:
            state = with_props(state, powered="true" if found else "false")
            level.set_block(pos, state, UPDATE_ALL)
            for dx, dy, dz in _RAIL_LINKS.get(prop(state, "shape"), ()):
                link = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
                level.neighbor_changed(link, self.name, pos)
            level.update_neighbors_at(pos, self.name)
            level.update_neighbors_at(rel(pos, "down"), self.name)
        if found:
            level.schedule_tick(pos, self.name, 20)
        level.update_neighbour_for_output_signal(pos, self.name)

    def analog_output(self, level, state, pos) -> int:
        if prop(state, "powered") != "true":
            return 0
        from ..minecart import detector_signal
        return detector_signal(level.server, *pos)

    def get_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" else 0

    def get_direct_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" and direction == "up" else 0

    def is_signal_source(self, state) -> bool:
        return True

    def on_remove(self, level, state, pos, new, moved):
        if moved:
            return
        super().on_remove(level, state, pos, new, moved)
        if prop(state, "powered") == "true":
            level.update_neighbors_at(pos, self.name)
            level.update_neighbors_at(rel(pos, "down"), self.name)

    def has_analog_output(self, state) -> bool:
        return True


class CoralFan(Block):
    """Coral fans: pop when their support goes (and are pushable, see piston.push_reaction)."""

    def __init__(self, name: str, wall: bool):
        self.name = name
        self.wall = wall

    def support_direction(self, state) -> str:
        return OPP[prop(state, "facing")] if self.wall else "down"

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        support = self.support_direction(state)
        if direction == support and not is_face_sturdy(neighbor_state, OPP[support]):
            return AIR
        return state


# --------------------------------------------------------------------------
# tripwire and tripwire hooks
# --------------------------------------------------------------------------

def _try_set(state, **changes):
    """BlockState.trySetValue: only properties the block has."""
    p = props_of(state)
    return with_props(state, **{k: v for k, v in changes.items() if k in p})


def _bool(value) -> str:
    return "true" if value else "false"


class TripwireHook(Block):
    name = "minecraft:tripwire_hook"

    def can_survive(self, level, state, pos):
        facing = prop(state, "facing")
        return is_face_sturdy(level.get(rel(pos, OPP[facing])), facing)

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if OPP[direction] == prop(state, "facing") and not self.can_survive(level, state, pos):
            return AIR
        return state

    def on_placed_by_player(self, level, state, pos):
        self.calculate_state(level, pos, state, False, False, -1, None)

    @staticmethod
    def notify_neighbors(level, pos, direction):
        level.update_neighbors_at(pos, TripwireHook.name)
        level.update_neighbors_at(rel(pos, OPP[direction]), TripwireHook.name)

    def calculate_state(self, level, pos, hook_state, attaching, notify, search_range, wire_state):
        """TripWireHookBlock.calculateState."""
        direction = prop(hook_state, "facing")
        if direction is None:
            return
        was_attached = prop(hook_state, "attached") == "true"
        was_powered = prop(hook_state, "powered") == "true"
        attached = not attaching
        powered = False
        other = 0
        cached = [None] * 42
        for j in range(1, 42):
            p = rel(pos, direction, j)
            state = level.get(p)
            if name_of(state) == self.name:
                if prop(state, "facing") == OPP[direction]:
                    other = j
                break
            if name_of(state) != Tripwire.name and j != search_range:
                cached[j] = None
                attached = False
            else:
                if j == search_range:
                    state = wire_state if wire_state is not None else state
                armed = prop(state, "disarmed") != "true"
                pressed = prop(state, "powered") == "true"
                powered |= armed and pressed
                cached[j] = state
                if j == search_range:
                    level.schedule_tick(pos, self.name, 10)
                    attached &= armed
        attached &= other > 1
        powered &= attached
        new_hook = _try_set(default_state(self.name), attached=_bool(attached), powered=_bool(powered))
        if other > 0:
            other_pos = rel(pos, direction, other)
            back = OPP[direction]
            level.set_block(other_pos, with_props(new_hook, facing=back), UPDATE_ALL)
            self.notify_neighbors(level, other_pos, back)
        if not attaching:
            level.set_block(pos, with_props(new_hook, facing=direction), UPDATE_ALL)
            if notify:
                self.notify_neighbors(level, pos, direction)
        if was_attached != attached:
            for k in range(1, other):
                state = cached[k]
                if state is not None:
                    level.set_block(rel(pos, direction, k), _try_set(state, attached=_bool(attached)), UPDATE_ALL)

    def tick(self, level, state, pos):
        self.calculate_state(level, pos, state, False, True, -1, None)

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name:
            attached = prop(state, "attached") == "true"
            powered = prop(state, "powered") == "true"
            if attached or powered:
                self.calculate_state(level, pos, state, True, False, -1, None)
            if powered:
                level.update_neighbors_at(pos, self.name)
                level.update_neighbors_at(rel(pos, OPP[prop(state, "facing")]), self.name)

    def get_signal(self, level, state, pos, direction) -> int:
        return 15 if prop(state, "powered") == "true" else 0

    def get_direct_signal(self, level, state, pos, direction) -> int:
        if prop(state, "powered") != "true":
            return 0
        return 15 if prop(state, "facing") == direction else 0

    def is_signal_source(self, state) -> bool:
        return True


class Tripwire(Block):
    name = "minecraft:tripwire"

    @staticmethod
    def should_connect_to(state, direction) -> bool:
        if name_of(state) == TripwireHook.name:
            return prop(state, "facing") == OPP[direction]
        return name_of(state) == Tripwire.name

    def placement_state(self, level, pos):
        state = default_state(self.name)
        return with_props(state, **{d: _bool(self.should_connect_to(level.get(rel(pos, d)), d)) for d in HORIZONTAL})

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction in HORIZONTAL:
            return with_props(state, **{direction: _bool(self.should_connect_to(neighbor_state, direction))})
        return state

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != self.name:
            self.update_source(level, pos, state)

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name:
            self.update_source(level, pos, with_props(state, powered="true"))

    def update_source(self, level, pos, state):
        hook = TripwireHook()
        for direction in ("south", "west"):
            for i in range(1, 42):
                p = rel(pos, direction, i)
                other = level.get(p)
                if name_of(other) == TripwireHook.name:
                    if prop(other, "facing") == OPP[direction]:
                        hook.calculate_state(level, p, other, False, True, i, state)
                    break
                if name_of(other) != self.name:
                    break

    def _entities_inside(self, level, pos) -> bool:
        server = level.server
        x, y, z = pos
        for player in server.get_online_players() if hasattr(server, "get_online_players") else ():
            if getattr(player, "gamemode", "") != "spectator" and x - 0.3 < player.x < x + 1.3 \
                    and z - 0.3 < player.z < z + 1.3 and y - 1.8 < player.y < y + 0.15:
                return True
        manager = getattr(server, "entity_manager", None)
        if manager is not None:
            for entity in manager.list_entities():
                if x <= entity.x < x + 1 and z <= entity.z < z + 1 and y - 0.5 < entity.y < y + 0.15:
                    return True
        return False

    def check_pressed(self, level, pos):
        state = level.get(pos)
        powered = prop(state, "powered") == "true"
        pressed = self._entities_inside(level, pos)
        if pressed != powered:
            state = with_props(state, powered=_bool(pressed))
            level.set_block(pos, state, UPDATE_ALL)
            self.update_source(level, pos, state)
        if pressed:
            level.schedule_tick(pos, self.name, 10)

    def entity_inside(self, level, state, pos):
        if prop(state, "powered") != "true":
            self.check_pressed(level, pos)

    def tick(self, level, state, pos):
        if prop(state, "powered") == "true":
            self.check_pressed(level, pos)


# --------------------------------------------------------------------------
# plain attached blocks that just need to break with their support
# --------------------------------------------------------------------------

class NeedsSupportBelow(Block):
    def __init__(self, name: str):
        self.name = name

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == "down" and not is_face_sturdy(neighbor_state, "up") and neighbor_state == AIR:
            return AIR
        return state


class WallAttached(Block):
    def __init__(self, name: str):
        self.name = name

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if direction == OPP[prop(state, "facing")] and not is_face_sturdy(neighbor_state, prop(state, "facing")):
            return AIR
        return state


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

SIGNAL_SOURCES = set()


def _is_signal_source_state(state) -> bool:
    from . import registry
    return registry().get(name_of(state)).is_signal_source(state)


def build_registry() -> dict:
    from .piston import MovingPistonBlock, PistonBase, PistonHead
    reg: dict = {}

    def add(behaviour):
        reg[behaviour.name] = behaviour

    for b in (RedstoneWire(), RedstoneTorch(), RedstoneWallTorch(), Repeater(), Comparator(), Observer(),
              Lever(), RedstoneBlock(), Target(), RedstoneLamp(), Tnt(), NoteBlock(), Hopper(),
              TripwireHook(), Tripwire(),
              PistonBase("minecraft:piston", False), PistonBase("minecraft:sticky_piston", True),
              PistonHead(), MovingPistonBlock()):
        add(b)
    for name in STATE_ID_TO_BLOCK_NAMES():
        short = name.split(":")[1]
        if name in reg:
            continue
        if short.endswith("_button"):
            add(Button(name, 20 if short in ("stone_button", "polished_blackstone_button") else 30))
        elif short.endswith("_pressure_plate"):
            kind = {"light_weighted_pressure_plate": "light", "heavy_weighted_pressure_plate": "heavy",
                    "stone_pressure_plate": "stone", "polished_blackstone_pressure_plate": "stone"}.get(short, "wood")
            add(PressurePlate(name, kind))
        elif short.endswith("_door"):
            add(Door(name))
        elif short.endswith("_trapdoor"):
            add(Trapdoor(name))
        elif short.endswith("_fence_gate"):
            add(FenceGate(name))
        elif short in ("dispenser", "dropper"):
            add(Dispenser(name))
        elif short in ("powered_rail", "activator_rail"):
            add(PoweredRail(name))
        elif short == "detector_rail":
            add(DetectorRail(name))
        elif short == "rail":
            add(BaseRail(name, False))
        elif short.endswith("_coral_wall_fan"):
            add(CoralFan(name, True))
        elif short.endswith("_coral_fan"):
            add(CoralFan(name, False))
        elif short in ("chest", "trapped_chest"):
            add(ChestBlock(name))
        elif short == "composter":
            add(Composter())
        elif short in ("barrel", "furnace", "blast_furnace", "smoker",
                       "brewing_stand", "crafter") or short.endswith("shulker_box"):
            add(Container(name))
        elif short in ("water_cauldron", "powder_snow_cauldron"):
            add(LeveledAnalog(name, "level"))
        elif short == "cake":
            add(LeveledAnalog(name, "bites", lambda b: (7 - b) * 2))
        elif short == "respawn_anchor":
            add(LeveledAnalog(name, "charges", lambda c: int(c / 4 * 15)))
        elif short in ("torch", "soul_torch", "redstone_wire_dummy") or short.endswith("_carpet") \
                or short.endswith("_sapling") or short in (
                    "short_grass", "fern", "dandelion", "poppy", "sugar_cane", "wheat", "carrots", "potatoes"):
            add(NeedsSupportBelow(name))
        elif short in ("wall_torch", "soul_wall_torch", "ladder") or short.endswith("_wall_sign"):
            add(WallAttached(name))
    for name, behaviour in reg.items():
        try:
            states = [s for s, (n, _) in STATE_ID_TO_BLOCK.items() if n == name][:1]
            if states and behaviour.is_signal_source(states[0]):
                SIGNAL_SOURCES.add(name)
        except Exception:
            pass
    return reg


@lru_cache(maxsize=1)
def STATE_ID_TO_BLOCK_NAMES():
    return sorted({name for name, _ in STATE_ID_TO_BLOCK.values()})
