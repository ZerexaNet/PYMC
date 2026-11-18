"""
Minecarts and hopper minecarts (AbstractMinecart / MinecartHopper).

* placed on rails with the minecart / hopper_minecart item, follow the track
  (straight, curved and sloped rails), powered rails boost or brake them,
  container minecarts slow down by fill level, off the track they fall and
  slide;
* a hopper minecart has 5 slots and, unless it stands on a powered activator
  rail, sucks one item per tick from the container above it or picks up item
  entities (the item moving itself happens in the native hopper code);
* hoppers push into and pull from a hopper minecart in the block next to them;
* players break minecarts (dropping the item and the contents) and open a
  hopper minecart's 5-slot window;
* minecarts are saved with the world (pymc_minecarts.json).
"""

from __future__ import annotations

import json
import math
import os

from .entities import Entity, _is_solid

RAIL_NAMES = {"minecraft:rail", "minecraft:powered_rail", "minecraft:detector_rail", "minecraft:activator_rail"}
MINECART_ITEMS = {"minecraft:minecart": "minecart", "minecraft:hopper_minecart": "hopper_minecart"}
SAVE_FILE = "pymc_minecarts.json"

# BaseRailBlock exits: (dx, dy, dz) of both ends
EXITS = {
    "north_south": ((0, 0, -1), (0, 0, 1)),
    "east_west": ((-1, 0, 0), (1, 0, 0)),
    "ascending_east": ((-1, 0, 0), (1, 1, 0)),
    "ascending_west": ((-1, 1, 0), (1, 0, 0)),
    "ascending_north": ((0, 1, -1), (0, 0, 1)),
    "ascending_south": ((0, 0, -1), (0, 1, 1)),
    "south_east": ((0, 0, 1), (1, 0, 0)),
    "south_west": ((0, 0, 1), (-1, 0, 0)),
    "north_west": ((0, 0, -1), (-1, 0, 0)),
    "north_east": ((0, 0, -1), (1, 0, 0)),
}
SLOPE_PUSH = {"ascending_east": (-0.0078125, 0.0), "ascending_west": (0.0078125, 0.0),
              "ascending_north": (0.0, 0.0078125), "ascending_south": (0.0, -0.0078125)}
MAX_SPEED = 0.4          # 8 blocks per second
HALF_WIDTH = 0.49
HEIGHT = 0.7


def _block(server, x, y, z):
    getter = getattr(server, "get_block_at", None)
    if getter is not None:
        return getter(x, y, z)
    storage = getattr(server, "world_storage", None)
    if storage is None or y < -64 or y > 319:
        return None
    chunk = storage.load_generated_chunk(x >> 4, z >> 4)
    return None if chunk is None else chunk[y + 64][z & 15][x & 15]


def _rail(server, x, y, z):
    """(name, props) of the rail at (x, y, z), or None."""
    from .chunk_io import STATE_ID_TO_BLOCK
    state = _block(server, x, y, z)
    if not state:
        return None
    name, props = STATE_ID_TO_BLOCK.get(state, ("", {}))
    return (name, props) if name in RAIL_NAMES else None


