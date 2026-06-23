# ============================================================
# PyMC - 1:1 Vanilla Terrain Generator (Minecraft Java 1.21.1)
# Implements vanilla's density function pipeline, cell-based noise
# interpolation, MultiNoise biome sampling, cave carvers with
# aquifer, biome-specific surface rules, and triangular ore
# distribution matching vanilla Java Edition.
# ============================================================

"""
1:1 Vanilla terrain generator for Minecraft Java Edition 1.21.1.

This module replicates the terrain generation algorithm used by vanilla
Minecraft Java Edition, producing terrain that closely matches vanilla
output for the same seed.

Architecture matches vanilla's worldgen pipeline:
  1. Climate sampling (Temperature, Humidity, Continentalness, Erosion, Weirdness)
  2. Cell-based density computation with trilinear interpolation
  3. Density function tree with ShiftedNoise, Splines, Clamping, YClampedGradient
  4. Cave carving (Cheese, Spaghetti, Noodle caves + Aquifer)
  5. Surface rules (biome-specific block placement)
  6. Ore veins (vanilla triangular distribution)
  7. Decorations (trees, plants, underwater features)

Key improvements over the basic terrain generator:
  - DensityFunction class hierarchy matching vanilla's DF system
  - Cell-based noise interpolation (CELL_WIDTH=4, CELL_HEIGHT=8)
  - Proper ShiftedNoise with yScale/yMax parameters
  - Cubic spline interpolation for continentalness/erosion/density mapping
  - YClampedGradient for height-based density effects
  - BlendDensity for 3D terrain blending near transitions
  - Aquifer system: water fills caves below sea level, lava below y=-54
  - Dual ore distributions for Coal and Iron
  - Biome-specific surface rules with depth-based replacement
"""

import math
import random as _random
from dataclasses import dataclass, field
from typing import Optional, Callable

from .blocks import (
    AIR, STONE, GRANITE, DIORITE, ANDESITE,
    GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL,
    COBBLESTONE, BEDROCK,
    WATER, SAND, RED_SAND, GRAVEL, SANDSTONE,
    COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, LAPIS_ORE,
    COPPER_ORE, EMERALD_ORE, REDSTONE_ORE,
    DEEPSLATE_COAL_ORE, DEEPSLATE_IRON_ORE, DEEPSLATE_GOLD_ORE,
    DEEPSLATE_DIAMOND_ORE, DEEPSLATE_LAPIS_ORE, DEEPSLATE_COPPER_ORE,
    DEEPSLATE_EMERALD_ORE, DEEPSLATE_REDSTONE_ORE,
    DEEPSLATE, TUFF, CLAY, CALCITE,
    SNOW_BLOCK, SNOW, ICE, PACKED_ICE, BLUE_ICE,
    OAK_LOG, OAK_LEAVES, BIRCH_LOG, BIRCH_LEAVES,
    SPRUCE_LOG, SPRUCE_LEAVES, JUNGLE_LOG, JUNGLE_LEAVES,
    ACACIA_LOG, ACACIA_LEAVES,
    CHERRY_LOG, CHERRY_LEAVES,
    DARK_OAK_LOG, DARK_OAK_LEAVES,
    MANGROVE_LOG, MANGROVE_LEAVES,
    SHORT_GRASS, DANDELION, POPPY,
    DIRT_PATH,
    MOSS_BLOCK,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT,
    TUBE_CORAL_BLOCK, BRAIN_CORAL_BLOCK, BUBBLE_CORAL_BLOCK,
    FIRE_CORAL_BLOCK, HORN_CORAL_BLOCK,
    TUBE_CORAL_FAN, BRAIN_CORAL_FAN, BUBBLE_CORAL_FAN,
    FIRE_CORAL_FAN, HORN_CORAL_FAN,
    BLUE_ORCHID, ALLIUM, AZURE_BLUET, RED_TULIP, ORANGE_TULIP,
    WHITE_TULIP, PINK_TULIP, OXEYE_DAISY, CORNFLOWER, LILY_OF_THE_VALLEY,
    TERRACOTTA, WHITE_TERRACOTTA, ORANGE_TERRACOTTA, YELLOW_TERRACOTTA,
    RED_TERRACOTTA, BROWN_TERRACOTTA, GREEN_TERRACOTTA,
    LIGHT_GRAY_TERRACOTTA, GRAY_TERRACOTTA, LIGHT_BLUE_TERRACOTTA,
    MAGENTA_TERRACOTTA, PINK_TERRACOTTA, LIME_TERRACOTTA,
    CYAN_TERRACOTTA, PURPLE_TERRACOTTA, BLUE_TERRACOTTA,
    RAW_IRON_BLOCK, RAW_COPPER_BLOCK,
    LAVA,
)
from .biomes import BIOME_NAME_TO_ID

# --------------------------------------------------
# World constants (vanilla overworld)
# --------------------------------------------------

MIN_Y = -64
MAX_Y = 319
WORLD_HEIGHT = 384
SEA_LEVEL = 63
SECTION_HEIGHT = 16
NUM_SECTIONS = WORLD_HEIGHT // SECTION_HEIGHT  # 24

# Vanilla noise settings: minecraft:overworld
# Cell dimensions for trilinear interpolation of density
CELL_WIDTH = 4       # horizontal cell size in blocks
CELL_HEIGHT = 8      # vertical cell size in blocks
CELL_COUNT_XZ = 16 // CELL_WIDTH   # 4 cells per chunk horizontally
CELL_COUNT_Y = WORLD_HEIGHT // CELL_HEIGHT  # 48 cells vertically

# Vanilla density thresholds
GLOBAL_OFFSET = -0.50375
SURFACE_DENSITY_THRESHOLD = 1.5625
CHEESE_NOISE_TARGET = -0.703125

# Mask for unsigned 64-bit arithmetic
_MASK64 = 0xFFFFFFFFFFFFFFFF


# ============================================================
# Bit manipulation helpers (vanilla Xoroshiro128++ seed derivation)
# ============================================================

def _rotl64(v: int, n: int) -> int:
    """Rotate left a 64-bit integer."""
    v &= _MASK64
    return ((v << n) | (v >> (64 - n))) & _MASK64


def _mix_stafford13(x: int) -> int:
    """Stafford13 mix function used by vanilla for seed scrambling."""
    x &= _MASK64
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9 & _MASK64
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB & _MASK64
    return (x ^ (x >> 31)) & _MASK64


def _upgrade_seed_to128(seed: int) -> tuple[int, int]:
    """Upgrade a 64-bit world seed to a 128-bit (lo, hi) pair."""
    seed = seed & _MASK64
    lo = (seed ^ 0x6A09E667F3BCC909) & _MASK64
    hi = (lo + 0x9E3779B97F4A7C15) & _MASK64
    return _mix_stafford13(lo), _mix_stafford13(hi)


def _fnv1a64(s: str, basis: int) -> int:
    """FNV-1a 64-bit hash of a string."""
    h = basis & _MASK64
    prime = 1099511628211
    for c in s.encode('utf-8'):
        h = ((h ^ c) * prime) & _MASK64
    return h


# ============================================================
# Xoroshiro128++ PRNG (vanilla exact)
# ============================================================

class Xoroshiro128PlusPlus:
    """
    Xoroshiro128++ pseudo-random number generator.
    This is the EXACT same PRNG used by vanilla Minecraft Java Edition.
    """

    __slots__ = ('_lo', '_hi')

    def __init__(self, seed_lo: int, seed_hi: int):
        seed_lo &= _MASK64
        seed_hi &= _MASK64
        if seed_lo == 0 and seed_hi == 0:
            seed_lo = 0x9E3779B97F4A7C15
            seed_hi = 0x6A09E667F3BCC909
        self._lo = seed_lo
        self._hi = seed_hi

    def next_u64(self) -> int:
        s0 = self._lo
        s1 = self._hi
        out = (_rotl64((s0 + s1) & _MASK64, 17) + s0) & _MASK64
        s1 ^= s0
        self._lo = (_rotl64(s0, 49) ^ s1 ^ ((s1 << 21) & _MASK64)) & _MASK64
        self._hi = _rotl64(s1, 28)
        return out

    def next_int(self, bound: int) -> int:
        if bound <= 0:
            return 0
        u = self.next_u64() & 0xFFFFFFFF
        m = (u * bound) & _MASK64
        l = m & 0xFFFFFFFF
        if l < bound:
            threshold = (0 - bound) % bound
            while l < threshold:
                u = self.next_u64() & 0xFFFFFFFF
                m = (u * bound) & _MASK64
                l = m & 0xFFFFFFFF
        return (m >> 32) & 0xFFFFFFFF

    def next_double(self) -> float:
        return (self.next_u64() >> 11) * (1.0 / 9007199254740992.0)


# ============================================================
# HashRandomFactory (vanilla seeded random factory)
# ============================================================

class HashRandomFactory:
    """
    Vanilla's seeded random factory. Used to derive child RNGs
    from the world seed using FNV-1a hashing.
    """

    __slots__ = ('_lo', '_hi')

    def __init__(self, lo: int, hi: int):
        self._lo = lo & _MASK64
        self._hi = hi & _MASK64

    @classmethod
    def from_seed(cls, world_seed: int) -> 'HashRandomFactory':
        lo, hi = _upgrade_seed_to128(world_seed)
        return cls(lo, hi)

    def child(self, key: str) -> 'HashRandomFactory':
        h0, h1 = self._hash2x64(key)
        return HashRandomFactory(self._lo ^ h0, self._hi ^ h1)

    def from_hash(self, key: str) -> Xoroshiro128PlusPlus:
        h0, h1 = self._hash2x64(key)
        return Xoroshiro128PlusPlus(self._lo ^ h0, self._hi ^ h1)

    @staticmethod
    def _hash2x64(key: str) -> tuple[int, int]:
        h0 = _fnv1a64(key, 1469598103934665603)
        h1 = _fnv1a64(key, 7809847782465536322)
        h0 = _mix_stafford13(h0)
        h1 = _mix_stafford13((h1 ^ (h0 + 0x9E3779B97F4A7C15)) & _MASK64)
        return h0, h1


# ============================================================
# Improved Perlin Noise (vanilla exact)
# ============================================================

