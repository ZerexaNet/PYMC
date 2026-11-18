// ============================================================
// PyMC - vanilla redstone components (C++ port of world/rs/blocks.py,
// world/rs/piston.py). Keep in sync with the Python reference.
// ============================================================
#pragma once

#include "engine.h"

namespace vrs {

inline bool ends_with(const std::string& s, const char* suf) {
    size_t l = strlen(suf);
    return s.size() >= l && s.compare(s.size() - l, l, suf) == 0;
}
inline Dir facing(Level& L, int state) { return dir_from(L.table.prop(state, "facing")); }
inline bool prop_true(Level& L, int state, const char* key) { return L.table.is(state, key, "true"); }
inline bool support_ok(Level& L, Pos pos, Dir to_support) {
    return L.face_sturdy(L.get(pos.rel(to_support)), OPPD[to_support]);
}

// ---------------------------------------------------------- redstone wire
struct RedstoneWire : Behavior {
    int self;
    explicit RedstoneWire(int s) : self(s) {}

    static bool connected(const std::string& side) { return !side.empty() && side != "none"; }
    bool is_dot(Level& L, int st) {
        for (Dir d : HORIZONTAL) if (L.table.prop(st, DIR_NAME[d]) != "none") return false;
        return true;
    }
    bool is_cross(Level& L, int st) {
        for (Dir d : HORIZONTAL) if (!connected(L.table.prop(st, DIR_NAME[d]))) return false;
        return true;
    }
    int cross_state(Level& L, int power) {
        int st = L.def(self);
        for (Dir d : HORIZONTAL) st = L.table.with(st, DIR_NAME[d], "side");
        return L.table.with(st, "power", power);
    }
    static bool can_survive_on(Level& L, int state) { return L.face_sturdy(state, UP) || L.is_block(state, L.B_HOPPER); }
    bool survives(Level& L, Pos pos) { return can_survive_on(L, L.get(pos.rel(DOWN))); }

    static bool should_connect_to(Level& L, int state, Dir d) {
        int b = L.bidx(state);
        if (b == L.B_WIRE) return true;
        if (b == L.B_REPEATER) {
            Dir f = facing(L, state);
            return d != NODIR && (f == d || f == OPPD[d]);
        }
        if (b == L.B_OBSERVER) return d == facing(L, state);
        return d != NODIR && L.beh(state).is_signal_source(state);
    }
    std::string connecting_side(Level& L, Pos pos, Dir d, int nca = -1) {
        bool non_conductor_above = nca < 0 ? !L.is_conductor(L.get(pos.rel(UP))) : nca == 1;
        Pos np = pos.rel(d);
        int ns = L.get(np);
        if (non_conductor_above) {
            bool trapdoor = ends_with(L.short_name(ns), "_trapdoor");
            if ((trapdoor || can_survive_on(L, ns)) && should_connect_to(L, L.get(np.rel(UP)), NODIR)) {
                if (L.face_sturdy(ns, OPPD[d])) return "up";
                return "side";
            }
        }
        if (!should_connect_to(L, ns, d) && (L.is_conductor(ns) || !should_connect_to(L, L.get(np.rel(DOWN)), NODIR)))
            return "none";
        return "side";
    }
    int missing_connections(Level& L, int st, Pos pos) {
        int nca = L.is_conductor(L.get(pos.rel(UP))) ? 0 : 1;
        for (Dir d : HORIZONTAL)
            if (!connected(L.table.prop(st, DIR_NAME[d]))) st = L.table.with(st, DIR_NAME[d], connecting_side(L, pos, d, nca));
        return st;
    }
    int connection_state(Level& L, int st, Pos pos) {
        bool dot = is_dot(L, st);
        st = missing_connections(L, L.table.with(L.def(self), "power", L.table.prop(st, "power")), pos);
        if (dot && is_dot(L, st)) return st;
        bool n = connected(L.table.prop(st, "north")), s = connected(L.table.prop(st, "south"));
        bool e = connected(L.table.prop(st, "east")), w = connected(L.table.prop(st, "west"));
        bool no_ns = !n && !s, no_ew = !e && !w;
        if (!w && no_ns) st = L.table.with(st, "west", "side");
        if (!e && no_ns) st = L.table.with(st, "east", "side");
        if (!n && no_ew) st = L.table.with(st, "north", "side");
        if (!s && no_ew) st = L.table.with(st, "south", "side");
        return st;
    }
    bool has_placement_state() override { return true; }
    int placement_state(Level& L, Pos pos, int state) override {
        return L.table.with(connection_state(L, cross_state(L, 0), pos), "power", L.table.prop(state, "power"));
    }
    int update_shape(Level& L, int st, Dir d, int ns, Pos pos, Pos np) override {
        if (d == DOWN) return can_survive_on(L, ns) ? st : 0;
        if (d == UP) return connection_state(L, st, pos);
        std::string side = connecting_side(L, pos, d);
        if (connected(side) == connected(L.table.prop(st, DIR_NAME[d])) && !is_cross(L, st))
            return L.table.with(st, DIR_NAME[d], side);
        return connection_state(L, L.table.with(cross_state(L, L.table.prop_int(st, "power")), DIR_NAME[d], side), pos);
    }
    void update_indirect_neighbour_shapes(Level& L, int st, Pos pos, int flags, int recursion) override {
        for (Dir d : HORIZONTAL) {
            if (L.table.prop(st, DIR_NAME[d]) == "none") continue;
            if (L.is_block(L.get(pos.rel(d)), self)) continue;
            for (Dir v : {DOWN, UP}) {
                Pos np = pos.rel(d).rel(v);
                if (L.is_block(L.get(np), self)) {
                    Pos other = np.rel(OPPD[d]);
                    L.neighbor_shape_changed(OPPD[d], L.get(other), np, other, flags, recursion);
                }
            }
        }
    }
    bool use(Level& L, int st, Pos pos) override {
        if (!(is_cross(L, st) || is_dot(L, st))) return false;
        int power = L.table.prop_int(st, "power");
        int nw = is_cross(L, st) ? L.table.with(L.def(self), "power", power) : cross_state(L, power);
        nw = connection_state(L, nw, pos);
        if (nw == st) return false;
        L.set_block(pos, nw, UPDATE_ALL);
        for (Dir d : HORIZONTAL) {
            Pos np = pos.rel(d);
            if (connected(L.table.prop(st, DIR_NAME[d])) != connected(L.table.prop(nw, DIR_NAME[d])) && L.is_conductor(L.get(np)))
                L.update_neighbors_at_except(np, self, OPPD[d]);
        }
        return true;
    }
    int wire_signal(Level& L, int st) { return L.is_block(st, self) ? L.table.prop_int(st, "power") : 0; }
    int calculate_target_strength(Level& L, Pos pos) {
        L.should_signal = false;
        int i = L.get_best_neighbor_signal(pos);
        L.should_signal = true;
        int j = 0;
        if (i < 15) {
            bool above_conducts = L.is_conductor(L.get(pos.rel(UP)));
            for (Dir d : HORIZONTAL) {
                Pos np = pos.rel(d);
                int ns = L.get(np);
                j = std::max(j, wire_signal(L, ns));
                if (L.is_conductor(ns)) {
                    if (!above_conducts) j = std::max(j, wire_signal(L, L.get(np.rel(UP))));
                } else {
                    j = std::max(j, wire_signal(L, L.get(np.rel(DOWN))));
                }
            }
        }
        return std::max(i, j - 1);
    }
    void update_power_strength(Level& L, Pos pos, int st) {
        int i = calculate_target_strength(L, pos);
        if (L.table.prop_int(st, "power") != i) {
            if (L.get(pos) == st) L.set_block(pos, L.table.with(st, "power", i), UPDATE_CLIENTS);
            std::vector<Pos> ps{pos};
            for (Dir d : DIRECTIONS) ps.push_back(pos.rel(d));
            for (const Pos& p : java_hash_order(ps)) L.update_neighbors_at(p, self);
        }
    }
    void check_corner_change_at(Level& L, Pos pos) {
        if (L.is_block(L.get(pos), self)) {
            L.update_neighbors_at(pos, self);
            for (Dir d : DIRECTIONS) L.update_neighbors_at(pos.rel(d), self);
        }
    }
    void update_neighbors_of_neighboring_wires(Level& L, Pos pos) {
        for (Dir d : HORIZONTAL) check_corner_change_at(L, pos.rel(d));
        for (Dir d : HORIZONTAL) {
            Pos np = pos.rel(d);
            if (L.is_conductor(L.get(np))) check_corner_change_at(L, np.rel(UP));
            else check_corner_change_at(L, np.rel(DOWN));
        }
    }
    void on_place(Level& L, int st, Pos pos, int old, bool) override {
        if (!L.is_block(old, self)) {
            update_power_strength(L, pos, st);
            for (Dir d : VERTICAL) L.update_neighbors_at(pos.rel(d), self);
            update_neighbors_of_neighboring_wires(L, pos);
        }
    }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self)) {
            for (Dir d : DIRECTIONS) L.update_neighbors_at(pos.rel(d), self);
            update_power_strength(L, pos, st);
            update_neighbors_of_neighboring_wires(L, pos);
        }
    }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        if (survives(L, pos)) update_power_strength(L, pos, st);
        else { L.drop_resources(st, pos); L.remove_block(pos); }
    }
    int get_signal(Level& L, int st, Pos pos, Dir d) override {
        if (!L.should_signal || d == DOWN) return 0;
        int power = L.table.prop_int(st, "power");
        if (power == 0) return 0;
        if (d != UP && !connected(L.table.prop(connection_state(L, st, pos), DIR_NAME[OPPD[d]]))) return 0;
        return power;
    }
    int get_direct_signal(Level& L, int st, Pos pos, Dir d) override { return L.should_signal ? get_signal(L, st, pos, d) : 0; }
    bool is_signal_source(int) override { return true; }   // shouldSignal is checked in get_signal
};

