import math
import random
import time
import uuid
from dataclasses import dataclass, field

from .blocks import AIR, WATER, LAVA, FIRE, SOUL_FIRE, POWDER_SNOW, POWDER_SNOW_CAULDRON


PASSABLE_BLOCKS = {AIR, WATER, LAVA, FIRE, SOUL_FIRE, POWDER_SNOW, POWDER_SNOW_CAULDRON}

MOB_PROFILES = {
    "pig": {
        "category": "passive",
        "health": 10.0,
        "speed": 0.055,
        "wander_interval": 120,
        "look_range": 8.0,
        "height": 0.9,
        "drops": [("minecraft:porkchop", 1, 3)],
        "xp": (1, 3),
    },
    "cow": {
        "category": "passive",
        "health": 10.0,
        "speed": 0.055,
        "wander_interval": 120,
        "look_range": 8.0,
        "height": 1.4,
        "drops": [("minecraft:beef", 1, 3), ("minecraft:leather", 0, 2)],
        "xp": (1, 3),
    },
    "sheep": {
        "category": "passive",
        "health": 8.0,
        "speed": 0.055,
        "wander_interval": 120,
        "look_range": 8.0,
        "height": 1.3,
        "drops": [("minecraft:mutton", 1, 2), ("minecraft:white_wool", 1, 1)],
        "xp": (1, 3),
    },
    "zombie": {
        "category": "hostile",
        "health": 20.0,
        "speed": 0.075,
        "follow_range": 35.0,
        "attack_damage": 3.0,
        "attack_range": 1.7,
        "attack_interval": 20,
        "height": 1.95,
        "drops": [("minecraft:rotten_flesh", 0, 2)],
        "xp": (5, 5),
    },
    "skeleton": {
        "category": "hostile",
        "health": 20.0,
        "speed": 0.07,
        "follow_range": 35.0,
        "attack_damage": 2.0,
        "attack_range": 15.0,
        "attack_interval": 30,
        "height": 1.99,
        "ranged": True,
        "drops": [("minecraft:bone", 0, 2), ("minecraft:arrow", 0, 2)],
        "xp": (5, 5),
    },
    "creeper": {
        "category": "hostile",
        "health": 20.0,
        "speed": 0.078,
        "follow_range": 25.0,
        "attack_damage": 8.0,
        "attack_range": 2.4,
        "attack_interval": 35,
        "height": 1.7,
        "drops": [("minecraft:gunpowder", 0, 2)],
        "xp": (5, 5),
    },
    "spider": {
        "category": "hostile",
        "health": 16.0,
        "speed": 0.105,
        "follow_range": 24.0,
        "attack_damage": 2.0,
        "attack_range": 1.9,
        "attack_interval": 20,
        "height": 0.9,
        "drops": [("minecraft:string", 0, 2), ("minecraft:spider_eye", 0, 1)],
        "xp": (5, 5),
    },
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_passable(block_id: int | None) -> bool:
    return block_id is not None and block_id in PASSABLE_BLOCKS


def _is_solid(block_id: int | None) -> bool:
    return block_id is None or block_id not in PASSABLE_BLOCKS


@dataclass
class Entity:
    entity_id: int
    kind: str
    x: float
    y: float
    z: float
    yaw: float = 0.0
    pitch: float = 0.0
    uuid_value: uuid.UUID = field(default_factory=uuid.uuid4)
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    on_ground: bool = False
    alive: bool = True
    age_ticks: int = 0
    persistent: bool = False
    custom_name: str | None = None
    metadata: dict = field(default_factory=dict)

    def tick(self, server):
        self.age_ticks += 1

    def distance_squared_to(self, x: float, y: float, z: float) -> float:
        dx = self.x - x
        dy = self.y - y
        dz = self.z - z
        return dx * dx + dy * dy + dz * dz

    def as_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "uuid": str(self.uuid_value),
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "yaw": self.yaw,
            "pitch": self.pitch,
            "vx": self.vx,
            "vy": self.vy,
            "vz": self.vz,
            "on_ground": self.on_ground,
            "alive": self.alive,
            "age_ticks": self.age_ticks,
            "persistent": self.persistent,
            "custom_name": self.custom_name,
            "metadata": dict(self.metadata),
        }


