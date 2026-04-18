// ============================================================
// PyMC - C++ 高性能地形生成器
// 通过 stdin/stdout 二进制协议通信，作为 Python 服务端的子进程
// 协议:
//   请求: 16 字节 (小端)
//     [0:4]   int32  chunk_x
//     [4:8]   int32  chunk_z
//     [8:16]  int64  seed
//   响应: 197120 字节 (小端)
//     [0:4]      uint32  数据长度 (固定 197116)
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
static constexpr int SEA_LEVEL = 62;
static constexpr int DENSITY_MARGIN = 8;

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

// ============================================================
// 地形生成器
// ============================================================
struct TerrainGenerator {
    int64_t seed;
    OctaveNoise continental_noise;
    OctaveNoise erosion_noise;
    OctaveNoise peaks_noise;
    OctaveNoise density_noise;
    OctaveNoise detail_noise;
    OctaveNoise surface_noise;
    OctaveNoise temperature_noise;

    void init(int64_t s) {
        seed = s;
        continental_noise.init(s + 1, 3, 0.5, 2.0);
        erosion_noise.init(s + 2, 3, 0.45, 2.0);
        peaks_noise.init(s + 3, 3, 0.5, 2.0);
        density_noise.init(s + 4, 2, 0.5, 2.0);
        detail_noise.init(s + 5, 2, 0.6, 2.0);
        surface_noise.init(s + 6, 2, 0.5, 2.0);
        temperature_noise.init(s + 7, 2, 0.5, 2.0);
    }

    double block_hash(int x, int y, int z) const {
        int64_t n = (int64_t)x * 374761393LL + (int64_t)y * 668265263LL
                  + (int64_t)z * 1274126177LL + seed;
        n = (n ^ (n >> 13)) * 1103515245LL;
        n = n ^ (n >> 16);
        return (double)(n & 0x7FFFFFFF) / (double)0x7FFFFFFF;
    }

    int get_terrain_height(int wx, int wz) const {
        double nx = wx / 512.0;
        double nz = wz / 512.0;

        double continental = continental_noise.sample(nx, nz);
        double erosion = erosion_noise.sample(wx / 256.0, wz / 256.0);
        double peaks = peaks_noise.sample(wx / 128.0, wz / 128.0);
        double ridge = 1.0 - std::fabs(peaks);
        double detail = detail_noise.sample(wx / 16.0, wz / 16.0);

        double base_height;
        if (continental > 0)
            base_height = SEA_LEVEL + continental * 40.0;
        else
            base_height = SEA_LEVEL + continental * 30.0;

        double roughness = std::max(0.0, 1.0 - (erosion + 1.0) * 0.5);
        double peak_contribution = ridge * roughness * 60.0;
        double height = base_height + peak_contribution + detail * 4.0;

        height = std::max((double)(MIN_Y + 5), std::min((double)(MAX_Y - 10), height));
        return (int)height;
    }

    double get_density(int wx, int wy, int wz, int surface_height) const {
        double base_density = (surface_height - wy) / 8.0;
        double d3d = density_noise.sample_3d(wx / 64.0, wy / 64.0, wz / 64.0);
        return base_density + d3d * 2.0;
    }