// ---------------------------------------------------------------- torches
struct RedstoneTorch : Behavior {
    int self;
    bool wall;
    RedstoneTorch(int s, bool w) : self(s), wall(w) {}
    Dir attached(Level& L, int st) { return wall ? OPPD[facing(L, st)] : DOWN; }
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (d == attached(L, st) && !support_ok(L, pos, attached(L, st))) return 0;
        return st;
    }
    bool has_neighbor_signal(Level& L, Pos pos, int st) { Dir d = attached(L, st); return L.has_signal(pos.rel(d), d); }
    void on_place(Level& L, int, Pos pos, int, bool) override { for (Dir d : DIRECTIONS) L.update_neighbors_at(pos.rel(d), self); }
    void on_remove(Level& L, int, Pos pos, int, bool moved) override {
        if (!moved) for (Dir d : DIRECTIONS) L.update_neighbors_at(pos.rel(d), self);
    }
    int get_signal(Level& L, int st, Pos, Dir d) override {
        if (!prop_true(L, st, "lit")) return 0;
        if (wall) return facing(L, st) == d ? 0 : 15;
        return d == UP ? 0 : 15;
    }
    int get_direct_signal(Level& L, int st, Pos pos, Dir d) override { return d == DOWN ? get_signal(L, st, pos, d) : 0; }
    bool is_signal_source(int) override { return true; }
    bool toggled_too_often(Level& L, Pos pos, bool log) {
        auto& t = L.torch_toggles[pos];
        if (log) t.push_back(L.game_time);
        return t.size() >= 8;
    }
    void tick(Level& L, int st, Pos pos) override {
        bool powered = has_neighbor_signal(L, pos, st);
        auto it = L.torch_toggles.find(pos);
        if (it != L.torch_toggles.end())
            while (!it->second.empty() && L.game_time - it->second.front() > 60) it->second.pop_front();
        if (prop_true(L, st, "lit")) {
            if (powered) {
                L.set_block(pos, L.table.with(st, "lit", false), UPDATE_ALL);
                if (toggled_too_often(L, pos, true)) {
                    L.effect(FX_BURNOUT, pos);
                    L.schedule_tick(pos, self, 160);
                }
            }
        } else if (!powered && !toggled_too_often(L, pos, false)) {
            L.set_block(pos, L.table.with(st, "lit", true), UPDATE_ALL);
        }
    }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        if (prop_true(L, st, "lit") == has_neighbor_signal(L, pos, st) && !L.will_tick_this_tick(pos, self))
            L.schedule_tick(pos, self, 2);
    }
};

// ------------------------------------------------------------------ diodes
struct Diode : Behavior {
    int self;
    bool side_diodes_only = true;
    explicit Diode(int s) : self(s) {}
    bool survives(Level& L, Pos pos) { return L.face_sturdy(L.get(pos.rel(DOWN)), UP); }
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (d == DOWN && !survives(L, pos)) return 0;
        return st;
    }
    virtual int delay(Level&, int) { return 2; }
    virtual int output_signal(Level&, Pos, int) { return 15; }
    virtual int input_signal(Level& L, Pos pos, int st) {
        Dir d = facing(L, st);
        Pos np = pos.rel(d);
        int i = L.get_signal(np, d);
        if (i >= 15) return i;
        int ns = L.get(np);
        return std::max(i, L.is_block(ns, L.B_WIRE) ? L.table.prop_int(ns, "power") : 0);
    }
    int alternate_signal(Level& L, Pos pos, int st) {
        Dir f = facing(L, st);
        Dir d1 = cw(f), d2 = ccw(f);
        return std::max(L.get_control_input_signal(pos.rel(d1), d1, side_diodes_only),
                        L.get_control_input_signal(pos.rel(d2), d2, side_diodes_only));
    }
    virtual bool is_locked(Level&, Pos, int) { return false; }
    virtual bool should_turn_on(Level& L, Pos pos, int st) { return input_signal(L, pos, st) > 0; }
    bool should_prioritize(Level& L, Pos pos, int st) {
        Dir d = OPPD[facing(L, st)];
        int front = L.get(pos.rel(d));
        int b = L.bidx(front);
        return (b == L.B_REPEATER || b == L.B_COMPARATOR) && facing(L, front) != d;
    }
    virtual void check_tick_on_neighbor(Level& L, Pos pos, int st) {
        if (is_locked(L, pos, st)) return;
        bool powered = prop_true(L, st, "powered");
        bool on = should_turn_on(L, pos, st);
        if (powered != on && !L.will_tick_this_tick(pos, self)) {
            int pr = HIGH;
            if (should_prioritize(L, pos, st)) pr = EXTREMELY_HIGH;
            else if (powered) pr = VERY_HIGH;
            L.schedule_tick(pos, self, delay(L, st), pr);
        }
    }
    void tick(Level& L, int st, Pos pos) override {
        if (is_locked(L, pos, st)) return;
        bool powered = prop_true(L, st, "powered");
        bool on = should_turn_on(L, pos, st);
        if (powered && !on) {
            L.set_block(pos, L.table.with(st, "powered", false), UPDATE_CLIENTS);
        } else if (!powered) {
            L.set_block(pos, L.table.with(st, "powered", true), UPDATE_CLIENTS);
            if (!on) L.schedule_tick(pos, self, delay(L, st), VERY_HIGH);
        }
    }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        if (survives(L, pos)) {
            check_tick_on_neighbor(L, pos, st);
        } else {
            L.drop_resources(st, pos);
            L.remove_block(pos);
            for (Dir d : DIRECTIONS) L.update_neighbors_at(pos.rel(d), self);
        }
    }
    int get_signal(Level& L, int st, Pos pos, Dir d) override {
        if (!prop_true(L, st, "powered")) return 0;
        return facing(L, st) == d ? output_signal(L, pos, st) : 0;
    }
    int get_direct_signal(Level& L, int st, Pos pos, Dir d) override { return get_signal(L, st, pos, d); }
    bool is_signal_source(int) override { return true; }
    void update_neighbors_in_front(Level& L, Pos pos, int st) {
        Dir f = facing(L, st);
        Pos front = pos.rel(OPPD[f]);
        L.neighbor_changed(front, self, pos);
        L.update_neighbors_at_except(front, self, f);
    }
    void on_place(Level& L, int st, Pos pos, int, bool) override { update_neighbors_in_front(L, pos, st); }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self)) update_neighbors_in_front(L, pos, st);
    }
    void on_placed_by_player(Level& L, int st, Pos pos) override {
        if (should_turn_on(L, pos, st)) L.schedule_tick(pos, self, 1);
    }
};

struct Repeater : Diode {
    explicit Repeater(int s) : Diode(s) {}
    int delay(Level& L, int st) override { return L.table.prop_int(st, "delay", 1) * 2; }
    bool is_locked(Level& L, Pos pos, int st) override { return alternate_signal(L, pos, st) > 0; }
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (d == DOWN && !survives(L, pos)) return 0;
        if (axis(d) != axis(facing(L, st))) return L.table.with(st, "locked", is_locked(L, pos, st));
        return st;
    }
    bool use(Level& L, int st, Pos pos) override {
        L.set_block(pos, L.table.with(st, "delay", L.table.prop_int(st, "delay", 1) % 4 + 1), UPDATE_ALL);
        return true;
    }
};

