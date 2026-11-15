// ============================================================
// PyMC - Density function graph (Minecraft Java 1.21.1 noise router)
//
// Compiles the vanilla density-function JSON into a node array and
// evaluates it with the same caching semantics as NoiseChunk:
//   interpolated  -> trilinear interpolation between 4x8x4 cell corners
//   flat_cache    -> value at the quart position (y = 0) inside the chunk
//   cache_2d / cache_once / cache_all_in_cell -> pure caches
//   blend_*       -> no blending (no old chunks), beardifier -> 0
// ============================================================
#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "json.h"
#include "noise.h"
#include "random.h"

namespace vgen {

enum class DF : uint8_t {
    Const, Add, Mul, Min, Max, Abs, Square, Cube, HalfNeg, QuarterNeg, Squeeze, Clamp,
    YGradient, Noise, ShiftedNoise, ShiftA, ShiftB, Shift, RangeChoice, Interpolated,
    FlatCache, Cache2D, CacheOnce, BlendAlpha, BlendOffset, BlendDensity, Beardifier,
    OldBlended, WeirdScaled, Spline,
};

struct DFNode {
    DF t = DF::Const;
    int a = -1, b = -1, c = -1, d = -1;   // children
    double p0 = 0, p1 = 0, p2 = 0, p3 = 0;
    int noise = -1;                       // NormalNoise index / BlendedNoise index
    int spline = -1;
    int slot = -1;                        // cache slot for cache nodes
};

struct SplineDef {
    int coordinate = -1;
    std::vector<float> locations, derivatives, constants;
    std::vector<int> children;  // -1 => constant value
};

struct NoiseDef { int first_octave; std::vector<double> amplitudes; };

static constexpr int CHUNK_QUARTS = 5;                 // noiseSizeXZ + 1
static constexpr int INTERP_X = 5, INTERP_Z = 5, INTERP_Y = 49;

// Per-chunk evaluation state (one per generated chunk, not shared between threads).
struct ChunkEval {
    bool active = false;
    int min_x = 0, min_z = 0, min_y = -64;
    int first_qx = 0, first_qz = 0;
    std::vector<std::vector<double>> interp;
    std::vector<char> interp_ready;
    std::vector<std::array<double, CHUNK_QUARTS * CHUNK_QUARTS>> flat;
    std::vector<char> flat_ready;
    std::vector<std::unordered_map<int64_t, double>> cache2d;
    struct Once { int x = 0, y = 0, z = 0; double v = 0; bool valid = false; };
    std::vector<Once> once;

    void init(int slots_interp, int slots_flat, int slots_2d, int slots_once) {
        interp.assign(slots_interp, std::vector<double>());
        interp_ready.assign(slots_interp, 0);
        flat.assign(slots_flat, {});
        flat_ready.assign(slots_flat, 0);
        cache2d.assign(slots_2d, {});
        once.assign(slots_once, Once());
    }
    void set_chunk(int chunk_x, int chunk_z) {
        active = true;
        min_x = chunk_x * 16;
        min_z = chunk_z * 16;
        first_qx = min_x >> 2;
        first_qz = min_z >> 2;
        std::fill(interp_ready.begin(), interp_ready.end(), 0);
        std::fill(flat_ready.begin(), flat_ready.end(), 0);
        for (auto& m : cache2d) m.clear();
        for (auto& o : once) o.valid = false;
    }
};

class DensityGraph {
public:
    std::vector<DFNode> nodes;
    std::vector<SplineDef> splines;
    std::vector<NormalNoise> noises;
    std::vector<std::unique_ptr<BlendedNoise>> blended;
    std::map<std::string, int> noise_index;
    std::map<std::string, NoiseDef> noise_defs;
    int slots_interp = 0, slots_flat = 0, slots_2d = 0, slots_once = 0;
    int min_y = -64;
    bool deepslate_compat = false;