class MinecartEntity(Entity):
    """A minecart (variant "minecart") or hopper minecart (variant "hopper_minecart")."""

    def __init__(self, entity_id: int, x: float, y: float, z: float, variant: str = "hopper_minecart"):
        super().__init__(entity_id=entity_id, kind="minecart", x=x, y=y, z=z)
        self.variant = variant
        self.metadata = {"mob_type": variant}
        self.persistent = True
        self.damage = 0.0
        self.enabled = True
        self.on_rail = False
        if variant == "hopper_minecart":
            from .block_behavior import ContainerData
            self.container = ContainerData(type="hopper")
        else:
            self.container = None

    # ------------------------------------------------------------- inventory

    @property
    def is_container(self) -> bool:
        return self.container is not None

    def bounding_box(self):
        return (self.x - HALF_WIDTH, self.y, self.z - HALF_WIDTH), (self.x + HALF_WIDTH, self.y + HEIGHT,
                                                                  self.z + HALF_WIDTH)

    def intersects_block(self, x: int, y: int, z: int) -> bool:
        (x0, y0, z0), (x1, y1, z1) = self.bounding_box()
        return x0 < x + 1 and x1 > x and y0 < y + 1 and y1 > y and z0 < z + 1 and z1 > z

    def comparator_signal(self) -> int:
        if self.container is None:
            return 0
        fill, any_items = 0.0, False
        for stack in self.container.items:
            if stack is None or stack.is_empty:
                continue
            fill += stack.count / float(max(1, min(64, stack.max_stack_size)))
            any_items = True
        return int(fill / len(self.container.items) * 14.0) + (1 if any_items else 0)

    # ----------------------------------------------------------------- moving

    def tick(self, server):
        super().tick(server)
        bx, by, bz = math.floor(self.x), math.floor(self.y), math.floor(self.z)
        rail = _rail(server, bx, by, bz)
        if rail is None:
            rail = _rail(server, bx, by - 1, bz)
            if rail is not None:
                by -= 1
        if rail is not None:
            self.on_rail = True
            self._move_along_track(server, bx, by, bz, *rail)
        else:
            self.on_rail = False
            self._come_off_track(server)

    def _move_along_track(self, server, bx, by, bz, name, props):
        shape = props.get("shape", "north_south")
        powered = props.get("powered") == "true"
        if name == "minecraft:activator_rail":
            # MinecartHopper.activateMinecart: a powered activator rail locks the hopper
            self.enabled = not powered
        boost = name == "minecraft:powered_rail" and powered
        brake = name == "minecraft:powered_rail" and not powered

        push = SLOPE_PUSH.get(shape)
        if push is not None:
            self.vx += push[0]
            self.vz += push[1]

        (ax, ay, az), (cx, cy, cz) = EXITS.get(shape, EXITS["north_south"])
        dir_x, dir_z = cx - ax, cz - az
        length = math.sqrt(dir_x * dir_x + dir_z * dir_z)
        if self.vx * dir_x + self.vz * dir_z < 0.0:
            dir_x, dir_z = -dir_x, -dir_z
        speed = min(2.0, math.sqrt(self.vx * self.vx + self.vz * self.vz))
        self.vx, self.vz = speed * dir_x / length, speed * dir_z / length

        if brake:
            if speed < 0.03:
                self.vx = self.vz = 0.0
            else:
                self.vx *= 0.5
                self.vz *= 0.5

        # snap onto the track line between the two exits
        x0, z0 = bx + 0.5 + ax * 0.5, bz + 0.5 + az * 0.5
        x1, z1 = bx + 0.5 + cx * 0.5, bz + 0.5 + cz * 0.5
        ex, ez = x1 - x0, z1 - z0
        if ex == 0.0:
            t = self.z - bz
        elif ez == 0.0:
            t = self.x - bx
        else:
            t = ((self.x - x0) * ex + (self.z - z0) * ez) * 2.0
        self.x, self.z = x0 + ex * t, z0 + ez * t
        self.y = by + 0.0625 + (max(ay, cy) * min(1.0, max(0.0, t if cy > ay else 1.0 - t)) if ay or cy else 0.0)

        mx = max(-MAX_SPEED, min(MAX_SPEED, self.vx))
        mz = max(-MAX_SPEED, min(MAX_SPEED, self.vz))
        nx, nz = self.x + mx, self.z + mz
        if not self._blocked(server, nx, self.y, nz):
            self.x, self.z = nx, nz
        else:
            self.vx = self.vz = 0.0
        # climbing out of a slope
        for ex_, ey_, ez_ in ((ax, ay, az), (cx, cy, cz)):
            if ey_ != 0 and math.floor(self.x) - bx == ex_ and math.floor(self.z) - bz == ez_:
                self.y = by + ey_ + 0.0625
                break

        # AbstractMinecartContainer.applyNaturalSlowdown / AbstractMinecart
        factor = 0.98 + (15 - self.comparator_signal()) * 0.001 if self.is_container else 0.96
        self.vx *= factor
        self.vz *= factor

        if boost:
            speed = math.sqrt(self.vx * self.vx + self.vz * self.vz)
            if speed > 0.01:
                self.vx += self.vx / speed * 0.06
                self.vz += self.vz / speed * 0.06
            elif shape == "east_west":
                if _is_solid(_block(server, bx - 1, by, bz)):
                    self.vx = 0.02
                elif _is_solid(_block(server, bx + 1, by, bz)):
                    self.vx = -0.02
            elif shape == "north_south":
                if _is_solid(_block(server, bx, by, bz - 1)):
                    self.vz = 0.02
                elif _is_solid(_block(server, bx, by, bz + 1)):
                    self.vz = -0.02
        self.vy = 0.0
        self.on_ground = True

    def _come_off_track(self, server):
        self.vx = max(-MAX_SPEED, min(MAX_SPEED, self.vx))
        self.vz = max(-MAX_SPEED, min(MAX_SPEED, self.vz))
        self.vy -= 0.04
        if self.on_ground:
            self.vx *= 0.5
            self.vz *= 0.5
        if not self._blocked(server, self.x, self.y + self.vy, self.z):
            self.y += self.vy
            self.on_ground = False
        else:
            if self.vy < 0:
                self.y = math.floor(self.y + self.vy) + 1.0 if not self._blocked(
                    server, self.x, math.floor(self.y + self.vy) + 1.0, self.z) else self.y
                self.on_ground = True
            self.vy = 0.0
        for axis in ("x", "z"):
            v = self.vx if axis == "x" else self.vz
            nx, nz = (self.x + v, self.z) if axis == "x" else (self.x, self.z + v)
            if not self._blocked(server, nx, self.y, nz):
                self.x, self.z = nx, nz
            elif axis == "x":
                self.vx = 0.0
            else:
                self.vz = 0.0
        if not self.on_ground:
            self.vx *= 0.95
            self.vz *= 0.95
        if self.y < -128:
            self.alive = False

    def _blocked(self, server, x, y, z) -> bool:
        for bx in range(math.floor(x - HALF_WIDTH), math.floor(x + HALF_WIDTH) + 1):
            for bz in range(math.floor(z - HALF_WIDTH), math.floor(z + HALF_WIDTH) + 1):
                for by in range(math.floor(y), math.floor(y + HEIGHT - 1e-6) + 1):
                    if _is_solid(_block(server, bx, by, bz)):
                        return True
        return False

    # ------------------------------------------------------------ persistence

    def to_dict(self) -> dict:
        data = {"variant": self.variant, "x": self.x, "y": self.y, "z": self.z,
                "vx": self.vx, "vy": self.vy, "vz": self.vz, "yaw": self.yaw}
        if self.container is not None:
            data["items"] = [None if s is None or s.is_empty else s.to_dict() for s in self.container.items]
        return data