struct Comparator : Diode {
    explicit Comparator(int s) : Diode(s) { side_diodes_only = false; }
    int output_signal(Level& L, Pos pos, int) override {
        auto it = L.comparator_output.find(pos);
        return it == L.comparator_output.end() ? 0 : it->second;
    }
    int input_signal(Level& L, Pos pos, int st) override {
        int i = Diode::input_signal(L, pos, st);
        Dir d = facing(L, st);
        Pos np = pos.rel(d);
        int ns = L.get(np);
        if (L.beh(ns).has_analog_output(ns)) {
            i = L.beh(ns).analog_output(L, ns, np);
        } else if (i < 15 && L.is_conductor(ns)) {
            np = np.rel(d);
            ns = L.get(np);
            if (L.beh(ns).has_analog_output(ns)) i = L.beh(ns).analog_output(L, ns, np);
        }
        return i;
    }
    int calculate_output(Level& L, Pos pos, int st) {
        int i = input_signal(L, pos, st);
        if (i == 0) return 0;
        int j = alternate_signal(L, pos, st);
        if (j > i) return 0;
        return L.table.is(st, "mode", "subtract") ? i - j : i;
    }
    bool should_turn_on(Level& L, Pos pos, int st) override {
        int i = input_signal(L, pos, st);
        if (i == 0) return false;
        int j = alternate_signal(L, pos, st);
        return i > j || (i == j && L.table.is(st, "mode", "compare"));
    }
    void check_tick_on_neighbor(Level& L, Pos pos, int st) override {
        if (L.will_tick_this_tick(pos, self)) return;
        int i = calculate_output(L, pos, st);
        int j = output_signal(L, pos, st);
        if (i != j || prop_true(L, st, "powered") != should_turn_on(L, pos, st))
            L.schedule_tick(pos, self, 2, should_prioritize(L, pos, st) ? HIGH : NORMAL);
    }
    void refresh(Level& L, Pos pos, int st) {
        int i = calculate_output(L, pos, st);
        int j = output_signal(L, pos, st);
        L.comparator_output[pos] = i;
        if (j != i || L.table.is(st, "mode", "compare")) {
            bool on = should_turn_on(L, pos, st);
            bool powered = prop_true(L, st, "powered");
            if (powered && !on) L.set_block(pos, L.table.with(st, "powered", false), UPDATE_CLIENTS);
            else if (!powered && on) L.set_block(pos, L.table.with(st, "powered", true), UPDATE_CLIENTS);
            update_neighbors_in_front(L, pos, L.get(pos));
        }
    }
    void tick(Level& L, int st, Pos pos) override { refresh(L, pos, st); }
    bool use(Level& L, int st, Pos pos) override {
        st = L.table.with(st, "mode", L.table.is(st, "mode", "subtract") ? "compare" : "subtract");
        L.set_block(pos, st, UPDATE_CLIENTS);
        refresh(L, pos, st);
        return true;
    }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        Diode::on_remove(L, st, pos, nw, moved);
        if (!L.is_block(nw, self)) L.comparator_output.erase(pos);
    }
};

// --------------------------------------------------------------- observer
struct Observer : Behavior {
    int self;
    explicit Observer(int s) : self(s) {}
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (facing(L, st) == d && !prop_true(L, st, "powered") && !L.has_scheduled_tick(pos, self))
            L.schedule_tick(pos, self, 2);
        return st;
    }
    void tick(Level& L, int st, Pos pos) override {
        if (prop_true(L, st, "powered")) {
            st = L.table.with(st, "powered", false);
            L.set_block(pos, st, UPDATE_CLIENTS);
        } else {
            st = L.table.with(st, "powered", true);
            L.set_block(pos, st, UPDATE_CLIENTS);
            L.schedule_tick(pos, self, 2);
        }
        front(L, pos, st);
    }
    void front(Level& L, Pos pos, int st) {
        Dir f = facing(L, st);
        Pos behind = pos.rel(OPPD[f]);
        L.neighbor_changed(behind, self, pos);
        L.update_neighbors_at_except(behind, self, f);
    }
    int get_signal(Level& L, int st, Pos, Dir d) override { return prop_true(L, st, "powered") && facing(L, st) == d ? 15 : 0; }
    int get_direct_signal(Level& L, int st, Pos pos, Dir d) override { return get_signal(L, st, pos, d); }
    bool is_signal_source(int) override { return true; }
    void on_place(Level& L, int st, Pos pos, int old, bool) override {
        if (!L.is_block(old, self) && prop_true(L, st, "powered") && !L.has_scheduled_tick(pos, self)) {
            int nw = L.table.with(st, "powered", false);
            L.set_block(pos, nw, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE);
            front(L, pos, nw);
        }
    }
    void on_remove(Level& L, int st, Pos pos, int nw, bool) override {
        if (!L.is_block(nw, self) && prop_true(L, st, "powered") && L.has_scheduled_tick(pos, self))
            front(L, pos, L.table.with(st, "powered", false));
    }
};

// ---------------------------------------- levers, buttons, plates, sources
inline Dir connected_direction(Level& L, int st) {
    const std::string& face = L.table.prop(st, "face");
    if (face == "ceiling") return DOWN;
    if (face == "floor") return UP;
    return facing(L, st);
}

struct FaceAttached : Behavior {
    int self;
    explicit FaceAttached(int s) : self(s) {}
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        Dir back = OPPD[connected_direction(L, st)];
        if (back == d && !support_ok(L, pos, back)) return 0;
        return st;
    }
    void update_neighbours(Level& L, int st, Pos pos) {
        L.update_neighbors_at(pos, self);
        L.update_neighbors_at(pos.rel(OPPD[connected_direction(L, st)]), self);
    }
    int get_signal(Level& L, int st, Pos, Dir) override { return prop_true(L, st, "powered") ? 15 : 0; }
    int get_direct_signal(Level& L, int st, Pos, Dir d) override {
        return prop_true(L, st, "powered") && connected_direction(L, st) == d ? 15 : 0;
    }
    bool is_signal_source(int) override { return true; }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self) && prop_true(L, st, "powered")) update_neighbours(L, st, pos);
    }
};

struct Lever : FaceAttached {
    explicit Lever(int s) : FaceAttached(s) {}
    bool use(Level& L, int st, Pos pos) override {
        st = L.table.with(st, "powered", !prop_true(L, st, "powered"));
        L.set_block(pos, st, UPDATE_ALL);
        update_neighbours(L, st, pos);
        L.effect(FX_SOUND, pos, SND_LEVER, prop_true(L, st, "powered") ? 60 : 50);
        return true;
    }
};

struct Button : FaceAttached {
    int ticks;
    bool stone;
    Button(int s, int t, bool st) : FaceAttached(s), ticks(t), stone(st) {}
    bool use(Level& L, int st, Pos pos) override {
        if (prop_true(L, st, "powered")) return true;
        st = L.table.with(st, "powered", true);
        L.set_block(pos, st, UPDATE_ALL);
        update_neighbours(L, st, pos);
        L.schedule_tick(pos, self, ticks);
        L.effect(FX_SOUND, pos, stone ? SND_STONE_BUTTON : SND_WOOD_BUTTON, 100);
        return true;
    }
    void tick(Level& L, int st, Pos pos) override {
        if (prop_true(L, st, "powered")) {
            st = L.table.with(st, "powered", false);
            L.set_block(pos, st, UPDATE_ALL);
            update_neighbours(L, st, pos);
        }
    }
};

struct PressurePlate : Behavior {
    int self, kind;  // 0 wood (any), 1 stone (living), 2 light, 3 heavy
    PressurePlate(int s, int k) : self(s), kind(k) {}
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (d == DOWN) {
            int below = L.get(pos.rel(DOWN));
            if (!(L.face_sturdy(below, UP) || ends_with(L.short_name(below), "_fence"))) return 0;
        }
        return st;
    }
    int signal_of(Level& L, int st) {
        if (L.table.has_prop(st, "power")) return L.table.prop_int(st, "power");
        return prop_true(L, st, "powered") ? 15 : 0;
    }
    int with_signal(Level& L, int st, int sig) {
        if (L.table.has_prop(st, "power")) return L.table.with(st, "power", sig);
        return L.table.with(st, "powered", sig > 0);
    }
    int strength(Level& L, Pos pos) {
        if (!L.entity_count) return 0;
        int count = L.entity_count(pos.x, pos.y, pos.z, kind == 1 ? 1 : (kind >= 2 ? 2 : 0));
        if (kind == 2) return std::min(count, 15);
        if (kind == 3) return count ? std::min((count + 9) / 10, 15) : 0;
        return count ? 15 : 0;
    }
    void check_pressed(Level& L, Pos pos, int st, int current) {
        int sig = strength(L, pos);
        if (sig != current) {
            st = with_signal(L, st, sig);
            L.set_block(pos, st, UPDATE_CLIENTS);
            L.update_neighbors_at(pos, self);
            L.update_neighbors_at(pos.rel(DOWN), self);
        }
        if (sig > 0) L.schedule_tick(pos, self, kind >= 2 ? 10 : 20);
    }
    void entity_inside(Level& L, int st, Pos pos) override { if (signal_of(L, st) == 0) check_pressed(L, pos, st, 0); }
    void tick(Level& L, int st, Pos pos) override { int c = signal_of(L, st); if (c > 0) check_pressed(L, pos, st, c); }
    int get_signal(Level& L, int st, Pos, Dir) override { return signal_of(L, st); }
    int get_direct_signal(Level& L, int st, Pos, Dir d) override { return d == UP ? signal_of(L, st) : 0; }
    bool is_signal_source(int) override { return true; }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self) && signal_of(L, st) > 0) {
            L.update_neighbors_at(pos, self);
            L.update_neighbors_at(pos.rel(DOWN), self);
        }
    }
};

struct RedstoneBlock : Behavior {
    int get_signal(Level&, int, Pos, Dir) override { return 15; }
    bool is_signal_source(int) override { return true; }
};

struct Target : Behavior {
    int get_signal(Level& L, int st, Pos, Dir) override { return L.table.prop_int(st, "power"); }
    bool is_signal_source(int) override { return true; }
    void tick(Level& L, int st, Pos pos) override {
        if (L.table.prop_int(st, "power") != 0) L.set_block(pos, L.table.with(st, "power", 0), UPDATE_ALL);
    }
};

