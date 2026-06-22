// ============================================================
// PyMC - Light Propagation Engine
//
// Implements proper Minecraft 1.21.1 light propagation:
//   - Sky light: BFS flood-fill from top down through
//     air/transparent blocks
//   - Block light: BFS flood-fill from light sources outward
//   - Handles light-blocking and light-filtering blocks
//   - Incremental updates: only recalculate when blocks change
//
// Light levels are stored per-subchunk (16x16x16 sections),
// with boundary sections for seamless inter-chunk transitions.
// ============================================================

#ifndef PYMC_LIGHT_ENGINE_H
#define PYMC_LIGHT_ENGINE_H

#include <cstdint>
#include <vector>
#include <deque>
#include <unordered_set>
#include <unordered_map>
#include <array>
#include <functional>

namespace pymc {

// -----------------------------------------------------------
// Constants
// -----------------------------------------------------------
constexpr int SECTION_SIZE = 16;
constexpr int CHUNK_SECTIONS = 24;      // 384 / 16
constexpr int LIGHT_SECTIONS = 26;      // CHUNK_SECTIONS + 2 boundary sections
constexpr int MAX_LIGHT = 15;
constexpr int MIN_Y = -64;

// -----------------------------------------------------------
// Block light properties
// -----------------------------------------------------------
enum class LightType : uint8_t {
    TRANSPARENT = 0,   // Air, glass, etc. — light passes through fully
    FILTER = 1,        // Water, leaves, etc. — light decreases by 1 extra
    OPAQUE = 2,        // Stone, dirt, etc. — blocks all light
    SOURCE = 3,        // Glowstone, torch, etc. — emits light
};

// Block light info for a single block
struct BlockLightInfo {
    LightType sky_type;      // How this block affects sky light
    LightType block_type;    // How this block affects block light
    uint8_t emitted_light;   // Light level emitted (0-15)
    uint8_t filter_level;    // Extra light reduction when filtering (0-2)
};

// -----------------------------------------------------------
// Light update entry
// -----------------------------------------------------------
struct LightUpdate {
    int32_t x, y, z;
    uint8_t new_sky_light;
    uint8_t new_block_light;
};

// -----------------------------------------------------------
// BlockPos for light engine
// -----------------------------------------------------------
struct LightPos {
    int32_t x, y, z;
    bool operator==(const LightPos& o) const {
        return x == o.x && y == o.y && z == o.z;
    }
};

struct LightPosHash {
    size_t operator()(const LightPos& p) const {
        size_t h = 14695981039346656037ULL;
        h ^= static_cast<size_t>(static_cast<uint32_t>(p.x));
        h *= 1099511628211ULL;
        h ^= static_cast<size_t>(static_cast<uint32_t>(p.y));
        h *= 1099511628211ULL;
        h ^= static_cast<size_t>(static_cast<uint32_t>(p.z));
        h *= 1099511628211ULL;
        return h;
    }
};

// -----------------------------------------------------------
// LightEngine — main class
// -----------------------------------------------------------
class LightEngine {
public:
    LightEngine();
    ~LightEngine();

    // ---- Full chunk lighting calculation ----

    // Calculate lighting for an entire chunk column.
    //   blocks:     24 sections of 16x16x16, indexed [section][y][z][x]
    //               Block state IDs (0 = air, etc.)
    //   sky_light:  Output sky light [26][16][16][16]
    //   block_light: Output block light [26][16][16][16]
    void calculate_chunk_lighting(
        const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        uint8_t sky_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        uint8_t block_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE]
    );

    // Simplified version with flat block array and biome data
    // blocks: flat array of 98304 uint16_t (y*256 + z*16 + x ordering)
    void calculate_chunk_lighting_flat(
        const uint16_t* blocks,
        uint8_t* sky_light,    // LIGHT_SECTIONS * 4096 bytes
        uint8_t* block_light   // LIGHT_SECTIONS * 4096 bytes
    );

    // ---- Incremental update ----

    // Update lighting when a single block changes.
    // Returns the list of positions whose light levels changed.
    std::vector<LightUpdate> update_block_light(
        int x, int y, int z,
        uint16_t old_block, uint16_t new_block
    );

    // ---- Block property lookup ----

    // Get the light properties of a block by its state ID.
    // Override this to provide block-specific light behavior.
    BlockLightInfo get_block_info(uint16_t block_state) const;

    // Register a custom block light info
    void set_block_info(uint16_t block_state, const BlockLightInfo& info);

    // ---- Internal light data access ----

    // For incremental updates, the engine maintains light data
    // for loaded chunks. These methods manage that data.

    // Set the light data for a chunk section
    void set_section_data(int chunk_x, int section_y, int chunk_z,
                          const uint8_t* sky_light, const uint8_t* block_light,
                          const uint16_t* blocks);

    // Get light level at a world position
    uint8_t get_sky_light_at(int x, int y, int z) const;
    uint8_t get_block_light_at(int x, int y, int z) const;

private:
    // Custom block info overrides
    std::unordered_map<uint16_t, BlockLightInfo> custom_block_info_;

    // Cached light data for loaded chunks
    // Key: (chunk_x, section_y, chunk_z) packed into int64_t
    struct SectionData {
        uint8_t sky_light[SECTION_SIZE * SECTION_SIZE * SECTION_SIZE];
        uint8_t block_light[SECTION_SIZE * SECTION_SIZE * SECTION_SIZE];
        uint16_t blocks[SECTION_SIZE * SECTION_SIZE * SECTION_SIZE];
    };

    static int64_t make_section_key(int cx, int sy, int cz) {
        return (static_cast<int64_t>(cx & 0x3FFFFF) << 42)
             | (static_cast<int64_t>(sy & 0x1FF) << 21)
             | (static_cast<int64_t>(cz & 0x3FFFFF));
    }

    std::unordered_map<int64_t, SectionData> section_cache_;

    // ---- Internal BFS-based propagation ----

    // Propagate sky light from top down
    void propagate_sky_light(
        uint8_t sky_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        int chunk_x, int chunk_z
    );

    // Propagate block light from sources
    void propagate_block_light(
        uint8_t block_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE]
    );

    // BFS flood fill for light propagation
    // type=0: sky light, type=1: block light
    void bfs_propagate(
        uint8_t light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
        std::deque<LightPos>& queue,
        bool is_sky_light
    );

    // Calculate the light decrease when passing through a block
    uint8_t light_decrease(uint16_t block_state, bool is_sky_light) const;

    // Check if a block is transparent to light
    bool is_transparent(uint16_t block_state) const;

    // Initialize default block light properties
    void init_default_block_info();
};

}  // namespace pymc

#endif  // PYMC_LIGHT_ENGINE_H
