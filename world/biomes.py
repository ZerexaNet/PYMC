from collections import OrderedDict

from protocol.nbt import NbtByte, NbtFloat
from .noise import OctaveNoise

MIN_Y = -64
SEA_LEVEL = 63
NUM_SECTIONS = 24


def _biome_entry(temperature: float, downfall: float,
                 has_precipitation: bool = True,
                 sky_color: int = 7907327,
                 water_color: int = 4159204,
                 water_fog_color: int = 329011,
                 fog_color: int = 12638463,
                 grass_color: int | None = None,
                 foliage_color: int | None = None,
                 grass_color_modifier: str | None = None) -> dict:
    entry = {
        "has_precipitation": NbtByte(1 if has_precipitation else 0),
        "temperature": NbtFloat(temperature),
        "downfall": NbtFloat(downfall),
        "effects": {
            "sky_color": sky_color,
            "water_color": water_color,
            "water_fog_color": water_fog_color,
            "fog_color": fog_color,
        },
    }
    if grass_color is not None:
        entry["effects"]["grass_color"] = grass_color
    if foliage_color is not None:
        entry["effects"]["foliage_color"] = foliage_color
    if grass_color_modifier is not None:
        entry["effects"]["grass_color_modifier"] = grass_color_modifier
    return entry


BIOME_REGISTRY = OrderedDict({
    "minecraft:badlands": _biome_entry(2.0, 0.0, grass_color=9470285, foliage_color=10387789),
    "minecraft:bamboo_jungle": _biome_entry(0.95, 0.9, grass_color=6141935, foliage_color=6141935),
    "minecraft:basalt_deltas": _biome_entry(2.0, 0.0, False, sky_color=7254527, fog_color=6840176),
    "minecraft:beach": _biome_entry(0.8, 0.4),
    "minecraft:birch_forest": _biome_entry(0.6, 0.6, grass_color=8431445, foliage_color=8431445),
    "minecraft:cherry_grove": _biome_entry(0.5, 0.8, grass_color=11983713, foliage_color=11983713),
    "minecraft:cold_ocean": _biome_entry(0.5, 0.5, False, water_color=4020182),
    "minecraft:crimson_forest": _biome_entry(2.0, 0.0, False, sky_color=7254527, fog_color=3344392),
    "minecraft:dark_forest": _biome_entry(0.7, 0.8, grass_color=2634762, foliage_color=2634762),
    "minecraft:deep_cold_ocean": _biome_entry(0.5, 0.5, False, water_color=4020182),
    "minecraft:deep_dark": _biome_entry(0.8, 0.4, False, sky_color=0, fog_color=12638463),
    "minecraft:deep_frozen_ocean": _biome_entry(0.0, 0.5, True, water_color=3750089),
    "minecraft:deep_lukewarm_ocean": _biome_entry(0.8, 0.4, False, water_color=4566514),
    "minecraft:deep_ocean": _biome_entry(0.5, 0.5, False, water_color=4159204),
    "minecraft:desert": _biome_entry(2.0, 0.0, False, grass_color=16421912, foliage_color=16421912),
    "minecraft:dripstone_caves": _biome_entry(0.8, 0.4, False),
    "minecraft:end_barrens": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:end_highlands": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:end_midlands": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:eroded_badlands": _biome_entry(2.0, 0.0, grass_color=9470285, foliage_color=10387789),
    "minecraft:flower_forest": _biome_entry(0.7, 0.8, grass_color=11272193, foliage_color=11272193),
    "minecraft:forest": _biome_entry(0.7, 0.8),
    "minecraft:frozen_ocean": _biome_entry(0.0, 0.5, True, water_color=3750089),
    "minecraft:frozen_peaks": _biome_entry(-0.7, 0.9),
    "minecraft:frozen_river": _biome_entry(0.0, 0.5),
    "minecraft:grove": _biome_entry(-0.2, 0.8),
    "minecraft:ice_spikes": _biome_entry(0.0, 0.5),
    "minecraft:jagged_peaks": _biome_entry(-0.7, 0.9),
    "minecraft:jungle": _biome_entry(0.95, 0.9, grass_color=5470985, foliage_color=5470985),
    "minecraft:lukewarm_ocean": _biome_entry(0.8, 0.4, False, water_color=4566514),
    "minecraft:lush_caves": _biome_entry(0.5, 0.5, False, grass_color=9286496, foliage_color=9286496),
    "minecraft:mangrove_swamp": _biome_entry(0.8, 0.9, grass_color=9285927, foliage_color=9285927),
    "minecraft:meadow": _biome_entry(0.5, 0.8, grass_color=937679, foliage_color=9470285),
    "minecraft:mushroom_fields": _biome_entry(0.9, 1.0, False, grass_color=10486015, foliage_color=10486015),
    "minecraft:nether_wastes": _biome_entry(2.0, 0.0, False, sky_color=7254527, fog_color=3344392),
    "minecraft:ocean": _biome_entry(0.5, 0.5, False, water_color=4159204),
    "minecraft:old_growth_birch_forest": _biome_entry(0.6, 0.6, grass_color=8431445, foliage_color=8431445),
    "minecraft:old_growth_pine_taiga": _biome_entry(0.3, 0.8, grass_color=10387789, foliage_color=10387789),
    "minecraft:old_growth_spruce_taiga": _biome_entry(0.25, 0.8, grass_color=8233509, foliage_color=8233509),
    "minecraft:plains": _biome_entry(0.8, 0.4),
    "minecraft:river": _biome_entry(0.5, 0.5),
    "minecraft:savanna": _biome_entry(1.2, 0.0, grass_color=12431967, foliage_color=12431967),
    "minecraft:savanna_plateau": _biome_entry(1.0, 0.0, grass_color=12431967, foliage_color=12431967),
    "minecraft:small_end_islands": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:snowy_beach": _biome_entry(0.05, 0.3),
    "minecraft:snowy_plains": _biome_entry(0.0, 0.5),
    "minecraft:snowy_slopes": _biome_entry(-0.3, 0.9),
    "minecraft:snowy_taiga": _biome_entry(-0.5, 0.4),
    "minecraft:soul_sand_valley": _biome_entry(2.0, 0.0, False, sky_color=7254527, fog_color=1787717),
    "minecraft:sparse_jungle": _biome_entry(0.95, 0.8, grass_color=5470985, foliage_color=5470985),
    "minecraft:stony_peaks": _biome_entry(1.0, 0.3),
    "minecraft:stony_shore": _biome_entry(0.2, 0.3),
    "minecraft:sunflower_plains": _biome_entry(0.8, 0.4),
    "minecraft:swamp": _biome_entry(0.8, 0.9, grass_color=6975545, foliage_color=6975545, grass_color_modifier="swamp"),
    "minecraft:taiga": _biome_entry(0.25, 0.8),
    "minecraft:the_end": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:the_void": _biome_entry(0.5, 0.5, False, sky_color=0, water_color=4159204),
    "minecraft:warm_ocean": _biome_entry(0.9, 0.5, False, water_color=4445678),
    "minecraft:warped_forest": _biome_entry(2.0, 0.0, False, sky_color=7254527, fog_color=1705242),
    "minecraft:windswept_forest": _biome_entry(0.2, 0.3),
    "minecraft:windswept_gravelly_hills": _biome_entry(0.2, 0.3),
    "minecraft:windswept_hills": _biome_entry(0.2, 0.3),
    "minecraft:windswept_savanna": _biome_entry(1.1, 0.0, grass_color=12431967, foliage_color=12431967),
    "minecraft:wooded_badlands": _biome_entry(2.0, 0.0, grass_color=9470285, foliage_color=10387789),
})

