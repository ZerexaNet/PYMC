import math
import time
import uuid
from dataclasses import dataclass, field


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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

    def __init__(self, entity_id: int, x: float, y: float, z: float,
                 mob_type: str = "pig"):
        super().__init__(entity_id=entity_id, kind="mob", x=x, y=y, z=z)
        self.mob_type = mob_type
        self.health = 20.0 if mob_type in {"zombie", "skeleton"} else 10.0
        self.max_health = self.health
        self.ai_enabled = True
        self.wander_cooldown = 0
        self.metadata = {"mob_type": mob_type}

    def tick(self, server):
        super().tick(server)
        if not self.ai_enabled:
            return

        if self.wander_cooldown > 0:
            self.wander_cooldown -= 1
        else:
            # 很轻量的随机游走占位逻辑，后续 AI 可以直接替换这里。
            seed = (self.entity_id * 1103515245 + self.age_ticks * 12345) & 0xFFFFFFFF
            offset = ((seed % 2001) - 1000) / 1000.0
            self.vx = _clamp(offset * 0.05, -0.1, 0.1)
            self.vz = _clamp((((seed // 7) % 2001) - 1000) / 1000.0 * 0.05, -0.1, 0.1)
            self.wander_cooldown = 20

        self.vy = _clamp(self.vy - 0.08, -3.92, 3.92)
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz

        foot_x = math.floor(self.x)
        foot_y = math.floor(self.y - 0.1)
        foot_z = math.floor(self.z)
        block_below = server.get_block_at(foot_x, foot_y, foot_z)
        if block_below not in (None, 0, 80):
            self.on_ground = True
            self.vy = 0.0
            self.y = foot_y + 1.0
            self.vx *= 0.75
            self.vz *= 0.75
        else:
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
        return self.entities.pop(entity_id, None)

    def get_entity(self, entity_id: int) -> Entity | None:
        return self.entities.get(entity_id)

    def list_entities(self) -> list[Entity]:
        return [entity for entity in self.entities.values() if entity.alive]

    def count_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.list_entities():
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return counts

    def tick(self):
        to_remove: list[int] = []
        for entity in self.entities.values():
            if not entity.alive:
                to_remove.append(entity.entity_id)
                continue
            entity.tick(self.server)
            if not entity.alive:
                to_remove.append(entity.entity_id)

        for entity_id in to_remove:
            self.remove_entity(entity_id)
