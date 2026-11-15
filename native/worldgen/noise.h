// ============================================================
// PyMC - Vanilla noise generators (Minecraft Java 1.21.1)
//
// ImprovedNoise, PerlinNoise (new and legacy octave initialisation),
// NormalNoise, BlendedNoise ("old_blended_noise"), SimplexNoise and
// PerlinSimplexNoise. Arithmetic follows the Java code operation by
// operation so results are bit-identical (build without FMA contraction).
// ============================================================
#pragma once

#include <cmath>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "random.h"

namespace vgen {

inline int floor_int(double d) {
    int i = (int)d;
    return d < (double)i ? i - 1 : i;
}
inline int64_t lfloor(double d) {
    int64_t l = (int64_t)d;
    return d < (double)l ? l - 1 : l;
}
inline double lerp(double t, double a, double b) { return a + t * (b - a); }
inline float lerpf(float t, float a, float b) { return a + t * (b - a); }
inline double lerp2(double dx, double dy, double a, double b, double c, double d) {
    return lerp(dy, lerp(dx, a, b), lerp(dx, c, d));
}
inline double lerp3(double dx, double dy, double dz, double a, double b, double c, double d,
                    double e, double f, double g, double h) {
    return lerp(dz, lerp2(dx, dy, a, b, c, d), lerp2(dx, dy, e, f, g, h));
}
inline double smoothstep(double d) { return d * d * d * (d * (d * 6.0 - 15.0) + 10.0); }
inline double clampd(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }
inline double inverse_lerp(double d, double e, double f) { return (d - e) / (f - e); }
inline double clamped_lerp(double a, double b, double t) { return t < 0.0 ? a : (t > 1.0 ? b : lerp(t, a, b)); }
inline double clamped_map(double d, double e, double f, double g, double h) {
    return clamped_lerp(g, h, inverse_lerp(d, e, f));
}
inline double map_range(double d, double e, double f, double g, double h) {
    return lerp(inverse_lerp(d, e, f), g, h);
}
inline int floor_div(int a, int b) {
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}
inline int floor_mod(int a, int b) { return a - floor_div(a, b) * b; }

static const int GRADIENT[16][3] = {
    {1, 1, 0}, {-1, 1, 0}, {1, -1, 0}, {-1, -1, 0}, {1, 0, 1}, {-1, 0, 1}, {1, 0, -1}, {-1, 0, -1},
    {0, 1, 1}, {0, -1, 1}, {0, 1, -1}, {0, -1, -1}, {1, 1, 0}, {0, -1, 1}, {-1, 1, 0}, {0, -1, -1}};

inline double grad_dot(int hash, double x, double y, double z) {
    const int* g = GRADIENT[hash & 15];
    return (double)g[0] * x + (double)g[1] * y + (double)g[2] * z;
}

// ---------------- ImprovedNoise ----------------
struct ImprovedNoise {
    uint8_t p[256];
    double xo, yo, zo;

    template <class R>
    explicit ImprovedNoise(R& random) {
        xo = random.next_double() * 256.0;
        yo = random.next_double() * 256.0;
        zo = random.next_double() * 256.0;
        for (int i = 0; i < 256; i++) p[i] = (uint8_t)i;
        for (int i = 0; i < 256; i++) {
            int j = random.next_int(256 - i);
            uint8_t b = p[i];
            p[i] = p[i + j];
            p[i + j] = b;
        }
    }

    inline int P(int i) const { return p[i & 0xFF]; }

    double noise(double d, double e, double f, double y_scale = 0.0, double y_max = 0.0) const {
        double i = d + xo, j = e + yo, k = f + zo;
        int l = floor_int(i), m = floor_int(j), n = floor_int(k);
        double o = i - (double)l, q = j - (double)m, r = k - (double)n;
        double s = 0.0;
        if (y_scale != 0.0) {
            double t = (y_max >= 0.0 && y_max < q) ? y_max : q;
            s = (double)floor_int(t / y_scale + (double)1.0E-7f) * y_scale;
        }
        return sample_and_lerp(l, m, n, o, q - s, r, q);
    }

    double sample_and_lerp(int i, int j, int k, double d, double e, double f, double g) const {
        int l = P(i), m = P(i + 1);
        int n = P(l + j), o = P(l + j + 1);
        int q = P(m + j), r = P(m + j + 1);
        double h = grad_dot(P(n + k), d, e, f);
        double s = grad_dot(P(q + k), d - 1.0, e, f);
        double t = grad_dot(P(o + k), d, e - 1.0, f);
        double u = grad_dot(P(r + k), d - 1.0, e - 1.0, f);
        double v = grad_dot(P(n + k + 1), d, e, f - 1.0);
        double w = grad_dot(P(q + k + 1), d - 1.0, e, f - 1.0);
        double x = grad_dot(P(o + k + 1), d, e - 1.0, f - 1.0);
        double y = grad_dot(P(r + k + 1), d - 1.0, e - 1.0, f - 1.0);
        return lerp3(smoothstep(d), smoothstep(g), smoothstep(f), h, s, t, u, v, w, x, y);
    }
};

inline double perlin_wrap(double d) {
    return d - (double)lfloor(d / 3.3554432E7 + 0.5) * 3.3554432E7;
}

// ---------------- PerlinNoise ----------------
struct PerlinNoise {
    std::vector<std::unique_ptr<ImprovedNoise>> levels;
    std::vector<double> amplitudes;
    int first_octave = 0;
    double lowest_freq_input_factor = 1.0;
    double lowest_freq_value_factor = 1.0;