BIOME_NAME_TO_ID = {name: index for index, name in enumerate(BIOME_REGISTRY.keys())}
BIOME_ID_TO_NAME = {index: name for name, index in BIOME_NAME_TO_ID.items()}


def build_biome_registry_entries() -> OrderedDict:
    return BIOME_REGISTRY.copy()


class BiomeSampler:
    def __init__(self, seed: int = 0):
        self.seed = seed
        self.temperature_noise = OctaveNoise(seed + 11, octaves=3, persistence=0.5, lacunarity=2.0)
        self.humidity_noise = OctaveNoise(seed + 12, octaves=3, persistence=0.5, lacunarity=2.0)
        self.continental_noise = OctaveNoise(seed + 13, octaves=3, persistence=0.5, lacunarity=2.0)
        self.erosion_noise = OctaveNoise(seed + 14, octaves=3, persistence=0.5, lacunarity=2.0)
        self.weirdness_noise = OctaveNoise(seed + 15, octaves=2, persistence=0.5, lacunarity=2.0)
        self.swamp_noise = OctaveNoise(seed + 16, octaves=2, persistence=0.5, lacunarity=2.0)
        self.mushroom_noise = OctaveNoise(seed + 17, octaves=1, persistence=1.0, lacunarity=2.0)

    def _sample_climate(self, world_x: int, world_z: int) -> tuple[float, float, float, float, float]:
        temperature = self.temperature_noise.sample(world_x / 512.0, world_z / 512.0)
        humidity = self.humidity_noise.sample(world_x / 384.0, world_z / 384.0)
        continental = self.continental_noise.sample(world_x / 768.0, world_z / 768.0)
        erosion = self.erosion_noise.sample(world_x / 256.0, world_z / 256.0)
        weirdness = self.weirdness_noise.sample(world_x / 192.0, world_z / 192.0)
        return temperature, humidity, continental, erosion, weirdness

    def sample_surface_biome(self, world_x: int, world_z: int, surface_height: int) -> str:
        temperature, humidity, continental, erosion, weirdness = self._sample_climate(world_x, world_z)
        swampiness = self.swamp_noise.sample(world_x / 160.0, world_z / 160.0)
        mushroom = self.mushroom_noise.sample(world_x / 2048.0, world_z / 2048.0)

        if mushroom > 0.82 and continental < -0.15:
            return "minecraft:mushroom_fields"

        if continental < -0.55:
            if temperature < -0.45:
                return "minecraft:deep_frozen_ocean" if surface_height < SEA_LEVEL - 10 else "minecraft:frozen_ocean"
            if temperature < -0.05:
                return "minecraft:deep_cold_ocean" if surface_height < SEA_LEVEL - 10 else "minecraft:cold_ocean"
            if temperature > 0.65:
                return "minecraft:warm_ocean" if humidity > 0.35 else "minecraft:lukewarm_ocean"
            return "minecraft:deep_ocean" if surface_height < SEA_LEVEL - 10 else "minecraft:ocean"

        if continental < -0.42:
            if temperature < -0.25:
                return "minecraft:frozen_river"
            return "minecraft:river"

        if surface_height <= SEA_LEVEL + 2:
            if temperature < -0.3:
                return "minecraft:snowy_beach"
            if erosion < -0.35:
                return "minecraft:stony_shore"
            return "minecraft:beach"

        if surface_height > 140 or (surface_height > 118 and weirdness > 0.55):
            if temperature < -0.45:
                return "minecraft:jagged_peaks" if weirdness > 0.15 else "minecraft:frozen_peaks"
            if temperature < -0.1:
                return "minecraft:snowy_slopes" if humidity > 0.0 else "minecraft:grove"
            return "minecraft:stony_peaks"

        if surface_height > 110:
            if temperature < -0.2:
                return "minecraft:grove"
            return "minecraft:meadow"

        if temperature > 0.8 and humidity < -0.05:
            if weirdness > 0.35:
                return "minecraft:eroded_badlands"
            if erosion < -0.15:
                return "minecraft:wooded_badlands"
            if humidity < -0.3:
                return "minecraft:desert"
            return "minecraft:badlands"

        if temperature > 0.7 and humidity > 0.3:
            if humidity > 0.65 and weirdness > 0.2:
                return "minecraft:bamboo_jungle"
            if humidity > 0.5:
                return "minecraft:jungle"
            return "minecraft:sparse_jungle"

        if 0.35 < temperature <= 0.8 and humidity > 0.35 and surface_height <= SEA_LEVEL + 12:
            return "minecraft:mangrove_swamp" if swampiness > 0.25 else "minecraft:swamp"

        if temperature > 0.45 and humidity < 0.15:
            if weirdness > 0.45:
                return "minecraft:windswept_savanna"
            if surface_height > 88:
                return "minecraft:savanna_plateau"
            return "minecraft:savanna"

        if temperature < -0.45:
            if weirdness > 0.55:
                return "minecraft:ice_spikes"
            if humidity > 0.0:
                return "minecraft:snowy_taiga"
            return "minecraft:snowy_plains"

        if humidity < -0.35:
            if weirdness > 0.45:
                return "minecraft:windswept_gravelly_hills"
            if weirdness > 0.15 or surface_height > 90:
                return "minecraft:windswept_hills"
            return "minecraft:plains"

        if humidity > 0.55:
            if surface_height > 88 and weirdness > 0.15:
                return "minecraft:old_growth_spruce_taiga"
            if temperature < 0.35:
                return "minecraft:taiga"
            if weirdness > 0.45:
                return "minecraft:dark_forest"
            return "minecraft:forest"

        if 0.45 < humidity <= 0.55:
            if weirdness > 0.55:
                return "minecraft:flower_forest"
            if weirdness > 0.25:
                return "minecraft:birch_forest"
            return "minecraft:forest"

        if 0.2 < humidity <= 0.45:
            if surface_height > 95 and weirdness > 0.35:
                return "minecraft:old_growth_birch_forest"
            if temperature < 0.35:
                return "minecraft:old_growth_pine_taiga"
            if weirdness > 0.5:
                return "minecraft:cherry_grove"
            return "minecraft:plains"

        return "minecraft:sunflower_plains" if weirdness > 0.6 else "minecraft:plains"

    def sample_biome(self, world_x: int, world_y: int, world_z: int,
                     surface_height: int) -> str:
        surface_biome = self.sample_surface_biome(world_x, world_z, surface_height)
        temperature, humidity, continental, erosion, weirdness = self._sample_climate(world_x, world_z)
        depth = surface_height - world_y

        if world_y < -48 and depth > 16 and continental > 0.15 and erosion < -0.05:
            return "minecraft:deep_dark"
        if world_y < 40 and depth > 12:
            if humidity > 0.35 and temperature > 0.0:
                return "minecraft:lush_caves"
            if humidity < -0.15 and weirdness > 0.0:
                return "minecraft:dripstone_caves"
        return surface_biome

    def build_chunk_biome_sections(self, chunk_x: int, chunk_z: int,
                                   chunk_blocks: list[list[list[int]]]) -> list[list[int]]:
        base_x = chunk_x * 16
        base_z = chunk_z * 16
        surface_heights = [[MIN_Y for _ in range(16)] for _ in range(16)]

        for z in range(16):
            for x in range(16):
                for y_index in range(len(chunk_blocks) - 1, -1, -1):
                    if chunk_blocks[y_index][z][x] != 0:
                        surface_heights[z][x] = y_index + MIN_Y
                        break

        sections: list[list[int]] = []
        for section_idx in range(NUM_SECTIONS):
            section_biomes: list[int] = []
            for local_biome_y in range(4):
                for biome_z in range(4):
                    for biome_x in range(4):
                        sample_x = biome_x * 4 + 2
                        sample_z = biome_z * 4 + 2
                        world_x = base_x + sample_x
                        world_z = base_z + sample_z
                        world_y = MIN_Y + section_idx * 16 + local_biome_y * 4 + 2
                        surface_height = surface_heights[min(15, sample_z)][min(15, sample_x)]
                        biome_name = self.sample_biome(world_x, world_y, world_z, surface_height)
                        section_biomes.append(BIOME_NAME_TO_ID[biome_name])
            sections.append(section_biomes)
        return sections
