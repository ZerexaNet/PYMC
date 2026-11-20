// ============================================================
// PyMC - C API of the native vanilla engine (loaded with ctypes)
//
//   redstone / block updates (BUD, QC, pistons, ...)  -> vrs_tick, vrs_block_changed, ...
//   hoppers                                           -> vrs_tick_hoppers
//   explosions (rays + exposure, thread safe)         -> vrs_explosion_blocks, vrs_exposure
//
// The engine keeps a mirror of the chunks it reads (loaded through a
// callback); every change it makes is logged and drained by Python, which
// writes it to the world storage.
// ============================================================
#include <array>
#include <mutex>

#include "behaviors.h"
#include "hopper.h"
#include "lighting.h"

#if defined(_WIN32)
#define VRS_API extern "C" __declspec(dllexport)
#else
#define VRS_API extern "C" __attribute__((visibility("default")))
#endif

using namespace vrs;

static Level* G = nullptr;
static Hoppers* H = nullptr;
static std::recursive_mutex M;

#define LOCK std::lock_guard<std::recursive_mutex> lock_(M)

static Pos P(int x, int y, int z) { return Pos{x, y, z}; }

VRS_API int vrs_version() { return 4; }

// ---------------------------------------------------------------- light
// Independent of the game state: its own block tables, read-only after vlight_init, so the
// light workers (thread pool) call it without the game lock.
static BlockTable g_light_table;
static LightTables g_light;
static std::mutex g_light_init_mutex;

VRS_API int vlight_init(const char* blocks_json) {
    std::lock_guard<std::mutex> guard(g_light_init_mutex);
    if (g_light.loaded) return 1;
    if (!g_light_table.load(blocks_json)) return 0;
    g_light.build(g_light_table);
    return 1;
}

// blocks: 98304 states, index y*256 + z*16 + x. sky_out / block_out: 26 * 2048 bytes each.
// out[0..3] = sky mask, block mask, empty sky mask, empty block mask; out[4] / out[5] = array counts.
VRS_API int vlight_build_sections(const uint16_t* blocks, uint8_t* sky_out, uint8_t* block_out, int32_t* out) {
    if (!g_light.loaded) return 0;
    int32_t masks[4], counts[2];
    light_build_sections(g_light, blocks, sky_out, block_out, masks, counts);
    out[0] = masks[0]; out[1] = masks[1]; out[2] = masks[2]; out[3] = masks[3];
    out[4] = counts[0]; out[5] = counts[1];
    return 1;
}

// Chunks kept in the mirror. Every chunk is 196 KB; the rest are re-read from storage on demand.
static size_t g_chunk_limit = 256;
VRS_API void vrs_set_chunk_limit(int n) { LOCK; g_chunk_limit = n < 1 ? 1 : (size_t)n; }

VRS_API int vrs_init(const char* blocks_json) {
    LOCK;
    Level* L = new Level();
    if (!L->table.load(blocks_json)) {
        delete L;
        return 0;
    }
    build_registry(*L);
    build_shape_tables(*L);
    delete G;
    delete H;
    G = L;
    H = new Hoppers();
    H->B_COMPOSTER = L->table.index_of("minecraft:composter");
    return 1;
}

// Forget all dynamic state (a new server / world); the block tables stay, so explosion
// workers that use them concurrently are unaffected.
VRS_API void vrs_reset() {
    LOCK;
    Level& L = *G;
    L.chunks.clear(); L.chunk_order.clear();
    L.changes.clear(); L.actions.clear(); L.effects.clear();
    L.ticks = decltype(L.ticks)();
    L.tick_keys.clear(); L.running.clear(); L.sub_tick = 0;
    L.events.clear(); L.event_keys.clear();
    L.moving.clear(); L.moving_order.clear();
    L.comparator_output.clear(); L.torch_toggles.clear();
    L.game_time = 0; L.depth = 0; L.should_signal = true;
    H->entities.clear(); H->changed.clear();
}

VRS_API void vrs_set_callbacks(LoadChunkFn load, ContainerSignalFn signal, EntityCountFn entities) {
    LOCK;
    G->load_chunk = load;
    G->container_signal = signal;
    G->entity_count = entities;
}

VRS_API void vrs_set_hopper_callbacks(InvGetFn get, CanPlaceFn can_place, TakeFn take, GiveFn give, PickupFn pickup,
                                      CompostFn compost, int bone_meal_item) {
    LOCK;
    H->inv_get = get;
    H->can_place = can_place;
    H->take = take;
    H->give = give;
    H->pickup = pickup;
    H->compost = compost;
    H->bone_meal = bone_meal_item;
}