    void load(const Json& data, const PositionalFactory& random, bool compat = false) {
        deepslate_compat = compat;
        random_ = random;
        functions_ = &data["density_functions"];
        for (auto& kv : data["noises"].obj) {
            NoiseDef def;
            def.first_octave = kv.second["firstOctave"].as_int();
            for (auto& a : kv.second["amplitudes"].arr) def.amplitudes.push_back(a.as_double());
            noise_defs[kv.first] = def;
        }
        min_y = data["noise"]["min_y"].as_int();
    }

    int compile(const Json& node) {
        if (node.is_number()) return add_const(node.num);
        if (node.is_string()) return ref(node.str);
        std::string type = node["type"].str;
        if (type == "ref") return ref(node["name"].str);
        DFNode n;
        if (type == "constant") { n.t = DF::Const; n.p0 = node["argument"].as_double(); return push(n); }
        if (type == "add" || type == "mul" || type == "min" || type == "max") {
            n.t = type == "add" ? DF::Add : type == "mul" ? DF::Mul : type == "min" ? DF::Min : DF::Max;
            n.a = compile(node["argument1"]);
            n.b = compile(node["argument2"]);
            return push(n);
        }
        static const std::map<std::string, DF> unary = {
            {"abs", DF::Abs}, {"square", DF::Square}, {"cube", DF::Cube}, {"half_negative", DF::HalfNeg},
            {"quarter_negative", DF::QuarterNeg}, {"squeeze", DF::Squeeze}, {"interpolated", DF::Interpolated},
            {"flat_cache", DF::FlatCache}, {"cache_2d", DF::Cache2D}, {"cache_once", DF::CacheOnce},
            {"cache_all_in_cell", DF::CacheOnce}, {"blend_density", DF::BlendDensity}};
        auto u = unary.find(type);
        if (u != unary.end()) {
            n.t = u->second;
            n.a = compile(node["argument"]);
            if (n.t == DF::Interpolated) n.slot = slots_interp++;
            else if (n.t == DF::FlatCache) n.slot = slots_flat++;
            else if (n.t == DF::Cache2D) n.slot = slots_2d++;
            else if (n.t == DF::CacheOnce) n.slot = slots_once++;
            return push(n);
        }
        if (type == "clamp") {
            n.t = DF::Clamp; n.a = compile(node["input"]);
            n.p0 = node["min"].as_double(); n.p1 = node["max"].as_double();
            return push(n);
        }
        if (type == "y_clamped_gradient") {
            n.t = DF::YGradient;
            n.p0 = node["from_y"].as_double(); n.p1 = node["to_y"].as_double();
            n.p2 = node["from_value"].as_double(); n.p3 = node["to_value"].as_double();
            return push(n);
        }
        if (type == "noise") {
            n.t = DF::Noise; n.noise = get_noise(node["noise"].str);
            n.p0 = node.get("xz_scale", 1.0); n.p1 = node.get("y_scale", 1.0);
            return push(n);
        }
        if (type == "shifted_noise") {
            n.t = DF::ShiftedNoise; n.noise = get_noise(node["noise"].str);
            n.p0 = node.get("xz_scale", 1.0); n.p1 = node.get("y_scale", 1.0);
            n.a = compile(node["shift_x"]); n.b = compile(node["shift_y"]); n.c = compile(node["shift_z"]);
            return push(n);
        }
        if (type == "shift_a" || type == "shift_b" || type == "shift") {
            n.t = type == "shift_a" ? DF::ShiftA : type == "shift_b" ? DF::ShiftB : DF::Shift;
            n.noise = get_noise(node["argument"].str);
            return push(n);
        }
        if (type == "range_choice") {
            n.t = DF::RangeChoice;
            n.a = compile(node["input"]);
            n.p0 = node["min_inclusive"].as_double(); n.p1 = node["max_exclusive"].as_double();
            n.b = compile(node["when_in_range"]); n.c = compile(node["when_out_of_range"]);
            return push(n);
        }
        if (type == "blend_alpha") { n.t = DF::BlendAlpha; return push(n); }
        if (type == "blend_offset") { n.t = DF::BlendOffset; return push(n); }
        if (type == "beardifier") { n.t = DF::Beardifier; return push(n); }
        if (type == "old_blended_noise") {
            n.t = DF::OldBlended;
            Xoroshiro r = random_.from_hash_of("minecraft:terrain");
            blended.push_back(std::make_unique<BlendedNoise>(
                r, node["xz_scale"].as_double(), node["y_scale"].as_double(), node["xz_factor"].as_double(),
                node["y_factor"].as_double(), node["smear_scale_multiplier"].as_double(), deepslate_compat));
            n.noise = (int)blended.size() - 1;
            return push(n);
        }
        if (type == "weird_scaled_sampler") {
            n.t = DF::WeirdScaled;
            n.a = compile(node["input"]);
            n.noise = get_noise(node["noise"].str);
            n.p0 = node["rarity_value_mapper"].str == "type_1" ? 1.0 : 2.0;
            return push(n);
        }
        if (type == "spline") {
            n.t = DF::Spline;
            n.spline = compile_spline(node["spline"]);
            return push(n);
        }
        throw std::runtime_error("unsupported density function type: " + type);
    }

