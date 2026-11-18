// ============================================================
// PyMC - vanilla 1.21.1 block update / redstone engine (C++ port of world/rs)
//
// Same model and order as the Python reference implementation:
//   setBlock with flags, onRemove/onPlace, block updates (W,E,D,U,N,S),
//   shape updates (W,E,N,S,D,U), scheduled ticks by (tick, priority, sub-tick),
//   block events, moving-piston block entities.
// Quasi-connectivity, BUD, 0-tick and TNT duplication emerge from it.
// ============================================================
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <queue>
#include <random>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "blocktable.h"

namespace vrs {

// ---------------------------------------------------------------- basics
enum Dir { DOWN = 0, UP = 1, NORTH = 2, SOUTH = 3, WEST = 4, EAST = 5, NODIR = 6 };
static const int DX[6] = {0, 0, 0, 0, -1, 1}, DY[6] = {-1, 1, 0, 0, 0, 0}, DZ[6] = {0, 0, -1, 1, 0, 0};
static const Dir OPPD[6] = {UP, DOWN, SOUTH, NORTH, EAST, WEST};
static const char* DIR_NAME[6] = {"down", "up", "north", "south", "west", "east"};
static const Dir DIRECTIONS[6] = {DOWN, UP, NORTH, SOUTH, WEST, EAST};
static const Dir UPDATE_ORDER[6] = {WEST, EAST, DOWN, UP, NORTH, SOUTH};
static const Dir SHAPE_ORDER[6] = {WEST, EAST, NORTH, SOUTH, DOWN, UP};
static const Dir HORIZONTAL[4] = {NORTH, EAST, SOUTH, WEST};
static const Dir VERTICAL[2] = {UP, DOWN};
inline Dir cw(Dir d) { return d == NORTH ? EAST : d == EAST ? SOUTH : d == SOUTH ? WEST : NORTH; }
inline Dir ccw(Dir d) { return d == NORTH ? WEST : d == WEST ? SOUTH : d == SOUTH ? EAST : NORTH; }
inline int axis(Dir d) { return d <= UP ? 1 : (d <= SOUTH ? 2 : 0); }
inline Dir dir_from(const std::string& s) {
    for (int i = 0; i < 6; i++)
        if (s == DIR_NAME[i]) return (Dir)i;
    return NODIR;
}

struct Pos {
    int x = 0, y = 0, z = 0;
    bool operator==(const Pos& o) const { return x == o.x && y == o.y && z == o.z; }
    bool operator!=(const Pos& o) const { return !(*this == o); }
    Pos rel(Dir d, int n = 1) const { return {x + DX[d] * n, y + DY[d] * n, z + DZ[d] * n}; }
};
struct PosHash {
    size_t operator()(const Pos& p) const {
        return std::hash<int64_t>()(((int64_t)p.x * 73856093) ^ ((int64_t)p.y * 19349663) ^ ((int64_t)p.z * 83492791));
    }
};

enum Flags { UPDATE_NEIGHBORS = 1, UPDATE_CLIENTS = 2, UPDATE_INVISIBLE = 4, UPDATE_KNOWN_SHAPE = 16,
             UPDATE_SUPPRESS_DROPS = 32, UPDATE_MOVE_BY_PISTON = 64, UPDATE_ALL = 3 };
enum Priority { EXTREMELY_HIGH = -3, VERY_HIGH = -2, HIGH = -1, NORMAL = 0 };
enum EffectKind { FX_DROP = 1, FX_SOUND = 2, FX_NOTE = 3, FX_DISPENSE = 4, FX_PRIME_TNT = 5, FX_BURNOUT = 6 };
enum Sound { SND_LEVER = 1, SND_STONE_BUTTON = 2, SND_WOOD_BUTTON = 3, SND_PISTON_OUT = 4, SND_PISTON_IN = 5,
             SND_COMPOSTER_FILL = 6, SND_COMPOSTER_FILL_SUCCESS = 7, SND_COMPOSTER_EMPTY = 8, SND_COMPOSTER_READY = 9 };

// Java BlockPos.hashCode and HashSet/HashMap iteration order
inline int32_t blockpos_hash(const Pos& p) {
    uint32_t h = (uint32_t)p.y + (uint32_t)p.z * 31u;
    h = h * 31u + (uint32_t)p.x;
    return (int32_t)h;
}
inline std::vector<Pos> java_hash_order(const std::vector<Pos>& in) {
    std::vector<Pos> seen;
    for (const Pos& p : in)
        if (std::find(seen.begin(), seen.end(), p) == seen.end()) seen.push_back(p);
    uint32_t cap = 16;
    while (seen.size() > cap * 0.75) cap *= 2;
    std::vector<std::pair<std::pair<uint32_t, size_t>, Pos>> keyed;
    for (size_t i = 0; i < seen.size(); i++) {
        uint32_t h = (uint32_t)blockpos_hash(seen[i]);
        keyed.push_back({{(h ^ (h >> 16)) & (cap - 1), i}, seen[i]});
    }
    std::sort(keyed.begin(), keyed.end(), [](auto& a, auto& b) { return a.first < b.first; });
    std::vector<Pos> out;
    for (auto& k : keyed) out.push_back(k.second);
    return out;
}

struct Effect { int kind, x, y, z, a, b; };
struct Action { int x, y, z, block_id, event, param; };
struct Change { int x, y, z, state; };

typedef int (*LoadChunkFn)(int cx, int cz, uint16_t* out);
typedef int (*ContainerSignalFn)(int x, int y, int z);
typedef int (*EntityCountFn)(int x, int y, int z, int mode);

class Level;

// ------------------------------------------------------------ behaviours
struct Behavior {
    virtual ~Behavior() {}
    virtual void neighbor_changed(Level&, int, Pos, int /*source block*/, Pos, bool) {}
    virtual void on_place(Level&, int, Pos, int /*old*/, bool) {}
    virtual void on_remove(Level&, int, Pos, int /*new*/, bool) {}
    virtual int update_shape(Level&, int state, Dir, int, Pos, Pos) { return state; }
    virtual void update_indirect_neighbour_shapes(Level&, int, Pos, int, int) {}
    virtual void tick(Level&, int, Pos) {}
    virtual bool use(Level&, int, Pos) { return false; }
    virtual bool trigger_event(Level&, int, Pos, int, int) { return false; }
    virtual int get_signal(Level&, int, Pos, Dir) { return 0; }
    virtual int get_direct_signal(Level&, int, Pos, Dir) { return 0; }
    virtual bool is_signal_source(int) { return false; }
    virtual bool has_analog_output(int) { return false; }
    virtual int analog_output(Level&, int, Pos) { return 0; }
    virtual int placement_state(Level&, Pos, int state) { return state; }
    virtual bool has_placement_state() { return false; }
    virtual void on_placed_by_player(Level&, int, Pos) {}
    virtual void entity_inside(Level&, int, Pos) {}
};

struct MovingPiston {
    Pos pos;
    int moved_state = 0;
    Dir direction = NORTH;
    bool extending = false, is_source = false;
    double progress = 0.0, progress_o = 0.0;
    int64_t last_ticked = -1;
};

struct TickEntry {
    int64_t time;
    int priority;
    int64_t sub;
    Pos pos;
    int block;
    bool operator>(const TickEntry& o) const {
        if (time != o.time) return time > o.time;
        if (priority != o.priority) return priority > o.priority;
        return sub > o.sub;
    }
};

struct TickKey {
    Pos pos;
    int block;
    bool operator==(const TickKey& o) const { return pos == o.pos && block == o.block; }
};
struct TickKeyHash {
    size_t operator()(const TickKey& k) const { return PosHash()(k.pos) * 31 + (size_t)k.block; }
};
struct EventKey {
    Pos pos;
    int block, id, param;
    bool operator==(const EventKey& o) const { return pos == o.pos && block == o.block && id == o.id && param == o.param; }
};
struct EventKeyHash {
    size_t operator()(const EventKey& k) const { return PosHash()(k.pos) * 131 + k.block * 7 + k.id * 3 + k.param; }
};

// ------------------------------------------------------------------ level
class Level {
public:
    BlockTable table;
    std::vector<Behavior*> behaviors;           // by block index
    Behavior default_behavior;
    std::vector<std::unique_ptr<Behavior>> owned;
    std::vector<uint8_t> conductor, sturdy_full, no_collision;  // by state