// ---------------------------------------------------------------- consumers
struct RedstoneLamp : Behavior {
    int self;
    explicit RedstoneLamp(int s) : self(s) {}
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        bool lit = prop_true(L, st, "lit");
        if (lit != L.has_neighbor_signal(pos)) {
            if (lit) L.schedule_tick(pos, self, 4);
            else L.set_block(pos, L.table.with(st, "lit", true), UPDATE_CLIENTS);
        }
    }
    void tick(Level& L, int st, Pos pos) override {
        if (prop_true(L, st, "lit") && !L.has_neighbor_signal(pos)) L.set_block(pos, L.table.with(st, "lit", false), UPDATE_CLIENTS);
    }
};

struct Tnt : Behavior {
    int self;
    explicit Tnt(int s) : self(s) {}
    void prime(Level& L, Pos pos) { L.effect(FX_PRIME_TNT, pos); L.remove_block(pos); }
    void on_place(Level& L, int, Pos pos, int old, bool) override {
        if (!L.is_block(old, self) && L.has_neighbor_signal(pos)) prime(L, pos);
    }
    void neighbor_changed(Level& L, int, Pos pos, int, Pos, bool) override {
        if (L.has_neighbor_signal(pos)) prime(L, pos);
    }
};

struct NoteBlock : Behavior {
    int self;
    explicit NoteBlock(int s) : self(s) {}
    std::string instrument(Level& L, Pos pos) {
        static const std::vector<std::pair<std::vector<const char*>, const char*>> table = {
            {{"stone", "cobblestone", "deepslate", "andesite", "diorite", "granite", "netherrack", "basalt", "obsidian",
              "bricks", "terracotta", "concrete", "blackstone", "end_stone", "_ore", "quartz", "prismarine", "purpur",
              "tuff", "calcite", "sandstone"}, "basedrum"},
            {{"sand", "gravel", "concrete_powder", "suspicious"}, "snare"},
            {{"glass", "sea_lantern", "beacon"}, "hat"},
            {{"_planks", "_log", "_wood", "_stem", "_hyphae", "bookshelf", "chest", "crafting_table", "note_block",
              "jukebox", "barrel", "_fence", "_sign", "banner"}, "bass"},
            {{"clay"}, "flute"}, {{"gold_block"}, "bell"}, {{"_wool"}, "guitar"}, {{"packed_ice"}, "chime"},
            {{"bone_block"}, "xylophone"}, {{"iron_block"}, "iron_xylophone"}, {{"soul_sand"}, "cow_bell"},
            {{"pumpkin"}, "didgeridoo"}, {{"emerald_block"}, "bit"}, {{"hay_block"}, "banjo"}, {{"glowstone"}, "pling"}};
        const std::string& below = L.short_name(L.get(pos.rel(DOWN)));
        for (auto& row : table)
            for (const char* suf : row.first)
                if (below.find(suf) != std::string::npos) return row.second;
        return "harp";
    }
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (d == DOWN) return L.table.with(st, "instrument", instrument(L, pos));
        return st;
    }
    void play(Level& L, Pos pos) { if (L.get(pos.rel(UP)) == 0) L.block_event(pos, self, 0, 0); }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        bool powered = L.has_neighbor_signal(pos);
        if (powered != prop_true(L, st, "powered")) {
            if (powered) play(L, pos);
            L.set_block(pos, L.table.with(st, "powered", powered), UPDATE_ALL);
        }
    }
    bool use(Level& L, int st, Pos pos) override {
        st = L.table.with(st, "note", (L.table.prop_int(st, "note") + 1) % 25);
        L.set_block(pos, st, UPDATE_ALL);
        play(L, pos);
        return true;
    }
    bool trigger_event(Level& L, int st, Pos pos, int, int) override {
        L.effect(FX_NOTE, pos, L.table.prop_int(st, "note"));
        return true;
    }
};

struct Door : Behavior {
    int self;
    explicit Door(int s) : self(s) {}
    int update_shape(Level& L, int st, Dir d, int ns, Pos, Pos) override {
        const std::string& half = L.table.prop(st, "half");
        if (axis(d) == 1 && (half == "lower") == (d == UP)) {
            if (L.is_block(ns, self) && L.table.prop(ns, "half") != half) return L.table.with(ns, "half", half);
            return 0;
        }
        if (half == "lower" && d == DOWN && !L.face_sturdy(ns, UP)) return 0;
        return st;
    }
    void neighbor_changed(Level& L, int st, Pos pos, int source, Pos, bool) override {
        Pos other = pos.rel(L.table.is(st, "half", "lower") ? UP : DOWN);
        bool powered = L.has_neighbor_signal(pos) || L.has_neighbor_signal(other);
        if (source != self && powered != prop_true(L, st, "powered"))
            L.set_block(pos, L.table.with(L.table.with(st, "powered", powered), "open", powered), UPDATE_CLIENTS);
    }
};

struct Trapdoor : Behavior {
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        bool powered = L.has_neighbor_signal(pos);
        if (powered != prop_true(L, st, "powered")) {
            int nw = L.table.with(st, "powered", powered);
            if (prop_true(L, st, "open") != powered) nw = L.table.with(nw, "open", powered);
            L.set_block(pos, nw, UPDATE_CLIENTS);
        }
    }
};

struct FenceGate : Behavior {
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        bool powered = L.has_neighbor_signal(pos);
        if (prop_true(L, st, "powered") != powered)
            L.set_block(pos, L.table.with(L.table.with(st, "powered", powered), "open", powered), UPDATE_CLIENTS);
    }
};

inline int container_signal(Level& L, Pos p) { return L.container_signal ? L.container_signal(p.x, p.y, p.z) : 0; }

struct Dispenser : Behavior {
    int self;
    bool dropper;
    Dispenser(int s, bool d) : self(s), dropper(d) {}
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override {
        bool powered = L.has_neighbor_signal(pos) || L.has_neighbor_signal(pos.rel(UP));
        bool triggered = prop_true(L, st, "triggered");
        if (powered && !triggered) {
            L.schedule_tick(pos, self, 4);
            L.set_block(pos, L.table.with(st, "triggered", true), UPDATE_INVISIBLE);
        } else if (!powered && triggered) {
            L.set_block(pos, L.table.with(st, "triggered", false), UPDATE_INVISIBLE);
        }
    }
    void tick(Level& L, int st, Pos pos) override { L.effect(FX_DISPENSE, pos, (int)facing(L, st), dropper ? 1 : 0); }
    bool has_analog_output(int) override { return true; }
    int analog_output(Level& L, int, Pos pos) override { return container_signal(L, pos); }
};

struct HopperBlock : Behavior {
    int self;
    explicit HopperBlock(int s) : self(s) {}
    void check(Level& L, int st, Pos pos) {
        bool enabled = !L.has_neighbor_signal(pos);
        if (enabled != prop_true(L, st, "enabled")) L.set_block(pos, L.table.with(st, "enabled", enabled), UPDATE_INVISIBLE);
    }
    void on_place(Level& L, int st, Pos pos, int old, bool) override { if (!L.is_block(old, self)) check(L, st, pos); }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override { check(L, st, pos); }
    bool has_analog_output(int) override { return true; }
    int analog_output(Level& L, int, Pos pos) override { return container_signal(L, pos); }
};

struct Container : Behavior {
    bool has_analog_output(int) override { return true; }
    int analog_output(Level& L, int, Pos pos) override { return container_signal(L, pos); }
};

struct LeveledAnalog : Behavior {
    const char* key;
    int mode;  // 0 raw, 1 cake, 2 anchor
    LeveledAnalog(const char* k, int m) : key(k), mode(m) {}
    bool has_analog_output(int) override { return true; }
    int analog_output(Level& L, int st, Pos) override {
        int v = L.table.prop_int(st, key);
        if (mode == 1) return (7 - v) * 2;
        if (mode == 2) return (int)(v / 4.0 * 15);
        return v;
    }
};

// ------------------------------------------------------------------ rails
struct BaseRail : Behavior {
    int self;
    bool straight;
    BaseRail(int s, bool st) : self(s), straight(st) {}
    static Dir ascending_support(const std::string& shape) {
        if (shape == "ascending_east") return EAST;
        if (shape == "ascending_west") return WEST;
        if (shape == "ascending_north") return NORTH;
        if (shape == "ascending_south") return SOUTH;
        return NODIR;
    }
    bool should_be_removed(Level& L, Pos pos, int st) {
        if (!L.face_sturdy(L.get(pos.rel(DOWN)), UP)) return true;
        Dir side = ascending_support(L.table.prop(st, "shape"));
        return side != NODIR && !L.face_sturdy(L.get(pos.rel(side)), UP);
    }
    void on_place(Level& L, int, Pos pos, int old, bool) override {
        if (!L.is_block(old, self) && straight) L.neighbor_changed(pos, self, pos);
    }
    void neighbor_changed(Level& L, int st, Pos pos, int source, Pos, bool moved) override {
        if (!L.is_block(L.get(pos), self)) return;
        if (should_be_removed(L, pos, st)) { L.drop_resources(st, pos); L.remove_block(pos, moved); }
        else rail_update(L, st, pos, source);
    }
    virtual void rail_update(Level&, int, Pos, int) {}
    void on_remove(Level& L, int st, Pos pos, int, bool moved) override {
        if (moved) return;
        if (L.table.prop(st, "shape").rfind("ascending", 0) == 0) L.update_neighbors_at(pos.rel(UP), self);
        if (straight) { L.update_neighbors_at(pos, self); L.update_neighbors_at(pos.rel(DOWN), self); }
    }
};