    int get_noise(const std::string& name) {
        auto it = noise_index.find(name);
        if (it != noise_index.end()) return it->second;
        auto def = noise_defs.find(name);
        if (def == noise_defs.end()) throw std::runtime_error("unknown noise: " + name);
        noises.push_back(NormalNoise::create(random_.from_hash_of(name), def->second.first_octave, def->second.amplitudes));
        int idx = (int)noises.size() - 1;
        noise_index[name] = idx;
        return idx;
    }

    // ---------------- evaluation ----------------

    double eval(int idx, int x, int y, int z, ChunkEval* cc, bool fill) const {
        const DFNode& n = nodes[idx];
        switch (n.t) {
            case DF::Const: return n.p0;
            case DF::Add: return eval(n.a, x, y, z, cc, fill) + eval(n.b, x, y, z, cc, fill);
            case DF::Mul: {
                double v = eval(n.a, x, y, z, cc, fill);
                return v == 0.0 ? 0.0 : v * eval(n.b, x, y, z, cc, fill);
            }
            case DF::Min: return std::min(eval(n.a, x, y, z, cc, fill), eval(n.b, x, y, z, cc, fill));
            case DF::Max: return std::max(eval(n.a, x, y, z, cc, fill), eval(n.b, x, y, z, cc, fill));
            case DF::Abs: return std::fabs(eval(n.a, x, y, z, cc, fill));
            case DF::Square: { double v = eval(n.a, x, y, z, cc, fill); return v * v; }
            case DF::Cube: { double v = eval(n.a, x, y, z, cc, fill); return v * v * v; }
            case DF::HalfNeg: { double v = eval(n.a, x, y, z, cc, fill); return v > 0.0 ? v : v * 0.5; }
            case DF::QuarterNeg: { double v = eval(n.a, x, y, z, cc, fill); return v > 0.0 ? v : v * 0.25; }
            case DF::Squeeze: {
                double e = clampd(eval(n.a, x, y, z, cc, fill), -1.0, 1.0);
                return e / 2.0 - e * e * e / 24.0;
            }
            case DF::Clamp: return clampd(eval(n.a, x, y, z, cc, fill), n.p0, n.p1);
            case DF::YGradient: return clamped_map((double)y, n.p0, n.p1, n.p2, n.p3);
            case DF::Noise:
                return noises[n.noise].value((double)x * n.p0, (double)y * n.p1, (double)z * n.p0);
            case DF::ShiftedNoise: {
                double d = (double)x * n.p0 + eval(n.a, x, y, z, cc, fill);
                double e = (double)y * n.p1 + eval(n.b, x, y, z, cc, fill);
                double f = (double)z * n.p0 + eval(n.c, x, y, z, cc, fill);
                return noises[n.noise].value(d, e, f);
            }
            case DF::ShiftA: return shift(n.noise, (double)x, 0.0, (double)z);
            case DF::ShiftB: return shift(n.noise, (double)z, (double)x, 0.0);
            case DF::Shift: return shift(n.noise, (double)x, (double)y, (double)z);
            case DF::RangeChoice: {
                double v = eval(n.a, x, y, z, cc, fill);
                return (v >= n.p0 && v < n.p1) ? eval(n.b, x, y, z, cc, fill) : eval(n.c, x, y, z, cc, fill);
            }
            case DF::Interpolated: {
                if (fill && cc && cc->active) return interpolate(n, x, y, z, cc);
                return eval(n.a, x, y, z, cc, false);
            }
            case DF::FlatCache: {
                if (cc && cc->active) {
                    int qx = (x >> 2) - cc->first_qx, qz = (z >> 2) - cc->first_qz;
                    if (qx >= 0 && qz >= 0 && qx < CHUNK_QUARTS && qz < CHUNK_QUARTS) {
                        auto& grid = cc->flat[n.slot];
                        if (!cc->flat_ready[n.slot]) {
                            for (int i = 0; i < CHUNK_QUARTS; i++)
                                for (int j = 0; j < CHUNK_QUARTS; j++)
                                    grid[i * CHUNK_QUARTS + j] =
                                        eval(n.a, (cc->first_qx + i) << 2, 0, (cc->first_qz + j) << 2, cc, false);
                            cc->flat_ready[n.slot] = 1;
                        }
                        return grid[qx * CHUNK_QUARTS + qz];
                    }
                }
                return eval(n.a, x, y, z, cc, fill);
            }
            case DF::Cache2D: {
                if (cc) {
                    int64_t key = ((int64_t)x << 32) ^ (int64_t)(uint32_t)z;
                    auto& m = cc->cache2d[n.slot];
                    auto it = m.find(key);
                    if (it != m.end()) return it->second;
                    double v = eval(n.a, x, y, z, cc, fill);
                    m.emplace(key, v);
                    return v;
                }
                return eval(n.a, x, y, z, cc, fill);
            }
            case DF::CacheOnce: {
                if (cc) {
                    auto& o = cc->once[n.slot];
                    if (o.valid && o.x == x && o.y == y && o.z == z) return o.v;
                    double v = eval(n.a, x, y, z, cc, fill);
                    o.x = x; o.y = y; o.z = z; o.v = v; o.valid = true;
                    return v;
                }
                return eval(n.a, x, y, z, cc, fill);
            }
            case DF::BlendAlpha: return 1.0;
            case DF::BlendOffset: return 0.0;
            case DF::BlendDensity: return eval(n.a, x, y, z, cc, fill);
            case DF::Beardifier: return 0.0;
            case DF::OldBlended: return blended[n.noise]->compute(x, y, z);
            case DF::WeirdScaled: {
                double d = eval(n.a, x, y, z, cc, fill);
                double e;
                if (n.p0 == 1.0) e = d < -0.5 ? 0.75 : d < 0.0 ? 1.0 : d < 0.5 ? 1.5 : 2.0;
                else e = d < -0.75 ? 0.5 : d < -0.5 ? 0.75 : d < 0.5 ? 1.0 : d < 0.75 ? 2.0 : 3.0;
                return e * std::fabs(noises[n.noise].value((double)x / e, (double)y / e, (double)z / e));
            }
            case DF::Spline: return (double)apply_spline(n.spline, x, y, z, cc, fill);
        }
        return 0.0;
    }

private:
    PositionalFactory random_;
    const Json* functions_ = nullptr;
    std::map<std::string, int> refs_;

