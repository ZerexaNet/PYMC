"""
Vanilla 1.21.1 pistons: PistonBaseBlock, PistonHeadBlock, MovingPistonBlock,
PistonMovingBlockEntity and PistonStructureResolver.

Quasi-connectivity (getNeighborSignal also checks around the block above),
BUD behaviour (no re-check without a block update), 0-tick behaviour (a
retraction in the same tick finalTick()s the blocks still moving out, sticky
pistons dropping their block with event 2) and the push order all come
straight from the vanilla code paths reproduced here.
"""

from __future__ import annotations

from .blocks import Block, destroy_speed
from .core import (
    AIR, DATA_3D, DIRECTIONS, FROM_3D, OPP, UPDATE_ALL, UPDATE_CLIENTS, UPDATE_INVISIBLE,
    UPDATE_KNOWN_SHAPE, UPDATE_MOVE_BY_PISTON, default_state, java_hash_order,
    name_of, prop, rel, with_props,
)

MOVING_PISTON = "minecraft:moving_piston"
PISTON_HEAD = "minecraft:piston_head"
PUSH_LIMIT = 12

# blocks with a block entity (immovable unless they are destroyed instead)
_BLOCK_ENTITIES = {
    "chest", "trapped_chest", "ender_chest", "furnace", "blast_furnace", "smoker", "hopper", "dispenser",
    "dropper", "barrel", "brewing_stand", "enchanting_table", "beacon", "spawner", "jukebox", "lectern",
    "bell", "campfire", "soul_campfire", "beehive", "bee_nest", "conduit", "daylight_detector",
    "comparator", "sculk_sensor", "calibrated_sculk_sensor", "sculk_catalyst", "sculk_shrieker",
    "chiseled_bookshelf", "decorated_pot", "crafter", "trial_spawner", "vault", "command_block",
    "chain_command_block", "repeating_command_block", "structure_block", "jigsaw", "end_gateway",
    "end_portal", "moving_piston", "suspicious_sand", "suspicious_gravel", "creaking_heart",
}
_BLOCK_REACTION = {"obsidian", "crying_obsidian", "respawn_anchor", "reinforced_deepslate", "piston_head",
                   "moving_piston", "barrier", "end_portal_frame", "light", "nether_portal"}
_PUSH_ONLY = ("glazed_terracotta",)
_DESTROY_NAMES = {
    "cactus", "cobweb", "dragon_egg", "flower_pot", "scaffolding", "snow", "bamboo", "bamboo_sapling",
    "cocoa", "chorus_plant", "chorus_flower", "lantern", "soul_lantern", "pointed_dripstone",
    "big_dripleaf", "big_dripleaf_stem", "small_dripleaf", "sea_pickle", "turtle_egg", "sniffer_egg",
    "frogspawn", "moss_carpet", "pale_moss_carpet", "azalea", "flowering_azalea", "conduit", "lily_pad",
    "pitcher_plant", "pitcher_crop", "torchflower_crop", "sweet_berry_bush", "cave_vines",
    "cave_vines_plant", "glow_lichen", "sculk_vein", "hanging_roots", "spore_blossom", "repeater",
    "comparator", "redstone_wire", "redstone_torch", "redstone_wall_torch", "lever", "tripwire",
    "tripwire_hook", "jack_o_lantern_dummy", "melon_stem", "pumpkin_stem", "attached_melon_stem",
    "attached_pumpkin_stem", "nether_wart", "kelp", "kelp_plant", "seagrass", "tall_seagrass",
    "water", "lava", "fire", "soul_fire", "powder_snow", "heavy_core_dummy", "end_rod_dummy",
}
_DESTROY_SUFFIXES = ("_door", "_bed", "_carpet", "_button", "_pressure_plate", "_sapling", "_sign",
                     "_wall_sign", "_hanging_sign", "_banner", "_wall_banner", "_head", "_skull",
                     "_wall_head", "_wall_skull", "_candle", "candle", "_cluster", "_bud", "_coral", "torch", "_flower", "_tulip", "_mushroom", "_fungus",
                     "_roots", "_vines", "_vines_plant", "_leaves_dummy", "_rail_dummy", "_crop")