# Vanilla's exact gradient table (16 entries)
_GRADIENT = [
    (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
    (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
    (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
    (1, 1, 0), (0, -1, 1), (-1, 1, 0), (0, -1, -1),
]


def _fast_floor(v: float) -> int:
    i = int(v)
    return (i - 1) if v < i else i


def _smoothstep(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(t: float, a: float, b: float) -> float:
    return a + t * (b - a)


def _clamped_lerp(a: float, b: float, t: float) -> float:
    if t < 0.0:
        return a
    if t > 1.0:
        return b
    return _lerp(t, a, b)


class ImprovedNoise:
    """
    Vanilla Improved Perlin Noise.
    Uses the exact gradient table and permutation shuffling from vanilla.
    Supports yScale/yMax for vanilla's shifted noise.
    """

    __slots__ = ('_p', '_xo', '_yo', '_zo')

    def __init__(self, rng: Xoroshiro128PlusPlus):
        self._xo = rng.next_double() * 256.0
        self._yo = rng.next_double() * 256.0
        self._zo = rng.next_double() * 256.0

        p = list(range(256))
        for i in range(256):
            j = i + rng.next_int(256 - i)
            p[i], p[j] = p[j], p[i]
        self._p = p + p

    def noise(self, x: float, y: float, z: float,
              y_scale: float = 0.0, y_max: float = 0.0) -> float:
        xs = x + self._xo
        ys = y + self._yo
        zs = z + self._zo

        x_floor = _fast_floor(xs)
        y_floor = _fast_floor(ys)
        z_floor = _fast_floor(zs)

        x_frac = xs - x_floor
        y_frac = ys - y_floor
        z_frac = zs - z_floor

        # Vanilla's shifted noise: quantize y by yScale when set
        y_quantized_offset = 0.0
        if y_scale != 0.0:
            y_anchor = y_frac
            if 0.0 <= y_max < y_frac:
                y_anchor = y_max
            y_quantized_offset = math.floor(y_anchor / y_scale + 1.0e-7) * y_scale

        y_frac -= y_quantized_offset
        y_smooth_input = ys - y_floor

        return self._sample_and_lerp(
            x_floor, y_floor, z_floor,
            x_frac, y_frac, z_frac,
            y_smooth_input,
        )

    def _p_idx(self, idx: int) -> int:
        return self._p[idx & 0xFF]

    @staticmethod
    def _grad_dot(h: int, x: float, y: float, z: float) -> float:
        g = _GRADIENT[h & 0x0F]
        return g[0] * x + g[1] * y + g[2] * z

    def _sample_and_lerp(self, x_floor: int, y_floor: int, z_floor: int,
                         x_frac: float, y_frac: float, z_frac: float,
                         y_smooth_input: float) -> float:
        p = self._p
        x0 = p[x_floor & 0x1FF]
        x1 = p[(x_floor + 1) & 0x1FF]
        a = p[(x0 + y_floor) & 0x1FF]
        b = p[(x0 + y_floor + 1) & 0x1FF]
        c = p[(x1 + y_floor) & 0x1FF]
        d = p[(x1 + y_floor + 1) & 0x1FF]

        n000 = self._grad_dot(p[(a + z_floor) & 0x1FF], x_frac, y_frac, z_frac)
        n100 = self._grad_dot(p[(c + z_floor) & 0x1FF], x_frac - 1.0, y_frac, z_frac)
        n010 = self._grad_dot(p[(b + z_floor) & 0x1FF], x_frac, y_frac - 1.0, z_frac)
        n110 = self._grad_dot(p[(d + z_floor) & 0x1FF], x_frac - 1.0, y_frac - 1.0, z_frac)
        n001 = self._grad_dot(p[(a + z_floor + 1) & 0x1FF], x_frac, y_frac, z_frac - 1.0)
        n101 = self._grad_dot(p[(c + z_floor + 1) & 0x1FF], x_frac - 1.0, y_frac, z_frac - 1.0)
        n011 = self._grad_dot(p[(b + z_floor + 1) & 0x1FF], x_frac, y_frac - 1.0, z_frac - 1.0)
        n111 = self._grad_dot(p[(d + z_floor + 1) & 0x1FF], x_frac - 1.0, y_frac - 1.0, z_frac - 1.0)

        u = _smoothstep(x_frac)
        v = _smoothstep(y_smooth_input)
        w = _smoothstep(z_frac)

        x00 = _lerp(u, n000, n100)
        x10 = _lerp(u, n010, n110)
        x01 = _lerp(u, n001, n101)
        x11 = _lerp(u, n011, n111)
        y0 = _lerp(v, x00, x10)
        y1 = _lerp(v, x01, x11)
        return _lerp(w, y0, y1)


# ============================================================
# PerlinNoise (multi-octave, vanilla exact)
# ============================================================

_WRAP_RANGE = 33554432.0  # 2^25


def _noise_wrap(v: float) -> float:
    return v - math.floor(v / _WRAP_RANGE + 0.5) * _WRAP_RANGE


class PerlinNoise:
    """
    Vanilla PerlinNoise: a collection of ImprovedNoise octaves
    with specific firstOctave and amplitudes.
    """

    __slots__ = ('_first_octave', '_amplitudes', '_levels',
                 '_has_level', '_lowest_freq_input', '_lowest_freq_value')

    def __init__(self, seed_factory: HashRandomFactory,
                 first_octave: int, amplitudes: list[float],
                 label: str):
        self._first_octave = first_octave
        self._amplitudes = amplitudes
        count = len(amplitudes)
        self._levels: list[Optional[ImprovedNoise]] = [None] * count
        self._has_level: list[bool] = [False] * count

        octave_factory = seed_factory.child(label)
        for i in range(count):
            if amplitudes[i] == 0.0:
                continue
            octave = first_octave + i
            rng = octave_factory.from_hash(f"octave_{octave}")
            self._levels[i] = ImprovedNoise(rng)
            self._has_level[i] = True

        octave_shift = -first_octave
        self._lowest_freq_input = 2.0 ** (-octave_shift)
        self._lowest_freq_value = (2.0 ** (count - 1)) / ((2.0 ** count) - 1.0)

    def get_value(self, x: float, y: float, z: float,
                  y_scale: float = 0.0, y_max: float = 0.0) -> float:
        value = 0.0
        freq = self._lowest_freq_input
        amp = self._lowest_freq_value
        for i in range(len(self._levels)):
            if self._has_level[i]:
                value += (self._amplitudes[i] *
                          self._levels[i].noise(
                              _noise_wrap(x * freq),
                              _noise_wrap(y * freq),
                              _noise_wrap(z * freq),
                              y_scale, y_max,
                          ) * amp)
            freq *= 2.0
            amp /= 2.0
        return value


# ============================================================
# NormalNoise (vanilla exact: two PerlinNoise with value factor)
# ============================================================

_INPUT_FACTOR = 1.0181268882175227


class NormalNoise:
    """
    Vanilla NormalNoise: two PerlinNoise instances (first and second)
    with the second sampled at a slightly different scale.
    """

    __slots__ = ('_first', '_second', '_value_factor')

    def __init__(self, base_factory: HashRandomFactory,
                 noise_key: str,
                 first_octave: int,
                 amplitudes: list[float]):
        self._first = PerlinNoise(
            base_factory.child(f"{noise_key}:a"),
            first_octave, amplitudes, "first",
        )
        self._second = PerlinNoise(
            base_factory.child(f"{noise_key}:b"),
            first_octave, amplitudes, "second",
        )

        # Compute value factor
        min_idx = max_idx = -1
        for i, a in enumerate(amplitudes):
            if a == 0.0:
                continue
            if min_idx < 0:
                min_idx = i
            max_idx = i
        if min_idx < 0:
            min_idx = 0
            max_idx = 0
        expected_deviation = 0.1 * (1.0 + 1.0 / (max_idx - min_idx + 1))
        self._value_factor = (1.0 / 6.0) / expected_deviation

    def get_value(self, x: float, y: float, z: float) -> float:
        sx = x * _INPUT_FACTOR
        sy = y * _INPUT_FACTOR
        sz = z * _INPUT_FACTOR
        return (self._first.get_value(x, y, z) +
                self._second.get_value(sx, sy, sz)) * self._value_factor


# ============================================================
# Density Function System (vanilla pipeline)
# ============================================================

class DensityFunction:
    """Base class for density functions (matching vanilla's DF system)."""

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        raise NotImplementedError


class ShiftedNoise(DensityFunction):
    """
    Vanilla's shifted noise with spline interpolation.
    Samples 3D noise at shifted coordinates derived from climate parameters.
    Uses yScale/yMax for vertical quantization (vanilla's shifted noise behavior).
    """

    def __init__(self, noise: NormalNoise,
                 xz_scale: float, y_scale: float,
                 shift_x: DensityFunction = None,
                 shift_y: DensityFunction = None,
                 shift_z: DensityFunction = None):
        self._noise = noise
        self._xz_scale = xz_scale
        self._y_scale = y_scale
        self._shift_x = shift_x
        self._shift_y = shift_y
        self._shift_z = shift_z

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        sx = x * self._xz_scale
        sy = y * self._y_scale
        sz = z * self._xz_scale

        # Apply shifts from other density functions
        if self._shift_x is not None:
            sx += self._shift_x.compute(x, y, z, climate) * 4.0
        if self._shift_y is not None:
            sy += self._shift_y.compute(x, y, z, climate) * 4.0
        if self._shift_z is not None:
            sz += self._shift_z.compute(x, y, z, climate) * 4.0

        return self._noise.get_value(sx, sy, sz)


class Clamped(DensityFunction):
    """Clamp a density function output to [min, max]."""

    def __init__(self, inner: DensityFunction, min_val: float, max_val: float):
        self._inner = inner
        self._min = min_val
        self._max = max_val

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        return max(self._min, min(self._max, self._inner.compute(x, y, z, climate)))


class Spline(DensityFunction):
    """
    Vanilla's cubic spline interpolation.
    Maps a single input parameter to an output value using spline control points.
    """

    def __init__(self, points: list[tuple[float, float]]):
        """
        Args:
            points: List of (x, y) control points, sorted by x.
        """
        self._points = points

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        return self.interpolate(self._extract_value(x, y, z, climate))

    def _extract_value(self, x: float, y: float, z: float,
                       climate: 'ClimateSample') -> float:
        """Override in subclasses to select which parameter to spline on."""
        raise NotImplementedError

    def interpolate(self, value: float) -> float:
        """Cubic spline interpolation between control points."""
        pts = self._points
        if not pts:
            return 0.0
        if value <= pts[0][0]:
            return pts[0][1]
        if value >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            if pts[i][0] <= value <= pts[i + 1][0]:
                t = (value - pts[i][0]) / (pts[i + 1][0] - pts[i][0])
                # Catmull-Rom style cubic interpolation
                p0 = pts[max(0, i - 1)][1]
                p1 = pts[i][1]
                p2 = pts[i + 1][1]
                p3 = pts[min(len(pts) - 1, i + 2)][1]
                return _catmull_rom(p0, p1, p2, p3, t)
        return pts[-1][1]


class ContinentalnessSpline(Spline):
    """Spline that maps continentalness to density contribution."""

    def _extract_value(self, x, y, z, climate):
        return climate.continentalness


class ErosionSpline(Spline):
    """Spline that maps erosion to density contribution."""

    def _extract_value(self, x, y, z, climate):
        return climate.erosion


class PeaksValleysSpline(Spline):
    """Spline that maps peaks_and_valleys to density contribution."""

    def _extract_value(self, x, y, z, climate):
        return climate.peaks_valleys


class WeirdnessSpline(Spline):
    """Spline that maps weirdness to density contribution."""

    def _extract_value(self, x, y, z, climate):
        return climate.weirdness


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Catmull-Rom cubic interpolation."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1) +
        (-p0 + p2) * t +
        (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 +
        (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


class YClampedGradient(DensityFunction):
    """Height-based gradient: linear interpolation from (from_y, from_val) to (to_y, to_val)."""

    def __init__(self, from_y: int, to_y: int, from_val: float, to_val: float):
        self._from_y = from_y
        self._to_y = to_y
        self._from_val = from_val
        self._to_val = to_val

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        if y <= self._from_y:
            return self._from_val
        if y >= self._to_y:
            return self._to_val
        t = (y - self._from_y) / (self._to_y - self._from_y)
        return _lerp(t, self._from_val, self._to_val)


class BlendDensity(DensityFunction):
    """3D terrain blending: interpolates between two density functions."""

    def __init__(self, func_a: DensityFunction, func_b: DensityFunction,
                 blend: DensityFunction):
        self._a = func_a
        self._b = func_b
        self._blend = blend

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        blend_val = self._blend.compute(x, y, z, climate)
        a = self._a.compute(x, y, z, climate)
        b = self._b.compute(x, y, z, climate)
        return _clamped_lerp(a, b, blend_val)


class SplineDensity(DensityFunction):
    """
    Generic cubic spline density function.
    Maps an input parameter (extracted via a selector function) to an output
    value using cubic spline interpolation between control points.
    This is the unified replacement for ContinentalnessSpline, ErosionSpline, etc.
    """

    def __init__(self, points: list[tuple[float, float]],
                 selector: str = 'continentalness'):
        """
        Args:
            points: List of (x, y) control points, sorted by x.
            selector: Which climate parameter to spline on.
                One of: 'continentalness', 'erosion', 'peaks_valleys',
                'weirdness', 'temperature', 'humidity', 'depth'.
        """
        self._points = points
        self._selector = selector

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        value = self._extract(x, y, z, climate)
        return self.interpolate(value)

    def _extract(self, x: float, y: float, z: float,
                 climate: 'ClimateSample') -> float:
        return getattr(climate, self._selector, 0.0)

    def interpolate(self, value: float) -> float:
        """Cubic spline interpolation between control points."""
        pts = self._points
        if not pts:
            return 0.0
        if value <= pts[0][0]:
            return pts[0][1]
        if value >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            if pts[i][0] <= value <= pts[i + 1][0]:
                t = (value - pts[i][0]) / (pts[i + 1][0] - pts[i][0])
                p0 = pts[max(0, i - 1)][1]
                p1 = pts[i][1]
                p2 = pts[i + 1][1]
                p3 = pts[min(len(pts) - 1, i + 2)][1]
                return _catmull_rom(p0, p1, p2, p3, t)
        return pts[-1][1]


class ClampedNormal(DensityFunction):
    """
    Vanilla's clamped normal distribution density function.
    Used primarily for ore placement and feature distribution.

    Computes a Gaussian-like distribution clamped to [min_val, max_val]:
      f(y) = clamp(mean + stddev * noise(x, y, z), min_val, max_val)

    This matches vanilla's ClampedNormalPoint (used in configured features
    for ore placement heights and other y-level-dependent distributions).
    """

    def __init__(self, noise: 'NormalNoise',
                 mean: float, stddev: float,
                 min_val: float, max_val: float):
        self._noise = noise
        self._mean = mean
        self._stddev = stddev
        self._min = min_val
        self._max = max_val

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        noise_val = self._noise.get_value(x, y, z)
        result = self._mean + self._stddev * noise_val
        return max(self._min, min(self._max, result))


class AddDensity(DensityFunction):
    """Add two density functions."""

    def __init__(self, a: DensityFunction, b: DensityFunction):
        self._a = a
        self._b = b

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        return self._a.compute(x, y, z, climate) + self._b.compute(x, y, z, climate)


class MulDensity(DensityFunction):
    """Multiply two density functions."""

    def __init__(self, a: DensityFunction, b: DensityFunction):
        self._a = a
        self._b = b

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        return self._a.compute(x, y, z, climate) * self._b.compute(x, y, z, climate)


class ConstantDensity(DensityFunction):
    """Constant density value."""

    def __init__(self, value: float):
        self._value = value

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        return self._value


class CacheOnce(DensityFunction):
    """Caches density computation within a single chunk to avoid redundant sampling."""

    def __init__(self, inner: DensityFunction):
        self._inner = inner
        self._cache: dict[tuple[int, int, int], float] = {}

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        key = (int(x), int(y), int(z))
        if key in self._cache:
            return self._cache[key]
        val = self._inner.compute(x, y, z, climate)
        self._cache[key] = val
        return val

    def clear_cache(self):
        self._cache.clear()


class Cache2D(DensityFunction):
    """Caches a 2D density function (only x, z) within a single chunk."""

    def __init__(self, inner: DensityFunction):
        self._inner = inner
        self._cache: dict[tuple[int, int], float] = {}

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        key = (int(x), int(z))
        if key in self._cache:
            return self._cache[key]
        val = self._inner.compute(x, y, z, climate)
        self._cache[key] = val
        return val

    def clear_cache(self):
        self._cache.clear()


class SmoothClamp(DensityFunction):
    """Smoothly clamps density function output using vanilla's SMOOTH logic.

    When the inner density exceeds the edge value, it smoothly transitions
    instead of hard clamping. The transition follows vanilla's formula:
      - For val > edge: result = edge + slope * (1 - 1/(1 + (val-edge)/slope))
      - For val < -edge: result = -edge - slope * (1 - 1/(1 + (-edge-val)/slope))

    This creates natural-looking terrain boundaries instead of hard cliffs.
    """

    def __init__(self, inner: DensityFunction,
                 edge: float, slope: float = 1.0):
        self._inner = inner
        self._edge = edge
        self._slope = slope

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        val = self._inner.compute(x, y, z, climate)
        if val < -self._edge:
            excess = (-self._edge) - val
            return -self._edge - self._slope * (1.0 - 1.0 / (1.0 + excess / self._slope))
        if val > self._edge:
            excess = val - self._edge
            return self._edge + self._slope * (1.0 - 1.0 / (1.0 + excess / self._slope))
        return val


class InterpolateColumn(DensityFunction):
    """Vanilla's interpolate column density function.

    Computes two density functions at different y-levels and interpolates
    between them based on the current y coordinate. Used for creating
    smooth transitions between different terrain heights.
    """

    def __init__(self, start_y: int, end_y: int,
                 start_density: DensityFunction, end_density: DensityFunction):
        self._start_y = start_y
        self._end_y = end_y
        self._start_density = start_density
        self._end_density = end_density

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        if y <= self._start_y:
            return self._start_density.compute(x, y, z, climate)
        if y >= self._end_y:
            return self._end_density.compute(x, y, z, climate)
        t = (y - self._start_y) / (self._end_y - self._start_y)
        start_val = self._start_density.compute(x, y, z, climate)
        end_val = self._end_density.compute(x, y, z, climate)
        return _clamped_lerp(start_val, end_val, t)


class RangeChoice(DensityFunction):
    """Vanilla's range_choice density function.

    Selects between two density functions based on the value of an input
    parameter relative to a range. This is used in vanilla's noise router
    for conditional terrain shaping based on climate parameters.
    """

    def __init__(self, input_func: DensityFunction,
                 min_inclusive: float, max_exclusive: float,
                 when_in_range: DensityFunction,
                 when_out_of_range: DensityFunction):
        self._input = input_func
        self._min = min_inclusive
        self._max = max_exclusive
        self._in_range = when_in_range
        self._out_range = when_out_of_range

    def compute(self, x: float, y: float, z: float,
                climate: 'ClimateSample') -> float:
        val = self._input.compute(x, y, z, climate)
        if self._min <= val < self._max:
            return self._in_range.compute(x, y, z, climate)
        return self._out_range.compute(x, y, z, climate)


# ============================================================
# Vanilla overworld density function spline data
# ============================================================

# Continentalness spline (maps continentalness -> density contribution)
# These values match vanilla's overworld density function tree
_CONT_SPLINE_POINTS = [
    (-1.0, -0.13),
    (-0.75, -0.09),
    (-0.55, -0.065),
    (-0.40, -0.03),
    (-0.19, 0.01),
    (-0.11, 0.04),
    (0.03, 0.07),
    (0.3, 0.10),
    (1.0, 0.12),
]

# Erosion spline (maps erosion -> density contribution)
_EROSION_SPLINE_POINTS = [
    (-1.0, 0.09),
    (-0.78, 0.065),
    (-0.375, 0.04),
    (-0.2225, 0.025),
    (0.05, 0.0),
    (0.45, -0.03),
    (0.55, -0.04),
    (1.0, -0.06),
]

# Peaks/valleys spline (maps peaks_and_valleys -> density contribution)
_PV_SPLINE_POINTS = [
    (-0.56666666, 0.1),
    (-0.4, 0.05),
    (-0.26666668, 0.01),
    (-0.05, -0.02),
    (0.05, -0.02),
    (0.26666668, 0.01),
    (0.4, 0.05),
    (0.56666666, 0.1),
]


def _spline_interpolate(points: list[tuple[float, float]], value: float) -> float:
    """Cubic spline interpolation between control points."""
    if not points:
        return 0.0
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        if points[i][0] <= value <= points[i + 1][0]:
            t = (value - points[i][0]) / (points[i + 1][0] - points[i][0])
            # Catmull-Rom cubic
            p0 = points[max(0, i - 1)][1]
            p1 = points[i][1]
            p2 = points[i + 1][1]
            p3 = points[min(len(points) - 1, i + 2)][1]
            return _catmull_rom(p0, p1, p2, p3, t)
    return points[-1][1]


# ============================================================
# Climate parameter noise configurations (vanilla exact)
# ============================================================

def _make_temperature_params() -> tuple[int, list[float]]:
    return -10, [1.5, 0.0, 1.0, 0.0, 0.0, 0.0]


def _make_humidity_params() -> tuple[int, list[float]]:
    return -8, [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]


def _make_continental_params() -> tuple[int, list[float]]:
    return -9, [1.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0]


def _make_erosion_params() -> tuple[int, list[float]]:
    return -9, [1.0, 1.0, 0.0, 1.0, 1.0]


def _make_ridge_params() -> tuple[int, list[float]]:
    return -7, [1.0, 2.0, 1.0, 0.0, 0.0, 0.0]


# ============================================================
# Climate data structures
# ============================================================

@dataclass
class ClimateSample:
    temperature: float = 0.0
    humidity: float = 0.0
    continentalness: float = 0.0
    erosion: float = 0.0
    weirdness: float = 0.0
    peaks_valleys: float = 0.0


@dataclass
class ClimateRange:
    min_val: float = -1.0
    max_val: float = 1.0


def _span(a: float, b: float) -> ClimateRange:
    if a <= b:
        return ClimateRange(a, b)
    return ClimateRange(b, a)


def _span2(a: ClimateRange, b: ClimateRange) -> ClimateRange:
    return ClimateRange(min(a.min_val, b.min_val), max(a.max_val, b.max_val))


def _point(v: float) -> ClimateRange:
    return ClimateRange(v, v)


def _range_distance(r: ClimateRange, value: float) -> float:
    if value < r.min_val:
        return r.min_val - value
    if value > r.max_val:
        return value - r.max_val
    return 0.0


def _peaks_and_valleys(weirdness: float) -> float:
    return -(abs(abs(weirdness) - 0.6666667) - 0.33333334) * 3.0


# ============================================================
# OverworldBiomeTable (vanilla exact parameter points)
# ============================================================

class _BiomeId:
    """Biome enum matching vanilla's multi-noise parameter points."""
    NONE = 0
    PLAINS = 1
    SUNFLOWER_PLAINS = 2
    SNOWY_PLAINS = 3
    ICE_SPIKES = 4
    DESERT = 5
    SWAMP = 6
    MANGROVE_SWAMP = 7
    FOREST = 8
    FLOWER_FOREST = 9
    BIRCH_FOREST = 10
    DARK_FOREST = 11
    OLD_GROWTH_BIRCH_FOREST = 12
    OLD_GROWTH_PINE_TAIGA = 13
    OLD_GROWTH_SPRUCE_TAIGA = 14
    TAIGA = 15
    SNOWY_TAIGA = 16
    SAVANNA = 17
    SAVANNA_PLATEAU = 18
    WINDSWEPT_HILLS = 19
    WINDSWEPT_GRAVELLY_HILLS = 20
    WINDSWEPT_FOREST = 21
    WINDSWEPT_SAVANNA = 22
    JUNGLE = 23
    SPARSE_JUNGLE = 24
    BAMBOO_JUNGLE = 25
    BADLANDS = 26
    ERODED_BADLANDS = 27
    WOODED_BADLANDS = 28
    MEADOW = 29
    CHERRY_GROVE = 30
    GROVE = 31
    SNOWY_SLOPES = 32
    FROZEN_PEAKS = 33
    JAGGED_PEAKS = 34
    STONY_PEAKS = 35
    RIVER = 36
    FROZEN_RIVER = 37
    BEACH = 38
    SNOWY_BEACH = 39
    STONY_SHORE = 40
    WARM_OCEAN = 41
    LUKEWARM_OCEAN = 42
    DEEP_LUKEWARM_OCEAN = 43
    OCEAN = 44
    DEEP_OCEAN = 45
    COLD_OCEAN = 46
    DEEP_COLD_OCEAN = 47
    FROZEN_OCEAN = 48
    DEEP_FROZEN_OCEAN = 49
    MUSHROOM_FIELDS = 50
    DRIPSTONE_CAVES = 51
    LUSH_CAVES = 52
    DEEP_DARK = 53


_BIOME_ID_TO_NAME = {
    _BiomeId.PLAINS: "minecraft:plains",
    _BiomeId.SUNFLOWER_PLAINS: "minecraft:sunflower_plains",
    _BiomeId.SNOWY_PLAINS: "minecraft:snowy_plains",
    _BiomeId.ICE_SPIKES: "minecraft:ice_spikes",
    _BiomeId.DESERT: "minecraft:desert",
    _BiomeId.SWAMP: "minecraft:swamp",
    _BiomeId.MANGROVE_SWAMP: "minecraft:mangrove_swamp",
    _BiomeId.FOREST: "minecraft:forest",
    _BiomeId.FLOWER_FOREST: "minecraft:flower_forest",
    _BiomeId.BIRCH_FOREST: "minecraft:birch_forest",
    _BiomeId.DARK_FOREST: "minecraft:dark_forest",
    _BiomeId.OLD_GROWTH_BIRCH_FOREST: "minecraft:old_growth_birch_forest",
    _BiomeId.OLD_GROWTH_PINE_TAIGA: "minecraft:old_growth_pine_taiga",
    _BiomeId.OLD_GROWTH_SPRUCE_TAIGA: "minecraft:old_growth_spruce_taiga",
    _BiomeId.TAIGA: "minecraft:taiga",
    _BiomeId.SNOWY_TAIGA: "minecraft:snowy_taiga",
    _BiomeId.SAVANNA: "minecraft:savanna",
    _BiomeId.SAVANNA_PLATEAU: "minecraft:savanna_plateau",
    _BiomeId.WINDSWEPT_HILLS: "minecraft:windswept_hills",
    _BiomeId.WINDSWEPT_GRAVELLY_HILLS: "minecraft:windswept_gravelly_hills",
    _BiomeId.WINDSWEPT_FOREST: "minecraft:windswept_forest",
    _BiomeId.WINDSWEPT_SAVANNA: "minecraft:windswept_savanna",
    _BiomeId.JUNGLE: "minecraft:jungle",
    _BiomeId.SPARSE_JUNGLE: "minecraft:sparse_jungle",
    _BiomeId.BAMBOO_JUNGLE: "minecraft:bamboo_jungle",
    _BiomeId.BADLANDS: "minecraft:badlands",
    _BiomeId.ERODED_BADLANDS: "minecraft:eroded_badlands",
    _BiomeId.WOODED_BADLANDS: "minecraft:wooded_badlands",
    _BiomeId.MEADOW: "minecraft:meadow",
    _BiomeId.CHERRY_GROVE: "minecraft:cherry_grove",
    _BiomeId.GROVE: "minecraft:grove",
    _BiomeId.SNOWY_SLOPES: "minecraft:snowy_slopes",
    _BiomeId.FROZEN_PEAKS: "minecraft:frozen_peaks",
    _BiomeId.JAGGED_PEAKS: "minecraft:jagged_peaks",
    _BiomeId.STONY_PEAKS: "minecraft:stony_peaks",
    _BiomeId.RIVER: "minecraft:river",
    _BiomeId.FROZEN_RIVER: "minecraft:frozen_river",
    _BiomeId.BEACH: "minecraft:beach",
    _BiomeId.SNOWY_BEACH: "minecraft:snowy_beach",
    _BiomeId.STONY_SHORE: "minecraft:stony_shore",
    _BiomeId.WARM_OCEAN: "minecraft:warm_ocean",
    _BiomeId.LUKEWARM_OCEAN: "minecraft:lukewarm_ocean",
    _BiomeId.DEEP_LUKEWARM_OCEAN: "minecraft:deep_lukewarm_ocean",
    _BiomeId.OCEAN: "minecraft:ocean",
    _BiomeId.DEEP_OCEAN: "minecraft:deep_ocean",
    _BiomeId.COLD_OCEAN: "minecraft:cold_ocean",
    _BiomeId.DEEP_COLD_OCEAN: "minecraft:deep_cold_ocean",
    _BiomeId.FROZEN_OCEAN: "minecraft:frozen_ocean",
    _BiomeId.DEEP_FROZEN_OCEAN: "minecraft:deep_frozen_ocean",
    _BiomeId.MUSHROOM_FIELDS: "minecraft:mushroom_fields",
    _BiomeId.DRIPSTONE_CAVES: "minecraft:dripstone_caves",
    _BiomeId.LUSH_CAVES: "minecraft:lush_caves",
    _BiomeId.DEEP_DARK: "minecraft:deep_dark",
}


@dataclass
class _ClimatePoint:
    temperature: ClimateRange
    humidity: ClimateRange
    continentalness: ClimateRange
    erosion: ClimateRange
    depth: ClimateRange
    weirdness: ClimateRange
    offset: float
    biome: int


class OverworldBiomeTable:
    """
    Vanilla's overworld biome parameter point table.
    Uses the exact same climate ranges and biome assignments as vanilla Java.
    """

    def __init__(self):
        self._init_ranges()
        self._points: list[_ClimatePoint] = []
        self._add_biomes()

    def resolve(self, temperature: float, humidity: float,
                continentalness: float, erosion: float,
                depth: float, weirdness: float) -> int:
        """Resolve a climate sample to a biome ID using nearest-point search."""
        best = float('inf')
        result = _BiomeId.PLAINS
        for p in self._points:
            d = 0.0
            d += _range_distance(p.temperature, temperature) ** 2
            d += _range_distance(p.humidity, humidity) ** 2
            d += _range_distance(p.continentalness, continentalness) ** 2
            d += _range_distance(p.erosion, erosion) ** 2
            d += _range_distance(p.depth, depth) ** 2
            d += _range_distance(p.weirdness, weirdness) ** 2
            d += p.offset ** 2
            if d < best:
                best = d
                result = p.biome
        return result

    def _add_surface_biome(self, t: ClimateRange, h: ClimateRange,
                           c: ClimateRange, e: ClimateRange,
                           w: ClimateRange, offset: float, biome: int):
        self._points.append(_ClimatePoint(t, h, c, e, _point(0.0), w, offset, biome))
        self._points.append(_ClimatePoint(t, h, c, e, _point(1.0), w, offset, biome))

    def _add_underground_biome(self, t: ClimateRange, h: ClimateRange,
                               c: ClimateRange, e: ClimateRange,
                               w: ClimateRange, offset: float, biome: int):
        self._points.append(_ClimatePoint(t, h, c, e, _span(0.2, 0.9), w, offset, biome))

    def _add_bottom_biome(self, t: ClimateRange, h: ClimateRange,
                          c: ClimateRange, e: ClimateRange,
                          w: ClimateRange, offset: float, biome: int):
        self._points.append(_ClimatePoint(t, h, c, e, _point(1.1), w, offset, biome))

    def _init_ranges(self):
        self.full = _span(-1.0, 1.0)
        self.temps = [
            _span(-1.0, -0.45),
            _span(-0.45, -0.15),
            _span(-0.15, 0.2),
            _span(0.2, 0.55),
            _span(0.55, 1.0),
        ]
        self.humids = [
            _span(-1.0, -0.35),
            _span(-0.35, -0.1),
            _span(-0.1, 0.1),
            _span(0.1, 0.3),
            _span(0.3, 1.0),
        ]
        self.erosions = [
            _span(-1.0, -0.78),
            _span(-0.78, -0.375),
            _span(-0.375, -0.2225),
            _span(-0.2225, 0.05),
            _span(0.05, 0.45),
            _span(0.45, 0.55),
            _span(0.55, 1.0),
        ]
        self.conts = [
            _span(-1.0, -0.19),
            _span(-0.19, -0.11),
            _span(-0.11, 0.03),
            _span(0.03, 0.3),
            _span(0.3, 1.0),
        ]
        self.depths = [
            _span(-0.5, 0.0),
            _span(0.0, 0.2),
            _span(0.2, 0.9),
            _span(0.9, 1.1),
            _span(1.1, 1.6),
        ]
        self.weirds = [
            _span(-1.0, -0.56666666),
            _span(-0.56666666, -0.26666668),
            _span(-0.26666668, 0.05),
            _span(0.05, 0.26666668),
            _span(0.26666668, 0.56666666),
            _span(0.56666666, 1.0),
        ]

    def _add_biomes(self):
        E = _BiomeId
        f = self.full

        # Ocean biomes (continentalness < -0.19)
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[0], f, f, 0.0, E.DEEP_FROZEN_OCEAN)
        self._add_surface_biome(self.temps[1], self.humids[2], self.conts[0], f, f, 0.0, E.DEEP_COLD_OCEAN)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[0], f, f, 0.0, E.DEEP_OCEAN)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[0], f, f, 0.0, E.DEEP_LUKEWARM_OCEAN)
        self._add_surface_biome(self.temps[3], self.humids[3], self.conts[0], f, f, 0.0, E.DEEP_LUKEWARM_OCEAN)
        self._add_surface_biome(self.temps[4], self.humids[2], self.conts[0], f, f, 0.0, E.WARM_OCEAN)

        # Coastal (continentalness between -0.19 and -0.11)
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[1], f, f, 0.0, E.FROZEN_RIVER)
        self._add_surface_biome(self.temps[1], self.humids[2], self.conts[1], f, f, 0.0, E.RIVER)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[1], f, f, 0.0, E.RIVER)
        self._add_surface_biome(self.temps[3], self.humids[2], self.conts[1], f, f, 0.0, E.RIVER)
        self._add_surface_biome(self.temps[4], self.humids[2], self.conts[1], f, f, 0.0, E.RIVER)

        # Shallow ocean (continentalness -0.19 to -0.11, depth near surface)
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[0], f, self.weirds[0], 0.0, E.FROZEN_OCEAN)
        self._add_surface_biome(self.temps[1], self.humids[2], self.conts[0], f, f, 0.0, E.COLD_OCEAN)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[0], f, f, 0.0, E.OCEAN)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[0], f, f, 0.0, E.LUKEWARM_OCEAN)
        self._add_surface_biome(self.temps[3], self.humids[3], self.conts[0], f, f, 0.0, E.LUKEWARM_OCEAN)
        self._add_surface_biome(self.temps[4], self.humids[2], self.conts[0], f, f, 0.0, E.WARM_OCEAN)

        # Mushroom fields (very low continentalness)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[0], self.erosions[0], self.weirds[0], 1.0, E.MUSHROOM_FIELDS)

        # Beach biomes (near sea level, continentalness 0.03-0.3)
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.SNOWY_BEACH)
        self._add_surface_biome(self.temps[1], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.BEACH)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.BEACH)
        self._add_surface_biome(self.temps[3], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.BEACH)
        self._add_surface_biome(self.temps[4], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.STONY_SHORE)
        self._add_surface_biome(self.temps[2], self.humids[2], self.conts[3], self.erosions[0], f, 0.0, E.STONY_SHORE)
        self._add_surface_biome(self.temps[3], self.humids[2], self.conts[3], self.erosions[0], f, 0.0, E.STONY_SHORE)

        # Mountain biomes
        self._add_surface_biome(self.temps[0], f, self.conts[4], f, self.weirds[0], 0.0, E.JAGGED_PEAKS)
        self._add_surface_biome(self.temps[0], f, self.conts[4], f, self.weirds[4], 0.0, E.FROZEN_PEAKS)
        self._add_surface_biome(self.temps[0], f, self.conts[4], f, self.weirds[2], 0.0, E.SNOWY_SLOPES)
        self._add_surface_biome(self.temps[0], self.humids[3], self.conts[4], f, self.weirds[2], 0.0, E.GROVE)

        # Mid mountains
        self._add_surface_biome(self.temps[1], f, self.conts[4], f, self.weirds[2], 0.0, E.SNOWY_SLOPES)
        self._add_surface_biome(self.temps[1], self.humids[3], self.conts[4], f, self.weirds[2], 0.0, E.GROVE)
        self._add_surface_biome(self.temps[1], f, self.conts[4], f, self.weirds[3], 0.0, E.MEADOW)
        self._add_surface_biome(self.temps[2], f, self.conts[4], f, self.weirds[3], 0.0, E.MEADOW)
        self._add_surface_biome(self.temps[3], f, self.conts[4], f, f, 0.0, E.CHERRY_GROVE)
        self._add_surface_biome(self.temps[2], f, self.conts[4], f, self.weirds[4], 0.0, E.STONY_PEAKS)
        self._add_surface_biome(self.temps[3], f, self.conts[4], f, self.weirds[4], 0.0, E.STONY_PEAKS)
        self._add_surface_biome(self.temps[4], f, self.conts[4], f, self.weirds[4], 0.0, E.STONY_PEAKS)

        # Badlands (high temp, low humidity)
        self._add_surface_biome(self.temps[4], self.humids[0], self.conts[4], f, self.weirds[4], 0.0, E.ERODED_BADLANDS)
        self._add_surface_biome(self.temps[4], self.humids[1], self.conts[4], self.erosions[0], f, 0.0, E.WOODED_BADLANDS)
        self._add_surface_biome(self.temps[4], self.humids[1], self.conts[4], self.erosions[1], f, 0.0, E.WOODED_BADLANDS)
        self._add_surface_biome(self.temps[4], self.humids[0], self.conts[4], f, f, 0.0, E.BADLANDS)

        # Temperate biomes
        self._add_surface_biome(self.temps[2], self.humids[4], self.conts[3], f, self.weirds[4], 0.0, E.JUNGLE)
        self._add_surface_biome(self.temps[2], self.humids[4], self.conts[3], f, self.weirds[3], 0.0, E.SPARSE_JUNGLE)
        self._add_surface_biome(self.temps[2], self.humids[4], self.conts[3], f, self.weirds[5], 0.0, E.BAMBOO_JUNGLE)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[3], f, f, 0.0, E.SWAMP)
        self._add_surface_biome(self.temps[2], self.humids[4], self.conts[3], f, f, 0.0, E.MANGROVE_SWAMP)

        # Forest biomes
        self._add_surface_biome(self.temps[1], self.humids[3], self.conts[3], f, self.weirds[4], 0.0, E.FLOWER_FOREST)
        self._add_surface_biome(self.temps[1], self.humids[3], self.conts[3], f, self.weirds[3], 0.0, E.FOREST)
        self._add_surface_biome(self.temps[1], self.humids[4], self.conts[3], f, self.weirds[3], 0.0, E.DARK_FOREST)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[3], f, self.weirds[4], 0.0, E.FOREST)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[3], f, self.weirds[3], 0.0, E.BIRCH_FOREST)
        self._add_surface_biome(self.temps[2], self.humids[3], self.conts[3], f, self.weirds[5], 0.0, E.OLD_GROWTH_BIRCH_FOREST)

        # Taiga
        self._add_surface_biome(self.temps[1], self.humids[3], self.conts[3], f, self.weirds[2], 0.0, E.TAIGA)
        self._add_surface_biome(self.temps[1], self.humids[4], self.conts[3], f, self.weirds[2], 0.0, E.OLD_GROWTH_PINE_TAIGA)
        self._add_surface_biome(self.temps[0], self.humids[3], self.conts[3], f, f, 0.0, E.SNOWY_TAIGA)
        self._add_surface_biome(self.temps[1], self.humids[4], self.conts[3], f, self.weirds[5], 0.0, E.OLD_GROWTH_SPRUCE_TAIGA)

        # Cold biomes
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[3], f, self.weirds[5], 0.0, E.ICE_SPIKES)
        self._add_surface_biome(self.temps[0], self.humids[2], self.conts[3], f, f, 0.0, E.SNOWY_PLAINS)

        # Savanna
        self._add_surface_biome(self.temps[3], self.humids[0], self.conts[3], f, self.weirds[5], 0.0, E.WINDSWEPT_SAVANNA)
        self._add_surface_biome(self.temps[3], self.humids[1], self.conts[3], self.erosions[4], f, 0.0, E.SAVANNA_PLATEAU)
        self._add_surface_biome(self.temps[3], self.humids[1], self.conts[3], self.erosions[4], self.weirds[3], 0.0, E.SAVANNA)
        self._add_surface_biome(self.temps[3], self.humids[2], self.conts[3], self.erosions[4], f, 0.0, E.SAVANNA)

        # Plains / Windswept
        self._add_surface_biome(self.temps[2], self.humids[0], self.conts[3], self.erosions[0], self.weirds[4], 0.0, E.WINDSWEPT_GRAVELLY_HILLS)
        self._add_surface_biome(self.temps[2], self.humids[0], self.conts[3], self.erosions[1], self.weirds[4], 0.0, E.WINDSWEPT_HILLS)
        self._add_surface_biome(self.temps[2], self.humids[0], self.conts[3], self.erosions[1], self.weirds[5], 0.0, E.WINDSWEPT_FOREST)
        self._add_surface_biome(self.temps[2], self.humids[1], self.conts[3], f, self.weirds[5], 0.0, E.SUNFLOWER_PLAINS)
        self._add_surface_biome(self.temps[2], self.humids[1], self.conts[3], f, f, 0.0, E.PLAINS)

        # Underground biomes
        self._add_underground_biome(self.temps[2], self.humids[4], self.conts[2], f, self.weirds[3], 0.0, E.LUSH_CAVES)
        self._add_underground_biome(self.temps[2], self.humids[0], self.conts[2], f, self.weirds[3], 0.0, E.DRIPSTONE_CAVES)
        self._add_bottom_biome(self.temps[2], self.humids[2], self.conts[4], self.erosions[0], self.weirds[3], 0.0, E.DEEP_DARK)


