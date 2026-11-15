// ============================================================
// PyMC - Vanilla overworld terrain (Minecraft Java 1.21.1)
//
// Noise stage of NoiseBasedChunkGenerator: biomes (multi-noise climate +
// parameter tree), terrain fill with cell interpolation, aquifers, ore
// veins, and the surface system (surface rules, badlands pillars,
// icebergs). Ported from the vanilla algorithms; the data (density
// functions, noises, surface rule, biome tree) comes from
// world/data/worldgen_overworld.json.
// ============================================================
#pragma once

#include <array>
#include <climits>
#include <cmath>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "density.h"
#include "json.h"
#include "noise.h"
#include "random.h"

namespace vgen {

static constexpr int MIN_Y = -64;
static constexpr int HEIGHT = 384;
static constexpr int MAX_Y = MIN_Y + HEIGHT - 1;
static constexpr int SECTIONS = HEIGHT / 16;
static constexpr int WAY_BELOW_MIN_Y = -2032;
static constexpr int BLOCKS_PER_CHUNK = HEIGHT * 256;

inline int block_index(int lx, int y, int lz) { return (y - MIN_Y) * 256 + lz * 16 + lx; }

// ---------------- SHA-256 (BiomeManager.obfuscateSeed) ----------------
inline void sha256(const uint8_t* msg, size_t len, uint8_t out[32]) {
    static const uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,
        0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
        0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
        0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,
        0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
        0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    uint32_t h[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    std::vector<uint8_t> m(msg, msg + len);
    m.push_back(0x80);
    while (m.size() % 64 != 56) m.push_back(0);
    uint64_t bits = (uint64_t)len * 8;
    for (int i = 7; i >= 0; i--) m.push_back((uint8_t)(bits >> (8 * i)));
    auto rotr = [](uint32_t x, int n) { return (x >> n) | (x << (32 - n)); };
    for (size_t off = 0; off < m.size(); off += 64) {
        uint32_t w[64];
        for (int i = 0; i < 16; i++)
            w[i] = ((uint32_t)m[off + 4 * i] << 24) | ((uint32_t)m[off + 4 * i + 1] << 16) |
                   ((uint32_t)m[off + 4 * i + 2] << 8) | (uint32_t)m[off + 4 * i + 3];
        for (int i = 16; i < 64; i++) {
            uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 64; i++) {
            uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = hh + S1 + ch + k[i] + w[i];
            uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + mj;
            hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
        }
        h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    for (int i = 0; i < 8; i++) for (int j = 0; j < 4; j++) out[i * 4 + j] = (uint8_t)(h[i] >> (24 - 8 * j));
}

// Guava Hashing.sha256().hashLong(seed).asLong(): little-endian in and out.
inline int64_t obfuscate_seed(int64_t seed) {
    uint8_t in[8], out[32];
    for (int i = 0; i < 8; i++) in[i] = (uint8_t)((uint64_t)seed >> (8 * i));
    sha256(in, 8, out);
    uint64_t v = 0;
    for (int i = 7; i >= 0; i--) v = (v << 8) | out[i];
    return (int64_t)v;
}

// ---------------- Biome parameter tree (cubiomes btree20 encoding) ----------------
struct BiomeTree {
    int order = 6;
    std::vector<uint32_t> steps;
    std::vector<int32_t> params;  // [min, max] pairs
    std::vector<uint64_t> nodes;

    void load(const Json& j) {
        order = j["order"].as_int();
        for (auto& v : j["steps"].arr) steps.push_back((uint32_t)v.as_int());
        for (auto& p : j["params"].arr) { params.push_back((int32_t)p[0].as_int()); params.push_back((int32_t)p[1].as_int()); }
        for (auto& n : j["nodes"].arr) nodes.push_back(std::stoull(n.str));
    }
    uint64_t dist(const uint64_t np[6], int idx) const {
        uint64_t ds = 0, node = nodes[idx];
        for (int i = 0; i < 6; i++) {
            int p = (int)((node >> (8 * i)) & 0xFF);
            uint64_t a = np[i] - (uint64_t)(int64_t)params[2 * p + 1];
            uint64_t b = (uint64_t)(int64_t)params[2 * p] - np[i];
            uint64_t d = (int64_t)a > 0 ? a : (int64_t)b > 0 ? b : 0;
            ds += d * d;
        }
        return ds;
    }
    int resulting_node(const uint64_t np[6], int idx, int alt, uint64_t ds, int depth) const {
        if (steps[depth] == 0) return idx;
        uint32_t step;
        do { step = steps[depth]; depth++; } while ((size_t)(idx + step) >= nodes.size());
        uint64_t node = nodes[idx];
        uint32_t inner = (uint32_t)(node >> 48);
        int leaf = alt;
        for (int i = 0; i < order; i++) {
            uint64_t ds_inner = dist(np, (int)inner);
            if (ds_inner < ds) {
                int leaf2 = resulting_node(np, (int)inner, leaf, ds, depth);
                uint64_t ds_leaf2 = ((int)inner == leaf2) ? ds_inner : dist(np, leaf2);
                if (ds_leaf2 < ds) { ds = ds_leaf2; leaf = leaf2; }
            }
            inner += step;
            if (inner >= nodes.size()) break;
        }
        return leaf;
    }
    int lookup(const int64_t target[6]) const {
        uint64_t np[6];
        for (int i = 0; i < 6; i++) np[i] = (uint64_t)target[i];
        int idx = resulting_node(np, 0, 0, (uint64_t)-1, 0);
        return (int)((nodes[idx] >> 48) & 0xFF);
    }
};

// ---------------- Surface rules ----------------
struct VerticalAnchor {
    int kind = 0;  // 0 absolute, 1 above_bottom, 2 below_top
    int value = 0;
    int resolve() const { return kind == 0 ? value : kind == 1 ? MIN_Y + value : MAX_Y - value; }
    static VerticalAnchor parse(const Json& j) {
        VerticalAnchor a;
        if (j.has("absolute")) { a.kind = 0; a.value = j["absolute"].as_int(); }
        else if (j.has("above_bottom")) { a.kind = 1; a.value = j["above_bottom"].as_int(); }
        else if (j.has("below_top")) { a.kind = 2; a.value = j["below_top"].as_int(); }
        return a;
    }
};

enum class SC : uint8_t { Biome, NoiseThreshold, VerticalGradient, YAbove, Water, Temperature, Steep, Not, Hole,
                          AbovePreliminary, StoneDepth };
enum class SR : uint8_t { Block, Sequence, Condition, Bandlands };

struct SurfaceCondition {
    SC t;
    std::vector<int> biomes;     // biome mask ids
    int noise = -1;
    double min = 0, max = 0;
    int random = -1;             // vertical gradient random factory index
    VerticalAnchor a1, a2;
    int mult = 0;
    bool add_stone_depth = false;
    int offset = 0;
    bool add_surface_depth = false;
    int secondary_range = 0;
    bool ceiling = false;
    int inner = -1;              // for Not
    uint64_t biome_mask = 0;
};

struct SurfaceRule {
    SR t;
    int state = 0;
    std::vector<int> children;
    int condition = -1;
    int then = -1;
};

struct BiomeClimate { float temperature = 0.8f; bool frozen = false; bool precipitation = true; };

// Column produced by the noise stage
struct TerrainChunk {
    int chunk_x = 0, chunk_z = 0;
    std::vector<uint16_t> blocks;           // y*256 + z*16 + x
    std::array<uint16_t, SECTIONS * 64> biomes{};
    std::array<int16_t, 256> world_surface{};  // highest non-air y (incl. fluids), MIN_Y-1 if none
    std::array<int16_t, 256> ocean_floor{};    // highest solid (non-fluid) y

    uint16_t get(int lx, int y, int lz) const {
        if (y < MIN_Y || y > MAX_Y) return 0;
        return blocks[block_index(lx, y, lz)];
    }
    void set(int lx, int y, int lz, uint16_t s) {
        if (y < MIN_Y || y > MAX_Y) return;
        blocks[block_index(lx, y, lz)] = s;
    }
    uint16_t biome_at(int lx, int y, int lz) const {
        int qy = (std::max(MIN_Y, std::min(MAX_Y, y)) - MIN_Y) >> 2;
        return biomes[(qy >> 2) * 64 + (qy & 3) * 16 + (lz >> 2) * 4 + (lx >> 2)];
    }
};

class Terrain {
public:
    // block state ids
    int AIR = 0, WATER = 80, LAVA = 96, STONE = 1, DEFAULT_BLOCK = 1, DEFAULT_FLUID = 80;
    int GRANITE, TUFF, COPPER_ORE, DEEPSLATE_IRON_ORE, RAW_COPPER_BLOCK, RAW_IRON_BLOCK;
    int TERRACOTTA, ORANGE_TC, YELLOW_TC, BROWN_TC, RED_TC, WHITE_TC, LIGHT_GRAY_TC;
    int PACKED_ICE, SNOW_BLOCK, ICE;

    int64_t seed = 0;
    int sea_level = 63;
    bool aquifers_enabled = true, ore_veins_enabled = true;
    DensityGraph graph;
    PositionalFactory random;            // RandomState.random
    PositionalFactory aquifer_random, ore_random;
    int r_final, r_initial, r_barrier, r_flood, r_spread, r_lava, r_vein_toggle, r_vein_ridged, r_vein_gap;
    int r_temperature, r_vegetation, r_continents, r_erosion, r_depth, r_ridges;
    BiomeTree biome_tree;
    int64_t biome_zoom_seed = 0;
    std::vector<BiomeClimate> climates;
    std::vector<SurfaceCondition> conditions;
    std::vector<SurfaceRule> rules;
    int surface_root = -1;
    std::vector<PositionalFactory> gradient_randoms;
    int n_surface, n_surface_secondary, n_clay_offset, n_badlands_pillar, n_badlands_roof, n_badlands_surface;
    int n_iceberg_pillar, n_iceberg_roof, n_iceberg_surface;
    std::array<int, 192> clay_bands{};
    std::unique_ptr<PerlinSimplexNoise> temperature_noise, frozen_temperature_noise, biome_info_noise;
    std::vector<std::array<int64_t, 13>> spawn_target;  // 6 [min,max] + offset

    void init(const Json& data, int64_t world_seed, bool deepslate_compat = false) {
        seed = world_seed;
        Xoroshiro base(seed);
        random = fork_positional(base);
        {
            Xoroshiro r = random.from_hash_of("minecraft:aquifer");
            aquifer_random = fork_positional(r);
            Xoroshiro o = random.from_hash_of("minecraft:ore");
            ore_random = fork_positional(o);
        }
        sea_level = data["sea_level"].as_int();
        aquifers_enabled = data["aquifers_enabled"].as_bool();
        ore_veins_enabled = data["ore_veins_enabled"].as_bool();
        DEFAULT_BLOCK = data["default_block"].as_int();
        DEFAULT_FLUID = data["default_fluid"].as_int();
        const Json& b = data["blocks"];
        auto blk = [&](const char* n) { return b[std::string("minecraft:") + n].as_int(); };
        AIR = blk("air"); WATER = blk("water"); LAVA = blk("lava"); STONE = blk("stone");
        GRANITE = blk("granite"); TUFF = blk("tuff"); COPPER_ORE = blk("copper_ore");
        DEEPSLATE_IRON_ORE = blk("deepslate_iron_ore"); RAW_COPPER_BLOCK = blk("raw_copper_block");
        RAW_IRON_BLOCK = blk("raw_iron_block"); TERRACOTTA = blk("terracotta"); ORANGE_TC = blk("orange_terracotta");
        YELLOW_TC = blk("yellow_terracotta"); BROWN_TC = blk("brown_terracotta"); RED_TC = blk("red_terracotta");
        WHITE_TC = blk("white_terracotta"); LIGHT_GRAY_TC = blk("light_gray_terracotta");
        PACKED_ICE = blk("packed_ice"); SNOW_BLOCK = blk("snow_block"); ICE = blk("ice");

        graph.load(data, random, deepslate_compat);
        const Json& router = data["router"];
        r_final = graph.compile(router["final_density"]);
        r_initial = graph.compile(router["initial_density_without_jaggedness"]);
        r_barrier = graph.compile(router["barrier"]);
        r_flood = graph.compile(router["fluid_level_floodedness"]);
        r_spread = graph.compile(router["fluid_level_spread"]);
        r_lava = graph.compile(router["lava"]);
        r_vein_toggle = graph.compile(router["vein_toggle"]);
        r_vein_ridged = graph.compile(router["vein_ridged"]);
        r_vein_gap = graph.compile(router["vein_gap"]);
        r_temperature = graph.compile(router["temperature"]);
        r_vegetation = graph.compile(router["vegetation"]);
        r_continents = graph.compile(router["continents"]);
        r_erosion = graph.compile(router["erosion"]);
        r_depth = graph.compile(router["depth"]);
        r_ridges = graph.compile(router["ridges"]);

        biome_tree.load(data["biome_tree"]);
        biome_zoom_seed = obfuscate_seed(seed);
        for (auto& kv : data["biomes"].obj) {
            int id = std::stoi(kv.first);
            if ((int)climates.size() <= id) climates.resize(id + 1);
            climates[id].temperature = (float)kv.second["temperature"].as_double();
            climates[id].frozen = kv.second["frozen"].as_bool();
            climates[id].precipitation = kv.second["precipitation"].as_bool(true);
        }
        for (auto& p : data["spawn_target"].arr) {
            std::array<int64_t, 13> t{};
            const char* keys[6] = {"temperature", "humidity", "continentalness", "erosion", "depth", "weirdness"};
            for (int i = 0; i < 6; i++) {
                const Json& v = p[keys[i]];
                double lo = v.is_array() ? v[0].as_double() : v.as_double();
                double hi = v.is_array() ? v[1].as_double() : v.as_double();
                t[2 * i] = quantize((float)lo);
                t[2 * i + 1] = quantize((float)hi);
            }
            t[12] = quantize((float)p.get("offset", 0.0));
            spawn_target.push_back(t);
        }

        n_surface = graph.get_noise("minecraft:surface");
        n_surface_secondary = graph.get_noise("minecraft:surface_secondary");
        n_clay_offset = graph.get_noise("minecraft:clay_bands_offset");
        n_badlands_pillar = graph.get_noise("minecraft:badlands_pillar");
        n_badlands_roof = graph.get_noise("minecraft:badlands_pillar_roof");
        n_badlands_surface = graph.get_noise("minecraft:badlands_surface");
        n_iceberg_pillar = graph.get_noise("minecraft:iceberg_pillar");
        n_iceberg_roof = graph.get_noise("minecraft:iceberg_pillar_roof");
        n_iceberg_surface = graph.get_noise("minecraft:iceberg_surface");
        generate_clay_bands();
        {
            LegacyRandom r1(1234), r2(3456), r3(2345);
            temperature_noise = std::make_unique<PerlinSimplexNoise>(r1, std::vector<int>{0});
            frozen_temperature_noise = std::make_unique<PerlinSimplexNoise>(r2, std::vector<int>{-2, -1, 0});
            biome_info_noise = std::make_unique<PerlinSimplexNoise>(r3, std::vector<int>{0});
        }
        surface_root = compile_rule(data["surface_rule"]);
        const Json& ids = data["biome_ids"];
        eroded_badlands_id = ids["minecraft:eroded_badlands"].as_int();
        frozen_ocean_id = ids["minecraft:frozen_ocean"].as_int();
        deep_frozen_ocean_id = ids["minecraft:deep_frozen_ocean"].as_int();
        for (auto& kv : ids.obj) biome_ids[kv.first] = kv.second.as_int();
    }

    std::map<std::string, int> biome_ids;
    int biome_id(const std::string& name) const {
        auto it = biome_ids.find(name);
        return it == biome_ids.end() ? -1 : it->second;
    }

    static int64_t quantize(float f) { return (int64_t)(f * 10000.0f); }

    void new_eval(ChunkEval& ev) const {
        ev.init(graph.slots_interp, graph.slots_flat, graph.slots_2d, graph.slots_once);
        ev.min_y = MIN_Y;
    }

    // ---------------- biomes ----------------
    void climate(int qx, int qy, int qz, ChunkEval* cc, int64_t out[6]) const {
        int x = qx << 2, y = qy << 2, z = qz << 2;
        out[0] = quantize((float)graph.eval(r_temperature, x, y, z, cc, false));
        out[1] = quantize((float)graph.eval(r_vegetation, x, y, z, cc, false));
        out[2] = quantize((float)graph.eval(r_continents, x, y, z, cc, false));
        out[3] = quantize((float)graph.eval(r_erosion, x, y, z, cc, false));
        out[4] = quantize((float)graph.eval(r_depth, x, y, z, cc, false));
        out[5] = quantize((float)graph.eval(r_ridges, x, y, z, cc, false));
    }
    int noise_biome(int qx, int qy, int qz, ChunkEval* cc) const {
        qy = std::max(MIN_Y >> 2, std::min(((MAX_Y + 1) >> 2) - 1, qy));
        int64_t t[6];
        climate(qx, qy, qz, cc, t);
        return biome_tree.lookup(t);
    }

    // BiomeManager.getBiome (fuzzy zoom)
    static int64_t lcg_next(int64_t l, int64_t m) {
        return (int64_t)((uint64_t)l * ((uint64_t)l * 6364136223846793005ULL + 1442695040888963407ULL) + (uint64_t)m);
    }
    static double fiddle(int64_t l) {
        double d = (double)floor_mod((int)(l >> 24), 1024) / 1024.0;
        return (d - 0.5) * 0.9;
    }
    double fiddled_distance(int i, int j, int k, double d, double e, double f) const {
        int64_t s = biome_zoom_seed;
        int64_t m = lcg_next(s, i);
        m = lcg_next(m, j); m = lcg_next(m, k); m = lcg_next(m, i); m = lcg_next(m, j); m = lcg_next(m, k);
        double g = fiddle(m);
        m = lcg_next(m, s);
        double h = fiddle(m);
        m = lcg_next(m, s);
        double n = fiddle(m);
        return (f + n) * (f + n) + (e + h) * (e + h) + (d + g) * (d + g);
    }
    template <class Lookup>
    int zoomed_biome(int x, int y, int z, Lookup&& lookup) const {
        int i = x - 2, j = y - 2, k = z - 2;
        int l = i >> 2, m = j >> 2, n = k >> 2;
        double d = (double)(i & 3) / 4.0, e = (double)(j & 3) / 4.0, f = (double)(k & 3) / 4.0;
        int best = 0;
        double best_dist = INFINITY;
        for (int p = 0; p < 8; p++) {
            bool bx = (p & 4) == 0, by = (p & 2) == 0, bz = (p & 1) == 0;
            int q = bx ? l : l + 1, r = by ? m : m + 1, s = bz ? n : n + 1;
            double h = bx ? d : d - 1.0, t = by ? e : e - 1.0, u = bz ? f : f - 1.0;
            double v = fiddled_distance(q, r, s, h, t, u);
            if (best_dist > v) { best = p; best_dist = v; }
        }
        int qx = (best & 4) == 0 ? l : l + 1;
        int qy = (best & 2) == 0 ? m : m + 1;
        int qz = (best & 1) == 0 ? n : n + 1;
        return lookup(qx, qy, qz);
    }

    // ---------------- biome temperature ----------------
    float base_temperature(int biome) const { return biome < (int)climates.size() ? climates[biome].temperature : 0.8f; }
    float temperature(int biome, int x, int y, int z) const {
        float f = base_temperature(biome);
        if (biome < (int)climates.size() && climates[biome].frozen) {
            double d = frozen_temperature_noise->value((double)x * 0.05, (double)z * 0.05, false) * 7.0;
            double e = biome_info_noise->value((double)x * 0.2, (double)z * 0.2, false);
            if (d + e < 0.3) {
                double h = biome_info_noise->value((double)x * 0.09, (double)z * 0.09, false);
                if (h < 0.8) f = 0.2f;
            }
        }
        if (y > 80) {
            float g = (float)(temperature_noise->value((double)((float)x / 8.0f), (double)((float)z / 8.0f), false) * 8.0);
            return f - (g + (float)y - 80.0f) * 0.05f / 40.0f;
        }
        return f;
    }
    bool cold_enough_to_snow(int biome, int x, int y, int z) const { return !(temperature(biome, x, y, z) >= 0.15f); }

    // ---------------- spawn finder (Climate.findSpawnPosition) ----------------
    int64_t spawn_fitness(int x, int z) const {
        double d = 2500.0 * 2500.0;
        int64_t sq = (int64_t)x * x + (int64_t)z * z;
        int64_t l = (int64_t)((double)(10000.0f * 10000.0f) * std::pow((double)sq / d, 2.0));
        int64_t t[6];
        climate(x >> 2, 0, z >> 2, nullptr, t);
        t[4] = 0;
        int64_t best = INT64_MAX;
        for (auto& p : spawn_target) {
            int64_t f = 0;
            for (int i = 0; i < 6; i++) {
                int64_t lo = p[2 * i], hi = p[2 * i + 1], v = t[i];
                int64_t dist = v - hi > 0 ? v - hi : (lo - v > 0 ? lo - v : 0);
                f += dist * dist;
            }
            f += p[12] * p[12];
            best = std::min(best, f);
        }
        return l + best;
    }
    void find_spawn(int& out_x, int& out_z) const {
        int bx = 0, bz = 0;
        int64_t best = spawn_fitness(0, 0);
        auto radial = [&](float max_r, float step) {
            float h = 0.0f, i = step;
            int cx = bx, cz = bz;
            while (i <= max_r) {
                int j = cx + (int)(std::sin((double)h) * (double)i);
                int k = cz + (int)(std::cos((double)h) * (double)i);
                int64_t f = spawn_fitness(j, k);
                if (f < best) { best = f; bx = j; bz = k; }
                h += step / i;
                if (h > 6.2831855f) { h = 0.0f; i += step; }
            }
        };
        radial(2048.0f, 512.0f);
        radial(512.0f, 32.0f);
        out_x = bx;
        out_z = bz;
    }

    // ---------------- noise stage ----------------
    void generate(int chunk_x, int chunk_z, TerrainChunk& out) const {
        out.chunk_x = chunk_x;
        out.chunk_z = chunk_z;
        out.blocks.assign(BLOCKS_PER_CHUNK, (uint16_t)AIR);
        ChunkEval ev;
        new_eval(ev);
        ev.set_chunk(chunk_x, chunk_z);
        const int min_x = chunk_x * 16, min_z = chunk_z * 16;

        // biomes
        for (int sec = 0; sec < SECTIONS; sec++)
            for (int qy = 0; qy < 4; qy++)
                for (int qz = 0; qz < 4; qz++)
                    for (int qx = 0; qx < 4; qx++)
                        out.biomes[sec * 64 + qy * 16 + qz * 4 + qx] = (uint16_t)noise_biome(
                            (min_x >> 2) + qx, (MIN_Y >> 2) + sec * 4 + qy, (min_z >> 2) + qz, &ev);

        Aquifer aquifer(*this, chunk_x, chunk_z, ev);
        for (int lx = 0; lx < 16; lx++) {
            for (int lz = 0; lz < 16; lz++) {
                int x = min_x + lx, z = min_z + lz;
                for (int y = MAX_Y; y >= MIN_Y; y--) {
                    double density = graph.eval(r_final, x, y, z, &ev, true);
                    int state = aquifer.compute(x, y, z, density);
                    if (state < 0 && ore_veins_enabled) state = ore_vein(x, y, z, ev);
                    if (state < 0) state = DEFAULT_BLOCK;
                    out.blocks[block_index(lx, y, lz)] = (uint16_t)state;
                }
            }
        }
        update_heightmaps(out);
        build_surface(out, ev, aquifer);
        update_heightmaps(out);
    }

    bool is_fluid(int s) const { return s == WATER || s == LAVA; }

    void update_heightmaps(TerrainChunk& c) const {
        for (int lz = 0; lz < 16; lz++)
            for (int lx = 0; lx < 16; lx++) {
                int ws = MIN_Y - 1, of = MIN_Y - 1;
                for (int y = MAX_Y; y >= MIN_Y; y--) {
                    int s = c.blocks[block_index(lx, y, lz)];
                    if (s == AIR) continue;
                    if (ws == MIN_Y - 1) ws = y;
                    if (!is_fluid(s)) { of = y; break; }
                }
                c.world_surface[lz * 16 + lx] = (int16_t)ws;
                c.ocean_floor[lz * 16 + lx] = (int16_t)of;
            }
    }

    // ---------------- ore veins ----------------
    int ore_vein(int x, int y, int z, ChunkEval& ev) const {
        double d = graph.eval(r_vein_toggle, x, y, z, &ev, true);
        bool copper = d > 0.0;
        int max_y = copper ? 50 : -8, min_y = copper ? 0 : -60;
        double e = std::fabs(d);
        int j = max_y - y, k = y - min_y;
        if (k < 0 || j < 0) return -1;
        int l = std::min(j, k);
        double f = clamped_map((double)l, 0.0, 20.0, -0.2, 0.0);
        if (e + f < (double)0.4f) return -1;
        Xoroshiro rs = ore_random.at(x, y, z);
        if (rs.next_float() > 0.7f) return -1;
        if (graph.eval(r_vein_ridged, x, y, z, &ev, true) >= 0.0) return -1;
        double g = clamped_map(e, (double)0.4f, (double)0.6f, (double)0.1f, (double)0.3f);
        if ((double)rs.next_float() < g && graph.eval(r_vein_gap, x, y, z, &ev, true) > (double)-0.3f) {
            bool raw = rs.next_float() < 0.02f;
            if (copper) return raw ? RAW_COPPER_BLOCK : COPPER_ORE;
            return raw ? RAW_IRON_BLOCK : DEEPSLATE_IRON_ORE;
        }
        return copper ? GRANITE : TUFF;
    }

    // ---------------- aquifer (NoiseBasedAquifer) ----------------
    struct FluidStatus { int level; int type; };

    FluidStatus global_fluid(int x, int y, int z) const {
        (void)x; (void)z;
        if (y < std::min(-54, sea_level)) return {-54, LAVA};
        return {sea_level, DEFAULT_FLUID};
    }

    // NoiseChunk.preliminarySurfaceLevel
    int preliminary_surface_level(int x, int z, ChunkEval& ev, std::unordered_map<int64_t, int>& cache) const {
        int qx = (x >> 2) << 2, qz = (z >> 2) << 2;
        int64_t key = ((int64_t)qx << 32) ^ (int64_t)(uint32_t)qz;
        auto it = cache.find(key);
        if (it != cache.end()) return it->second;
        int result = INT_MAX;
        for (int y = MIN_Y + HEIGHT; y >= MIN_Y; y -= 8) {
            if (graph.eval(r_initial, qx, y, qz, &ev, false) > 0.390625) { result = y; break; }
        }
        cache.emplace(key, result);
        return result;
    }

    class Aquifer {
    public:
        Aquifer(const Terrain& t, int chunk_x, int chunk_z, ChunkEval& ev) : t_(t), ev_(ev) {
            min_gx = floor_div(chunk_x * 16, 16) - 1;
            int max_gx = floor_div(chunk_x * 16 + 15, 16) + 1;
            size_x = max_gx - min_gx + 1;
            min_gy = floor_div(MIN_Y, 12) - 1;
            int max_gy = floor_div(MIN_Y + HEIGHT, 12) + 1;
            size_y = max_gy - min_gy + 1;
            min_gz = floor_div(chunk_z * 16, 16) - 1;
            int max_gz = floor_div(chunk_z * 16 + 15, 16) + 1;
            size_z = max_gz - min_gz + 1;
            int n = size_x * size_y * size_z;
            status_cache.assign(n, FluidStatus{0, -1});
            status_ready.assign(n, 0);
            location_cache.assign(n, 0);
            location_ready.assign(n, 0);
        }

        std::unordered_map<int64_t, int> preliminary;

        int compute(int i, int j, int k, double density) {
            if (density > 0.0) return -1;
            if (!t_.aquifers_enabled) {
                FluidStatus g = t_.global_fluid(i, j, k);
                return j < g.level ? g.type : t_.AIR;
            }
            FluidStatus global = t_.global_fluid(i, j, k);
            if (j < global.level && global.type == t_.LAVA) return t_.LAVA;
            int l = floor_div(i - 5, 16), m = floor_div(j + 1, 12), n = floor_div(k - 5, 16);
            int o = INT_MAX, p = INT_MAX, q = INT_MAX;
            int r = 0, s = 0, tt = 0;  // cache indices of the three closest centres
            for (int u = 0; u <= 1; u++)
                for (int v = -1; v <= 1; v++)
                    for (int w = 0; w <= 1; w++) {
                        int x = l + u, y = m + v, z = n + w;
                        int idx = index(x, y, z);
                        if (!location_ready[idx]) {
                            Xoroshiro rs = t_.aquifer_random.at(x, y, z);
                            int lx = x * 16 + rs.next_int(10);
                            int ly = y * 12 + rs.next_int(9);
                            int lz = z * 16 + rs.next_int(10);
                            location_cache[idx] = pack(lx, ly, lz);
                            location_ready[idx] = 1;
                        }
                        int64_t loc = location_cache[idx];
                        int dx = unpack_x(loc) - i, dy = unpack_y(loc) - j, dz = unpack_z(loc) - k;
                        int dist = dx * dx + dy * dy + dz * dz;
                        if (o >= dist) { tt = s; s = r; r = idx; q = p; p = o; o = dist; }
                        else if (p >= dist) { tt = s; s = idx; q = p; p = dist; }
                        else if (q >= dist) { tt = idx; q = dist; }
                    }
            FluidStatus st1 = status(r);
            double e = similarity(o, p);
            int bs = at(st1, j);
            if (e <= 0.0) return bs;
            if (bs == t_.WATER) {
                FluidStatus below = t_.global_fluid(i, j - 1, k);
                if (j - 1 < below.level && below.type == t_.LAVA) return bs;
            }
            double barrier = NAN;
            FluidStatus st2 = status(s);
            double f = e * pressure(i, j, k, barrier, st1, st2);
            if (density + f > 0.0) return -1;
            FluidStatus st3 = status(tt);
            double g = similarity(o, q);
            if (g > 0.0) {
                double h = e * g * pressure(i, j, k, barrier, st1, st3);
                if (density + h > 0.0) return -1;
            }
            double h = similarity(p, q);
            if (h > 0.0) {
                double a = e * h * pressure(i, j, k, barrier, st2, st3);
                if (density + a > 0.0) return -1;
            }
            return bs;
        }

    private:
        const Terrain& t_;
        ChunkEval& ev_;
        int min_gx, min_gy, min_gz, size_x, size_y, size_z;
        std::vector<FluidStatus> status_cache;
        std::vector<char> status_ready;
        std::vector<int64_t> location_cache;
        std::vector<char> location_ready;

        static int64_t pack(int x, int y, int z) {
            return (((int64_t)x & 0x3FFFFFF) << 38) | (((int64_t)z & 0x3FFFFFF) << 12) | ((int64_t)y & 0xFFF);
        }
        static int unpack_x(int64_t p) { return (int)(p >> 38); }
        static int unpack_y(int64_t p) { return (int)((p << 52) >> 52); }
        static int unpack_z(int64_t p) { return (int)((p << 26) >> 38); }

        int index(int x, int y, int z) const {
            return ((y - min_gy) * size_z + (z - min_gz)) * size_x + (x - min_gx);
        }
        static double similarity(int a, int b) { return 1.0 - (double)std::abs(b - a) / 25.0; }
        int at(const FluidStatus& s, int y) const { return y < s.level ? s.type : t_.AIR; }

        double pressure(int x, int y, int z, double& barrier, const FluidStatus& a, const FluidStatus& b) {
            int sa = at(a, y), sb = at(b, y);
            if ((sa == t_.LAVA && sb == t_.WATER) || (sa == t_.WATER && sb == t_.LAVA)) return 2.0;
            int j = std::abs(a.level - b.level);
            if (j == 0) return 0.0;
            double d = 0.5 * (double)(a.level + b.level);
            double e = (double)y + 0.5 - d;
            double f = (double)j / 2.0;
            double o = f - std::fabs(e);
            double q;
            if (e > 0.0) { double p = 0.0 + o; q = p > 0.0 ? p / 1.5 : p / 2.5; }
            else { double p = 3.0 + o; q = p > 0.0 ? p / 3.0 : p / 10.0; }
            double r;
            if (q < -2.0 || q > 2.0) r = 0.0;
            else {
                if (std::isnan(barrier)) barrier = t_.graph.eval(t_.r_barrier, x, y, z, &ev_, true);
                r = barrier;
            }
            return 2.0 * (r + q);
        }

        FluidStatus status(int idx) {
            if (status_ready[idx]) return status_cache[idx];
            int64_t loc = location_cache[idx];
            FluidStatus s = compute_fluid(unpack_x(loc), unpack_y(loc), unpack_z(loc));
            status_cache[idx] = s;
            status_ready[idx] = 1;
            return s;
        }

        FluidStatus compute_fluid(int i, int j, int k) {
            static const int OFFSETS[13][2] = {{0, 0}, {-2, -1}, {-1, -1}, {0, -1}, {1, -1}, {-3, 0}, {-2, 0},
                                               {-1, 0}, {1, 0}, {-2, 1}, {-1, 1}, {0, 1}, {1, 1}};
            FluidStatus fs = t_.global_fluid(i, j, k);
            int l = INT_MAX, m = j + 12, n = j - 12;
            bool bl = false;
            for (auto& off : OFFSETS) {
                int o = i + off[0] * 16, p = k + off[1] * 16;
                int q = t_.preliminary_surface_level(o, p, ev_, preliminary);
                int r = q + 8;
                bool center = off[0] == 0 && off[1] == 0;
                if (center && n > r) return fs;
                bool bl3 = m > r;
                if (bl3 || center) {
                    FluidStatus fs2 = t_.global_fluid(o, r, p);
                    if (at(fs2, r) != t_.AIR) {
                        if (center) bl = true;
                        if (bl3) return fs2;
                    }
                }
                l = std::min(l, q);
            }
            int s = surface_level(i, j, k, fs, l, bl);
            return {s, fluid_type(i, j, k, fs, s)};
        }

        int surface_level(int i, int j, int k, const FluidStatus& fs, int l, bool bl) {
            double d, e;
            double erosion = t_.graph.eval(t_.r_erosion, i, j, k, &ev_, false);
            double depth = t_.graph.eval(t_.r_depth, i, j, k, &ev_, false);
            if (erosion < (double)-0.225f && depth > (double)0.9f) { d = -1.0; e = -1.0; }
            else {
                int m = l + 8 - j;
                double f = bl ? clamped_map((double)m, 0.0, 64.0, 1.0, 0.0) : 0.0;
                double g = clampd(t_.graph.eval(t_.r_flood, i, j, k, &ev_, false), -1.0, 1.0);
                double h = map_range(f, 1.0, 0.0, -0.3, 0.8);
                double nn = map_range(f, 1.0, 0.0, -0.8, 0.4);
                d = g - nn;
                e = g - h;
            }
            if (e > 0.0) return fs.level;
            if (d > 0.0) return randomized_level(i, j, k, l);
            return WAY_BELOW_MIN_Y;
        }

        int randomized_level(int i, int j, int k, int l) {
            int o = floor_div(i, 16), p = floor_div(j, 40), q = floor_div(k, 16);
            int r = p * 40 + 20;
            double d = t_.graph.eval(t_.r_spread, o, p, q, nullptr, false) * 10.0;
            int tq = (int)std::floor(d / 3.0) * 3;
            return std::min(l, r + tq);
        }

        int fluid_type(int i, int j, int k, const FluidStatus& fs, int l) {
            int b = fs.type;
            if (l <= -10 && l != WAY_BELOW_MIN_Y && fs.type != t_.LAVA) {
                int o = floor_div(i, 64), p = floor_div(j, 40), q = floor_div(k, 64);
                double d = t_.graph.eval(t_.r_lava, o, p, q, nullptr, false);
                if (std::fabs(d) > 0.3) b = t_.LAVA;
            }
            return b;
        }
    };

    // ---------------- surface system ----------------
    void generate_clay_bands() {
        Xoroshiro r = random.from_hash_of("minecraft:clay_bands");
        auto& b = clay_bands;
        b.fill(TERRACOTTA);
        for (int i = 0; i < 192; ++i) {
            i += r.next_int(5) + 1;
            if (i < 192) b[i] = ORANGE_TC;
        }
        auto bands = [&](int min_width, int state) {
            int i = r.next_int_between_inclusive(6, 15);
            for (int j = 0; j < i; ++j) {
                int k = min_width + r.next_int(3);
                int l = r.next_int(192);
                for (int m = 0; l + m < 192 && m < k; ++m) b[l + m] = state;
            }
        };
        bands(1, YELLOW_TC);
        bands(2, BROWN_TC);
        bands(1, RED_TC);
        int j = r.next_int_between_inclusive(9, 15);
        int k = 0;
        for (int l = 0; k < j && l < 192; l += r.next_int(16) + 4) {
            b[l] = WHITE_TC;
            if (l - 1 > 0 && r.next_boolean()) b[l - 1] = LIGHT_GRAY_TC;
            if (l + 1 < 192 && r.next_boolean()) b[l + 1] = LIGHT_GRAY_TC;
            ++k;
        }
    }

    int band(int x, int y, int z) const {
        int i = (int)std::floor(graph.noises[n_clay_offset].value((double)x, 0.0, (double)z) * 4.0 + 0.5);
        return clay_bands[floor_mod(y + i + 192, 192)];
    }

    int surface_depth(int x, int z) const {
        double d = graph.noises[n_surface].value((double)x, 0.0, (double)z);
        Xoroshiro r = random.at(x, 0, z);
        return (int)(d * 2.75 + 3.0 + r.next_double() * 0.25);
    }

    int compile_condition(const Json& j) {
        SurfaceCondition c;
        std::string t = j["type"].str;
        if (t == "biome") {
            c.t = SC::Biome;
            for (auto& b : j["biome_is"].arr) c.biome_mask |= (1ULL << b.as_int());
        } else if (t == "noise_threshold") {
            c.t = SC::NoiseThreshold; c.noise = graph.get_noise(j["noise"].str);
            c.min = j["min_threshold"].as_double(); c.max = j["max_threshold"].as_double();
        } else if (t == "vertical_gradient") {
            c.t = SC::VerticalGradient;
            Xoroshiro r = random.from_hash_of(j["random_name"].str);
            gradient_randoms.push_back(fork_positional(r));
            c.random = (int)gradient_randoms.size() - 1;
            c.a1 = VerticalAnchor::parse(j["true_at_and_below"]);
            c.a2 = VerticalAnchor::parse(j["false_at_and_above"]);
        } else if (t == "y_above") {
            c.t = SC::YAbove; c.a1 = VerticalAnchor::parse(j["anchor"]);
            c.mult = j["surface_depth_multiplier"].as_int(); c.add_stone_depth = j["add_stone_depth"].as_bool();
        } else if (t == "water") {
            c.t = SC::Water; c.offset = j["offset"].as_int();
            c.mult = j["surface_depth_multiplier"].as_int(); c.add_stone_depth = j["add_stone_depth"].as_bool();
        } else if (t == "temperature") {
            c.t = SC::Temperature;
        } else if (t == "steep") {
            c.t = SC::Steep;
        } else if (t == "not") {
            c.t = SC::Not; c.inner = compile_condition(j["invert"]);
        } else if (t == "hole") {
            c.t = SC::Hole;
        } else if (t == "above_preliminary_surface") {
            c.t = SC::AbovePreliminary;
        } else if (t == "stone_depth") {
            c.t = SC::StoneDepth; c.offset = j["offset"].as_int();
            c.add_surface_depth = j["add_surface_depth"].as_bool();
            c.secondary_range = j["secondary_depth_range"].as_int();
            c.ceiling = j["surface_type"].str == "ceiling";
        } else {
            throw std::runtime_error("unsupported surface condition: " + t);
        }
        conditions.push_back(c);
        return (int)conditions.size() - 1;
    }

    int compile_rule(const Json& j) {
        SurfaceRule r;
        std::string t = j["type"].str;
        if (t == "block") { r.t = SR::Block; r.state = j["result_state"].as_int(); }
        else if (t == "sequence") {
            r.t = SR::Sequence;
            for (auto& c : j["sequence"].arr) r.children.push_back(compile_rule(c));
        } else if (t == "condition") {
            r.t = SR::Condition;
            r.condition = compile_condition(j["if_true"]);
            r.then = compile_rule(j["then_run"]);
        } else if (t == "bandlands") { r.t = SR::Bandlands; }
        else throw std::runtime_error("unsupported surface rule: " + t);
        rules.push_back(r);
        return (int)rules.size() - 1;
    }

    struct SurfaceContext {
        const Terrain* t;
        TerrainChunk* chunk;
        ChunkEval* ev;
        std::unordered_map<int64_t, int>* preliminary;
        std::unordered_map<int64_t, int>* biome_cache;
        int block_x = 0, block_z = 0, block_y = 0;
        int surface_depth = 0;
        bool secondary_ready = false; double secondary = 0;
        bool min_surface_ready = false; int min_surface = 0;
        int water_height = INT_MIN, stone_depth_below = 0, stone_depth_above = 0;
        bool biome_ready = false; int biome = 0;

        int get_biome() {
            if (!biome_ready) {
                biome = t->zoomed_biome(block_x, block_y, block_z, [&](int qx, int qy, int qz) {
                    qy = std::max(MIN_Y >> 2, std::min(((MAX_Y + 1) >> 2) - 1, qy));
                    int64_t key = ((int64_t)(qx & 0x3FFFFF) << 42) | ((int64_t)(qz & 0x3FFFFF) << 20) | (int64_t)(qy & 0xFFFFF);
                    auto it = biome_cache->find(key);
                    if (it != biome_cache->end()) return it->second;
                    int b = t->noise_biome(qx, qy, qz, ev);
                    biome_cache->emplace(key, b);
                    return b;
                });
                biome_ready = true;
            }
            return biome;
        }
        double get_secondary() {
            if (!secondary_ready) {
                secondary = t->graph.noises[t->n_surface_secondary].value((double)block_x, 0.0, (double)block_z);
                secondary_ready = true;
            }
            return secondary;
        }
        int get_min_surface() {
            if (!min_surface_ready) {
                int i = block_x >> 4, j = block_z >> 4;
                int c0 = t->preliminary_surface_level(i * 16, j * 16, *ev, *preliminary);
                int c1 = t->preliminary_surface_level((i + 1) * 16, j * 16, *ev, *preliminary);
                int c2 = t->preliminary_surface_level(i * 16, (j + 1) * 16, *ev, *preliminary);
                int c3 = t->preliminary_surface_level((i + 1) * 16, (j + 1) * 16, *ev, *preliminary);
                double fx = (double)((float)(block_x & 15) / 16.0f), fz = (double)((float)(block_z & 15) / 16.0f);
                int k = floor_int(lerp2(fx, fz, (double)c0, (double)c1, (double)c2, (double)c3));
                min_surface = k + surface_depth - 8;
                min_surface_ready = true;
            }
            return min_surface;
        }
    };

    bool test(int ci, SurfaceContext& c) const {
        const SurfaceCondition& k = conditions[ci];
        switch (k.t) {
            case SC::Biome: return (k.biome_mask >> c.get_biome()) & 1ULL;
            case SC::NoiseThreshold: {
                double d = graph.noises[k.noise].value((double)c.block_x, 0.0, (double)c.block_z);
                return d >= k.min && d <= k.max;
            }
            case SC::VerticalGradient: {
                int i = k.a1.resolve(), j = k.a2.resolve();
                int y = c.block_y;
                if (y <= i) return true;
                if (y >= j) return false;
                double d = map_range((double)y, (double)i, (double)j, 1.0, 0.0);
                Xoroshiro r = gradient_randoms[k.random].at(c.block_x, y, c.block_z);
                return (double)r.next_float() < d;
            }
            case SC::YAbove:
                return c.block_y + (k.add_stone_depth ? c.stone_depth_above : 0) >= k.a1.resolve() + c.surface_depth * k.mult;
            case SC::Water:
                return c.water_height == INT_MIN ||
                       c.block_y + (k.add_stone_depth ? c.stone_depth_above : 0) >= c.water_height + k.offset + c.surface_depth * k.mult;
            case SC::Temperature:
                return cold_enough_to_snow(c.get_biome(), c.block_x, c.block_y, c.block_z);
            case SC::Steep: {
                int i = c.block_x & 15, j = c.block_z & 15;
                auto h = [&](int x, int z) { return (int)c.chunk->world_surface[z * 16 + x] + 1; };
                int kz = std::max(j - 1, 0), lz = std::min(j + 1, 15);
                int m = h(i, kz), n = h(i, lz);
                if (n >= m + 4) return true;
                int o = std::max(i - 1, 0), p = std::min(i + 1, 15);
                int q = h(o, j), r = h(p, j);
                return q >= r + 4;
            }
            case SC::Not: return !test(k.inner, c);
            case SC::Hole: return c.surface_depth <= 0;
            case SC::AbovePreliminary: return c.block_y >= c.get_min_surface();
            case SC::StoneDepth: {
                int i = k.ceiling ? c.stone_depth_below : c.stone_depth_above;
                int j = k.add_surface_depth ? c.surface_depth : 0;
                int kk = k.secondary_range == 0 ? 0 :
                         (int)map_range(c.get_secondary(), -1.0, 1.0, 0.0, (double)k.secondary_range);
                return i <= 1 + k.offset + j + kk;
            }
        }
        return false;
    }

    int apply(int ri, SurfaceContext& c) const {
        const SurfaceRule& r = rules[ri];
        switch (r.t) {
            case SR::Block: return r.state;
            case SR::Sequence:
                for (int ch : r.children) { int s = apply(ch, c); if (s >= 0) return s; }
                return -1;
            case SR::Condition: return test(r.condition, c) ? apply(r.then, c) : -1;
            case SR::Bandlands: return band(c.block_x, c.block_y, c.block_z);
        }
        return -1;
    }

    bool is_stone(int s) const { return s != AIR && !is_fluid(s); }

    void build_surface(TerrainChunk& chunk, ChunkEval& ev, Aquifer& aquifer) const {
        std::unordered_map<int64_t, int> biome_cache;
        auto& prelim = aquifer.preliminary;
        const int min_x = chunk.chunk_x * 16, min_z = chunk.chunk_z * 16;
        for (int lx = 0; lx < 16; lx++) {
            for (int lz = 0; lz < 16; lz++) {
                int m = min_x + lx, n = min_z + lz;
                int o = chunk.world_surface[lz * 16 + lx] + 2;   // getHeight(WORLD_SURFACE_WG) + 1
                SurfaceContext probe{this, &chunk, &ev, &prelim, &biome_cache};
                probe.block_x = m; probe.block_z = n; probe.block_y = o;
                int column_biome = probe.get_biome();
                if (column_biome == eroded_badlands_id) eroded_badlands(chunk, lx, lz, m, n, o);
                int p = chunk.world_surface[lz * 16 + lx] + 2;

                SurfaceContext c{this, &chunk, &ev, &prelim, &biome_cache};
                c.block_x = m; c.block_z = n;
                c.surface_depth = surface_depth(m, n);
                int q = 0, r = INT_MIN, s = INT_MAX;
                for (int u = std::min(p, MAX_Y + 1); u >= MIN_Y; --u) {
                    int bs = chunk.get(lx, u, lz);
                    if (bs == AIR) { q = 0; r = INT_MIN; continue; }
                    if (is_fluid(bs)) { if (r == INT_MIN) r = u + 1; continue; }
                    if (s >= u) {
                        s = WAY_BELOW_MIN_Y;
                        for (int v = u - 1; v >= MIN_Y - 1; --v) {
                            int b2 = v < MIN_Y ? AIR : chunk.get(lx, v, lz);
                            if (!is_stone(b2)) { s = v + 1; break; }
                        }
                    }
                    int v = u - s + 1;
                    c.stone_depth_above = ++q;
                    c.stone_depth_below = v;
                    c.water_height = r;
                    c.block_y = u;
                    c.biome_ready = false;
                    if (bs != DEFAULT_BLOCK) continue;
                    int st = apply(surface_root, c);
                    if (st >= 0) chunk.set(lx, u, lz, (uint16_t)st);
                }
                if (column_biome == frozen_ocean_id || column_biome == deep_frozen_ocean_id)
                    frozen_ocean(chunk, c.get_min_surface(), column_biome, lx, lz, m, n, o);
            }
        }
    }

    int eroded_badlands_id = -1, frozen_ocean_id = -1, deep_frozen_ocean_id = -1;

    void eroded_badlands(TerrainChunk& chunk, int lx, int lz, int x, int z, int surface_y) const {
        double e = std::min(std::fabs(graph.noises[n_badlands_surface].value((double)x, 0.0, (double)z) * 8.25),
                            graph.noises[n_badlands_pillar].value((double)x * 0.2, 0.0, (double)z * 0.2) * 15.0);
        if (e <= 0.0) return;
        double h = std::fabs(graph.noises[n_badlands_roof].value((double)x * 0.75, 0.0, (double)z * 0.75) * 1.5);
        double l = 64.0 + std::min(e * e * 2.5, std::ceil(h * 50.0) + 24.0);
        int m = floor_int(l);
        if (surface_y > m) return;
        for (int n = m; n >= MIN_Y; --n) {
            int bs = chunk.get(lx, n, lz);
            if (bs == DEFAULT_BLOCK) break;
            if (bs == WATER) return;
        }
        for (int n = m; n >= MIN_Y && chunk.get(lx, n, lz) == AIR; --n) chunk.set(lx, n, lz, (uint16_t)DEFAULT_BLOCK);
        if (chunk.world_surface[lz * 16 + lx] < m) chunk.world_surface[lz * 16 + lx] = (int16_t)m;
    }

    void frozen_ocean(TerrainChunk& chunk, int min_surface, int biome, int lx, int lz, int x, int z, int surface_y) const {
        double e = std::min(std::fabs(graph.noises[n_iceberg_surface].value((double)x, 0.0, (double)z) * 8.25),
                            graph.noises[n_iceberg_pillar].value((double)x * 1.28, 0.0, (double)z * 1.28) * 15.0);
        if (e <= 1.8) return;
        double h = std::fabs(graph.noises[n_iceberg_roof].value((double)x * 1.17, 0.0, (double)z * 1.17) * 1.5);
        double i = std::min(e * e * 1.2, std::ceil(h * 40.0) + 14.0);
        if (temperature(biome, x, 63, z) > 0.1f) i -= 2.0;
        double j;
        if (i > 2.0) { j = (double)sea_level - i - 7.0; i += (double)sea_level; }
        else { i = 0.0; j = 0.0; }
        double k = i;
        Xoroshiro rs = random.at(x, 0, z);
        int l = 2 + rs.next_int(4);
        int m = sea_level + 18 + rs.next_int(10);
        int n = 0;
        for (int o = std::max(surface_y, (int)k + 1); o >= min_surface; --o) {
            int bs = chunk.get(lx, o, lz);
            bool place = (bs == AIR && o < (int)k && rs.next_double() > 0.01) ||
                         (bs == WATER && o > (int)j && o < sea_level && j != 0.0 && rs.next_double() > 0.15);
            if (!place) continue;
            if (n <= l && o > m) { chunk.set(lx, o, lz, (uint16_t)SNOW_BLOCK); ++n; continue; }
            chunk.set(lx, o, lz, (uint16_t)PACKED_ICE);
        }
    }
};

}  // namespace vgen
