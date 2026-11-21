// ============================================================
// PyMC - biome sampling, native port of world/biomes.py
//
// The noise tables (permutations and offsets) are built in Python with the same
// random generator as world/noise.py and passed in, so the octave noise here
// evaluates the same double-precision operations in the same order. Build with
// -ffp-contract=off so no fused multiply-add changes the results
// (tests/test_biome_native.py compares every biome with the Python sampler).
// ============================================================
#pragma once

#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

namespace vrs::biome {

constexpr int MIN_Y = -64;
constexpr int SEA_LEVEL = 63;
constexpr int SECTIONS = 24;
constexpr int SAMPLES_PER_SECTION = 64;   // 4 x 4 x 4 biome cells

struct Layer {
    double xo, yo, zo;
    int perm[512];
};

struct Octaves {
    int count = 0;
    double persistence = 0.5, lacunarity = 2.0, max_value = 1.0;
    std::vector<Layer> layers;

    static inline double fade(double t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
    static inline double lerp(double t, double a, double b) { return a + t * (b - a); }
    static inline double grad(int hash, double x, double y, double z) {
        int h = hash & 15;
        double u = h < 8 ? x : y;
        double v;
        if (h < 4) v = y;
        else if (h == 12 || h == 14) v = x;
        else v = z;
        return ((h & 1) == 0 ? u : -u) + ((h & 2) == 0 ? v : -v);
    }

    // ImprovedNoise.noise2d(x, z) = noise(x, 0, z)
    static double layer_noise(const Layer& layer, double x, double z) {
        x = x + layer.xo;
        double y = 0.0 + layer.yo;
        z = z + layer.zo;
        const int64_t fx = (int64_t)std::floor(x), fy = (int64_t)std::floor(y), fz = (int64_t)std::floor(z);
        const int xi = (int)(fx & 255), yi = (int)(fy & 255), zi = (int)(fz & 255);
        const double xf = x - (double)fx, yf = y - (double)fy, zf = z - (double)fz;
        const double u = fade(xf), v = fade(yf), w = fade(zf);
        const int* p = layer.perm;
        const int a = p[xi] + yi;
        const int aa = p[a] + zi;
        const int ab = p[a + 1] + zi;
        const int b = p[xi + 1] + yi;
        const int ba = p[b] + zi;
        const int bb = p[b + 1] + zi;
        return lerp(w,
            lerp(v,
                lerp(u, grad(p[aa], xf, yf, zf), grad(p[ba], xf - 1, yf, zf)),
                lerp(u, grad(p[ab], xf, yf - 1, zf), grad(p[bb], xf - 1, yf - 1, zf))),
            lerp(v,
                lerp(u, grad(p[aa + 1], xf, yf, zf - 1), grad(p[ba + 1], xf - 1, yf, zf - 1)),
                lerp(u, grad(p[ab + 1], xf, yf - 1, zf - 1), grad(p[bb + 1], xf - 1, yf - 1, zf - 1))));
    }

    double sample(double x, double z) const {
        double total = 0.0, amplitude = 1.0, frequency = 1.0;
        for (const Layer& layer : layers) {
            total += layer_noise(layer, x * frequency, z * frequency) * amplitude;
            amplitude *= persistence;
            frequency *= lacunarity;
        }
        return total / max_value;
    }
};

struct Sampler {
    Octaves temperature, humidity, continental, erosion, weirdness, swamp, mushroom;
    std::unordered_map<std::string, int> ids;

    int id(const char* name) const { return ids.at(name); }

    struct Climate { double temperature, humidity, continental, erosion, weirdness; };

    Climate climate(int64_t wx, int64_t wz) const {
        return {
            temperature.sample((double)wx / 512.0, (double)wz / 512.0),
            humidity.sample((double)wx / 384.0, (double)wz / 384.0),
            continental.sample((double)wx / 768.0, (double)wz / 768.0),
            erosion.sample((double)wx / 256.0, (double)wz / 256.0),
            weirdness.sample((double)wx / 192.0, (double)wz / 192.0),
        };
    }