struct PoweredRail : BaseRail {
    explicit PoweredRail(int s) : BaseRail(s, true) {}
    bool find_signal(Level& L, Pos pos, int st, bool forward, int distance) {
        if (distance >= 8) return false;
        int x = pos.x, y = pos.y, z = pos.z;
        bool ascend = true;
        std::string shape = L.table.prop(st, "shape");
        if (shape == "north_south") z += forward ? -1 : 1;
        else if (shape == "east_west") x += forward ? -1 : 1;
        else if (shape == "ascending_east") { if (forward) x -= 1; else { x += 1; y += 1; ascend = false; } shape = "east_west"; }
        else if (shape == "ascending_west") { if (forward) { x -= 1; y += 1; ascend = false; } else x += 1; shape = "east_west"; }
        else if (shape == "ascending_north") { if (forward) z += 1; else { z -= 1; y += 1; ascend = false; } shape = "north_south"; }
        else if (shape == "ascending_south") { if (forward) { z += 1; y += 1; ascend = false; } else z -= 1; shape = "north_south"; }
        else return false;
        if (same_rail_with_power(L, {x, y, z}, forward, distance, shape)) return true;
        return ascend && same_rail_with_power(L, {x, y - 1, z}, forward, distance, shape);
    }
    bool same_rail_with_power(Level& L, Pos pos, bool forward, int distance, const std::string& shape) {
        int st = L.get(pos);
        if (!L.is_block(st, self)) return false;
        const std::string& other = L.table.prop(st, "shape");
        if (shape == "east_west" && (other == "north_south" || other == "ascending_north" || other == "ascending_south")) return false;
        if (shape == "north_south" && (other == "east_west" || other == "ascending_east" || other == "ascending_west")) return false;
        if (!prop_true(L, st, "powered")) return false;
        return L.has_neighbor_signal(pos) || find_signal(L, pos, st, forward, distance + 1);
    }
    void rail_update(Level& L, int st, Pos pos, int) override {
        bool powered = prop_true(L, st, "powered");
        bool should = L.has_neighbor_signal(pos) || find_signal(L, pos, st, true, 0) || find_signal(L, pos, st, false, 0);
        if (should != powered) {
            L.set_block(pos, L.table.with(st, "powered", should), UPDATE_ALL);
            L.update_neighbors_at(pos.rel(DOWN), self);
            if (L.table.prop(st, "shape").rfind("ascending", 0) == 0) L.update_neighbors_at(pos.rel(UP), self);
        }
    }
};

struct DetectorRail : BaseRail {
    explicit DetectorRail(int s) : BaseRail(s, true) {}
    int get_signal(Level& L, int st, Pos, Dir) override { return prop_true(L, st, "powered") ? 15 : 0; }
    int get_direct_signal(Level& L, int st, Pos, Dir d) override { return prop_true(L, st, "powered") && d == UP ? 15 : 0; }
    bool is_signal_source(int) override { return true; }
    bool has_analog_output(int) override { return true; }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (moved) return;
        BaseRail::on_remove(L, st, pos, nw, moved);
        if (prop_true(L, st, "powered")) { L.update_neighbors_at(pos, self); L.update_neighbors_at(pos.rel(DOWN), self); }
    }
};

struct CoralFan : Behavior {
    bool wall;
    explicit CoralFan(bool w) : wall(w) {}
    int update_shape(Level& L, int st, Dir d, int ns, Pos, Pos) override {
        Dir support = wall ? OPPD[facing(L, st)] : DOWN;
        if (d == support && !L.face_sturdy(ns, OPPD[support])) return 0;
        return st;
    }
};

struct NeedsSupportBelow : Behavior {
    int update_shape(Level& L, int st, Dir d, int ns, Pos, Pos) override {
        if (d == DOWN && !L.face_sturdy(ns, UP) && ns == 0) return 0;
        return st;
    }
};

struct WallAttached : Behavior {
    int update_shape(Level& L, int st, Dir d, int ns, Pos, Pos) override {
        Dir f = facing(L, st);
        if (d == OPPD[f] && !L.face_sturdy(ns, f)) return 0;
        return st;
    }
};

// -------------------------------------------------------------- tripwire
struct Tripwire;

struct TripwireHook : Behavior {
    int self;
    explicit TripwireHook(int s) : self(s) {}
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        Dir f = facing(L, st);
        if (OPPD[d] == f && !L.face_sturdy(L.get(pos.rel(OPPD[f])), f)) return 0;
        return st;
    }
    void on_placed_by_player(Level& L, int st, Pos pos) override { calculate_state(L, pos, st, false, false, -1, -1); }
    void notify(Level& L, Pos pos, Dir d) { L.update_neighbors_at(pos, self); L.update_neighbors_at(pos.rel(OPPD[d]), self); }
    static int try_set(Level& L, int st, const char* key, bool v) { return L.table.has_prop(st, key) ? L.table.with(st, key, v) : st; }
    void calculate_state(Level& L, Pos pos, int hook, bool attaching, bool notify_neighbors, int search, int wire_state) {
        Dir d = facing(L, hook);
        if (d == NODIR) return;
        bool was_attached = prop_true(L, hook, "attached");
        bool attached = !attaching, powered = false;
        int other = 0;
        int cached[42];
        for (int i = 0; i < 42; i++) cached[i] = -1;
        for (int j = 1; j < 42; j++) {
            Pos p = pos.rel(d, j);
            int st = L.get(p);
            if (L.is_block(st, self)) {
                if (facing(L, st) == OPPD[d]) other = j;
                break;
            }
            if (!L.is_block(st, L.B_TRIPWIRE) && j != search) {
                cached[j] = -1;
                attached = false;
            } else {
                if (j == search) st = wire_state >= 0 ? wire_state : st;
                bool armed = !prop_true(L, st, "disarmed");
                bool pressed = prop_true(L, st, "powered");
                powered = powered || (armed && pressed);
                cached[j] = st;
                if (j == search) { L.schedule_tick(pos, self, 10); attached = attached && armed; }
            }
        }
        attached = attached && other > 1;
        powered = powered && attached;
        int nh = try_set(L, try_set(L, L.def(self), "attached", attached), "powered", powered);
        if (other > 0) {
            Pos op = pos.rel(d, other);
            L.set_block(op, L.table.with(nh, "facing", DIR_NAME[OPPD[d]]), UPDATE_ALL);
            notify(L, op, OPPD[d]);
        }
        if (!attaching) {
            L.set_block(pos, L.table.with(nh, "facing", DIR_NAME[d]), UPDATE_ALL);
            if (notify_neighbors) notify(L, pos, d);
        }
        if (was_attached != attached)
            for (int k = 1; k < other; k++)
                if (cached[k] >= 0) L.set_block(pos.rel(d, k), try_set(L, cached[k], "attached", attached), UPDATE_ALL);
    }
    void tick(Level& L, int st, Pos pos) override { calculate_state(L, pos, st, false, true, -1, -1); }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self)) {
            bool attached = prop_true(L, st, "attached"), powered = prop_true(L, st, "powered");
            if (attached || powered) calculate_state(L, pos, st, true, false, -1, -1);
            if (powered) { L.update_neighbors_at(pos, self); L.update_neighbors_at(pos.rel(OPPD[facing(L, st)]), self); }
        }
    }
    int get_signal(Level& L, int st, Pos, Dir) override { return prop_true(L, st, "powered") ? 15 : 0; }
    int get_direct_signal(Level& L, int st, Pos, Dir d) override { return prop_true(L, st, "powered") && facing(L, st) == d ? 15 : 0; }
    bool is_signal_source(int) override { return true; }
};

struct Tripwire : Behavior {
    int self;
    TripwireHook* hook;
    Tripwire(int s, TripwireHook* h) : self(s), hook(h) {}
    bool connects(Level& L, int st, Dir d) {
        if (L.is_block(st, L.B_HOOK)) return facing(L, st) == OPPD[d];
        return L.is_block(st, self);
    }
    bool has_placement_state() override { return true; }
    int placement_state(Level& L, Pos pos, int) override {
        int st = L.def(self);
        for (Dir d : HORIZONTAL) st = L.table.with(st, DIR_NAME[d], connects(L, L.get(pos.rel(d)), d));
        return st;
    }
    int update_shape(Level& L, int st, Dir d, int ns, Pos, Pos) override {
        if (d >= NORTH) return L.table.with(st, DIR_NAME[d], connects(L, ns, d));
        return st;
    }
    void on_place(Level& L, int st, Pos pos, int old, bool) override { if (!L.is_block(old, self)) update_source(L, pos, st); }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self)) update_source(L, pos, L.table.with(st, "powered", true));
    }
    void update_source(Level& L, Pos pos, int st) {
        for (Dir d : {SOUTH, WEST}) {
            for (int i = 1; i < 42; i++) {
                Pos p = pos.rel(d, i);
                int other = L.get(p);
                if (L.is_block(other, L.B_HOOK)) {
                    if (facing(L, other) == OPPD[d]) hook->calculate_state(L, p, other, false, true, i, st);
                    break;
                }
                if (!L.is_block(other, self)) break;
            }
        }
    }
    void check_pressed(Level& L, Pos pos) {
        int st = L.get(pos);
        bool powered = prop_true(L, st, "powered");
        bool pressed = L.entity_count && L.entity_count(pos.x, pos.y, pos.z, 3) > 0;
        if (pressed != powered) {
            st = L.table.with(st, "powered", pressed);
            L.set_block(pos, st, UPDATE_ALL);
            update_source(L, pos, st);
        }
        if (pressed) L.schedule_tick(pos, self, 10);
    }
    void entity_inside(Level& L, int st, Pos pos) override { if (!prop_true(L, st, "powered")) check_pressed(L, pos); }
    void tick(Level& L, int st, Pos pos) override { if (prop_true(L, st, "powered")) check_pressed(L, pos); }
};