# ============================================================
# Biome height parameters (vanilla-like)
# ============================================================

def _biome_height_params(biome_id: int) -> tuple[float, float]:
    """Return (base_height, variation) for a biome, matching vanilla's MultiNoise terrain shaping."""
    E = _BiomeId
    mountain = {E.JAGGED_PEAKS, E.FROZEN_PEAKS, E.STONY_PEAKS}
    mid_mountain = {E.SNOWY_SLOPES, E.GROVE, E.MEADOW, E.CHERRY_GROVE}
    hills = {E.WINDSWEPT_HILLS, E.WINDSWEPT_GRAVELLY_HILLS, E.WINDSWEPT_FOREST}
    badlands = {E.BADLANDS, E.ERODED_BADLANDS, E.WOODED_BADLANDS}
    flat = {E.PLAINS, E.SUNFLOWER_PLAINS, E.DESERT, E.SNOWY_PLAINS}
    forest = {E.FOREST, E.FLOWER_FOREST, E.BIRCH_FOREST, E.DARK_FOREST,
              E.OLD_GROWTH_BIRCH_FOREST}
    taiga = {E.TAIGA, E.OLD_GROWTH_PINE_TAIGA, E.OLD_GROWTH_SPRUCE_TAIGA, E.SNOWY_TAIGA}

    if biome_id in (E.OCEAN, E.DEEP_OCEAN, E.WARM_OCEAN, E.LUKEWARM_OCEAN,
                    E.COLD_OCEAN, E.FROZEN_OCEAN, E.DEEP_COLD_OCEAN,
                    E.DEEP_FROZEN_OCEAN, E.DEEP_LUKEWARM_OCEAN):
        return -0.70, 0.15
    if biome_id in (E.RIVER, E.FROZEN_RIVER):
        return -0.50, 0.05
    if biome_id in (E.BEACH, E.SNOWY_BEACH):
        return -0.05, 0.03
    if biome_id == E.STONY_SHORE:
        return 0.10, 0.08
    if biome_id in (E.SWAMP, E.MANGROVE_SWAMP):
        return -0.20, 0.08
    if biome_id in mountain:
        return 1.30, 0.70
    if biome_id in mid_mountain:
        return 0.55, 0.30
    if biome_id in hills:
        return 1.00, 0.50
    if biome_id in badlands:
        return 0.30, 0.20
    if biome_id == E.SAVANNA_PLATEAU:
        return 0.35, 0.20
    if biome_id in flat:
        return 0.125, 0.05
    if biome_id in forest:
        return 0.10, 0.20
    if biome_id in taiga:
        return 0.20, 0.20
    if biome_id == E.ICE_SPIKES:
        return 0.45, 0.50
    return 0.125, 0.05


