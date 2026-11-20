// ============================================================
// PyMC - chunk light (C++ port of world/lighting.py)
//
// The same rules as the Python reference, so the output is byte-identical:
//   * direct sky light column by column (15 until a filtering block; each block
//     subtracts its opacity, filters of 0-1 cost 1), then sideways spread from
//     the cells next to a column whose direct light stops higher up;
//   * block light from every emitting block (blocks.json emitLight), spread with
//     the same cost rule;
//   * both spread through the 16x16 chunk column only (no light crosses chunks);
//   * sections are packed to 2048 nibbles; all-dark sections are reported empty.
// Opacity and emission come from blocks.json (filterLight / emitLight).
// ============================================================
#pragma once

#include <cstdint>
#include <cstring>
#include <deque>
#include <vector>

#include "blocktable.h"

namespace vrs {

constexpr int LIGHT_WORLD_HEIGHT = 384;
constexpr int LIGHT_LAYER = 256;               // 16 * 16 cells per y layer
constexpr int LIGHT_SECTION_VOLUME = 4096;     // 16 * 16 * 16
constexpr int LIGHT_SECTION_BYTES = 2048;      // packed nibbles
constexpr int LIGHT_SECTIONS = 26;             // below the world, 24 world sections, above the world

struct LightTables {
    std::vector<uint8_t> opacity;   // by state id; states beyond the table count as opaque (15)
    std::vector<uint8_t> emission;  // by state id
    bool loaded = false;