def _short(state) -> str:
    return name_of(state).split(":")[1]


def push_reaction(state) -> str:
    """BlockState.getPistonPushReaction: normal / destroy / block / push_only."""
    short = _short(state)
    if short in _BLOCK_REACTION:
        return "block"
    if short.endswith(_PUSH_ONLY):
        return "push_only"
    if short in _DESTROY_NAMES or short.endswith(_DESTROY_SUFFIXES):
        return "destroy"
    if short.endswith("rail"):
        return "normal"   # rails can be pushed (rail-based TNT dupers)
    if short.endswith("_coral_fan") or short.endswith("_coral_wall_fan"):
        return "normal"   # vanilla: coral fans can be pushed (MC-133541), the base of TNT dupers
    from ..block_shapes import no_collision_states
    if state in no_collision_states():
        return "destroy"
    return "normal"


def has_block_entity(state) -> bool:
    short = _short(state)
    return short in _BLOCK_ENTITIES or short.endswith("shulker_box") or short.endswith("_sign") \
        or short.endswith("_banner") or short.endswith("_bed") or short.endswith("_head") \
        or short.endswith("_skull")


def is_sticky(state) -> bool:
    return _short(state) in ("slime_block", "honey_block")


def can_stick(a, b) -> bool:
    sa, sb = _short(a), _short(b)
    if (sa == "honey_block" and sb == "slime_block") or (sa == "slime_block" and sb == "honey_block"):
        return False
    return is_sticky(a) or is_sticky(b)


def is_pushable(state, level, pos, direction, allow_destroy, piston_facing) -> bool:
    x, y, z = pos
    if y < -64 or y > 319:
        return False
    if state == AIR:
        return True
    short = _short(state)
    if short in ("obsidian", "crying_obsidian", "respawn_anchor", "reinforced_deepslate"):
        return False
    if (direction == "down" and y == -64) or (direction == "up" and y == 319):
        return False
    if short not in ("piston", "sticky_piston"):
        if destroy_speed(state) == -1.0:
            return False
        reaction = push_reaction(state)
        if reaction == "block":
            return False
        if reaction == "destroy":
            return allow_destroy
        if reaction == "push_only":
            return direction == piston_facing
    elif prop(state, "extended") == "true":
        return False
    return not has_block_entity(state)


class StructureResolver:
    """PistonStructureResolver."""

    def __init__(self, level, piston_pos, piston_direction, extending):
        self.level = level
        self.piston_pos = piston_pos
        self.piston_direction = piston_direction
        self.extending = extending
        if extending:
            self.push_direction = piston_direction
            self.start_pos = rel(piston_pos, piston_direction)
        else:
            self.push_direction = OPP[piston_direction]
            self.start_pos = rel(piston_pos, piston_direction, 2)
        self.to_push: list = []
        self.to_destroy: list = []

    def resolve(self) -> bool:
        self.to_push.clear()
        self.to_destroy.clear()
        state = self.level.get(self.start_pos)
        if not is_pushable(state, self.level, self.start_pos, self.push_direction, False, self.piston_direction):
            if self.extending and push_reaction(state) == "destroy":
                self.to_destroy.append(self.start_pos)
                return True
            return False
        if not self.add_block_line(self.start_pos, self.push_direction):
            return False
        i = 0
        while i < len(self.to_push):
            pos = self.to_push[i]
            if is_sticky(self.level.get(pos)) and not self.add_branching_blocks(pos):
                return False
            i += 1
        return True

    def add_block_line(self, origin, direction) -> bool:
        state = self.level.get(origin)
        if state == AIR:
            return True
        if not is_pushable(state, self.level, origin, self.push_direction, False, direction):
            return True
        if origin == self.piston_pos or origin in self.to_push:
            return True
        i = 1
        if i + len(self.to_push) > PUSH_LIMIT:
            return False
        back = OPP[self.push_direction]
        while is_sticky(state):
            pos = rel(origin, back, i)
            previous = state
            state = self.level.get(pos)
            if state == AIR or not can_stick(previous, state) \
                    or not is_pushable(state, self.level, pos, self.push_direction, False, back) \
                    or pos == self.piston_pos:
                break
            i += 1
            if i + len(self.to_push) > PUSH_LIMIT:
                return False
        added = 0
        for k in range(i - 1, -1, -1):
            self.to_push.append(rel(origin, back, k))
            added += 1
        j = 1
        while True:
            pos = rel(origin, self.push_direction, j)
            if pos in self.to_push:
                index = self.to_push.index(pos)
                self.reorder_list_at_collision(added, index)
                for k in range(0, index + added + 1):
                    p = self.to_push[k]
                    if is_sticky(self.level.get(p)) and not self.add_branching_blocks(p):
                        return False
                return True
            state = self.level.get(pos)
            if state == AIR:
                return True
            if not is_pushable(state, self.level, pos, self.push_direction, True, self.push_direction) \
                    or pos == self.piston_pos:
                return False
            if push_reaction(state) == "destroy":
                self.to_destroy.append(pos)
                return True
            if len(self.to_push) >= PUSH_LIMIT:
                return False
            self.to_push.append(pos)
            added += 1
            j += 1

    def reorder_list_at_collision(self, offsets, index):
        head = self.to_push[:index]
        tail = self.to_push[len(self.to_push) - offsets:]
        middle = self.to_push[index:len(self.to_push) - offsets]
        self.to_push[:] = head + tail + middle

    def add_branching_blocks(self, origin) -> bool:
        from .core import AXIS
        state = self.level.get(origin)
        for direction in DIRECTIONS:
            if AXIS[direction] != AXIS[self.push_direction]:
                pos = rel(origin, direction)
                if can_stick(self.level.get(pos), state) and not self.add_block_line(pos, direction):
                    return False
        return True