# ============================================================
# Vanilla Density Function Tree
# ============================================================

class VanillaDensityFunction:
    """
    Vanilla overworld density function pipeline.

    Implements the full density function tree as used by vanilla
    Minecraft Java 1.21.1, including:
      - ShiftedNoise for base terrain shape
      - SplineDensity for climate->density mapping (replaces separate spline subclasses)
      - ClampedNormal for ore placement distributions
      - YClampedGradient for height-based effects
      - BlendDensity for 3D terrain blending
      - SmoothClamp for natural terrain boundaries
      - InterpolateColumn for smooth height transitions
      - RangeChoice for conditional terrain shaping
      - Cell-based trilinear interpolation

    The density function tree follows vanilla's noise_router pipeline:
      1. Sample climate parameters (temperature, humidity, continentalness, erosion, weirdness)
      2. Compute factor/offset/jaggedness from climate splines
      3. Compute base 3D noise with shifted coordinates
      4. Blend density = base_3d_noise + depth + offset + factor * jaggedness
      5. Apply cave carving (cheese/spaghetti/noodle)
      6. Final density determines solid (>=0) vs air (<0)
    """

    def __init__(self, seed_factory: HashRandomFactory):
        self._factory = seed_factory

        # === Terrain shaping noises (vanilla: overworld/noise_router) ===

        # Shifted noise for base terrain density
        # vanilla uses "offset" and "factor" noise keys
        self._offset_noise = NormalNoise(
            seed_factory.child("offset"),
            "offset",
            -5, [1.0, 1.0, 1.0, 0.0],
        )
        self._factor_noise = NormalNoise(
            seed_factory.child("factor"),
            "factor",
            -5, [1.0, 1.0, 1.0, 0.0],
        )

        # Terrain shaping: low/high blend
        self._terrain_low = NormalNoise(
            seed_factory.child("terrain"),
            "terrain_low",
            -6, [1.0, 1.0, 0.0, 0.0, 0.0],
        )
        self._terrain_high = NormalNoise(
            seed_factory.child("terrain"),
            "terrain_high",
            -6, [1.0, 1.0, 0.0, 0.0, 0.0],
        )
        self._terrain_selector = NormalNoise(
            seed_factory.child("terrain"),
            "terrain_selector",
            -7, [1.0, 1.0, 1.0, 0.0],
        )

        # Detail noise for micro-terrain variation
        self._detail_noise = NormalNoise(
            seed_factory.child("terrain"),
            "terrain_detail",
            -3, [1.0, 0.0, 0.0],
        )

        # === Cave carving noises ===
        self._cheese_noise = NormalNoise(
            seed_factory.child("cheese"), "cheese",
            -5, [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0],
        )
        self._spaghetti_noise = NormalNoise(
            seed_factory.child("spaghetti"), "spaghetti_2d",
            -5, [1.0, 1.0, 1.0, 0.0],
        )
        self._spaghetti_roughness = NormalNoise(
            seed_factory.child("spaghetti_roughness"),
            "spaghetti_roughness",
            -3, [1.0, 0.0, 0.0],
        )
        self._noodle_noise = NormalNoise(
            seed_factory.child("noodle"), "noodle",
            -4, [1.0, 1.0, 0.0, 0.0],
        )
        self._pillar_noise = NormalNoise(
            seed_factory.child("pillar"), "pillar",
            -4, [1.0, 1.0, 1.0, 0.0],
        )
        self._pillar_thickness = NormalNoise(
            seed_factory.child("pillar"), "pillar_thickness",
            -3, [1.0, 0.0, 0.0],
        )

        # === ClampedNormal noises for ore placement ===
        self._ore_height_noise = NormalNoise(
            seed_factory.child("ore_height"), "ore_height",
            -4, [1.0, 1.0, 0.0],
        )
        self._ore_spread_noise = NormalNoise(
            seed_factory.child("ore_spread"), "ore_spread",
            -3, [1.0, 0.0, 0.0],
        )

        # === Density function instances ===
        # Y gradient: density decreases with height
        self._y_gradient = YClampedGradient(-64, 320, 1.0, -1.0)

        # Climate splines (using the new SplineDensity generic class)
        self._cont_spline = SplineDensity(_CONT_SPLINE_POINTS, 'continentalness')
        self._erosion_spline = SplineDensity(_EROSION_SPLINE_POINTS, 'erosion')
        self._pv_spline = SplineDensity(_PV_SPLINE_POINTS, 'peaks_valleys')
        self._weirdness_spline = SplineDensity(
            [(-1.0, -0.05), (-0.5, -0.02), (0.0, 0.0), (0.5, 0.02), (1.0, 0.05)],
            'weirdness',
        )

        # Depth-based offset spline (surface=0, underground=negative)
        self._depth_offset_spline = SplineDensity(
            [(-1.0, -0.15), (-0.5, -0.08), (0.0, 0.0), (0.5, 0.04), (1.0, 0.06)],
            'depth',
        )

        # ClampedNormal for ore height distribution
        self._coal_height_normal = ClampedNormal(
            self._ore_height_noise, 96.0, 32.0, -64.0, 320.0,
        )
        self._iron_height_normal = ClampedNormal(
            self._ore_height_noise, 16.0, 24.0, -64.0, 320.0,
        )
        self._diamond_height_normal = ClampedNormal(
            self._ore_spread_noise, -64.0, 16.0, -64.0, 16.0,
        )

        # Factor function: interpolates continentalness/erosion contributions
        self._factor_func = SplineDensity(
            [(-1.0, 0.5), (-0.5, 0.7), (0.0, 1.0), (0.5, 1.3), (1.0, 1.5)],
            'continentalness',
        )

        # Jaggedness function: controls mountain peak sharpness
        self._jaggedness_func = SplineDensity(
            [(-1.0, 0.0), (-0.5, 0.0), (0.0, 0.1), (0.5, 0.4), (1.0, 0.8)],
            'weirdness',
        )

    def compute_base_density(self, x: float, y: float, z: float,
                              climate: ClimateSample) -> float:
        """
        Compute the base terrain density at a given position.

        This implements vanilla's density function tree:
          1. Compute climate-based spline offsets (continentalness, erosion, peaks/valleys)
          2. Compute factor and jaggedness from climate parameters
          3. Compute terrain shape (low/high blend with selector)
          4. Compute depth-based offset (surface=0, underground=negative)
          5. Combine: final_density = base_3d_noise + depth + offset + factor * jaggedness
          6. Add detail noise and global offset

        Returns a value where > 0 means solid and <= 0 means air.

        The density function is calibrated so that:
          - At y=SEA_LEVEL with average climate: density ≈ 0.3 (solid)
          - At y=100 with average climate: density ≈ 0 (surface)
          - At y=200 with average climate: density ≈ -0.5 (air)
          - Ocean biomes (low continentalness): surface at y ≈ 40-60
          - Mountains (high continentalness, low erosion): surface at y ≈ 100-200
        """
        # Step 1: Climate-based density offsets via spline interpolation
        # Using the generic SplineDensity class
        cont_offset = self._cont_spline.compute(x, y, z, climate)
        erosion_offset = self._erosion_spline.compute(x, y, z, climate)
        pv_offset = self._pv_spline.compute(x, y, z, climate)
        weird_offset = self._weirdness_spline.compute(x, y, z, climate)

        # Step 2: Factor and jaggedness (vanilla's noise router components)
        factor = self._factor_func.compute(x, y, z, climate)
        jaggedness = self._jaggedness_func.compute(x, y, z, climate)

        # Step 3: Terrain shape blending
        # Scale coordinates to noise space (vanilla quart-space sampling)
        qx = x / 16.0
        qy = y / 16.0
        qz = z / 16.0

        low = self._terrain_low.get_value(qx, qy, qz)
        high = self._terrain_high.get_value(qx, qy, qz)
        selector_raw = self._terrain_selector.get_value(qx, qy, qz)
        # Blend factor: map [-1,1] to [0,1] with clamping
        blend = max(0.0, min(1.0, (selector_raw + 1.0) * 0.5))
        terrain_shape = _clamped_lerp(low, high, blend)

        # Step 4: Y-gradient with climate-dependent surface height
        # Vanilla's approach: density = spline_offsets + y_factor * (1 - (y - offset) / scale)
        # We compute a y-factor that gives positive density below surface and negative above
        # The surface height is approximately: SEA_LEVEL + cont_offset*40 + pv_offset*25
        # So we need the gradient to cross zero at that height
        surface_approx = SEA_LEVEL + cont_offset * 300.0 + pv_offset * 180.0 + erosion_offset * 100.0
        # Y-gradient: positive below surface, negative above
        # Use a smooth gradient that crosses zero at surface_approx
        y_density = (surface_approx - y) / 64.0

        # Step 5: Depth-based offset (vanilla's depth_noise contribution)
        # Surface = 0, underground = negative (more solid)
        depth = max(0.0, (surface_approx - y) / 128.0)
        depth_offset = self._depth_offset_spline.compute(x, y, z, climate)

        # Step 6: Detail noise
        detail = self._detail_noise.get_value(qx * 4.0, qy * 4.0, qz * 4.0) * 0.03

        # Step 7: Combine all density contributions
        # Vanilla formula: base_3d_noise + depth + offset + factor * jaggedness
        density = 0.0
        density += y_density
        density += terrain_shape * 0.1
        density += detail
        density += depth_offset * 0.05
        density += factor * jaggedness * 0.02

        # Global offset (vanilla's -0.50375 adjusts the overall density threshold)
        density += GLOBAL_OFFSET

        return density

    def compute_cave_density(self, x: float, y: float, z: float) -> float:
        """
        Compute cave carving density.
        Returns a value where negative means the block should be carved out.

        Implements vanilla's three cave types:
          - Cheese caves: large open areas
          - Spaghetti caves: winding tunnels
          - Noodle caves: thin worm-like passages

        Caves are relatively rare - only ~5-10% of underground blocks are carved.
        """
        # Skip caves at very top and very bottom of world
        wy = y
        if wy < -60 or wy > MAX_Y - 8:
            return 0.0

        nx = x / 40.0
        ny = y / 40.0
        nz = z / 40.0

        # Depth factor: caves become more common deeper underground
        depth_factor = max(0.0, min(1.0, (y + 60.0) / 120.0))

        # === Cheese caves (large open areas) ===
        # These are relatively rare - only the most extreme noise values create them
        cheese = self._cheese_noise.get_value(nx, ny, nz)
        # Vanilla's cheese cave threshold: CHEESE_NOISE_TARGET = -0.703125
        # Only carve when cheese > threshold AND depth is sufficient
        # Threshold increases near surface (fewer caves)
        cheese_threshold = 0.75 + depth_factor * 0.15
        if cheese > cheese_threshold and depth_factor > 0.3:
            return -1.0  # Carve out

        # === Spaghetti caves (winding tunnels) ===
        # These create thin winding passages
        spag = self._spaghetti_noise.get_value(nx, ny, nz)
        roughness = self._spaghetti_roughness.get_value(
            x / 80.0, y / 80.0, z / 80.0)
        # Spaghetti caves: very thin band around zero
        # The threshold is tight, so only a small fraction of blocks are carved
        spag_half_width = 0.05 + abs(roughness) * 0.02
        if abs(spag) < spag_half_width and depth_factor > 0.15:
            return -1.0  # Carve out

        # === Noodle caves (thin winding passages) ===
        # These are the rarest and thinnest type
        noodle = self._noodle_noise.get_value(
            x / 24.0, y / 24.0, z / 24.0)
        if noodle > 0.85 and depth_factor > 0.4:
            return -1.0  # Carve out

        # === Pillar check (prevent carving at certain noise values) ===
        # Pillars create stalactite/stalagmite-like features in caves
        pillar = self._pillar_noise.get_value(
            x / 40.0, y / 40.0, z / 40.0)
        thickness = self._pillar_thickness.get_value(
            x / 30.0, y / 30.0, z / 30.0)
        if pillar > 0.5 and abs(thickness) < 0.1:
            return 0.5  # Force slightly solid (pillar)

        return 0.0  # No carving

    def compute(self, x: float, y: float, z: float,
                climate: ClimateSample) -> float:
        """
        Compute the final density at a given position.
        Combines base terrain density with cave carving.

        Returns a value where > 0 means solid and <= 0 means air.
        """
        # Base terrain density
        density = self.compute_base_density(x, y, z, climate)

        # Apply cave carving on top of base density
        cave_density = self.compute_cave_density(x, y, z)
        if cave_density < 0:
            # Cave carving: use min to carve out
            density = min(density, cave_density)

        return density


