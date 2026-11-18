// ============================================================
// PyMC - vanilla 1.21.1 hoppers (HopperBlockEntity, MinecartHopper)
//
// Inventories stay in Python (container_manager, minecart entities). The hopper
// code reads the containers it touches through a callback - each slot tagged
// with the inventory that really owns it, so both halves of a double chest
// stay consistent - decides moves exactly like vanilla, and applies every move
// immediately through take/give callbacks. Composters are block-state
// containers handled here directly (WorldlyContainer of ComposterBlock).
// ============================================================
#pragma once

#include "engine.h"

namespace vrs {

// who really holds a slot: 0 block container at (a,b,c), 1 entity a, 2 composter at (a,b,c)
struct Owner {
    int kind = 0, a = 0, b = 0, c = 0;
    bool operator==(const Owner& o) const { return kind == o.kind && a == o.a && b == o.b && c == o.c; }
};

struct Slot {
    Owner owner;
    int slot = 0, item = 0, count = 0, max = 64;
    int flags = 0;  // 1 insert allowed, 2 insert needs a per-item check, 4 extract allowed
};

// Container reachable at a block position (kind 0: block container, or else an entity
// container such as a hopper minecart there) or an entity (kind 1), seen from `face`
// (NODIR = all slots). Fills up to cap*9 ints per slot:
//   owner kind, owner a, owner b, owner c, slot, item, count, max stack, flags
// and returns the slot count, or -1 when there is no container.
typedef int (*InvGetFn)(int kind, int a, int b, int c, int face, int32_t* out, int cap);
typedef int (*CanPlaceFn)(int kind, int a, int b, int c, int slot, int item, int face);
typedef void (*TakeFn)(int kind, int a, int b, int c, int slot, int count);
typedef void (*GiveFn)(int kind, int a, int b, int c, int slot, int item, int count);
// pick up item entities into a hopper (kind 0, block position) or hopper minecart (kind 1, entity id);
// returns 1 when a whole item entity was absorbed
typedef int (*PickupFn)(int kind, int a, int b, int c);
// ComposterBlock.COMPOSTABLES chance of an item (0 = not compostable)
typedef double (*CompostFn)(int item);

struct HopperEntity {
    int cooldown = -1;
    int64_t ticked = 0;
};

struct MinecartTick {
    int id;
    double x, y, z;
    bool enabled;
};

class Hoppers {
public:
    InvGetFn inv_get = nullptr;
    CanPlaceFn can_place = nullptr;
    TakeFn take = nullptr;
    GiveFn give = nullptr;
    PickupFn pickup = nullptr;
    CompostFn compost = nullptr;
    int bone_meal = 0;
    int B_COMPOSTER = -1;
    std::mt19937 rng{12345};
    std::unordered_map<Pos, HopperEntity, PosHash> entities;
    std::vector<Owner> changed;  // inventories whose contents changed (comparators / open windows)

    void tick(Level& L, const std::vector<Pos>& hoppers) {
        cache.clear();
        std::unordered_set<Pos, PosHash> live(hoppers.begin(), hoppers.end());
        for (auto it = entities.begin(); it != entities.end();) {
            if (!live.count(it->first)) it = entities.erase(it);
            else ++it;
        }
        for (const Pos& p : hoppers) {
            int st = L.get(p);
            if (!L.is_block(st, L.B_HOPPER)) continue;
            HopperEntity& h = entities[p];
            h.cooldown--;
            h.ticked = L.game_time;
            if (h.cooldown <= 0) {
                h.cooldown = 0;
                try_move_items(L, p, st, h);
            }
        }
        cache.clear();
    }

    // MinecartHopper.tick: when enabled, suck one item every tick (no cooldown)
    void tick_minecarts(Level& L, const std::vector<MinecartTick>& carts) {
        cache.clear();
        for (const MinecartTick& m : carts) {
            if (!m.enabled) continue;
            Owner self{1, m.id, 0, 0};
            Inv& own = inv(self, NODIR);
            if (!own.exists || all_full(own)) continue;
            Pos above{(int)std::floor(m.x), (int)std::floor(m.y + 0.5 + 1.0), (int)std::floor(m.z)};
            if (suck_into(L, self, above, false)) mark_changed(L, self);
        }
        cache.clear();
    }

private:
    struct Inv {
        bool exists = false;
        std::vector<Slot> slots;
    };
    struct Key {
        Owner o;
        int face;
        bool operator==(const Key& k) const { return o == k.o && face == k.face; }
    };
    struct KeyHash {
        size_t operator()(const Key& k) const {
            return ((((size_t)k.o.kind * 1000003u + (size_t)(uint32_t)k.o.a) * 1000003u + (size_t)(uint32_t)k.o.b) *
                        1000003u + (size_t)(uint32_t)k.o.c) * 31u + (size_t)k.face;
        }
    };
    std::unordered_map<Key, Inv, KeyHash> cache;

