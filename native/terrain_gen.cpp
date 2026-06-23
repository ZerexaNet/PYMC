// ============================================================
// PyMC - C++ 高性能地形生成器
// 通过 stdin/stdout 二进制协议通信，作为 Python 服务端的子进程
// 协议:
//   请求: 16 字节 (小端)
//     [0:4]   int32  chunk_x
//     [4:8]   int32  chunk_z
//     [8:16]  int64  seed
//   响应: 200192 字节 (小端)
//     [0:4]      uint32  数据长度 (固定 200192)
//     [4:196612] uint16  方块数据 98304 个 (y*256+z*16+x 顺序)
//     [196612:197124] int16  高度图 256 个 (z*16+x 顺序)
//     [197124:200196] uint16 生物群系 1536 个 (section*64 + y*16 + z*4 + x)
// ============================================================

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <string>
#include <string_view>
#include <vector>
#include <algorithm>
#include <array>
#include <thread>
#include <atomic>
#include <utility>
#include <limits>
#include <initializer_list>
#include <memory>

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
static constexpr int COARSE_DIRT = 11;
static constexpr int PODZOL = 13;
static constexpr int BEDROCK = 79;
static constexpr int WATER = 80;
static constexpr int LAVA = 96;
static constexpr int SAND = 112;
static constexpr int RED_SAND = 117;
static constexpr int OAK_LOG = 131;
static constexpr int SPRUCE_LOG = 134;
static constexpr int BIRCH_LOG = 137;
static constexpr int JUNGLE_LOG = 140;
static constexpr int ACACIA_LOG = 143;
static constexpr int DARK_OAK_LOG = 149;
static constexpr int OAK_LEAVES = 264;
static constexpr int SPRUCE_LEAVES = 292;
static constexpr int BIRCH_LEAVES = 320;
static constexpr int JUNGLE_LEAVES = 348;
static constexpr int ACACIA_LEAVES = 376;
static constexpr int DARK_OAK_LEAVES = 432;
static constexpr int SANDSTONE = 535;
static constexpr int GRAVEL = 118;
static constexpr int WHITE_TERRACOTTA = 9356;
static constexpr int ORANGE_TERRACOTTA = 9357;
static constexpr int YELLOW_TERRACOTTA = 9360;
static constexpr int LIGHT_GRAY_TERRACOTTA = 9364;
static constexpr int BROWN_TERRACOTTA = 9368;
static constexpr int RED_TERRACOTTA = 9370;
static constexpr int TERRACOTTA = 10744;
static constexpr int RED_SANDSTONE = 11079;
static constexpr int SHORT_GRASS = 2005;
static constexpr int FERN = 2006;
static constexpr int DEAD_BUSH = 2007;
static constexpr int SEAGRASS = 2008;
static constexpr int DANDELION = 2075;
static constexpr int POPPY = 2077;
static constexpr int BROWN_MUSHROOM = 2089;
static constexpr int RED_MUSHROOM = 2090;
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
static constexpr int CACTUS = 5782;
static constexpr int CLAY = 5798;
static constexpr int SUGAR_CANE = 5799;
static constexpr int PUMPKIN = 6811;
static constexpr int MELON = 6812;
static constexpr int EMERALD_ORE = 7511;
static constexpr int DEEPSLATE_EMERALD_ORE = 7512;
static constexpr int LARGE_FERN = 10758;
static constexpr int KELP = 12760;
static constexpr int KELP_PLANT = 12786;
static constexpr int TUFF = 21081;
static constexpr int CALCITE = 22316;
static constexpr int POWDER_SNOW = 22318;
static constexpr int COPPER_ORE = 22942;
static constexpr int DEEPSLATE_COPPER_ORE = 22943;
static constexpr int RAW_IRON_BLOCK = 26558;
static constexpr int RAW_COPPER_BLOCK = 26559;
static constexpr int DEEPSLATE = 24905;
static constexpr int MOSS_BLOCK = 24843;

// ============================================================
// 世界常量
// ============================================================
static constexpr int MIN_Y = -64;
static constexpr int MAX_Y = 319;
static constexpr int WORLD_HEIGHT = 384;  // MAX_Y - MIN_Y + 1
static constexpr int NUM_SECTIONS = WORLD_HEIGHT / 16;
static constexpr int SEA_LEVEL = 63;
static constexpr int CELL_WIDTH = 4;       // NoiseSettings.create(-64, 384, 1, 2)
static constexpr int CELL_HEIGHT = 8;      // QuartPos.toBlock(noiseSizeVertical)
static constexpr int CELL_COUNT_XZ = 16 / CELL_WIDTH;
static constexpr int CELL_COUNT_Y = WORLD_HEIGHT / CELL_HEIGHT;
static constexpr double GLOBAL_OFFSET = -0.50375;
static constexpr double SURFACE_DENSITY_THRESHOLD = 1.5625;
static constexpr double CHEESE_NOISE_TARGET = -0.703125;
static constexpr double PI = 3.14159265358979323846;
static constexpr uint64_t GOLDEN_RATIO_64 = 0x9E3779B97F4A7C15ULL;
static constexpr uint64_t SILVER_RATIO_64 = 0x6A09E667F3BCC909ULL;

// Biome registry indices must match world/biomes.py registration order.
static constexpr uint16_t BIOME_BADLANDS = 0;
static constexpr uint16_t BIOME_BAMBOO_JUNGLE = 1;
static constexpr uint16_t BIOME_BEACH = 3;
static constexpr uint16_t BIOME_BIRCH_FOREST = 4;
static constexpr uint16_t BIOME_CHERRY_GROVE = 5;
static constexpr uint16_t BIOME_COLD_OCEAN = 6;
static constexpr uint16_t BIOME_DARK_FOREST = 8;
static constexpr uint16_t BIOME_DEEP_COLD_OCEAN = 9;
static constexpr uint16_t BIOME_DEEP_DARK = 10;
static constexpr uint16_t BIOME_DEEP_FROZEN_OCEAN = 11;
static constexpr uint16_t BIOME_DEEP_LUKEWARM_OCEAN = 12;
static constexpr uint16_t BIOME_DEEP_OCEAN = 13;
static constexpr uint16_t BIOME_DESERT = 14;
static constexpr uint16_t BIOME_DRIPSTONE_CAVES = 15;
static constexpr uint16_t BIOME_ERODED_BADLANDS = 19;
static constexpr uint16_t BIOME_FLOWER_FOREST = 20;
static constexpr uint16_t BIOME_FOREST = 21;
static constexpr uint16_t BIOME_FROZEN_OCEAN = 22;
static constexpr uint16_t BIOME_FROZEN_PEAKS = 23;
static constexpr uint16_t BIOME_FROZEN_RIVER = 24;
static constexpr uint16_t BIOME_GROVE = 25;
static constexpr uint16_t BIOME_ICE_SPIKES = 26;
static constexpr uint16_t BIOME_JAGGED_PEAKS = 27;
static constexpr uint16_t BIOME_JUNGLE = 28;
static constexpr uint16_t BIOME_LUKEWARM_OCEAN = 29;
static constexpr uint16_t BIOME_LUSH_CAVES = 30;
static constexpr uint16_t BIOME_MANGROVE_SWAMP = 31;
static constexpr uint16_t BIOME_MEADOW = 32;
static constexpr uint16_t BIOME_MUSHROOM_FIELDS = 33;
static constexpr uint16_t BIOME_OCEAN = 35;
static constexpr uint16_t BIOME_OLD_GROWTH_BIRCH_FOREST = 36;
static constexpr uint16_t BIOME_OLD_GROWTH_PINE_TAIGA = 37;
static constexpr uint16_t BIOME_OLD_GROWTH_SPRUCE_TAIGA = 38;
static constexpr uint16_t BIOME_PLAINS = 39;
static constexpr uint16_t BIOME_RIVER = 40;
static constexpr uint16_t BIOME_SAVANNA = 41;
static constexpr uint16_t BIOME_SAVANNA_PLATEAU = 42;
static constexpr uint16_t BIOME_SNOWY_BEACH = 44;
static constexpr uint16_t BIOME_SNOWY_PLAINS = 45;
static constexpr uint16_t BIOME_SNOWY_SLOPES = 46;
static constexpr uint16_t BIOME_SNOWY_TAIGA = 47;
static constexpr uint16_t BIOME_SPARSE_JUNGLE = 49;
static constexpr uint16_t BIOME_STONY_PEAKS = 50;
static constexpr uint16_t BIOME_STONY_SHORE = 51;
static constexpr uint16_t BIOME_SUNFLOWER_PLAINS = 52;
static constexpr uint16_t BIOME_SWAMP = 53;
static constexpr uint16_t BIOME_TAIGA = 54;
static constexpr uint16_t BIOME_WARM_OCEAN = 57;
static constexpr uint16_t BIOME_WINDSWEPT_FOREST = 59;
static constexpr uint16_t BIOME_WINDSWEPT_GRAVELLY_HILLS = 60;
static constexpr uint16_t BIOME_WINDSWEPT_HILLS = 61;
static constexpr uint16_t BIOME_WINDSWEPT_SAVANNA = 62;
static constexpr uint16_t BIOME_WOODED_BADLANDS = 63;

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

static inline uint64_t rotl64(uint64_t x, int k) {
    return (x << k) | (x >> (64 - k));
}

static inline uint64_t mix_stafford13(uint64_t x) {
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static inline std::pair<uint64_t, uint64_t> upgrade_seed_to_128(uint64_t seed) {
    uint64_t lo = seed ^ SILVER_RATIO_64;
    uint64_t hi = lo + GOLDEN_RATIO_64;
    return {mix_stafford13(lo), mix_stafford13(hi)};
}

static inline uint64_t fnv1a64(std::string_view s, uint64_t basis) {
    constexpr uint64_t prime = 1099511628211ULL;
    uint64_t h = basis;
    for (unsigned char c : s) {
        h ^= (uint64_t)c;
        h *= prime;
    }
    return h;
}

static inline std::pair<uint64_t, uint64_t> key_hash_128(std::string_view key, int octave = 0) {
    auto left_rotate = [](uint32_t x, uint32_t c) -> uint32_t {
        return (x << c) | (x >> (32 - c));
    };
    auto read_le32 = [](const uint8_t* p) -> uint32_t {
        return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
               ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
    };
    auto write_le64 = [](std::vector<uint8_t>& out, uint64_t v) {
        for (int i = 0; i < 8; i++) {
            out.push_back((uint8_t)((v >> (i * 8)) & 0xFF));
        }
    };

    static const uint32_t shifts[64] = {
        7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
        5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
        4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
        6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21
    };
    static const uint32_t table[64] = {
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
        0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
        0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
        0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
        0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa,
        0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
        0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
        0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
        0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
        0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05,
        0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
        0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039,
        0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
        0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391
    };

    std::string full_key = std::string(key) + ":octave_salt_" + std::to_string(octave);
    std::vector<uint8_t> msg(full_key.begin(), full_key.end());
    uint64_t bit_len = (uint64_t)msg.size() * 8ULL;
    msg.push_back(0x80);
    while ((msg.size() % 64) != 56) {
        msg.push_back(0);
    }
    write_le64(msg, bit_len);

    uint32_t a0 = 0x67452301;
    uint32_t b0 = 0xefcdab89;
    uint32_t c0 = 0x98badcfe;
    uint32_t d0 = 0x10325476;

    for (size_t offset = 0; offset < msg.size(); offset += 64) {
        uint32_t m[16];
        for (int i = 0; i < 16; i++) {
            m[i] = read_le32(&msg[offset + i * 4]);
        }

        uint32_t a = a0, b = b0, c = c0, d = d0;
        for (uint32_t i = 0; i < 64; i++) {
            uint32_t f, g;
            if (i < 16) {
                f = (b & c) | (~b & d);
                g = i;
            } else if (i < 32) {
                f = (d & b) | (~d & c);
                g = (5 * i + 1) & 15;
            } else if (i < 48) {
                f = b ^ c ^ d;
                g = (3 * i + 5) & 15;
            } else {
                f = c ^ (b | ~d);
                g = (7 * i) & 15;
            }
            uint32_t tmp = d;
            d = c;
            c = b;
            b = b + left_rotate(a + f + table[i] + m[g], shifts[i]);
            a = tmp;
        }
        a0 += a;
        b0 += b;
        c0 += c;
        d0 += d;
    }

    uint8_t digest[16] = {
        (uint8_t)(a0 & 0xFF), (uint8_t)((a0 >> 8) & 0xFF),
        (uint8_t)((a0 >> 16) & 0xFF), (uint8_t)((a0 >> 24) & 0xFF),
        (uint8_t)(b0 & 0xFF), (uint8_t)((b0 >> 8) & 0xFF),
        (uint8_t)((b0 >> 16) & 0xFF), (uint8_t)((b0 >> 24) & 0xFF),
        (uint8_t)(c0 & 0xFF), (uint8_t)((c0 >> 8) & 0xFF),
        (uint8_t)((c0 >> 16) & 0xFF), (uint8_t)((c0 >> 24) & 0xFF),
        (uint8_t)(d0 & 0xFF), (uint8_t)((d0 >> 8) & 0xFF),
        (uint8_t)((d0 >> 16) & 0xFF), (uint8_t)((d0 >> 24) & 0xFF),
    };
    uint64_t h0 = 0;
    uint64_t h1 = 0;
    for (int i = 0; i < 8; i++) {
        h0 = (h0 << 8) | digest[i];
        h1 = (h1 << 8) | digest[i + 8];
    }
    return {h0, h1};
}

// Xoroshiro128++ 风格随机源。原版 1.21.1 的 RandomSupport 会先把
// world seed 升级到 128-bit，再通过噪声 key 派生各个 NormalNoise/Perlin octave。
struct SimpleRNG {
    uint64_t seed_lo = GOLDEN_RATIO_64;
    uint64_t seed_hi = SILVER_RATIO_64;

    void seed(int64_t s) {
        auto [lo, hi] = upgrade_seed_to_128((uint64_t)s);
        seed_lo = lo;
        seed_hi = hi;
        if ((seed_lo | seed_hi) == 0ULL) {
            seed_lo = GOLDEN_RATIO_64;
            seed_hi = SILVER_RATIO_64;
        }
    }

    void seed_key(int64_t world_seed, std::string_view key, int octave = 0) {
        auto [lo, hi] = upgrade_seed_to_128((uint64_t)world_seed);
        auto [h0, h1] = key_hash_128(key, octave);
        seed_lo = lo ^ h0;
        seed_hi = hi ^ h1;
        if ((seed_lo | seed_hi) == 0ULL) {
            seed_lo = GOLDEN_RATIO_64;
            seed_hi = SILVER_RATIO_64;
        }
    }

    uint64_t next_u64() {
        const uint64_t s0 = seed_lo;
        uint64_t s1 = seed_hi;
        const uint64_t out = rotl64(s0 + s1, 17) + s0;
        s1 ^= s0;
        seed_lo = rotl64(s0, 49) ^ s1 ^ (s1 << 21);
        seed_hi = rotl64(s1, 28);
        return out;
    }

    uint32_t next_u32() {
        return (uint32_t)next_u64();
    }

    int randint(int lo, int hi) {
        if (lo >= hi) return lo;
        uint32_t bound = (uint32_t)(hi - lo + 1);
        uint64_t u = (uint64_t)next_u32();
        uint64_t m = u * (uint64_t)bound;
        uint64_t l = m & 0xFFFFFFFFULL;
        if (l < (uint64_t)bound) {
            const uint32_t threshold = (uint32_t)((0U - bound) % bound);
            while (l < threshold) {
                u = (uint64_t)next_u32();
                m = u * (uint64_t)bound;
                l = m & 0xFFFFFFFFULL;
            }
        }
        return lo + (int)(m >> 32);
    }

    double random_double() {
        return (double)(next_u64() >> 11) * (1.0 / 9007199254740992.0);
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
        for (int i = 0; i < 256; i++) {
            p[i] = i;
        }

        // Vanilla ImprovedNoise initializes p[i]=i and shuffles forward with the source RNG.
        for (int i = 0; i < 256; i++) {
            int j = i + rng.randint(0, 255 - i);
            std::swap(p[i], p[j]);
        }

        for (int i = 0; i < 256; i++) {
            perm[i] = p[i];
            perm[i + 256] = p[i];
        }
    }

    double noise(double x, double y, double z,
                 double y_scale = 0.0, double y_max = 0.0) const {
        x += x_offset;
        y += y_offset;
        z += z_offset;

        int xi = ((int)std::floor(x)) & 255;
        int yi = ((int)std::floor(y)) & 255;
        int zi = ((int)std::floor(z)) & 255;

        double xf = x - std::floor(x);
        double yf = y - std::floor(y);
        double zf = z - std::floor(z);
        double y_grad = yf;
        if (y_scale != 0.0) {
            double limit = (y_max >= 0.0 && y_max < yf) ? y_max : yf;
            y_grad = yf - std::floor(limit / y_scale + 1.0e-7) * y_scale;
        }

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
                lerp(u, grad(perm[aa],     xf,     y_grad,     zf),
                        grad(perm[ba],     xf-1.0, y_grad,     zf)),
                lerp(u, grad(perm[ab],     xf,     y_grad-1.0, zf),
                        grad(perm[bb],     xf-1.0, y_grad-1.0, zf))),
            lerp(v,
                lerp(u, grad(perm[aa+1],   xf,     y_grad,     zf-1.0),
                        grad(perm[ba+1],   xf-1.0, y_grad,     zf-1.0)),
                lerp(u, grad(perm[ab+1],   xf,     y_grad-1.0, zf-1.0),
                        grad(perm[bb+1],   xf-1.0, y_grad-1.0, zf-1.0))));
    }

    double noise2d(double x, double z) const {
        return noise(x, 0.0, z);
    }
};

