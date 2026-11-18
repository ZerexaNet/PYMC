"""In-memory world for exercising the vanilla redstone engine."""

from types import SimpleNamespace

from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK
from world.rs import RedstoneEngine
from world.rs.core import name_of, props_of, with_props

STONE = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:stone"]


def S(name, **props):
    """State id for minecraft:<name> with properties."""
    state = BLOCK_NAME_TO_DEFAULT_STATE["minecraft:" + name]
    return with_props(state, **props) if props else state


class MemoryStorage:
    def __init__(self, floor_y=63):
        self.chunks = {}
        self.floor_y = floor_y
        self.world_dir = "/nonexistent"

    def load_generated_chunk(self, cx, cz):
        chunk = self.chunks.get((cx, cz))
        if chunk is None:
            chunk = [[[0] * 16 for _ in range(16)] for _ in range(384)]
            for z in range(16):
                for x in range(16):
                    chunk[self.floor_y + 64][z][x] = STONE
            self.chunks[(cx, cz)] = chunk
        return chunk

    def save_generated_chunk(self, cx, cz, chunk, biomes=None):
        self.chunks[(cx, cz)] = chunk


class World:
    """Place blocks like a player (side effects included) and step game ticks."""

    native = False      # class default; tests/test_native_engine.py runs everything with True

    def __init__(self, native=None):
        self.storage = MemoryStorage()
        self.entities = []
        manager = SimpleNamespace(list_entities=lambda: list(self.entities),
                                  create_tnt=lambda x, y, z, *a, **k: self.entities.append(
                                      SimpleNamespace(kind="tnt", x=x, y=y, z=z, metadata={})),
                                  create_item=lambda *a, **k: SimpleNamespace(entity_id=0, vx=0, vy=0, vz=0))
        self.server = SimpleNamespace(world_storage=self.storage, entity_manager=manager,
                                      get_online_players=lambda: [])
        if self.native if native is None else native:
            from world.rs.native import NativeRedstoneEngine
            self.engine = NativeRedstoneEngine(self.server)
        else:
            self.engine = RedstoneEngine(self.server)

    def get(self, x, y, z):
        return self.storage.load_generated_chunk(x >> 4, z >> 4)[y + 64][z & 15][x & 15]

    def name(self, x, y, z):
        return name_of(self.get(x, y, z)).split(":")[1]

    def props(self, x, y, z):
        return props_of(self.get(x, y, z))

    def set(self, x, y, z, state):
        """Place/remove a block like a player would (BlockItem.place / destroy)."""
        old = self.get(x, y, z)
        self.storage.load_generated_chunk(x >> 4, z >> 4)[y + 64][z & 15][x & 15] = state
        self.engine.on_block_change(x, y, z, old, state)

    def poke(self, x, y, z, state):
        """Write a block without any update (a 'budded' setup)."""
        self.storage.load_generated_chunk(x >> 4, z >> 4)[y + 64][z & 15][x & 15] = state
        if hasattr(self.engine, "mirror_block"):
            self.engine.mirror_block(x, y, z, state)
        else:
            self.engine.level._chunks.clear()

    def use(self, x, y, z):
        return self.engine.on_player_interact(x, y, z, None)

    def tick(self, n=1):
        for _ in range(n):
            self.engine.tick()