    PerlinNoise() = default;

    // new factory (XoroshiroRandomSource): octave noises from positional hashes
    static PerlinNoise create(Xoroshiro& random, int first_octave, const std::vector<double>& amps) {
        PerlinNoise n;
        n.init_factors(first_octave, amps);
        PositionalFactory pf = fork_positional(random);
        for (size_t l = 0; l < amps.size(); l++) {
            if (amps[l] != 0.0) {
                int octave = first_octave + (int)l;
                Xoroshiro r = pf.from_hash_of("octave_" + std::to_string(octave));
                n.levels[l] = std::make_unique<ImprovedNoise>(r);
            }
        }
        return n;
    }

    // legacy initialisation (PerlinNoise(..., useNewFactory=false))
    template <class R>
    static PerlinNoise create_legacy(R& random, int first_octave, const std::vector<double>& amps) {
        PerlinNoise n;
        n.init_factors(first_octave, amps);
        int j = (int)amps.size();
        int k = -first_octave;
        auto first = std::make_unique<ImprovedNoise>(random);
        if (k >= 0 && k < j && amps[k] != 0.0) n.levels[k] = std::move(first);
        for (int l = k - 1; l >= 0; --l) {
            if (l < j && amps[l] != 0.0) n.levels[l] = std::make_unique<ImprovedNoise>(random);
            else random.consume(262);
        }
        return n;
    }

    void init_factors(int first, const std::vector<double>& amps) {
        first_octave = first;
        amplitudes = amps;
        levels.clear();
        levels.resize(amps.size());
        int j = (int)amps.size();
        lowest_freq_input_factor = std::pow(2.0, (double)first);
        lowest_freq_value_factor = std::pow(2.0, (double)(j - 1)) / (std::pow(2.0, (double)j) - 1.0);
    }

    const ImprovedNoise* octave(int i) const { return levels[levels.size() - 1 - i].get(); }

    double value(double x, double y, double z) const {
        double d = 0.0, e = lowest_freq_input_factor, f = lowest_freq_value_factor;
        for (size_t l = 0; l < levels.size(); l++) {
            const ImprovedNoise* n = levels[l].get();
            if (n) {
                double g = n->noise(perlin_wrap(x * e), perlin_wrap(y * e), perlin_wrap(z * e), 0.0, 0.0);
                d += amplitudes[l] * g * f;
            }
            e *= 2.0;
            f /= 2.0;
        }
        return d;
    }
};

// ---------------- NormalNoise ----------------
struct NormalNoise {
    PerlinNoise first, second;
    double value_factor = 0.0;

    static NormalNoise create(Xoroshiro random, int first_octave, const std::vector<double>& amps) {
        NormalNoise n;
        n.first = PerlinNoise::create(random, first_octave, amps);
        n.second = PerlinNoise::create(random, first_octave, amps);
        int lo = 1 << 30, hi = -(1 << 30);
        for (size_t i = 0; i < amps.size(); i++) {
            if (amps[i] != 0.0) {
                lo = std::min(lo, (int)i);
                hi = std::max(hi, (int)i);
            }
        }
        double expected = 0.1 * (1.0 + 1.0 / (double)(hi - lo + 1));
        n.value_factor = 0.16666666666666666 / expected;
        return n;
    }

    double value(double x, double y, double z) const {
        double d = x * 1.0181268882175227, e = y * 1.0181268882175227, f = z * 1.0181268882175227;
        return (first.value(x, y, z) + second.value(d, e, f)) * value_factor;
    }
};

// ---------------- BlendedNoise ----------------
struct BlendedNoise {
    PerlinNoise min_limit, max_limit, main;
    double xz_scale, y_scale, xz_factor, y_factor, smear;
    double xz_multiplier, y_multiplier;

    BlendedNoise(Xoroshiro& random, double xz, double y, double xzf, double yf, double sm, bool deepslate_compat = false)
        : xz_scale(xz), y_scale(y), xz_factor(xzf), y_factor(yf), smear(sm) {
        if (deepslate_compat) {
            // Only for cross-checking against deepslate, which uses the new
            // octave factory and truncated octave lists here.
            std::vector<double> lim = {1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0};
            std::vector<double> mn = {1, 1, 1, 1, 1, 0, 0, 0};
            min_limit = PerlinNoise::create(random, -15, lim);
            max_limit = PerlinNoise::create(random, -15, lim);
            main = PerlinNoise::create(random, -7, mn);
        } else {
            std::vector<double> lim(16, 1.0), mn(8, 1.0);
            min_limit = PerlinNoise::create_legacy(random, -15, lim);
            max_limit = PerlinNoise::create_legacy(random, -15, lim);
            main = PerlinNoise::create_legacy(random, -7, mn);
        }
        xz_multiplier = 684.412 * xz_scale;
        y_multiplier = 684.412 * y_scale;
    }