# ---------------------------------------------------------------- world access

def minecarts(server) -> list:
    manager = getattr(server, "entity_manager", None)
    if manager is None:
        return []
    return [e for e in manager.list_entities() if isinstance(e, MinecartEntity)]


def hopper_minecarts(server) -> list:
    return [e for e in minecarts(server) if e.container is not None]


def container_minecarts_at(server, x: int, y: int, z: int) -> list:
    """Container minecarts whose box reaches into the block (HopperBlockEntity.getEntityContainer)."""
    return [e for e in hopper_minecarts(server) if e.intersects_block(x, y, z)]


def spawn_minecart(server, item_id: str, x: int, y: int, z: int, yaw: float = 0.0):
    """MinecartItem.useOn: put a minecart on the rail at (x, y, z); returns the entity or None."""
    variant = MINECART_ITEMS.get(item_id)
    rail = _rail(server, x, y, z)
    if variant is None or rail is None:
        return None
    shape = rail[1].get("shape", "north_south")
    offset = 0.5 if shape.startswith("ascending") else 0.0
    manager = server.entity_manager
    entity = MinecartEntity(server.get_next_entity_id(), x + 0.5, y + 0.0625 + offset, z + 0.5, variant)
    entity.yaw = yaw
    manager.add_entity(entity)
    return entity


def break_minecart(server, entity, drop: bool = True):
    """AbstractMinecart.destroy: drop the item (and the contents of a container minecart)."""
    entity.alive = False
    if not drop:
        return []
    manager = server.entity_manager
    spawned = [manager.create_item(entity.x, entity.y + 0.3, entity.z, "minecraft:" + entity.variant, 1)]
    if entity.container is not None:
        for stack in entity.container.items:
            if stack is not None and not stack.is_empty:
                spawned.append(manager.create_item(entity.x, entity.y + 0.3, entity.z, stack.item_id, stack.count))
        entity.container.items = [None] * len(entity.container.items)
    return spawned


def hurt_minecart(server, entity, amount: float, creative: bool):
    """AbstractMinecart.hurt: damage builds up (x10). Returns the dropped items when it broke, else None."""
    if creative:
        return break_minecart(server, entity, drop=False)
    entity.damage += amount * 10.0
    if entity.damage > 40.0:
        return break_minecart(server, entity)
    return None


def save_minecarts(server, world_dir) -> None:
    data = [m.to_dict() for m in minecarts(server)]
    path = os.path.join(str(world_dir), SAVE_FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def load_minecarts(server, world_dir) -> int:
    from .inventory import ItemStack
    path = os.path.join(str(world_dir), SAVE_FILE)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    count = 0
    for record in data if isinstance(data, list) else []:
        try:
            entity = MinecartEntity(server.get_next_entity_id(), float(record["x"]), float(record["y"]),
                                    float(record["z"]), record.get("variant", "minecart"))
            entity.vx, entity.vy, entity.vz = (float(record.get(k, 0.0)) for k in ("vx", "vy", "vz"))
            entity.yaw = float(record.get("yaw", 0.0))
            if entity.container is not None:
                items = record.get("items") or []
                for i, raw in enumerate(items[:len(entity.container.items)]):
                    entity.container.items[i] = ItemStack.from_dict(raw) if raw else None
            server.entity_manager.add_entity(entity)
            count += 1
        except (KeyError, TypeError, ValueError):
            continue
    return count
