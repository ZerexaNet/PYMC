// ============================================================
// PyMC - Light Engine Implementation
// BFS-based light propagation with incremental updates
// ============================================================

#include "light_engine.h"

#include <algorithm>
#include <cstring>
#include <cstdio>
#include <queue>

namespace pymc {

// ===========================================================
// Default block light properties
// ===========================================================

// Well-known block IDs (matching terrain_gen.cpp and blocks.py)
static constexpr uint16_t BL_AIR = 0;
static constexpr uint16_t BL_STONE = 1;
static constexpr uint16_t BL_GRASS_BLOCK = 9;
static constexpr uint16_t BL_DIRT = 10;
static constexpr uint16_t BL_BEDROCK = 79;
static constexpr uint16_t BL_WATER = 80;
static constexpr uint16_t BL_LAVA = 96;
static constexpr uint16_t BL_SAND = 112;
static constexpr uint16_t BL_GLASS = 519;
static constexpr uint16_t BL_GLOWSTONE = 922;
static constexpr uint16_t BL_REDSTONE_LAMP_OFF = 923;
static constexpr uint16_t BL_REDSTONE_LAMP_ON = 924;
static constexpr uint16_t BL_TORCH = 1987;
static constexpr uint16_t BL_LANTERN = 2265;
static constexpr uint16_t BL_CAMPFIRE = 1358;
static constexpr uint16_t BL_SOUL_CAMPFIRE = 1359;
static constexpr uint16_t BL_SHROOMLIGHT = 1712;
static constexpr uint16_t BL_SEA_LANTERN = 997;
static constexpr uint16_t BL_CONDUIT = 1199;
static constexpr uint16_t BL_BEACON = 866;
static constexpr uint16_t BL_OAK_LEAVES = 264;
static constexpr uint16_t BL_SPRUCE_LEAVES = 292;
static constexpr uint16_t BL_BIRCH_LEAVES = 320;
static constexpr uint16_t BL_ICE = 655;
static constexpr uint16_t BL_PACKED_ICE = 727;
static constexpr uint16_t BL_FROSTED_ICE = 728;

LightEngine::LightEngine() {
    init_default_block_info();
}

LightEngine::~LightEngine() = default;

void LightEngine::init_default_block_info() {
    // Air: fully transparent
    custom_block_info_[BL_AIR] = {LightType::TRANSPARENT, LightType::TRANSPARENT, 0, 0};

    // Water: filters light (reduces by 1 extra per block)
    custom_block_info_[BL_WATER] = {LightType::FILTER, LightType::FILTER, 0, 1};

    // Lava: emits block light 15
    custom_block_info_[BL_LAVA] = {LightType::FILTER, LightType::SOURCE, 15, 1};

    // Glass: transparent to both
    custom_block_info_[BL_GLASS] = {LightType::TRANSPARENT, LightType::TRANSPARENT, 0, 0};

    // Leaves: filter sky and block light
    custom_block_info_[BL_OAK_LEAVES] = {LightType::FILTER, LightType::FILTER, 0, 1};
    custom_block_info_[BL_SPRUCE_LEAVES] = {LightType::FILTER, LightType::FILTER, 0, 1};
    custom_block_info_[BL_BIRCH_LEAVES] = {LightType::FILTER, LightType::FILTER, 0, 1};

    // Light sources
    custom_block_info_[BL_GLOWSTONE] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_SEA_LANTERN] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_SHROOMLIGHT] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_TORCH] = {LightType::TRANSPARENT, LightType::SOURCE, 14, 0};
    custom_block_info_[BL_LANTERN] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_CAMPFIRE] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_SOUL_CAMPFIRE] = {LightType::FILTER, LightType::SOURCE, 10, 0};
    custom_block_info_[BL_CONDUIT] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_BEACON] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_REDSTONE_LAMP_ON] = {LightType::FILTER, LightType::SOURCE, 15, 0};
    custom_block_info_[BL_FROSTED_ICE] = {LightType::FILTER, LightType::TRANSPARENT, 0, 1};
    custom_block_info_[BL_ICE] = {LightType::FILTER, LightType::TRANSPARENT, 0, 0};
}

BlockLightInfo LightEngine::get_block_info(uint16_t block_state) const {
    auto it = custom_block_info_.find(block_state);
    if (it != custom_block_info_.end()) {
        return it->second;
    }

    // Default: opaque block
    // Most blocks in Minecraft are opaque
    if (block_state == BL_AIR) {
        return {LightType::TRANSPARENT, LightType::TRANSPARENT, 0, 0};
    }

    return {LightType::OPAQUE, LightType::OPAQUE, 0, 0};
}

