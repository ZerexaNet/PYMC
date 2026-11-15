import unittest

from handlers.play import _is_safe_player_location, _resolve_spawn_location
from world.blocks import AIR, GRASS_BLOCK, LAVA, STONE, WATER


def _empty_chunk():
    return [[[AIR for _ in range(16)] for _ in range(16)] for _ in range(384)]


def _set_block(chunk, x, y, z, block_id):
    chunk[y + 64][z & 15][x & 15] = block_id


def _make_ground_chunk(ground_y=64, block_id=GRASS_BLOCK):
    chunk = _empty_chunk()
    for z in range(16):
        for x in range(16):
            _set_block(chunk, x, ground_y, z, block_id)
    return chunk


class FakeStorage:
    def __init__(self, chunks=None):
        self.chunks = dict(chunks or {})
        self.saved = []

    def load_generated_chunk_with_biomes(self, cx, cz):
        chunk = self.chunks.get((cx, cz))
        if chunk is None:
            return None
        return chunk, None

    def load_generated_chunk(self, cx, cz):
        return self.chunks.get((cx, cz))

    def save_generated_chunk(self, cx, cz, chunk_blocks, chunk_biomes=None):
        self.chunks[(cx, cz)] = chunk_blocks
        self.saved.append((cx, cz))


class FakeTerrain:
    def __init__(self, chunk):
        self.chunk = chunk

    def generate_chunk(self, cx, cz):
        return self.chunk


class FakeServer:
    def __init__(self, storage, terrain=None):
        self.world_storage = storage
        self.terrain_generator = terrain
        self.biome_sampler = None
        self._use_native_terrain = False
        self.spawn_position = (0, 100, 0)

    def _initialize_terrain_generator(self):
        pass


class SpawnSafetyTests(unittest.TestCase):
    def test_resolve_spawn_generates_missing_chunk(self):
        generated_chunk = _make_ground_chunk(64, GRASS_BLOCK)
        server = FakeServer(FakeStorage(), FakeTerrain(generated_chunk))

        self.assertEqual(_resolve_spawn_location(server, 0, 0), (0, 65, 0))
        self.assertIn((0, 0), server.world_storage.saved)

    def test_resolve_spawn_stands_on_top_of_the_column(self):
        # Like vanilla, the player stands on the topmost full block.
        chunk = _empty_chunk()
        _set_block(chunk, 0, 64, 0, GRASS_BLOCK)
        _set_block(chunk, 0, 65, 0, STONE)
        _set_block(chunk, 1, 64, 0, GRASS_BLOCK)
        server = FakeServer(FakeStorage({(0, 0): chunk}))

        self.assertEqual(_resolve_spawn_location(server, 0, 0), (0, 66, 0))

    def test_resolve_spawn_skips_water_and_lava(self):
        chunk = _empty_chunk()
        for z in range(16):
            for x in range(16):
                _set_block(chunk, x, 50, z, STONE)
                _set_block(chunk, x, 51, z, WATER)
        _set_block(chunk, 5, 51, 0, STONE)            # an island far enough from lava
        _set_block(chunk, 1, 51, 0, LAVA)             # lava pool top
        _set_block(chunk, 2, 51, 0, STONE)            # stone right next to the lava
        server = FakeServer(FakeStorage({(0, 0): chunk}))

        self.assertEqual(_resolve_spawn_location(server, 0, 0), (5, 52, 0))

    def test_new_players_spawn_within_spawn_radius_on_safe_ground(self):
        from handlers.play.spawn import fudge_spawn_location
        chunks = {}
        for cx in (-1, 0):
            for cz in (-1, 0):
                chunk = _make_ground_chunk(64, GRASS_BLOCK)
                chunks[(cx, cz)] = chunk
        _set_block(chunks[(0, 0)], 0, 65, 0, LAVA)
        server = FakeServer(FakeStorage(chunks))
        server.gamerules = {"spawnRadius": 3}
        for _ in range(50):
            x, y, z = fudge_spawn_location(server, (0, 65, 0))
            self.assertLessEqual(abs(x), 3)
            self.assertLessEqual(abs(z), 3)
            self.assertEqual(y, 65)
            self.assertGreater(abs(x) + abs(z), 1)    # never on or next to the lava

    def test_safe_location_requires_air_space_and_solid_ground(self):
        chunk = _make_ground_chunk(70, GRASS_BLOCK)
        server = FakeServer(FakeStorage({(0, 0): chunk}))

        self.assertTrue(_is_safe_player_location(server, 0, 71, 0))
        _set_block(chunk, 0, 71, 0, WATER)
        self.assertFalse(_is_safe_player_location(server, 0, 71, 0))
        _set_block(chunk, 0, 71, 0, AIR)
        _set_block(chunk, 0, 70, 0, WATER)
        self.assertFalse(_is_safe_player_location(server, 0, 71, 0))


if __name__ == "__main__":
    unittest.main()