// ---------------------------------------------------------------- chunks
VRS_API void vrs_invalidate_chunk(int cx, int cz) { LOCK; G->invalidate(cx, cz); }
VRS_API void vrs_invalidate_all() { LOCK; G->chunks.clear(); G->chunk_order.clear(); }
VRS_API void vrs_evict(int keep) { LOCK; G->evict((size_t)keep); }
VRS_API int vrs_get_block(int x, int y, int z) { LOCK; return G->raw(P(x, y, z)); }

// --------------------------------------------------------------- stepping
static int guarded(const std::function<void()>& fn) {
    try {
        fn();
        return 1;
    } catch (...) {
        return 0;
    }
}

VRS_API int vrs_tick() {
    LOCK;
    return guarded([] {
        G->tick_all();
        G->evict(g_chunk_limit);   // no pointers into the mirror are held between ticks
    });
}

VRS_API int vrs_tick_hoppers(const int32_t* xyz, int n) {
    LOCK;
    std::vector<Pos> list;
    list.reserve(n);
    for (int i = 0; i < n; i++) list.push_back(P(xyz[i * 3], xyz[i * 3 + 1], xyz[i * 3 + 2]));
    return guarded([&] { H->tick(*G, list); });
}

// hopper minecarts: ids[n], xyz[3n] (entity position), enabled[n]
VRS_API int vrs_tick_hopper_minecarts(const int32_t* ids, const double* xyz, const uint8_t* enabled, int n) {
    LOCK;
    std::vector<MinecartTick> carts;
    carts.reserve(n);
    for (int i = 0; i < n; i++) carts.push_back({ids[i], xyz[i * 3], xyz[i * 3 + 1], xyz[i * 3 + 2], enabled[i] != 0});
    return guarded([&] { H->tick_minecarts(*G, carts); });
}

VRS_API int64_t vrs_game_time() { LOCK; return G->game_time; }
VRS_API void vrs_set_game_time(int64_t t) { LOCK; G->game_time = t; }

// A block was set by something else (placing, breaking, commands, explosions).
VRS_API int vrs_block_changed(int x, int y, int z, int old, int state, int by_player) {
    LOCK;
    return guarded([&] {
        Level& L = *G;
        Pos pos = P(x, y, z);
        L.mirror(pos, state);
        if (L.raw(pos) != state) L.mirror(pos, state);
        if (old == state) return;
        Behavior& nb = L.beh(state);
        if (nb.has_placement_state() && L.bidx(state) != L.bidx(old)) {
            int shaped = nb.placement_state(L, pos, state);
            L.write(pos, shaped);
            state = shaped;
        }
        L.beh(old).on_remove(L, old, pos, state, false);
        if (L.get(pos) == state) L.beh(state).on_place(L, state, pos, old, false);
        if (L.get(pos) == state) {
            L.update_neighbors_at(pos, L.bidx(old));
            Behavior& b = L.beh(state);
            if (b.has_analog_output(state)) L.update_neighbour_for_output_signal(pos, L.bidx(state));
            L.beh(old).update_indirect_neighbour_shapes(L, old, pos, UPDATE_CLIENTS, 511);
            L.update_neighbour_shapes(state, pos, UPDATE_CLIENTS);
            b.update_indirect_neighbour_shapes(L, state, pos, UPDATE_CLIENTS, 511);
            if (state && by_player) b.on_placed_by_player(L, state, pos);
        }
    });
}

// mirror an external write without running any update logic
VRS_API void vrs_mirror_block(int x, int y, int z, int state) { LOCK; G->mirror(P(x, y, z), state); }

VRS_API int vrs_use(int x, int y, int z) {
    LOCK;
    int handled = 0;
    guarded([&] {
        Pos pos = P(x, y, z);
        int st = G->get(pos);
        handled = G->beh(st).use(*G, st, pos) ? 1 : 0;
    });
    return handled;
}

VRS_API int vrs_entity_inside(int x, int y, int z) {
    LOCK;
    return guarded([&] {
        Pos pos = P(x, y, z);
        int st = G->raw(pos);
        if (st >= 0) G->beh(st).entity_inside(*G, st, pos);
    });
}

VRS_API int vrs_container_changed(int x, int y, int z) {
    LOCK;
    return guarded([&] {
        Pos pos = P(x, y, z);
        G->update_neighbour_for_output_signal(pos, G->bidx(G->get(pos)));
    });
}

// Finish every moving piston (before saving the world).
VRS_API int vrs_finish_pistons() {
    LOCK;
    return guarded([] {
        std::vector<Pos> snapshot = G->moving_order;
        for (const Pos& p : snapshot)
            if (G->moving.count(p)) G->final_tick(p);
    });
}

// ----------------------------------------------------------------- drains
// changes: x, y, z, state (in order; the same block can appear repeatedly)
VRS_API int vrs_drain_changes(int32_t* out, int cap) {
    LOCK;
    int n = std::min((int)G->changes.size(), cap);
    for (int i = 0; i < n; i++) {
        const Change& c = G->changes[i];
        out[i * 4] = c.x; out[i * 4 + 1] = c.y; out[i * 4 + 2] = c.z; out[i * 4 + 3] = c.state;
    }
    G->changes.erase(G->changes.begin(), G->changes.begin() + n);
    return n;
}
VRS_API int vrs_pending_changes() { LOCK; return (int)G->changes.size(); }