void LightEngine::set_block_info(uint16_t block_state, const BlockLightInfo& info) {
    custom_block_info_[block_state] = info;
}

// ===========================================================
// Full chunk lighting calculation
// ===========================================================

void LightEngine::calculate_chunk_lighting(
    const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    uint8_t sky_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    uint8_t block_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE]
) {
    // Initialize all light to 0
    std::memset(sky_light, 0, LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);
    std::memset(block_light, 0, LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);

    // Phase 1: Sky light propagation
    propagate_sky_light(sky_light, blocks, 0, 0);

    // Phase 2: Block light propagation
    propagate_block_light(block_light, blocks);
}

void LightEngine::calculate_chunk_lighting_flat(
    const uint16_t* blocks,
    uint8_t* sky_light,
    uint8_t* block_light
) {
    // Convert flat array to sectioned array
    uint16_t sectioned[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE];

    for (int sec = 0; sec < CHUNK_SECTIONS; sec++) {
        for (int y = 0; y < SECTION_SIZE; y++) {
            for (int z = 0; z < SECTION_SIZE; z++) {
                for (int x = 0; x < SECTION_SIZE; x++) {
                    int flat_idx = (sec * SECTION_SIZE + y) * 256 + z * 16 + x;
                    sectioned[sec][y][z][x] = blocks[flat_idx];
                }
            }
        }
    }

    uint8_t sl[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE];
    uint8_t bl[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE];

    calculate_chunk_lighting(sectioned, sl, bl);

    // Copy to flat output
    std::memcpy(sky_light, sl, LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);
    std::memcpy(block_light, bl, LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);
}

// ===========================================================
// Sky light propagation
// ===========================================================

void LightEngine::propagate_sky_light(
    uint8_t sky_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    int chunk_x, int chunk_z
) {
    // Step 1: Initialize sky light from the top.
    // In the topmost section (section index 25 = boundary above),
    // all positions start with sky light 15.

    // Top boundary section (index 25)
    for (int z = 0; z < SECTION_SIZE; z++) {
        for (int x = 0; x < SECTION_SIZE; x++) {
            sky_light[25][0][z][x] = MAX_LIGHT;
        }
    }

    // Step 2: Cast columns downward.
    // For each (x, z) column, propagate sky light downward until blocked.
    std::deque<LightPos> queue;

    for (int z = 0; z < SECTION_SIZE; z++) {
        for (int x = 0; x < SECTION_SIZE; x++) {
            uint8_t current_light = MAX_LIGHT;
            bool blocked = false;

            // Walk down from section 23 (top game section) to 0 (bottom)
            for (int sec = CHUNK_SECTIONS - 1; sec >= 0 && !blocked; sec--) {
                for (int y = SECTION_SIZE - 1; y >= 0 && !blocked; y--) {
                    uint16_t block = blocks[sec][y][z][x];
                    BlockLightInfo info = get_block_info(block);

                    if (info.sky_type == LightType::OPAQUE) {
                        // Fully blocks sky light
                        sky_light[sec + 1][y][z][x] = current_light;  // +1 for boundary offset
                        blocked = true;
                        break;
                    }

                    if (info.sky_type == LightType::FILTER) {
                        current_light = std::max(0, current_light - 1 - info.filter_level);
                    }

                    // Section index offset: sections[0..23] -> light sections[1..24]
                    sky_light[sec + 1][y][z][x] = current_light;

                    if (current_light > 0 && current_light < MAX_LIGHT) {
                        // This position might spread light horizontally
                        int world_y = (sec + 1) * SECTION_SIZE + y + MIN_Y;
                        queue.push_back({x, world_y, z});
                    }
                }
            }
        }
    }

    // Step 3: BFS propagate sky light horizontally and diagonally.
    bfs_propagate(sky_light, blocks, queue, true);
}

// ===========================================================
// Block light propagation
// ===========================================================