    void build(const BlockTable& table) {
        const size_t size = table.block_of_state.size();
        opacity.assign(size, 15);
        emission.assign(size, 0);
        for (size_t s = 0; s < size; s++) {
            const BlockInfo& b = table.blocks[table.block_of_state[s]];
            opacity[s] = (uint8_t)b.filter_light;
            emission[s] = (uint8_t)b.emit_light;
        }
        loaded = true;
    }
    inline int cost(uint16_t state) const { return state < opacity.size() ? opacity[state] : 15; }
    inline int emit(uint16_t state) const { return state < emission.size() ? emission[state] : 0; }
};

// _spread: flood-fill levels from the queued cells (index = y * 256 + z * 16 + x)
inline void light_spread(uint8_t* light, std::deque<uint32_t>& queue, const uint16_t* blocks,
                         const LightTables& L) {
    while (!queue.empty()) {
        const uint32_t idx = queue.front();
        queue.pop_front();
        const int x = idx & 15, z = (idx >> 4) & 15, y = (int)(idx >> 8);
        const int level = light[idx];
        if (level <= 1) continue;
        const int nx[6] = {x + 1, x - 1, x, x, x, x};
        const int ny[6] = {y, y, y + 1, y - 1, y, y};
        const int nz[6] = {z, z, z, z, z + 1, z - 1};
        for (int k = 0; k < 6; k++) {
            if (nx[k] < 0 || nx[k] >= 16 || nz[k] < 0 || nz[k] >= 16 || ny[k] < 0 || ny[k] >= LIGHT_WORLD_HEIGHT)
                continue;
            const uint32_t n = (uint32_t)(ny[k] * LIGHT_LAYER + nz[k] * 16 + nx[k]);
            const int c = L.cost(blocks[n]);
            const int new_level = level - (c > 1 ? c : 1);
            if (new_level <= 0) continue;
            if (light[n] < new_level) {
                light[n] = (uint8_t)new_level;
                queue.push_back(n);
            }
        }
    }
}

// compute_light: sky and block light for one chunk column (flat y*256+z*16+x arrays)
inline void light_compute(const LightTables& L, const uint16_t* blocks, uint8_t* sky, uint8_t* block_light) {
    std::memset(sky, 0, LIGHT_WORLD_HEIGHT * LIGHT_LAYER);
    std::memset(block_light, 0, LIGHT_WORLD_HEIGHT * LIGHT_LAYER);

    // highest layer that holds anything; everything above is open sky
    int top = LIGHT_WORLD_HEIGHT - 1;
    while (top >= 0) {
        bool any = false;
        const uint16_t* layer = blocks + top * LIGHT_LAYER;
        for (int i = 0; i < LIGHT_LAYER && !any; i++) any = layer[i] != 0;
        if (any) break;
        top--;
    }
    for (int i = (top + 1) * LIGHT_LAYER; i < LIGHT_WORLD_HEIGHT * LIGHT_LAYER; i++) sky[i] = 15;

    // direct sky light, column by column
    int floors[16][16];
    std::vector<uint32_t> partial;
    for (int z = 0; z < 16; z++) {
        for (int x = 0; x < 16; x++) {
            int level = 15;
            int y = top;
            const int offset = z * 16 + x;
            bool broke = false;
            floors[z][x] = 0;
            while (y >= 0) {
                const uint32_t idx = (uint32_t)(y * LIGHT_LAYER + offset);
                const int cost = L.cost(blocks[idx]);
                if (level == 15) {
                    if (cost) {
                        level -= cost;
                        floors[z][x] = y + 1;
                        if (level <= 0) { broke = true; break; }
                        sky[idx] = (uint8_t)level;
                        partial.push_back(idx);
                    } else {
                        sky[idx] = 15;
                    }
                } else {
                    level -= cost > 1 ? cost : 1;
                    if (level <= 0) { broke = true; break; }
                    sky[idx] = (uint8_t)level;
                    partial.push_back(idx);
                }
                y--;
            }
            if (!broke) floors[z][x] = 0;   // Python's while/else: a full pass resets the floor
        }
    }

    // sideways spread next to columns whose direct light stops higher up
    std::deque<uint32_t> queue(partial.begin(), partial.end());
    for (int z = 0; z < 16; z++) {
        for (int x = 0; x < 16; x++) {
            const int floor = floors[z][x];
            int highest = floor;
            if (x > 0 && floors[z][x - 1] > highest) highest = floors[z][x - 1];
            if (x < 15 && floors[z][x + 1] > highest) highest = floors[z][x + 1];
            if (z > 0 && floors[z - 1][x] > highest) highest = floors[z - 1][x];
            if (z < 15 && floors[z + 1][x] > highest) highest = floors[z + 1][x];
            const int stop = highest < top + 1 ? highest : top + 1;
            for (int y = floor; y < stop; y++) queue.push_back((uint32_t)(y * LIGHT_LAYER + z * 16 + x));
        }
    }
    light_spread(sky, queue, blocks, L);

    // block light from emitting blocks
    std::deque<uint32_t> emitters;
    for (int y = 0; y <= top; y++) {
        for (int i = 0; i < LIGHT_LAYER; i++) {
            const uint32_t idx = (uint32_t)(y * LIGHT_LAYER + i);
            const int e = L.emit(blocks[idx]);
            if (e > 0) {
                block_light[idx] = (uint8_t)e;
                emitters.push_back(idx);
            }
        }
    }
    if (!emitters.empty()) light_spread(block_light, emitters, blocks, L);
}

// _pack_section: 4096 levels -> 2048 nibbles (low nibble first). Returns false when all dark.
inline bool light_pack(const uint8_t* levels, uint8_t* out) {
    bool any = false;
    for (int i = 0; i < LIGHT_SECTION_VOLUME && !any; i++) any = levels[i] != 0;
    if (!any) return false;
    for (int k = 0; k < LIGHT_SECTION_BYTES; k++)
        out[k] = (uint8_t)((levels[2 * k] & 0x0F) | ((levels[2 * k + 1] & 0x0F) << 4));
    return true;
}

// build_light_sections: the Chunk Data layout. masks[0..3] = sky, block, empty sky, empty block
// (bit i = light section i: 0 below the world, 1..24 world sections, 25 above the world).
// sky_out / block_out receive the non-empty arrays in section order (LIGHT_SECTIONS * 2048 bytes max).
// counts[0] / counts[1] = number of arrays written to sky_out / block_out.
inline void light_build_sections(const LightTables& L, const uint16_t* blocks, uint8_t* sky_out,
                                 uint8_t* block_out, int32_t* masks, int32_t* counts) {
    std::vector<uint8_t> sky(LIGHT_WORLD_HEIGHT * LIGHT_LAYER), block_light(LIGHT_WORLD_HEIGHT * LIGHT_LAYER);
    light_compute(L, blocks, sky.data(), block_light.data());

    uint32_t sky_mask = 0, block_mask = 0, empty_sky = 0, empty_block = 0;
    int sky_n = 0, block_n = 0;
    auto add = [&](int index, const uint8_t* sky_levels, const uint8_t* block_levels) {
        if (sky_levels && light_pack(sky_levels, sky_out + sky_n * LIGHT_SECTION_BYTES)) {
            sky_mask |= 1u << index;
            sky_n++;
        } else {
            empty_sky |= 1u << index;
        }
        if (block_levels && light_pack(block_levels, block_out + block_n * LIGHT_SECTION_BYTES)) {
            block_mask |= 1u << index;
            block_n++;
        } else {
            empty_block |= 1u << index;
        }
    };

    add(0, nullptr, nullptr);                               // below the world: dark
    for (int s = 0; s < LIGHT_WORLD_HEIGHT / 16; s++) {
        add(s + 1, sky.data() + s * LIGHT_SECTION_VOLUME, block_light.data() + s * LIGHT_SECTION_VOLUME);
    }
    // above the world: open sky (fully lit sky section, no block light)
    std::vector<uint8_t> full(LIGHT_SECTION_VOLUME, 15);
    add(LIGHT_SECTIONS - 1, full.data(), nullptr);

    masks[0] = (int32_t)sky_mask;
    masks[1] = (int32_t)block_mask;
    masks[2] = (int32_t)empty_sky;
    masks[3] = (int32_t)empty_block;
    counts[0] = sky_n;
    counts[1] = block_n;
}

}  // namespace vrs