    double compute(int bx, int by, int bz) const {
        double d = (double)bx * xz_multiplier, e = (double)by * y_multiplier, f = (double)bz * xz_multiplier;
        double g = d / xz_factor, h = e / y_factor, l = f / xz_factor;
        double m = y_multiplier * smear, n = m / y_factor;
        double o = 0.0, p = 0.0, q = 0.0, r = 1.0;
        for (int s = 0; s < 8; s++) {
            const ImprovedNoise* noise = main.octave(s);
            if (noise) q += noise->noise(perlin_wrap(g * r), perlin_wrap(h * r), perlin_wrap(l * r), n * r, h * r) / r;
            r /= 2.0;
        }
        double t = (q / 10.0 + 1.0) / 2.0;
        bool bl2 = t >= 1.0, bl3 = t <= 0.0;
        r = 1.0;
        for (int u = 0; u < 16; u++) {
            double v = perlin_wrap(d * r), w = perlin_wrap(e * r), x = perlin_wrap(f * r), y = m * r;
            if (!bl2) {
                const ImprovedNoise* noise = min_limit.octave(u);
                if (noise) o += noise->noise(v, w, x, y, e * r) / r;
            }
            if (!bl3) {
                const ImprovedNoise* noise = max_limit.octave(u);
                if (noise) p += noise->noise(v, w, x, y, e * r) / r;
            }
            r /= 2.0;
        }
        return clamped_lerp(o / 512.0, p / 512.0, t) / 128.0;
    }
};

// ---------------- SimplexNoise (2D, used by biome temperature noise) ----------------
struct SimplexNoise {
    int p[512];
    double xo, yo, zo;
    static constexpr double SQRT3 = 1.7320508075688772;

    template <class R>
    explicit SimplexNoise(R& random) {
        xo = random.next_double() * 256.0;
        yo = random.next_double() * 256.0;
        zo = random.next_double() * 256.0;
        for (int i = 0; i < 256; i++) p[i] = i;
        for (int i = 0; i < 256; i++) {
            int j = random.next_int(256 - i);
            int k = p[i];
            p[i] = p[j + i];
            p[j + i] = k;
        }
    }
    int P(int i) const { return p[i & 0xFF]; }
    static double corner(int i, double d, double e, double f, double g) {
        double h = g - d * d - e * e - f * f;
        if (h < 0.0) return 0.0;
        h *= h;
        return h * h * grad_dot(i, d, e, f);
    }
    double value2(double d, double e) const {
        const double F2 = 0.5 * (SQRT3 - 1.0);
        const double G2 = (3.0 - SQRT3) / 6.0;
        double f = (d + e) * F2;
        int i = floor_int(d + f), j = floor_int(e + f);
        double g = (double)(i + j) * G2;
        double h = (double)i - g, k = (double)j - g;
        double l = d - h, m = e - k;
        int n, o;
        if (l > m) { n = 1; o = 0; } else { n = 0; o = 1; }
        double q = l - (double)n + G2, r = m - (double)o + G2;
        double s = l - 1.0 + 2.0 * G2, t = m - 1.0 + 2.0 * G2;
        int u = i & 0xFF, v = j & 0xFF;
        int w = P(u + P(v)) % 12, x = P(u + n + P(v + o)) % 12, y = P(u + 1 + P(v + 1)) % 12;
        return 70.0 * (corner(w, l, m, 0.0, 0.5) + corner(x, q, r, 0.0, 0.5) + corner(y, s, t, 0.0, 0.5));
    }
};

struct PerlinSimplexNoise {
    std::vector<std::unique_ptr<SimplexNoise>> levels;
    double input_factor = 1.0, value_factor = 1.0;

    PerlinSimplexNoise(LegacyRandom& random, const std::vector<int>& octaves) {
        int i = -octaves.front(), j = octaves.back(), k = i + j + 1;
        auto has = [&](int o) { for (int v : octaves) if (v == o) return true; return false; };
        auto first = std::make_unique<SimplexNoise>(random);
        levels.resize(k);
        int l = j;
        if (l >= 0 && l < k && has(0)) levels[l] = std::move(first);
        for (int m = l + 1; m < k; m++) {
            if (m >= 0 && has(l - m)) levels[m] = std::make_unique<SimplexNoise>(random);
            else random.consume(262);
        }
        input_factor = std::pow(2.0, (double)j);
        value_factor = 1.0 / (std::pow(2.0, (double)k) - 1.0);
    }
    double value(double d, double e, bool offsets) const {
        double f = 0.0, g = input_factor, h = value_factor;
        for (auto& s : levels) {
            if (s) f += s->value2(d * g + (offsets ? s->xo : 0.0), e * g + (offsets ? s->yo : 0.0)) * h;
            g /= 2.0;
            h *= 2.0;
        }
        return f;
    }
};

}  // namespace vgen
