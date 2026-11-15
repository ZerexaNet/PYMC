// ============================================================
// PyMC - Overworld decoration (trees, plants, ores, snow)
//
// Vanilla-style feature stage on top of the vanilla noise stage. Shapes
// (trunk/foliage placers, ore blobs, ice spikes) and per-biome densities
// follow the vanilla 1.21.1 placed features; exact block-for-block
// placement is not reproduced (that would need the full feature registry).
//
// Trees may cross chunk borders: every tree is generated deterministically
// from its source chunk using only that chunk's terrain summary, and each
// chunk it touches draws its own part. Everything else stays inside the
// chunk it was placed from.
// ============================================================
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include "terrain.h"

namespace vgen {

struct ChunkSummary {
    int cx = 0, cz = 0;
    std::array<int16_t, 256> floor{};    // highest solid block
    std::array<int16_t, 256> surface{};  // highest non-air block (fluids included)
    std::array<uint16_t, 256> ground{};  // block at floor
    std::array<uint8_t, 256> biome{};    // biome above the floor
};

inline ChunkSummary summarize(const TerrainChunk& c) {
    ChunkSummary s;
    s.cx = c.chunk_x;
    s.cz = c.chunk_z;
    for (int z = 0; z < 16; z++)
        for (int x = 0; x < 16; x++) {
            int i = z * 16 + x;
            s.floor[i] = c.ocean_floor[i];
            s.surface[i] = c.world_surface[i];
            s.ground[i] = c.get(x, c.ocean_floor[i], z);
            s.biome[i] = (uint8_t)c.biome_at(x, c.ocean_floor[i] + 1, z);
        }
    return s;
}

enum class Tree : uint8_t {
    Oak, FancyOak, Birch, TallBirch, Spruce, Pine, MegaSpruce, MegaPine, Jungle, MegaJungle, JungleBush,
    Acacia, DarkOak, SwampOak, Cherry, Mangrove, AzaleaLike
};

struct TreeChoice { Tree tree; float weight; };

struct BiomeDecoration {
    float trees = 0.0f;              // average trees per chunk
    std::vector<TreeChoice> tree_types;
    int grass = 0, tall_grass = 0, ferns = 0, large_ferns = 0, dead_bushes = 0, flowers = 0;
    int flower_set = 0;              // 0 default, 1 plains, 2 forest, 3 flower forest, 4 swamp, 5 meadow
    int cacti = 0, sugar_cane = 0, pumpkins = 0, melons = 0, berries = 0, lily_pads = 0;
    int seagrass = 0, kelp = 0, mushrooms = 0, bamboo = 0, sunflowers = 0, tall_flowers = 0, petals = 0;
    int boulders = 0, huge_mushrooms = 0, ice_spikes = 0, sea_pickles = 0;
    int disks_sand = 0, disks_clay = 0, disks_gravel = 0;
    bool emeralds = false;
    bool trees_on_snow = false;      // grove: SPRUCE_ON_SNOW / PINE_ON_SNOW
};

class Features {
public:
    explicit Features(const Terrain& t) : t_(t) {}