    static Owner block_owner(Pos p) { return Owner{0, p.x, p.y, p.z}; }
    static Pos pos_of(const Owner& o) { return Pos{o.a, o.b, o.c}; }

    Inv& inv(Owner o, int face, Level* L = nullptr) {
        Key k{o, face};
        auto it = cache.find(k);
        if (it != cache.end()) return it->second;
        Inv& v = cache[k];
        if (o.kind == 0 && L && B_COMPOSTER >= 0) {
            int st = L->get(pos_of(o));
            if (L->is_block(st, B_COMPOSTER)) {
                composter_view(*L, st, pos_of(o), face, v);
                return v;
            }
        }
        if (inv_get) {
            static thread_local int32_t buf[128 * 9];
            int n = inv_get(o.kind, o.a, o.b, o.c, face, buf, 128);
            if (n >= 0) {
                v.exists = true;
                for (int i = 0; i < n && i < 128; i++) {
                    const int32_t* r = buf + i * 9;
                    Slot s;
                    s.owner = Owner{r[0], r[1], r[2], r[3]};
                    s.slot = r[4]; s.item = r[5]; s.count = r[6]; s.max = r[7]; s.flags = r[8];
                    v.slots.push_back(s);
                }
            }
        }
        return v;
    }

    // ComposterBlock.getContainer: output (level 8), empty (level 7) or input (< 7)
    void composter_view(Level& L, int st, Pos p, int face, Inv& v) {
        v.exists = true;
        int level = L.table.prop_int(st, "level");
        if (level == 7) return;
        Slot s;
        s.owner = Owner{2, p.x, p.y, p.z};
        s.max = 1;
        if (level == 8) {
            s.item = bone_meal; s.count = 1; s.max = 64;
            s.flags = face == DOWN ? 4 : 0;
        } else {
            s.flags = (face == UP || face == NODIR) ? 2 : 0;
        }
        v.slots.push_back(s);
    }

    void forget(const Owner& o) {
        for (auto it = cache.begin(); it != cache.end();) {
            bool hit = it->first.o == o;
            for (const Slot& s : it->second.slots) if (s.owner == o) hit = true;
            if (hit) it = cache.erase(it);
            else ++it;
        }
    }
    // a move changes the same slot as seen from every view (both halves of a double chest, every face)
    void adjust(const Owner& o, int slot, int item, int delta) {
        for (auto& kv : cache) {
            for (Slot& s : kv.second.slots) {
                if (!(s.owner == o) || s.slot != slot) continue;
                if (delta > 0 && s.count == 0) s.item = item;
                s.count += delta;
                if (s.count <= 0) { s.count = 0; s.item = 0; }
            }
        }
    }
    static bool all_empty(const Inv& v) {
        for (const Slot& s : v.slots) if (s.count > 0) return false;
        return true;
    }
    static bool all_full(const Inv& v) {
        for (const Slot& s : v.slots) if (s.count < s.max) return false;
        return true;
    }
    bool can_place_in(const Slot& s, int item, int face) {
        if (s.flags & 1) return true;
        if (!(s.flags & 2)) return false;
        if (s.owner.kind == 2) return compost && compost(item) > 0.0;
        return can_place && can_place(s.owner.kind, s.owner.a, s.owner.b, s.owner.c, s.slot, item, face);
    }
    void mark_changed(Level& L, const Owner& o) {
        if (o.kind == 2) return;  // the composter's block state change does it
        if (std::find(changed.begin(), changed.end(), o) == changed.end()) changed.push_back(o);
        if (o.kind == 0) {
            Pos p = pos_of(o);
            L.update_neighbour_for_output_signal(p, L.bidx(L.get(p)));
        }
    }
    void mark_view_changed(Level& L, const Inv& v, const Owner& fallback) {
        bool any = false;
        std::vector<Owner> done;
        for (const Slot& s : v.slots) {
            if (std::find(done.begin(), done.end(), s.owner) != done.end()) continue;
            done.push_back(s.owner);
            mark_changed(L, s.owner);
            any = true;
        }
        if (!any) mark_changed(L, fallback);
    }

    // ComposterBlock.insertItem
    void composter_insert(Level& L, Pos p, int item) {
        int st = L.get(p);
        if (!L.is_block(st, B_COMPOSTER)) return;
        int level = L.table.prop_int(st, "level");
        double chance = compost ? compost(item) : 0.0;
        if ((level == 0 && chance > 0.0) || std::uniform_real_distribution<double>(0.0, 1.0)(rng) < chance) {
            int nl = level + 1;
            L.set_block(p, L.table.with(st, "level", nl), UPDATE_ALL);
            L.effect(FX_SOUND, p, SND_COMPOSTER_FILL_SUCCESS, 100);
            if (nl == 7) L.schedule_tick(p, B_COMPOSTER, 20);
        } else {
            L.effect(FX_SOUND, p, SND_COMPOSTER_FILL, 100);
        }
    }
    // ComposterBlock.empty
    void composter_empty(Level& L, Pos p) {
        int st = L.get(p);
        if (!L.is_block(st, B_COMPOSTER)) return;
        L.set_block(p, L.table.with(st, "level", 0), UPDATE_ALL);
        L.effect(FX_SOUND, p, SND_COMPOSTER_EMPTY, 100);
    }