    LoadChunkFn load_chunk = nullptr;
    ContainerSignalFn container_signal = nullptr;
    EntityCountFn entity_count = nullptr;

    int64_t game_time = 0;
    bool should_signal = true;
    int depth = 0;
    static const int MAX_DEPTH = 6000;

    std::unordered_map<int64_t, std::vector<uint16_t>> chunks;
    std::deque<int64_t> chunk_order;

    std::vector<Change> changes;
    std::vector<Action> actions;
    std::vector<Effect> effects;

    std::priority_queue<TickEntry, std::vector<TickEntry>, std::greater<TickEntry>> ticks;
    std::unordered_set<TickKey, TickKeyHash> tick_keys, running;
    int64_t sub_tick = 0;
    std::deque<EventKey> events;
    std::unordered_set<EventKey, EventKeyHash> event_keys;

    std::unordered_map<Pos, MovingPiston, PosHash> moving;
    std::vector<Pos> moving_order;
    std::unordered_map<Pos, int, PosHash> comparator_output;
    std::unordered_map<Pos, std::deque<int64_t>, PosHash> torch_toggles;

    // block indices used by the engine
    int B_AIR = 0, B_WIRE, B_REPEATER, B_COMPARATOR, B_OBSERVER, B_REDSTONE_BLOCK, B_HOPPER, B_MOVING_PISTON,
        B_PISTON_HEAD, B_PISTON, B_STICKY_PISTON, B_TRIPWIRE, B_HOOK, B_TNT, B_SLIME, B_HONEY;