// effects: kind, x, y, z, a, b
VRS_API int vrs_drain_effects(int32_t* out, int cap) {
    LOCK;
    int n = std::min((int)G->effects.size(), cap);
    for (int i = 0; i < n; i++) {
        const Effect& e = G->effects[i];
        int32_t* o = out + i * 6;
        o[0] = e.kind; o[1] = e.x; o[2] = e.y; o[3] = e.z; o[4] = e.a; o[5] = e.b;
    }
    G->effects.erase(G->effects.begin(), G->effects.begin() + n);
    return n;
}

// block actions: x, y, z, block registry id, event, param
VRS_API int vrs_drain_actions(int32_t* out, int cap) {
    LOCK;
    int n = std::min((int)G->actions.size(), cap);
    for (int i = 0; i < n; i++) {
        const Action& a = G->actions[i];
        int32_t* o = out + i * 6;
        o[0] = a.x; o[1] = a.y; o[2] = a.z; o[3] = a.block_id; o[4] = a.event; o[5] = a.param;
    }
    G->actions.erase(G->actions.begin(), G->actions.begin() + n);
    return n;
}

// inventories changed by hoppers: owner kind, a, b, c (0: block container at a,b,c; 1: entity a)
VRS_API int vrs_drain_hopper_changes(int32_t* out, int cap) {
    LOCK;
    int n = std::min((int)H->changed.size(), cap);
    for (int i = 0; i < n; i++) {
        const Owner& o = H->changed[i];
        out[i * 4] = o.kind; out[i * 4 + 1] = o.a; out[i * 4 + 2] = o.b; out[i * 4 + 3] = o.c;
    }
    H->changed.erase(H->changed.begin(), H->changed.begin() + n);
    return n;
}

// ---------------------------------------------------- scheduled-tick state
VRS_API int vrs_tick_count() { LOCK; return (int)G->ticks.size(); }
VRS_API int vrs_moving_count() { LOCK; return (int)G->moving.size(); }

// pending ticks: x, y, z, block index, delay, priority (in execution order)
VRS_API int vrs_export_ticks(int32_t* out, int cap) {
    LOCK;
    auto copy = G->ticks;
    int n = 0;
    while (!copy.empty() && n < cap) {
        const TickEntry& e = copy.top();
        int32_t* o = out + n * 6;
        o[0] = e.pos.x; o[1] = e.pos.y; o[2] = e.pos.z; o[3] = e.block;
        o[4] = (int32_t)std::max<int64_t>(1, e.time - G->game_time); o[5] = e.priority;
        copy.pop();
        n++;
    }
    return n;
}
VRS_API void vrs_schedule_tick(int x, int y, int z, int block_index, int delay, int priority) {
    LOCK;
    G->schedule_tick(P(x, y, z), block_index, delay, priority);
}
VRS_API int vrs_block_index(const char* name) { LOCK; return G->table.index_of(name); }
VRS_API int vrs_block_index_of_state(int state) { LOCK; return G->bidx(state); }

VRS_API int vrs_export_comparators(int32_t* out, int cap) {
    LOCK;
    int n = 0;
    for (auto& kv : G->comparator_output) {
        if (n >= cap) break;
        if (!kv.second) continue;
        out[n * 4] = kv.first.x; out[n * 4 + 1] = kv.first.y; out[n * 4 + 2] = kv.first.z; out[n * 4 + 3] = kv.second;
        n++;
    }
    return n;
}
VRS_API void vrs_set_comparator(int x, int y, int z, int value) { LOCK; G->comparator_output[P(x, y, z)] = value; }

// ---------------------------------------------------------------- explosions
// Thread safe: reads only the immutable block tables and the chunk buffers given.
// Each buffer holds rows ymin .. ymin+rows-1 of one chunk (256 blocks per row, z*16+x).
struct ChunkView {
    int n;
    const int32_t* cxz;
    const uint16_t* const* data;
    int ymin, rows;
    int last = -1;
    int get(int x, int y, int z) {
        if (y < -64 || y > 319) return -1;
        if (y < ymin || y >= ymin + rows) return 0;
        int cx = x >> 4, cz = z >> 4;
        if (last < 0 || cxz[last * 2] != cx || cxz[last * 2 + 1] != cz) {
            last = -1;
            for (int i = 0; i < n; i++)
                if (cxz[i * 2] == cx && cxz[i * 2 + 1] == cz) { last = i; break; }
            if (last < 0) return -1;
        }
        return data[last][(y - ymin) * 256 + (z & 15) * 16 + (x & 15)];
    }
};