@dataclass
class ItemEntity(Entity):
    item_name: str = "minecraft:stone"
    count: int = 1
    pickup_delay: int = 20

    def __init__(self, entity_id: int, x: float, y: float, z: float,
                 item_name: str = "minecraft:stone", count: int = 1):
        super().__init__(entity_id=entity_id, kind="item", x=x, y=y, z=z)
        self.item_name = item_name
        self.count = count
        self.pickup_delay = 20
        self.metadata = {"item_name": item_name, "count": count}

    def tick(self, server):
        super().tick(server)
        if self.pickup_delay > 0:
            self.pickup_delay -= 1

        # 基础重力与阻尼。
        self.vy = _clamp(self.vy - 0.04, -3.92, 3.92)
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz
        self.vx *= 0.98
        self.vy *= 0.98
        self.vz *= 0.98

        # 粗略地面碰撞。
        foot_x = math.floor(self.x)
        foot_y = math.floor(self.y - 0.1)
        foot_z = math.floor(self.z)
        block_below = server.get_block_at(foot_x, foot_y, foot_z)
        if block_below not in (None, 0, 80):
            self.on_ground = True
            self.vy = 0.0
            self.y = foot_y + 1.0
            self.vx *= 0.6
            self.vz *= 0.6
        else:
            self.on_ground = False

        # 超时自动清理。
        if self.age_ticks >= 6000 and not self.persistent:
            self.alive = False


