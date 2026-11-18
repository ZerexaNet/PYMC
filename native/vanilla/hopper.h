// ============================================================
// PyMC - vanilla 1.21.1 hopper block entity (HopperBlockEntity.pushItemsTick)
//
// Inventories stay in Python (container_manager). Each tick the hopper code
// reads the containers it touches through a callback, decides moves exactly
// like vanilla (eject one item to the facing container, then pull one item
// from the container above or pick up item entities), and applies every move
// through a callback immediately, so Python and the local cache never differ.
// ============================================================
#pragma once

#include "engine.h"

namespace vrs {

// one slot as Python describes it
struct Slot {
    int slot = 0, item = 0, count = 0, max = 64;
    int flags = 0;  // 1 insert allowed, 2 insert needs a per-item check, 4 extract allowed
};

// fill up to cap*5 ints (slot, item, count, max, flags) for the slots reachable from `face`
// (NODIR = all slots); returns the slot count, or -1 when there is no container
typedef int (*InvGetFn)(int x, int y, int z, int face, int32_t* out, int cap);
typedef int (*CanPlaceFn)(int x, int y, int z, int slot, int item, int face);
// move `count` items from (sx,sy,sz)[sslot] into (dx,dy,dz)[dslot]
typedef void (*TransferFn)(int sx, int sy, int sz, int sslot, int dx, int dy, int dz, int dslot, int count);
// pick up item entities above a hopper into it; returns 1 when something moved
typedef int (*PickupFn)(int x, int y, int z);

struct HopperEntity {
    int cooldown = -1;
    int64_t ticked = 0;
};

class Hoppers {
public:
    InvGetFn inv_get = nullptr;
    CanPlaceFn can_place = nullptr;
    TransferFn transfer = nullptr;
    PickupFn pickup = nullptr;
    std::unordered_map<Pos, HopperEntity, PosHash> entities;
    std::vector<Pos> changed;  // containers whose contents changed (for comparators / open windows)

    void tick(Level& L, const std::vector<Pos>& hoppers) {
        cache.clear();
        // forget hoppers that no longer exist
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

private:
    struct Inv {
        bool exists = false;
        std::vector<Slot> slots;
    };
    std::unordered_map<int64_t, Inv> cache;  // key: pos + face

    static int64_t key(Pos p, int face) {
        return (((int64_t)p.x & 0x3FFFFFF) << 38) ^ (((int64_t)p.z & 0x3FFFFFF) << 12) ^ (((int64_t)(p.y + 64) & 0x1FF) << 3) ^
               face;
    }
    Inv& inv(Pos p, int face) {
        int64_t k = key(p, face);
        auto it = cache.find(k);
        if (it != cache.end()) return it->second;
        Inv& v = cache[k];
        if (inv_get) {
            int32_t buf[64 * 5];
            int n = inv_get(p.x, p.y, p.z, face, buf, 64);
            if (n >= 0) {
                v.exists = true;
                for (int i = 0; i < n && i < 64; i++) {
                    Slot s;
                    s.slot = buf[i * 5]; s.item = buf[i * 5 + 1]; s.count = buf[i * 5 + 2];
                    s.max = buf[i * 5 + 3]; s.flags = buf[i * 5 + 4];
                    v.slots.push_back(s);
                }
            }
        }
        return v;
    }
    void forget(Pos p) {
        for (int f = 0; f <= NODIR; f++) cache.erase(key(p, f));
    }
    // a move changes the same slot as seen from every face: keep all cached views in step
    void adjust(Pos p, int slot, int item, int delta) {
        for (int f = 0; f <= NODIR; f++) {
            auto it = cache.find(key(p, f));
            if (it == cache.end()) continue;
            for (Slot& s : it->second.slots) {
                if (s.slot != slot) continue;
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
    bool can_place_in(Pos p, const Slot& s, int item, int face) {
        if (s.flags & 1) return true;
        if (s.flags & 2) return can_place && can_place(p.x, p.y, p.z, s.slot, item, face);
        return false;
    }
    void mark_changed(Level& L, Pos p) {
        if (std::find(changed.begin(), changed.end(), p) == changed.end()) changed.push_back(p);
        L.update_neighbour_for_output_signal(p, L.bidx(L.get(p)));
    }

    // HopperBlockEntity.addItem(source, destination, 1 item, face) for one item from src[slot]
    bool move_one(Level& L, Pos src, const Slot& from, Pos dst, int face, bool src_is_hopper) {
        Inv& d = inv(dst, face);
        if (!d.exists) return false;
        bool dst_was_empty = all_empty(inv(dst, NODIR));
        for (Slot& s : d.slots) {
            if (!can_place_in(dst, s, from.item, face)) continue;
            bool ok = false;
            if (s.count == 0) ok = true;
            else if (s.item == from.item && s.count < s.max && s.count < from.max) ok = true;
            if (!ok) continue;
            int item = from.item, sslot = from.slot, dslot = s.slot;
            if (transfer) transfer(src.x, src.y, src.z, sslot, dst.x, dst.y, dst.z, dslot, 1);
            adjust(src, sslot, item, -1);
            adjust(dst, dslot, item, +1);
            if (dst_was_empty && L.is_block(L.get(dst), L.B_HOPPER)) {
                auto it = entities.emplace(dst, HopperEntity()).first;   // block entity exists from placement
                if (it->second.cooldown <= 8) {
                    int k = 0;
                    if (src_is_hopper) {
                        auto sit = entities.find(src);
                        if (sit != entities.end() && it->second.ticked >= sit->second.ticked) k = 1;
                    }
                    it->second.cooldown = 8 - k;
                }
            }
            mark_changed(L, dst);
            return true;
        }
        return false;
    }

    bool eject(Level& L, Pos p, int st) {
        Dir f = dir_from(L.table.prop(st, "facing"));
        if (f == NODIR) return false;
        Pos target = p.rel(f);
        int face = OPPD[f];
        Inv& t = inv(target, face);
        if (!t.exists || all_full(t)) return false;
        Inv& self = inv(p, NODIR);
        std::vector<Slot> slots = self.slots;  // copy: move_one adjusts the cache
        for (const Slot& s : slots) {
            if (s.count <= 0) continue;
            if (move_one(L, p, s, target, face, true)) return true;
        }
        return false;
    }

    bool suck(Level& L, Pos p) {
        Pos above = p.rel(UP);
        Inv& src = inv(above, DOWN);
        if (src.exists) {
            std::vector<Slot> slots = src.slots;
            bool above_is_hopper = L.is_block(L.get(above), L.B_HOPPER);
            for (const Slot& s : slots) {
                if (s.count <= 0 || !(s.flags & 4)) continue;
                if (move_one(L, above, s, p, NODIR, above_is_hopper)) {
                    mark_changed(L, above);
                    return true;
                }
            }
            return false;
        }
        // item entities, unless a full collision block covers the hopper
        int st = L.get(above);
        if (L.is_full(st)) return false;
        if (pickup && pickup(p.x, p.y, p.z)) {
            forget(p);
            return true;
        }
        return false;
    }

    void try_move_items(Level& L, Pos p, int st, HopperEntity& h) {
        if (h.cooldown > 0 || !L.table.is(st, "enabled", "true")) return;
        bool moved = false;
        if (!all_empty(inv(p, NODIR))) moved = eject(L, p, st);
        if (!all_full(inv(p, NODIR))) moved |= suck(L, p);
        if (moved) {
            h.cooldown = 8;
            mark_changed(L, p);
        }
    }
};

}  // namespace vrs