    int push(const DFNode& n) { nodes.push_back(n); return (int)nodes.size() - 1; }
    int add_const(double v) { DFNode n; n.t = DF::Const; n.p0 = v; return push(n); }

    int ref(const std::string& name) {
        auto it = refs_.find(name);
        if (it != refs_.end()) {
            if (it->second < 0) throw std::runtime_error("cyclic density function: " + name);
            return it->second;
        }
        refs_[name] = -1;
        int idx = compile((*functions_)[name]);
        refs_[name] = idx;
        return idx;
    }

    int compile_spline(const Json& s) {
        SplineDef def;
        def.coordinate = compile(s["coordinate"]);
        for (auto& p : s["points"].arr) {
            def.locations.push_back((float)p["location"].as_double());
            def.derivatives.push_back((float)p["derivative"].as_double());
            const Json& v = p["value"];
            if (v.is_number()) { def.children.push_back(-1); def.constants.push_back((float)v.num); }
            else { def.children.push_back(compile_spline(v)); def.constants.push_back(0.0f); }
        }
        splines.push_back(std::move(def));
        return (int)splines.size() - 1;
    }

    double shift(int noise, double d, double e, double f) const {
        return noises[noise].value(d * 0.25, e * 0.25, f * 0.25) * 4.0;
    }

