// ============================================================
// PyMC - per-chunk light (sky + block), native port of world/lighting.py
//
// The algorithm is the one world/lighting.py describes: direct sky light
// column by column, sideways spread from the columns whose light stops
// higher up, then block light from every emitting block. Both spreads are
// FIFO flood fills that re-queue a cell whenever its level improves, so the
// result is the same as the Python version (tests/test_light_native.py
// compares the two on random and generated chunks).
//
// Blocks are a flat [y][z][x] array of state ids: index = y*256 + z*16 + x.
// ============================================================
#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <vector>

namespace vrs::light {

constexpr int LAYER = 256;

struct Tables {
    std::vector<uint8_t> opacity;   // by state id; states past the end count as 15
    std::vector<uint8_t> emission;  // by state id
};

inline Tables& tables() {
    static Tables t;
    return t;
}

// Set once at start-up (before any compute call runs).
inline void set_tables(const uint8_t* opacity, const uint8_t* emission, int n) {
    Tables& t = tables();
    t.opacity.assign(opacity, opacity + n);
    t.emission.assign(emission, emission + n);
}

inline int opacity_of(uint16_t state) {
    const auto& op = tables().opacity;
    return state < op.size() ? op[state] : 15;
}

inline int emission_of(uint16_t state) {
    const auto& em = tables().emission;
    return state < em.size() ? em[state] : 0;
}

using Queue = std::deque<std::array<int, 3>>;

// Flood fill from the queued cells (x, y, z); a neighbour loses max(1, opacity).
inline void spread(uint8_t* light, Queue& queue, const uint16_t* blocks, int height) {
    static const int D[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    while (!queue.empty()) {
        const auto cell = queue.front();
        queue.pop_front();
        const int x = cell[0], y = cell[1], z = cell[2];
        const int level = light[y * LAYER + z * 16 + x];
        if (level <= 1) continue;
        for (const auto& d : D) {
            const int nx = x + d[0], ny = y + d[1], nz = z + d[2];
            if (nx < 0 || nx > 15 || nz < 0 || nz > 15 || ny < 0 || ny >= height) continue;
            const int index = ny * LAYER + nz * 16 + nx;
            const int cost = opacity_of(blocks[index]);
            const int new_level = level - (cost > 1 ? cost : 1);
            if (new_level <= 0) continue;
            if (light[index] < new_level) {
                light[index] = (uint8_t)new_level;
                queue.push_back({nx, ny, nz});
            }
        }
    }
}

// blocks: height*256 state ids. sky and block_light: height*256 levels each (overwritten).
inline void compute(const uint16_t* blocks, int height, uint8_t* sky, uint8_t* block_light) {
    const size_t total = (size_t)height * LAYER;
    std::memset(sky, 0, total);
    std::memset(block_light, 0, total);
    if (height <= 0) return;

    // Highest layer that contains anything: everything above is open sky.
    int top = height - 1;
    while (top >= 0) {
        bool any = false;
        const uint16_t* layer = blocks + top * LAYER;
        for (int i = 0; i < LAYER && !any; i++) any = layer[i] != 0;
        if (any) break;
        top--;
    }
    for (size_t i = (size_t)(top + 1) * LAYER; i < total; i++) sky[i] = 15;

    // --- direct sky light, column by column ---
    int floors[16][16] = {};  // lowest layer still at level 15, per (z, x)
    Queue queue;
    for (int z = 0; z < 16; z++) {
        for (int x = 0; x < 16; x++) {
            int level = 15;
            bool broke = false;
            const int offset = z * 16 + x;
            for (int y = top; y >= 0; y--) {
                const int cost = opacity_of(blocks[y * LAYER + offset]);
                if (level == 15) {
                    if (cost) {
                        level -= cost;
                        floors[z][x] = y + 1;
                        if (level <= 0) { broke = true; break; }
                        sky[y * LAYER + offset] = (uint8_t)level;
                        queue.push_back({x, y, z});
                    } else {
                        sky[y * LAYER + offset] = 15;
                    }
                } else {
                    level -= cost > 1 ? cost : 1;
                    if (level <= 0) { broke = true; break; }
                    sky[y * LAYER + offset] = (uint8_t)level;
                    queue.push_back({x, y, z});
                }
            }
            if (!broke) floors[z][x] = 0;
        }
    }

    // --- sideways spread: cells below the highest neighbouring column's floor ---
    for (int z = 0; z < 16; z++) {
        for (int x = 0; x < 16; x++) {
            const int floor = floors[z][x];
            int highest = floor;
            if (x > 0 && floors[z][x - 1] > highest) highest = floors[z][x - 1];
            if (x < 15 && floors[z][x + 1] > highest) highest = floors[z][x + 1];
            if (z > 0 && floors[z - 1][x] > highest) highest = floors[z - 1][x];
            if (z < 15 && floors[z + 1][x] > highest) highest = floors[z + 1][x];
            const int stop = highest < top + 1 ? highest : top + 1;
            for (int y = floor; y < stop; y++) queue.push_back({x, y, z});
        }
    }
    spread(sky, queue, blocks, height);

    // --- block light ---
    queue.clear();
    for (int y = 0; y <= top; y++) {
        for (int z = 0; z < 16; z++) {
            for (int x = 0; x < 16; x++) {
                const uint16_t state = blocks[y * LAYER + z * 16 + x];
                const int emit = emission_of(state);
                if (emit > 0) {
                    block_light[y * LAYER + z * 16 + x] = (uint8_t)emit;
                    queue.push_back({x, y, z});
                }
            }
        }
    }
    if (!queue.empty()) spread(block_light, queue, blocks, height);
}

}  // namespace vrs::light