// ----------------------------------------------------------------- pistons
static const std::set<std::string> BLOCK_ENTITIES = {
    "chest", "trapped_chest", "ender_chest", "furnace", "blast_furnace", "smoker", "hopper", "dispenser", "dropper",
    "barrel", "brewing_stand", "enchanting_table", "beacon", "spawner", "jukebox", "lectern", "bell", "campfire",
    "soul_campfire", "beehive", "bee_nest", "conduit", "daylight_detector", "comparator", "sculk_sensor",
    "calibrated_sculk_sensor", "sculk_catalyst", "sculk_shrieker", "chiseled_bookshelf", "decorated_pot", "crafter",
    "trial_spawner", "vault", "command_block", "chain_command_block", "repeating_command_block", "structure_block",
    "jigsaw", "end_gateway", "end_portal", "moving_piston", "suspicious_sand", "suspicious_gravel", "creaking_heart"};
static const std::set<std::string> BLOCK_REACTION = {"obsidian", "crying_obsidian", "respawn_anchor", "reinforced_deepslate",
    "piston_head", "moving_piston", "barrier", "end_portal_frame", "light", "nether_portal"};
static const std::set<std::string> DESTROY_NAMES = {
    "cactus", "cobweb", "dragon_egg", "flower_pot", "scaffolding", "snow", "bamboo", "bamboo_sapling", "cocoa",
    "chorus_plant", "chorus_flower", "lantern", "soul_lantern", "pointed_dripstone", "big_dripleaf", "big_dripleaf_stem",
    "small_dripleaf", "sea_pickle", "turtle_egg", "sniffer_egg", "frogspawn", "moss_carpet", "pale_moss_carpet", "azalea",
    "flowering_azalea", "conduit", "lily_pad", "pitcher_plant", "pitcher_crop", "torchflower_crop", "sweet_berry_bush",
    "cave_vines", "cave_vines_plant", "glow_lichen", "sculk_vein", "hanging_roots", "spore_blossom", "repeater",
    "comparator", "redstone_wire", "redstone_torch", "redstone_wall_torch", "lever", "tripwire", "tripwire_hook",
    "melon_stem", "pumpkin_stem", "attached_melon_stem", "attached_pumpkin_stem", "nether_wart", "kelp", "kelp_plant",
    "seagrass", "tall_seagrass", "water", "lava", "fire", "soul_fire", "powder_snow"};
static const std::vector<const char*> DESTROY_SUFFIXES = {
    "_door", "_bed", "_carpet", "_button", "_pressure_plate", "_sapling", "_sign", "_wall_sign", "_hanging_sign",
    "_banner", "_wall_banner", "_head", "_skull", "_wall_head", "_wall_skull", "_candle", "candle", "_cluster", "_bud",
    "_coral", "torch", "_flower", "_tulip", "_mushroom", "_fungus", "_roots", "_vines", "_vines_plant", "_crop"};

inline int push_reaction(Level& L, int st) {  // 0 normal, 1 destroy, 2 block, 3 push_only
    const std::string& s = L.short_name(st);
    if (BLOCK_REACTION.count(s)) return 2;
    if (ends_with(s, "glazed_terracotta")) return 3;
    if (DESTROY_NAMES.count(s)) return 1;
    for (const char* suf : DESTROY_SUFFIXES) if (ends_with(s, suf)) return 1;
    if (ends_with(s, "rail")) return 0;
    if (ends_with(s, "_coral_fan") || ends_with(s, "_coral_wall_fan")) return 0;
    if (L.passable(st)) return 1;
    return 0;
}
inline bool has_block_entity(Level& L, int st) {
    const std::string& s = L.short_name(st);
    return BLOCK_ENTITIES.count(s) || ends_with(s, "shulker_box") || ends_with(s, "_sign") || ends_with(s, "_banner") ||
           ends_with(s, "_bed") || ends_with(s, "_head") || ends_with(s, "_skull");
}
inline bool is_sticky(Level& L, int st) { int b = L.bidx(st); return b == L.B_SLIME || b == L.B_HONEY; }
inline bool can_stick(Level& L, int a, int b) {
    int ba = L.bidx(a), bb = L.bidx(b);
    if ((ba == L.B_HONEY && bb == L.B_SLIME) || (ba == L.B_SLIME && bb == L.B_HONEY)) return false;
    return is_sticky(L, a) || is_sticky(L, b);
}
inline bool is_pushable(Level& L, int st, Pos pos, Dir d, bool allow_destroy, Dir piston_facing) {
    if (pos.y < -64 || pos.y > 319) return false;
    if (st == 0) return true;
    const std::string& s = L.short_name(st);
    if (s == "obsidian" || s == "crying_obsidian" || s == "respawn_anchor" || s == "reinforced_deepslate") return false;
    if ((d == DOWN && pos.y == -64) || (d == UP && pos.y == 319)) return false;
    int b = L.bidx(st);
    if (b != L.B_PISTON && b != L.B_STICKY_PISTON) {
        if (L.table.info(st).hardness == -1.0f) return false;
        int r = push_reaction(L, st);
        if (r == 2) return false;
        if (r == 1) return allow_destroy;
        if (r == 3) return d == piston_facing;
    } else if (prop_true(L, st, "extended")) {
        return false;
    }
    return !has_block_entity(L, st);
}

struct StructureResolver {
    Level& L;
    Pos piston_pos, start_pos;
    Dir piston_dir, push_dir;
    bool extending;
    std::vector<Pos> to_push, to_destroy;
    StructureResolver(Level& l, Pos pp, Dir pd, bool ext) : L(l), piston_pos(pp), piston_dir(pd), extending(ext) {
        push_dir = ext ? pd : OPPD[pd];
        start_pos = ext ? pp.rel(pd) : pp.rel(pd, 2);
    }
    bool contains(const Pos& p) { return std::find(to_push.begin(), to_push.end(), p) != to_push.end(); }
    bool resolve() {
        to_push.clear();
        to_destroy.clear();
        int st = L.get(start_pos);
        if (!is_pushable(L, st, start_pos, push_dir, false, piston_dir)) {
            if (extending && push_reaction(L, st) == 1) { to_destroy.push_back(start_pos); return true; }
            return false;
        }
        if (!add_block_line(start_pos, push_dir)) return false;
        for (size_t i = 0; i < to_push.size(); i++) {
            Pos p = to_push[i];
            if (is_sticky(L, L.get(p)) && !add_branching(p)) return false;
        }
        return true;
    }
    bool add_block_line(Pos origin, Dir d) {
        int st = L.get(origin);
        if (st == 0) return true;
        if (!is_pushable(L, st, origin, push_dir, false, d)) return true;
        if (origin == piston_pos || contains(origin)) return true;
        int i = 1;
        if (i + (int)to_push.size() > 12) return false;
        Dir back = OPPD[push_dir];
        while (is_sticky(L, st)) {
            Pos p = origin.rel(back, i);
            int prev = st;
            st = L.get(p);
            if (st == 0 || !can_stick(L, prev, st) || !is_pushable(L, st, p, push_dir, false, back) || p == piston_pos) break;
            i++;
            if (i + (int)to_push.size() > 12) return false;
        }
        int added = 0;
        for (int k = i - 1; k >= 0; k--) { to_push.push_back(origin.rel(back, k)); added++; }
        int j = 1;
        while (true) {
            Pos p = origin.rel(push_dir, j);
            auto it = std::find(to_push.begin(), to_push.end(), p);
            if (it != to_push.end()) {
                int index = (int)(it - to_push.begin());
                reorder(added, index);
                for (int k = 0; k <= index + added; k++) {
                    Pos q = to_push[k];
                    if (is_sticky(L, L.get(q)) && !add_branching(q)) return false;
                }
                return true;
            }
            st = L.get(p);
            if (st == 0) return true;
            if (!is_pushable(L, st, p, push_dir, true, push_dir) || p == piston_pos) return false;
            if (push_reaction(L, st) == 1) { to_destroy.push_back(p); return true; }
            if (to_push.size() >= 12) return false;
            to_push.push_back(p);
            added++;
            j++;
        }
    }
    void reorder(int offsets, int index) {
        std::vector<Pos> head(to_push.begin(), to_push.begin() + index);
        std::vector<Pos> tail(to_push.end() - offsets, to_push.end());
        std::vector<Pos> mid(to_push.begin() + index, to_push.end() - offsets);
        to_push.clear();
        to_push.insert(to_push.end(), head.begin(), head.end());
        to_push.insert(to_push.end(), tail.begin(), tail.end());
        to_push.insert(to_push.end(), mid.begin(), mid.end());
    }
    bool add_branching(Pos origin) {
        int st = L.get(origin);
        for (Dir d : DIRECTIONS) {
            if (axis(d) != axis(push_dir)) {
                Pos p = origin.rel(d);
                if (can_stick(L, L.get(p), st) && !add_block_line(p, d)) return false;
            }
        }
        return true;
    }
};