    // Port of BiomeSampler.sample_surface_biome; returns the biome id.
    int surface(int64_t wx, int64_t wz, int surface_height) const {
        const Climate c = climate(wx, wz);
        const double swampiness = swamp.sample((double)wx / 160.0, (double)wz / 160.0);
        const double mushroom_v = mushroom.sample((double)wx / 2048.0, (double)wz / 2048.0);
        const double temp = c.temperature, humid = c.humidity, cont = c.continental;
        const double eros = c.erosion, weird = c.weirdness;
        const bool deep = surface_height < SEA_LEVEL - 10;

        if (mushroom_v > 0.82 && cont < -0.15) return id("minecraft:mushroom_fields");

        if (cont < -0.55) {
            if (temp < -0.45) return id(deep ? "minecraft:deep_frozen_ocean" : "minecraft:frozen_ocean");
            if (temp < -0.05) return id(deep ? "minecraft:deep_cold_ocean" : "minecraft:cold_ocean");
            if (temp > 0.65) return id(humid > 0.35 ? "minecraft:warm_ocean" : "minecraft:lukewarm_ocean");
            return id(deep ? "minecraft:deep_ocean" : "minecraft:ocean");
        }

        if (cont < -0.42) {
            if (temp < -0.25) return id("minecraft:frozen_river");
            return id("minecraft:river");
        }

        if (surface_height <= SEA_LEVEL + 2) {
            if (temp < -0.3) return id("minecraft:snowy_beach");
            if (eros < -0.35) return id("minecraft:stony_shore");
            return id("minecraft:beach");
        }

        if (surface_height > 140 || (surface_height > 118 && weird > 0.55)) {
            if (temp < -0.45) return id(weird > 0.15 ? "minecraft:jagged_peaks" : "minecraft:frozen_peaks");
            if (temp < -0.1) return id(humid > 0.0 ? "minecraft:snowy_slopes" : "minecraft:grove");
            return id("minecraft:stony_peaks");
        }

        if (surface_height > 110) {
            if (temp < -0.2) return id("minecraft:grove");
            return id("minecraft:meadow");
        }

        if (temp > 0.8 && humid < -0.05) {
            if (weird > 0.35) return id("minecraft:eroded_badlands");
            if (eros < -0.15) return id("minecraft:wooded_badlands");
            if (humid < -0.3) return id("minecraft:desert");
            return id("minecraft:badlands");
        }

        if (temp > 0.7 && humid > 0.3) {
            if (humid > 0.65 && weird > 0.2) return id("minecraft:bamboo_jungle");
            if (humid > 0.5) return id("minecraft:jungle");
            return id("minecraft:sparse_jungle");
        }

        if (0.35 < temp && temp <= 0.8 && humid > 0.35 && surface_height <= SEA_LEVEL + 12) {
            return id(swampiness > 0.25 ? "minecraft:mangrove_swamp" : "minecraft:swamp");
        }

        if (temp > 0.45 && humid < 0.15) {
            if (weird > 0.45) return id("minecraft:windswept_savanna");
            if (surface_height > 88) return id("minecraft:savanna_plateau");
            return id("minecraft:savanna");
        }

        if (temp < -0.45) {
            if (weird > 0.55) return id("minecraft:ice_spikes");
            if (humid > 0.0) return id("minecraft:snowy_taiga");
            return id("minecraft:snowy_plains");
        }

        if (humid < -0.35) {
            if (weird > 0.45) return id("minecraft:windswept_gravelly_hills");
            if (weird > 0.15 || surface_height > 90) return id("minecraft:windswept_hills");
            return id("minecraft:plains");
        }

        if (humid > 0.55) {
            if (surface_height > 88 && weird > 0.15) return id("minecraft:old_growth_spruce_taiga");
            if (temp < 0.35) return id("minecraft:taiga");
            if (weird > 0.45) return id("minecraft:dark_forest");
            return id("minecraft:forest");
        }

        if (0.45 < humid && humid <= 0.55) {
            if (weird > 0.55) return id("minecraft:flower_forest");
            if (weird > 0.25) return id("minecraft:birch_forest");
            return id("minecraft:forest");
        }

        if (0.2 < humid && humid <= 0.45) {
            if (surface_height > 95 && weird > 0.35) return id("minecraft:old_growth_birch_forest");
            if (temp < 0.35) return id("minecraft:old_growth_pine_taiga");
            if (weird > 0.5) return id("minecraft:cherry_grove");
            return id("minecraft:plains");
        }

        return id(weird > 0.6 ? "minecraft:sunflower_plains" : "minecraft:plains");
    }

    // Port of BiomeSampler.sample_biome (surface biome plus caves).
    int sample(int64_t wx, int wy, int64_t wz, int surface_height) const {
        const int surface_id = surface(wx, wz, surface_height);
        const Climate c = climate(wx, wz);
        const int depth = surface_height - wy;
        if (wy < -48 && depth > 16 && c.continental > 0.15 && c.erosion < -0.05) return id("minecraft:deep_dark");
        if (wy < 40 && depth > 12) {
            if (c.humidity > 0.35 && c.temperature > 0.0) return id("minecraft:lush_caves");
            if (c.humidity < -0.15 && c.weirdness > 0.0) return id("minecraft:dripstone_caves");
        }
        return surface_id;
    }
};

// Surface heights of the 16x16 columns (index x + z*16), from column_heights:
// the index of the highest non-air block + 1, or 0 when the column is empty.
inline void build_sections(const Sampler& s, int chunk_x, int chunk_z,
                           const int32_t* column_height, int32_t* out) {
    const int64_t base_x = (int64_t)chunk_x * 16, base_z = (int64_t)chunk_z * 16;
    for (int section = 0; section < SECTIONS; section++) {
        int32_t* dst = out + section * SAMPLES_PER_SECTION;
        int k = 0;
        for (int local_y = 0; local_y < 4; local_y++) {
            for (int bz = 0; bz < 4; bz++) {
                for (int bx = 0; bx < 4; bx++, k++) {
                    const int sample_x = bx * 4 + 2, sample_z = bz * 4 + 2;
                    const int64_t wx = base_x + sample_x, wz = base_z + sample_z;
                    const int wy = MIN_Y + section * 16 + local_y * 4 + 2;
                    const int h = column_height[sample_x + sample_z * 16];
                    const int surface_height = h > 0 ? h - 1 + MIN_Y : MIN_Y;
                    dst[k] = s.sample(wx, wy, wz, surface_height);
                }
            }
        }
    }
}

}  // namespace vrs::biome