@dataclass
class MobEntity(Entity):
    mob_type: str = "pig"
    health: float = 10.0
    max_health: float = 10.0
    ai_enabled: bool = True
    wander_cooldown: int = 0
    attack_cooldown: int = 0
    target_username: str | None = None
    aggressive_ticks: int = 0
    look_time: int = 0
    target_x: float | None = None
    target_y: float | None = None
    target_z: float | None = None

    def __init__(self, entity_id: int, x: float, y: float, z: float,
                 mob_type: str = "pig"):
        super().__init__(entity_id=entity_id, kind="mob", x=x, y=y, z=z)
        self.mob_type = mob_type
        self.profile = MOB_PROFILES.get(mob_type, MOB_PROFILES["pig"])
        self.health = float(self.profile["health"])
        self.max_health = self.health
        self.ai_enabled = True
        self.wander_cooldown = 0
        self.attack_cooldown = 0
        self.target_username = None
        self.aggressive_ticks = 0
        self.look_time = 0
        self.target_x = None
        self.target_y = None
        self.target_z = None
        self._rng = random.Random((entity_id << 16) ^ int(x * 31) ^ int(z * 131))
        self.metadata = {
            "mob_type": mob_type,
            "category": self.profile.get("category", "passive"),
            "health": self.health,
            "max_health": self.max_health,
            "aggressive": False,
        }

    def tick(self, server, native_ai=None):
        super().tick(server)
        if not self.ai_enabled:
            return
        if self.attack_cooldown > 0:
            self.attack_cooldown -= 1

        used_native_ai = False
        if native_ai is not None:
            used_native_ai = native_ai.tick_mob(self, server)

        if not used_native_ai:
            if self.profile.get("category") == "hostile":
                self._tick_hostile_ai(server)
            else:
                self._tick_passive_ai(server)

        self._apply_physics(server)
        self.metadata["health"] = self.health
        self.metadata["aggressive"] = self.aggressive_ticks > 0

    def _find_chase_target(self, server):
        nearest = None
        follow_range = float(self.profile.get("follow_range", 16.0))
        nearest_distance = follow_range * follow_range
        for player in server.get_online_players():
            if player.gamemode in {"creative", "spectator"}:
                continue
            distance = self.distance_squared_to(player.x, player.y, player.z)
            if distance < nearest_distance:
                nearest = player
                nearest_distance = distance
        return nearest

    def _tick_hostile_ai(self, server):
        target = self._find_chase_target(server)
        if target is None:
            self.target_username = None
            self.aggressive_ticks = max(0, self.aggressive_ticks - 1)
            self._tick_wander()
            return

        self.target_username = target.username
        dx = target.x - self.x
        dz = target.z - self.z
        distance = math.sqrt(dx * dx + dz * dz)
        if distance > 0.001:
            speed = float(self.profile.get("speed", 0.06))
            self.vx = _clamp(dx / distance * speed, -0.16, 0.16)
            self.vz = _clamp(dz / distance * speed, -0.16, 0.16)
            self.yaw = math.degrees(math.atan2(-dx, dz))
            if self.mob_type == "zombie":
                self.aggressive_ticks = min(20, self.aggressive_ticks + 1)

    def _tick_passive_ai(self, server):
        if self.look_time > 0:
            self.look_time -= 1
            player = self._nearest_player(server, float(self.profile.get("look_range", 8.0)))
            if player is not None:
                self._look_at(player.x, player.y, player.z)
                self.vx *= 0.75
                self.vz *= 0.75
                return

        if self._rng.random() < 0.02:
            player = self._nearest_player(server, float(self.profile.get("look_range", 8.0)))
            if player is not None:
                self.look_time = 40 + self._rng.randint(0, 39)
                self._look_at(player.x, player.y, player.z)
                return

        self._tick_wander()

    def _tick_wander(self):
        if self.target_x is not None:
            dx = self.target_x - self.x
            dz = self.target_z - self.z
            distance = math.sqrt(dx * dx + dz * dz)
            if distance < 0.7:
                self.target_x = self.target_y = self.target_z = None
                self.vx *= 0.4
                self.vz *= 0.4
                return
            speed = float(self.profile.get("speed", 0.05))
            self.vx = _clamp(dx / distance * speed, -0.12, 0.12)
            self.vz = _clamp(dz / distance * speed, -0.12, 0.12)
            self.yaw = math.degrees(math.atan2(-dx, dz))
            return

        if self.wander_cooldown > 0:
            self.wander_cooldown -= 1
            self.vx *= 0.85
            self.vz *= 0.85
            return

        angle = self._rng.random() * math.tau
        radius = 4.0 + self._rng.random() * 6.0
        self.target_x = self.x + math.cos(angle) * radius
        self.target_y = self.y
        self.target_z = self.z + math.sin(angle) * radius
        interval = int(self.profile.get("wander_interval", 120))
        self.wander_cooldown = max(20, interval // 2 + self._rng.randint(0, interval))

    def _nearest_player(self, server, radius: float):
        nearest = None
        nearest_distance = radius * radius
        for player in server.get_online_players():
            distance = self.distance_squared_to(player.x, player.y, player.z)
            if distance < nearest_distance:
                nearest = player
                nearest_distance = distance
        return nearest

    def _look_at(self, x: float, y: float, z: float):
        dx = x - self.x
        dy = y - self.y
        dz = z - self.z
        horizontal = max(0.001, math.sqrt(dx * dx + dz * dz))
        self.yaw = math.degrees(math.atan2(-dx, dz))
        self.pitch = _clamp(-math.degrees(math.atan2(dy, horizontal)), -90.0, 90.0)

    def _can_occupy(self, server, x: float, y: float, z: float) -> bool:
        block_x = math.floor(x)
        block_z = math.floor(z)
        foot_y = math.floor(y)
        head_y = math.floor(y + float(self.profile.get("height", 1.8)) - 0.05)
        if not _is_passable(server.get_block_at(block_x, foot_y, block_z)):
            return False
        if head_y != foot_y and not _is_passable(server.get_block_at(block_x, head_y, block_z)):
            return False
        return True

    def _apply_physics(self, server):
        self.vy = _clamp(self.vy - 0.08, -3.92, 3.92)

        next_x = self.x + self.vx
        next_z = self.z + self.vz
        if self._can_occupy(server, next_x, self.y, next_z):
            self.x = next_x
            self.z = next_z
        elif self.on_ground and self._can_occupy(server, next_x, self.y + 1.0, next_z):
            self.x = next_x
            self.y += 1.0
            self.z = next_z
            self.vy = max(self.vy, 0.0)
        else:
            self.vx *= -0.15
            self.vz *= -0.15
            self.target_x = self.target_y = self.target_z = None

        next_y = self.y + self.vy
        if self.vy <= 0:
            start_y = math.floor(self.y - 0.1)
            end_y = math.floor(next_y - 0.1)
            landed_y = None
            for block_y in range(start_y, end_y - 1, -1):
                if _is_solid(server.get_block_at(math.floor(self.x), block_y, math.floor(self.z))):
                    landed_y = block_y + 1.0
                    break
            if landed_y is not None:
                self.y = landed_y
                self.vy = 0.0
                self.on_ground = True
                self.vx *= 0.75
                self.vz *= 0.75
            else:
                self.y = next_y
                self.on_ground = False
        else:
            head_y = math.floor(next_y + float(self.profile.get("height", 1.8)))
            if _is_solid(server.get_block_at(math.floor(self.x), head_y, math.floor(self.z))):
                self.vy = 0.0
            else:
                self.y = next_y
                self.on_ground = False


@dataclass
class ExperienceOrbEntity(Entity):
    count: int = 1

    def __init__(self, entity_id: int, x: float, y: float, z: float, count: int = 1):
        super().__init__(entity_id=entity_id, kind="orb", x=x, y=y, z=z)
        self.count = count
        self.metadata = {"count": count}

    def tick(self, server):
        super().tick(server)
        self.vy = _clamp(self.vy - 0.03, -3.92, 3.92)
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz
        self.vx *= 0.98
        self.vy *= 0.98
        self.vz *= 0.98

        foot_x = math.floor(self.x)
        foot_y = math.floor(self.y - 0.1)
        foot_z = math.floor(self.z)
        block_below = server.get_block_at(foot_x, foot_y, foot_z)
        if block_below not in (None, 0, 80):
            self.on_ground = True
            self.vy = 0.0
            self.y = foot_y + 0.2
            self.vx *= 0.7
            self.vz *= 0.7
        else:
            self.on_ground = False

        if self.age_ticks >= 6000 and not self.persistent:
            self.alive = False


class EntityManager:
    def __init__(self, server):
        self.server = server
        self.entities: dict[int, Entity] = {}
        self.spawned_at: dict[int, float] = {}
        self.removed_ids: list[int] = []
        self.native_ai = None
        try:
            from .ai_native import NativeMobAiEngine
            self.native_ai = NativeMobAiEngine()
        except Exception:
            self.native_ai = None

    def create_item(self, x: float, y: float, z: float,
                    item_name: str = "minecraft:stone", count: int = 1) -> ItemEntity:
        entity = ItemEntity(self.server.get_next_entity_id(), x, y, z, item_name, count)
        self.add_entity(entity)
        return entity

    def create_mob(self, x: float, y: float, z: float, mob_type: str = "pig") -> MobEntity:
        entity = MobEntity(self.server.get_next_entity_id(), x, y, z, mob_type)
        self.add_entity(entity)
        return entity

    def create_experience_orb(self, x: float, y: float, z: float, count: int = 1) -> ExperienceOrbEntity:
        entity = ExperienceOrbEntity(self.server.get_next_entity_id(), x, y, z, count)
        self.add_entity(entity)
        return entity

    def add_entity(self, entity: Entity):
        self.entities[entity.entity_id] = entity
        self.spawned_at[entity.entity_id] = time.time()

    def remove_entity(self, entity_id: int) -> Entity | None:
        self.spawned_at.pop(entity_id, None)
        entity = self.entities.pop(entity_id, None)
        if entity is not None:
            self.removed_ids.append(entity_id)
        return entity

    def get_entity(self, entity_id: int) -> Entity | None:
        return self.entities.get(entity_id)

    def list_entities(self) -> list[Entity]:
        return [entity for entity in self.entities.values() if entity.alive]

    def count_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.list_entities():
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return counts

    def count_mobs(self) -> int:
        return sum(1 for entity in self.list_entities() if entity.kind == "mob")

    def spawn_natural_mobs(self, max_spawned: int = 2, cap: int = 32) -> int:
        """Spawn a small vanilla-inspired trickle near players."""
        players = self.server.get_online_players()
        if not players or self.count_mobs() >= cap:
            return 0

        terrain = getattr(self.server, "terrain_generator", None)
        if terrain is None:
            return 0

        spawned = 0
        rng = random.Random(int(time.time() * 20) ^ self.server.next_entity_id)
        is_night = 13000 <= int(getattr(self.server, "world_time", 0)) <= 23000

        for player in players:
            if spawned >= max_spawned or self.count_mobs() >= cap:
                break
            if player.gamemode == "spectator":
                continue

            angle = rng.random() * math.tau
            radius = rng.randint(24, 48)
            x = math.floor(player.x + math.cos(angle) * radius)
            z = math.floor(player.z + math.sin(angle) * radius)
            try:
                y = int(terrain.get_terrain_height(x, z)) + 1
            except Exception:
                continue

            if abs(x - player.x) < 24 and abs(z - player.z) < 24:
                continue
            if not _is_passable(self.server.get_block_at(x, y, z)):
                continue
            if not _is_solid(self.server.get_block_at(x, y - 1, z)):
                continue

            mob_type = rng.choice(["zombie", "skeleton", "creeper", "spider"]) if is_night else rng.choice(["pig", "cow", "sheep"])
            self.create_mob(x + 0.5, y, z + 0.5, mob_type=mob_type)
            spawned += 1

        return spawned

    def tick(self):
        to_remove: list[int] = []
        for entity in self.entities.values():
            if not entity.alive:
                to_remove.append(entity.entity_id)
                continue
            if isinstance(entity, MobEntity):
                entity.tick(self.server, self.native_ai)
            else:
                entity.tick(self.server)
            if not entity.alive:
                to_remove.append(entity.entity_id)

        for entity_id in to_remove:
            self.remove_entity(entity_id)

    def shutdown(self):
        if self.native_ai is not None:
            self.native_ai.shutdown()
            self.native_ai = None

    def consume_removed_ids(self) -> list[int]:
        removed = list(dict.fromkeys(self.removed_ids))
        self.removed_ids.clear()
        return removed