struct NoiseParameters {
    int first_octave;
    std::vector<double> amplitudes;
};

struct VanillaPerlinNoise {
    std::vector<ImprovedNoise> levels;
    std::vector<bool> has_level;
    std::vector<double> amplitudes;
    int first_octave = 0;
    double lowest_freq_input_factor = 1.0;
    double lowest_freq_value_factor = 1.0;

    void init(int64_t seed_val, std::string_view noise_key,
              int first, const std::vector<double>& amps,
              std::string_view label) {
        first_octave = first;
        amplitudes = amps;
        int count = (int)amplitudes.size();
        levels.resize(count);
        has_level.assign(count, false);

        std::string base_key = std::string(noise_key) + ":" + std::string(label);
        for (int i = 0; i < count; i++) {
            if (amplitudes[i] == 0.0) {
                continue;
            }
            int octave = first_octave + i;
            SimpleRNG rng;
            rng.seed_key(seed_val, base_key + ":octave_" + std::to_string(octave), octave);
            levels[i].init(rng);
            has_level[i] = true;
        }

        int octave_shift = -first_octave;
        lowest_freq_input_factor = std::pow(2.0, -octave_shift);
        lowest_freq_value_factor =
            std::pow(2.0, count - 1) / (std::pow(2.0, count) - 1.0);
    }

    void init_legacy(int64_t seed_val, std::string_view noise_key,
                     int first, const std::vector<double>& amps) {
        first_octave = first;
        amplitudes = amps;
        int count = (int)amplitudes.size();
        levels.resize(count);
        has_level.assign(count, false);

        SimpleRNG rng;
        rng.seed_key(seed_val, noise_key, 0);
        int octave_shift = -first_octave;
        if (octave_shift >= 0 && octave_shift < count && amplitudes[octave_shift] != 0.0) {
            levels[octave_shift].init(rng);
            has_level[octave_shift] = true;
        }
        for (int i = octave_shift - 1; i >= 0; i--) {
            if (i < count && amplitudes[i] != 0.0) {
                levels[i].init(rng);
            } else {
                for (int skip = 0; skip < 262; skip++) {
                    rng.next_u32();
                }
            }
            if (i < count && amplitudes[i] != 0.0) {
                has_level[i] = true;
            }
        }

        lowest_freq_input_factor = std::pow(2.0, -octave_shift);
        lowest_freq_value_factor =
            std::pow(2.0, count - 1) / (std::pow(2.0, count) - 1.0);
    }

    static double wrap(double v) {
        constexpr double wrap_range = 33554432.0;
        return v - std::floor(v / wrap_range + 0.5) * wrap_range;
    }

    double get_value(double x, double y, double z) const {
        double value = 0.0;
        double freq = lowest_freq_input_factor;
        double amp = lowest_freq_value_factor;
        for (size_t i = 0; i < levels.size(); i++) {
            if (has_level[i]) {
                value += amplitudes[i] *
                         levels[i].noise(wrap(x * freq), wrap(y * freq), wrap(z * freq)) * amp;
            }
            freq *= 2.0;
            amp /= 2.0;
        }
        return value;
    }
};

struct VanillaNormalNoise {
    VanillaPerlinNoise first;
    VanillaPerlinNoise second;
    double value_factor = 1.0;

    void init(int64_t seed_val, std::string_view noise_key, const NoiseParameters& params) {
        first.init(seed_val, std::string(noise_key) + ":a",
                   params.first_octave, params.amplitudes, "first");
        second.init(seed_val, std::string(noise_key) + ":b",
                    params.first_octave, params.amplitudes, "second");

        int min_idx = std::numeric_limits<int>::max();
        int max_idx = std::numeric_limits<int>::min();
        for (int i = 0; i < (int)params.amplitudes.size(); i++) {
            if (params.amplitudes[i] == 0.0) {
                continue;
            }
            min_idx = std::min(min_idx, i);
            max_idx = std::max(max_idx, i);
        }
        if (min_idx == std::numeric_limits<int>::max()) {
            min_idx = 0;
            max_idx = 0;
        }
        double expected_deviation = 0.1 * (1.0 + 1.0 / (double)((max_idx - min_idx) + 1));
        value_factor = (1.0 / 6.0) / expected_deviation;
    }