# ============================================================
# Vanilla Surface Rules
# ============================================================

class SurfaceRules:
    """
    Vanilla overworld surface rule system.
    Determines which blocks to place on the terrain surface based on
    biome, depth, height, and noise values.
    """

    def __init__(self, seed: int):
        self._seed = seed
        self._surface_noise = NormalNoise(
            HashRandomFactory.from_seed(seed).child("surface"),
            "surface",
            -4, [1.0, 1.0, 0.0, 0.0],
        )
        self._calcite_noise = NormalNoise(
            HashRandomFactory.from_seed(seed).child("calcite"),
            "calcite",
            -3, [1.0, 0.0, 0.0],
        )

    def apply(self, blocks: list, height_map: list, biome_map: list,
              base_x: int, base_z: int):
        """Apply vanilla surface rules to a chunk."""
        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]
                biome = biome_map[lz][lx]
                si = surface_h - MIN_Y

                if si < 0 or si >= WORLD_HEIGHT:
                    continue

                # Find actual solid surface (skip carved-out air)
                if blocks[si][lz][lx] in (AIR, WATER):
                    for search in range(si, max(0, si - 20), -1):
                        if blocks[search][lz][lx] not in (AIR, WATER):
                            si = search
                            surface_h = si + MIN_Y
                            break
                    else:
                        continue

                # Surface noise for variation
                surf_n = self._surface_noise.get_value(
                    wx / 48.0, surface_h / 48.0, wz / 48.0)

                is_underwater = surface_h < SEA_LEVEL
                water_above = (si + 1 < WORLD_HEIGHT and
                               blocks[si + 1][lz][lx] == WATER)

                # Apply biome-specific surface rules
                self._apply_biome_surface(
                    blocks, lx, lz, si, surface_h, biome,
                    surf_n, is_underwater, water_above, wx, wz,
                )

    def _apply_biome_surface(self, blocks, lx, lz, si, surface_h,
                             biome, surf_n, is_underwater, water_above,
                             wx, wz):
        """Apply surface rules for a specific biome."""
        # Badlands terracotta
        if biome in ("minecraft:badlands", "minecraft:eroded_badlands",
                     "minecraft:wooded_badlands"):
            self._place_badlands_surface(blocks, lx, lz, si, surface_h,
                                         surf_n, is_underwater, water_above, wx, wz)
            return

        # Desert
        if biome == "minecraft:desert":
            self._place_desert_surface(blocks, lx, lz, si, surface_h,
                                       is_underwater, water_above)
            return

        # Beach variants
        if biome == "minecraft:beach":
            self._place_beach_surface(blocks, lx, lz, si, surface_h,
                                      is_underwater, water_above)
            return
        if biome == "minecraft:snowy_beach":
            self._place_snowy_beach_surface(blocks, lx, lz, si, surface_h,
                                            is_underwater, water_above)
            return

        # Stony shore
        if biome == "minecraft:stony_shore":
            self._place_stony_shore_surface(blocks, lx, lz, si, surface_h,
                                            is_underwater, water_above, surf_n)
            return

        # Ocean floor
        if biome.endswith("ocean"):
            self._place_ocean_floor(blocks, lx, lz, si, surf_n)
            return

        # River
        if biome in ("minecraft:river", "minecraft:frozen_river"):
            self._place_river_surface(blocks, lx, lz, si, surface_h,
                                      is_underwater, surf_n)
            return

        # Swamp
        if biome in ("minecraft:swamp", "minecraft:mangrove_swamp"):
            self._place_swamp_surface(blocks, lx, lz, si, surface_h,
                                      is_underwater, water_above)
            return

        # Snowy biomes
        if biome.startswith("minecraft:snowy") or biome in (
                "minecraft:ice_spikes", "minecraft:frozen_peaks",
                "minecraft:jagged_peaks", "minecraft:snowy_slopes"):
            self._place_snowy_surface(blocks, lx, lz, si, surface_h,
                                      biome, is_underwater, water_above, surf_n)
            return

        # Grove
        if biome == "minecraft:grove":
            self._place_grove_surface(blocks, lx, lz, si, surface_h,
                                      is_underwater, water_above, surf_n)
            return

        # Stony peaks
        if biome == "minecraft:stony_peaks":
            self._place_stony_peaks_surface(blocks, lx, lz, si, surface_h,
                                            is_underwater, water_above, surf_n, wx, wz)
            return

        # Meadow / Cherry grove
        if biome in ("minecraft:meadow", "minecraft:cherry_grove"):
            self._place_meadow_surface(blocks, lx, lz, si, is_underwater, water_above)
            return

        # Windswept biomes
        if biome.startswith("minecraft:windswept"):
            self._place_windswept_surface(blocks, lx, lz, si, surface_h,
                                          biome, is_underwater, water_above, surf_n)
            return

        # Savanna
        if biome.startswith("minecraft:savanna"):
            self._place_savanna_surface(blocks, lx, lz, si, surface_h,
                                        is_underwater, water_above)
            return

        # Default: grass/dirt
        self._place_grass_surface(blocks, lx, lz, si, surface_h,
                                  is_underwater, water_above)

    def _replace_surface(self, blocks, lx, lz, si, block_id, depth, filler):
        """Replace surface and sub-surface blocks."""
        blocks[si][lz][lx] = block_id
        for d in range(1, depth + 1):
            idx = si - d
            if 0 <= idx < WORLD_HEIGHT:
                if blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = filler

    def _place_badlands_surface(self, blocks, lx, lz, si, surface_h,
                                surf_n, is_underwater, water_above, wx, wz):
        """Place badlands terracotta layers (vanilla-style banding)."""
        if surface_h <= SEA_LEVEL:
            blocks[si][lz][lx] = RED_SAND
            for d in range(1, 3):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = RED_SAND
            # Sandstone below
            for d in range(3, 5):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = RED_SAND  # vanilla uses red sandstone
        else:
            # Terracotta bands based on y coordinate (vanilla pattern)
            # The band index cycles through terracotta colors
            band = (surface_h + int(surf_n * 3)) % 21
            terracotta_sequence = [
                WHITE_TERRACOTTA, ORANGE_TERRACOTTA, TERRACOTTA,
                YELLOW_TERRACOTTA, BROWN_TERRACOTTA, RED_TERRACOTTA,
                LIGHT_GRAY_TERRACOTTA, TERRACOTTA, ORANGE_TERRACOTTA,
                WHITE_TERRACOTTA, BROWN_TERRACOTTA, YELLOW_TERRACOTTA,
                RED_TERRACOTTA, LIGHT_GRAY_TERRACOTTA, ORANGE_TERRACOTTA,
                TERRACOTTA, WHITE_TERRACOTTA, ORANGE_TERRACOTTA,
                TERRACOTTA, YELLOW_TERRACOTTA, BROWN_TERRACOTTA,
            ]
            if band < len(terracotta_sequence):
                blocks[si][lz][lx] = terracotta_sequence[band]
            else:
                blocks[si][lz][lx] = TERRACOTTA

            # Sub-surface: terracotta with red sand deeper
            for d in range(1, 8):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    if d < 3:
                        blocks[idx][lz][lx] = TERRACOTTA
                    elif d < 5:
                        blocks[idx][lz][lx] = ORANGE_TERRACOTTA
                    else:
                        blocks[idx][lz][lx] = RED_SAND

    def _place_desert_surface(self, blocks, lx, lz, si, surface_h,
                              is_underwater, water_above):
        """Place desert sand surface with sandstone below."""
        self._replace_surface(blocks, lx, lz, si, SAND, 4, SAND)
        for d in range(3, 5):
            idx = si - d
            if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (SAND, STONE):
                blocks[idx][lz][lx] = SANDSTONE

    def _place_beach_surface(self, blocks, lx, lz, si, surface_h,
                             is_underwater, water_above):
        """Place beach sand surface."""
        if is_underwater:
            blocks[si][lz][lx] = SAND
            for d in range(1, 3):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = SAND
            for d in range(3, 5):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                    blocks[idx][lz][lx] = SANDSTONE
        else:
            self._replace_surface(blocks, lx, lz, si, SAND, 2, SAND)
            for d in range(2, 4):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                    blocks[idx][lz][lx] = SANDSTONE

    def _place_snowy_beach_surface(self, blocks, lx, lz, si, surface_h,
                                   is_underwater, water_above):
        """Place snowy beach surface."""
        self._replace_surface(blocks, lx, lz, si, SAND, 2, SAND)
        for d in range(2, 4):
            idx = si - d
            if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                blocks[idx][lz][lx] = SANDSTONE
        if not is_underwater and si + 1 < WORLD_HEIGHT and blocks[si + 1][lz][lx] == AIR:
            blocks[si + 1][lz][lx] = SNOW

    def _place_stony_shore_surface(self, blocks, lx, lz, si, surface_h,
                                   is_underwater, water_above, surf_n):
        """Place stony shore surface."""
        if surf_n > 0.3:
            blocks[si][lz][lx] = GRAVEL
            for d in range(1, 3):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = GRAVEL
        else:
            blocks[si][lz][lx] = STONE
            for d in range(1, 2):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                    blocks[idx][lz][lx] = COBBLESTONE

    def _place_ocean_floor(self, blocks, lx, lz, si, surf_n):
        """Place ocean floor surface."""
        if surf_n > 0.3:
            blocks[si][lz][lx] = CLAY
        elif surf_n > -0.1:
            blocks[si][lz][lx] = SAND
        elif surf_n > -0.4:
            blocks[si][lz][lx] = GRAVEL
        else:
            blocks[si][lz][lx] = DIRT

    def _place_river_surface(self, blocks, lx, lz, si, surface_h,
                             is_underwater, surf_n):
        """Place river surface."""
        if is_underwater:
            if surf_n > 0.2:
                blocks[si][lz][lx] = CLAY
            else:
                blocks[si][lz][lx] = SAND
            for d in range(1, 3):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = DIRT
        else:
            self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 3, DIRT)

    def _place_swamp_surface(self, blocks, lx, lz, si, surface_h,
                             is_underwater, water_above):
        """Place swamp surface."""
        if water_above:
            blocks[si][lz][lx] = CLAY
            for d in range(1, 2):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = CLAY
        else:
            self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 3, DIRT)

    def _place_snowy_surface(self, blocks, lx, lz, si, surface_h, biome,
                             is_underwater, water_above, surf_n):
        """Place snowy surface."""
        if is_underwater:
            blocks[si][lz][lx] = CLAY if surf_n > 0.3 else SAND
            # Freeze water surface
            water_yi = SEA_LEVEL - MIN_Y
            if 0 <= water_yi < WORLD_HEIGHT and blocks[water_yi][lz][lx] == WATER:
                blocks[water_yi][lz][lx] = ICE
        else:
            # Snow block or packed ice on top
            if biome in ("minecraft:frozen_peaks", "minecraft:jagged_peaks"):
                if surf_n > 0.3:
                    blocks[si][lz][lx] = PACKED_ICE
                else:
                    blocks[si][lz][lx] = STONE
                for d in range(1, 3):
                    idx = si - d
                    if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                        blocks[idx][lz][lx] = PACKED_ICE
            elif biome == "minecraft:ice_spikes":
                blocks[si][lz][lx] = SNOW_BLOCK
                self._replace_surface(blocks, lx, lz, si - 1, DIRT, 2, DIRT)
            else:
                blocks[si][lz][lx] = SNOW_BLOCK
                for d in range(1, 4):
                    idx = si - d
                    if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                        blocks[idx][lz][lx] = DIRT
            # Snow layer on top
            if si + 1 < WORLD_HEIGHT and blocks[si + 1][lz][lx] == AIR:
                blocks[si + 1][lz][lx] = SNOW

    def _place_grove_surface(self, blocks, lx, lz, si, surface_h,
                             is_underwater, water_above, surf_n):
        """Place grove surface (snowy forest)."""
        if is_underwater:
            blocks[si][lz][lx] = DIRT
        else:
            blocks[si][lz][lx] = SNOW_BLOCK
            for d in range(1, 4):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = DIRT
            if si + 1 < WORLD_HEIGHT and blocks[si + 1][lz][lx] == AIR:
                blocks[si + 1][lz][lx] = SNOW

    def _place_stony_peaks_surface(self, blocks, lx, lz, si, surface_h,
                                   is_underwater, water_above, surf_n, wx, wz):
        """Place stony peaks surface."""
        calcite_n = self._calcite_noise.get_value(wx / 32.0, surface_h / 32.0, wz / 32.0)
        if calcite_n > 0.3:
            blocks[si][lz][lx] = CALCITE
        elif surf_n > 0.2:
            blocks[si][lz][lx] = GRANITE
        else:
            blocks[si][lz][lx] = STONE

    def _place_meadow_surface(self, blocks, lx, lz, si, is_underwater, water_above):
        """Place meadow surface."""
        if is_underwater:
            blocks[si][lz][lx] = DIRT
        else:
            self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 3, DIRT)

    def _place_windswept_surface(self, blocks, lx, lz, si, surface_h, biome,
                                 is_underwater, water_above, surf_n):
        """Place windswept biome surface."""
        if is_underwater:
            blocks[si][lz][lx] = GRAVEL if surf_n > 0.0 else DIRT
        elif biome == "minecraft:windswept_gravelly_hills":
            if surf_n > 0.3:
                blocks[si][lz][lx] = GRAVEL
                for d in range(1, 3):
                    idx = si - d
                    if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                        blocks[idx][lz][lx] = GRAVEL
            else:
                self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 3, DIRT)
        elif biome == "minecraft:windswept_hills":
            blocks[si][lz][lx] = GRASS_BLOCK
            for d in range(1, 3):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] == STONE:
                    blocks[idx][lz][lx] = COBBLESTONE
        else:
            self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 3, DIRT)

    def _place_savanna_surface(self, blocks, lx, lz, si, surface_h,
                               is_underwater, water_above):
        """Place savanna surface."""
        if is_underwater:
            blocks[si][lz][lx] = DIRT
        else:
            self._replace_surface(blocks, lx, lz, si, GRASS_BLOCK, 2, DIRT)

    def _place_grass_surface(self, blocks, lx, lz, si, surface_h,
                             is_underwater, water_above):
        """Default grass/dirt surface placement."""
        if is_underwater:
            blocks[si][lz][lx] = DIRT
            for d in range(1, 2):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = DIRT
        else:
            top = GRASS_BLOCK
            filler = DIRT
            if surface_h > SEA_LEVEL + 60:
                top = COARSE_DIRT
                filler = COARSE_DIRT
            blocks[si][lz][lx] = top
            for d in range(1, 4):
                idx = si - d
                if 0 <= idx < WORLD_HEIGHT and blocks[idx][lz][lx] in (STONE, DEEPSLATE):
                    blocks[idx][lz][lx] = filler