    void perform(Level& L, const Slot& from, const Slot& to) {
        int item = from.item;
        if (from.owner.kind == 2) {
            composter_empty(L, pos_of(from.owner));
            if (give) give(to.owner.kind, to.owner.a, to.owner.b, to.owner.c, to.slot, item, 1);
            forget(from.owner);
            adjust(to.owner, to.slot, item, +1);
        } else if (to.owner.kind == 2) {
            if (take) take(from.owner.kind, from.owner.a, from.owner.b, from.owner.c, from.slot, 1);
            adjust(from.owner, from.slot, item, -1);
            composter_insert(L, pos_of(to.owner), item);
            forget(to.owner);
        } else {
            if (take) take(from.owner.kind, from.owner.a, from.owner.b, from.owner.c, from.slot, 1);
            if (give) give(to.owner.kind, to.owner.a, to.owner.b, to.owner.c, to.slot, item, 1);
            adjust(from.owner, from.slot, item, -1);
            adjust(to.owner, to.slot, item, +1);
        }
    }

    // HopperBlockEntity.addItem(source, destination, one item of `from`, face)
    bool move_one(Level& L, const Slot& from, Owner dst, int face, const Pos* src_hopper) {
        Inv& d = inv(dst, face, &L);
        if (!d.exists) return false;
        bool dst_was_empty = all_empty(inv(dst, NODIR, &L));
        std::vector<Slot> slots = d.slots;
        for (const Slot& s : slots) {
            if (!can_place_in(s, from.item, face)) continue;
            bool ok = s.count == 0 || (s.item == from.item && s.count < s.max && s.count < from.max);
            if (!ok) continue;
            perform(L, from, s);
            if (dst_was_empty && dst.kind == 0 && L.is_block(L.get(pos_of(dst)), L.B_HOPPER)) {
                Pos dp = pos_of(dst);
                auto it = entities.emplace(dp, HopperEntity()).first;  // block entity exists from placement
                if (it->second.cooldown <= 8) {
                    int k = 0;
                    if (src_hopper) {
                        auto sit = entities.find(*src_hopper);
                        if (sit != entities.end() && it->second.ticked >= sit->second.ticked) k = 1;
                    }
                    it->second.cooldown = 8 - k;
                }
            }
            if (s.owner.kind != 2) mark_view_changed(L, d, dst);
            return true;
        }
        return false;
    }

    bool eject(Level& L, Pos p, int st) {
        Dir f = dir_from(L.table.prop(st, "facing"));
        if (f == NODIR) return false;
        Owner target = block_owner(p.rel(f));
        int face = OPPD[f];
        Inv& t = inv(target, face, &L);
        if (!t.exists || all_full(t)) return false;
        std::vector<Slot> slots = inv(block_owner(p), NODIR, &L).slots;
        for (const Slot& s : slots) {
            if (s.count <= 0) continue;
            if (move_one(L, s, target, face, &p)) return true;
        }
        return false;
    }

    // HopperBlockEntity.suckInItems for a hopper block (grid aligned) or a hopper minecart
    bool suck_into(Level& L, Owner self, Pos above, bool grid_aligned) {
        Owner src_owner = block_owner(above);
        Inv& src = inv(src_owner, DOWN, &L);
        if (src.exists) {
            std::vector<Slot> slots = src.slots;
            Pos above_pos = above;
            bool above_is_hopper = L.is_block(L.get(above), L.B_HOPPER);
            for (const Slot& s : slots) {
                if (s.count <= 0 || !(s.flags & 4)) continue;
                if (move_one(L, s, self, NODIR, above_is_hopper ? &above_pos : nullptr)) {
                    if (s.owner.kind != 2) mark_view_changed(L, src, src_owner);
                    return true;
                }
            }
            return false;
        }
        if (grid_aligned && L.is_full(L.get(above))) return false;  // a full block covers the hopper
        if (pickup && pickup(self.kind, self.a, self.b, self.c)) {
            forget(self);
            return true;
        }
        forget(self);  // partial pickups change the inventory too
        return false;
    }

    void try_move_items(Level& L, Pos p, int st, HopperEntity& h) {
        if (h.cooldown > 0 || !L.table.is(st, "enabled", "true")) return;
        Owner self = block_owner(p);
        bool moved = false;
        if (!all_empty(inv(self, NODIR, &L))) moved = eject(L, p, st);
        if (!all_full(inv(self, NODIR, &L))) moved |= suck_into(L, self, p.rel(UP), true);
        if (moved) {
            h.cooldown = 8;
            mark_changed(L, self);
        }
    }
};

}  // namespace vrs
