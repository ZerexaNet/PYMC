// ============================================================
// PyMC - C++ 高性能地形生成器
// 通过 stdin/stdout 二进制协议通信，作为 Python 服务端的子进程
// 协议:
//   请求: 16 字节 (小端)
//     [0:4]   int32  chunk_x
//     [4:8]   int32  chunk_z
//     [8:16]  int64  seed
//   响应: 197120 字节 (小端)
//     [0:4]      uint32  数据长度 (固定 197120)
//     [4:196612] uint16  方块数据 98304 个 (y*256+z*16+x 顺序)
//     [196612:197124] int16  高度图 256 个 (z*16+x 顺序)
// ============================================================

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <string>
#include <vector>
#include <algorithm>
#include <array>
#include <thread>
#include <atomic>

#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

// ============================================================
// 方块 ID 常量 (与 Minecraft 1.21.1 全局调色板一致)
// ============================================================
static constexpr int AIR = 0;
static constexpr int STONE = 1;
static constexpr int GRANITE = 2;
static constexpr int DIORITE = 4;
static constexpr int ANDESITE = 6;
static constexpr int GRASS_BLOCK = 9;
static constexpr int DIRT = 10;
static constexpr int BEDROCK = 79;
static constexpr int WATER = 80;
static constexpr int SAND = 112;
static constexpr int SANDSTONE = 535;
static constexpr int GRAVEL = 118;
static constexpr int GOLD_ORE = 123;
static constexpr int DEEPSLATE_GOLD_ORE = 124;
static constexpr int IRON_ORE = 125;
static constexpr int DEEPSLATE_IRON_ORE = 126;
static constexpr int COAL_ORE = 127;
static constexpr int DEEPSLATE_COAL_ORE = 128;
static constexpr int LAPIS_ORE = 520;
static constexpr int DEEPSLATE_LAPIS_ORE = 521;
static constexpr int DIAMOND_ORE = 4274;
static constexpr int DEEPSLATE_DIAMOND_ORE = 4275;
static constexpr int REDSTONE_ORE = 5735;
static constexpr int DEEPSLATE_REDSTONE_ORE = 5737;
static constexpr int SNOW = 5772;
static constexpr int ICE = 5780;
static constexpr int SNOW_BLOCK = 5781;
static constexpr int CLAY = 5798;
static constexpr int EMERALD_ORE = 7511;
static constexpr int DEEPSLATE_EMERALD_ORE = 7512;
static constexpr int TUFF = 21081;
static constexpr int COPPER_ORE = 22942;
static constexpr int DEEPSLATE_COPPER_ORE = 22943;
static constexpr int DEEPSLATE = 24905;

// ============================================================
// 世界常量
// ============================================================
static constexpr int MIN_Y = -64;
static constexpr int MAX_Y = 319;
static constexpr int WORLD_HEIGHT = 384;  // MAX_Y - MIN_Y + 1
static constexpr int SEA_LEVEL = 63;
static constexpr int CELL_WIDTH = 4;       // NoiseSettings.create(-64, 384, 1, 2)
static constexpr int CELL_HEIGHT = 8;      // QuartPos.toBlock(noiseSizeVertical)
static constexpr int CELL_COUNT_XZ = 16 / CELL_WIDTH;
static constexpr int CELL_COUNT_Y = WORLD_HEIGHT / CELL_HEIGHT;
static constexpr double GLOBAL_OFFSET = -0.50375;
static constexpr double SURFACE_DENSITY_THRESHOLD = 1.5625;
static constexpr double CHEESE_NOISE_TARGET = -0.703125;

// ============================================================
// Perlin 排列表
// ============================================================
static const int PERLIN_PERM[256] = {
    151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,
    140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,
    247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,
    57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,
    74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,
    60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,
    65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,
    200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,
    52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,
    207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,
    119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,
    129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,
    218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,
    81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,
    184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,
    222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180
};

