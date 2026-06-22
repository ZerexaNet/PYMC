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

// Helper: index into a flat section array [sec][y][z][x]
static inline int light_idx(int sec, int y, int z, int x) {
    return ((sec * LIGHT_SECTION_SIZE + y) * LIGHT_SECTION_SIZE + z) * LIGHT_SECTION_SIZE + x;
}

// Helper: index into flat blocks array [sec][y][z][x]
static inline int block_idx(int sec, int y, int z, int x) {
    return ((sec * LIGHT_SECTION_SIZE + y) * LIGHT_SECTION_SIZE + z) * LIGHT_SECTION_SIZE + x;
}

LightEngine::LightEngine() {
    init_default_block_info();
}

LightEngine::~LightEngine() = default;

void LightEngine::init_default_block_info() {
    // Air: fully transparent
    custom_block_info_[BL_AIR] = {LightType::LIGHT_TRANSPARENT, LightType::LIGHT_TRANSPARENT, 0, 0};

    // Water: filters light (reduces by 1 extra per block)
    custom_block_info_[BL_WATER] = {LightType::LIGHT_FILTER, LightType::LIGHT_FILTER, 0, 1};

    // Lava: emits block light 15
    custom_block_info_[BL_LAVA] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 1};

    // Glass: transparent to both
    custom_block_info_[BL_GLASS] = {LightType::LIGHT_TRANSPARENT, LightType::LIGHT_TRANSPARENT, 0, 0};

    // Leaves: filter sky and block light
    custom_block_info_[BL_OAK_LEAVES] = {LightType::LIGHT_FILTER, LightType::LIGHT_FILTER, 0, 1};
    custom_block_info_[BL_SPRUCE_LEAVES] = {LightType::LIGHT_FILTER, LightType::LIGHT_FILTER, 0, 1};
    custom_block_info_[BL_BIRCH_LEAVES] = {LightType::LIGHT_FILTER, LightType::LIGHT_FILTER, 0, 1};

    // Light sources
    custom_block_info_[BL_GLOWSTONE] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_SEA_LANTERN] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_SHROOMLIGHT] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_TORCH] = {LightType::LIGHT_TRANSPARENT, LightType::LIGHT_SOURCE, 14, 0};
    custom_block_info_[BL_LANTERN] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_CAMPFIRE] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_SOUL_CAMPFIRE] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 10, 0};
    custom_block_info_[BL_CONDUIT] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_BEACON] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_REDSTONE_LAMP_ON] = {LightType::LIGHT_FILTER, LightType::LIGHT_SOURCE, 15, 0};
    custom_block_info_[BL_FROSTED_ICE] = {LightType::LIGHT_FILTER, LightType::LIGHT_TRANSPARENT, 0, 1};
    custom_block_info_[BL_ICE] = {LightType::LIGHT_FILTER, LightType::LIGHT_TRANSPARENT, 0, 0};
}

BlockLightInfo LightEngine::get_block_info(uint16_t block_state) const {
    auto it = custom_block_info_.find(block_state);
    if (it != custom_block_info_.end()) {
        return it->second;
    }

    // Default: opaque block
    if (block_state == BL_AIR) {
        return {LightType::LIGHT_TRANSPARENT, LightType::LIGHT_TRANSPARENT, 0, 0};
    }

    return {LightType::LIGHT_OPAQUE, LightType::LIGHT_OPAQUE, 0, 0};
}

void LightEngine::set_block_info(uint16_t block_state, const BlockLightInfo& info) {
    custom_block_info_[block_state] = info;
}

// ===========================================================
// Full chunk lighting calculation
// ===========================================================

void LightEngine::calculate_chunk_lighting(
    const uint16_t* blocks,
    uint8_t* sky_light,
    uint8_t* block_light
) {
    // Initialize all light to 0
    std::memset(sky_light, 0, LIGHT_SECTION_COUNT * SECTION_VOLUME);
    std::memset(block_light, 0, LIGHT_SECTION_COUNT * SECTION_VOLUME);

    // Phase 1: Sky light propagation
    propagate_sky_light(sky_light, blocks, 0, 0);

    // Phase 2: Block light propagation
    propagate_block_light(block_light, blocks);
}

// ===========================================================
// Sky light propagation
// ===========================================================