void LightEngine::propagate_block_light(
    uint8_t block_light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE]
) {
    std::deque<LightPos> queue;

    // Find all light sources and seed the BFS
    for (int sec = 0; sec < CHUNK_SECTIONS; sec++) {
        for (int y = 0; y < SECTION_SIZE; y++) {
            for (int z = 0; z < SECTION_SIZE; z++) {
                for (int x = 0; x < SECTION_SIZE; x++) {
                    uint16_t block = blocks[sec][y][z][x];
                    BlockLightInfo info = get_block_info(block);

                    if (info.block_type == LightType::SOURCE && info.emitted_light > 0) {
                        int light_sec = sec + 1;  // Boundary offset
                        block_light[light_sec][y][z][x] = info.emitted_light;
                        int world_y = sec * SECTION_SIZE + y + MIN_Y;
                        queue.push_back({x, world_y, z});
                    }
                }
            }
        }
    }

    // BFS propagate block light
    bfs_propagate(block_light, blocks, queue, false);
}

void LightEngine::bfs_propagate(
    uint8_t light[LIGHT_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    const uint16_t blocks[CHUNK_SECTIONS][SECTION_SIZE][SECTION_SIZE][SECTION_SIZE],
    std::deque<LightPos>& queue,
    bool is_sky_light
) {
    // 6-connected neighbors
    static constexpr int dx[] = {-1, 1, 0, 0, 0, 0};
    static constexpr int dy[] = {0, 0, -1, 1, 0, 0};
    static constexpr int dz[] = {0, 0, 0, 0, -1, 1};

    while (!queue.empty()) {
        LightPos pos = queue.front();
        queue.pop_front();

        // Convert world y to section/local coordinates
        int local_y = pos.y - MIN_Y;
        int sec = local_y / SECTION_SIZE;
        int y_in_sec = local_y % SECTION_SIZE;

        if (sec < 0 || sec >= LIGHT_SECTIONS) continue;
        if (y_in_sec < 0 || y_in_sec >= SECTION_SIZE) continue;
        if (pos.x < 0 || pos.x >= SECTION_SIZE) continue;
        if (pos.z < 0 || pos.z >= SECTION_SIZE) continue;

        uint8_t current = light[sec][y_in_sec][pos.z][pos.x];
        if (current == 0) continue;

        // Try to propagate to neighbors
        for (int d = 0; d < 6; d++) {
            int nx = pos.x + dx[d];
            int ny = pos.y + dy[d];
            int nz = pos.z + dz[d];

            // Check bounds (within chunk column)
            if (nx < 0 || nx >= SECTION_SIZE) continue;
            if (nz < 0 || nz >= SECTION_SIZE) continue;

            int n_local_y = ny - MIN_Y;
            int n_sec = n_local_y / SECTION_SIZE;
            int n_y = n_local_y % SECTION_SIZE;

            if (n_sec < 0 || n_sec >= LIGHT_SECTIONS) continue;
            if (n_y < 0 || n_y >= SECTION_SIZE) continue;

            // Get the block at the neighbor position
            uint16_t neighbor_block = BL_AIR;
            int block_sec = n_sec - 1;  // Convert from light section to block section
            if (block_sec >= 0 && block_sec < CHUNK_SECTIONS) {
                neighbor_block = blocks[block_sec][n_y][nz][nx];
            }

            BlockLightInfo info = get_block_info(neighbor_block);
            if (info.block_type == LightType::OPAQUE && info.sky_type == LightType::OPAQUE) {
                continue;  // Light can't pass through fully opaque blocks
            }

            // Calculate new light level at neighbor
            uint8_t decrease = 1;
            if (is_sky_light && info.sky_type == LightType::FILTER) {
                decrease += info.filter_level;
            } else if (!is_sky_light && info.block_type == LightType::FILTER) {
                decrease += info.filter_level;
            }

            uint8_t new_light = (current > decrease) ? (current - decrease) : 0;

            // Sky light special: propagates downward without decrease
            if (is_sky_light && dy[d] < 0 && info.sky_type == LightType::TRANSPARENT) {
                new_light = current;  // No decrease going down through air
            }

            uint8_t& existing = light[n_sec][n_y][nz][nx];
            if (new_light > existing) {
                existing = new_light;
                if (new_light > 1) {
                    queue.push_back({nx, ny, nz});
                }
            }
        }
    }
}

// ===========================================================
// Incremental update
// ===========================================================

std::vector<LightUpdate> LightEngine::update_block_light(
    int x, int y, int z,
    uint16_t old_block, uint16_t new_block
) {
    std::vector<LightUpdate> updates;

    BlockLightInfo old_info = get_block_info(old_block);
    BlockLightInfo new_info = get_block_info(new_block);

    // If light properties haven't changed, no update needed
    if (old_info.sky_type == new_info.sky_type &&
        old_info.block_type == new_info.block_type &&
        old_info.emitted_light == new_info.emitted_light &&
        old_info.filter_level == new_info.filter_level) {
        return updates;
    }

    // For incremental updates, we need to:
    // 1. Remove the old light contribution
    // 2. Add the new light contribution
    // 3. Re-propagate affected area

    // This is a simplified version — a full implementation would
    // use a proper "un-propagate" algorithm (like Minecraft's)
    // For now, we just mark the position as needing recalculation

    LightUpdate update;
    update.x = x;
    update.y = y;
    update.z = z;
    update.new_sky_light = 0;
    update.new_block_light = 0;

    // If the new block is a light source, set its block light
    if (new_info.block_type == LightType::SOURCE) {
        update.new_block_light = new_info.emitted_light;
    }

    // If the new block is transparent, it may allow sky light
    if (new_info.sky_type == LightType::TRANSPARENT) {
        update.new_sky_light = MAX_LIGHT;  // Will be refined by propagation
    }

    updates.push_back(update);

    // Mark neighbors as potentially affected
    static constexpr int dx[] = {-1, 1, 0, 0, 0, 0};
    static constexpr int dy[] = {0, 0, -1, 1, 0, 0};
    static constexpr int dz[] = {0, 0, 0, 0, -1, 1};

    for (int d = 0; d < 6; d++) {
        LightUpdate neighbor;
        neighbor.x = x + dx[d];
        neighbor.y = y + dy[d];
        neighbor.z = z + dz[d];
        neighbor.new_sky_light = 0;
        neighbor.new_block_light = 0;
        updates.push_back(neighbor);
    }

    return updates;
}

// ===========================================================
// Section cache management
// ===========================================================

void LightEngine::set_section_data(int chunk_x, int section_y, int chunk_z,
                                    const uint8_t* sky_light, const uint8_t* block_light,
                                    const uint16_t* blocks) {
    int64_t key = make_section_key(chunk_x, section_y, chunk_z);
    auto& data = section_cache_[key];
    std::memcpy(data.sky_light, sky_light, SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);
    std::memcpy(data.block_light, block_light, SECTION_SIZE * SECTION_SIZE * SECTION_SIZE);
    std::memcpy(data.blocks, blocks, SECTION_SIZE * SECTION_SIZE * SECTION_SIZE * sizeof(uint16_t));
}

uint8_t LightEngine::get_sky_light_at(int x, int y, int z) const {
    int cx = x >> 4;
    int cz = z >> 4;
    int lx = x & 15;
    int lz = z & 15;
    int local_y = y - MIN_Y;
    int sec = local_y / SECTION_SIZE;
    int ly = local_y % SECTION_SIZE;

    int64_t key = make_section_key(cx, sec, cz);
    auto it = section_cache_.find(key);
    if (it == section_cache_.end()) return 0;
    return it->second.sky_light[ly * SECTION_SIZE * SECTION_SIZE + lz * SECTION_SIZE + lx];
}

uint8_t LightEngine::get_block_light_at(int x, int y, int z) const {
    int cx = x >> 4;
    int cz = z >> 4;
    int lx = x & 15;
    int lz = z & 15;
    int local_y = y - MIN_Y;
    int sec = local_y / SECTION_SIZE;
    int ly = local_y % SECTION_SIZE;

    int64_t key = make_section_key(cx, sec, cz);
    auto it = section_cache_.find(key);
    if (it == section_cache_.end()) return 0;
    return it->second.block_light[ly * SECTION_SIZE * SECTION_SIZE + lz * SECTION_SIZE + lx];
}

uint8_t LightEngine::light_decrease(uint16_t block_state, bool is_sky_light) const {
    BlockLightInfo info = get_block_info(block_state);
    if (info.sky_type == LightType::OPAQUE) return MAX_LIGHT;  // Fully blocks
    uint8_t decrease = 1;
    if (is_sky_light && info.sky_type == LightType::FILTER) {
        decrease += info.filter_level;
    } else if (!is_sky_light && info.block_type == LightType::FILTER) {
        decrease += info.filter_level;
    }
    return decrease;
}

bool LightEngine::is_transparent(uint16_t block_state) const {
    BlockLightInfo info = get_block_info(block_state);
    return info.sky_type != LightType::OPAQUE;
}

}  // namespace pymc