// ============================================================
// Perlin Noise
// ============================================================
static inline double fade(double t) {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

static inline double lerp(double t, double a, double b) {
    return a + t * (b - a);
}

static inline double grad(int hash_val, double x, double y, double z) {
    int h = hash_val & 15;
    double u = h < 8 ? x : y;
    double v;
    if (h < 4) v = y;
    else if (h == 12 || h == 14) v = x;
    else v = z;
    return ((h & 1) == 0 ? u : -u) + ((h & 2) == 0 ? v : -v);
}

// 简易线性同余随机数生成器 (模拟 Python 的 Random)
struct SimpleRNG {
    // 使用 Mersenne Twister 风格的 LCG
    uint64_t state;

    void seed(int64_t s) {
        // 与 Python random.Random(seed) 行为近似
        state = (uint64_t)s;
        // 预热
        for (int i = 0; i < 10; i++) next_u32();
    }

    uint32_t next_u32() {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return (uint32_t)(state >> 33);
    }

    // 返回 [0, n] 范围内的整数 (模拟 Python randint(0, n))
    int randint(int lo, int hi) {
        if (lo >= hi) return lo;
        uint32_t range = (uint32_t)(hi - lo + 1);
        return lo + (int)(next_u32() % range);
    }

    // 返回 [0, 1) 的浮点数
    double random_double() {
        return (double)(next_u32() & 0x7FFFFFFF) / (double)0x80000000;
    }

    // 三角分布
    double triangular(double lo, double hi, double mode) {
        double u = random_double();
        double c = (mode - lo) / (hi - lo);
        if (u <= c) {
            return lo + std::sqrt(u * (hi - lo) * (mode - lo));
        } else {
            return hi - std::sqrt((1.0 - u) * (hi - lo) * (hi - mode));
        }
    }
};

struct ImprovedNoise {
    int perm[512];
    double x_offset, y_offset, z_offset;

    void init(SimpleRNG& rng) {
        x_offset = rng.random_double() * 256.0;
        y_offset = rng.random_double() * 256.0;
        z_offset = rng.random_double() * 256.0;

        int p[256];
        memcpy(p, PERLIN_PERM, sizeof(p));

        // Fisher-Yates 洗牌
        for (int i = 255; i > 0; i--) {
            int j = rng.randint(0, i);
            std::swap(p[i], p[j]);
        }

        for (int i = 0; i < 256; i++) {
            perm[i] = p[i];
            perm[i + 256] = p[i];
        }
    }

    double noise(double x, double y, double z) const {
        x += x_offset;
        y += y_offset;
        z += z_offset;

        int xi = ((int)std::floor(x)) & 255;
        int yi = ((int)std::floor(y)) & 255;
        int zi = ((int)std::floor(z)) & 255;

        double xf = x - std::floor(x);
        double yf = y - std::floor(y);
        double zf = z - std::floor(z);

        double u = fade(xf);
        double v = fade(yf);
        double w = fade(zf);

        int a  = perm[xi] + yi;
        int aa = perm[a] + zi;
        int ab = perm[a + 1] + zi;
        int b  = perm[xi + 1] + yi;
        int ba = perm[b] + zi;
        int bb = perm[b + 1] + zi;

        return lerp(w,
            lerp(v,
                lerp(u, grad(perm[aa],     xf,     yf,     zf),
                        grad(perm[ba],     xf-1.0, yf,     zf)),
                lerp(u, grad(perm[ab],     xf,     yf-1.0, zf),
                        grad(perm[bb],     xf-1.0, yf-1.0, zf))),
            lerp(v,
                lerp(u, grad(perm[aa+1],   xf,     yf,     zf-1.0),
                        grad(perm[ba+1],   xf-1.0, yf,     zf-1.0)),
                lerp(u, grad(perm[ab+1],   xf,     yf-1.0, zf-1.0),
                        grad(perm[bb+1],   xf-1.0, yf-1.0, zf-1.0))));
    }

    double noise2d(double x, double z) const {
        return noise(x, 0.0, z);
    }
};

struct OctaveNoise {
    std::vector<ImprovedNoise> layers;
    int octaves;
    double persistence;
    double lacunarity;
    double max_value;

    void init(int64_t seed_val, int oct, double pers, double lac) {
        octaves = oct;
        persistence = pers;
        lacunarity = lac;

        SimpleRNG rng;
        rng.seed(seed_val);
        layers.resize(oct);
        for (int i = 0; i < oct; i++) {
            layers[i].init(rng);
        }

        max_value = 0.0;
        double amp = 1.0;
        for (int i = 0; i < oct; i++) {
            max_value += amp;
            amp *= pers;
        }
    }

    double sample(double x, double z) const {
        double total = 0.0;
        double amp = 1.0;
        double freq = 1.0;
        for (int i = 0; i < octaves; i++) {
            total += layers[i].noise2d(x * freq, z * freq) * amp;
            amp *= persistence;
            freq *= lacunarity;
        }
        return total / max_value;
    }

    double sample_3d(double x, double y, double z) const {
        double total = 0.0;
        double amp = 1.0;
        double freq = 1.0;
        for (int i = 0; i < octaves; i++) {
            total += layers[i].noise(x * freq, y * freq, z * freq) * amp;
            amp *= persistence;
            freq *= lacunarity;
        }
        return total / max_value;
    }
};

static inline double clamp01(double v) {
    return std::max(0.0, std::min(1.0, v));
}

static inline double clamped_lerp(double a, double b, double t) {
    return lerp(clamp01(t), a, b);
}

static inline double inverse_lerp(double a, double b, double v) {
    if (a == b) return 0.0;
    return clamp01((v - a) / (b - a));
}

static inline double y_clamped_gradient(double y, double y0, double y1,
                                        double v0, double v1) {
    return clamped_lerp(v0, v1, inverse_lerp(y0, y1, y));
}

static inline double half_negative(double v) {
    return v < 0.0 ? v * 0.5 : v;
}

static inline double quarter_negative(double v) {
    return v < 0.0 ? v * 0.25 : v;
}

static inline double peaks_and_valleys(double v) {
    return -(std::fabs(std::fabs(v) - 0.6666667) - 0.33333334) * 3.0;
}

static inline double density_squeeze(double v) {
    double x = std::max(-1.0, std::min(1.0, v));
    return x / 2.0 - x * x * x / 24.0;
}

// ============================================================
// 地形生成器
// ============================================================
struct TerrainGenerator {
    int64_t seed;
    OctaveNoise shift_noise;
    OctaveNoise continental_noise;
    OctaveNoise erosion_noise;
    OctaveNoise ridge_noise;
    OctaveNoise jagged_noise;
    OctaveNoise low_noise;
    OctaveNoise high_noise;
    OctaveNoise selector_noise;
    OctaveNoise cave_noise;
    OctaveNoise cave_layer_noise;
    OctaveNoise cave_entrance_noise;
    OctaveNoise noodle_noise;
    OctaveNoise noodle_ridge_noise;
    OctaveNoise surface_noise;
    OctaveNoise temperature_noise;

    void init(int64_t s) {
        seed = s;
        // Parameters mirror the 1.21.1 decompiled NoiseData keys closely
        // enough for this native fast path while keeping the binary protocol
        // compact and dependency-free.
        shift_noise.init(s + 24, 4, 0.5, 2.0);          // Noises.SHIFT
        continental_noise.init(s + 17, 9, 0.52, 2.0);   // Noises.CONTINENTALNESS
        erosion_noise.init(s + 18, 5, 0.50, 2.0);       // Noises.EROSION
        ridge_noise.init(s + 23, 6, 0.50, 2.0);         // Noises.RIDGE
        jagged_noise.init(s + 53, 16, 0.50, 2.0);       // Noises.JAGGED
        low_noise.init(s + 101, 8, 0.50, 2.0);          // BlendedNoise low
        high_noise.init(s + 102, 8, 0.50, 2.0);         // BlendedNoise high
        selector_noise.init(s + 103, 4, 0.50, 2.0);     // BlendedNoise selector
        cave_noise.init(s + 44, 10, 0.50, 2.0);         // Noises.CAVE_CHEESE
        cave_layer_noise.init(s + 43, 3, 0.50, 2.0);    // Noises.CAVE_LAYER
        cave_entrance_noise.init(s + 42, 3, 0.50, 2.0); // Noises.CAVE_ENTRANCE
        noodle_noise.init(s + 49, 3, 0.50, 2.0);        // Noises.NOODLE
        noodle_ridge_noise.init(s + 51, 3, 0.50, 2.0);  // Noises.NOODLE_RIDGE_A/B
        surface_noise.init(s + 54, 3, 0.5, 2.0);        // Noises.SURFACE
        temperature_noise.init(s + 15, 6, 0.5, 2.0);    // Noises.TEMPERATURE
    }

    double block_hash(int x, int y, int z) const {
        int64_t n = (int64_t)x * 374761393LL + (int64_t)y * 668265263LL
                  + (int64_t)z * 1274126177LL + seed;
        n = (n ^ (n >> 13)) * 1103515245LL;
        n = n ^ (n >> 16);
        return (double)(n & 0x7FFFFFFF) / (double)0x7FFFFFFF;
    }

    struct TerrainSample {
        double continental;
        double erosion;
        double ridges;
        double peaks_valleys;
    };

    TerrainSample sample_terrain(int wx, int wz) const {
        double sx = shift_noise.sample(wx / 1024.0, wz / 1024.0) * 32.0;
        double sz = shift_noise.sample((wx + 10000) / 1024.0, (wz - 10000) / 1024.0) * 32.0;
        double x = wx + sx;
        double z = wz + sz;

        TerrainSample t{};
        t.continental = std::max(-1.2, std::min(1.2, continental_noise.sample(x / 768.0, z / 768.0) * 1.18));
        t.erosion = std::max(-1.0, std::min(1.0, erosion_noise.sample(x / 512.0, z / 512.0) * 1.10));
        t.ridges = std::max(-1.0, std::min(1.0, ridge_noise.sample(x / 384.0, z / 384.0) * 1.20));
        t.peaks_valleys = peaks_and_valleys(t.ridges);
        return t;
    }

    double terrain_offset(const TerrainSample& t) const {
        double c = t.continental;
        double e = t.erosion;
        double pv = t.peaks_valleys;
        if (c < -1.02) return clamped_lerp(0.044, -0.2222, inverse_lerp(-1.10, -1.02, c));
        if (c < -0.51) return -0.2222;
        if (c < -0.44) return clamped_lerp(-0.2222, -0.12, inverse_lerp(-0.51, -0.44, c));
        if (c < -0.18) return -0.12;
        if (c < -0.10) return clamped_lerp(-0.12, -0.055, inverse_lerp(-0.18, -0.10, c));

        double erosion_low = 1.0 - clamp01((e + 1.0) * 0.5);
        double inland = clamp01((c + 0.10) / 1.10);
        double peak = clamp01((pv + 0.20) / 1.20);
        double valley = clamp01((0.10 - std::fabs(t.ridges)) / 0.10);
        double mountain = inland * peak * (0.35 + erosion_low * 0.95);
        double rolling = (0.03 + 0.10 * inland) * (0.45 + erosion_low * 0.55);
        return rolling + mountain * 0.34 - valley * 0.075;
    }

    double terrain_factor(const TerrainSample& t) const {
        double c = t.continental;
        double e = t.erosion;
        double pv = t.peaks_valleys;
        if (c < -0.19) return 3.95;
        double erosion_low = 1.0 - clamp01((e + 1.0) * 0.5);
        double peak = clamp01((pv + 0.15) / 1.15);
        double base = clamped_lerp(4.69, 6.30, erosion_low);
        return base + peak * erosion_low * 1.35;
    }

    double terrain_jaggedness(const TerrainSample& t) const {
        if (t.continental < -0.11) return 0.0;
        double erosion_low = 1.0 - clamp01((t.erosion + 1.0) * 0.5);
        double peak = clamp01((t.peaks_valleys - 0.10) / 0.90);
        return peak * erosion_low * clamp01((t.continental + 0.11) / 0.76);
    }

    double blended_base_noise(int wx, int wy, int wz) const {
        double xz = 80.0;
        double y = 160.0;
        double low = low_noise.sample_3d(wx / xz, wy / y, wz / xz);
        double high = high_noise.sample_3d(wx / xz, wy / y, wz / xz);
        double selector = clamp01((selector_noise.sample_3d(wx / 640.0, wy / 320.0, wz / 640.0) + 1.0) * 0.5);
        double detail = low * (1.0 - selector) + high * selector;
        return detail * 0.82 + CHEESE_NOISE_TARGET * 0.12;
    }

    double slide_overworld(double density, int wy) const {
        double top = y_clamped_gradient(wy, 240.0, 256.0, 1.0, 0.0);
        density = lerp(top, -0.078125, density);
        double bottom = y_clamped_gradient(wy, -64.0, -40.0, 0.0, 1.0);
        density = lerp(bottom, 0.1171875, density);
        return density;
    }

    double cave_density(int wx, int wy, int wz, double sloped_cheese) const {
        if (wy > 96 || sloped_cheese > SURFACE_DENSITY_THRESHOLD) {
            return sloped_cheese;
        }

        double cheese = cave_noise.sample_3d(wx / 64.0, wy / 48.0, wz / 64.0);
        double layer = cave_layer_noise.sample_3d(wx / 96.0, wy / 40.0, wz / 96.0);
        double roughness = std::fabs(cave_entrance_noise.sample_3d(wx / 32.0, wy / 32.0, wz / 32.0)) - 0.36;
        double cave = std::max(layer * layer * 2.6, 0.34 + cheese + roughness * 0.35);

        double noodle_gate = noodle_noise.sample_3d(wx / 96.0, wy / 96.0, wz / 96.0);
        if (wy >= -60 && noodle_gate < 0.0) {
            double ridge_a = std::fabs(noodle_ridge_noise.sample_3d(wx / 36.0, wy / 36.0, wz / 36.0));
            double ridge_b = std::fabs(noodle_ridge_noise.sample_3d((wx + 20000) / 36.0, wy / 36.0, (wz - 20000) / 36.0));
            cave = std::min(cave, -0.08 + std::max(ridge_a, ridge_b) * 1.5);
        }

        return std::min(sloped_cheese, cave);
    }

    double sample_density(int wx, int wy, int wz) const {
        TerrainSample t = sample_terrain(wx, wz);
        double offset = GLOBAL_OFFSET + terrain_offset(t);
        double depth = y_clamped_gradient(wy, -64.0, 320.0, 1.5, -1.5) + offset;
        double jagged = terrain_jaggedness(t) *
                        half_negative(jagged_noise.sample_3d(wx / 1500.0, wy / 1500.0, wz / 1500.0));
        double gradient = 4.0 * quarter_negative((depth + jagged) * terrain_factor(t));
        double sloped_cheese = gradient + blended_base_noise(wx, wy, wz);
        double density = cave_density(wx, wy, wz, sloped_cheese);
        density = slide_overworld(density, wy);
        return density_squeeze(density * 0.64);
    }

    static double trilerp(double tx, double ty, double tz,
                          double c000, double c100, double c010, double c110,
                          double c001, double c101, double c011, double c111) {
        double x00 = lerp(tx, c000, c100);
        double x10 = lerp(tx, c010, c110);
        double x01 = lerp(tx, c001, c101);
        double x11 = lerp(tx, c011, c111);
        double y0 = lerp(ty, x00, x10);
        double y1 = lerp(ty, x01, x11);
        return lerp(tz, y0, y1);
    }

    // 主生成函数: 生成 384*16*16 的方块数据
    // blocks[y][z][x] => blocks[y * 256 + z * 16 + x]
    void generate_chunk(int chunk_x, int chunk_z, int* blocks, int16_t* heightmap_out = nullptr) const {
        const int total = WORLD_HEIGHT * 16 * 16;
        memset(blocks, 0, total * sizeof(int));  // 全 AIR

        int base_x = chunk_x * 16;
        int base_z = chunk_z * 16;

        int height_map[16][16];
        for (int z = 0; z < 16; z++) {
            for (int x = 0; x < 16; x++) {
                height_map[z][x] = MIN_Y;
            }
        }

        double density[CELL_COUNT_XZ + 1][CELL_COUNT_Y + 1][CELL_COUNT_XZ + 1];
        for (int cx = 0; cx <= CELL_COUNT_XZ; cx++) {
            int wx = base_x + cx * CELL_WIDTH;
            for (int cz = 0; cz <= CELL_COUNT_XZ; cz++) {
                int wz = base_z + cz * CELL_WIDTH;
                for (int cy = 0; cy <= CELL_COUNT_Y; cy++) {
                    int wy = MIN_Y + cy * CELL_HEIGHT;
                    density[cx][cy][cz] = sample_density(wx, wy, wz);
                }
            }
        }

        // --- 第一步: 1.21.1 NoiseBasedChunkGenerator 风格的 cell 插值填充 ---
        for (int cx = 0; cx < CELL_COUNT_XZ; cx++) {
            for (int cz = 0; cz < CELL_COUNT_XZ; cz++) {
                for (int cy = 0; cy < CELL_COUNT_Y; cy++) {
                    double c000 = density[cx][cy][cz];
                    double c100 = density[cx + 1][cy][cz];
                    double c010 = density[cx][cy + 1][cz];
                    double c110 = density[cx + 1][cy + 1][cz];
                    double c001 = density[cx][cy][cz + 1];
                    double c101 = density[cx + 1][cy][cz + 1];
                    double c011 = density[cx][cy + 1][cz + 1];
                    double c111 = density[cx + 1][cy + 1][cz + 1];

                    for (int dy = 0; dy < CELL_HEIGHT; dy++) {
                        int yi = cy * CELL_HEIGHT + dy;
                        int wy = MIN_Y + yi;
                        double ty = (double)dy / (double)CELL_HEIGHT;
                        for (int dx = 0; dx < CELL_WIDTH; dx++) {
                            int lx = cx * CELL_WIDTH + dx;
                            int wx = base_x + lx;
                            double tx = (double)dx / (double)CELL_WIDTH;
                            for (int dz = 0; dz < CELL_WIDTH; dz++) {
                                int lz = cz * CELL_WIDTH + dz;
                                int wz = base_z + lz;
                                double tz = (double)dz / (double)CELL_WIDTH;
                                double d = trilerp(tx, ty, tz, c000, c100, c010, c110, c001, c101, c011, c111);
                                int idx = yi * 256 + lz * 16 + lx;

                                if (yi == 0 || (yi < 5 && block_hash(wx, wy, wz) < (5 - yi) * 0.2)) {
                                    blocks[idx] = BEDROCK;
                                } else if (d > 0.0) {
                                    blocks[idx] = (wy < 0) ? DEEPSLATE : STONE;
                                    if (wy > height_map[lz][lx]) {
                                        height_map[lz][lx] = wy;
                                    }
                                } else if (wy <= SEA_LEVEL) {
                                    blocks[idx] = WATER;
                                }
                            }
                        }
                    }
                }
            }
        }

        for (int lz = 0; lz < 16; lz++) {
            for (int lx = 0; lx < 16; lx++) {
                if (height_map[lz][lx] < MIN_Y + 1) {
                    height_map[lz][lx] = MIN_Y + 1;
                }
                if (heightmap_out != nullptr) {
                    heightmap_out[lz * 16 + lx] = (int16_t)height_map[lz][lx];
                }
            }
        }

        // --- 第二步: 地表规则 ---
        apply_surface_rules(blocks, height_map, base_x, base_z);

        // --- 第三步: 矿石 ---
        place_ores(blocks, base_x, base_z);

        // --- 第四步: 石头变种 ---
        place_stone_variants(blocks, base_x, base_z);
    }

    void apply_surface_rules(int* blocks, int height_map[16][16],
                             int base_x, int base_z) const {
        for (int lx = 0; lx < 16; lx++) {
            for (int lz = 0; lz < 16; lz++) {
                int wx = base_x + lx;
                int wz = base_z + lz;
                int surface_h = height_map[lz][lx];

                double surf_n = surface_noise.sample(wx / 48.0, wz / 48.0);
                double temp = temperature_noise.sample(wx / 512.0, wz / 512.0);

                bool is_beach = (SEA_LEVEL - 2 <= surface_h && surface_h <= SEA_LEVEL + 2 && surf_n > -0.3);
                bool is_desert = (surf_n > 0.6 && surface_h < SEA_LEVEL + 15);
                bool is_cold = (temp < -0.5 && surface_h > SEA_LEVEL + 10);
                bool is_gravel_beach = (is_beach && surf_n > 0.4);
                bool is_underwater = (surface_h < SEA_LEVEL);

                int si = surface_h - MIN_Y;
                if (si < 0 || si >= WORLD_HEIGHT) continue;

                // 检查地表是否被挖空
                int cur = blocks[si * 256 + lz * 16 + lx];
                if (cur == AIR || cur == WATER) {
                    bool found = false;
                    for (int sy = si; sy >= std::max(0, si - 20); sy--) {
                        int sc = blocks[sy * 256 + lz * 16 + lx];
                        if (sc != AIR && sc != WATER) {
                            si = sy;
                            surface_h = si + MIN_Y;
                            found = true;
                            break;
                        }
                    }
                    if (!found) continue;
                }

                auto set_block = [&](int yi, int lz_, int lx_, int bid) {
                    if (yi >= 0 && yi < WORLD_HEIGHT)
                        blocks[yi * 256 + lz_ * 16 + lx_] = bid;
                };

                auto get_block = [&](int yi, int lz_, int lx_) -> int {
                    if (yi >= 0 && yi < WORLD_HEIGHT)
                        return blocks[yi * 256 + lz_ * 16 + lx_];
                    return AIR;
                };

                if (is_gravel_beach) {
                    set_block(si, lz, lx, GRAVEL);
                    for (int d = 1; d < 4; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, DIRT);
                    }
                } else if (is_desert) {
                    set_block(si, lz, lx, SAND);
                    for (int d = 1; d < 5; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, d < 3 ? SAND : SANDSTONE);
                    }
                } else if (is_beach && !is_underwater) {
                    set_block(si, lz, lx, SAND);
                    for (int d = 1; d < 4; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, d < 2 ? SAND : SANDSTONE);
                    }
                } else if (is_cold) {
                    set_block(si, lz, lx, SNOW_BLOCK);
                    for (int d = 1; d < 4; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, DIRT);
                    }
                    if (si + 1 < WORLD_HEIGHT && get_block(si + 1, lz, lx) == AIR)
                        set_block(si + 1, lz, lx, SNOW);
                    int water_yi = SEA_LEVEL - MIN_Y;
                    if (water_yi >= 0 && water_yi < WORLD_HEIGHT &&
                        get_block(water_yi, lz, lx) == WATER)
                        set_block(water_yi, lz, lx, ICE);
                } else if (is_underwater) {
                    if (surf_n > 0.2) set_block(si, lz, lx, CLAY);
                    else if (surf_n > -0.2) set_block(si, lz, lx, SAND);
                    else set_block(si, lz, lx, GRAVEL);
                    for (int d = 1; d < 3; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, DIRT);
                    }
                } else {
                    set_block(si, lz, lx, GRASS_BLOCK);
                    int dirt_depth = 3 + (int)(std::fabs(surf_n) * 2.0);
                    for (int d = 1; d <= dirt_depth; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, DIRT);
                    }
                }

                // 深层过渡
                int wy_start = std::max(0, MIN_Y + 5);
                for (int wy = wy_start; wy < 8; wy++) {
                    int yi = wy - MIN_Y;
                    if (yi < WORLD_HEIGHT && get_block(yi, lz, lx) == STONE) {
                        if (wy < 0) {
                            set_block(yi, lz, lx, DEEPSLATE);
                        } else if (block_hash(wx, wy, wz) < 0.5) {
                            set_block(yi, lz, lx, DEEPSLATE);
                        }
                    }
                }
            }
        }
    }

    void place_stone_variants(int* blocks, int base_x, int base_z) const {
        SimpleRNG rng;
        rng.seed(seed ^ ((int64_t)base_x * 341873128712LL + (int64_t)base_z * 132897987541LL));

        struct Variant { int block_id; int count; };
        Variant variants[] = {
            {GRANITE, 80}, {DIORITE, 80}, {ANDESITE, 80}, {TUFF, 40}
        };

        for (auto& v : variants) {
            for (int i = 0; i < v.count; i++) {
                int lx = rng.randint(0, 15);
                int ly_rel = rng.randint(0, 200);
                int lz = rng.randint(0, 15);

                if (v.block_id == TUFF && ly_rel > 64) continue;

                int yi = ly_rel;  // MIN_Y + ly_rel - MIN_Y
                if (yi < 0 || yi >= WORLD_HEIGHT) continue;

                int cur = blocks[yi * 256 + lz * 16 + lx];
                if (cur == STONE || cur == DEEPSLATE) {
                    blocks[yi * 256 + lz * 16 + lx] = v.block_id;

                    for (int dx = -1; dx <= 1; dx++) {
                        for (int dy = -1; dy <= 1; dy++) {
                            for (int dz = -1; dz <= 1; dz++) {
                                if (rng.random_double() < 0.4) {
                                    int nx = lx + dx, ny = yi + dy, nz = lz + dz;
                                    if (nx >= 0 && nx < 16 && nz >= 0 && nz < 16 &&
                                        ny >= 0 && ny < WORLD_HEIGHT) {
                                        int c = blocks[ny * 256 + nz * 16 + nx];
                                        if (c == STONE || c == DEEPSLATE)
                                            blocks[ny * 256 + nz * 16 + nx] = v.block_id;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    void place_ores(int* blocks, int base_x, int base_z) const {
        SimpleRNG rng;
        rng.seed(seed ^ ((int64_t)base_x * 6364136223846793005LL
                       + (int64_t)base_z * 1442695040888963407LL));

        struct OreConfig {
            int ore, deep_ore, attempts, vein_size, y_min, y_max, best_y;
        };
        OreConfig ores[] = {
            {COAL_ORE, DEEPSLATE_COAL_ORE, 20, 10, 0, 256, 96},
            {IRON_ORE, DEEPSLATE_IRON_ORE, 20, 8, -64, 256, 16},
            {COPPER_ORE, DEEPSLATE_COPPER_ORE, 16, 9, -16, 112, 48},
            {GOLD_ORE, DEEPSLATE_GOLD_ORE, 4, 7, -64, 32, -16},
            {REDSTONE_ORE, DEEPSLATE_REDSTONE_ORE, 8, 6, -64, 16, -32},
            {LAPIS_ORE, DEEPSLATE_LAPIS_ORE, 2, 5, -64, 64, 0},
            {DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE, 2, 4, -64, 16, -60},
            {EMERALD_ORE, DEEPSLATE_EMERALD_ORE, 1, 2, -16, 256, 100},
        };

        for (auto& o : ores) {
            for (int a = 0; a < o.attempts; a++) {
                int lx = rng.randint(0, 15);
                int lz = rng.randint(0, 15);
                int wy = (int)rng.triangular((double)o.y_min, (double)o.y_max, (double)o.best_y);
                int yi = wy - MIN_Y;

                if (yi < 0 || yi >= WORLD_HEIGHT) continue;

                int target = blocks[yi * 256 + lz * 16 + lx];
                int ore_block;
                if (target == STONE) ore_block = o.ore;
                else if (target == DEEPSLATE) ore_block = o.deep_ore;
                else continue;

                blocks[yi * 256 + lz * 16 + lx] = ore_block;
                for (int v = 0; v < o.vein_size - 1; v++) {
                    int dx = rng.randint(-1, 1);
                    int dy = rng.randint(-1, 1);
                    int dz = rng.randint(-1, 1);
                    int nx = lx + dx, ny = yi + dy, nz = lz + dz;
                    if (nx >= 0 && nx < 16 && nz >= 0 && nz < 16 &&
                        ny >= 0 && ny < WORLD_HEIGHT) {
                        int c = blocks[ny * 256 + nz * 16 + nx];
                        if (c == STONE) blocks[ny * 256 + nz * 16 + nx] = o.ore;
                        else if (c == DEEPSLATE) blocks[ny * 256 + nz * 16 + nx] = o.deep_ore;
                    }
                }
            }
        }
    }
};

// ============================================================
// 二进制 I/O 辅助函数
// ============================================================

// 从 stdin 精确读取 n 字节，返回是否成功
static bool read_exact(void* buf, size_t n) {
    uint8_t* p = (uint8_t*)buf;
    while (n > 0) {
        size_t r = fread(p, 1, n, stdin);
        if (r == 0) return false;  // EOF 或错误
        p += r;
        n -= r;
    }
    return true;
}

// 向 stdout 精确写入 n 字节
static bool write_exact(const void* buf, size_t n) {
    const uint8_t* p = (const uint8_t*)buf;
    while (n > 0) {
        size_t w = fwrite(p, 1, n, stdout);
        if (w == 0) return false;
        p += w;
        n -= w;
    }
    return true;
}

// ============================================================
// 响应常量
// ============================================================
// 方块数据: 98304 个 uint16 = 196608 字节
// 高度图:   256 个 int16   = 512 字节
// 总数据:   197120 字节
static constexpr uint32_t BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16;  // 98304
static constexpr uint32_t BLOCKS_BYTES = BLOCKS_COUNT * 2;        // 196608
static constexpr uint32_t HEIGHTMAP_COUNT = 256;
static constexpr uint32_t HEIGHTMAP_BYTES = HEIGHTMAP_COUNT * 2;  // 512
static constexpr uint32_t PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES;  // 197120

struct ChunkResponse {
    std::vector<uint16_t> blocks;
    std::array<int16_t, HEIGHTMAP_COUNT> heightmap;

    ChunkResponse() : blocks(BLOCKS_COUNT, 0) {
        heightmap.fill(0);
    }
};

struct ChunkCoord {
    int32_t chunk_x;
    int32_t chunk_z;
};

// ============================================================
// 主循环: 从 stdin 读取二进制请求，生成地形，写入二进制响应
// ============================================================
int main(int argc, char** argv) {
#ifdef _WIN32
    // Windows: 将 stdin/stdout 设为二进制模式，避免 \n -> \r\n 转换
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    // 禁用缓冲以确保即时通信
    setvbuf(stdin, nullptr, _IONBF, 0);
    setvbuf(stdout, nullptr, _IONBF, 0);

    int thread_count = (int)std::thread::hardware_concurrency();
    if (thread_count <= 0) thread_count = 4;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--threads") == 0 && i + 1 < argc) {
            thread_count = std::max(1, std::atoi(argv[i + 1]));
            i++;
        }
    }

    // 当前种子和生成器缓存
    int64_t current_seed = -1;
    TerrainGenerator gen;

    // 方块数据缓冲区
    static int blocks[BLOCKS_COUNT];

    // 二进制响应缓冲区 (4字节长度头 + 数据)
    static uint8_t response_buf[4 + PAYLOAD_SIZE];

    // 写入固定的长度头
    uint32_t payload_size_le = PAYLOAD_SIZE;
    memcpy(response_buf, &payload_size_le, 4);

    while (true) {
        uint8_t command = 0;
        if (!read_exact(&command, 1)) {
            break;
        }

        if (command == 'C') {
            uint8_t request_buf[16];
            if (!read_exact(request_buf, 16)) break;

            int32_t chunk_x, chunk_z;
            int64_t seed;
            memcpy(&chunk_x, request_buf + 0, 4);
            memcpy(&chunk_z, request_buf + 4, 4);
            memcpy(&seed,    request_buf + 8, 8);

            if (seed != current_seed) {
                gen.init(seed);
                current_seed = seed;
            }

            int16_t* heightmap_out = (int16_t*)(response_buf + 4 + BLOCKS_BYTES);
            gen.generate_chunk(chunk_x, chunk_z, blocks, heightmap_out);

            uint16_t* blocks_out = (uint16_t*)(response_buf + 4);
            for (uint32_t i = 0; i < BLOCKS_COUNT; i++) {
                blocks_out[i] = (uint16_t)blocks[i];
            }

            if (!write_exact(response_buf, 4 + PAYLOAD_SIZE)) break;
            fflush(stdout);
            continue;
        }

        if (command != 'B') {
            break;
        }

        int64_t seed = 0;
        uint32_t chunk_count = 0;
        if (!read_exact(&seed, sizeof(seed))) break;
        if (!read_exact(&chunk_count, sizeof(chunk_count))) break;

        if (seed != current_seed) {
            gen.init(seed);
            current_seed = seed;
        }

        if (chunk_count == 0) {
            uint32_t zero = 0;
            if (!write_exact(&zero, sizeof(zero))) break;
            fflush(stdout);
            continue;
        }

        std::vector<ChunkCoord> coords(chunk_count);
        if (!read_exact(coords.data(), chunk_count * sizeof(coords[0]))) break;

        std::vector<ChunkResponse> results(chunk_count);
        unsigned worker_count = std::min<unsigned>((unsigned)thread_count, chunk_count);
        if (worker_count == 0) worker_count = 1;
        std::atomic<uint32_t> next_index(0);
        std::vector<std::thread> workers;
        workers.reserve(worker_count);

        for (unsigned worker = 0; worker < worker_count; worker++) {
            workers.emplace_back([&]() {
                std::vector<int> local_blocks(BLOCKS_COUNT);
                while (true) {
                    uint32_t idx = next_index.fetch_add(1);
                    if (idx >= chunk_count) break;
                    int32_t chunk_x = coords[idx].chunk_x;
                    int32_t chunk_z = coords[idx].chunk_z;
                    gen.generate_chunk(
                        chunk_x,
                        chunk_z,
                        local_blocks.data(),
                        results[idx].heightmap.data()
                    );
                    for (uint32_t i = 0; i < BLOCKS_COUNT; i++) {
                        results[idx].blocks[i] = (uint16_t)local_blocks[i];
                    }
                }
            });
        }

        for (auto& worker : workers) {
            worker.join();
        }

        if (!write_exact(&chunk_count, sizeof(chunk_count))) break;
        for (uint32_t idx = 0; idx < chunk_count; idx++) {
            if (!write_exact(results[idx].blocks.data(), BLOCKS_BYTES)) {
                chunk_count = 0;
                break;
            }
            if (!write_exact(results[idx].heightmap.data(), HEIGHTMAP_BYTES)) {
                chunk_count = 0;
                break;
            }
        }
        if (chunk_count == 0) break;
        fflush(stdout);
    }

    return 0;
}