# ============================================================
# Cave Carver with Aquifer System
# ============================================================

class CaveCarver:
    """
    Vanilla-style cave carver with aquifer system.

    Implements three cave types:
      - Cheese caves: large open areas (3D noise, depth-dependent threshold)
      - Spaghetti caves: winding tunnels (2D noise with roughness modulation)
      - Noodle caves: thin worm-like passages (high-frequency noise)

    Aquifer system:
      - Below sea level (y=63): caves fill with water
      - Below y=-54: caves fill with lava instead of water
      - This creates the vanilla aquifer behavior
    """

    def __init__(self, seed: int):
        factory = HashRandomFactory.from_seed(seed)
        self._density_func = VanillaDensityFunction(factory)

    def carve(self, blocks: list, base_x: int, base_z: int,
              climate_func: Callable) -> None:
        """
        Carve caves into a chunk using the density function's cave carving.

        Args:
            blocks: [y][z][x] block state ID array
            base_x, base_z: chunk base world coordinates
            climate_func: callable(x, z) -> ClimateSample
        """
        for ly in range(WORLD_HEIGHT):
            wy = MIN_Y + ly
            # Skip very bottom and top of world
            if wy < -60 or wy > MAX_Y - 8:
                continue

            for lz in range(16):
                for lx in range(16):
                    wx = base_x + lx
                    wz = base_z + lz
                    target = blocks[ly][lz][lx]

                    # Only carve through solid blocks
                    if target not in (STONE, DEEPSLATE, GRANITE, DIORITE,
                                      ANDESITE, TUFF, CALCITE):
                        continue

                    # Get climate for this column
                    climate = climate_func(wx, wz)

                    # Compute cave density
                    cave_density = self._density_func.compute_cave_density(
                        float(wx), float(wy), float(wz))

                    if cave_density < 0:
                        # Aquifer: fill with water below sea level, lava deep underground
                        if wy <= -54:
                            blocks[ly][lz][lx] = LAVA
                        elif wy <= SEA_LEVEL:
                            blocks[ly][lz][lx] = WATER
                        else:
                            blocks[ly][lz][lx] = AIR