    // ---- storage
    static int64_t ckey(int cx, int cz) { return ((int64_t)cx << 32) ^ (uint32_t)cz; }

    uint16_t* chunk(int cx, int cz) {
        int64_t k = ckey(cx, cz);
        auto it = chunks.find(k);
        if (it != chunks.end()) return it->second.data();
        if (!load_chunk) return nullptr;
        std::vector<uint16_t> buf(98304);
        if (!load_chunk(cx, cz, buf.data())) return nullptr;
        chunks[k] = std::move(buf);
        chunk_order.push_back(k);
        return chunks[k].data();
    }
    void evict(size_t keep) {
        while (chunks.size() > keep && !chunk_order.empty()) {
            chunks.erase(chunk_order.front());
            chunk_order.pop_front();
        }
    }
    void invalidate(int cx, int cz) {
        int64_t k = ckey(cx, cz);
        chunks.erase(k);
        chunk_order.erase(std::remove(chunk_order.begin(), chunk_order.end(), k), chunk_order.end());
    }
    int raw(Pos p) {
        if (p.y < -64 || p.y > 319) return -1;
        uint16_t* c = chunk(p.x >> 4, p.z >> 4);
        if (!c) return -1;
        return c[(p.y + 64) * 256 + (p.z & 15) * 16 + (p.x & 15)];
    }
    int get(Pos p) { int s = raw(p); return s < 0 ? 0 : s; }
    bool write(Pos p, int state) {
        if (p.y < -64 || p.y > 319) return false;
        uint16_t* c = chunk(p.x >> 4, p.z >> 4);
        if (!c) return false;
        c[(p.y + 64) * 256 + (p.z & 15) * 16 + (p.x & 15)] = (uint16_t)state;
        changes.push_back({p.x, p.y, p.z, state});
        return true;
    }
    // external write already in PyMC's storage: keep the mirror in sync (no log)
    void mirror(Pos p, int state) {
        if (p.y < -64 || p.y > 319) return;
        int64_t k = ckey(p.x >> 4, p.z >> 4);
        auto it = chunks.find(k);
        if (it != chunks.end()) it->second[(p.y + 64) * 256 + (p.z & 15) * 16 + (p.x & 15)] = (uint16_t)state;
    }

    // ---- helpers
    int bidx(int state) const { return table.block_index(state); }
    Behavior& beh(int state) { return *behaviors[table.block_index(state)]; }
    bool is_block(int state, int block_index) const { return table.block_index(state) == block_index; }
    bool is_conductor(int state) const { return state > 0 && state < (int)conductor.size() && conductor[state]; }
    bool is_full(int state) const { return state > 0 && state < (int)sturdy_full.size() && sturdy_full[state]; }
    bool passable(int state) const { return state >= 0 && state < (int)no_collision.size() && no_collision[state]; }
    const std::string& name(int state) const { return table.info(state).name; }
    const std::string& short_name(int state) const { return table.info(state).short_name; }
    int def(int block_index) const { return table.blocks[block_index].default_state; }

    bool face_sturdy(int state, Dir face) const {
        if (state <= 0) return false;
        if (is_full(state)) return true;
        const std::string& n = short_name(state);
        auto ends = [&](const char* suf) { size_t l = strlen(suf); return n.size() >= l && n.compare(n.size() - l, l, suf) == 0; };
        if (ends("_slab")) {
            const std::string& t = table.prop(state, "type");
            return t == "double" || (t == "top" && face == UP) || (t == "bottom" && face == DOWN);
        }
        if (ends("_stairs")) {
            const std::string& h = table.prop(state, "half");
            return (face == UP && h == "top") || (face == DOWN && h == "bottom") || DIR_NAME[face] == table.prop(state, "facing");
        }
        return false;
    }