struct PistonBase : Behavior {
    int self;
    bool sticky;
    PistonBase(int s, bool st) : self(s), sticky(st) {}
    bool neighbor_signal(Level& L, Pos pos, Dir f) {
        for (Dir d : DIRECTIONS) if (d != f && L.has_signal(pos.rel(d), d)) return true;
        if (L.has_signal(pos, DOWN)) return true;
        Pos above = pos.rel(UP);
        for (Dir d : DIRECTIONS) if (d != DOWN && L.has_signal(above.rel(d), d)) return true;
        return false;
    }
    void check_if_extend(Level& L, Pos pos, int st) {
        Dir f = facing(L, st);
        bool powered = neighbor_signal(L, pos, f);
        bool extended = prop_true(L, st, "extended");
        if (powered && !extended) {
            StructureResolver r(L, pos, f, true);
            if (r.resolve()) L.block_event(pos, self, 0, (int)f);
        } else if (!powered && extended) {
            Pos front2 = pos.rel(f, 2);
            int ev = 1;
            if (L.is_block(L.get(front2), L.B_MOVING_PISTON)) {
                auto it = L.moving.find(front2);
                if (it != L.moving.end()) {
                    MovingPiston& m = it->second;
                    if (m.direction == f && m.extending && (m.progress < 0.5 || L.game_time == m.last_ticked || m.is_source)) ev = 2;
                }
            }
            L.block_event(pos, self, ev, (int)f);
        }
    }
    void neighbor_changed(Level& L, int st, Pos pos, int, Pos, bool) override { check_if_extend(L, pos, st); }
    void on_place(Level& L, int st, Pos pos, int old, bool) override {
        if (L.bidx(old) != L.bidx(st) && !L.moving.count(pos)) check_if_extend(L, pos, st);
    }
    void on_placed_by_player(Level& L, int st, Pos pos) override { check_if_extend(L, pos, st); }
    bool trigger_event(Level& L, int st, Pos pos, int id, int param) override {
        Dir d = facing(L, st);
        bool powered = neighbor_signal(L, pos, d);
        if (powered && (id == 1 || id == 2)) { L.set_block(pos, L.table.with(st, "extended", true), UPDATE_CLIENTS); return false; }
        if (!powered && id == 0) return false;
        if (id == 0) {
            if (!move_blocks(L, pos, d, true)) return false;
            L.set_block(pos, L.table.with(st, "extended", true), UPDATE_MOVE_BY_PISTON | UPDATE_ALL);
            L.effect(FX_SOUND, pos, SND_PISTON_OUT, 75);
            return true;
        }
        Pos front = pos.rel(d);
        if (L.moving.count(front)) L.final_tick(front);
        int mv = L.table.with(L.table.with(L.def(L.B_MOVING_PISTON), "facing", DIR_NAME[d]), "type", sticky ? "sticky" : "normal");
        L.set_block(pos, mv, UPDATE_INVISIBLE | UPDATE_KNOWN_SHAPE);
        MovingPiston m;
        m.pos = pos;
        m.moved_state = L.table.with(L.def(self), "facing", DIR_NAME[(param & 7) < 6 ? (param & 7) : 0]);
        m.direction = d;
        m.extending = false;
        m.is_source = true;
        L.add_moving(m);
        L.update_neighbors_at(pos, L.B_MOVING_PISTON);
        L.update_neighbour_shapes(mv, pos, UPDATE_CLIENTS);
        if (sticky) {
            Pos far = pos.rel(d, 2);
            int fs = L.get(far);
            bool pulled = false;
            if (L.is_block(fs, L.B_MOVING_PISTON)) {
                auto it = L.moving.find(far);
                if (it != L.moving.end() && it->second.direction == d && it->second.extending) { L.final_tick(far); pulled = true; }
            }
            if (!pulled) {
                int fb = L.bidx(fs);
                if (id != 1 || fs == 0 || !is_pushable(L, fs, far, OPPD[d], false, d) ||
                    (push_reaction(L, fs) != 0 && fb != L.B_PISTON && fb != L.B_STICKY_PISTON))
                    L.remove_block(front);
                else
                    move_blocks(L, pos, d, false);
            }
        } else {
            L.remove_block(front);
        }
        L.effect(FX_SOUND, pos, SND_PISTON_IN, 60);
        return true;
    }
    bool move_blocks(Level& L, Pos pos, Dir f, bool extending) {
        Pos head_pos = pos.rel(f);
        if (!extending && L.is_block(L.get(head_pos), L.B_PISTON_HEAD)) L.set_block(head_pos, 0, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE);
        StructureResolver r(L, pos, f, extending);
        if (!r.resolve()) return false;
        std::vector<Pos> to_push = r.to_push, to_destroy = r.to_destroy;
        std::vector<int> moved_states;
        for (const Pos& p : to_push) moved_states.push_back(L.get(p));
        std::unordered_map<Pos, int, PosHash> vacated;
        for (size_t k = 0; k < to_push.size(); k++) vacated[to_push[k]] = moved_states[k];
        Dir dir = extending ? f : OPPD[f];
        std::vector<int> removed;
        for (int k = (int)to_destroy.size() - 1; k >= 0; k--) {
            Pos p = to_destroy[k];
            int st = L.get(p);
            L.drop_resources(st, p);
            L.set_block(p, 0, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE);
            removed.push_back(st);
        }
        for (int k = (int)to_push.size() - 1; k >= 0; k--) {
            Pos src = to_push[k];
            int st = L.get(src);
            Pos target = src.rel(dir);
            vacated.erase(target);
            int mv = L.table.with(L.def(L.B_MOVING_PISTON), "facing", DIR_NAME[f]);
            L.set_block(target, mv, UPDATE_INVISIBLE | UPDATE_MOVE_BY_PISTON);
            MovingPiston m;
            m.pos = target; m.moved_state = moved_states[k]; m.direction = f; m.extending = extending; m.is_source = false;
            L.add_moving(m);
            removed.push_back(st);
        }
        if (extending) {
            const char* kind = sticky ? "sticky" : "normal";
            int head = L.table.with(L.table.with(L.def(L.B_PISTON_HEAD), "facing", DIR_NAME[f]), "type", kind);
            int mv = L.table.with(L.table.with(L.def(L.B_MOVING_PISTON), "facing", DIR_NAME[f]), "type", kind);
            vacated.erase(head_pos);
            L.set_block(head_pos, mv, UPDATE_INVISIBLE | UPDATE_MOVE_BY_PISTON);
            MovingPiston m;
            m.pos = head_pos; m.moved_state = head; m.direction = f; m.extending = true; m.is_source = true;
            L.add_moving(m);
        }
        std::vector<Pos> order;
        for (const Pos& p : java_hash_order(to_push)) if (vacated.count(p)) order.push_back(p);
        for (const Pos& p : order) L.set_block(p, 0, UPDATE_CLIENTS | UPDATE_KNOWN_SHAPE | UPDATE_MOVE_BY_PISTON);
        for (const Pos& p : order) {
            int old = vacated[p];
            L.beh(old).update_indirect_neighbour_shapes(L, old, p, UPDATE_CLIENTS, 511);
            L.update_neighbour_shapes(0, p, UPDATE_CLIENTS);
        }
        size_t i = 0;
        for (int k = (int)to_destroy.size() - 1; k >= 0; k--) {
            int st = removed[i++];
            L.beh(st).update_indirect_neighbour_shapes(L, st, to_destroy[k], UPDATE_CLIENTS, 511);
            L.update_neighbors_at(to_destroy[k], L.bidx(st));
        }
        for (int k = (int)to_push.size() - 1; k >= 0; k--) L.update_neighbors_at(to_push[k], L.bidx(removed[i++]));
        if (extending) L.update_neighbors_at(head_pos, L.B_PISTON_HEAD);
        return true;
    }
};