    // 主生成函数: 生成 384*16*16 的方块数据
    // blocks[y][z][x] => blocks[y * 256 + z * 16 + x]
    void generate_chunk(int chunk_x, int chunk_z, int* blocks) const {
        const int total = WORLD_HEIGHT * 16 * 16;
        memset(blocks, 0, total * sizeof(int));  // 全 AIR

        int base_x = chunk_x * 16;
        int base_z = chunk_z * 16;

        // 高度图
        int height_map[16][16];

        // --- 第一步: 基础地形 ---
        for (int lx = 0; lx < 16; lx++) {
            for (int lz = 0; lz < 16; lz++) {
                int wx = base_x + lx;
                int wz = base_z + lz;
                int surface_h = get_terrain_height(wx, wz);
                height_map[lz][lx] = surface_h;
                int si = surface_h - MIN_Y;

                // 基岩层
                blocks[0 * 256 + lz * 16 + lx] = BEDROCK;
                for (int byi = 1; byi < 5; byi++) {
                    double rv = block_hash(wx, MIN_Y + byi, wz);
                    int idx = byi * 256 + lz * 16 + lx;
                    if (rv < (5 - byi) * 0.2) {
                        blocks[idx] = BEDROCK;
                    } else if (MIN_Y + byi < 0) {
                        blocks[idx] = DEEPSLATE;
                    } else {
                        blocks[idx] = STONE;
                    }
                }

                // 基岩以上 -> 密度采样区域以下: 直接固体
                int density_bottom_yi = std::max(5, si - DENSITY_MARGIN);
                for (int yi = 5; yi < density_bottom_yi; yi++) {
                    int wy = MIN_Y + yi;
                    blocks[yi * 256 + lz * 16 + lx] = (wy < 0) ? DEEPSLATE : STONE;
                }

                // 密度采样区域
                int density_top_yi = std::min(WORLD_HEIGHT, si + DENSITY_MARGIN);
                for (int yi = density_bottom_yi; yi < density_top_yi; yi++) {
                    int wy = MIN_Y + yi;
                    double density = get_density(wx, wy, wz, surface_h);
                    int idx = yi * 256 + lz * 16 + lx;
                    if (density > 0) {
                        blocks[idx] = (wy < 0) ? DEEPSLATE : STONE;
                    } else {
                        if (wy <= SEA_LEVEL && surface_h < SEA_LEVEL) {
                            blocks[idx] = WATER;
                        }
                    }
                }

                // 海平面填水
                if (surface_h < SEA_LEVEL) {
                    int sea_yi = SEA_LEVEL - MIN_Y;
                    for (int yi = density_top_yi; yi <= std::min(sea_yi, WORLD_HEIGHT - 1); yi++) {
                        int idx = yi * 256 + lz * 16 + lx;
                        if (blocks[idx] == AIR) blocks[idx] = WATER;
                    }
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

// ============================================================
// 主循环: 从 stdin 读取二进制请求，生成地形，写入二进制响应
// ============================================================
int main() {
#ifdef _WIN32
    // Windows: 将 stdin/stdout 设为二进制模式，避免 \n -> \r\n 转换
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    // 禁用缓冲以确保即时通信
    setvbuf(stdin, nullptr, _IONBF, 0);
    setvbuf(stdout, nullptr, _IONBF, 0);

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

    // 请求缓冲区: 16 字节 (int32 + int32 + int64)
    uint8_t request_buf[16];

    while (read_exact(request_buf, 16)) {
        // 解析请求 (小端序, x86 原生字节序)
        int32_t chunk_x, chunk_z;
        int64_t seed;
        memcpy(&chunk_x, request_buf + 0, 4);
        memcpy(&chunk_z, request_buf + 4, 4);
        memcpy(&seed,    request_buf + 8, 8);

        // 种子变化时重新初始化
        if (seed != current_seed) {
            gen.init(seed);
            current_seed = seed;
        }

        // 生成区块
        gen.generate_chunk(chunk_x, chunk_z, blocks);

        // 将 int 方块数据转换为 uint16 并写入响应缓冲区
        uint16_t* blocks_out = (uint16_t*)(response_buf + 4);
        for (uint32_t i = 0; i < BLOCKS_COUNT; i++) {
            blocks_out[i] = (uint16_t)blocks[i];
        }

        // 计算高度图并写入响应缓冲区
        int16_t* heightmap_out = (int16_t*)(response_buf + 4 + BLOCKS_BYTES);
        int bx = chunk_x * 16, bz = chunk_z * 16;
        for (int lz = 0; lz < 16; lz++) {
            for (int lx = 0; lx < 16; lx++) {
                heightmap_out[lz * 16 + lx] = (int16_t)gen.get_terrain_height(bx + lx, bz + lz);
            }
        }

        // 一次性写出整个响应
        if (!write_exact(response_buf, 4 + PAYLOAD_SIZE)) {
            break;  // 写入失败，退出
        }
        fflush(stdout);
    }

    return 0;
}