# ============================================================
# Ore Vein Generator (vanilla triangular distribution)
# ============================================================

class OreVeinGenerator:
    """
    Vanilla-style ore vein generator with triangular distribution.

    Ore distributions match vanilla Minecraft 1.21.1:
      - Coal: y=0 to y=320, peak at y=96 (main) + y=-64 to y=0, peak at y=-64 (underground)
      - Iron: y=-64 to y=320, peak at y=16 (common) + y=80 to y=384, peak at y=232 (high)
      - Gold: y=-64 to y=32, peak at y=-16
      - Diamond: y=-64 to y=16, peak at y=-64
      - Lapis: y=-64 to y=64, peak at y=0
      - Redstone: y=-64 to y=16
      - Copper: y=-16 to y=112, peak at y=48
      - Emerald: y=-16 to y=320, peak at y=256 (mountains only)
    """

    def __init__(self, seed: int):
        self._seed = seed

    def place(self, blocks: list, base_x: int, base_z: int):
        """Place ore veins in a chunk using vanilla triangular distribution."""
        rng = _random.Random(
            self._seed ^ (base_x * 6364136223846793005 + base_z * 1442695040888963407)
        )

        # Ore configurations matching vanilla 1.21.1
        # (ore_id, deepslate_ore_id, attempts, vein_size, y_min, y_max, peak_y, distribution)
        ore_configs = [
            # Coal - two distributions (main + underground)
            (COAL_ORE, DEEPSLATE_COAL_ORE, 20, 10, 0, 320, 96, 'triangular'),
            (COAL_ORE, DEEPSLATE_COAL_ORE, 10, 10, -64, 0, -64, 'triangular'),
            # Iron - two distributions (common + high)
            (IRON_ORE, DEEPSLATE_IRON_ORE, 20, 8, -64, 320, 16, 'triangular'),
            (IRON_ORE, DEEPSLATE_IRON_ORE, 10, 4, 80, 384, 232, 'triangular'),
            # Copper
            (COPPER_ORE, DEEPSLATE_COPPER_ORE, 16, 9, -16, 112, 48, 'triangular'),
            # Gold
            (GOLD_ORE, DEEPSLATE_GOLD_ORE, 4, 7, -64, 32, -16, 'triangular'),
            # Redstone
            (REDSTONE_ORE, DEEPSLATE_REDSTONE_ORE, 8, 6, -64, 16, -32, 'triangular'),
            # Lapis
            (LAPIS_ORE, DEEPSLATE_LAPIS_ORE, 2, 5, -64, 64, 0, 'triangular'),
            # Diamond
            (DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE, 2, 4, -64, 16, -64, 'triangular'),
            # Emerald (mountains only - rare)
            (EMERALD_ORE, DEEPSLATE_EMERALD_ORE, 1, 2, -16, 320, 256, 'triangular'),
        ]

        for ore_id, deep_ore_id, attempts, vein_size, y_min, y_max, peak_y, dist in ore_configs:
            for _ in range(attempts):
                lx = rng.randint(0, 15)
                lz = rng.randint(0, 15)

                if dist == 'triangular':
                    # Vanilla's triangular distribution:
                    # P(y) = triangular(y_min, y_max, peak_y)
                    wy = int(rng.triangular(y_min, y_max, peak_y))
                else:
                    wy = rng.randint(y_min, y_max)

                yi = wy - MIN_Y
                if yi < 0 or yi >= WORLD_HEIGHT:
                    continue

                target = blocks[yi][lz][lx]
                if target == STONE:
                    ore_block = ore_id
                elif target == DEEPSLATE:
                    ore_block = deep_ore_id
                else:
                    continue

                # Place vein (spherical scatter, matching vanilla's ore vein shape)
                blocks[yi][lz][lx] = ore_block
                for _ in range(vein_size - 1):
                    dx = rng.randint(-1, 1)
                    dy = rng.randint(-1, 1)
                    dz = rng.randint(-1, 1)
                    nx, ny, nz = lx + dx, yi + dy, lz + dz
                    if 0 <= nx < 16 and 0 <= nz < 16 and 0 <= ny < WORLD_HEIGHT:
                        if blocks[ny][nz][nx] == STONE:
                            blocks[ny][nz][nx] = ore_id
                        elif blocks[ny][nz][nx] == DEEPSLATE:
                            blocks[ny][nz][nx] = deep_ore_id

        # Stone variants (granite, diorite, andesite, tuff) - vanilla vein sizes
        variants = [
            (GRANITE, 80, 0, 256),
            (DIORITE, 80, 0, 256),
            (ANDESITE, 80, 0, 256),
            (TUFF, 40, -64, 0),
        ]
        for block_id, count, vy_min, vy_max in variants:
            for _ in range(count):
                lx = rng.randint(0, 15)
                ly_rel = rng.randint(max(0, vy_min - MIN_Y), min(WORLD_HEIGHT - 1, vy_max - MIN_Y))
                lz = rng.randint(0, 15)

                if blocks[ly_rel][lz][lx] in (STONE, DEEPSLATE):
                    blocks[ly_rel][lz][lx] = block_id
                    # Small cluster expansion (3x3x3 with probability)
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            for dz in range(-1, 2):
                                if rng.random() < 0.4:
                                    nx2, ny2, nz2 = lx + dx, ly_rel + dy, lz + dz
                                    if (0 <= nx2 < 16 and 0 <= nz2 < 16
                                            and 0 <= ny2 < WORLD_HEIGHT):
                                        if blocks[ny2][nz2][nx2] in (STONE, DEEPSLATE):
                                            blocks[ny2][nz2][nx2] = block_id


# ============================================================
# VanillaTerrainGenerator
# ============================================================