    float spline_value(const SplineDef& s, int i, int x, int y, int z, ChunkEval* cc, bool fill) const {
        return s.children[i] < 0 ? s.constants[i] : apply_spline(s.children[i], x, y, z, cc, fill);
    }

    float apply_spline(int idx, int x, int y, int z, ChunkEval* cc, bool fill) const {
        const SplineDef& s = splines[idx];
        float f = (float)eval(s.coordinate, x, y, z, cc, fill);
        int count = (int)s.locations.size();
        int first_greater = count;
        for (int k = 0; k < count; k++) if (f < s.locations[k]) { first_greater = k; break; }
        int i = first_greater - 1;
        int j = count - 1;
        if (i < 0) {
            float v = spline_value(s, 0, x, y, z, cc, fill);
            float g = s.derivatives[0];
            return g == 0.0f ? v : v + g * (f - s.locations[0]);
        }
        if (i == j) {
            float v = spline_value(s, j, x, y, z, cc, fill);
            float g = s.derivatives[j];
            return g == 0.0f ? v : v + g * (f - s.locations[j]);
        }
        float g = s.locations[i], h = s.locations[i + 1];
        float k = (f - g) / (h - g);
        float l = s.derivatives[i], m = s.derivatives[i + 1];
        float nv = spline_value(s, i, x, y, z, cc, fill);
        float o = spline_value(s, i + 1, x, y, z, cc, fill);
        float p = l * (h - g) - (o - nv);
        float q = -m * (h - g) + (o - nv);
        return lerpf(k, nv, o) + k * (1.0f - k) * lerpf(k, p, q);
    }

    double interpolate(const DFNode& n, int x, int y, int z, ChunkEval* cc) const {
        auto& grid = cc->interp[n.slot];
        if (!cc->interp_ready[n.slot]) {
            grid.resize(INTERP_X * INTERP_Z * INTERP_Y);
            for (int cx = 0; cx < INTERP_X; cx++)
                for (int cz = 0; cz < INTERP_Z; cz++)
                    for (int cy = 0; cy < INTERP_Y; cy++)
                        grid[(cx * INTERP_Z + cz) * INTERP_Y + cy] =
                            eval(n.a, cc->min_x + cx * 4, cc->min_y + cy * 8, cc->min_z + cz * 4, cc, false);
            cc->interp_ready[n.slot] = 1;
        }
        int lx = x - cc->min_x, lz = z - cc->min_z, ly = y - cc->min_y;
        int cx = lx >> 2, cz = lz >> 2, cy = ly >> 3;
        if (cx < 0 || cz < 0 || cy < 0 || cx >= 4 || cz >= 4 || cy >= INTERP_Y - 1)
            return eval(n.a, x, y, z, cc, false);
        double dx = (double)(lx & 3) / 4.0, dz = (double)(lz & 3) / 4.0, dy = (double)(ly & 7) / 8.0;
        auto g = [&](int ix, int iy, int iz) { return grid[((cx + ix) * INTERP_Z + (cz + iz)) * INTERP_Y + cy + iy]; };
        double xz00 = lerp(dy, g(0, 0, 0), g(0, 1, 0));
        double xz10 = lerp(dy, g(1, 0, 0), g(1, 1, 0));
        double xz01 = lerp(dy, g(0, 0, 1), g(0, 1, 1));
        double xz11 = lerp(dy, g(1, 0, 1), g(1, 1, 1));
        double z0 = lerp(dx, xz00, xz10);
        double z1 = lerp(dx, xz01, xz11);
        return lerp(dz, z0, z1);
    }
};

}  // namespace vgen