    // ---- setBlock
    bool set_block(Pos pos, int state, int flags = UPDATE_ALL, int recursion = 512) {
        int old = raw(pos);
        if (old < 0 || old == state) return false;
        bool moved = flags & UPDATE_MOVE_BY_PISTON;
        write(pos, state);
        beh(old).on_remove(*this, old, pos, state, moved);
        if (raw(pos) != state) return true;
        beh(state).on_place(*this, state, pos, old, moved);
        if (raw(pos) != state) return true;
        if (flags & UPDATE_NEIGHBORS) {
            update_neighbors_at(pos, bidx(old));
            if (beh(state).has_analog_output(state)) update_neighbour_for_output_signal(pos, bidx(state));
        }
        if (!(flags & UPDATE_KNOWN_SHAPE) && recursion > 0) {
            int f = flags & ~(UPDATE_NEIGHBORS | UPDATE_SUPPRESS_DROPS);
            beh(old).update_indirect_neighbour_shapes(*this, old, pos, f, recursion - 1);
            update_neighbour_shapes(state, pos, f, recursion - 1);
            beh(state).update_indirect_neighbour_shapes(*this, state, pos, f, recursion - 1);
        }
        return true;
    }
    bool remove_block(Pos pos, bool moved = false) { return set_block(pos, 0, UPDATE_ALL | (moved ? UPDATE_MOVE_BY_PISTON : 0)); }
    bool destroy_block(Pos pos, bool drop = true, int recursion = 512) {
        int state = get(pos);
        if (state == 0) return false;
        if (drop) drop_resources(state, pos);
        return set_block(pos, 0, UPDATE_ALL, recursion);
    }
    void drop_resources(int state, Pos pos) { effects.push_back({FX_DROP, pos.x, pos.y, pos.z, state, 0}); }
    void effect(int kind, Pos p, int a = 0, int b = 0) { effects.push_back({kind, p.x, p.y, p.z, a, b}); }

    // ---- updates
    void neighbor_changed(Pos pos, int source, Pos from, bool moved = false) {
        int state = raw(pos);
        if (state < 0) return;
        if (depth > MAX_DEPTH) return;
        depth++;
        beh(state).neighbor_changed(*this, state, pos, source, from, moved);
        depth--;
    }
    void update_neighbors_at(Pos pos, int source) {
        for (Dir d : UPDATE_ORDER) neighbor_changed(pos.rel(d), source, pos);
    }
    void update_neighbors_at_except(Pos pos, int source, Dir skip) {
        for (Dir d : UPDATE_ORDER)
            if (d != skip) neighbor_changed(pos.rel(d), source, pos);
    }
    void update_neighbour_shapes(int state, Pos pos, int flags, int recursion = 512) {
        if (depth > MAX_DEPTH) return;
        depth++;
        for (Dir d : SHAPE_ORDER) {
            Pos np = pos.rel(d);
            int ns = raw(np);
            if (ns < 0) continue;
            int nw = beh(ns).update_shape(*this, ns, OPPD[d], state, np, pos);
            update_or_destroy(ns, nw, np, flags, recursion);
        }
        depth--;
    }
    void neighbor_shape_changed(Dir d, int neighbor_state, Pos pos, Pos npos, int flags, int recursion) {
        int state = raw(pos);
        if (state < 0) return;
        int nw = beh(state).update_shape(*this, state, d, neighbor_state, pos, npos);
        update_or_destroy(state, nw, pos, flags, recursion);
    }
    void update_or_destroy(int old, int nw, Pos pos, int flags, int recursion = 512) {
        if (nw == old) return;
        if (nw == 0) {
            if (old != 0) destroy_block(pos, !(flags & UPDATE_SUPPRESS_DROPS), recursion);
        } else {
            set_block(pos, nw, flags & ~UPDATE_SUPPRESS_DROPS, recursion);
        }
    }
    int update_from_neighbour_shapes(int state, Pos pos) {
        for (Dir d : SHAPE_ORDER) {
            Pos np = pos.rel(d);
            state = beh(state).update_shape(*this, state, d, get(np), pos, np);
        }
        return state;
    }
    void update_neighbour_for_output_signal(Pos pos, int source) {
        for (Dir d : HORIZONTAL) {
            Pos np = pos.rel(d);
            int ns = raw(np);
            if (ns < 0) continue;
            if (is_block(ns, B_COMPARATOR)) {
                beh(ns).neighbor_changed(*this, ns, np, source, pos, false);
            } else if (is_conductor(ns)) {
                np = np.rel(d);
                ns = raw(np);
                if (ns >= 0 && is_block(ns, B_COMPARATOR)) beh(ns).neighbor_changed(*this, ns, np, source, pos, false);
            }
        }
    }