struct PistonHead : Behavior {
    int self;
    explicit PistonHead(int s) : self(s) {}
    bool fitting_base(Level& L, int st, int base) {
        int wanted = L.table.is(st, "type", "sticky") ? L.B_STICKY_PISTON : L.B_PISTON;
        return L.bidx(base) == wanted && prop_true(L, base, "extended") && facing(L, base) == facing(L, st);
    }
    bool survives(Level& L, int st, Pos pos) {
        int behind = L.get(pos.rel(OPPD[facing(L, st)]));
        return fitting_base(L, st, behind) || (L.is_block(behind, L.B_MOVING_PISTON) && facing(L, behind) == facing(L, st));
    }
    int update_shape(Level& L, int st, Dir d, int, Pos pos, Pos) override {
        if (OPPD[d] == facing(L, st) && !survives(L, st, pos)) return 0;
        return st;
    }
    void neighbor_changed(Level& L, int st, Pos pos, int source, Pos from, bool) override {
        if (survives(L, st, pos)) L.neighbor_changed(pos.rel(OPPD[facing(L, st)]), source, from);
    }
    void on_remove(Level& L, int st, Pos pos, int nw, bool moved) override {
        if (!moved && !L.is_block(nw, self)) {
            Pos base = pos.rel(OPPD[facing(L, st)]);
            if (fitting_base(L, st, L.get(base))) L.destroy_block(base, true);
        }
    }
};

struct MovingPistonBlock : Behavior {
    int self;
    explicit MovingPistonBlock(int s) : self(s) {}
    void on_remove(Level& L, int, Pos pos, int nw, bool) override {
        if (!L.is_block(nw, self) && L.moving.count(pos)) L.final_tick(pos);
    }
};

inline void Level::tick_moving_piston(Pos p) {
    auto it = moving.find(p);
    if (it == moving.end()) return;
    MovingPiston& m = it->second;
    m.last_ticked = game_time;
    m.progress_o = m.progress;
    if (m.progress_o >= 1.0) {
        MovingPiston copy = m;
        remove_moving(p);
        if (is_block(get(p), B_MOVING_PISTON)) {
            int st = update_from_neighbour_shapes(copy.moved_state, p);
            if (st == 0) {
                set_block(p, copy.moved_state, UPDATE_MOVE_BY_PISTON | UPDATE_KNOWN_SHAPE | UPDATE_INVISIBLE);
                update_or_destroy(copy.moved_state, st, p, UPDATE_ALL);
            } else {
                set_block(p, st, UPDATE_MOVE_BY_PISTON | UPDATE_ALL);
                neighbor_changed(p, bidx(st), p);
            }
        }
        return;
    }
    m.progress = std::min(1.0, m.progress + 0.5);
}

inline void Level::final_tick(Pos p) {
    auto it = moving.find(p);
    if (it == moving.end()) return;
    MovingPiston copy = it->second;
    if (copy.progress_o < 1.0) {
        remove_moving(p);
        if (is_block(get(p), B_MOVING_PISTON)) {
            int st = copy.is_source ? 0 : update_from_neighbour_shapes(copy.moved_state, p);
            set_block(p, st, UPDATE_ALL);
            neighbor_changed(p, bidx(st), p);
        }
    }
}

// ---------------------------------------------------------------- registry
inline void build_registry(Level& L) {
    BlockTable& T = L.table;
    auto idx = [&](const char* n) { return T.index_of(std::string("minecraft:") + n); };
    L.B_AIR = idx("air"); L.B_WIRE = idx("redstone_wire"); L.B_REPEATER = idx("repeater"); L.B_COMPARATOR = idx("comparator");
    L.B_OBSERVER = idx("observer"); L.B_REDSTONE_BLOCK = idx("redstone_block"); L.B_HOPPER = idx("hopper");
    L.B_MOVING_PISTON = idx("moving_piston"); L.B_PISTON_HEAD = idx("piston_head"); L.B_PISTON = idx("piston");
    L.B_STICKY_PISTON = idx("sticky_piston"); L.B_TRIPWIRE = idx("tripwire"); L.B_HOOK = idx("tripwire_hook");
    L.B_TNT = idx("tnt"); L.B_SLIME = idx("slime_block"); L.B_HONEY = idx("honey_block");

    L.behaviors.assign(T.blocks.size(), &L.default_behavior);
    auto add = [&](int index, Behavior* b) {
        L.owned.emplace_back(b);
        if (index >= 0) L.behaviors[index] = b;
    };
    add(L.B_WIRE, new RedstoneWire(L.B_WIRE));
    add(idx("redstone_torch"), new RedstoneTorch(idx("redstone_torch"), false));
    add(idx("redstone_wall_torch"), new RedstoneTorch(idx("redstone_wall_torch"), true));
    add(L.B_REPEATER, new Repeater(L.B_REPEATER));
    add(L.B_COMPARATOR, new Comparator(L.B_COMPARATOR));
    add(L.B_OBSERVER, new Observer(L.B_OBSERVER));
    add(idx("lever"), new Lever(idx("lever")));
    add(L.B_REDSTONE_BLOCK, new RedstoneBlock());
    add(idx("target"), new Target());
    add(idx("redstone_lamp"), new RedstoneLamp(idx("redstone_lamp")));
    add(L.B_TNT, new Tnt(L.B_TNT));
    add(idx("note_block"), new NoteBlock(idx("note_block")));
    add(L.B_HOPPER, new HopperBlock(L.B_HOPPER));
    TripwireHook* hook = new TripwireHook(L.B_HOOK);
    add(L.B_HOOK, hook);
    add(L.B_TRIPWIRE, new Tripwire(L.B_TRIPWIRE, hook));
    add(L.B_PISTON, new PistonBase(L.B_PISTON, false));
    add(L.B_STICKY_PISTON, new PistonBase(L.B_STICKY_PISTON, true));
    add(L.B_PISTON_HEAD, new PistonHead(L.B_PISTON_HEAD));
    add(L.B_MOVING_PISTON, new MovingPistonBlock(L.B_MOVING_PISTON));

    for (int i = 0; i < (int)T.blocks.size(); i++) {
        if (L.behaviors[i] != &L.default_behavior) continue;
        const std::string& s = T.blocks[i].short_name;
        if (ends_with(s, "_button")) {
            bool stone = s == "stone_button" || s == "polished_blackstone_button";
            add(i, new Button(i, stone ? 20 : 30, stone));
        } else if (ends_with(s, "_pressure_plate")) {
            int kind = 0;
            if (s == "light_weighted_pressure_plate") kind = 2;
            else if (s == "heavy_weighted_pressure_plate") kind = 3;
            else if (s == "stone_pressure_plate" || s == "polished_blackstone_pressure_plate") kind = 1;
            add(i, new PressurePlate(i, kind));
        } else if (ends_with(s, "_door")) add(i, new Door(i));
        else if (ends_with(s, "_trapdoor")) add(i, new Trapdoor());
        else if (ends_with(s, "_fence_gate")) add(i, new FenceGate());
        else if (s == "dispenser" || s == "dropper") add(i, new Dispenser(i, s == "dropper"));
        else if (s == "powered_rail" || s == "activator_rail") add(i, new PoweredRail(i));
        else if (s == "detector_rail") add(i, new DetectorRail(i));
        else if (s == "rail") add(i, new BaseRail(i, false));
        else if (ends_with(s, "_coral_wall_fan")) add(i, new CoralFan(true));
        else if (ends_with(s, "_coral_fan")) add(i, new CoralFan(false));
        else if (s == "chest" || s == "trapped_chest" || s == "barrel" || s == "furnace" || s == "blast_furnace" ||
                 s == "smoker" || s == "brewing_stand" || s == "crafter" || ends_with(s, "shulker_box"))
            add(i, new Container());
        else if (s == "composter" || s == "water_cauldron" || s == "powder_snow_cauldron") add(i, new LeveledAnalog("level", 0));
        else if (s == "cake") add(i, new LeveledAnalog("bites", 1));
        else if (s == "respawn_anchor") add(i, new LeveledAnalog("charges", 2));
        else if (s == "torch" || s == "soul_torch" || ends_with(s, "_carpet") || ends_with(s, "_sapling") ||
                 s == "short_grass" || s == "fern" || s == "dandelion" || s == "poppy" || s == "sugar_cane" ||
                 s == "wheat" || s == "carrots" || s == "potatoes")
            add(i, new NeedsSupportBelow());
        else if (s == "wall_torch" || s == "soul_wall_torch" || s == "ladder" || ends_with(s, "_wall_sign"))
            add(i, new WallAttached());
    }
}

// collision / conductor classes, like world/rs/blocks.py and world/block_shapes.py
inline void build_shape_tables(Level& L) {
    static const std::set<std::string> never = {"piston", "sticky_piston", "piston_head", "moving_piston", "observer",
        "redstone_block", "soul_sand", "glowstone", "mud", "farmland", "dirt_path", "barrier", "spawner", "trial_spawner",
        "vault", "beacon", "shulker_box"};
    static const std::set<std::string> always = {"ice", "frosted_ice", "packed_ice", "blue_ice"};
    size_t n = L.table.block_of_state.size();
    L.conductor.assign(n, 0);
    L.sturdy_full.assign(n, 0);
    L.no_collision.assign(n, 0);
    for (const BlockInfo& b : L.table.blocks) {
        bool cond = ((b.full && !b.transparent) || always.count(b.short_name)) && !never.count(b.short_name) &&
                    !ends_with(b.short_name, "shulker_box");
        for (int s = b.min_state; s <= b.max_state; s++) {
            L.sturdy_full[s] = b.full;
            L.conductor[s] = cond;
            L.no_collision[s] = b.empty_box || b.short_name == "powder_snow";
        }
        if (b.short_name == "snow") L.no_collision[b.min_state] = 1;
    }
}

}  // namespace vrs