class MovingPiston:
    """PistonMovingBlockEntity."""

    def __init__(self, pos, moved_state, direction, extending, is_source):
        self.pos = pos
        self.moved_state = moved_state
        self.direction = direction
        self.extending = extending
        self.is_source = is_source
        self.progress = 0.0
        self.progress_o = 0.0
        self.last_ticked = -1

    def tick(self, level):
        self.last_ticked = level.game_time
        self.progress_o = self.progress
        if self.progress_o >= 1.0:
            level.moving_pistons.pop(self.pos, None)
            if name_of(level.get(self.pos)) == MOVING_PISTON:
                state = level.update_from_neighbour_shapes(self.moved_state, self.pos)
                if state == AIR:
                    level.set_block(self.pos, self.moved_state, UPDATE_MOVE_BY_PISTON | UPDATE_KNOWN_SHAPE | UPDATE_INVISIBLE)
                    level.update_or_destroy(self.moved_state, state, self.pos, UPDATE_ALL)
                else:
                    level.set_block(self.pos, state, UPDATE_MOVE_BY_PISTON | UPDATE_ALL)
                    level.neighbor_changed(self.pos, name_of(state), self.pos)
            return
        self.progress = min(1.0, self.progress + 0.5)
        self._move_entities(level)

    def final_tick(self, level):
        if self.progress_o < 1.0:
            self.progress = 1.0
            self.progress_o = 1.0
            level.moving_pistons.pop(self.pos, None)
            if name_of(level.get(self.pos)) == MOVING_PISTON:
                state = AIR if self.is_source else level.update_from_neighbour_shapes(self.moved_state, self.pos)
                level.set_block(self.pos, state, UPDATE_ALL)
                level.neighbor_changed(self.pos, name_of(state), self.pos)

    def _move_entities(self, level):
        """Push entities standing in the way (simplified PistonMovingBlockEntity.moveCollidedEntities)."""
        if self.moved_state == AIR or (self.is_source and not self.extending):
            return
        manager = getattr(level.server, "entity_manager", None)
        if manager is None:
            return
        from .core import VEC
        dx, dy, dz = VEC[self.direction if self.extending else OPP[self.direction]]
        x, y, z = self.pos
        for entity in manager.list_entities():
            if x - 0.5 <= entity.x <= x + 1.5 and y - 0.5 <= entity.y <= y + 1.0 and z - 0.5 <= entity.z <= z + 1.5:
                entity.x += dx * 0.5
                entity.y += dy * 0.5
                entity.z += dz * 0.5