    // ---- signals (direction points from the querying block to the emitter)
    int get_signal(Pos pos, Dir d) {
        int state = get(pos);
        int i = beh(state).get_signal(*this, state, pos, d);
        if (is_conductor(state)) return std::max(i, get_direct_signal_to(pos));
        return i;
    }
    int get_direct_signal(Pos pos, Dir d) {
        int state = get(pos);
        return beh(state).get_direct_signal(*this, state, pos, d);
    }
    int get_direct_signal_to(Pos pos) {
        int best = 0;
        for (Dir d : DIRECTIONS) {
            int j = get_direct_signal(pos.rel(d), d);
            if (j >= 15) return 15;
            best = std::max(best, j);
        }
        return best;
    }
    bool has_signal(Pos pos, Dir d) { return get_signal(pos, d) > 0; }
    bool has_neighbor_signal(Pos pos) {
        for (Dir d : DIRECTIONS)
            if (get_signal(pos.rel(d), d) > 0) return true;
        return false;
    }
    int get_best_neighbor_signal(Pos pos) {
        int best = 0;
        for (Dir d : DIRECTIONS) {
            int j = get_signal(pos.rel(d), d);
            if (j >= 15) return 15;
            best = std::max(best, j);
        }
        return best;
    }
    int get_control_input_signal(Pos pos, Dir d, bool diodes_only) {
        int state = get(pos);
        int b = bidx(state);
        if (diodes_only) return (b == B_REPEATER || b == B_COMPARATOR) ? get_direct_signal(pos, d) : 0;
        if (b == B_REDSTONE_BLOCK) return 15;
        if (b == B_WIRE) return table.prop_int(state, "power");
        if (beh(state).is_signal_source(state)) return get_direct_signal(pos, d);
        return 0;
    }

    // ---- scheduled ticks
    void schedule_tick(Pos pos, int block, int delay, int priority = NORMAL) {
        TickKey k{pos, block};
        if (tick_keys.count(k)) return;
        tick_keys.insert(k);
        ticks.push({game_time + std::max(1, delay), priority, ++sub_tick, pos, block});
    }
    bool has_scheduled_tick(Pos pos, int block) { return tick_keys.count({pos, block}) > 0; }
    bool will_tick_this_tick(Pos pos, int block) { return running.count({pos, block}) > 0; }
    void run_scheduled_ticks(size_t limit = 65536) {
        std::vector<TickEntry> due;
        while (!ticks.empty() && ticks.top().time <= game_time && due.size() < limit) {
            TickEntry e = ticks.top();
            ticks.pop();
            tick_keys.erase({e.pos, e.block});
            due.push_back(e);
        }
        running.clear();
        for (auto& e : due) running.insert({e.pos, e.block});
        for (auto& e : due) {
            running.erase({e.pos, e.block});
            int state = raw(e.pos);
            if (state < 0 || bidx(state) != e.block) continue;
            beh(state).tick(*this, state, e.pos);
        }
        running.clear();
    }

    // ---- block events
    void block_event(Pos pos, int block, int id, int param) {
        EventKey k{pos, block, id, param};
        if (event_keys.count(k)) return;
        event_keys.insert(k);
        events.push_back(k);
    }
    void run_block_events() {
        int rounds = 0;
        while (!events.empty() && rounds++ < 65536) {
            EventKey k = events.front();
            events.pop_front();
            event_keys.erase(k);
            int state = raw(k.pos);
            if (state < 0 || bidx(state) != k.block) continue;
            if (beh(state).trigger_event(*this, state, k.pos, k.id, k.param))
                actions.push_back({k.pos.x, k.pos.y, k.pos.z, table.blocks[k.block].id, k.id, k.param});
        }
    }

    // ---- moving pistons (block entities)
    // insertion-ordered like the Python dict (re-adding after removal goes to the end)
    void add_moving(const MovingPiston& m) {
        if (!moving.count(m.pos)) moving_order.push_back(m.pos);
        moving[m.pos] = m;
    }
    void remove_moving(Pos p) {
        if (moving.erase(p)) moving_order.erase(std::find(moving_order.begin(), moving_order.end(), p));
    }
    void tick_moving_piston(Pos p);
    void final_tick(Pos p);
    void tick_block_entities() {
        std::vector<Pos> snapshot = moving_order;
        for (const Pos& p : snapshot)
            if (moving.count(p)) tick_moving_piston(p);
    }

    void tick_all() {
        game_time++;
        run_scheduled_ticks();
        run_block_events();
        tick_block_entities();
    }
};

}  // namespace vrs
