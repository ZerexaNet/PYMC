"""
Vanilla-accurate redstone for PyMC (see core.py for the update model).

RedstoneEngine keeps the interface the server already uses (tick,
on_block_change, on_player_interact, get_visual_updates,
drain_pending_effects) on top of the vanilla Level port.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from .core import (
    AIR, DIRECTIONS, Level, UPDATE_ALL, UPDATE_CLIENTS, UPDATE_KNOWN_SHAPE, name_of, prop, props_of, rel,
)

logger = logging.getLogger("PyMC.红石")


class _Registry(dict):
    def __missing__(self, key):
        from .blocks import DEFAULT
        return DEFAULT

    def get(self, key, default=None):
        value = dict.get(self, key)
        if value is None:
            from .blocks import DEFAULT
            return DEFAULT if default is None else default
        return value


@lru_cache(maxsize=1)
def registry() -> _Registry:
    from .blocks import build_registry
    return _Registry(build_registry())


INTERACTIVE = {"minecraft:lever", "minecraft:repeater", "minecraft:comparator", "minecraft:note_block",
               "minecraft:redstone_wire"}


def is_redstone_block(block_name: str) -> bool:
    """Blocks whose right-click the redstone engine handles."""
    return block_name in INTERACTIVE or block_name.endswith("_button")


class RedstoneEngine:
    TICKS_FILE = "pymc_scheduled_ticks.json"

    def __init__(self, server):
        self.server = server
        self.level = Level(server)
        self.level.blocks = registry()
        self.visual_updates: list = []
        self.pending_effects: list = []
        self._load_ticks()

    # ----------------------------------------------------------------- tick

    def tick(self):
        level = self.level
        level.game_time += 1
        try:
            level.run_scheduled_ticks()
            level.run_block_events()
            level.tick_block_entities()
        except RecursionError:
            logger.warning("Redstone update chain too deep; rest of this tick skipped")
        finally:
            self._finish_step()

    def _finish_step(self):
        level = self.level
        self._handle_effects()
        level.flush()
        self.visual_updates.extend((x, y, z, s) for (x, y, z), s in level.client_changes.items())
        level.client_changes.clear()

    # ------------------------------------------------------ external changes

    def on_block_change(self, x: int, y: int, z: int, old_block, new_block):
        """A block was set by something else (placing, breaking, commands, explosions)."""
        level = self.level
        pos = (int(x), int(y), int(z))
        level._chunks.clear()
        old = int(old_block or 0)
        state = level.get(pos)
        if old == state:
            return
        reg = registry()
        try:
            if name_of(state) == "minecraft:redstone_wire" and name_of(old) != "minecraft:redstone_wire":
                shaped = reg.get("minecraft:redstone_wire").placement_state(level, pos)
                level._write(pos, shaped)
                level.client_changes[pos] = shaped
                state = shaped
            reg.get(name_of(old)).on_remove(level, old, pos, state, False)
            if level.get(pos) == state:
                reg.get(name_of(state)).on_place(level, state, pos, old, False)
            if level.get(pos) == state:
                level.update_neighbors_at(pos, name_of(old))
                behaviour = reg.get(name_of(state))
                if behaviour.has_analog_output(state):
                    level.update_neighbour_for_output_signal(pos, name_of(state))
                reg.get(name_of(old)).update_indirect_neighbour_shapes(level, old, pos, UPDATE_CLIENTS, 511)
                level.update_neighbour_shapes(state, pos, UPDATE_CLIENTS)
                behaviour.update_indirect_neighbour_shapes(level, state, pos, UPDATE_CLIENTS, 511)
                placed_by = getattr(behaviour, "on_placed_by_player", None)
                if placed_by is not None and state:
                    placed_by(level, state, pos)
        except RecursionError:
            logger.warning(f"Redstone update chain too deep after change at {pos}")
        finally:
            self._finish_step()

    def on_container_changed(self, x: int, y: int, z: int):
        level = self.level
        pos = (int(x), int(y), int(z))
        state = level.get(pos)
        level.update_neighbour_for_output_signal(pos, name_of(state))
        self._finish_step()

    def on_player_interact(self, x: int, y: int, z: int, player) -> bool:
        level = self.level
        pos = (int(x), int(y), int(z))
        level._chunks.clear()
        state = level.get(pos)
        name = name_of(state)
        if name == "minecraft:redstone_wire" and _holds_placeable_item(player):
            return False
        try:
            handled = registry().get(name).use(level, state, pos, player)
        except RecursionError:
            handled = True
        self._finish_step()
        return handled

    def on_entity_move(self, x: int, y: int, z: int):
        """An entity is inside the block at (x, y, z): pressure plates."""
        level = self.level
        pos = (int(x), int(y), int(z))
        state = level.raw(pos)
        if state is None:
            return
        behaviour = registry().get(name_of(state))
        inside = getattr(behaviour, "entity_inside", None)
        if inside is not None:
            inside(level, state, pos)
            self._finish_step()

    def on_projectile_hit(self, x: int, y: int, z: int):
        pass

    def scan_chunk(self, chunk_x: int, chunk_z: int, chunk_blocks):
        """Block states carry all redstone state; nothing to scan."""

    # -------------------------------------------------------------- outputs

    def get_visual_updates(self) -> list:
        updates, self.visual_updates = self.visual_updates, []
        return updates

    def drain_pending_effects(self) -> list:
        effects, self.pending_effects = self.pending_effects, []
        return effects

    def drain_block_actions(self) -> list:
        actions, self.level.block_actions = self.level.block_actions, []
        return actions

    def _handle_effects(self):
        level = self.level
        effects, level.effects = level.effects, []
        for kind, payload in effects:
            if kind == "dispense":
                self._dispense(payload)
            else:
                self.pending_effects.append((kind, payload))

    def _dispense(self, payload):
        from ..block_behavior import container_manager
        from .core import VEC
        x, y, z = payload["pos"]
        container = container_manager.get_container(x, y, z)
        if container is None:
            return
        for index, stack in enumerate(container.items):
            if stack is None or stack.is_empty:
                continue
            item_name = stack.item_id
            stack.count -= 1
            if stack.count <= 0:
                container.items[index] = None
            dx, dy, dz = VEC.get(payload.get("facing") or "north", (0, 0, -1))
            manager = getattr(self.server, "entity_manager", None)
            if manager is not None:
                entity = manager.create_item(x + 0.5 + dx * 0.7, y + 0.5 + dy * 0.7 - 0.15, z + 0.5 + dz * 0.7,
                                             item_name=item_name, count=1)
                entity.vx, entity.vy, entity.vz = dx * 0.2, 0.1 + dy * 0.2, dz * 0.2
                self.pending_effects.append(("entity_spawn", {"entity_id": entity.entity_id}))
            self.pending_effects.append(("sound", {"pos": (x, y, z), "sound": "minecraft:block.dispenser.dispense"}))
            self.level.update_neighbour_for_output_signal((x, y, z), payload.get("block", ""))
            return
        self.pending_effects.append(("sound", {"pos": (x, y, z), "sound": "minecraft:block.dispenser.fail"}))

    # ---------------------------------------------------------- persistence

    def _ticks_path(self):
        storage = getattr(self.server, "world_storage", None)
        if storage is None:
            return None
        return os.path.join(str(storage.world_dir), self.TICKS_FILE)

    def save(self):
        """Finish moving pistons and store pending block ticks (vanilla keeps them in the chunks)."""
        level = self.level
        for pos in list(level.moving_pistons):
            entity = level.moving_pistons.get(pos)
            if entity is not None:
                entity.final_tick(level)
        self._finish_step()
        path = self._ticks_path()
        if path is None:
            return
        data = {"ticks": [[list(pos), block, delay, priority] for pos, block, delay, priority in level.pending_ticks()],
                "comparators": [[list(pos), value] for pos, value in level.comparator_output.items() if value]}
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(path + ".tmp", path)
        except OSError as e:
            logger.warning(f"Could not save scheduled redstone ticks: {e}")

    def _load_ticks(self):
        path = self._ticks_path()
        if path is None or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for pos, block, delay, priority in data.get("ticks", []):
            self.level.schedule_tick(tuple(pos), block, max(1, int(delay)), int(priority))
        for pos, value in data.get("comparators", []):
            self.level.comparator_output[tuple(pos)] = int(value)

    def get_status(self) -> dict:
        return {"scheduled_ticks": len(self.level._tick_heap),
                "moving_pistons": len(self.level.moving_pistons)}


def _holds_placeable_item(player) -> bool:
    inventory = getattr(player, "inventory_obj", None)
    if inventory is None:
        return False
    held = inventory.get_held_item_from_slot(getattr(player, "selected_hotbar_slot", 0))
    if held is None or held.is_empty:
        return False
    from ..placement import block_for_item
    return block_for_item(held.item_id) is not None