    void init(const Json& data) {
        const Json& st = data["states"];
        auto S = [&](const std::string& key) {
            std::string k = "minecraft:" + key;
            if (!st.has(k)) throw std::runtime_error("missing block state " + k);
            return (uint16_t)st[k].as_int();
        };
        AIR = S("air"); WATER = S("water"); STONE = S("stone"); DEEPSLATE = S("deepslate");
        GRANITE = S("granite"); DIORITE = S("diorite"); ANDESITE = S("andesite"); TUFF = S("tuff");
        DIRT = S("dirt"); GRAVEL = S("gravel"); CLAY = S("clay"); SAND = S("sand"); RED_SAND = S("red_sand");
        GRASS = S("grass_block"); GRASS_SNOWY = S("grass_block[snowy=true]");
        PODZOL = S("podzol"); PODZOL_SNOWY = S("podzol[snowy=true]");
        MYCELIUM = S("mycelium"); MYCELIUM_SNOWY = S("mycelium[snowy=true]");
        COARSE_DIRT = S("coarse_dirt"); ROOTED_DIRT = S("rooted_dirt"); MOSS = S("moss_block"); MUD = S("mud");
        SNOW_LAYER = S("snow[layers=1]"); SNOW_BLOCK = S("snow_block"); ICE = S("ice"); PACKED_ICE = S("packed_ice");
        BLUE_ICE = S("blue_ice"); POWDER_SNOW = S("powder_snow"); TERRACOTTA = S("terracotta");
        SHORT_GRASS = S("short_grass"); FERN = S("fern"); DEAD_BUSH = S("dead_bush");
        TALL_GRASS_L = S("tall_grass[half=lower]"); TALL_GRASS_U = S("tall_grass[half=upper]");
        LARGE_FERN_L = S("large_fern[half=lower]"); LARGE_FERN_U = S("large_fern[half=upper]");
        CACTUS = S("cactus[age=0]"); SUGAR_CANE = S("sugar_cane[age=0]"); PUMPKIN = S("pumpkin"); MELON = S("melon");
        BERRIES = S("sweet_berry_bush[age=3]"); LILY_PAD = S("lily_pad"); SEAGRASS = S("seagrass");
        TALL_SEAGRASS_L = S("tall_seagrass[half=lower]"); TALL_SEAGRASS_U = S("tall_seagrass[half=upper]");
        KELP = S("kelp[age=20]"); KELP_PLANT = S("kelp_plant");
        BROWN_MUSHROOM = S("brown_mushroom"); RED_MUSHROOM = S("red_mushroom");
        MOSSY_COBBLE = S("mossy_cobblestone"); SEA_PICKLE = S("sea_pickle[pickles=3,waterlogged=true]");
        BAMBOO = S("bamboo[age=0,leaves=none,stage=0]"); BAMBOO_SMALL = S("bamboo[age=0,leaves=small,stage=0]");
        BAMBOO_LARGE = S("bamboo[age=0,leaves=large,stage=0]");
        MANGROVE_ROOTS = S("mangrove_roots");
        const char* faces = "down=true,east=true,north=true,south=true,up=true,west=true";
        BROWN_CAP = S(std::string("brown_mushroom_block[") + faces + "]");
        RED_CAP = S(std::string("red_mushroom_block[") + faces + "]");
        STEM = S("mushroom_stem[down=false,east=true,north=true,south=true,up=true,west=true]");
        const char* vine_dirs[4] = {"north", "east", "south", "west"};
        for (int i = 0; i < 4; i++) {
            std::string k = "vine[";
            const char* order[5] = {"east", "north", "south", "up", "west"};
            for (int j = 0; j < 5; j++) {
                if (j) k += ",";
                k += std::string(order[j]) + "=" + (std::string(order[j]) == vine_dirs[i] ? "true" : "false");
            }
            VINE[i] = S(k + "]");
        }
        const char* tall[4] = {"sunflower", "lilac", "rose_bush", "peony"};
        for (int i = 0; i < 4; i++) {
            TALL_FLOWER_L[i] = S(std::string(tall[i]) + "[half=lower]");
            TALL_FLOWER_U[i] = S(std::string(tall[i]) + "[half=upper]");
        }
        const char* flowers[12] = {"dandelion", "poppy", "blue_orchid", "allium", "azure_bluet", "red_tulip",
                                   "orange_tulip", "white_tulip", "pink_tulip", "oxeye_daisy", "cornflower",
                                   "lily_of_the_valley"};
        for (int i = 0; i < 12; i++) FLOWER[i] = S(flowers[i]);
        for (int a = 1; a <= 4; a++) PETALS[a - 1] = S("pink_petals[facing=north,flower_amount=" + std::to_string(a) + "]");
        const char* woods[8] = {"oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "cherry", "mangrove"};
        for (int w = 0; w < 8; w++) {
            LOG_Y[w] = S(std::string(woods[w]) + "_log[axis=y]");
            LOG_X[w] = S(std::string(woods[w]) + "_log[axis=x]");
            LOG_Z[w] = S(std::string(woods[w]) + "_log[axis=z]");
            for (int d = 1; d <= 7; d++)
                LEAVES[w][d - 1] = S(std::string(woods[w]) + "_leaves[distance=" + std::to_string(d) +
                                     ",persistent=false,waterlogged=false]");
        }
        const char* ores[8] = {"coal", "iron", "copper", "gold", "redstone", "lapis", "diamond", "emerald"};
        for (int o = 0; o < 8; o++) {
            std::string a = std::string(ores[o]) + "_ore", b = std::string("deepslate_") + ores[o] + "_ore";
            if (o == 4) { a += "[lit=false]"; b += "[lit=false]"; }
            ORE[o] = S(a);
            DEEP_ORE[o] = S(b);
        }
        for (int i = 0; i < 16; i++) terracotta_like_.insert((uint16_t)(TERRACOTTA));
        build_biome_table();
        for (auto& kv : data["states"].obj) {
            if (kv.first.find("terracotta") != std::string::npos) terracotta_like_.insert((uint16_t)kv.second.as_int());
        }
        terracotta_like_.insert(t_.TERRACOTTA); terracotta_like_.insert(t_.ORANGE_TC); terracotta_like_.insert(t_.YELLOW_TC);
        terracotta_like_.insert(t_.BROWN_TC); terracotta_like_.insert(t_.RED_TC); terracotta_like_.insert(t_.WHITE_TC);
        terracotta_like_.insert(t_.LIGHT_GRAY_TC);
        for (int w = 0; w < 8; w++) {
            for (int d = 0; d < 7; d++) leaves_set_.insert(LEAVES[w][d]);
            logs_set_.insert(LOG_X[w]); logs_set_.insert(LOG_Y[w]); logs_set_.insert(LOG_Z[w]);
        }
        uint16_t plants[] = {SHORT_GRASS, FERN, DEAD_BUSH, TALL_GRASS_L, TALL_GRASS_U, LARGE_FERN_L, LARGE_FERN_U,
                             BROWN_MUSHROOM, RED_MUSHROOM, SNOW_LAYER, BERRIES, PETALS[0], PETALS[1], PETALS[2], PETALS[3]};
        for (auto p : plants) plants_set_.insert(p);
        for (int i = 0; i < 12; i++) plants_set_.insert(FLOWER[i]);
        for (int i = 0; i < 4; i++) { plants_set_.insert(TALL_FLOWER_L[i]); plants_set_.insert(TALL_FLOWER_U[i]); plants_set_.insert(VINE[i]); }
    }

    // ------------------------------------------------------------------
    // Decorate one chunk. ``neighbor(cx, cz)`` returns terrain summaries of
    // the 3x3 neighbourhood (including the chunk itself).
    // ------------------------------------------------------------------
    void decorate(TerrainChunk& c, const std::function<const ChunkSummary&(int, int)>& neighbor) const {
        const ChunkSummary& self = neighbor(c.chunk_x, c.chunk_z);
        place_ores(c, self);
        place_disks(c, self);
        for (int dz = -1; dz <= 1; dz++)
            for (int dx = -1; dx <= 1; dx++)
                place_trees(c, neighbor(c.chunk_x + dx, c.chunk_z + dz));
        place_local_features(c, self);
        place_vegetation(c, self);
        freeze_top_layer(c);
    }

private:
    const Terrain& t_;
    std::map<int, BiomeDecoration> deco_;
    BiomeDecoration empty_deco_;
    std::set<uint16_t> terracotta_like_, leaves_set_, logs_set_, plants_set_;

public:
    uint16_t AIR, WATER, STONE, DEEPSLATE, GRANITE, DIORITE, ANDESITE, TUFF, DIRT, GRAVEL, CLAY, SAND, RED_SAND;
    uint16_t GRASS, GRASS_SNOWY, PODZOL, PODZOL_SNOWY, MYCELIUM, MYCELIUM_SNOWY, COARSE_DIRT, ROOTED_DIRT, MOSS, MUD;
    uint16_t SNOW_LAYER, SNOW_BLOCK, ICE, PACKED_ICE, BLUE_ICE, POWDER_SNOW, TERRACOTTA;
    uint16_t SHORT_GRASS, FERN, DEAD_BUSH, TALL_GRASS_L, TALL_GRASS_U, LARGE_FERN_L, LARGE_FERN_U;
    uint16_t CACTUS, SUGAR_CANE, PUMPKIN, MELON, BERRIES, LILY_PAD, SEAGRASS, TALL_SEAGRASS_L, TALL_SEAGRASS_U;
    uint16_t KELP, KELP_PLANT, BROWN_MUSHROOM, RED_MUSHROOM, MOSSY_COBBLE, SEA_PICKLE;
    uint16_t BAMBOO, BAMBOO_SMALL, BAMBOO_LARGE, MANGROVE_ROOTS, BROWN_CAP, RED_CAP, STEM;
    uint16_t VINE[4], TALL_FLOWER_L[4], TALL_FLOWER_U[4], FLOWER[12], PETALS[4];
    uint16_t LOG_X[8], LOG_Y[8], LOG_Z[8], LEAVES[8][7], ORE[8], DEEP_ORE[8];

private:
    enum Wood { OAK = 0, SPRUCE, BIRCH, JUNGLE, ACACIA, DARK_OAK, CHERRY, MANGROVE };

    // ---------------- helpers ----------------
    Xoroshiro rng(int cx, int cz, uint64_t salt) const {
        uint64_t a = mix_stafford13((uint64_t)t_.seed ^ (salt * 0x9E3779B97F4A7C15ULL));
        uint64_t b = mix_stafford13(a ^ ((uint64_t)(uint32_t)cx << 32 | (uint32_t)cz));
        return Xoroshiro(a ^ 0x5DEECE66DULL, b);
    }
    bool is_dirt(uint16_t s) const {
        return s == GRASS || s == DIRT || s == PODZOL || s == COARSE_DIRT || s == ROOTED_DIRT || s == MOSS ||
               s == MUD || s == MYCELIUM || s == GRASS_SNOWY || s == PODZOL_SNOWY || s == MYCELIUM_SNOWY;
    }
    bool is_sandy(uint16_t s) const { return s == SAND || s == RED_SAND; }
    bool is_leaves(uint16_t s) const { return leaves_set_.count(s) > 0; }
    bool is_log(uint16_t s) const { return logs_set_.count(s) > 0; }
    bool is_plant(uint16_t s) const { return plants_set_.count(s) > 0; }
    bool tree_replaceable(uint16_t s) const { return s == AIR || is_leaves(s) || is_plant(s); }
    const BiomeDecoration& deco(int biome) const {
        auto it = deco_.find(biome);
        return it == deco_.end() ? empty_deco_ : it->second;
    }
    static int tri(Xoroshiro& r, int n) { return r.next_int(n + 1) - r.next_int(n + 1); }

    // ---------------- per-biome decoration table ----------------
    void build_biome_table() {
        auto B = [&](const char* name) -> BiomeDecoration& {
            int id = t_.biome_id(std::string("minecraft:") + name);
            return deco_[id];
        };
        auto set_ocean = [&](const char* name, int seagrass, int kelp, int pickles) {
            auto& d = B(name); d.seagrass = seagrass; d.kelp = kelp; d.sea_pickles = pickles;
            d.disks_sand = 3; d.disks_clay = 1; d.disks_gravel = 1;
        };
        { auto& d = B("plains"); d.trees = 0.05f; d.tree_types = {{Tree::Oak, 0.8f}, {Tree::FancyOak, 0.2f}};
          d.grass = 40; d.tall_grass = 7; d.flowers = 4; d.flower_set = 1; d.pumpkins = 1; d.sugar_cane = 10; }
        { auto& d = B("sunflower_plains"); d = deco_[t_.biome_id("minecraft:plains")]; d.sunflowers = 10; }
        { auto& d = B("meadow"); d.trees = 0.01f; d.tree_types = {{Tree::Birch, 0.5f}, {Tree::FancyOak, 0.5f}};
          d.grass = 60; d.tall_grass = 6; d.flowers = 12; d.flower_set = 5; }
        { auto& d = B("forest"); d.trees = 10.1f; d.tree_types = {{Tree::Oak, 0.7f}, {Tree::Birch, 0.2f}, {Tree::FancyOak, 0.1f}};
          d.grass = 14; d.flowers = 3; d.flower_set = 2; d.mushrooms = 1; d.tall_flowers = 1; d.pumpkins = 1; d.sugar_cane = 6; }
        { auto& d = B("flower_forest"); d.trees = 6.1f; d.tree_types = {{Tree::Oak, 0.6f}, {Tree::Birch, 0.2f}, {Tree::FancyOak, 0.2f}};
          d.grass = 10; d.flowers = 20; d.flower_set = 3; d.tall_flowers = 3; }
        { auto& d = B("birch_forest"); d.trees = 10.1f; d.tree_types = {{Tree::Birch, 1.0f}};
          d.grass = 14; d.flowers = 3; d.flower_set = 2; d.tall_flowers = 1; }
        { auto& d = B("old_growth_birch_forest"); d.trees = 10.1f; d.tree_types = {{Tree::TallBirch, 0.8f}, {Tree::Birch, 0.2f}};
          d.grass = 14; d.flowers = 3; d.flower_set = 2; d.tall_flowers = 1; }
        { auto& d = B("dark_forest"); d.trees = 16.0f;
          d.tree_types = {{Tree::DarkOak, 0.66f}, {Tree::Birch, 0.12f}, {Tree::FancyOak, 0.06f}, {Tree::Oak, 0.16f}};
          d.grass = 14; d.flowers = 2; d.flower_set = 2; d.mushrooms = 2; d.huge_mushrooms = 1; d.tall_flowers = 1; }
        { auto& d = B("taiga"); d.trees = 10.1f; d.tree_types = {{Tree::Spruce, 0.66f}, {Tree::Pine, 0.34f}};
          d.grass = 8; d.ferns = 12; d.large_ferns = 2; d.berries = 1; d.mushrooms = 1; d.pumpkins = 1; d.sugar_cane = 4; }
        { auto& d = B("snowy_taiga"); d = deco_[t_.biome_id("minecraft:taiga")]; }
        { auto& d = B("old_growth_pine_taiga"); d.trees = 10.1f;
          d.tree_types = {{Tree::MegaPine, 0.33f}, {Tree::Spruce, 0.33f}, {Tree::Pine, 0.34f}};
          d.grass = 8; d.ferns = 14; d.large_ferns = 4; d.berries = 1; d.mushrooms = 2; d.boulders = 1; }
        { auto& d = B("old_growth_spruce_taiga"); d.trees = 10.1f;
          d.tree_types = {{Tree::MegaSpruce, 0.33f}, {Tree::Spruce, 0.47f}, {Tree::Pine, 0.2f}};
          d.grass = 8; d.ferns = 14; d.large_ferns = 4; d.berries = 1; d.mushrooms = 2; d.boulders = 1; }
        { auto& d = B("grove"); d.trees = 10.1f; d.tree_types = {{Tree::Spruce, 0.66f}, {Tree::Pine, 0.34f}}; d.trees_on_snow = true; }
        { auto& d = B("snowy_plains"); d.trees = 0.1f; d.tree_types = {{Tree::Spruce, 1.0f}}; d.grass = 2; }
        { auto& d = B("ice_spikes"); d.ice_spikes = 3; }
        { auto& d = B("windswept_hills"); d.trees = 0.1f; d.tree_types = {{Tree::Spruce, 0.66f}, {Tree::Oak, 0.24f}, {Tree::FancyOak, 0.1f}}; d.grass = 6; d.emeralds = true; }
        { auto& d = B("windswept_gravelly_hills"); d = deco_[t_.biome_id("minecraft:windswept_hills")]; }
        { auto& d = B("windswept_forest"); d.trees = 3.1f; d.tree_types = {{Tree::Spruce, 0.66f}, {Tree::Oak, 0.24f}, {Tree::FancyOak, 0.1f}}; d.grass = 6; d.emeralds = true; }
        { auto& d = B("jungle"); d.trees = 50.0f;
          d.tree_types = {{Tree::FancyOak, 0.1f}, {Tree::JungleBush, 0.5f}, {Tree::MegaJungle, 0.13f}, {Tree::Jungle, 0.27f}};
          d.grass = 25; d.ferns = 8; d.flowers = 2; d.melons = 1; d.bamboo = 2; d.sugar_cane = 4; }
        { auto& d = B("sparse_jungle"); d.trees = 2.1f;
          d.tree_types = {{Tree::FancyOak, 0.1f}, {Tree::JungleBush, 0.5f}, {Tree::Jungle, 0.4f}};
          d.grass = 25; d.ferns = 8; d.flowers = 2; d.melons = 1; }
        { auto& d = B("bamboo_jungle"); d.trees = 30.0f;
          d.tree_types = {{Tree::FancyOak, 0.05f}, {Tree::JungleBush, 0.15f}, {Tree::MegaJungle, 0.33f}, {Tree::Jungle, 0.47f}};
          d.grass = 25; d.ferns = 8; d.melons = 1; d.bamboo = 20; }
        { auto& d = B("savanna"); d.trees = 1.1f; d.tree_types = {{Tree::Acacia, 0.8f}, {Tree::Oak, 0.2f}};
          d.grass = 50; d.tall_grass = 7; d.flowers = 2; }
        { auto& d = B("savanna_plateau"); d = deco_[t_.biome_id("minecraft:savanna")]; }
        { auto& d = B("windswept_savanna"); d.trees = 2.1f; d.tree_types = {{Tree::Acacia, 0.8f}, {Tree::Oak, 0.2f}};
          d.grass = 20; d.tall_grass = 4; d.flowers = 2; }
        { auto& d = B("desert"); d.cacti = 4; d.dead_bushes = 4; d.sugar_cane = 13; }
        { auto& d = B("badlands"); d.cacti = 2; d.dead_bushes = 20; d.sugar_cane = 13; }
        { auto& d = B("eroded_badlands"); d = deco_[t_.biome_id("minecraft:badlands")]; }
        { auto& d = B("wooded_badlands"); d.trees = 5.1f; d.tree_types = {{Tree::Oak, 1.0f}}; d.grass = 10; d.dead_bushes = 10; d.cacti = 1; }
        { auto& d = B("swamp"); d.trees = 2.1f; d.tree_types = {{Tree::SwampOak, 1.0f}};
          d.grass = 10; d.flowers = 2; d.flower_set = 4; d.lily_pads = 6; d.seagrass = 40; d.mushrooms = 3;
          d.sugar_cane = 10; d.disks_clay = 1; d.disks_sand = 1; }
        { auto& d = B("mangrove_swamp"); d.trees = 8.0f; d.tree_types = {{Tree::Mangrove, 1.0f}};
          d.grass = 4; d.lily_pads = 4; d.seagrass = 40; d.disks_clay = 1; }
        { auto& d = B("cherry_grove"); d.trees = 10.1f; d.tree_types = {{Tree::Cherry, 1.0f}};
          d.grass = 20; d.petals = 6; d.flowers = 1; d.flower_set = 5; d.emeralds = true; }
        { auto& d = B("mushroom_fields"); d.huge_mushrooms = 1; d.mushrooms = 3; }
        { auto& d = B("river"); d.seagrass = 48; d.sugar_cane = 10; d.disks_sand = 3; d.disks_clay = 1; d.disks_gravel = 1; }
        { auto& d = B("frozen_river"); d.disks_sand = 1; d.disks_gravel = 1; }
        { auto& d = B("beach"); d.sugar_cane = 0; }
        set_ocean("ocean", 48, 16, 0);
        set_ocean("deep_ocean", 48, 16, 0);
        set_ocean("cold_ocean", 32, 16, 0);
        set_ocean("deep_cold_ocean", 40, 16, 0);
        set_ocean("lukewarm_ocean", 80, 12, 0);
        set_ocean("deep_lukewarm_ocean", 80, 12, 0);
        set_ocean("warm_ocean", 80, 0, 2);
        set_ocean("frozen_ocean", 0, 0, 0);
        set_ocean("deep_frozen_ocean", 0, 0, 0);
        for (const char* n : {"stony_peaks", "jagged_peaks", "frozen_peaks", "snowy_slopes", "meadow", "grove"})
            B(n).emeralds = true;
    }

    // ---------------- ores ----------------
    struct OreConfig { int ore; int size; float discard; float count; int rarity; bool trapezoid; int lo, hi; };

    void place_ores(TerrainChunk& c, const ChunkSummary& s) const {
        // vanilla 1.21.1 overworld ore placements (size, discard on air exposure, count, height)
        static const OreConfig ORES[] = {
            {0, 17, 0.0f, 30, 0, false, 136, 320},   // ore_coal_upper
            {0, 17, 0.5f, 20, 0, true, 0, 192},      // ore_coal_lower
            {1, 9, 0.0f, 90, 0, true, 80, 384},      // ore_iron_upper
            {1, 9, 0.0f, 10, 0, true, -24, 56},      // ore_iron_middle
            {1, 4, 0.0f, 10, 0, false, -64, 72},     // ore_iron_small
            {3, 9, 0.5f, 4, 0, true, -64, 32},       // ore_gold
            {3, 9, 0.5f, 0.5f, 0, false, -64, -48},  // ore_gold_lower
            {4, 8, 0.0f, 4, 0, false, -64, 15},      // ore_redstone
            {4, 8, 0.0f, 8, 0, true, -96, -32},      // ore_redstone_lower
            {6, 4, 0.5f, 7, 0, true, -144, 16},      // ore_diamond
            {6, 12, 0.7f, 1, 9, true, -144, 16},     // ore_diamond_large
            {6, 8, 1.0f, 4, 0, true, -144, 16},      // ore_diamond_buried
            {5, 7, 0.0f, 2, 0, true, -32, 32},       // ore_lapis
            {5, 7, 1.0f, 4, 0, false, -64, 64},      // ore_lapis_buried
            {2, 10, 0.0f, 16, 0, true, -16, 112},    // ore_copper
        };
        static const OreConfig STONES[] = {
            {100, 33, 0.0f, 7, 0, false, 0, 160},    // ore_dirt
            {101, 33, 0.0f, 14, 0, false, -64, 320}, // ore_gravel
            {102, 64, 0.0f, 1, 6, false, 64, 128},   // ore_granite_upper
            {102, 64, 0.0f, 2, 0, false, 0, 60},     // ore_granite_lower
            {103, 64, 0.0f, 1, 6, false, 64, 128},   // ore_diorite_upper
            {103, 64, 0.0f, 2, 0, false, 0, 60},     // ore_diorite_lower
            {104, 64, 0.0f, 1, 6, false, 64, 128},   // ore_andesite_upper
            {104, 64, 0.0f, 2, 0, false, 0, 60},     // ore_andesite_lower
            {105, 64, 0.0f, 2, 0, false, -64, 0},    // ore_tuff
        };
        Xoroshiro r = rng(c.chunk_x, c.chunk_z, 1);
        for (const auto& o : STONES) place_ore_config(c, r, o);
        for (const auto& o : ORES) place_ore_config(c, r, o);
        // emeralds in mountain biomes (ore_emerald: size 3, count 100, trapezoid -16..480)
        const BiomeDecoration& d = deco(s.biome[8 * 16 + 8]);
        if (d.emeralds) place_ore_config(c, r, {7, 3, 0.0f, 100, 0, true, -16, 480});
    }

    void place_ore_config(TerrainChunk& c, Xoroshiro& r, const OreConfig& o) const {
        int count = (int)o.count;
        if (r.next_float() < o.count - (float)count) count++;
        if (o.rarity > 0 && r.next_int(o.rarity) != 0) count = 0;
        for (int i = 0; i < count; i++) {
            int x = r.next_int(16), z = r.next_int(16), y;
            if (o.trapezoid) {
                int k = o.hi - o.lo, l = k / 2, m = k - l;
                y = o.lo + r.next_int_between_inclusive(0, m) + r.next_int_between_inclusive(0, l);
            } else {
                y = r.next_int_between_inclusive(o.lo, o.hi);
            }
            if (y < MIN_Y || y > MAX_Y) continue;
            ore_blob(c, r, x, y, z, o);
        }
    }

    bool replace_ore(TerrainChunk& c, int lx, int y, int lz, const OreConfig& o, Xoroshiro& r) const {
        uint16_t cur = c.get(lx, y, lz);
        uint16_t place = 0;
        bool stone = cur == STONE || cur == GRANITE || cur == DIORITE || cur == ANDESITE;
        bool deep = cur == DEEPSLATE || cur == TUFF;
        if (o.ore >= 100) {
            if (!stone) return false;
            switch (o.ore) {
                case 100: place = DIRT; break;
                case 101: place = GRAVEL; break;
                case 102: place = GRANITE; break;
                case 103: place = DIORITE; break;
                case 104: place = ANDESITE; break;
                case 105: place = TUFF; break;
            }
            if (o.ore == 105 && !(cur == STONE || cur == DEEPSLATE)) return false;
        } else if (stone) {
            place = ORE[o.ore];
        } else if (deep) {
            place = DEEP_ORE[o.ore];
        } else {
            return false;
        }
        if (o.discard > 0.0f && exposed_to_air(c, lx, y, lz) && r.next_float() < o.discard) return false;
        c.set(lx, y, lz, place);
        return true;
    }

    bool exposed_to_air(const TerrainChunk& c, int lx, int y, int lz) const {
        static const int D[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
        for (auto& d : D) {
            int x = lx + d[0], yy = y + d[1], z = lz + d[2];
            if (x < 0 || x > 15 || z < 0 || z > 15) continue;
            uint16_t b = c.get(x, yy, z);
            if (b == AIR) return true;
        }
        return false;
    }

    // OreFeature: a chain of spheres along a random line segment
    void ore_blob(TerrainChunk& c, Xoroshiro& r, int ox, int oy, int oz, const OreConfig& o) const {
        float f = r.next_float() * 3.1415927f;
        float g = (float)o.size / 8.0f;
        double d = ox + std::sin(f) * g, e = ox - std::sin(f) * g;
        double h = oz + std::cos(f) * g, j = oz - std::cos(f) * g;
        double l = oy + r.next_int(3) - 2, m = oy + r.next_int(3) - 2;
        std::vector<std::array<double, 4>> balls(o.size);
        for (int k = 0; k < o.size; k++) {
            float fl = (float)k / (float)o.size;
            double w = r.next_double() * o.size / 16.0;
            double rad = ((double)(std::sin(3.1415927f * fl) + 1.0f) * w + 1.0) / 2.0;
            balls[k] = {lerp(fl, d, e), lerp(fl, l, m), lerp(fl, h, j), rad};
        }
        std::set<std::tuple<int, int, int>> done;
        for (auto& b : balls) {
            double radius = b[3] / 2.0 + 0.5;
            int x0 = floor_int(b[0] - radius), x1 = floor_int(b[0] + radius);
            int y0 = floor_int(b[1] - radius), y1 = floor_int(b[1] + radius);
            int z0 = floor_int(b[2] - radius), z1 = floor_int(b[2] + radius);
            for (int x = x0; x <= x1; x++) {
                double dx = (x + 0.5 - b[0]) / (b[3] / 2.0);
                if (dx * dx >= 1.0 || x < 0 || x > 15) continue;
                for (int y = y0; y <= y1; y++) {
                    double dy = (y + 0.5 - b[1]) / (b[3] / 2.0);
                    if (dx * dx + dy * dy >= 1.0 || y < MIN_Y || y > MAX_Y) continue;
                    for (int z = z0; z <= z1; z++) {
                        double dz = (z + 0.5 - b[2]) / (b[3] / 2.0);
                        if (dx * dx + dy * dy + dz * dz >= 1.0 || z < 0 || z > 15) continue;
                        if (!done.insert({x, y, z}).second) continue;
                        replace_ore(c, x, y, z, o, r);
                    }
                }
            }
        }
    }

    // ---------------- disks (sand / clay / gravel on water bottoms) ----------------
    void place_disks(TerrainChunk& c, const ChunkSummary& s) const {
        Xoroshiro r = rng(c.chunk_x, c.chunk_z, 2);
        const BiomeDecoration& d = deco(s.biome[8 * 16 + 8]);
        auto disk = [&](uint16_t block, int count, int rmin, int rmax, std::vector<uint16_t> targets) {
            for (int n = 0; n < count; n++) {
                int x = r.next_int(16), z = r.next_int(16);
                int radius = r.next_int_between_inclusive(rmin, rmax);
                int y = s.floor[z * 16 + x];
                if (s.surface[z * 16 + x] <= y) continue;  // must be under water
                for (int dx = -radius; dx <= radius; dx++)
                    for (int dz = -radius; dz <= radius; dz++) {
                        if (dx * dx + dz * dz > radius * radius) continue;
                        int lx = x + dx, lz = z + dz;
                        if (lx < 0 || lx > 15 || lz < 0 || lz > 15) continue;
                        for (int dy = -2; dy <= 1; dy++) {
                            uint16_t cur = c.get(lx, y + dy, lz);
                            if (std::find(targets.begin(), targets.end(), cur) != targets.end())
                                c.set(lx, y + dy, lz, block);
                        }
                    }
            }
        };
        disk(SAND, d.disks_sand, 2, 6, {DIRT, GRASS});
        disk(CLAY, d.disks_clay, 2, 3, {DIRT, CLAY});
        disk(GRAVEL, d.disks_gravel, 2, 5, {DIRT, GRASS});
    }

    // ---------------- trees ----------------
    struct TreeBlocks {
        std::vector<std::array<int, 4>> logs;      // x, y, z, state
        std::vector<std::array<int, 3>> leaves;
        std::vector<std::array<int, 4>> extras;    // vines, roots, ...
        std::vector<std::array<int, 3>> dirt;
        int wood = OAK;
    };

    void place_trees(TerrainChunk& target, const ChunkSummary& src) const {
        Xoroshiro r = rng(src.cx, src.cz, 3);
        const BiomeDecoration& center = deco(src.biome[8 * 16 + 8]);
        float avg = center.trees;
        int count = (int)avg;
        if (r.next_float() < avg - (float)count) count++;
        for (int n = 0; n < count; n++) {
            int x = r.next_int(15), z = r.next_int(15);  // 0..14 keeps 2x2 trunks inside the chunk
            int i = z * 16 + x;
            const BiomeDecoration& d = deco(src.biome[i]);
            Xoroshiro tr = rng(src.cx * 64 + x, src.cz * 64 + z, 1000 + n);
            if (d.tree_types.empty()) continue;
            Tree kind = pick_tree(tr, d);
            int y = src.floor[i];
            uint16_t ground = src.ground[i];
            bool submerged = src.surface[i] > y;
            if (kind == Tree::Mangrove) {
                if (!(is_dirt(ground) || ground == MUD || ground == CLAY)) continue;
                if (submerged && src.surface[i] - y > 3) continue;
            } else {
                bool snow_ok = d.trees_on_snow && (ground == SNOW_BLOCK || ground == POWDER_SNOW);
                if (submerged || !(is_dirt(ground) || snow_ok)) continue;
            }
            bool two_by_two = kind == Tree::MegaSpruce || kind == Tree::MegaPine || kind == Tree::MegaJungle || kind == Tree::DarkOak;
            if (two_by_two) {
                bool ok = true;
                for (int dz = 0; dz <= 1 && ok; dz++)
                    for (int dx = 0; dx <= 1 && ok; dx++) {
                        int j = (z + dz) * 16 + (x + dx);
                        if (src.floor[j] != y || src.surface[j] != y || !is_dirt(src.ground[j])) ok = false;
                    }
                if (!ok) {
                    if (kind == Tree::DarkOak) kind = Tree::Oak;
                    else if (kind == Tree::MegaJungle) kind = Tree::Jungle;
                    else kind = Tree::Spruce;
                }
            }
            TreeBlocks tb;
            int wx = src.cx * 16 + x, wz = src.cz * 16 + z;
            if (!grow_tree(kind, tr, wx, y + 1, wz, tb)) continue;
            commit_tree(target, tb);
        }
    }

    Tree pick_tree(Xoroshiro& r, const BiomeDecoration& d) const {
        float total = 0;
        for (auto& c : d.tree_types) total += c.weight;
        float v = r.next_float() * total;
        for (auto& c : d.tree_types) {
            if (v < c.weight) return c.tree;
            v -= c.weight;
        }
        return d.tree_types.back().tree;
    }

    void log(TreeBlocks& tb, int x, int y, int z, int axis = 1) const {
        int s = axis == 0 ? LOG_X[tb.wood] : axis == 2 ? LOG_Z[tb.wood] : LOG_Y[tb.wood];
        tb.logs.push_back({x, y, z, s});
    }
    void leaf(TreeBlocks& tb, int x, int y, int z) const { tb.leaves.push_back({x, y, z}); }

    // FoliagePlacer.placeLeavesRow with a skip predicate
    template <class Skip>
    void leaves_row(TreeBlocks& tb, int cx, int cy, int cz, int radius, int y_off, bool two, Skip&& skip) const {
        int k = two ? 1 : 0;
        for (int dx = -radius; dx <= radius + k; dx++)
            for (int dz = -radius; dz <= radius + k; dz++) {
                int ax = two ? std::min(std::abs(dx), std::abs(dx - 1)) : std::abs(dx);
                int az = two ? std::min(std::abs(dz), std::abs(dz - 1)) : std::abs(dz);
                if (skip(ax, y_off, az, radius)) continue;
                leaf(tb, cx + dx, cy + y_off, cz + dz);
            }
    }

    void blob_foliage(TreeBlocks& tb, Xoroshiro& r, int x, int top, int z, int radius, int height) const {
        for (int j = 0; j >= -height; --j) {
            int k = std::max(radius - 1 - j / 2, 0);
            leaves_row(tb, x, top, z, k, j, false, [&](int ax, int y, int az, int rad) {
                return ax == rad && az == rad && (r.next_int(2) == 0 || y == 0);
            });
        }
    }

    bool grow_tree(Tree kind, Xoroshiro& r, int x, int y, int z, TreeBlocks& tb) const {
        auto straight = [&](int base, int ra, int rb) { return base + r.next_int(ra + 1) + r.next_int(rb + 1); };
        int h = 0;
        switch (kind) {
            case Tree::Oak: case Tree::Birch: case Tree::TallBirch: case Tree::SwampOak: case Tree::Jungle: {
                tb.wood = kind == Tree::Birch || kind == Tree::TallBirch ? BIRCH : kind == Tree::Jungle ? JUNGLE : OAK;
                if (kind == Tree::Oak) h = straight(4, 2, 0);
                else if (kind == Tree::Birch) h = straight(5, 2, 0);
                else if (kind == Tree::TallBirch) h = straight(5, 2, 6);
                else if (kind == Tree::SwampOak) h = straight(5, 3, 0);
                else h = straight(4, 8, 0);
                if (y + h + 2 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                for (int i = 0; i < h; i++) log(tb, x, y + i, z);
                blob_foliage(tb, r, x, y + h, z, kind == Tree::SwampOak ? 3 : 2, 3);
                if (kind == Tree::SwampOak || kind == Tree::Jungle) add_vines(tb, r, kind == Tree::SwampOak ? 4 : 2);
                return true;
            }
            case Tree::FancyOak: {
                tb.wood = OAK;
                h = 5 + r.next_int(8);
                if (y + h + 4 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                for (int i = 0; i < h; i++) log(tb, x, y + i, z);
                int branches = 2 + r.next_int(3);
                std::vector<std::array<int, 3>> ends = {{x, y + h, z}};
                for (int b = 0; b < branches; b++) {
                    double ang = r.next_double() * 6.283185307179586;
                    int len = 2 + r.next_int(3);
                    int by = y + h / 2 + r.next_int(std::max(1, h / 2));
                    int ex = x, ez = z, ey = by;
                    for (int s = 1; s <= len; s++) {
                        ex = x + (int)std::lround(std::cos(ang) * s);
                        ez = z + (int)std::lround(std::sin(ang) * s);
                        ey = by + s / 2;
                        log(tb, ex, ey, ez, std::abs(std::cos(ang)) > std::abs(std::sin(ang)) ? 0 : 2);
                    }
                    ends.push_back({ex, ey, ez});
                }
                for (auto& e : ends)
                    for (int dy = -1; dy <= 2; dy++) {
                        int rad = dy == -1 || dy == 2 ? 2 : 3;
                        for (int dx = -rad; dx <= rad; dx++)
                            for (int dz = -rad; dz <= rad; dz++)
                                if (dx * dx + dz * dz <= rad * rad - (dy == 2 ? 1 : 0)) leaf(tb, e[0] + dx, e[1] + dy, e[2] + dz);
                    }
                return true;
            }
            case Tree::Spruce: {
                tb.wood = SPRUCE;
                h = straight(5, 2, 1);
                if (y + h + 2 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                int trunk_cut = 1 + r.next_int(2);
                for (int i = 0; i < h - trunk_cut + 1 && i < h; i++) log(tb, x, y + i, z);
                for (int i = h - trunk_cut + 1; i < h; i++) log(tb, x, y + i, z);
                int radius = 2 + r.next_int(2), offset = r.next_int(3);
                int fh = std::max(4, h - (1 + r.next_int(2)));
                int top = y + h;
                int l = r.next_int(2), m = 1, nn = 0;
                for (int o = offset; o >= -fh; --o) {
                    leaves_row(tb, x, top, z, l, o, false, [](int ax, int, int az, int rad) {
                        return ax == rad && az == rad && rad > 0;
                    });
                    if (l >= m) { l = nn; nn = 1; m = std::min(m + 1, radius); }
                    else ++l;
                }
                return true;
            }
            case Tree::Pine: {
                tb.wood = SPRUCE;
                h = straight(6, 4, 0);
                if (y + h + 2 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                for (int i = 0; i < h; i++) log(tb, x, y + i, z);
                int fh = 3 + r.next_int(2), offset = 1, radius = 1;
                int top = y + h, l = 0;
                for (int m = offset; m >= offset - fh; --m) {
                    leaves_row(tb, x, top, z, l, m, false, [](int ax, int, int az, int rad) {
                        return ax == rad && az == rad && rad > 0;
                    });
                    if (l >= 1 && m == offset - fh + 1) --l;
                    else if (l < radius) ++l;
                }
                return true;
            }
            case Tree::MegaSpruce: case Tree::MegaPine: {
                tb.wood = SPRUCE;
                h = straight(13, 2, 14);
                if (y + h + 2 > MAX_Y) return false;
                for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) tb.dirt.push_back({x + dx, y - 1, z + dz});
                for (int i = 0; i < h; i++)
                    for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) log(tb, x + dx, y + i, z + dz);
                int crown = kind == Tree::MegaSpruce ? 13 + r.next_int(5) : 3 + r.next_int(5);
                int top = y + h, prev = 0;
                for (int n = top - crown; n <= top; ++n) {
                    int o = top - n;
                    int p = floor_int((double)((float)o / (float)crown * 3.5f));
                    int q = (o > 0 && p == prev && (n & 1) == 0) ? p + 1 : p;
                    leaves_row(tb, x, n, z, q, 0, true, [](int ax, int, int az, int rad) {
                        return ax + az >= 7 || ax * ax + az * az > rad * rad;
                    });
                    prev = p;
                }
                return true;
            }
            case Tree::MegaJungle: {
                tb.wood = JUNGLE;
                h = straight(10, 2, 19);
                if (y + h + 3 > MAX_Y) return false;
                for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) tb.dirt.push_back({x + dx, y - 1, z + dz});
                for (int i = 0; i < h; i++)
                    for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) log(tb, x + dx, y + i, z + dz);
                for (int i = h - 2 - r.next_int(4); i > h / 2; i -= 2 + r.next_int(4)) {
                    double ang = r.next_double() * 6.283185307179586;
                    int bx = x, bz = z;
                    for (int s = 0; s < 5; s++) {
                        bx = x + (int)(1.5 + std::cos(ang) * s);
                        bz = z + (int)(1.5 + std::sin(ang) * s);
                        log(tb, bx, y + i - 3 + s / 2, bz, std::abs(std::cos(ang)) > std::abs(std::sin(ang)) ? 0 : 2);
                    }
                    int ty = y + i - 3 + 2;
                    for (int dy = 0; dy >= -1; dy--) {
                        int rad = 2 - dy;
                        for (int dx = -rad; dx <= rad; dx++)
                            for (int dz = -rad; dz <= rad; dz++)
                                if (dx * dx + dz * dz <= rad * rad) leaf(tb, bx + dx, ty + dy + 1, bz + dz);
                    }
                }
                for (int dy = 0; dy >= -2; dy--) {
                    int rad = 3 - dy / 2 + (dy == 0 ? 0 : 1);
                    for (int dx = -rad; dx <= rad + 1; dx++)
                        for (int dz = -rad; dz <= rad + 1; dz++) {
                            int ax = std::min(std::abs(dx), std::abs(dx - 1)), az = std::min(std::abs(dz), std::abs(dz - 1));
                            if (ax * ax + az * az <= rad * rad) leaf(tb, x + dx, y + h + dy, z + dz);
                        }
                }
                add_vines(tb, r, 3);
                return true;
            }
            case Tree::JungleBush: {
                tb.wood = JUNGLE;
                tb.dirt.push_back({x, y - 1, z});
                log(tb, x, y, z);
                for (int dy = 0; dy <= 2; dy++) {
                    int rad = 2 - dy;
                    for (int dx = -rad; dx <= rad; dx++)
                        for (int dz = -rad; dz <= rad; dz++)
                            if (!(std::abs(dx) == rad && std::abs(dz) == rad && rad > 0 && r.next_int(2) == 0))
                                leaf(tb, x + dx, y + dy, z + dz);
                }
                tb.wood = JUNGLE;
                tb.extras.push_back({x, y, z, -OAK - 1});  // marker: bush uses oak leaves
                return true;
            }
            case Tree::Acacia: {
                tb.wood = ACACIA;
                h = straight(5, 2, 2);
                if (y + h + 2 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                static const int DIRS[4][2] = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};
                int d1 = r.next_int(4);
                int j = h - r.next_int(4) - 1, k = 3 - r.next_int(3);
                int l = x, m = z, top1 = -1000;
                for (int o = 0; o < h; ++o) {
                    int p = y + o;
                    if (o >= j && k > 0) { l += DIRS[d1][0]; m += DIRS[d1][1]; --k; }
                    log(tb, l, p, m);
                    top1 = p + 1;
                }
                std::vector<std::array<int, 4>> attach = {{l, top1, m, 1}};
                l = x; m = z;
                int d2 = r.next_int(4);
                if (d2 != d1) {
                    int p = j - r.next_int(2) - 1, q = 1 + r.next_int(3), top2 = -1000;
                    for (int rr = p; rr < h && q > 0; ++rr, --q) {
                        if (rr < 1) continue;
                        int s = y + rr;
                        l += DIRS[d2][0]; m += DIRS[d2][1];
                        log(tb, l, s, m);
                        top2 = s + 1;
                    }
                    if (top2 > -1000) attach.push_back({l, top2, m, 0});
                }
                for (auto& a : attach) {
                    int rad = 2 + a[3];
                    auto skip = [](int ax, int yo, int az, int rr) {
                        if (yo == 0) return (ax > 1 || az > 1) && ax != 0 && az != 0;
                        return ax == rr && az == rr && rr > 0;
                    };
                    leaves_row(tb, a[0], a[1], a[2], rad, -1, false, skip);
                    leaves_row(tb, a[0], a[1], a[2], rad - 1, 0, false, skip);
                }
                return true;
            }
            case Tree::DarkOak: {
                tb.wood = DARK_OAK;
                h = straight(6, 2, 1);
                if (y + h + 2 > MAX_Y) return false;
                for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) tb.dirt.push_back({x + dx, y - 1, z + dz});
                int lean_dir = r.next_int(4);
                static const int DIRS[4][2] = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};
                int lean_start = h - r.next_int(4), lean = 2 - r.next_int(3);
                int cx = x, cz = z;
                for (int i = 0; i < h; i++) {
                    if (i >= lean_start && lean > 0) { cx += DIRS[lean_dir][0]; cz += DIRS[lean_dir][1]; --lean; }
                    for (int dx = 0; dx <= 1; dx++) for (int dz = 0; dz <= 1; dz++) log(tb, cx + dx, y + i, cz + dz);
                }
                int top = y + h;
                for (int dy = -2; dy <= 0; dy++) {
                    int rad = dy == 0 ? 2 : 3;
                    for (int dx = -rad; dx <= rad + 1; dx++)
                        for (int dz = -rad; dz <= rad + 1; dz++) {
                            int ax = std::min(std::abs(dx), std::abs(dx - 1)), az = std::min(std::abs(dz), std::abs(dz - 1));
                            if (ax == rad && az == rad) continue;
                            if (dy == -2 && ax + az > 3 && r.next_int(3) == 0) continue;
                            leaf(tb, cx + dx, top + dy, cz + dz);
                        }
                }
                for (int b = 0; b < 2 + r.next_int(3); b++) {
                    int bx = cx + r.next_int(6) - 2, bz = cz + r.next_int(6) - 2;
                    int bl = 1 + r.next_int(3);
                    for (int i = 0; i < bl; i++) log(tb, bx, top - 2 - i, bz);
                    for (int dx = -1; dx <= 1; dx++) for (int dz = -1; dz <= 1; dz++) leaf(tb, bx + dx, top - 1, bz + dz);
                }
                return true;
            }
            case Tree::Cherry: {
                tb.wood = CHERRY;
                h = 7 + r.next_int(2);
                if (y + h + 3 > MAX_Y) return false;
                tb.dirt.push_back({x, y - 1, z});
                int trunk = std::max(3, h - 3 - r.next_int(2));
                for (int i = 0; i < trunk; i++) log(tb, x, y + i, z);
                int branches = 1 + r.next_int(2);
                std::vector<std::array<int, 3>> tops;
                int d0 = r.next_int(4);
                static const int DIRS[4][2] = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};
                for (int b = 0; b < branches; b++) {
                    int d = (d0 + b * 2) % 4;
                    int len = 2 + r.next_int(2);
                    int bx = x, bz = z, by = y + trunk - 1;
                    for (int s = 1; s <= len; s++) {
                        bx += DIRS[d][0]; bz += DIRS[d][1];
                        log(tb, bx, by, bz, DIRS[d][0] != 0 ? 0 : 2);
                    }
                    for (int s = 1; s <= h - trunk; s++) log(tb, bx, by + s, bz);
                    tops.push_back({bx, by + h - trunk + 1, bz});
                }
                if (branches == 1) {
                    for (int i = trunk; i < h; i++) log(tb, x, y + i, z);
                    tops.push_back({x, y + h, z});
                }
                for (auto& tp : tops)
                    for (int dy = -3; dy <= 1; dy++) {
                        int rad = dy == 1 ? 2 : dy == -3 ? 3 : 4;
                        for (int dx = -rad; dx <= rad; dx++)
                            for (int dz = -rad; dz <= rad; dz++) {
                                double dd = dx * dx + dz * dz;
                                if (dd > rad * rad + 1) continue;
                                if (dd > (rad - 1) * (rad - 1) && r.next_int(4) == 0) continue;
                                leaf(tb, tp[0] + dx, tp[1] + dy, tp[2] + dz);
                                if (dy == -3 && dd > (rad - 1) * (rad - 1) && r.next_int(6) == 0)
                                    leaf(tb, tp[0] + dx, tp[1] + dy - 1, tp[2] + dz);
                            }
                    }
                return true;
            }
            case Tree::Mangrove: {
                tb.wood = MANGROVE;
                int lift = 1 + r.next_int(3);
                h = 4 + r.next_int(4);
                if (y + lift + h + 3 > MAX_Y) return false;
                int base = y + lift;
                for (int i = 0; i < h; i++) log(tb, x, base + i, z);
                static const int DIRS[4][2] = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};
                for (int d = 0; d < 4; d++) {
                    if (r.next_int(4) == 0) continue;
                    int rx = x, rz = z;
                    for (int s = lift; s >= -1; s--) {
                        if (s < lift - 1 || r.next_int(2) == 0) { rx += DIRS[d][0]; rz += DIRS[d][1]; }
                        tb.extras.push_back({rx, y + s, rz, MANGROVE_ROOTS});
                    }
                }
                for (int s = 0; s < lift; s++) tb.extras.push_back({x, y + s, z, MANGROVE_ROOTS});
                int top = base + h;
                for (int dy = -2; dy <= 1; dy++) {
                    int rad = dy == 1 ? 2 : 3;
                    for (int dx = -rad; dx <= rad; dx++)
                        for (int dz = -rad; dz <= rad; dz++) {
                            if (dx * dx + dz * dz > rad * rad) continue;
                            if (std::abs(dx) == rad && std::abs(dz) == rad) continue;
                            leaf(tb, x + dx, top + dy, z + dz);
                        }
                }
                add_vines(tb, r, 2);
                return true;
            }
            case Tree::AzaleaLike:
                return false;
        }
        return false;
    }

    void add_vines(TreeBlocks& tb, Xoroshiro& r, int chance) const {
        std::set<std::tuple<int, int, int>> occupied;
        for (auto& l : tb.leaves) occupied.insert({l[0], l[1], l[2]});
        for (auto& l : tb.logs) occupied.insert({l[0], l[1], l[2]});
        static const int D[4][2] = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};
        std::vector<std::array<int, 3>> sources(tb.leaves.begin(), tb.leaves.end());
        for (auto& l : sources) {
            for (int d = 0; d < 4; d++) {
                if (r.next_int(chance) != 0) continue;
                int vx = l[0] + D[d][0], vz = l[2] + D[d][1];
                if (occupied.count({vx, l[1], vz})) continue;
                // the vine attaches to the face of the leaves it hangs from
                int facing = (d + 2) % 4;
                int len = 1 + r.next_int(4);
                for (int s = 0; s < len; s++) {
                    if (occupied.count({vx, l[1] - s, vz})) break;
                    tb.extras.push_back({vx, l[1] - s, vz, VINE[facing]});
                }
            }
        }
    }

    void commit_tree(TerrainChunk& c, const TreeBlocks& tb) const {
        const int minx = c.chunk_x * 16, minz = c.chunk_z * 16;
        auto inside = [&](int x, int z) { return x >= minx && x < minx + 16 && z >= minz && z < minz + 16; };
        bool bush_oak = false;
        for (auto& e : tb.extras) if (e[3] == -OAK - 1) bush_oak = true;
        int leaf_wood = bush_oak ? OAK : tb.wood;

        // leaf distance to the nearest log (vanilla updates leaves this way)
        std::unordered_map<int64_t, int> dist;
        auto key = [](int x, int y, int z) { return ((int64_t)(x & 0xFFFFF) << 40) | ((int64_t)(z & 0xFFFFF) << 20) | (int64_t)(y & 0xFFFFF); };
        std::set<int64_t> leaf_keys;
        for (auto& l : tb.leaves) leaf_keys.insert(key(l[0], l[1], l[2]));
        std::vector<std::array<int, 4>> queue;
        for (auto& l : tb.logs) queue.push_back({l[0], l[1], l[2], 0});
        size_t head = 0;
        static const int D[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
        while (head < queue.size()) {
            auto q = queue[head++];
            if (q[3] >= 7) continue;
            for (auto& d : D) {
                int nx = q[0] + d[0], ny = q[1] + d[1], nz = q[2] + d[2];
                int64_t k = key(nx, ny, nz);
                if (!leaf_keys.count(k) || dist.count(k)) continue;
                dist[k] = q[3] + 1;
                queue.push_back({nx, ny, nz, q[3] + 1});
            }
        }
        for (auto& d : tb.dirt) {
            if (!inside(d[0], d[2])) continue;
            uint16_t cur = c.get(d[0] - minx, d[1], d[2] - minz);
            if (cur == GRASS || cur == MYCELIUM || cur == PODZOL || cur == GRASS_SNOWY) c.set(d[0] - minx, d[1], d[2] - minz, DIRT);
        }
        for (auto& l : tb.logs) {
            if (!inside(l[0], l[2])) continue;
            uint16_t cur = c.get(l[0] - minx, l[1], l[2] - minz);
            if (tree_replaceable(cur) || cur == WATER) c.set(l[0] - minx, l[1], l[2] - minz, (uint16_t)l[3]);
        }
        for (auto& l : tb.leaves) {
            if (!inside(l[0], l[2])) continue;
            uint16_t cur = c.get(l[0] - minx, l[1], l[2] - minz);
            if (!(cur == AIR || is_plant(cur))) continue;
            auto it = dist.find(key(l[0], l[1], l[2]));
            int d = it == dist.end() ? 7 : it->second;
            c.set(l[0] - minx, l[1], l[2] - minz, LEAVES[leaf_wood][d - 1]);
        }
        for (auto& e : tb.extras) {
            if (e[3] < 0 || !inside(e[0], e[2])) continue;
            uint16_t cur = c.get(e[0] - minx, e[1], e[2] - minz);
            if (cur == AIR || (e[3] == MANGROVE_ROOTS && (cur == WATER || is_plant(cur))))
                c.set(e[0] - minx, e[1], e[2] - minz, (uint16_t)e[3]);
        }
    }

    // ---------------- in-chunk large features ----------------
    void place_local_features(TerrainChunk& c, const ChunkSummary& s) const {
        Xoroshiro r = rng(c.chunk_x, c.chunk_z, 4);
        const BiomeDecoration& d = deco(s.biome[8 * 16 + 8]);
        for (int n = 0; n < d.huge_mushrooms; n++) {
            if (d.trees > 0 && r.next_int(3) != 0) continue;  // dark forest: rarer than trees
            int x = 3 + r.next_int(10), z = 3 + r.next_int(10);
            huge_mushroom(c, r, x, z);
        }
        for (int n = 0; n < d.boulders; n++) {
            int x = 2 + r.next_int(12), z = 2 + r.next_int(12);
            boulder(c, r, x, z);
        }
        for (int n = 0; n < d.ice_spikes; n++) {
            int x = 4 + r.next_int(8), z = 4 + r.next_int(8);
            ice_spike(c, r, x, z);
        }
    }

    int top_solid(const TerrainChunk& c, int x, int z) const {
        for (int y = MAX_Y; y > MIN_Y; y--) {
            uint16_t b = c.get(x, y, z);
            if (b != AIR && !is_plant(b) && !is_leaves(b)) return y;
        }
        return MIN_Y;
    }

    void huge_mushroom(TerrainChunk& c, Xoroshiro& r, int x, int z) const {
        int y = top_solid(c, x, z);
        uint16_t ground = c.get(x, y, z);
        if (!is_dirt(ground) || c.get(x, y + 1, z) != AIR) return;
        bool red = r.next_int(2) == 0;
        int h = 4 + r.next_int(3) + (r.next_int(12) == 0 ? 3 : 0);
        if (y + h + 2 > MAX_Y) return;
        for (int i = 1; i <= h; i++) c.set(x, y + i, z, STEM);
        int top = y + h;
        if (red) {
            for (int dy = -3; dy <= 0; dy++) {
                int rad = dy == 0 ? 1 : 2;
                for (int dx = -rad; dx <= rad; dx++)
                    for (int dz = -rad; dz <= rad; dz++) {
                        bool edge = std::abs(dx) == rad || std::abs(dz) == rad;
                        if (dy < 0 && !edge) continue;
                        if (dy < 0 && std::abs(dx) == rad && std::abs(dz) == rad) continue;
                        int px = x + dx, pz = z + dz;
                        if (px < 0 || px > 15 || pz < 0 || pz > 15) continue;
                        if (c.get(px, top + dy, pz) == AIR) c.set(px, top + dy, pz, RED_CAP);
                    }
            }
            if (c.get(x, top + 1, z) == AIR) c.set(x, top + 1, z, RED_CAP);
        } else {
            for (int dx = -3; dx <= 3; dx++)
                for (int dz = -3; dz <= 3; dz++) {
                    if (std::abs(dx) == 3 && std::abs(dz) == 3) continue;
                    int px = x + dx, pz = z + dz;
                    if (px < 0 || px > 15 || pz < 0 || pz > 15) continue;
                    if (c.get(px, top + 1, pz) == AIR) c.set(px, top + 1, pz, BROWN_CAP);
                }
        }
    }

    void boulder(TerrainChunk& c, Xoroshiro& r, int x, int z) const {
        int y = top_solid(c, x, z);
        if (!is_dirt(c.get(x, y, z)) && c.get(x, y, z) != STONE) return;
        for (int n = 0; n < 3; n++) {
            int rx = r.next_int(2), ry = r.next_int(2), rz = r.next_int(2);
            float radius = (float)(rx + ry + rz) * 0.333f + 0.5f;
            for (int dx = -rx - 1; dx <= rx + 1; dx++)
                for (int dy = -ry - 1; dy <= ry + 1; dy++)
                    for (int dz = -rz - 1; dz <= rz + 1; dz++) {
                        if ((float)(dx * dx + dy * dy + dz * dz) > radius * radius) continue;
                        int px = x + dx, pz = z + dz;
                        if (px < 0 || px > 15 || pz < 0 || pz > 15) continue;
                        c.set(px, y + 1 + dy, pz, MOSSY_COBBLE);
                    }
            x += r.next_int(3) - 1; z += r.next_int(3) - 1; y += r.next_int(2) - 1;
            x = std::max(1, std::min(14, x)); z = std::max(1, std::min(14, z));
        }
    }

    void ice_spike(TerrainChunk& c, Xoroshiro& r, int x, int z) const {
        int y = top_solid(c, x, z);
        if (c.get(x, y, z) != SNOW_BLOCK) return;
        y += r.next_int(4);
        int i = r.next_int(4) + 7, j = i / 4 + r.next_int(2);
        if (j > 1 && r.next_int(60) == 0) y += 10 + r.next_int(30);
        if (y + i > MAX_Y) return;
        auto ok = [&](uint16_t b) { return b == AIR || is_dirt(b) || b == SNOW_BLOCK || b == ICE; };
        for (int k = 0; k < i; ++k) {
            float f = (1.0f - (float)k / (float)i) * (float)j;
            int l = (int)std::ceil(f);
            for (int m = -l; m <= l; ++m) {
                float g = (float)std::abs(m) - 0.25f;
                for (int n = -l; n <= l; ++n) {
                    float h = (float)std::abs(n) - 0.25f;
                    if (((m == 0 && n == 0) || !(g * g + h * h > f * f)) &&
                        ((m != -l && m != l && n != -l && n != l) || !(r.next_float() > 0.75f))) {
                        int px = x + m, pz = z + n;
                        if (px < 0 || px > 15 || pz < 0 || pz > 15) continue;
                        if (ok(c.get(px, y + k, pz))) c.set(px, y + k, pz, PACKED_ICE);
                        if (k != 0 && l > 1 && ok(c.get(px, y - k, pz))) c.set(px, y - k, pz, PACKED_ICE);
                    }
                }
            }
        }
    }

    // ---------------- small vegetation (stays inside the chunk) ----------------
    void place_vegetation(TerrainChunk& c, const ChunkSummary& s) const {
        Xoroshiro r = rng(c.chunk_x, c.chunk_z, 5);
        // Patches are attempted from biome-specific settings sampled at their centre.
        auto patch = [&](int tries, int spread, const std::function<void(int, int, int)>& place) {
            int ox = r.next_int(16), oz = r.next_int(16);
            for (int n = 0; n < tries; n++) {
                int x = ox + tri(r, spread), z = oz + tri(r, spread);
                if (x < 0 || x > 15 || z < 0 || z > 15) continue;
                place(x, z, s.biome[z * 16 + x]);
            }
        };
        auto surface_y = [&](int x, int z) {
            int y = s.floor[z * 16 + x];
            // trees may have covered the column: stay on the terrain floor
            return y;
        };
        auto on_dirt = [&](int x, int z, uint16_t plant) {
            int y = surface_y(x, z);
            if (s.surface[z * 16 + x] != y) return false;
            if (!is_dirt(c.get(x, y, z)) || c.get(x, y + 1, z) != AIR) return false;
            c.set(x, y + 1, z, plant);
            return true;
        };
        auto tall_on_dirt = [&](int x, int z, uint16_t lower, uint16_t upper) {
            int y = surface_y(x, z);
            if (s.surface[z * 16 + x] != y) return;
            if (!is_dirt(c.get(x, y, z)) || c.get(x, y + 1, z) != AIR || c.get(x, y + 2, z) != AIR) return;
            c.set(x, y + 1, z, lower);
            c.set(x, y + 2, z, upper);
        };
        const BiomeDecoration& d = deco(s.biome[8 * 16 + 8]);
        auto flower_for = [&](int set, int x, int z) -> uint16_t {
            // flower selection, loosely following vanilla's flower_* features
            double n = t_.graph.noises[t_.n_surface].value((c.chunk_x * 16 + x) / 48.0, 0.0, (c.chunk_z * 16 + z) / 48.0);
            switch (set) {
                case 1: return n > 0.2 ? FLOWER[4 + r.next_int(6)] : FLOWER[r.next_int(2)];
                case 2: return FLOWER[r.next_int(2)] ;
                case 3: { static const int F[] = {0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11}; return FLOWER[F[r.next_int(11)]]; }
                case 4: return FLOWER[2];
                case 5: { static const int F[] = {4, 9, 10, 3, 1, 0}; return FLOWER[F[r.next_int(6)]]; }
                default: return FLOWER[r.next_int(2)];
            }
        };

        for (int i = 0; i < d.grass; i++) patch(1, 0, [&](int x, int z, int b) {
            const BiomeDecoration& bd = deco(b);
            on_dirt(x, z, (bd.ferns > 0 && r.next_int(4) == 0) ? FERN : SHORT_GRASS);
        });
        for (int i = 0; i < d.ferns; i++) patch(1, 0, [&](int x, int z, int) { on_dirt(x, z, FERN); });
        for (int i = 0; i < d.tall_grass; i++) patch(1, 0, [&](int x, int z, int) { tall_on_dirt(x, z, TALL_GRASS_L, TALL_GRASS_U); });
        for (int i = 0; i < d.large_ferns; i++) patch(1, 0, [&](int x, int z, int) { tall_on_dirt(x, z, LARGE_FERN_L, LARGE_FERN_U); });
        for (int i = 0; i < d.flowers; i++) {
            int set = d.flower_set;
            patch(12, 3, [&](int x, int z, int) { on_dirt(x, z, flower_for(set, x, z)); });
        }
        for (int i = 0; i < d.tall_flowers; i++) {
            int kind = 1 + r.next_int(3);
            patch(8, 3, [&](int x, int z, int) { tall_on_dirt(x, z, TALL_FLOWER_L[kind], TALL_FLOWER_U[kind]); });
        }
        for (int i = 0; i < d.sunflowers; i++) patch(4, 2, [&](int x, int z, int) { tall_on_dirt(x, z, TALL_FLOWER_L[0], TALL_FLOWER_U[0]); });
        for (int i = 0; i < d.petals; i++) patch(10, 3, [&](int x, int z, int) { on_dirt(x, z, PETALS[r.next_int(4)]); });
        for (int i = 0; i < d.mushrooms; i++) {
            if (r.next_int(4) != 0) continue;
            uint16_t m = r.next_int(2) ? BROWN_MUSHROOM : RED_MUSHROOM;
            patch(8, 3, [&](int x, int z, int) { on_dirt(x, z, m); });
        }
        if (d.berries && r.next_int(8) == 0) patch(12, 3, [&](int x, int z, int) { on_dirt(x, z, BERRIES); });
        if (d.pumpkins && r.next_int(32) == 0) patch(12, 3, [&](int x, int z, int) { on_dirt(x, z, PUMPKIN); });
        if (d.melons && r.next_int(6) == 0) patch(12, 3, [&](int x, int z, int) { on_dirt(x, z, MELON); });

        for (int i = 0; i < d.dead_bushes; i++) patch(1, 0, [&](int x, int z, int) {
            int y = surface_y(x, z);
            uint16_t g = c.get(x, y, z);
            if (s.surface[z * 16 + x] != y || c.get(x, y + 1, z) != AIR) return;
            if (is_sandy(g) || terracotta_like_.count(g) || is_dirt(g)) c.set(x, y + 1, z, DEAD_BUSH);
        });
        for (int i = 0; i < d.cacti; i++) patch(4, 2, [&](int x, int z, int) {
            int y = surface_y(x, z);
            if (s.surface[z * 16 + x] != y || !is_sandy(c.get(x, y, z))) return;
            int h = 1 + r.next_int(r.next_int(3) + 1);
            for (int k = 1; k <= h; k++) {
                if (c.get(x, y + k, z) != AIR) break;
                bool free = true;
                static const int D[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
                for (auto& dd : D) {
                    int nx = x + dd[0], nz = z + dd[1];
                    if (nx >= 0 && nx < 16 && nz >= 0 && nz < 16 && c.get(nx, y + k, nz) != AIR) free = false;
                }
                if (!free) break;
                c.set(x, y + k, z, CACTUS);
            }
        });
        for (int i = 0; i < d.sugar_cane; i++) patch(2, 2, [&](int x, int z, int) {
            int y = surface_y(x, z);
            uint16_t g = c.get(x, y, z);
            if (s.surface[z * 16 + x] != y || !(is_dirt(g) || is_sandy(g))) return;
            bool water = false;
            static const int D[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
            for (auto& dd : D) {
                int nx = x + dd[0], nz = z + dd[1];
                if (nx >= 0 && nx < 16 && nz >= 0 && nz < 16 && c.get(nx, y, nz) == WATER) water = true;
            }
            if (!water) return;
            int h = 2 + r.next_int(r.next_int(3) + 1);
            for (int k = 1; k <= h && c.get(x, y + k, z) == AIR; k++) c.set(x, y + k, z, SUGAR_CANE);
        });
        for (int i = 0; i < d.bamboo; i++) patch(6, 3, [&](int x, int z, int) {
            int y = surface_y(x, z);
            uint16_t g = c.get(x, y, z);
            if (s.surface[z * 16 + x] != y || !(is_dirt(g) || is_sandy(g) || g == GRAVEL)) return;
            int h = 5 + r.next_int(10);
            for (int k = 1; k <= h; k++) {
                if (c.get(x, y + k, z) != AIR) return;
            }
            for (int k = 1; k <= h; k++) c.set(x, y + k, z, k >= h - 1 ? BAMBOO_LARGE : k == h - 2 ? BAMBOO_SMALL : BAMBOO);
            if (g == GRASS || g == DIRT) c.set(x, y, z, PODZOL);
        });
        for (int i = 0; i < d.lily_pads; i++) patch(10, 3, [&](int x, int z, int) {
            int sy = s.surface[z * 16 + x];
            if (sy <= s.floor[z * 16 + x] || c.get(x, sy, z) != WATER || c.get(x, sy + 1, z) != AIR) return;
            c.set(x, sy + 1, z, LILY_PAD);
        });
        int seagrass = d.seagrass;
        for (int i = 0; i < seagrass; i++) patch(1, 0, [&](int x, int z, int) {
            int y = s.floor[z * 16 + x], sy = s.surface[z * 16 + x];
            if (sy <= y + 1 || c.get(x, y + 1, z) != WATER) return;
            uint16_t g = c.get(x, y, z);
            if (!(is_sandy(g) || g == GRAVEL || is_dirt(g) || g == CLAY)) return;
            if (sy > y + 2 && r.next_int(4) == 0 && c.get(x, y + 2, z) == WATER) {
                c.set(x, y + 1, z, TALL_SEAGRASS_L);
                c.set(x, y + 2, z, TALL_SEAGRASS_U);
            } else {
                c.set(x, y + 1, z, SEAGRASS);
            }
        });
        for (int i = 0; i < d.kelp; i++) patch(1, 0, [&](int x, int z, int) {
            int y = s.floor[z * 16 + x], sy = s.surface[z * 16 + x];
            if (sy - y < 4 || c.get(x, y + 1, z) != WATER) return;
            int h = 1 + r.next_int(std::max(1, sy - y - 2));
            h = std::min(h, 1 + r.next_int(10));
            for (int k = 1; k <= h; k++) {
                if (c.get(x, y + k, z) != WATER) break;
                c.set(x, y + k, z, k == h ? KELP : KELP_PLANT);
            }
        });
        for (int i = 0; i < d.sea_pickles; i++) patch(6, 3, [&](int x, int z, int) {
            int y = s.floor[z * 16 + x];
            if (s.surface[z * 16 + x] <= y + 1 || c.get(x, y + 1, z) != WATER) return;
            if (r.next_int(3) == 0) c.set(x, y + 1, z, SEA_PICKLE);
        });
    }

    // ---------------- freeze_top_layer ----------------
    bool blocks_motion(uint16_t b) const {
        if (b == AIR || is_plant(b) || b == SUGAR_CANE || b == LILY_PAD || b == SEAGRASS || b == TALL_SEAGRASS_L ||
            b == TALL_SEAGRASS_U)
            return false;
        return true;
    }

    bool snow_can_survive_on(uint16_t below) const {
        if (below == ICE || below == PACKED_ICE || below == BLUE_ICE || below == WATER || below == AIR) return false;
        if (below == CACTUS || below == SNOW_LAYER || below == BAMBOO || below == BAMBOO_SMALL || below == BAMBOO_LARGE)
            return false;
        if (is_plant(below) || below == SUGAR_CANE || below == LILY_PAD || below == SEAGRASS || below == KELP ||
            below == KELP_PLANT || below == MANGROVE_ROOTS || below == SEA_PICKLE)
            return false;
        for (int i = 0; i < 4; i++) if (below == VINE[i]) return false;
        if (below == t_.LAVA) return false;
        return true;
    }

    void freeze_top_layer(TerrainChunk& c) const {
        std::unordered_map<int64_t, int> biome_cache;
        ChunkEval ev;
        t_.new_eval(ev);
        ev.set_chunk(c.chunk_x, c.chunk_z);
        const int minx = c.chunk_x * 16, minz = c.chunk_z * 16;
        for (int z = 0; z < 16; z++)
            for (int x = 0; x < 16; x++) {
                int k = MIN_Y;
                for (int y = MAX_Y; y >= MIN_Y; y--) {
                    if (blocks_motion(c.get(x, y, z))) { k = y + 1; break; }
                }
                if (k > MAX_Y) continue;
                int wx = minx + x, wz = minz + z;
                int biome = t_.zoomed_biome(wx, k, wz, [&](int qx, int qy, int qz) {
                    int lqx = qx - (minx >> 2), lqz = qz - (minz >> 2);
                    int cqy = std::max(MIN_Y >> 2, std::min(((MAX_Y + 1) >> 2) - 1, qy));
                    if (lqx >= 0 && lqx < 4 && lqz >= 0 && lqz < 4) {
                        int sec = (cqy - (MIN_Y >> 2)) >> 2, iy = (cqy - (MIN_Y >> 2)) & 3;
                        return (int)c.biomes[sec * 64 + iy * 16 + lqz * 4 + lqx];
                    }
                    int64_t key = ((int64_t)(qx & 0x3FFFFF) << 42) | ((int64_t)(qz & 0x3FFFFF) << 20) | (int64_t)(cqy & 0xFFFFF);
                    auto it = biome_cache.find(key);
                    if (it != biome_cache.end()) return it->second;
                    int b = t_.noise_biome(qx, cqy, qz, &ev);
                    biome_cache.emplace(key, b);
                    return b;
                });
                uint16_t below = c.get(x, k - 1, z);
                if (below == WATER && t_.cold_enough_to_snow(biome, wx, k - 1, wz)) {
                    c.set(x, k - 1, z, ICE);
                    below = ICE;
                }
                if (t_.cold_enough_to_snow(biome, wx, k, wz) && c.get(x, k, z) == AIR && snow_can_survive_on(below)) {
                    c.set(x, k, z, SNOW_LAYER);
                    if (below == GRASS) c.set(x, k - 1, z, GRASS_SNOWY);
                    else if (below == PODZOL) c.set(x, k - 1, z, PODZOL_SNOWY);
                    else if (below == MYCELIUM) c.set(x, k - 1, z, MYCELIUM_SNOWY);
                }
            }
    }
};

}  // namespace vgen