class PistonBase(Block):
    def __init__(self, name: str, sticky: bool):
        self.name = name
        self.sticky = sticky

    def get_neighbor_signal(self, level, pos, facing) -> bool:
        for direction in DIRECTIONS:
            if direction != facing and level.has_signal(rel(pos, direction), direction):
                return True
        if level.has_signal(pos, "down"):
            return True
        above = rel(pos, "up")
        for direction in DIRECTIONS:
            if direction != "down" and level.has_signal(rel(above, direction), direction):
                return True
        return False

    def check_if_extend(self, level, pos, state):
        facing = prop(state, "facing")
        powered = self.get_neighbor_signal(level, pos, facing)
        extended = prop(state, "extended") == "true"
        if powered and not extended:
            if StructureResolver(level, pos, facing, True).resolve():
                level.block_event(pos, self.name, 0, DATA_3D[facing])
        elif not powered and extended:
            front2 = rel(pos, facing, 2)
            event = 1
            if name_of(level.get(front2)) == MOVING_PISTON:
                entity = level.moving_pistons.get(front2)
                if entity is not None and entity.direction == facing and entity.extending and (
                        entity.progress < 0.5 or level.game_time == entity.last_ticked or entity.is_source):
                    event = 2
            level.block_event(pos, self.name, event, DATA_3D[facing])

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        self.check_if_extend(level, pos, state)

    def on_place(self, level, state, pos, old, moved):
        if name_of(old) != name_of(state) and pos not in level.moving_pistons:
            self.check_if_extend(level, pos, state)

    def on_placed_by_player(self, level, state, pos):
        self.check_if_extend(level, pos, state)

    def trigger_event(self, level, state, pos, event_id, param) -> bool:
        direction = prop(state, "facing")
        powered = self.get_neighbor_signal(level, pos, direction)
        if powered and event_id in (1, 2):
            level.set_block(pos, with_props(state, extended="true"), UPDATE_CLIENTS)
            return False
        if not powered and event_id == 0:
            return False

        if event_id == 0:
            if not self.move_blocks(level, pos, direction, True):
                return False
            level.set_block(pos, with_props(state, extended="true"), UPDATE_MOVE_BY_PISTON | UPDATE_ALL)
            level.effects.append(("sound", {"pos": pos, "sound": "minecraft:block.piston.extend", "pitch": 0.75}))
            return True

        # retract (1) / fast retract without pulling (2)
        front = rel(pos, direction)
        entity = level.moving_pistons.get(front)
        if entity is not None:
            entity.final_tick(level)
        moving = with_props(default_state(MOVING_PISTON), facing=direction,
                            type="sticky" if self.sticky else "normal")
        level.set_block(pos, moving, UPDATE_INVISIBLE | UPDATE_KNOWN_SHAPE)
        level.moving_pistons[pos] = MovingPiston(
            pos, with_props(default_state(self.name), facing=FROM_3D[param & 7]), direction, False, True)
        level.update_neighbors_at(pos, MOVING_PISTON)
        level.update_neighbour_shapes(moving, pos, UPDATE_CLIENTS)
        if self.sticky:
            far = rel(pos, direction, 2)
            far_state = level.get(far)
            pulled_moving = False
            if name_of(far_state) == MOVING_PISTON:
                other = level.moving_pistons.get(far)
                if other is not None and other.direction == direction and other.extending:
                    other.final_tick(level)
                    pulled_moving = True
            if not pulled_moving:
                if event_id != 1 or far_state == AIR \
                        or not is_pushable(far_state, level, far, OPP[direction], False, direction) \
                        or (push_reaction(far_state) != "normal" and _short(far_state) not in ("piston", "sticky_piston")):
                    level.remove_block(front)
                else:
                    self.move_blocks(level, pos, direction, False)
        else:
            level.remove_block(front)
        level.effects.append(("sound", {"pos": pos, "sound": "minecraft:block.piston.contract", "pitch": 0.6}))
        return True

    def move_blocks(self, level, pos, facing, extending) -> bool:
        head_pos = rel(pos, facing)
        if not extending and name_of(level.get(head_pos)) == PISTON_HEAD:
            level.set_block(head_pos, AIR, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE)
        resolver = StructureResolver(level, pos, facing, extending)
        if not resolver.resolve():
            return False
        to_push = list(resolver.to_push)
        to_destroy = list(resolver.to_destroy)
        moved_states = [level.get(p) for p in to_push]
        vacated = {p: level.get(p) for p in to_push}          # HashMap<BlockPos, BlockState>
        insertion = list(to_push)
        direction = facing if extending else OPP[facing]
        removed_states = []
        for p in reversed(to_destroy):
            state = level.get(p)
            level.drop_resources(state, p)
            level.set_block(p, AIR, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE)
            removed_states.append(state)
        for k in range(len(to_push) - 1, -1, -1):
            source = to_push[k]
            state = level.get(source)
            target = rel(source, direction)
            vacated.pop(target, None)
            moving = with_props(default_state(MOVING_PISTON), facing=facing)
            level.set_block(target, moving, UPDATE_INVISIBLE | UPDATE_MOVE_BY_PISTON)
            level.moving_pistons[target] = MovingPiston(target, moved_states[k], facing, extending, False)
            removed_states.append(state)
        if extending:
            kind = "sticky" if self.sticky else "normal"
            head = with_props(default_state(PISTON_HEAD), facing=facing, type=kind)
            moving = with_props(default_state(MOVING_PISTON), facing=facing, type=kind)
            vacated.pop(head_pos, None)
            level.set_block(head_pos, moving, UPDATE_INVISIBLE | UPDATE_MOVE_BY_PISTON)
            level.moving_pistons[head_pos] = MovingPiston(head_pos, head, facing, True, True)
        order = [p for p in java_hash_order(insertion) if p in vacated]
        for p in order:
            level.set_block(p, AIR, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE | UPDATE_MOVE_BY_PISTON)
        for p in order:
            old_state = vacated[p]
            level.block(old_state).update_indirect_neighbour_shapes(level, old_state, p, UPDATE_CLIENTS, 511)
            level.update_neighbour_shapes(AIR, p, UPDATE_CLIENTS)
        i = 0
        for p in reversed(to_destroy):
            state = removed_states[i]
            i += 1
            level.block(state).update_indirect_neighbour_shapes(level, state, p, UPDATE_CLIENTS, 511)
            level.update_neighbors_at(p, name_of(state))
        for p in reversed(to_push):
            level.update_neighbors_at(p, name_of(removed_states[i]))
            i += 1
        if extending:
            level.update_neighbors_at(head_pos, PISTON_HEAD)
        return True