static std::vector<std::array<double, 3>> make_rays() {
    std::vector<std::array<double, 3>> rays;
    for (int i = 0; i < 16; i++)
        for (int j = 0; j < 16; j++)
            for (int k = 0; k < 16; k++) {
                if (i != 0 && i != 15 && j != 0 && j != 15 && k != 0 && k != 15) continue;
                double dx = i / 15.0 * 2 - 1, dy = j / 15.0 * 2 - 1, dz = k / 15.0 * 2 - 1;
                double len = std::sqrt(dx * dx + dy * dy + dz * dz);
                rays.push_back({dx / len, dy / len, dz / len});
            }
    return rays;
}

// Explosion.explode(): destroyed positions (unique, in discovery order).
// rand holds 1352 uniform [0,1) numbers, one per ray (intensity power*(0.7+r*0.6)).
VRS_API int vrs_explosion_blocks(int n_chunks, const int32_t* cxz, const uint16_t* const* data, int ymin, int rows,
                                 double x, double y, double z, double power, const double* rand, int32_t* out,
                                 int cap) {
    if (!G) return -1;
    static const std::vector<std::array<double, 3>> rays = make_rays();
    const BlockTable& T = G->table;
    ChunkView view{n_chunks, cxz, data, ymin, rows};
    std::unordered_set<Pos, PosHash> seen;
    int n = 0;
    for (size_t r = 0; r < rays.size(); r++) {
        double intensity = power * (0.7 + rand[r] * 0.6);
        double px = x, py = y, pz = z;
        const auto& d = rays[r];
        while (intensity > 0.0) {
            int bx = (int)std::floor(px), by = (int)std::floor(py), bz = (int)std::floor(pz);
            int st = view.get(bx, by, bz);
            if (st < 0) break;
            if (st != 0) {
                intensity -= (T.info(st).resistance + 0.3) * 0.3;
                if (intensity > 0.0) {
                    Pos p{bx, by, bz};
                    if (seen.insert(p).second && n < cap) {
                        out[n * 3] = bx; out[n * 3 + 1] = by; out[n * 3 + 2] = bz;
                        n++;
                    }
                }
            }
            px += d[0] * 0.3;
            py += d[1] * 0.3;
            pz += d[2] * 0.3;
            intensity -= 0.22500001;
        }
    }
    return n;
}

static bool clear_line(ChunkView& view, const std::vector<uint8_t>& passable, double sx, double sy, double sz,
                       double ex, double ey, double ez) {
    double dx = ex - sx, dy = ey - sy, dz = ez - sz;
    double len = std::sqrt(dx * dx + dy * dy + dz * dz);
    int steps = std::max(1, (int)(len / 0.25));
    bool have_last = false;
    int lx = 0, ly = 0, lz = 0;
    for (int i = 0; i < steps; i++) {
        double t = (double)i / steps;
        int cx = (int)std::floor(sx + dx * t), cy = (int)std::floor(sy + dy * t), cz = (int)std::floor(sz + dz * t);
        if (have_last && cx == lx && cy == ly && cz == lz) continue;
        have_last = true;
        lx = cx; ly = cy; lz = cz;
        int st = view.get(cx, cy, cz);
        if (st >= 0 && !(st < (int)passable.size() && passable[st])) return false;
    }
    return true;
}

// Explosion.getSeenPercent for the box (x0..x1, y0..y1, z0..z1) seen from (cx, cy, cz).
VRS_API double vrs_exposure(int n_chunks, const int32_t* cxz, const uint16_t* const* data, int ymin, int rows,
                            double cx, double cy, double cz, double x0, double y0, double z0, double x1, double y1,
                            double z1) {
    if (!G) return 0.0;
    ChunkView view{n_chunks, cxz, data, ymin, rows};
    double sx = 1.0 / ((x1 - x0) * 2.0 + 1.0);
    double sy = 1.0 / ((y1 - y0) * 2.0 + 1.0);
    double sz = 1.0 / ((z1 - z0) * 2.0 + 1.0);
    double ox = (1.0 - std::floor(1.0 / sx) * sx) / 2.0;
    double oz = (1.0 - std::floor(1.0 / sz) * sz) / 2.0;
    int seen = 0, total = 0;
    for (double fx = 0.0; fx <= 1.0; fx += sx)
        for (double fy = 0.0; fy <= 1.0; fy += sy)
            for (double fz = 0.0; fz <= 1.0; fz += sz) {
                double px = x0 + (x1 - x0) * fx + ox;
                double py = y0 + (y1 - y0) * fy;
                double pz = z0 + (z1 - z0) * fz + oz;
                if (clear_line(view, G->no_collision, px, py, pz, cx, cy, cz)) seen++;
                total++;
            }
    return total ? (double)seen / total : 0.0;
}