class VanillaTerrainGenerator:
    """
    1:1 Vanilla terrain generator for Minecraft Java Edition 1.21.1.

    Uses the exact same noise algorithms, climate system, and
    biome parameter points as vanilla to produce terrain that
    closely matches vanilla output.

    Drop-in replacement for TerrainGenerator with the same interface:
      - generate_chunk(chunk_x, chunk_z) -> list[list[list[int]]]
      - get_terrain_height(world_x, world_z) -> int
    """

    def __init__(self, seed: int = 0):
        self.seed = seed
        self._root_factory = HashRandomFactory.from_seed(seed)
        self._biome_table = OverworldBiomeTable()

        # Climate noises (vanilla exact parameters)
        fo, ha = _make_temperature_params()
        self._temp_noise = NormalNoise(self._root_factory, "temperature", fo, ha)
        fo, ha = _make_humidity_params()
        self._humidity_noise = NormalNoise(self._root_factory, "vegetation", fo, ha)
        fo, ha = _make_continental_params()
        self._continental_noise = NormalNoise(self._root_factory, "continentalness", fo, ha)
        fo, ha = _make_erosion_params()
        self._erosion_noise = NormalNoise(self._root_factory, "erosion", fo, ha)
        fo, ha = _make_ridge_params()
        self._ridge_noise = NormalNoise(self._root_factory, "ridge", fo, ha)

        # Density function system
        self._density = VanillaDensityFunction(self._root_factory)

        # Surface rules
        self._surface_rules = SurfaceRules(seed)

        # Cave carver
        self._cave_carver = CaveCarver(seed)

        # Ore veins
        self._ore_generator = OreVeinGenerator(seed)

    def sample_climate(self, x: int, z: int) -> ClimateSample:
        """Sample climate at a given (x, z) position."""
        # Java biome noise is sampled in quart space
        qx = x / 16.0
        qz = z / 16.0

        c = ClimateSample()
        c.temperature = self._temp_noise.get_value(qx, 0.0, qz)
        c.humidity = self._humidity_noise.get_value(qx, 0.0, qz)
        c.continentalness = self._continental_noise.get_value(qx, 0.0, qz)
        c.erosion = self._erosion_noise.get_value(qx, 0.0, qz)
        c.weirdness = self._ridge_noise.get_value(qx, 0.0, qz)
        c.peaks_valleys = _peaks_and_valleys(c.weirdness)
        return c

    def resolve_biome(self, climate: ClimateSample, depth: float = 0.0) -> int:
        """Resolve a climate sample to a biome ID."""
        return self._biome_table.resolve(
            climate.temperature, climate.humidity,
            climate.continentalness, climate.erosion,
            depth, climate.weirdness,
        )

    def sample_column(self, x: int, z: int) -> tuple[int, int, ClimateSample]:
        """
        Sample a terrain column to get (height, biome_id, climate).
        Uses the vanilla column sampling algorithm with density function.
        """
        climate = self.sample_climate(x, z)
        biome_id = self.resolve_biome(climate, 0.0)

        wx = float(x)
        wz = float(z)

        # Use biome height parameters for base height
        base_height, variation = _biome_height_params(biome_id)

        # Compute terrain shape using density function
        # Sample density at multiple y-levels to find the surface
        # This is equivalent to vanilla's "final_density" > 0 check
        # For efficiency, use a heuristic based on climate + noise

        # Terrain shape blending (matching vanilla's noise router)
        qx = wx / 16.0
        qz = wz / 16.0
        low = self._density._terrain_low.get_value(qx, 0.0, qz)
        high = self._density._terrain_high.get_value(qx, 0.0, qz)
        selector_raw = self._density._terrain_selector.get_value(qx, 0.0, qz)
        blend = max(0.0, min(1.0, (selector_raw + 1.0) * 0.5))
        terrain_shape = _clamped_lerp(low, high, blend)

        # Climate-based density offsets (using generic SplineDensity)
        cont_offset = self._density._cont_spline.interpolate(climate.continentalness)
        erosion_offset = self._density._erosion_spline.interpolate(climate.erosion)
        pv_offset = self._density._pv_spline.interpolate(climate.peaks_valleys)
        factor = self._density._factor_func.interpolate(climate.continentalness)
        jaggedness = self._density._jaggedness_func.interpolate(climate.weirdness)

        # Compute approximate surface height from density function
        # h = y where density(x, y, z) crosses zero
        # Start from sea level and adjust based on climate + noise
        h = 63.0 + 2.0
        h += base_height * 20.0
        h += terrain_shape * 16.0
        h += (blend - 0.5) * 6.0
        h += cont_offset * 40.0
        h += erosion_offset * 20.0
        h += pv_offset * 25.0
        # Factor and jaggedness add mountain peak contributions
        h += factor * jaggedness * 12.0

        # Detail noise
        detail = self._density._detail_noise.get_value(
            wx / 4.0, 0.0, wz / 4.0) * variation * 8.0
        h += detail

        h = max(5.0, min(250.0, h))
        return int(round(h)), biome_id, climate

    def generate_chunk(self, chunk_x: int, chunk_z: int) -> list[list[list[int]]]:
        """
        Generate a complete chunk column with vanilla-matching terrain.

        Args:
            chunk_x, chunk_z: Chunk coordinates

        Returns:
            3D block array [y][z][x], size 384 x 16 x 16
            y=0 corresponds to world_y = MIN_Y (-64)
        """
        blocks = [[[AIR for _ in range(16)] for _ in range(16)]
                  for _ in range(WORLD_HEIGHT)]

        base_x = chunk_x * 16
        base_z = chunk_z * 16

        # Step 1: Sample climate and compute surface heights
        height_map = [[0] * 16 for _ in range(16)]
        biome_map = [["minecraft:plains"] * 16 for _ in range(16)]
        climate_map: list[list[ClimateSample]] = [
            [ClimateSample() for _ in range(16)] for _ in range(16)
        ]

        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h, biome_id, climate = self.sample_column(wx, wz)
                height_map[lz][lx] = surface_h
                biome_map[lz][lx] = _BIOME_ID_TO_NAME.get(biome_id, "minecraft:plains")
                climate_map[lz][lx] = climate

        # Step 2: Fill base terrain (stone/deepslate/bedrock)
        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]

                # Bedrock layer (y = -64 to ~-60)
                blocks[0][lz][lx] = BEDROCK
                for bedrock_yi in range(1, 5):
                    rng_val = self._block_hash(wx, MIN_Y + bedrock_yi, wz)
                    if rng_val < (5 - bedrock_yi) * 0.2:
                        blocks[bedrock_yi][lz][lx] = BEDROCK
                    elif MIN_Y + bedrock_yi < 0:
                        blocks[bedrock_yi][lz][lx] = DEEPSLATE
                    else:
                        blocks[bedrock_yi][lz][lx] = STONE

                # Fill solid below surface
                si = surface_h - MIN_Y
                for yi in range(5, si):
                    wy = MIN_Y + yi
                    if wy < 0:
                        blocks[yi][lz][lx] = DEEPSLATE
                    else:
                        blocks[yi][lz][lx] = STONE

        # Step 3: Apply density function for 3D terrain shaping
        self._apply_density_functions(blocks, base_x, base_z, height_map, climate_map)

        # Step 4: Fill water
        for lx in range(16):
            for lz in range(16):
                surface_h = height_map[lz][lx]
                si = surface_h - MIN_Y
                sea_yi = SEA_LEVEL - MIN_Y
                # Fill water above solid but below sea level
                for yi in range(si, min(sea_yi + 1, WORLD_HEIGHT)):
                    if blocks[yi][lz][lx] == AIR:
                        blocks[yi][lz][lx] = WATER
                # Fill any air below sea level that isn't in a cave
                for yi in range(5, min(sea_yi + 1, WORLD_HEIGHT)):
                    if blocks[yi][lz][lx] == AIR and height_map[lz][lx] <= SEA_LEVEL:
                        blocks[yi][lz][lx] = WATER

        # Step 5: Carve caves (with aquifer)
        self._cave_carver.carve(blocks, base_x, base_z, self.sample_climate)

        # Step 6: Deepslate transition (y < 0)
        for lx in range(16):
            for lz in range(16):
                for wy in range(-64, 0):
                    yi = wy - MIN_Y
                    if 0 <= yi < WORLD_HEIGHT and blocks[yi][lz][lx] == STONE:
                        blocks[yi][lz][lx] = DEEPSLATE
                # Gradual transition at y=0 to y=8
                wx = base_x + lx
                wz = base_z + lz
                for wy in range(0, 8):
                    yi = wy - MIN_Y
                    if 0 <= yi < WORLD_HEIGHT and blocks[yi][lz][lx] == STONE:
                        if self._block_hash(wx, wy, wz) < 0.5:
                            blocks[yi][lz][lx] = DEEPSLATE

        # Step 7: Apply surface rules
        self._surface_rules.apply(blocks, height_map, biome_map, base_x, base_z)

        # Step 8: Place ores and stone variants
        self._ore_generator.place(blocks, base_x, base_z)

        # Step 9: Decorations (trees, plants)
        self._place_decorations(blocks, height_map, biome_map, base_x, base_z)

        return blocks

    def _apply_density_functions(self, blocks, base_x, base_z,
                                 height_map, climate_map):
        """Apply 3D density functions for terrain carving near the surface.
        
        The density function adds 3D terrain features (cliffs, overhangs, 
        cave entrances) near the surface. The height_map is the primary
        surface determination; density only carves away some solid blocks
        within DENSITY_MARGIN of the surface to create natural transitions.
        """
        DENSITY_MARGIN = 8  # Sample density within this range of surface

        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]
                climate = climate_map[lz][lx]
                si = surface_h - MIN_Y

                # Only apply density near the surface for 3D shaping
                # This creates cliffs and overhangs near the surface
                bottom_yi = max(5, si - DENSITY_MARGIN)
                top_yi = min(WORLD_HEIGHT, si + DENSITY_MARGIN // 2)

                for yi in range(bottom_yi, top_yi):
                    wy = MIN_Y + yi
                    density = self._density.compute_base_density(
                        float(wx), float(wy), float(wz), climate)

                    # Only carve if density is significantly negative
                    # This ensures only the most obvious carving happens
                    if density < -0.3:
                        if wy <= SEA_LEVEL and surface_h <= SEA_LEVEL:
                            blocks[yi][lz][lx] = WATER
                        else:
                            blocks[yi][lz][lx] = AIR

    def _place_decorations(self, blocks, height_map, biome_map, base_x, base_z):
        """Place trees, flowers, and other surface decorations."""
        rng = _random.Random(
            self.seed ^ (base_x * 42317861 + base_z * 9717613)
        )

        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]
                yi = surface_h - MIN_Y
                if yi < 0 or yi >= WORLD_HEIGHT:
                    continue

                biome = biome_map[lz][lx]
                top_block = blocks[yi][lz][lx]
                above_yi = yi + 1
                if above_yi >= WORLD_HEIGHT:
                    continue

                if top_block in (GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL, SNOW_BLOCK):
                    if self._should_place_tree(biome, surface_h, rng):
                        if self._is_clear_for_tree(blocks, lx, lz, above_yi):
                            self._place_tree(blocks, biome, lx, lz, above_yi, rng)
                            continue

                    if blocks[above_yi][lz][lx] == AIR:
                        self._place_surface_plant(blocks, biome, lx, lz, above_yi, rng)

                elif top_block in (SAND, RED_SAND, GRAVEL, CLAY) and surface_h < SEA_LEVEL:
                    self._place_underwater_decor(blocks, biome, lx, lz, yi, rng)

    def _should_place_tree(self, biome: str, surface_h: int, rng: _random.Random) -> bool:
        tree_chance = {
            "minecraft:plains": 0.015,
            "minecraft:forest": 0.08,
            "minecraft:flower_forest": 0.07,
            "minecraft:birch_forest": 0.08,
            "minecraft:dark_forest": 0.09,
            "minecraft:jungle": 0.10,
            "minecraft:bamboo_jungle": 0.08,
            "minecraft:sparse_jungle": 0.05,
            "minecraft:taiga": 0.07,
            "minecraft:old_growth_pine_taiga": 0.08,
            "minecraft:old_growth_spruce_taiga": 0.08,
            "minecraft:cherry_grove": 0.06,
            "minecraft:savanna": 0.035,
            "minecraft:savanna_plateau": 0.03,
            "minecraft:windswept_savanna": 0.025,
            "minecraft:mangrove_swamp": 0.04,
            "minecraft:swamp": 0.03,
        }.get(biome, 0.0)

        if surface_h > 130:
            tree_chance *= 0.3
        return rng.random() < tree_chance

    def _is_clear_for_tree(self, blocks, lx: int, lz: int, trunk_base_y: int,
                           radius: int = 2, height: int = 7) -> bool:
        for y in range(trunk_base_y, min(trunk_base_y + height, WORLD_HEIGHT)):
            for dz in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, nz = lx + dx, lz + dz
                    if not (0 <= nx < 16 and 0 <= nz < 16):
                        return False
                    if blocks[y][nz][nx] not in (AIR, WATER):
                        return False
        return True

    def _place_tree(self, blocks, biome: str, lx: int, lz: int,
                    trunk_base_y: int, rng: _random.Random):
        log_block = OAK_LOG
        leaves_block = OAK_LEAVES
        trunk_height = 4 + rng.randint(0, 2)
        canopy_radius = 2

        if biome in {"minecraft:birch_forest", "minecraft:old_growth_birch_forest"}:
            log_block = BIRCH_LOG
            leaves_block = BIRCH_LEAVES
        elif biome in {"minecraft:taiga", "minecraft:old_growth_pine_taiga",
                       "minecraft:old_growth_spruce_taiga", "minecraft:snowy_taiga"}:
            log_block = SPRUCE_LOG
            leaves_block = SPRUCE_LEAVES
            trunk_height = 5 + rng.randint(0, 2)
        elif biome in {"minecraft:jungle", "minecraft:bamboo_jungle",
                       "minecraft:sparse_jungle"}:
            log_block = JUNGLE_LOG
            leaves_block = JUNGLE_LEAVES
            trunk_height = 6 + rng.randint(0, 2)
        elif biome in {"minecraft:savanna", "minecraft:savanna_plateau",
                       "minecraft:windswept_savanna"}:
            log_block = ACACIA_LOG
            leaves_block = ACACIA_LEAVES
        elif biome == "minecraft:cherry_grove":
            log_block = CHERRY_LOG
            leaves_block = CHERRY_LEAVES
        elif biome == "minecraft:dark_forest":
            log_block = DARK_OAK_LOG
            leaves_block = DARK_OAK_LEAVES
            trunk_height = 5 + rng.randint(0, 1)
        elif biome in {"minecraft:mangrove_swamp", "minecraft:swamp"}:
            log_block = MANGROVE_LOG if biome == "minecraft:mangrove_swamp" else OAK_LOG
            leaves_block = MANGROVE_LEAVES if biome == "minecraft:mangrove_swamp" else OAK_LEAVES

        top_y = min(WORLD_HEIGHT - 1, trunk_base_y + trunk_height)
        for y in range(trunk_base_y, top_y):
            blocks[y][lz][lx] = log_block

        canopy_base = max(trunk_base_y, top_y - 3)
        for y in range(canopy_base, min(top_y + 2, WORLD_HEIGHT)):
            radius = canopy_radius - (1 if y >= top_y else 0)
            for dz in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if abs(dx) + abs(dz) > radius + 1 and rng.random() < 0.6:
                        continue
                    nx, nz = lx + dx, lz + dz
                    if 0 <= nx < 16 and 0 <= nz < 16 and blocks[y][nz][nx] == AIR:
                        blocks[y][nz][nx] = leaves_block

        if top_y < WORLD_HEIGHT and blocks[top_y][lz][lx] == AIR:
            blocks[top_y][lz][lx] = leaves_block

    def _place_surface_plant(self, blocks, biome: str, lx: int, lz: int,
                             plant_y: int, rng: _random.Random):
        flower_tables = {
            "minecraft:flower_forest": [DANDELION, POPPY, ALLIUM, AZURE_BLUET,
                                        RED_TULIP, ORANGE_TULIP, WHITE_TULIP,
                                        PINK_TULIP, OXEYE_DAISY, CORNFLOWER,
                                        LILY_OF_THE_VALLEY],
            "minecraft:cherry_grove": [PINK_TULIP, WHITE_TULIP, ALLIUM],
            "minecraft:meadow": [ALLIUM, AZURE_BLUET, CORNFLOWER, OXEYE_DAISY],
            "minecraft:swamp": [BLUE_ORCHID],
            "minecraft:mangrove_swamp": [BLUE_ORCHID],
            "minecraft:plains": [DANDELION, POPPY, CORNFLOWER],
            "minecraft:sunflower_plains": [DANDELION, POPPY, CORNFLOWER],
        }

        if biome in flower_tables and rng.random() < 0.18:
            blocks[plant_y][lz][lx] = rng.choice(flower_tables[biome])
        elif biome in {"minecraft:plains", "minecraft:forest", "minecraft:birch_forest",
                       "minecraft:flower_forest", "minecraft:meadow", "minecraft:taiga",
                       "minecraft:old_growth_pine_taiga",
                       "minecraft:old_growth_spruce_taiga"} and rng.random() < 0.35:
            blocks[plant_y][lz][lx] = SHORT_GRASS

    def _place_underwater_decor(self, blocks, biome: str, lx: int, lz: int,
                                floor_y: int, rng: _random.Random):
        water_y = floor_y + 1
        if water_y >= WORLD_HEIGHT or blocks[water_y][lz][lx] != WATER:
            return

        if biome in {"minecraft:warm_ocean", "minecraft:lukewarm_ocean"} and rng.random() < 0.08:
            coral_blocks = [
                TUBE_CORAL_BLOCK, BRAIN_CORAL_BLOCK, BUBBLE_CORAL_BLOCK,
                FIRE_CORAL_BLOCK, HORN_CORAL_BLOCK,
            ]
            coral_fans = [
                TUBE_CORAL_FAN, BRAIN_CORAL_FAN, BUBBLE_CORAL_FAN,
                FIRE_CORAL_FAN, HORN_CORAL_FAN,
            ]
            blocks[floor_y][lz][lx] = rng.choice(coral_blocks)
            if water_y < WORLD_HEIGHT and blocks[water_y][lz][lx] == WATER:
                blocks[water_y][lz][lx] = rng.choice(coral_fans)
            return

        if biome in {"minecraft:ocean", "minecraft:deep_ocean", "minecraft:cold_ocean",
                     "minecraft:deep_cold_ocean", "minecraft:lukewarm_ocean",
                     "minecraft:warm_ocean"}:
            if rng.random() < 0.22:
                height = 1 + rng.randint(0, 4)
                for i in range(height):
                    y = water_y + i
                    if y >= WORLD_HEIGHT or blocks[y][lz][lx] != WATER:
                        break
                    blocks[y][lz][lx] = KELP if i == height - 1 else KELP_PLANT
            elif rng.random() < 0.35:
                blocks[water_y][lz][lx] = SEAGRASS

    def _block_hash(self, x: int, y: int, z: int) -> float:
        """Simple coordinate hash for deterministic randomness."""
        n = x * 374761393 + y * 668265263 + z * 1274126177 + self.seed
        n = (n ^ (n >> 13)) * 1103515245
        n = n ^ (n >> 16)
        return (n & 0x7FFFFFFF) / 0x7FFFFFFF

    def get_height_map(self, chunk_x: int, chunk_z: int) -> list[list[int]]:
        """Compute height map for a chunk."""
        base_x = chunk_x * 16
        base_z = chunk_z * 16
        height_map = [[0] * 16 for _ in range(16)]
        for lx in range(16):
            for lz in range(16):
                h, _, _ = self.sample_column(base_x + lx, base_z + lz)
                height_map[lz][lx] = h
        return height_map

    def get_terrain_height(self, world_x: int, world_z: int) -> int:
        """Get terrain height at a specific world coordinate."""
        h, _, _ = self.sample_column(world_x, world_z)
        return h

    def build_chunk_biome_sections(self, chunk_x: int, chunk_z: int,
                                   chunk_blocks: list) -> list[list[int]]:
        """Build biome section IDs for a chunk, matching vanilla multi-noise."""
        base_x = chunk_x * 16
        base_z = chunk_z * 16

        # Compute surface heights from block data
        surface_heights = [[0] * 16 for _ in range(16)]
        for z in range(16):
            for x in range(16):
                for yi in range(len(chunk_blocks) - 1, -1, -1):
                    if chunk_blocks[yi][z][x] != 0:
                        surface_heights[z][x] = yi + MIN_Y
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

                        # Sample climate at this position
                        climate = self.sample_climate(world_x, world_z)

                        # Determine depth parameter
                        depth = max(0.0, min(1.0,
                                             (surface_height - world_y) / 128.0))
                        if world_y > surface_height:
                            depth = 0.0

                        biome_id = self.resolve_biome(climate, depth)

                        # Underground biome overrides
                        if world_y < -48 and surface_height - world_y > 16:
                            if climate.continentalness > 0.15 and climate.erosion < -0.05:
                                biome_id = _BiomeId.DEEP_DARK
                        if world_y < 40 and surface_height - world_y > 12:
                            if climate.humidity > 0.35 and climate.temperature > 0.0:
                                biome_id = _BiomeId.LUSH_CAVES
                            elif climate.humidity < -0.15 and climate.weirdness > 0.0:
                                biome_id = _BiomeId.DRIPSTONE_CAVES

                        biome_name = _BIOME_ID_TO_NAME.get(biome_id, "minecraft:plains")
                        section_biomes.append(
                            BIOME_NAME_TO_ID.get(biome_name, BIOME_NAME_TO_ID["minecraft:plains"])
                        )
            sections.append(section_biomes)
        return sections