void LightEngine::propagate_sky_light(
    uint8_t* sky_light,
    const uint16_t* blocks,
    int /*chunk_x*/, int /*chunk_z*/
) {
    // Step 1: Initialize sky light from the top.
    // Top boundary section (index 25)
    for (int z = 0; z < LIGHT_SECTION_SIZE; z++) {
        for (int x = 0; x < LIGHT_SECTION_SIZE; x++) {
            sky_light[light_idx(25, 0, z, x)] = LIGHT_MAX_LEVEL;
        }
    }

    // Step 2: Cast columns downward.
    std::deque<LightPos> queue;

    for (int z = 0; z < LIGHT_SECTION_SIZE; z++) {
        for (int x = 0; x < LIGHT_SECTION_SIZE; x++) {
            uint8_t current_light = LIGHT_MAX_LEVEL;
            bool blocked = false;

            // Walk down from section 23 (top game section) to 0 (bottom)
            for (int sec = LIGHT_CHUNK_SECTIONS - 1; sec >= 0 && !blocked; sec--) {
                for (int y = LIGHT_SECTION_SIZE - 1; y >= 0 && !blocked; y--) {
                    uint16_t block = blocks[block_idx(sec, y, z, x)];
                    BlockLightInfo info = get_block_info(block);

                    if (info.sky_type == LightType::LIGHT_OPAQUE) {
                        sky_light[light_idx(sec + 1, y, z, x)] = current_light;
                        blocked = true;
                        break;
                    }

                    if (info.sky_type == LightType::LIGHT_FILTER) {
                        current_light = std::max(0, current_light - 1 - info.filter_level);
                    }

                    sky_light[light_idx(sec + 1, y, z, x)] = current_light;

                    if (current_light > 0 && current_light < LIGHT_MAX_LEVEL) {
                        int world_y = (sec + 1) * LIGHT_SECTION_SIZE + y + LIGHT_MIN_Y;
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
    uint8_t* block_light,
    const uint16_t* blocks
) {
    std::deque<LightPos> queue;

    // Find all light sources and seed the BFS
    for (int sec = 0; sec < LIGHT_CHUNK_SECTIONS; sec++) {
        for (int y = 0; y < LIGHT_SECTION_SIZE; y++) {
            for (int z = 0; z < LIGHT_SECTION_SIZE; z++) {
                for (int x = 0; x < LIGHT_SECTION_SIZE; x++) {
                    uint16_t block = blocks[block_idx(sec, y, z, x)];
                    BlockLightInfo info = get_block_info(block);

                    if (info.block_type == LightType::LIGHT_SOURCE && info.emitted_light > 0) {
                        block_light[light_idx(sec + 1, y, z, x)] = info.emitted_light;
                        int world_y = sec * LIGHT_SECTION_SIZE + y + LIGHT_MIN_Y;
                        queue.push_back({x, world_y, z});
                    }
                }
            }
        }
    }

    bfs_propagate(block_light, blocks, queue, false);
}

void LightEngine::bfs_propagate(
    uint8_t* light,
    const uint16_t* blocks,
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
        int local_y = pos.y - LIGHT_MIN_Y;
        int sec = local_y / LIGHT_SECTION_SIZE;
        int y_in_sec = local_y % LIGHT_SECTION_SIZE;

        if (sec < 0 || sec >= LIGHT_SECTION_COUNT) continue;
        if (y_in_sec < 0 || y_in_sec >= LIGHT_SECTION_SIZE) continue;
        if (pos.x < 0 || pos.x >= LIGHT_SECTION_SIZE) continue;
        if (pos.z < 0 || pos.z >= LIGHT_SECTION_SIZE) continue;

        uint8_t current = light[light_idx(sec, y_in_sec, pos.z, pos.x)];
        if (current == 0) continue;

        for (int d = 0; d < 6; d++) {
            int nx = pos.x + dx[d];
            int ny = pos.y + dy[d];
            int nz = pos.z + dz[d];

            if (nx < 0 || nx >= LIGHT_SECTION_SIZE) continue;
            if (nz < 0 || nz >= LIGHT_SECTION_SIZE) continue;

            int n_local_y = ny - LIGHT_MIN_Y;
            int n_sec = n_local_y / LIGHT_SECTION_SIZE;
            int n_y = n_local_y % LIGHT_SECTION_SIZE;

            if (n_sec < 0 || n_sec >= LIGHT_SECTION_COUNT) continue;
            if (n_y < 0 || n_y >= LIGHT_SECTION_SIZE) continue;

            uint16_t neighbor_block = BL_AIR;
            int block_sec = n_sec - 1;
            if (block_sec >= 0 && block_sec < LIGHT_CHUNK_SECTIONS) {
                neighbor_block = blocks[block_idx(block_sec, n_y, nz, nx)];
            }

            BlockLightInfo info = get_block_info(neighbor_block);
            if (info.block_type == LightType::LIGHT_OPAQUE && info.sky_type == LightType::LIGHT_OPAQUE) {
                continue;
            }

            uint8_t decrease = 1;
            if (is_sky_light && info.sky_type == LightType::LIGHT_FILTER) {
                decrease += info.filter_level;
            } else if (!is_sky_light && info.block_type == LightType::LIGHT_FILTER) {
                decrease += info.filter_level;
            }

            uint8_t new_light = (current > decrease) ? (current - decrease) : 0;

            if (is_sky_light && dy[d] < 0 && info.sky_type == LightType::LIGHT_TRANSPARENT) {
                new_light = current;
            }

            uint8_t& existing = light[light_idx(n_sec, n_y, nz, nx)];
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

    if (old_info.sky_type == new_info.sky_type &&
        old_info.block_type == new_info.block_type &&
        old_info.emitted_light == new_info.emitted_light &&
        old_info.filter_level == new_info.filter_level) {
        return updates;
    }

    LightUpdate update;
    update.x = x;
    update.y = y;
    update.z = z;
    update.new_sky_light = 0;
    update.new_block_light = 0;

    if (new_info.block_type == LightType::LIGHT_SOURCE) {
        update.new_block_light = new_info.emitted_light;
    }

    if (new_info.sky_type == LightType::LIGHT_TRANSPARENT) {
        update.new_sky_light = LIGHT_MAX_LEVEL;
    }

    updates.push_back(update);

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
    std::memcpy(data.sky_light, sky_light, SECTION_VOLUME);
    std::memcpy(data.block_light, block_light, SECTION_VOLUME);
    std::memcpy(data.blocks, blocks, SECTION_VOLUME * sizeof(uint16_t));
}

uint8_t LightEngine::get_sky_light_at(int x, int y, int z) const {
    int cx = x >> 4;
    int cz = z >> 4;
    int lx = x & 15;
    int lz = z & 15;
    int local_y = y - LIGHT_MIN_Y;
    int sec = local_y / LIGHT_SECTION_SIZE;
    int ly = local_y % LIGHT_SECTION_SIZE;

    int64_t key = make_section_key(cx, sec, cz);
    auto it = section_cache_.find(key);
    if (it == section_cache_.end()) return 0;
    return it->second.sky_light[ly * LIGHT_SECTION_SIZE * LIGHT_SECTION_SIZE + lz * LIGHT_SECTION_SIZE + lx];
}

uint8_t LightEngine::get_block_light_at(int x, int y, int z) const {
    int cx = x >> 4;
    int cz = z >> 4;
    int lx = x & 15;
    int lz = z & 15;
    int local_y = y - LIGHT_MIN_Y;
    int sec = local_y / LIGHT_SECTION_SIZE;
    int ly = local_y % LIGHT_SECTION_SIZE;

    int64_t key = make_section_key(cx, sec, cz);
    auto it = section_cache_.find(key);
    if (it == section_cache_.end()) return 0;
    return it->second.block_light[ly * LIGHT_SECTION_SIZE * LIGHT_SECTION_SIZE + lz * LIGHT_SECTION_SIZE + lx];
}

uint8_t LightEngine::light_decrease(uint16_t block_state, bool is_sky_light) const {
    BlockLightInfo info = get_block_info(block_state);
    if (info.sky_type == LightType::LIGHT_OPAQUE) return LIGHT_MAX_LEVEL;
    uint8_t decrease = 1;
    if (is_sky_light && info.sky_type == LightType::LIGHT_FILTER) {
        decrease += info.filter_level;
    } else if (!is_sky_light && info.block_type == LightType::LIGHT_FILTER) {
        decrease += info.filter_level;
    }
    return decrease;
}

bool LightEngine::is_transparent(uint16_t block_state) const {
    BlockLightInfo info = get_block_info(block_state);
    return info.sky_type != LightType::LIGHT_OPAQUE;
}

}  // namespace pymc