class PistonHead(Block):
    name = PISTON_HEAD

    def _fitting_base(self, state, base_state) -> bool:
        base = name_of(base_state)
        wanted = "minecraft:sticky_piston" if prop(state, "type") == "sticky" else "minecraft:piston"
        return base == wanted and prop(base_state, "extended") == "true" and prop(base_state, "facing") == prop(state, "facing")

    def can_survive(self, level, state, pos):
        behind = level.get(rel(pos, OPP[prop(state, "facing")]))
        return self._fitting_base(state, behind) or (
            name_of(behind) == MOVING_PISTON and prop(behind, "facing") == prop(state, "facing"))

    def update_shape(self, level, state, direction, neighbor_state, pos, neighbor_pos):
        if OPP[direction] == prop(state, "facing") and not self.can_survive(level, state, pos):
            return AIR
        return state

    def neighbor_changed(self, level, state, pos, source, from_pos, moved):
        if self.can_survive(level, state, pos):
            level.neighbor_changed(rel(pos, OPP[prop(state, "facing")]), source, from_pos)

    def on_remove(self, level, state, pos, new, moved):
        if not moved and name_of(new) != self.name:
            base = rel(pos, OPP[prop(state, "facing")])
            if self._fitting_base(state, level.get(base)):
                level.destroy_block(base, True)


class MovingPistonBlock(Block):
    name = MOVING_PISTON

    def on_remove(self, level, state, pos, new, moved):
        if name_of(new) != self.name:
            entity = level.moving_pistons.get(pos)
            if entity is not None:
                entity.final_tick(level)