    double get_value(double x, double y, double z) const {
        constexpr double input_factor = 1.0181268882175227;
        return (first.get_value(x, y, z) +
                second.get_value(x * input_factor, y * input_factor, z * input_factor)) *
               value_factor;
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

static inline int floor_div(int a, int b) {
    int q = a / b;
    int r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) {
        q--;
    }
    return q;
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

static inline double hermite(double t, double p0, double m0, double p1, double m1) {
    double t2 = t * t;
    double t3 = t2 * t;
    return (2.0 * t3 - 3.0 * t2 + 1.0) * p0 +
           (t3 - 2.0 * t2 + t) * m0 +
           (-2.0 * t3 + 3.0 * t2) * p1 +
           (t3 - t2) * m1;
}

static inline double spline_value(double x,
                                  std::initializer_list<std::pair<double, double>> points) {
    std::vector<std::pair<double, double>> p(points);
    if (p.empty()) return 0.0;
    if (x <= p.front().first) return p.front().second;
    if (x >= p.back().first) return p.back().second;
    for (size_t i = 0; i + 1 < p.size(); i++) {
        double x0 = p[i].first;
        double x1 = p[i + 1].first;
        if (x < x0 || x > x1) continue;
        double t = (x - x0) / (x1 - x0);
        double prev_slope = (i == 0)
            ? (p[i + 1].second - p[i].second) / (x1 - x0)
            : (p[i + 1].second - p[i - 1].second) / (p[i + 1].first - p[i - 1].first);
        double next_slope = (i + 2 >= p.size())
            ? (p[i + 1].second - p[i].second) / (x1 - x0)
            : (p[i + 2].second - p[i].second) / (p[i + 2].first - p[i].first);
        return hermite(t, p[i].second, prev_slope * (x1 - x0),
                       p[i + 1].second, next_slope * (x1 - x0));
    }
    return p.back().second;
}

static inline double ridge_spline(double pv,
                                  double base,
                                  double low,
                                  double mid,
                                  double high,
                                  double peak) {
    return spline_value(pv, {
        {-1.0, base},
        {-0.4, low},
        { 0.0, mid},
        { 0.4, high},
        { 1.0, peak},
    });
}

struct TerrainSample {
    double continental;
    double erosion;
    double ridges;
    double peaks_valleys;
};

enum class TerrainCoord {
    Continental,
    Erosion,
    Ridges,
    PeaksValleys,
};

struct TerrainSpline {
    struct Point {
        double location;
        std::shared_ptr<TerrainSpline> value;
        double derivative;
    };

    bool is_constant = true;
    double constant_value = 0.0;
    TerrainCoord coord = TerrainCoord::Continental;
    std::vector<Point> points;

    static std::shared_ptr<TerrainSpline> constant(double value) {
        auto spline = std::make_shared<TerrainSpline>();
        spline->is_constant = true;
        spline->constant_value = value;
        return spline;
    }

    static std::shared_ptr<TerrainSpline> multipoint(TerrainCoord c, std::vector<Point> pts) {
        auto spline = std::make_shared<TerrainSpline>();
        spline->is_constant = false;
        spline->coord = c;
        spline->points = std::move(pts);
        return spline;
    }

    static double coord_value(TerrainCoord c, const TerrainSample& sample) {
        switch (c) {
            case TerrainCoord::Continental: return sample.continental;
            case TerrainCoord::Erosion: return sample.erosion;
            case TerrainCoord::Ridges: return sample.ridges;
            case TerrainCoord::PeaksValleys: return sample.peaks_valleys;
        }
        return 0.0;
    }

    double apply(const TerrainSample& sample) const {
        if (is_constant) {
            return constant_value;
        }
        if (points.empty()) {
            return 0.0;
        }

        double x = coord_value(coord, sample);
        auto linear_extend = [&](size_t idx) {
            return points[idx].value->apply(sample) +
                   points[idx].derivative * (x - points[idx].location);
        };

        if (x < points.front().location) {
            return linear_extend(0);
        }
        size_t last = points.size() - 1;
        if (x >= points[last].location) {
            return linear_extend(last);
        }

        size_t i = 0;
        while (i + 1 < points.size() && x >= points[i + 1].location) {
            i++;
        }

        const Point& a = points[i];
        const Point& b = points[i + 1];
        double span = b.location - a.location;
        if (span == 0.0) {
            return a.value->apply(sample);
        }

        double t = (x - a.location) / span;
        double va = a.value->apply(sample);
        double vb = b.value->apply(sample);
        double da = a.derivative * span - (vb - va);
        double db = -b.derivative * span + (vb - va);
        return lerp(t, va, vb) + t * (1.0 - t) * lerp(t, da, db);
    }
};

struct TerrainSplineBuilder {
    TerrainCoord coord;
    std::vector<TerrainSpline::Point> points;

    explicit TerrainSplineBuilder(TerrainCoord c) : coord(c) {}

    TerrainSplineBuilder& add(double location, double value, double derivative = 0.0) {
        return add(location, TerrainSpline::constant(value), derivative);
    }

    TerrainSplineBuilder& add(double location, std::shared_ptr<TerrainSpline> value,
                              double derivative = 0.0) {
        points.push_back({location, std::move(value), derivative});
        return *this;
    }

    std::shared_ptr<TerrainSpline> build() {
        return TerrainSpline::multipoint(coord, std::move(points));
    }
};

static inline double terrain_calculate_slope(double v0, double v1,
                                             double x0, double x1) {
    return (v1 - v0) / (x1 - x0);
}

static inline double terrain_mountain_continentalness(double weirdness,
                                                      double continentalness,
                                                      double floor_point) {
    double scale = 1.0 - (1.0 - continentalness) * 0.5;
    double bias = 0.5 * (1.0 - continentalness);
    double shaped = (weirdness + 1.17) * 0.46082947 * scale - bias;
    return std::max(shaped, weirdness < floor_point ? -0.2222 : 0.0);
}

static inline double terrain_mountain_zero_point(double continentalness) {
    double scale = 1.0 - (1.0 - continentalness) * 0.5;
    double bias = 0.5 * (1.0 - continentalness);
    return bias / (0.46082947 * scale) - 1.17;
}

static std::shared_ptr<TerrainSpline> build_mountain_ridge_spline_with_points(
        TerrainCoord coord, double continentalness, bool force_plateau) {
    TerrainSplineBuilder b(coord);
    double y_neg1 = terrain_mountain_continentalness(-1.0, continentalness, -0.7);
    double y_pos1 = terrain_mountain_continentalness(1.0, continentalness, -0.7);
    double zero = terrain_mountain_zero_point(continentalness);
    if (-0.65 < zero && zero < 1.0) {
        double y_neg065 = terrain_mountain_continentalness(-0.65, continentalness, -0.7);
        double y_neg075 = terrain_mountain_continentalness(-0.75, continentalness, -0.7);
        double slope_left = terrain_calculate_slope(y_neg1, y_neg075, -1.0, -0.75);
        b.add(-1.0, y_neg1, slope_left);
        b.add(-0.75, y_neg075);
        b.add(-0.65, y_neg065);
        double y_zero = terrain_mountain_continentalness(zero, continentalness, -0.7);
        double slope_right = terrain_calculate_slope(y_zero, y_pos1, zero, 1.0);
        b.add(zero - 0.01, y_zero);
        b.add(zero, y_zero, slope_right);
        b.add(1.0, y_pos1, slope_right);
    } else {
        double slope = terrain_calculate_slope(y_neg1, y_pos1, -1.0, 1.0);
        if (force_plateau) {
            b.add(-1.0, std::max(0.2, y_neg1));
            b.add(0.0, lerp(0.5, y_neg1, y_pos1), slope);
        } else {
            b.add(-1.0, y_neg1, slope);
        }
        b.add(1.0, y_pos1, slope);
    }
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_ridge_spline(
        TerrainCoord coord, double base, double low, double mid,
        double high, double peak, double min_slope) {
    double slope0 = std::max(0.5 * (low - base), min_slope);
    double slope1 = 5.0 * (mid - low);
    TerrainSplineBuilder b(coord);
    b.add(-1.0, base, slope0);
    b.add(-0.4, low, std::min(slope0, slope1));
    b.add(0.0, mid, slope1);
    b.add(0.4, high, 2.0 * (high - mid));
    b.add(1.0, peak, 0.7 * (peak - high));
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_erosion_offset_spline(
        TerrainCoord erosion_coord, TerrainCoord pv_coord,
        double base, double low, double mid, double mountain,
        double valley, double plateau, bool has_plateau_window,
        bool force_plateau) {
    double mountain_high = lerp(mountain, 0.6, 1.5);
    double mountain_mid = lerp(mountain, 0.6, 1.0);
    auto s14 = build_mountain_ridge_spline_with_points(pv_coord, mountain_high, force_plateau);
    auto s15 = build_mountain_ridge_spline_with_points(pv_coord, mountain_mid, force_plateau);
    auto s16 = build_mountain_ridge_spline_with_points(pv_coord, mountain, force_plateau);
    auto s17 = build_ridge_spline(pv_coord, base - 0.15, 0.5 * mountain,
                                  0.5 * mountain, 0.5 * mountain,
                                  0.6 * mountain, 0.5);
    auto s18 = build_ridge_spline(pv_coord, base, valley * mountain,
                                  low * mountain, 0.5 * mountain,
                                  0.6 * mountain, 0.5);
    auto s19 = build_ridge_spline(pv_coord, base, valley, valley, low, mid, 0.5);
    auto s20 = build_ridge_spline(pv_coord, base, valley, valley, low, mid, 0.5);
    auto s21 = TerrainSplineBuilder(pv_coord)
        .add(-1.0, base)
        .add(-0.4, s19)
        .add(0.0, mid + 0.07)
        .build();
    auto s22 = build_ridge_spline(pv_coord, -0.02, plateau, plateau, low, mid, 0.0);

    TerrainSplineBuilder b(erosion_coord);
    b.add(-0.85, s14);
    b.add(-0.7, s15);
    b.add(-0.4, s16);
    b.add(-0.35, s17);
    b.add(-0.1, s18);
    b.add(0.2, s19);
    if (has_plateau_window) {
        b.add(0.4, s20);
        b.add(0.45, s21);
        b.add(0.55, s21);
        b.add(0.58, s20);
    }
    b.add(0.7, s22);
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_overworld_offset_spline() {
    auto s5 = build_erosion_offset_spline(TerrainCoord::Erosion, TerrainCoord::PeaksValleys,
                                          -0.15, 0.0, 0.0, 0.1, 0.0, -0.03, false, false);
    auto s6 = build_erosion_offset_spline(TerrainCoord::Erosion, TerrainCoord::PeaksValleys,
                                          -0.1, 0.03, 0.1, 0.1, 0.01, -0.03, false, false);
    auto s7 = build_erosion_offset_spline(TerrainCoord::Erosion, TerrainCoord::PeaksValleys,
                                          -0.1, 0.03, 0.1, 0.7, 0.01, -0.03, true, true);
    auto s8 = build_erosion_offset_spline(TerrainCoord::Erosion, TerrainCoord::PeaksValleys,
                                          -0.05, 0.03, 0.1, 1.0, 0.01, 0.01, true, true);
    TerrainSplineBuilder b(TerrainCoord::Continental);
    b.add(-1.1, 0.044);
    b.add(-1.02, -0.2222);
    b.add(-0.51, -0.2222);
    b.add(-0.44, -0.12);
    b.add(-0.18, -0.12);
    b.add(-0.16, s5);
    b.add(-0.15, s5);
    b.add(-0.1, s6);
    b.add(0.25, s7);
    b.add(1.0, s8);
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_erosion_factor_spline(
        double target, bool has_ridge_branch) {
    auto ridge_base = TerrainSplineBuilder(TerrainCoord::Ridges)
        .add(-0.2, 6.3)
        .add(0.2, target)
        .build();
    TerrainSplineBuilder erosion(TerrainCoord::Erosion);
    erosion.add(-0.6, ridge_base);
    erosion.add(-0.5, TerrainSplineBuilder(TerrainCoord::Ridges)
        .add(-0.05, 6.3)
        .add(0.05, 2.67)
        .build());
    erosion.add(-0.35, ridge_base);
    erosion.add(-0.25, ridge_base);
    erosion.add(-0.1, TerrainSplineBuilder(TerrainCoord::Ridges)
        .add(-0.05, 2.67)
        .add(0.05, 6.3)
        .build());
    erosion.add(0.03, ridge_base);
    if (has_ridge_branch) {
        auto gentle = TerrainSplineBuilder(TerrainCoord::Ridges)
            .add(0.0, target)
            .add(0.1, 0.625)
            .build();
        auto pv = TerrainSplineBuilder(TerrainCoord::PeaksValleys)
            .add(-0.9, target)
            .add(-0.69, gentle)
            .build();
        erosion.add(0.35, target);
        erosion.add(0.45, pv);
        erosion.add(0.55, pv);
        erosion.add(0.62, target);
    } else {
        auto low_pv = TerrainSplineBuilder(TerrainCoord::PeaksValleys)
            .add(-0.7, ridge_base)
            .add(-0.15, 1.37)
            .build();
        auto high_pv = TerrainSplineBuilder(TerrainCoord::PeaksValleys)
            .add(0.45, ridge_base)
            .add(0.7, 1.56)
            .build();
        erosion.add(0.05, high_pv);
        erosion.add(0.4, high_pv);
        erosion.add(0.45, low_pv);
        erosion.add(0.55, low_pv);
        erosion.add(0.58, target);
    }
    return erosion.build();
}

static std::shared_ptr<TerrainSpline> build_overworld_factor_spline() {
    TerrainSplineBuilder b(TerrainCoord::Continental);
    b.add(-0.19, 3.95);
    b.add(-0.15, build_erosion_factor_spline(6.25, true));
    b.add(-0.1, build_erosion_factor_spline(5.47, true));
    b.add(0.03, build_erosion_factor_spline(5.08, true));
    b.add(0.06, build_erosion_factor_spline(4.69, false));
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_weirdness_jaggedness_spline(double amount) {
    return TerrainSplineBuilder(TerrainCoord::Ridges)
        .add(-0.01, 0.63 * amount)
        .add(0.01, 0.3 * amount)
        .build();
}

static std::shared_ptr<TerrainSpline> build_ridge_jaggedness_spline(
        double high_amount, double mid_amount) {
    double pv0 = peaks_and_valleys(0.4);
    double pv1 = peaks_and_valleys(0.56666666);
    double middle = (pv0 + pv1) * 0.5;
    TerrainSplineBuilder b(TerrainCoord::PeaksValleys);
    b.add(pv0, 0.0);
    b.add(middle, mid_amount > 0.0 ? build_weirdness_jaggedness_spline(mid_amount)
                                   : TerrainSpline::constant(0.0));
    b.add(1.0, high_amount > 0.0 ? build_weirdness_jaggedness_spline(high_amount)
                                 : TerrainSpline::constant(0.0));
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_erosion_jaggedness_spline(
        double high_amount, double mid_amount,
        double high_mid_amount, double mid_mid_amount) {
    auto high = build_ridge_jaggedness_spline(high_amount, high_mid_amount);
    auto mid = build_ridge_jaggedness_spline(mid_amount, mid_mid_amount);
    TerrainSplineBuilder b(TerrainCoord::Erosion);
    b.add(-1.0, high);
    b.add(-0.78, mid);
    b.add(-0.5775, mid);
    b.add(-0.375, 0.0);
    return b.build();
}

static std::shared_ptr<TerrainSpline> build_overworld_jaggedness_spline() {
    TerrainSplineBuilder b(TerrainCoord::Continental);
    b.add(-0.11, 0.0);
    b.add(0.03, build_erosion_jaggedness_spline(1.0, 0.5, 0.0, 0.0));
    b.add(0.65, build_erosion_jaggedness_spline(1.0, 1.0, 1.0, 0.0));
    return b.build();
}

// ============================================================
// 地形生成器
// ============================================================
struct TerrainGenerator {
    int64_t seed;
    VanillaNormalNoise shift_vanilla;
    VanillaNormalNoise continental_vanilla;
    VanillaNormalNoise erosion_vanilla;
    VanillaNormalNoise ridge_vanilla;
    VanillaNormalNoise jagged_vanilla;
    VanillaNormalNoise cave_cheese_vanilla;
    VanillaNormalNoise cave_layer_vanilla;
    VanillaNormalNoise cave_entrance_vanilla;
    VanillaNormalNoise noodle_vanilla;
    VanillaNormalNoise noodle_thickness_vanilla;
    VanillaNormalNoise noodle_ridge_a_vanilla;
    VanillaNormalNoise noodle_ridge_b_vanilla;
    VanillaNormalNoise spaghetti_roughness_vanilla;
    VanillaNormalNoise spaghetti_roughness_modulator_vanilla;
    VanillaNormalNoise spaghetti_2d_vanilla;
    VanillaNormalNoise spaghetti_2d_elevation_vanilla;
    VanillaNormalNoise spaghetti_2d_modulator_vanilla;
    VanillaNormalNoise spaghetti_2d_thickness_vanilla;
    VanillaNormalNoise spaghetti_3d_1_vanilla;
    VanillaNormalNoise spaghetti_3d_2_vanilla;
    VanillaNormalNoise spaghetti_3d_rarity_vanilla;
    VanillaNormalNoise spaghetti_3d_thickness_vanilla;
    VanillaNormalNoise pillar_vanilla;
    VanillaNormalNoise pillar_rareness_vanilla;
    VanillaNormalNoise pillar_thickness_vanilla;
    VanillaNormalNoise ore_veininess_vanilla;
    VanillaNormalNoise ore_vein_a_vanilla;
    VanillaNormalNoise ore_vein_b_vanilla;
    VanillaNormalNoise ore_gap_vanilla;
    VanillaNormalNoise aquifer_floodedness_vanilla;
    VanillaNormalNoise aquifer_spread_vanilla;
    VanillaNormalNoise aquifer_lava_vanilla;
    VanillaPerlinNoise blended_min_limit_vanilla;
    VanillaPerlinNoise blended_max_limit_vanilla;
    VanillaPerlinNoise blended_main_vanilla;
    VanillaNormalNoise surface_vanilla;
    VanillaNormalNoise temperature_vanilla;
    VanillaNormalNoise humidity_vanilla;
    std::shared_ptr<TerrainSpline> offset_spline;
    std::shared_ptr<TerrainSpline> factor_spline;
    std::shared_ptr<TerrainSpline> jaggedness_spline;

    void init(int64_t s) {
        seed = s;
        if (!offset_spline) {
            offset_spline = build_overworld_offset_spline();
            factor_spline = build_overworld_factor_spline();
            jaggedness_spline = build_overworld_jaggedness_spline();
        }
        // Ported from 1.21.1 NoiseData: first octave + amplitude lists used by
        // NormalNoise. These are the authoritative seed/noise channels for
        // climate and density routing in this clean-room native path.
        shift_vanilla.init(s, "minecraft:shift", {-3, {1.0, 1.0, 1.0, 0.0}});
        temperature_vanilla.init(s, "minecraft:temperature", {-10, {1.5, 0.0, 1.0, 0.0, 0.0, 0.0}});
        humidity_vanilla.init(s, "minecraft:vegetation", {-8, {1.0, 1.0, 0.0, 0.0, 0.0, 0.0}});
        continental_vanilla.init(s, "minecraft:continentalness", {-9, {1.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0}});
        erosion_vanilla.init(s, "minecraft:erosion", {-9, {1.0, 1.0, 0.0, 1.0, 1.0}});
        ridge_vanilla.init(s, "minecraft:ridge", {-7, {1.0, 2.0, 1.0, 0.0, 0.0, 0.0}});
        jagged_vanilla.init(s, "minecraft:jagged", {-16, {
            1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
        }});
        cave_entrance_vanilla.init(s, "minecraft:cave_entrance", {-7, {0.4, 0.5, 1.0}});
        cave_layer_vanilla.init(s, "minecraft:cave_layer", {-8, {1.0}});
        cave_cheese_vanilla.init(s, "minecraft:cave_cheese", {-8, {0.5, 1.0, 2.0, 1.0, 2.0, 1.0, 0.0, 2.0, 0.0}});
        noodle_vanilla.init(s, "minecraft:noodle", {-8, {1.0}});
        noodle_thickness_vanilla.init(s, "minecraft:noodle_thickness", {-8, {1.0}});
        noodle_ridge_a_vanilla.init(s, "minecraft:noodle_ridge_a", {-7, {1.0}});
        noodle_ridge_b_vanilla.init(s, "minecraft:noodle_ridge_b", {-7, {1.0}});
        spaghetti_roughness_vanilla.init(s, "minecraft:spaghetti_roughness", {-5, {1.0}});
        spaghetti_roughness_modulator_vanilla.init(s, "minecraft:spaghetti_roughness_modulator", {-8, {1.0}});
        spaghetti_2d_vanilla.init(s, "minecraft:spaghetti_2d", {-7, {1.0}});
        spaghetti_2d_elevation_vanilla.init(s, "minecraft:spaghetti_2d_elevation", {-8, {1.0}});
        spaghetti_2d_modulator_vanilla.init(s, "minecraft:spaghetti_2d_modulator", {-11, {1.0}});
        spaghetti_2d_thickness_vanilla.init(s, "minecraft:spaghetti_2d_thickness", {-11, {1.0}});
        spaghetti_3d_1_vanilla.init(s, "minecraft:spaghetti_3d_1", {-7, {1.0}});
        spaghetti_3d_2_vanilla.init(s, "minecraft:spaghetti_3d_2", {-7, {1.0}});
        spaghetti_3d_rarity_vanilla.init(s, "minecraft:spaghetti_3d_rarity", {-11, {1.0}});
        spaghetti_3d_thickness_vanilla.init(s, "minecraft:spaghetti_3d_thickness", {-8, {1.0}});
        pillar_vanilla.init(s, "minecraft:pillar", {-7, {1.0, 1.0}});
        pillar_rareness_vanilla.init(s, "minecraft:pillar_rareness", {-8, {1.0}});
        pillar_thickness_vanilla.init(s, "minecraft:pillar_thickness", {-8, {1.0}});
        ore_veininess_vanilla.init(s, "minecraft:ore_veininess", {-8, {1.0}});
        ore_vein_a_vanilla.init(s, "minecraft:ore_vein_a", {-7, {1.0}});
        ore_vein_b_vanilla.init(s, "minecraft:ore_vein_b", {-7, {1.0}});
        ore_gap_vanilla.init(s, "minecraft:ore_gap", {-5, {1.0}});
        aquifer_floodedness_vanilla.init(s, "minecraft:aquifer_fluid_level_floodedness", {-7, {1.0}});
        aquifer_spread_vanilla.init(s, "minecraft:aquifer_fluid_level_spread", {-5, {1.0}});
        aquifer_lava_vanilla.init(s, "minecraft:aquifer_lava", {-1, {1.0}});
        blended_min_limit_vanilla.init_legacy(s, "minecraft:overworld/base_3d_noise/min_limit", -15, std::vector<double>(16, 1.0));
        blended_max_limit_vanilla.init_legacy(s, "minecraft:overworld/base_3d_noise/max_limit", -15, std::vector<double>(16, 1.0));
        blended_main_vanilla.init_legacy(s, "minecraft:overworld/base_3d_noise/main", -7, std::vector<double>(8, 1.0));
        surface_vanilla.init(s, "minecraft:surface", {-6, {1.0, 1.0, 1.0}});
    }

    double block_hash(int x, int y, int z) const {
        int64_t n = (int64_t)x * 374761393LL + (int64_t)y * 668265263LL
                  + (int64_t)z * 1274126177LL + seed;
        n = (n ^ (n >> 13)) * 1103515245LL;
        n = n ^ (n >> 16);
        return (double)(n & 0x7FFFFFFF) / (double)0x7FFFFFFF;
    }

    double position_chance(int x, int y, int z, uint64_t salt) const {
        uint64_t h = (uint64_t)seed ^ salt;
        h ^= mix_stafford13((uint64_t)(int64_t)x + 0x9E3779B97F4A7C15ULL);
        h ^= rotl64(mix_stafford13((uint64_t)(int64_t)y + 0x6A09E667F3BCC909ULL), 21);
        h ^= rotl64(mix_stafford13((uint64_t)(int64_t)z + 0xBB67AE8584CAA73BULL), 42);
        h = mix_stafford13(h);
        return (double)(h >> 11) * (1.0 / 9007199254740992.0);
    }

    double shift_a(int wx, int wz) const {
        return shift_vanilla.get_value((double)wx * 0.25, 0.0, (double)wz * 0.25) * 4.0;
    }

    double shift_b(int wx, int wz) const {
        return shift_vanilla.get_value((double)wz * 0.25, (double)wx * 0.25, 0.0) * 4.0;
    }

    TerrainSample sample_terrain(int wx, int wz) const {
        double sx = shift_a(wx, wz);
        double sz = shift_b(wx, wz);
        double x = wx + sx;
        double z = wz + sz;

        TerrainSample t{};
        t.continental = std::max(-1.2, std::min(1.2, continental_vanilla.get_value(x * 0.25, 0.0, z * 0.25)));
        t.erosion = std::max(-1.0, std::min(1.0, erosion_vanilla.get_value(x * 0.25, 0.0, z * 0.25)));
        t.ridges = std::max(-1.0, std::min(1.0, ridge_vanilla.get_value(x * 0.25, 0.0, z * 0.25)));
        t.peaks_valleys = peaks_and_valleys(t.ridges);
        return t;
    }

    double terrain_offset(const TerrainSample& t) const {
        return offset_spline ? offset_spline->apply(t) : 0.0;
    }

    double terrain_factor(const TerrainSample& t) const {
        return factor_spline ? factor_spline->apply(t) : 4.69;
    }

    double terrain_jaggedness(const TerrainSample& t) const {
        return jaggedness_spline ? jaggedness_spline->apply(t) : 0.0;
    }

    double blended_octave(const VanillaPerlinNoise& noise, int octave,
                          double x, double y, double z,
                          double y_scale, double y_max) const {
        int idx = (int)noise.levels.size() - 1 - octave;
        if (idx < 0 || idx >= (int)noise.levels.size() || !noise.has_level[idx]) {
            return 0.0;
        }
        return noise.levels[idx].noise(VanillaPerlinNoise::wrap(x),
                                       VanillaPerlinNoise::wrap(y),
                                       VanillaPerlinNoise::wrap(z),
                                       y_scale,
                                       y_max);
    }

    double blended_base_noise(int wx, int wy, int wz) const {
        constexpr double xz_scale = 0.25;
        constexpr double y_scale = 0.125;
        constexpr double xz_factor = 80.0;
        constexpr double y_factor = 160.0;
        constexpr double smear_scale_multiplier = 8.0;

        double xz_multiplier = 684.412 * xz_scale;
        double y_multiplier = 684.412 * y_scale;
        double x = (double)wx * xz_multiplier;
        double y = (double)wy * y_multiplier;
        double z = (double)wz * xz_multiplier;
        double main_x = x / xz_factor;
        double main_y = y / y_factor;
        double main_z = z / xz_factor;
        double smear = y_multiplier * smear_scale_multiplier;
        double main_smear = smear / y_factor;

        double main = 0.0;
        double freq = 1.0;
        for (int octave = 0; octave < 8; octave++) {
            main += blended_octave(blended_main_vanilla, octave,
                                   main_x * freq, main_y * freq, main_z * freq,
                                   main_smear * freq, main_y * freq) / freq;
            freq /= 2.0;
        }

        double selector = (main / 10.0 + 1.0) * 0.5;
        bool use_max_only = selector >= 1.0;
        bool use_min_only = selector <= 0.0;
        double min_limit = 0.0;
        double max_limit = 0.0;
        freq = 1.0;
        for (int octave = 0; octave < 16; octave++) {
            double nx = x * freq;
            double ny = y * freq;
            double nz = z * freq;
            double y_smear = smear * freq;
            if (!use_max_only) {
                min_limit += blended_octave(blended_min_limit_vanilla, octave,
                                            nx, ny, nz, y_smear, y * freq) / freq;
            }
            if (!use_min_only) {
                max_limit += blended_octave(blended_max_limit_vanilla, octave,
                                            nx, ny, nz, y_smear, y * freq) / freq;
            }
            freq /= 2.0;
        }
        return clamped_lerp(min_limit / 512.0, max_limit / 512.0, selector) / 128.0;
    }

    double slide_overworld(double density, int wy) const {
        double top = y_clamped_gradient(wy, 240.0, 256.0, 1.0, 0.0);
        density = lerp(top, -0.078125, density);
        double bottom = y_clamped_gradient(wy, -64.0, -40.0, 0.0, 1.0);
        density = lerp(bottom, 0.1171875, density);
        return density;
    }

    static double map_from_unit(double v, double min_value, double max_value) {
        return (min_value + max_value) * 0.5 + (max_value - min_value) * 0.5 * v;
    }

    double noise3(const VanillaNormalNoise& noise, int wx, int wy, int wz,
                  double xz_scale = 1.0, double y_scale = 1.0) const {
        return noise.get_value((double)wx * xz_scale,
                               (double)wy * y_scale,
                               (double)wz * xz_scale);
    }

    double mapped_noise3(const VanillaNormalNoise& noise, int wx, int wy, int wz,
                         double xz_scale, double y_scale,
                         double min_value, double max_value) const {
        return map_from_unit(noise3(noise, wx, wy, wz, xz_scale, y_scale),
                             min_value, max_value);
    }

    static double spaghetti_rarity_2d(double v) {
        if (v < -0.75) return 0.5;
        if (v < -0.5) return 0.75;
        if (v < 0.5) return 1.0;
        if (v < 0.75) return 2.0;
        return 3.0;
    }

    static double spaghetti_rarity_3d(double v) {
        if (v < -0.5) return 0.75;
        if (v < 0.0) return 1.0;
        if (v < 0.5) return 1.5;
        return 2.0;
    }

    double weird_scaled_sampler(const VanillaNormalNoise& noise,
                                double rarity, int wx, int wy, int wz) const {
        return rarity * std::fabs(noise.get_value((double)wx / rarity,
                                                  (double)wy / rarity,
                                                  (double)wz / rarity));
    }

    double spaghetti_roughness(int wx, int wy, int wz) const {
        double rough = std::fabs(noise3(spaghetti_roughness_vanilla, wx, wy, wz)) - 0.4;
        double mod = mapped_noise3(spaghetti_roughness_modulator_vanilla,
                                   wx, wy, wz, 1.0, 1.0, 0.0, -0.1);
        return mod * rough;
    }

    double cave_entrances(int wx, int wy, int wz) const {
        double rarity_raw = noise3(spaghetti_3d_rarity_vanilla, wx, wy, wz, 2.0, 1.0);
        double rarity = spaghetti_rarity_3d(rarity_raw);
        double thickness = mapped_noise3(spaghetti_3d_thickness_vanilla,
                                         wx, wy, wz, 1.0, 1.0, -0.065, -0.088);
        double spaghetti = std::max(
            weird_scaled_sampler(spaghetti_3d_1_vanilla, rarity, wx, wy, wz),
            weird_scaled_sampler(spaghetti_3d_2_vanilla, rarity, wx, wy, wz)
        );
        spaghetti = std::max(-1.0, std::min(1.0, spaghetti + thickness));

        double entrance = noise3(cave_entrance_vanilla, wx, wy, wz, 0.75, 0.5) +
                          0.37 + y_clamped_gradient(wy, -10.0, 30.0, 0.3, 0.0);
        return std::min(entrance, spaghetti + spaghetti_roughness(wx, wy, wz));
    }

    double spaghetti_2d(int wx, int wy, int wz) const {
        double mod = noise3(spaghetti_2d_modulator_vanilla, wx, wy, wz, 2.0, 1.0);
        double rarity = spaghetti_rarity_2d(mod);
        double spaghetti = weird_scaled_sampler(spaghetti_2d_vanilla, rarity, wx, wy, wz);
        double elevation = mapped_noise3(spaghetti_2d_elevation_vanilla,
                                         wx, wy, wz, 1.0, 1.0, -8.0, 8.0);
        double thickness = mapped_noise3(spaghetti_2d_thickness_vanilla,
                                         wx, wy, wz, 2.0, 1.0, -0.6, -1.3);
        double vertical = std::fabs(elevation + y_clamped_gradient(wy, -64.0, 320.0, 8.0, -40.0));
        double floor = std::pow(vertical + thickness, 3.0);
        double line = spaghetti + 0.083 * thickness;
        return std::max(-1.0, std::min(1.0, std::max(line, floor)));
    }

    double pillars(int wx, int wy, int wz) const {
        double pillar = noise3(pillar_vanilla, wx, wy, wz, 25.0, 0.3);
        double rareness = mapped_noise3(pillar_rareness_vanilla, wx, wy, wz,
                                        1.0, 1.0, 0.0, -2.0);
        double thickness = mapped_noise3(pillar_thickness_vanilla, wx, wy, wz,
                                         1.0, 1.0, 0.0, 1.1);
        return (pillar * 2.0 + rareness) * thickness * thickness * thickness;
    }

    double noodle_density(int wx, int wy, int wz) const {
        if (wy < -60 || wy > 320) {
            return 64.0;
        }
        double gate = noise3(noodle_vanilla, wx, wy, wz, 1.0, 1.0);
        if (gate < 0.0) {
            return 64.0;
        }
        double thickness = mapped_noise3(noodle_thickness_vanilla,
                                         wx, wy, wz, 1.0, 1.0, -0.05, -0.1);
        double ridge_a = std::fabs(noise3(noodle_ridge_a_vanilla, wx, wy, wz,
                                          2.6666666667, 2.6666666667));
        double ridge_b = std::fabs(noise3(noodle_ridge_b_vanilla, wx, wy, wz,
                                          2.6666666667, 2.6666666667));
        return thickness + 1.5 * std::max(ridge_a, ridge_b);
    }

    int aquifer_fluid_block(int wx, int wy, int wz) const {
        if (wy < -54) {
            return LAVA;
        }

        double lava = aquifer_lava_vanilla.get_value((double)floor_div(wx, 64),
                                                     (double)floor_div(wy, 40),
                                                     (double)floor_div(wz, 64));
        if (wy <= -10 && std::fabs(lava) > 0.3) {
            return LAVA;
        }

        if (wy >= 30 && wy <= SEA_LEVEL) {
            return WATER;
        }

        double flood = std::max(-1.0, std::min(1.0,
            aquifer_floodedness_vanilla.get_value((double)wx * 0.67,
                                                  (double)wy * 0.67,
                                                  (double)wz * 0.67)));
        double depth_bias = y_clamped_gradient(wy, -20.0, 64.0, -0.35, 0.25);
        if (flood + depth_bias < -0.45) {
            return AIR;
        }

        double spread = aquifer_spread_vanilla.get_value((double)wx * 0.7142857142857143,
                                                         (double)wy * 0.7142857142857143,
                                                         (double)wz * 0.7142857142857143) * 10.0;
        int quantized_spread = (int)std::floor(spread / 3.0) * 3;
        int local_level = SEA_LEVEL;
        if (wy < SEA_LEVEL - 8) {
            int band = (floor_div(wy, 40) * 40) + 20 + quantized_spread;
            local_level = std::min(SEA_LEVEL, band);
        }

        if (wy < local_level) {
            return WATER;
        }
        return AIR;
    }

    double cave_density(int wx, int wy, int wz, double sloped_cheese) const {
        double entrances = cave_entrances(wx, wy, wz);
        if (sloped_cheese < SURFACE_DENSITY_THRESHOLD) {
            return std::min(sloped_cheese, entrances * 5.0);
        }

        double layer = noise3(cave_layer_vanilla, wx, wy, wz, 1.0, 8.0);
        double layer_term = 4.0 * layer * layer;
        double cheese = noise3(cave_cheese_vanilla, wx, wy, wz, 1.0, 0.6666666667);
        double cheese_term = std::max(-1.0, std::min(1.0, 0.27 + cheese)) +
                             std::max(0.0, std::min(0.5, 1.5 - 0.64 * sloped_cheese));
        double underground = std::min(std::min(layer_term + cheese_term, entrances),
                                      spaghetti_2d(wx, wy, wz) + spaghetti_roughness(wx, wy, wz));
        double pillar = pillars(wx, wy, wz);
        if (pillar > 0.03) {
            underground = std::max(underground, pillar);
        }
        return underground;
    }

    double sample_density(int wx, int wy, int wz) const {
        TerrainSample t = sample_terrain(wx, wz);
        double offset = GLOBAL_OFFSET + terrain_offset(t);
        double depth = y_clamped_gradient(wy, -64.0, 320.0, 1.5, -1.5) + offset;
        double jagged = terrain_jaggedness(t) *
                        half_negative(jagged_vanilla.get_value(wx / 1500.0, wy / 1500.0, wz / 1500.0));
        double gradient = 4.0 * quarter_negative((depth + jagged) * terrain_factor(t));
        double sloped_cheese = gradient + blended_base_noise(wx, wy, wz);
        double density = cave_density(wx, wy, wz, sloped_cheese);
        density = slide_overworld(density, wy);
        density = density_squeeze(density * 0.64);
        return std::min(density, noodle_density(wx, wy, wz));
    }

    struct ClimateSample {
        double temperature;
        double humidity;
        double continental;
        double erosion;
        double weirdness;
        double peaks_valleys;
    };

    ClimateSample sample_climate(int wx, int wz) const {
        double sx = shift_a(wx, wz);
        double sz = shift_b(wx, wz);
        double qx = (double)wx * 0.25 + sx;
        double qz = (double)wz * 0.25 + sz;
        ClimateSample c{};
        c.temperature = temperature_vanilla.get_value(qx, 0.0, qz);
        c.humidity = humidity_vanilla.get_value(qx, 0.0, qz);
        c.continental = continental_vanilla.get_value(qx, 0.0, qz);
        c.erosion = erosion_vanilla.get_value(qx, 0.0, qz);
        c.weirdness = ridge_vanilla.get_value(qx, 0.0, qz);
        c.peaks_valleys = peaks_and_valleys(c.weirdness);
        return c;
    }

    static int climate_index(double value, const std::array<double, 4>& ends) {
        for (int i = 0; i < 4; i++) {
            if (value < ends[i]) {
                return i;
            }
        }
        return 4;
    }

    static int temperature_index(double value) {
        return climate_index(value, {-0.45, -0.15, 0.2, 0.55});
    }

    static int humidity_index(double value) {
        return climate_index(value, {-0.35, -0.1, 0.1, 0.3});
    }

    static int erosion_index(double value) {
        const double ends[] = {-0.78, -0.375, -0.2225, 0.05, 0.45, 0.55};
        for (int i = 0; i < 6; i++) {
            if (value < ends[i]) {
                return i;
            }
        }
        return 6;
    }

    enum class WeirdnessSlice {
        Valley,
        Low,
        Mid,
        High,
        Peak,
    };

    static WeirdnessSlice weirdness_slice(double w) {
        if (-0.05 <= w && w < 0.05) return WeirdnessSlice::Valley;
        double aw = std::fabs(w);
        if (aw < 0.26666668) return WeirdnessSlice::Low;
        if (aw < 0.4 || aw >= 0.93333334) return WeirdnessSlice::Mid;
        if (aw < 0.56666666 || aw >= 0.7666667) return WeirdnessSlice::High;
        return WeirdnessSlice::Peak;
    }

    static uint16_t table_or(uint16_t value, uint16_t fallback) {
        return value == 0xFFFF ? fallback : value;
    }

    static uint16_t pick_middle_biome(int t, int h, bool positive_weirdness) {
        static constexpr uint16_t base[5][5] = {
            {BIOME_SNOWY_PLAINS, BIOME_SNOWY_PLAINS, BIOME_SNOWY_PLAINS, BIOME_SNOWY_TAIGA, BIOME_TAIGA},
            {BIOME_PLAINS, BIOME_PLAINS, BIOME_FOREST, BIOME_TAIGA, BIOME_OLD_GROWTH_SPRUCE_TAIGA},
            {BIOME_FLOWER_FOREST, BIOME_PLAINS, BIOME_FOREST, BIOME_BIRCH_FOREST, BIOME_DARK_FOREST},
            {BIOME_SAVANNA, BIOME_SAVANNA, BIOME_FOREST, BIOME_JUNGLE, BIOME_JUNGLE},
            {BIOME_DESERT, BIOME_DESERT, BIOME_DESERT, BIOME_DESERT, BIOME_DESERT},
        };
        static constexpr uint16_t variant[5][5] = {
            {BIOME_ICE_SPIKES, 0xFFFF, BIOME_SNOWY_TAIGA, 0xFFFF, 0xFFFF},
            {0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, BIOME_OLD_GROWTH_PINE_TAIGA},
            {BIOME_SUNFLOWER_PLAINS, 0xFFFF, 0xFFFF, BIOME_OLD_GROWTH_BIRCH_FOREST, 0xFFFF},
            {0xFFFF, 0xFFFF, BIOME_PLAINS, BIOME_SPARSE_JUNGLE, BIOME_BAMBOO_JUNGLE},
            {0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF},
        };
        return positive_weirdness ? table_or(variant[t][h], base[t][h]) : base[t][h];
    }

    static uint16_t pick_badlands_biome(int h, bool positive_weirdness) {
        if (h < 2) {
            return positive_weirdness ? BIOME_ERODED_BADLANDS : BIOME_BADLANDS;
        }
        if (h < 3) {
            return BIOME_BADLANDS;
        }
        return BIOME_WOODED_BADLANDS;
    }

    static uint16_t pick_middle_or_badlands(int t, int h, bool positive_weirdness) {
        return t == 4 ? pick_badlands_biome(h, positive_weirdness)
                      : pick_middle_biome(t, h, positive_weirdness);
    }

    static uint16_t pick_plateau_biome(int t, int h, bool positive_weirdness) {
        static constexpr uint16_t base[5][5] = {
            {BIOME_SNOWY_PLAINS, BIOME_SNOWY_PLAINS, BIOME_SNOWY_PLAINS, BIOME_SNOWY_TAIGA, BIOME_SNOWY_TAIGA},
            {BIOME_MEADOW, BIOME_MEADOW, BIOME_FOREST, BIOME_TAIGA, BIOME_OLD_GROWTH_SPRUCE_TAIGA},
            {BIOME_MEADOW, BIOME_MEADOW, BIOME_MEADOW, BIOME_MEADOW, BIOME_DARK_FOREST},
            {BIOME_SAVANNA_PLATEAU, BIOME_SAVANNA_PLATEAU, BIOME_FOREST, BIOME_FOREST, BIOME_JUNGLE},
            {BIOME_BADLANDS, BIOME_BADLANDS, BIOME_BADLANDS, BIOME_WOODED_BADLANDS, BIOME_WOODED_BADLANDS},
        };
        static constexpr uint16_t variant[5][5] = {
            {BIOME_ICE_SPIKES, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF},
            {BIOME_CHERRY_GROVE, 0xFFFF, BIOME_MEADOW, BIOME_MEADOW, BIOME_OLD_GROWTH_PINE_TAIGA},
            {BIOME_CHERRY_GROVE, BIOME_CHERRY_GROVE, BIOME_FOREST, BIOME_BIRCH_FOREST, 0xFFFF},
            {0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF},
            {BIOME_ERODED_BADLANDS, BIOME_ERODED_BADLANDS, 0xFFFF, 0xFFFF, 0xFFFF},
        };
        return positive_weirdness ? table_or(variant[t][h], base[t][h]) : base[t][h];
    }

    static uint16_t pick_slope_biome(int t, int h, bool positive_weirdness) {
        if (t >= 3) {
            return pick_plateau_biome(t, h, positive_weirdness);
        }
        return h <= 1 ? BIOME_SNOWY_SLOPES : BIOME_GROVE;
    }

    static uint16_t pick_peak_biome(int t, int h, bool positive_weirdness) {
        if (t <= 2) {
            return positive_weirdness ? BIOME_FROZEN_PEAKS : BIOME_JAGGED_PEAKS;
        }
        if (t == 3) {
            return BIOME_STONY_PEAKS;
        }
        return pick_badlands_biome(h, positive_weirdness);
    }

    static uint16_t pick_shattered_biome(int t, int h, bool positive_weirdness) {
        static constexpr uint16_t shattered[5][5] = {
            {BIOME_WINDSWEPT_GRAVELLY_HILLS, BIOME_WINDSWEPT_GRAVELLY_HILLS, BIOME_WINDSWEPT_HILLS, BIOME_WINDSWEPT_FOREST, BIOME_WINDSWEPT_FOREST},
            {BIOME_WINDSWEPT_GRAVELLY_HILLS, BIOME_WINDSWEPT_GRAVELLY_HILLS, BIOME_WINDSWEPT_HILLS, BIOME_WINDSWEPT_FOREST, BIOME_WINDSWEPT_FOREST},
            {BIOME_WINDSWEPT_HILLS, BIOME_WINDSWEPT_HILLS, BIOME_WINDSWEPT_HILLS, BIOME_WINDSWEPT_FOREST, BIOME_WINDSWEPT_FOREST},
            {0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF},
            {0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF},
        };
        return table_or(shattered[t][h], pick_middle_biome(t, h, positive_weirdness));
    }

    static uint16_t maybe_windswept_savanna(int t, int h, bool positive_weirdness, uint16_t fallback) {
        return (t > 1 && h < 4 && positive_weirdness) ? BIOME_WINDSWEPT_SAVANNA : fallback;
    }

    static uint16_t pick_beach_biome(int t) {
        if (t == 0) return BIOME_SNOWY_BEACH;
        if (t == 4) return BIOME_DESERT;
        return BIOME_BEACH;
    }

    static uint16_t pick_shattered_coast_biome(int t, int h, bool positive_weirdness) {
        uint16_t base = positive_weirdness ? pick_middle_biome(t, h, positive_weirdness)
                                           : pick_beach_biome(t);
        return maybe_windswept_savanna(t, h, positive_weirdness, base);
    }

    uint16_t sample_surface_biome(int wx, int wz, int surface_height) const {
        ClimateSample c = sample_climate(wx, wz);
        int t = temperature_index(c.temperature);
        int h = humidity_index(c.humidity);
        int e = erosion_index(c.erosion);
        bool positive = c.weirdness >= 0.0;
        WeirdnessSlice slice = weirdness_slice(c.weirdness);

        if (c.continental < -1.05) {
            return BIOME_MUSHROOM_FIELDS;
        }
        if (c.continental < -0.455) {
            static constexpr uint16_t oceans[5] = {
                BIOME_DEEP_FROZEN_OCEAN, BIOME_DEEP_COLD_OCEAN, BIOME_DEEP_OCEAN,
                BIOME_DEEP_LUKEWARM_OCEAN, BIOME_WARM_OCEAN
            };
            return oceans[t];
        }
        if (c.continental < -0.19) {
            static constexpr uint16_t oceans[5] = {
                BIOME_FROZEN_OCEAN, BIOME_COLD_OCEAN, BIOME_OCEAN,
                BIOME_LUKEWARM_OCEAN, BIOME_WARM_OCEAN
            };
            return oceans[t];
        }

        bool coast = c.continental < -0.11;
        bool near_inland = -0.11 <= c.continental && c.continental < 0.03;
        bool mid_inland = 0.03 <= c.continental && c.continental < 0.3;
        bool far_inland = c.continental >= 0.3;

        if (slice == WeirdnessSlice::Valley) {
            if (e == 6) {
                if (t == 0) return BIOME_FROZEN_RIVER;
                if (t == 1 || t == 2) return BIOME_SWAMP;
                if (t == 3 || t == 4) return BIOME_MANGROVE_SWAMP;
            }
            if (coast || near_inland || e <= 5) {
                return t == 0 ? BIOME_FROZEN_RIVER : BIOME_RIVER;
            }
            return pick_middle_or_badlands(t, h, positive);
        }

        if (coast) {
            if (slice == WeirdnessSlice::Mid && e <= 2) {
                return BIOME_STONY_SHORE;
            }
            if (e == 5) {
                return pick_shattered_coast_biome(t, h, positive);
            }
            if (e >= 3) {
                return pick_beach_biome(t);
            }
        }

        if (e == 6) {
            if (t == 1 || t == 2) return BIOME_SWAMP;
            if (t == 3 || t == 4) return BIOME_MANGROVE_SWAMP;
        }

        if (slice == WeirdnessSlice::Peak) {
            if (e == 0 || (e == 1 && (mid_inland || far_inland))) {
                return pick_peak_biome(t, h, positive);
            }
            if (e == 1 || (near_inland && (e == 2 || e == 3))) {
                return t == 0 ? pick_slope_biome(t, h, positive) : pick_middle_or_badlands(t, h, positive);
            }
            if (e == 2 || (far_inland && e == 3)) {
                return pick_plateau_biome(t, h, positive);
            }
            if (e == 5) {
                return mid_inland || far_inland ? pick_shattered_biome(t, h, positive)
                                                : maybe_windswept_savanna(t, h, positive, pick_middle_biome(t, h, positive));
            }
            return pick_middle_biome(t, h, positive);
        }

        if (slice == WeirdnessSlice::High) {
            if (e == 0) {
                if (near_inland) return pick_slope_biome(t, h, positive);
                if (mid_inland || far_inland) return pick_peak_biome(t, h, positive);
            }
            if (e == 1) {
                return near_inland ? pick_middle_or_badlands(t, h, positive)
                                   : pick_slope_biome(t, h, positive);
            }
            if (e == 2 || (far_inland && e == 3)) {
                return pick_plateau_biome(t, h, positive);
            }
            if (e == 5) {
                return mid_inland || far_inland ? pick_shattered_biome(t, h, positive)
                                                : maybe_windswept_savanna(t, h, positive, pick_middle_biome(t, h, positive));
            }
            return pick_middle_or_badlands(t, h, positive);
        }

        if (slice == WeirdnessSlice::Low) {
            if (e <= 1) {
                return near_inland ? pick_middle_or_badlands(t, h, positive)
                                   : (t == 0 ? pick_slope_biome(t, h, positive)
                                             : pick_middle_or_badlands(t, h, positive));
            }
            if (e == 5 && near_inland) {
                return maybe_windswept_savanna(t, h, positive, pick_middle_biome(t, h, positive));
            }
            return pick_middle_or_badlands(t, h, positive);
        }

        if (slice == WeirdnessSlice::Mid) {
            if (e == 0) return pick_slope_biome(t, h, positive);
            if (e == 1) return far_inland && t != 0 ? pick_plateau_biome(t, h, positive)
                                                    : pick_middle_or_badlands(t, h, positive);
            if (e == 2) return near_inland ? pick_middle_biome(t, h, positive)
                                           : (mid_inland ? pick_middle_or_badlands(t, h, positive)
                                                         : pick_plateau_biome(t, h, positive));
            if (e == 5) return mid_inland || far_inland ? pick_shattered_biome(t, h, positive)
                                                        : maybe_windswept_savanna(t, h, positive, pick_middle_biome(t, h, positive));
            return pick_middle_or_badlands(t, h, positive);
        }

        return pick_middle_biome(t, h, positive);
    }

    uint16_t sample_biome(int wx, int wy, int wz, int surface_height) const {
        uint16_t surface = sample_surface_biome(wx, wz, surface_height);
        ClimateSample c = sample_climate(wx, wz);
        int depth = surface_height - wy;
        if (wy < -48 && depth > 16 && c.erosion < -0.375) {
            return BIOME_DEEP_DARK;
        }
        if (wy < 40 && depth > 12) {
            if (c.humidity > 0.7) return BIOME_LUSH_CAVES;
            if (c.continental > 0.8) return BIOME_DRIPSTONE_CAVES;
        }
        return surface;
    }

    static bool biome_is_sandy(uint16_t biome) {
        return biome == BIOME_DESERT || biome == BIOME_BADLANDS ||
               biome == BIOME_ERODED_BADLANDS || biome == BIOME_WOODED_BADLANDS;
    }

    static bool biome_is_beach(uint16_t biome) {
        return biome == BIOME_BEACH || biome == BIOME_SNOWY_BEACH ||
               biome == BIOME_STONY_SHORE;
    }

    static bool biome_is_cold_surface(uint16_t biome) {
        return biome == BIOME_SNOWY_PLAINS || biome == BIOME_SNOWY_TAIGA ||
               biome == BIOME_ICE_SPIKES || biome == BIOME_GROVE ||
               biome == BIOME_SNOWY_SLOPES || biome == BIOME_FROZEN_PEAKS ||
               biome == BIOME_JAGGED_PEAKS || biome == BIOME_FROZEN_OCEAN ||
               biome == BIOME_DEEP_FROZEN_OCEAN || biome == BIOME_FROZEN_RIVER;
    }

    static bool biome_is_taiga_like(uint16_t biome) {
        return biome == BIOME_TAIGA || biome == BIOME_SNOWY_TAIGA ||
               biome == BIOME_OLD_GROWTH_PINE_TAIGA ||
               biome == BIOME_OLD_GROWTH_SPRUCE_TAIGA || biome == BIOME_GROVE;
    }

    static bool biome_is_forest_like(uint16_t biome) {
        return biome == BIOME_FOREST || biome == BIOME_DARK_FOREST ||
               biome == BIOME_FLOWER_FOREST || biome == BIOME_BIRCH_FOREST ||
               biome == BIOME_OLD_GROWTH_BIRCH_FOREST ||
               biome == BIOME_WINDSWEPT_FOREST;
    }

    static bool biome_is_jungle_like(uint16_t biome) {
        return biome == BIOME_JUNGLE || biome == BIOME_SPARSE_JUNGLE ||
               biome == BIOME_BAMBOO_JUNGLE;
    }

    static bool biome_is_grassy_open(uint16_t biome) {
        return biome == BIOME_PLAINS || biome == BIOME_SUNFLOWER_PLAINS ||
               biome == BIOME_MEADOW || biome == BIOME_SAVANNA ||
               biome == BIOME_SAVANNA_PLATEAU || biome == BIOME_WINDSWEPT_SAVANNA;
    }

    static bool biome_is_badlands(uint16_t biome) {
        return biome == BIOME_BADLANDS || biome == BIOME_ERODED_BADLANDS ||
               biome == BIOME_WOODED_BADLANDS;
    }

    static bool biome_is_stony_surface(uint16_t biome) {
        return biome == BIOME_STONY_PEAKS || biome == BIOME_STONY_SHORE ||
               biome == BIOME_WINDSWEPT_HILLS ||
               biome == BIOME_WINDSWEPT_GRAVELLY_HILLS ||
               biome == BIOME_JAGGED_PEAKS || biome == BIOME_FROZEN_PEAKS;
    }

    static bool biome_is_podzol_surface(uint16_t biome) {
        return biome == BIOME_OLD_GROWTH_PINE_TAIGA ||
               biome == BIOME_OLD_GROWTH_SPRUCE_TAIGA;
    }

    int badlands_band_block(int wx, int wy, int wz) const {
        double band_noise = surface_vanilla.get_value((double)wx * 0.0625,
                                                      0.0,
                                                      (double)wz * 0.0625) * 4.0;
        int band = floor_div(wy + (int)std::floor(band_noise), 2) & 15;
        switch (band) {
            case 1:
            case 2:
                return ORANGE_TERRACOTTA;
            case 4:
                return YELLOW_TERRACOTTA;
            case 6:
                return BROWN_TERRACOTTA;
            case 8:
                return RED_TERRACOTTA;
            case 10:
                return WHITE_TERRACOTTA;
            case 11:
                return LIGHT_GRAY_TERRACOTTA;
            default:
                return TERRACOTTA;
        }
    }

    void build_chunk_biomes(int chunk_x, int chunk_z, int height_map[16][16],
                            uint16_t* biome_out) const {
        if (biome_out == nullptr) {
            return;
        }
        int base_x = chunk_x * 16;
        int base_z = chunk_z * 16;
        int out = 0;
        for (int section = 0; section < NUM_SECTIONS; section++) {
            for (int local_biome_y = 0; local_biome_y < 4; local_biome_y++) {
                for (int biome_z = 0; biome_z < 4; biome_z++) {
                    for (int biome_x = 0; biome_x < 4; biome_x++) {
                        int sample_x = biome_x * 4 + 2;
                        int sample_z = biome_z * 4 + 2;
                        int wx = base_x + sample_x;
                        int wz = base_z + sample_z;
                        int wy = MIN_Y + section * 16 + local_biome_y * 4 + 2;
                        int surface_h = height_map[std::min(15, sample_z)][std::min(15, sample_x)];
                        biome_out[out++] = sample_biome(wx, wy, wz, surface_h);
                    }
                }
            }
        }
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

    static bool can_carver_replace(int block_id) {
        switch (block_id) {
            case STONE:
            case DEEPSLATE:
            case DIRT:
            case GRASS_BLOCK:
            case SAND:
            case SANDSTONE:
            case GRAVEL:
            case CLAY:
            case SNOW_BLOCK:
            case GRANITE:
            case DIORITE:
            case ANDESITE:
            case TUFF:
            case COAL_ORE:
            case DEEPSLATE_COAL_ORE:
            case IRON_ORE:
            case DEEPSLATE_IRON_ORE:
            case COPPER_ORE:
            case DEEPSLATE_COPPER_ORE:
            case GOLD_ORE:
            case DEEPSLATE_GOLD_ORE:
            case REDSTONE_ORE:
            case DEEPSLATE_REDSTONE_ORE:
            case LAPIS_ORE:
            case DEEPSLATE_LAPIS_ORE:
            case DIAMOND_ORE:
            case DEEPSLATE_DIAMOND_ORE:
            case EMERALD_ORE:
            case DEEPSLATE_EMERALD_ORE:
                return true;
            default:
                return false;
        }
    }

    void recompute_heightmap(int* blocks, int height_map[16][16]) const {
        for (int lz = 0; lz < 16; lz++) {
            for (int lx = 0; lx < 16; lx++) {
                int h = MIN_Y + 1;
                for (int yi = WORLD_HEIGHT - 1; yi >= 0; yi--) {
                    int block = blocks[yi * 256 + lz * 16 + lx];
                    if (block != AIR && block != WATER && block != LAVA) {
                        h = yi + MIN_Y;
                        break;
                    }
                }
                height_map[lz][lx] = h;
            }
        }
    }

    void carve_block(int* blocks, int lx, int yi, int lz,
                     int wx, int wy, int wz) const {
        if (lx < 0 || lx >= 16 || lz < 0 || lz >= 16 || yi <= 0 || yi >= WORLD_HEIGHT) {
            return;
        }
        int idx = yi * 256 + lz * 16 + lx;
        if (!can_carver_replace(blocks[idx])) {
            return;
        }
        if (wy <= MIN_Y + 8) {
            blocks[idx] = LAVA;
            return;
        }
        int fluid = aquifer_fluid_block(wx, wy, wz);
        blocks[idx] = (fluid == AIR) ? AIR : fluid;
    }

    void carve_ellipsoid(int* blocks, int base_x, int base_z,
                         double cx, double cy, double cz,
                         double horizontal_radius, double vertical_radius,
                         double floor_level, bool canyon_shape) const {
        if (horizontal_radius <= 0.0 || vertical_radius <= 0.0) {
            return;
        }
        double middle_x = base_x + 8.0;
        double middle_z = base_z + 8.0;
        double reach = 16.0 + horizontal_radius * 2.0;
        if (std::fabs(cx - middle_x) > reach || std::fabs(cz - middle_z) > reach) {
            return;
        }

        int min_lx = std::max(0, (int)std::floor(cx - horizontal_radius) - base_x - 1);
        int max_lx = std::min(15, (int)std::floor(cx + horizontal_radius) - base_x + 1);
        int min_lz = std::max(0, (int)std::floor(cz - horizontal_radius) - base_z - 1);
        int max_lz = std::min(15, (int)std::floor(cz + horizontal_radius) - base_z + 1);
        int min_y = std::max(MIN_Y + 1, (int)std::floor(cy - vertical_radius) - 1);
        int max_y = std::min(MAX_Y - 7, (int)std::floor(cy + vertical_radius) + 1);

        for (int lx = min_lx; lx <= max_lx; lx++) {
            int wx = base_x + lx;
            double nx = ((double)wx + 0.5 - cx) / horizontal_radius;
            for (int lz = min_lz; lz <= max_lz; lz++) {
                int wz = base_z + lz;
                double nz = ((double)wz + 0.5 - cz) / horizontal_radius;
                if (nx * nx + nz * nz >= 1.0) {
                    continue;
                }
                for (int wy = max_y; wy >= min_y; wy--) {
                    double ny = ((double)wy - 0.5 - cy) / vertical_radius;
                    bool skip = false;
                    if (canyon_shape) {
                        skip = (nx * nx + nz * nz) + (ny * ny / 6.0) >= 1.0;
                    } else {
                        skip = ny <= floor_level || (nx * nx + ny * ny + nz * nz) >= 1.0;
                    }
                    if (!skip) {
                        carve_block(blocks, lx, wy - MIN_Y, lz, wx, wy, wz);
                    }
                }
            }
        }
    }

    void carve_tunnel(int* blocks, int base_x, int base_z, SimpleRNG rng,
                      double x, double y, double z,
                      double horizontal_multiplier, double vertical_multiplier,
                      double thickness, double yaw, double pitch,
                      int step_start, int step_end,
                      double y_scale, double floor_level,
                      int branch_depth = 0) const {
        if (step_end <= step_start) {
            return;
        }
        int split_step = rng.randint(step_end / 4, std::max(step_end / 4, step_end / 2));
        bool gentle_pitch = rng.randint(0, 5) == 0;
        double yaw_velocity = 0.0;
        double pitch_velocity = 0.0;

        for (int step = step_start; step < step_end; step++) {
            double progress = (double)step / (double)step_end;
            double radius = 1.5 + std::sin(PI * progress) * thickness;
            double horizontal_radius = radius * horizontal_multiplier;
            double vertical_radius = radius * y_scale * vertical_multiplier;

            double cp = std::cos(pitch);
            x += std::cos(yaw) * cp;
            y += std::sin(pitch);
            z += std::sin(yaw) * cp;

            pitch *= gentle_pitch ? 0.92 : 0.70;
            pitch += pitch_velocity * 0.1;
            yaw += yaw_velocity * 0.1;
            pitch_velocity *= 0.9;
            yaw_velocity *= 0.75;
            pitch_velocity += (rng.random_double() - rng.random_double()) * rng.random_double() * 2.0;
            yaw_velocity += (rng.random_double() - rng.random_double()) * rng.random_double() * 4.0;

            if (branch_depth < 1 && step == split_step && thickness > 1.0) {
                SimpleRNG left = rng;
                left.seed((int64_t)rng.next_u64());
                carve_tunnel(blocks, base_x, base_z, left, x, y, z,
                             horizontal_multiplier, vertical_multiplier,
                             rng.random_double() * 0.5 + 0.5,
                             yaw - PI * 0.5, pitch / 3.0,
                             step, step_end, 1.0, floor_level, branch_depth + 1);
                SimpleRNG right = rng;
                right.seed((int64_t)rng.next_u64());
                carve_tunnel(blocks, base_x, base_z, right, x, y, z,
                             horizontal_multiplier, vertical_multiplier,
                             rng.random_double() * 0.5 + 0.5,
                             yaw + PI * 0.5, pitch / 3.0,
                             step, step_end, 1.0, floor_level, branch_depth + 1);
                return;
            }

            if (rng.randint(0, 3) == 0) {
                continue;
            }
            carve_ellipsoid(blocks, base_x, base_z, x, y, z,
                            horizontal_radius, vertical_radius, floor_level, false);
        }
    }

    void apply_cave_carver_from_start(int* blocks, int base_x, int base_z,
                                      int start_chunk_x, int start_chunk_z,
                                      bool extra_underground) const {
        SimpleRNG rng;
        const char* key = extra_underground ? "carver_cave_extra_underground" : "carver_cave";
        rng.seed_key(seed ^ ((int64_t)start_chunk_x * 341873128712LL
                           + (int64_t)start_chunk_z * 132897987541LL),
                     key);

        double probability = extra_underground ? 0.07 : 0.15;
        if (rng.random_double() > probability) {
            return;
        }

        int cave_count = rng.randint(0, rng.randint(0, rng.randint(0, 14)));
        int y_min = MIN_Y + 8;
        int y_max = extra_underground ? 47 : 180;
        int range_steps = (4 * 2 - 1) * 16;

        for (int i = 0; i < cave_count; i++) {
            double x = (double)(start_chunk_x * 16 + rng.randint(0, 15));
            double y = (double)rng.randint(y_min, y_max);
            double z = (double)(start_chunk_z * 16 + rng.randint(0, 15));
            double h_mult = 0.7 + rng.random_double() * 0.7;
            double v_mult = 0.8 + rng.random_double() * 0.5;
            double floor_level = -1.0 + rng.random_double() * 0.6;
            int tunnel_count = 1;

            if (rng.randint(0, 3) == 0) {
                double y_scale = 0.1 + rng.random_double() * 0.8;
                double room_thickness = 1.0 + rng.random_double() * 6.0;
                double radius = 1.5 + room_thickness;
                carve_ellipsoid(blocks, base_x, base_z, x + 1.0, y, z,
                                radius, radius * y_scale, floor_level, false);
                tunnel_count += rng.randint(0, 3);
            }

            for (int t = 0; t < tunnel_count; t++) {
                double yaw = rng.random_double() * PI * 2.0;
                double pitch = (rng.random_double() - 0.5) / 4.0;
                double thickness = rng.random_double() * 2.0 + rng.random_double();
                if (rng.randint(0, 9) == 0) {
                    thickness *= rng.random_double() * rng.random_double() * 3.0 + 1.0;
                }
                int steps = range_steps - rng.randint(0, range_steps / 4);
                SimpleRNG tunnel_rng;
                tunnel_rng.seed((int64_t)rng.next_u64());
                carve_tunnel(blocks, base_x, base_z, tunnel_rng,
                             x, y, z, h_mult, v_mult, thickness,
                             yaw, pitch, 0, steps, 1.0, floor_level);
            }
        }
    }

    void apply_canyon_carver_from_start(int* blocks, int base_x, int base_z,
                                        int start_chunk_x, int start_chunk_z) const {
        SimpleRNG rng;
        rng.seed_key(seed ^ ((int64_t)start_chunk_x * 6364136223846793005LL
                           + (int64_t)start_chunk_z * 1442695040888963407LL),
                     "carver_canyon");
        if (rng.random_double() > 0.01) {
            return;
        }

        double x = (double)(start_chunk_x * 16 + rng.randint(0, 15));
        double y = (double)rng.randint(10, 67);
        double z = (double)(start_chunk_z * 16 + rng.randint(0, 15));
        double yaw = rng.random_double() * PI * 2.0;
        double pitch = -0.125 + rng.random_double() * 0.25;
        double thickness = rng.triangular(0.0, 6.0, 2.0);
        double distance_factor = 0.75 + rng.random_double() * 0.25;
        int steps = (int)((4 * 2 - 1) * 16 * distance_factor);
        double yaw_velocity = 0.0;
        double pitch_velocity = 0.0;

        for (int step = 0; step < steps; step++) {
            double progress = (double)step / (double)std::max(1, steps);
            double base_radius = 1.5 + std::sin(PI * progress) * thickness;
            double horizontal_radius = base_radius * (0.75 + rng.random_double() * 0.25);
            double center_factor = 1.0 - std::fabs(0.5 - progress) * 2.0;
            double vertical_radius = base_radius * 3.0 * (1.0 + center_factor) *
                                     (0.75 + rng.random_double() * 0.25);

            double cp = std::cos(pitch);
            x += std::cos(yaw) * cp;
            y += std::sin(pitch);
            z += std::sin(yaw) * cp;
            pitch *= 0.7;
            pitch += pitch_velocity * 0.05;
            yaw += yaw_velocity * 0.05;
            pitch_velocity *= 0.8;
            yaw_velocity *= 0.5;
            pitch_velocity += (rng.random_double() - rng.random_double()) * rng.random_double() * 2.0;
            yaw_velocity += (rng.random_double() - rng.random_double()) * rng.random_double() * 4.0;

            if (rng.randint(0, 3) == 0) {
                continue;
            }
            carve_ellipsoid(blocks, base_x, base_z, x, y, z,
                            horizontal_radius, vertical_radius, -1.0, true);
        }
    }

    void apply_carvers(int* blocks, int chunk_x, int chunk_z, int base_x, int base_z) const {
        for (int sx = chunk_x - 4; sx <= chunk_x + 4; sx++) {
            for (int sz = chunk_z - 4; sz <= chunk_z + 4; sz++) {
                apply_cave_carver_from_start(blocks, base_x, base_z, sx, sz, false);
                apply_cave_carver_from_start(blocks, base_x, base_z, sx, sz, true);
                apply_canyon_carver_from_start(blocks, base_x, base_z, sx, sz);
            }
        }
    }

    // 主生成函数: 生成 384*16*16 的方块数据
    // blocks[y][z][x] => blocks[y * 256 + z * 16 + x]
    void generate_chunk(int chunk_x, int chunk_z, int* blocks,
                        int16_t* heightmap_out = nullptr,
                        uint16_t* biome_out = nullptr) const {
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
                                } else {
                                    int fluid = aquifer_fluid_block(wx, wy, wz);
                                    if (fluid != AIR) {
                                        blocks[idx] = fluid;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- 第二步: 原版 carver 阶段的轻量移植，额外切出洞穴/峡谷 ---
        apply_carvers(blocks, chunk_x, chunk_z, base_x, base_z);
        recompute_heightmap(blocks, height_map);

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

        build_chunk_biomes(chunk_x, chunk_z, height_map, biome_out);

        // --- 第三步: 地表规则 ---
        apply_surface_rules(blocks, height_map, base_x, base_z);

        // --- 第四步: 矿石 ---
        place_ores(blocks, base_x, base_z);
        apply_ore_veins(blocks, base_x, base_z);

        // --- 第五步: 原版 Feature 流程的轻量地表装饰 ---
        place_surface_features(blocks, height_map, base_x, base_z);

        // --- 第六步: 石头变种 ---
        place_stone_variants(blocks, base_x, base_z);
    }

    void apply_surface_rules(int* blocks, int height_map[16][16],
                             int base_x, int base_z) const {
        for (int lx = 0; lx < 16; lx++) {
            for (int lz = 0; lz < 16; lz++) {
                int wx = base_x + lx;
                int wz = base_z + lz;
                int surface_h = height_map[lz][lx];

                double surf_n = surface_vanilla.get_value((double)wx, 0.0, (double)wz);
                uint16_t surface_biome = sample_surface_biome(wx, wz, surface_h);

                bool is_beach = biome_is_beach(surface_biome) ||
                                (SEA_LEVEL - 2 <= surface_h && surface_h <= SEA_LEVEL + 2 && surf_n > -0.3);
                bool is_desert = biome_is_sandy(surface_biome);
                bool is_cold = biome_is_cold_surface(surface_biome);
                bool is_gravel_beach = surface_biome == BIOME_STONY_SHORE ||
                                       (is_beach && surf_n > 0.4);
                bool is_underwater = (surface_h < SEA_LEVEL);
                bool is_badlands_surface = biome_is_badlands(surface_biome);
                bool is_stony_surface = biome_is_stony_surface(surface_biome) ||
                                       (surface_h > 110 && surf_n > 0.45);

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

                if (is_badlands_surface && !is_underwater) {
                    set_block(si, lz, lx, RED_SAND);
                    for (int d = 1; d < 5; d++) {
                        int idx = si - d;
                        if (idx >= 0) {
                            int cur_block = get_block(idx, lz, lx);
                            if (cur_block == STONE || cur_block == DEEPSLATE || cur_block == DIRT) {
                                set_block(idx, lz, lx, d < 2 ? RED_SAND : RED_SANDSTONE);
                            }
                        }
                    }
                    int terracotta_depth = 18 + (int)(std::fabs(surf_n) * 8.0);
                    for (int d = 5; d <= terracotta_depth; d++) {
                        int idx = si - d;
                        if (idx >= 0) {
                            int cur_block = get_block(idx, lz, lx);
                            if (cur_block == STONE || cur_block == DEEPSLATE) {
                                set_block(idx, lz, lx, badlands_band_block(wx, surface_h - d, wz));
                            }
                        }
                    }
                } else if (is_gravel_beach) {
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
                } else if (is_stony_surface && !is_underwater) {
                    int top = (surface_biome == BIOME_WINDSWEPT_GRAVELLY_HILLS || surf_n > 0.65) ? GRAVEL : STONE;
                    if (surface_biome == BIOME_STONY_PEAKS && surf_n < -0.2) {
                        top = CALCITE;
                    }
                    set_block(si, lz, lx, top);
                    for (int d = 1; d < 4; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE) {
                            set_block(idx, lz, lx, STONE);
                        }
                    }
                } else if (is_cold && !is_underwater) {
                    bool snow_block_surface =
                        surface_biome == BIOME_FROZEN_PEAKS ||
                        surface_biome == BIOME_JAGGED_PEAKS ||
                        surface_biome == BIOME_SNOWY_SLOPES ||
                        surface_biome == BIOME_GROVE ||
                        surface_biome == BIOME_ICE_SPIKES;
                    int top = snow_block_surface ? SNOW_BLOCK : GRASS_BLOCK;
                    if (surface_biome == BIOME_GROVE && surf_n > 0.55) {
                        top = POWDER_SNOW;
                    }
                    set_block(si, lz, lx, top);
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
                    int top = GRASS_BLOCK;
                    int under = DIRT;
                    if (biome_is_podzol_surface(surface_biome)) {
                        top = PODZOL;
                        under = COARSE_DIRT;
                    } else if (surface_biome == BIOME_WINDSWEPT_SAVANNA && surf_n > 0.25) {
                        top = COARSE_DIRT;
                        under = COARSE_DIRT;
                    } else if ((surface_biome == BIOME_LUSH_CAVES || surface_biome == BIOME_SWAMP) &&
                               surf_n > 0.45) {
                        top = MOSS_BLOCK;
                    }
                    set_block(si, lz, lx, top);
                    int dirt_depth = 3 + (int)(std::fabs(surf_n) * 2.0);
                    for (int d = 1; d <= dirt_depth; d++) {
                        int idx = si - d;
                        if (idx >= 0 && get_block(idx, lz, lx) == STONE)
                            set_block(idx, lz, lx, under);
                    }
                }

                if (is_cold) {
                    int water_yi = SEA_LEVEL - MIN_Y;
                    if (water_yi >= 0 && water_yi < WORLD_HEIGHT &&
                        get_block(water_yi, lz, lx) == WATER) {
                        set_block(water_yi, lz, lx, ICE);
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

    bool can_replace_feature(int block_id) const {
        return block_id == AIR || block_id == SNOW || block_id == SHORT_GRASS ||
               block_id == FERN || block_id == DEAD_BUSH || block_id == SEAGRASS ||
               block_id == DANDELION || block_id == POPPY ||
               block_id == BROWN_MUSHROOM || block_id == RED_MUSHROOM;
    }

    void set_if_replaceable(int* blocks, int yi, int lz, int lx, int block_id) const {
        if (yi < 0 || yi >= WORLD_HEIGHT || lx < 0 || lx >= 16 || lz < 0 || lz >= 16) {
            return;
        }
        int idx = yi * 256 + lz * 16 + lx;
        if (can_replace_feature(blocks[idx])) {
            blocks[idx] = block_id;
        }
    }

    void place_simple_tree(int* blocks, int lx, int si, int lz, int log_id, int leaves_id,
                           int height) const {
        if (lx < 2 || lx > 13 || lz < 2 || lz > 13) {
            return;
        }
        if (si + height + 2 >= WORLD_HEIGHT) {
            return;
        }

        for (int dy = 1; dy <= height; dy++) {
            set_if_replaceable(blocks, si + dy, lz, lx, log_id);
        }

        int top = si + height;
        for (int dy = -2; dy <= 1; dy++) {
            int radius = (dy <= -1) ? 2 : 1;
            for (int dz = -radius; dz <= radius; dz++) {
                for (int dx = -radius; dx <= radius; dx++) {
                    int manhattan = std::abs(dx) + std::abs(dz);
                    if (manhattan > radius + 1) {
                        continue;
                    }
                    if (std::abs(dx) == radius && std::abs(dz) == radius && dy >= 0) {
                        continue;
                    }
                    set_if_replaceable(blocks, top + dy, lz + dz, lx + dx, leaves_id);
                }
            }
        }
        set_if_replaceable(blocks, top + 2, lz, lx, leaves_id);
    }

    bool has_adjacent_water(int* blocks, int yi, int lz, int lx) const {
        static constexpr int dirs[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
        for (auto& d : dirs) {
            int nx = lx + d[0];
            int nz = lz + d[1];
            if (nx < 0 || nx >= 16 || nz < 0 || nz >= 16 || yi < 0 || yi >= WORLD_HEIGHT) {
                continue;
            }
            if (blocks[yi * 256 + nz * 16 + nx] == WATER) {
                return true;
            }
        }
        return false;
    }

    void place_surface_features(int* blocks, int height_map[16][16],
                                int base_x, int base_z) const {
        for (int lz = 0; lz < 16; lz++) {
            for (int lx = 0; lx < 16; lx++) {
                int surface_h = height_map[lz][lx];
                int si = surface_h - MIN_Y;
                if (si < 0 || si + 1 >= WORLD_HEIGHT) {
                    continue;
                }

                int surface = blocks[si * 256 + lz * 16 + lx];
                int above = blocks[(si + 1) * 256 + lz * 16 + lx];
                if (above != AIR && above != SNOW) {
                    continue;
                }

                int wx = base_x + lx;
                int wz = base_z + lz;
                uint16_t biome = sample_surface_biome(wx, wz, surface_h);
                double feature_roll = block_hash(wx, surface_h + 17, wz);
                double detail_roll = block_hash(wx + 991, surface_h + 23, wz - 313);

                if (surface == GRASS_BLOCK) {
                    double tree_chance = 0.0015;
                    double grass_chance = 0.08;
                    double flower_chance = 0.012;

                    if (biome_is_forest_like(biome)) {
                        tree_chance = (biome == BIOME_DARK_FOREST) ? 0.045 : 0.024;
                        grass_chance = 0.055;
                        flower_chance = (biome == BIOME_FLOWER_FOREST) ? 0.065 : 0.018;
                    } else if (biome_is_taiga_like(biome)) {
                        tree_chance = 0.030;
                        grass_chance = 0.045;
                        flower_chance = 0.006;
                    } else if (biome_is_jungle_like(biome)) {
                        tree_chance = biome == BIOME_BAMBOO_JUNGLE ? 0.040 : 0.032;
                        grass_chance = 0.100;
                        flower_chance = 0.010;
                    } else if (biome == BIOME_MEADOW || biome == BIOME_SUNFLOWER_PLAINS) {
                        tree_chance = 0.003;
                        grass_chance = 0.180;
                        flower_chance = 0.080;
                    } else if (biome_is_grassy_open(biome)) {
                        tree_chance = (biome == BIOME_SAVANNA || biome == BIOME_SAVANNA_PLATEAU) ? 0.010 : 0.0025;
                        grass_chance = 0.120;
                        flower_chance = 0.020;
                    } else if (biome_is_cold_surface(biome)) {
                        tree_chance = (biome == BIOME_SNOWY_TAIGA || biome == BIOME_GROVE) ? 0.020 : 0.001;
                        grass_chance = 0.020;
                        flower_chance = 0.002;
                    }

                    if (feature_roll < tree_chance) {
                        int height = 4 + (int)(detail_roll * 3.0);
                        if (biome_is_taiga_like(biome) || biome_is_cold_surface(biome)) {
                            place_simple_tree(blocks, lx, si, lz, SPRUCE_LOG, SPRUCE_LEAVES, height + 1);
                        } else if (biome == BIOME_BIRCH_FOREST || biome == BIOME_OLD_GROWTH_BIRCH_FOREST) {
                            place_simple_tree(blocks, lx, si, lz, BIRCH_LOG, BIRCH_LEAVES, height);
                        } else if (biome_is_jungle_like(biome)) {
                            place_simple_tree(blocks, lx, si, lz, JUNGLE_LOG, JUNGLE_LEAVES, height + 2);
                        } else if (biome == BIOME_SAVANNA || biome == BIOME_SAVANNA_PLATEAU ||
                                   biome == BIOME_WINDSWEPT_SAVANNA) {
                            place_simple_tree(blocks, lx, si, lz, ACACIA_LOG, ACACIA_LEAVES, height);
                        } else if (biome == BIOME_DARK_FOREST) {
                            place_simple_tree(blocks, lx, si, lz, DARK_OAK_LOG, DARK_OAK_LEAVES, height + 1);
                        } else {
                            place_simple_tree(blocks, lx, si, lz, OAK_LOG, OAK_LEAVES, height);
                        }
                    } else if (feature_roll < tree_chance + grass_chance) {
                        int plant = SHORT_GRASS;
                        if (biome_is_taiga_like(biome) && detail_roll > 0.35) {
                            plant = detail_roll > 0.92 ? LARGE_FERN : FERN;
                        }
                        set_if_replaceable(blocks, si + 1, lz, lx, plant);
                    } else if (feature_roll < tree_chance + grass_chance + flower_chance) {
                        set_if_replaceable(blocks, si + 1, lz, lx, detail_roll < 0.5 ? DANDELION : POPPY);
                    } else if (feature_roll < tree_chance + grass_chance + flower_chance + 0.0018 &&
                               biome_is_grassy_open(biome)) {
                        set_if_replaceable(blocks, si + 1, lz, lx, PUMPKIN);
                    } else if (feature_roll < tree_chance + grass_chance + flower_chance + 0.004 &&
                               biome_is_jungle_like(biome)) {
                        set_if_replaceable(blocks, si + 1, lz, lx, MELON);
                    }
                } else if ((surface == SAND || surface == RED_SAND) && surface_h >= SEA_LEVEL &&
                           (biome == BIOME_DESERT || biome_is_badlands(biome))) {
                    if (feature_roll < 0.012) {
                        int cactus_height = 1 + (int)(detail_roll * 3.0);
                        for (int dy = 1; dy <= cactus_height && si + dy < WORLD_HEIGHT; dy++) {
                            if (blocks[(si + dy) * 256 + lz * 16 + lx] != AIR) {
                                break;
                            }
                            blocks[(si + dy) * 256 + lz * 16 + lx] = CACTUS;
                        }
                    } else if (feature_roll < 0.045) {
                        set_if_replaceable(blocks, si + 1, lz, lx, DEAD_BUSH);
                    }
                }

                if ((surface == GRASS_BLOCK || surface == DIRT || surface == SAND) &&
                    surface_h >= SEA_LEVEL - 1 &&
                    feature_roll > 0.965 &&
                    has_adjacent_water(blocks, si, lz, lx)) {
                    int cane_height = 1 + (int)(detail_roll * 3.0);
                    for (int dy = 1; dy <= cane_height && si + dy < WORLD_HEIGHT; dy++) {
                        if (blocks[(si + dy) * 256 + lz * 16 + lx] != AIR) {
                            break;
                        }
                        blocks[(si + dy) * 256 + lz * 16 + lx] = SUGAR_CANE;
                    }
                }

                if (surface_h < SEA_LEVEL && si + 1 < WORLD_HEIGHT) {
                    int water_yi = -1;
                    for (int wy_scan = std::min(SEA_LEVEL - MIN_Y, WORLD_HEIGHT - 1);
                         wy_scan > si; wy_scan--) {
                        if (blocks[wy_scan * 256 + lz * 16 + lx] == WATER &&
                            (wy_scan == si + 1 ||
                             blocks[(wy_scan - 1) * 256 + lz * 16 + lx] != WATER)) {
                            water_yi = wy_scan;
                            break;
                        }
                    }
                    if (water_yi >= 0) {
                        double water_roll = block_hash(wx - 211, surface_h + 5, wz + 409);
                        if (water_roll < 0.080) {
                            blocks[water_yi * 256 + lz * 16 + lx] = SEAGRASS;
                        } else if (water_roll < 0.095 && surface_h < SEA_LEVEL - 4) {
                            int height = 2 + (int)(detail_roll * 5.0);
                            for (int dy = 0; dy < height && water_yi + dy < WORLD_HEIGHT; dy++) {
                                int idx = (water_yi + dy) * 256 + lz * 16 + lx;
                                if (blocks[idx] != WATER) {
                                    break;
                                }
                                blocks[idx] = (dy == height - 1) ? KELP : KELP_PLANT;
                            }
                        }
                    }
                }
            }
        }
    }

    bool is_hidden_by_solid(int* blocks, int lx, int yi, int lz) const {
        static constexpr int dirs[6][3] = {
            {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}
        };
        for (auto& d : dirs) {
            int nx = lx + d[0];
            int ny = yi + d[1];
            int nz = lz + d[2];
            if (nx < 0 || nx >= 16 || nz < 0 || nz >= 16 || ny < 0 || ny >= WORLD_HEIGHT) {
                return false;
            }
            int block = blocks[ny * 256 + nz * 16 + nx];
            if (block == AIR || block == WATER || block == LAVA) {
                return false;
            }
        }
        return true;
    }

    int column_surface_height(int* blocks, int lx, int lz) const {
        for (int yi = WORLD_HEIGHT - 1; yi >= 0; yi--) {
            int block = blocks[yi * 256 + lz * 16 + lx];
            if (block != AIR && block != WATER && block != LAVA) {
                return yi + MIN_Y;
            }
        }
        return MIN_Y;
    }

    static bool biome_is_mountain_ore(uint16_t biome) {
        return biome == BIOME_MEADOW || biome == BIOME_GROVE ||
               biome == BIOME_SNOWY_SLOPES || biome == BIOME_FROZEN_PEAKS ||
               biome == BIOME_JAGGED_PEAKS || biome == BIOME_STONY_PEAKS ||
               biome == BIOME_WINDSWEPT_HILLS ||
               biome == BIOME_WINDSWEPT_GRAVELLY_HILLS ||
               biome == BIOME_WINDSWEPT_FOREST;
    }

    static bool is_vein_replaceable(int block_id) {
        return block_id == STONE || block_id == DEEPSLATE;
    }

    void apply_ore_veins(int* blocks, int base_x, int base_z) const {
        struct VeinType {
            int min_y;
            int max_y;
            int ore;
            int raw_block;
            int filler;
        };
        static constexpr VeinType COPPER_VEIN = {0, 50, COPPER_ORE, RAW_COPPER_BLOCK, GRANITE};
        static constexpr VeinType IRON_VEIN = {-60, -8, DEEPSLATE_IRON_ORE, RAW_IRON_BLOCK, TUFF};
        static constexpr double VEININESS_THRESHOLD = 0.4;
        static constexpr double EDGE_ROUNDOFF_BEGIN = 20.0;
        static constexpr double MAX_EDGE_ROUNDOFF = 0.2;
        static constexpr double VEIN_SOLIDNESS = 0.7;
        static constexpr double MIN_RICHNESS = 0.1;
        static constexpr double MAX_RICHNESS = 0.3;
        static constexpr double MAX_RICHNESS_THRESHOLD = 0.6;
        static constexpr double RAW_BLOCK_CHANCE = 0.02;
        static constexpr double GAP_THRESHOLD = -0.3;

        for (int lz = 0; lz < 16; lz++) {
            for (int lx = 0; lx < 16; lx++) {
                int wx = base_x + lx;
                int wz = base_z + lz;
                for (int wy = IRON_VEIN.min_y; wy <= COPPER_VEIN.max_y; wy++) {
                    int yi = wy - MIN_Y;
                    if (yi < 0 || yi >= WORLD_HEIGHT) {
                        continue;
                    }
                    int idx = yi * 256 + lz * 16 + lx;
                    if (!is_vein_replaceable(blocks[idx])) {
                        continue;
                    }

                    double veininess = noise3(ore_veininess_vanilla, wx, wy, wz, 1.5, 1.5);
                    const VeinType& type = (veininess > 0.0) ? COPPER_VEIN : IRON_VEIN;
                    if (wy < type.min_y || wy > type.max_y) {
                        continue;
                    }

                    double abs_veininess = std::fabs(veininess);
                    double edge_distance = (double)std::min(wy - type.min_y, type.max_y - wy);
                    double edge_roundoff =
                        clamped_lerp(MAX_EDGE_ROUNDOFF, 0.0, edge_distance / EDGE_ROUNDOFF_BEGIN);
                    double vein_threshold = VEININESS_THRESHOLD + edge_roundoff;
                    if (abs_veininess <= vein_threshold) {
                        continue;
                    }
                    if (position_chance(wx, wy, wz, 0xD1B54A32D192ED03ULL) > VEIN_SOLIDNESS) {
                        continue;
                    }

                    double vein_a = std::fabs(noise3(ore_vein_a_vanilla, wx, wy, wz, 4.0, 4.0));
                    double vein_b = std::fabs(noise3(ore_vein_b_vanilla, wx, wy, wz, 4.0, 4.0));
                    double ridged = -0.08 + std::max(vein_a, vein_b);
                    if (ridged >= 0.0) {
                        continue;
                    }

                    double richness =
                        clamped_lerp(MIN_RICHNESS, MAX_RICHNESS,
                                     inverse_lerp(vein_threshold, MAX_RICHNESS_THRESHOLD,
                                                  abs_veininess));
                    double gap = noise3(ore_gap_vanilla, wx, wy, wz);
                    if (position_chance(wx, wy, wz, 0xC2B2AE3D27D4EB4FULL) >= richness ||
                        gap <= GAP_THRESHOLD) {
                        blocks[idx] = type.filler;
                    } else if (position_chance(wx, wy, wz, 0x165667B19E3779F9ULL) < RAW_BLOCK_CHANCE) {
                        blocks[idx] = type.raw_block;
                    } else {
                        blocks[idx] = type.ore;
                    }
                }
            }
        }
    }

    void place_ores(int* blocks, int base_x, int base_z) const {
        enum OreBiomeFilter {
            ORE_ANY = 0,
            ORE_MOUNTAIN = 1,
            ORE_BADLANDS = 2,
        };

        struct OreConfig {
            int ore;
            int deep_ore;
            int attempts;
            int vein_size;
            int y_min;
            int y_max;
            bool triangle;
            double discard_chance;
            OreBiomeFilter biome_filter;
            const char* key;
        };

        OreConfig ores[] = {
            {COAL_ORE, DEEPSLATE_COAL_ORE, 30, 17, 136, 320, false, 0.0, ORE_ANY, "ore_coal_upper"},
            {COAL_ORE, DEEPSLATE_COAL_ORE, 20, 17,   0, 192, true,  0.5, ORE_ANY, "ore_coal_lower"},
            {IRON_ORE, DEEPSLATE_IRON_ORE, 90,  9,  80, 320, true,  0.0, ORE_ANY, "ore_iron_upper"},
            {IRON_ORE, DEEPSLATE_IRON_ORE, 10,  9, -24,  56, true,  0.0, ORE_ANY, "ore_iron_middle"},
            {IRON_ORE, DEEPSLATE_IRON_ORE, 10,  4, -64,  72, false, 0.0, ORE_ANY, "ore_iron_small"},
            {COPPER_ORE, DEEPSLATE_COPPER_ORE, 16, 10, -16, 112, true, 0.0, ORE_ANY, "ore_copper"},
            {COPPER_ORE, DEEPSLATE_COPPER_ORE, 16, 20, -16, 112, true, 0.0, ORE_ANY, "ore_copper_large"},
            {GOLD_ORE, DEEPSLATE_GOLD_ORE, 50,  9,  32, 256, false, 0.5, ORE_BADLANDS, "ore_gold_extra"},
            {GOLD_ORE, DEEPSLATE_GOLD_ORE,  4,  9, -64,  32, true,  0.5, ORE_ANY, "ore_gold"},
            {GOLD_ORE, DEEPSLATE_GOLD_ORE,  1,  9, -64, -48, false, 0.5, ORE_ANY, "ore_gold_lower"},
            {REDSTONE_ORE, DEEPSLATE_REDSTONE_ORE,  4, 8, -64, 15, false, 0.0, ORE_ANY, "ore_redstone"},
            {REDSTONE_ORE, DEEPSLATE_REDSTONE_ORE,  8, 8, -64, 32, true,  0.0, ORE_ANY, "ore_redstone_lower"},
            {DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE,  7,  4, -64,  80, true,  0.5, ORE_ANY, "ore_diamond_small"},
            {DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE,  2,  8, -64,  -4, false, 0.5, ORE_ANY, "ore_diamond_medium"},
            {DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE,  1, 12, -64,  80, true,  0.7, ORE_ANY, "ore_diamond_large"},
            {DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE,  4,  8, -64,  80, true,  1.0, ORE_ANY, "ore_diamond_buried"},
            {LAPIS_ORE, DEEPSLATE_LAPIS_ORE, 2, 7, -32, 32, true,  0.0, ORE_ANY, "ore_lapis"},
            {LAPIS_ORE, DEEPSLATE_LAPIS_ORE, 4, 7, -64, 64, false, 1.0, ORE_ANY, "ore_lapis_buried"},
            {EMERALD_ORE, DEEPSLATE_EMERALD_ORE, 100, 3, -16, 320, true, 0.0, ORE_MOUNTAIN, "ore_emerald"},
        };

        for (auto& o : ores) {
            SimpleRNG rng;
            rng.seed_key(seed ^ ((int64_t)base_x * 6364136223846793005LL
                               + (int64_t)base_z * 1442695040888963407LL),
                         o.key);
            for (int a = 0; a < o.attempts; a++) {
                int lx = rng.randint(0, 15);
                int lz = rng.randint(0, 15);
                if (o.biome_filter != ORE_ANY) {
                    int wx = base_x + lx;
                    int wz = base_z + lz;
                    int surface_h = column_surface_height(blocks, lx, lz);
                    uint16_t biome = sample_surface_biome(wx, wz, surface_h);
                    if (o.biome_filter == ORE_MOUNTAIN && !biome_is_mountain_ore(biome)) {
                        continue;
                    }
                    if (o.biome_filter == ORE_BADLANDS && !biome_is_sandy(biome)) {
                        continue;
                    }
                }
                int wy;
                if (o.triangle) {
                    wy = (int)rng.triangular((double)o.y_min, (double)o.y_max,
                                             ((double)o.y_min + (double)o.y_max) * 0.5);
                } else {
                    wy = rng.randint(o.y_min, o.y_max);
                }
                int yi = wy - MIN_Y;

                if (yi < 0 || yi >= WORLD_HEIGHT) continue;

                int target = blocks[yi * 256 + lz * 16 + lx];
                int ore_block;
                if (target == STONE) ore_block = o.ore;
                else if (target == DEEPSLATE) ore_block = o.deep_ore;
                else continue;
                if (o.discard_chance > 0.0 && is_hidden_by_solid(blocks, lx, yi, lz) &&
                    rng.random_double() < o.discard_chance) {
                    continue;
                }

                blocks[yi * 256 + lz * 16 + lx] = ore_block;
                for (int v = 0; v < o.vein_size - 1; v++) {
                    int dx = rng.randint(-1, 1);
                    int dy = rng.randint(-1, 1);
                    int dz = rng.randint(-1, 1);
                    int nx = lx + dx, ny = yi + dy, nz = lz + dz;
                    if (nx >= 0 && nx < 16 && nz >= 0 && nz < 16 &&
                        ny >= 0 && ny < WORLD_HEIGHT) {
                        int c = blocks[ny * 256 + nz * 16 + nx];
                        int placed = 0;
                        if (c == STONE) placed = o.ore;
                        else if (c == DEEPSLATE) placed = o.deep_ore;
                        if (placed != 0) {
                            if (o.discard_chance > 0.0 && is_hidden_by_solid(blocks, nx, ny, nz) &&
                                rng.random_double() < o.discard_chance) {
                                continue;
                            }
                            blocks[ny * 256 + nz * 16 + nx] = placed;
                        }
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
// 生物群系: 1536 个 uint16 = 3072 字节
// 总数据:   200192 字节
static constexpr uint32_t BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16;  // 98304
static constexpr uint32_t BLOCKS_BYTES = BLOCKS_COUNT * 2;        // 196608
static constexpr uint32_t HEIGHTMAP_COUNT = 256;
static constexpr uint32_t HEIGHTMAP_BYTES = HEIGHTMAP_COUNT * 2;  // 512
static constexpr uint32_t BIOME_COUNT = NUM_SECTIONS * 64;        // 1536
static constexpr uint32_t BIOME_BYTES = BIOME_COUNT * 2;          // 3072
static constexpr uint32_t PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES + BIOME_BYTES;

struct ChunkResponse {
    std::vector<uint16_t> blocks;
    std::array<int16_t, HEIGHTMAP_COUNT> heightmap;
    std::array<uint16_t, BIOME_COUNT> biomes;

    ChunkResponse() : blocks(BLOCKS_COUNT, 0) {
        heightmap.fill(0);
        biomes.fill(BIOME_PLAINS);
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
            uint16_t* biomes_out = (uint16_t*)(response_buf + 4 + BLOCKS_BYTES + HEIGHTMAP_BYTES);
            gen.generate_chunk(chunk_x, chunk_z, blocks, heightmap_out, biomes_out);

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
                TerrainGenerator local_gen;
                local_gen.init(seed);
                std::vector<int> local_blocks(BLOCKS_COUNT);
                while (true) {
                    uint32_t idx = next_index.fetch_add(1);
                    if (idx >= chunk_count) break;
                    int32_t chunk_x = coords[idx].chunk_x;
                    int32_t chunk_z = coords[idx].chunk_z;
                    local_gen.generate_chunk(
                        chunk_x,
                        chunk_z,
                        local_blocks.data(),
                        results[idx].heightmap.data(),
                        results[idx].biomes.data()
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
            if (!write_exact(results[idx].biomes.data(), BIOME_BYTES)) {
                chunk_count = 0;
                break;
            }
        }
        if (chunk_count == 0) break;
        fflush(stdout);
    }

    return 0;
}
