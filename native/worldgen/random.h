// ============================================================
// PyMC - Vanilla random sources (Minecraft Java 1.21.1)
//
// Bit-exact ports of the random number generators used by world
// generation: Xoroshiro128++ (XoroshiroRandomSource and its positional
// factory), the MD5 based "seedFromHashOf" key derivation, and the
// java.util.Random LCG (LegacyRandomSource / WorldgenRandom).
// ============================================================
#pragma once

#include <cstdint>
#include <cstring>
#include <string>
#include <string_view>

namespace vgen {

static constexpr uint64_t GOLDEN_RATIO_64 = 0x9E3779B97F4A7C15ULL;
static constexpr uint64_t SILVER_RATIO_64 = 0x6A09E667F3BCC909ULL;

inline uint64_t rotl64(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }

inline uint64_t mix_stafford13(uint64_t z) {
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

struct Seed128 { uint64_t lo, hi; };

inline Seed128 upgrade_seed_to_128(int64_t seed) {
    uint64_t lo = (uint64_t)seed ^ SILVER_RATIO_64;
    uint64_t hi = lo + GOLDEN_RATIO_64;
    return {mix_stafford13(lo), mix_stafford13(hi)};
}

// ---------------- MD5 (RFC 1321) ----------------
inline void md5(const uint8_t* msg, size_t len, uint8_t out[16]) {
    static const uint32_t K[64] = {
        0xd76aa478,0xe8c7b756,0x242070db,0xc1bdceee,0xf57c0faf,0x4787c62a,0xa8304613,0xfd469501,
        0x698098d8,0x8b44f7af,0xffff5bb1,0x895cd7be,0x6b901122,0xfd987193,0xa679438e,0x49b40821,
        0xf61e2562,0xc040b340,0x265e5a51,0xe9b6c7aa,0xd62f105d,0x02441453,0xd8a1e681,0xe7d3fbc8,
        0x21e1cde6,0xc33707d6,0xf4d50d87,0x455a14ed,0xa9e3e905,0xfcefa3f8,0x676f02d9,0x8d2a4c8a,
        0xfffa3942,0x8771f681,0x6d9d6122,0xfde5380c,0xa4beea44,0x4bdecfa9,0xf6bb4b60,0xbebfbc70,
        0x289b7ec6,0xeaa127fa,0xd4ef3085,0x04881d05,0xd9d4d039,0xe6db99e5,0x1fa27cf8,0xc4ac5665,
        0xf4292244,0x432aff97,0xab9423a7,0xfc93a039,0x655b59c3,0x8f0ccc92,0xffeff47d,0x85845dd1,
        0x6fa87e4f,0xfe2ce6e0,0xa3014314,0x4e0811a1,0xf7537e82,0xbd3af235,0x2ad7d2bb,0xeb86d391};
    static const int R[64] = {7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
                              4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21};
    uint32_t h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476;
    size_t padded = ((len + 8) / 64 + 1) * 64;
    std::string buf((const char*)msg, len);
    buf.push_back((char)0x80);
    buf.resize(padded - 8, 0);
    uint64_t bits = (uint64_t)len * 8;
    for (int i = 0; i < 8; i++) buf.push_back((char)((bits >> (8 * i)) & 0xFF));
    for (size_t off = 0; off < padded; off += 64) {
        uint32_t w[16];
        for (int i = 0; i < 16; i++) {
            const uint8_t* p = (const uint8_t*)buf.data() + off + i * 4;
            w[i] = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
        }
        uint32_t a = h0, b = h1, c = h2, d = h3;
        for (int i = 0; i < 64; i++) {
            uint32_t f; int g;
            if (i < 16) { f = (b & c) | (~b & d); g = i; }
            else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16; }
            else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16; }
            else { f = c ^ (b | ~d); g = (7 * i) % 16; }
            uint32_t tmp = d; d = c; c = b;
            uint32_t x = a + f + K[i] + w[g];
            b = b + ((x << R[i]) | (x >> (32 - R[i])));
            a = tmp;
        }
        h0 += a; h1 += b; h2 += c; h3 += d;
    }
    uint32_t hs[4] = {h0, h1, h2, h3};
    for (int i = 0; i < 4; i++) for (int j = 0; j < 4; j++) out[i * 4 + j] = (uint8_t)((hs[i] >> (8 * j)) & 0xFF);
}

// RandomSupport.seedFromHashOf: MD5 of the UTF-8 string, two big-endian longs.
inline Seed128 seed_from_hash_of(std::string_view s) {
    uint8_t d[16];
    md5((const uint8_t*)s.data(), s.size(), d);
    uint64_t lo = 0, hi = 0;
    for (int i = 0; i < 8; i++) lo = (lo << 8) | d[i];
    for (int i = 8; i < 16; i++) hi = (hi << 8) | d[i];
    return {lo, hi};
}

// ---------------- Xoroshiro128++ ----------------
struct Xoroshiro {
    uint64_t lo, hi;

    Xoroshiro(uint64_t l, uint64_t h) : lo(l), hi(h) {
        if ((lo | hi) == 0) { lo = GOLDEN_RATIO_64; hi = SILVER_RATIO_64; }
    }
    explicit Xoroshiro(int64_t seed) : Xoroshiro(upgrade_seed_to_128(seed).lo, upgrade_seed_to_128(seed).hi) {}

    uint64_t next_long() {
        uint64_t l = lo, m = hi;
        uint64_t n = rotl64(l + m, 17) + l;
        m ^= l;
        lo = rotl64(l, 49) ^ m ^ (m << 21);
        hi = rotl64(m, 28);
        return n;
    }
    int32_t next_int() { return (int32_t)next_long(); }
    int32_t next_int(int32_t bound) {
        uint64_t l = (uint64_t)(uint32_t)next_int();
        uint64_t m = l * (uint64_t)(int64_t)bound;
        uint64_t n = m & 0xFFFFFFFFULL;
        if (n < (uint64_t)bound) {
            uint32_t j = (uint32_t)(~bound + 1) % (uint32_t)bound;
            while (n < j) {
                l = (uint64_t)(uint32_t)next_int();
                m = l * (uint64_t)(int64_t)bound;
                n = m & 0xFFFFFFFFULL;
            }
        }
        return (int32_t)(int64_t)(m >> 32);
    }
    int32_t next_int_between_inclusive(int32_t a, int32_t b) { return next_int(b - a + 1) + a; }
    uint64_t next_bits(int bits) { return next_long() >> (64 - bits); }
    double next_double() { return (double)next_bits(53) * 1.1102230246251565E-16; }
    float next_float() { return (float)next_bits(24) * 5.9604645E-8f; }
    bool next_boolean() { return (next_long() & 1ULL) != 0; }
    void consume(int n) { for (int i = 0; i < n; i++) next_long(); }
};

// Mth.getSeed(x, y, z)
inline int64_t position_seed(int32_t x, int32_t y, int32_t z) {
    int64_t l = (int64_t)(int32_t)((uint32_t)x * 3129871u) ^ ((int64_t)z * 116129781LL) ^ (int64_t)y;
    l = (int64_t)((uint64_t)l * (uint64_t)l * 42317861ULL + (uint64_t)l * 11ULL);
    return l >> 16;
}

struct PositionalFactory {
    uint64_t lo = 0, hi = 0;
    PositionalFactory() = default;
    PositionalFactory(uint64_t l, uint64_t h) : lo(l), hi(h) {}

    Xoroshiro at(int32_t x, int32_t y, int32_t z) const {
        return Xoroshiro((uint64_t)position_seed(x, y, z) ^ lo, hi);
    }
    Xoroshiro from_hash_of(std::string_view key) const {
        Seed128 s = seed_from_hash_of(key);
        return Xoroshiro(s.lo ^ lo, s.hi ^ hi);
    }
};

inline PositionalFactory fork_positional(Xoroshiro& r) {
    uint64_t a = r.next_long();
    uint64_t b = r.next_long();
    return PositionalFactory(a, b);
}

// ---------------- java.util.Random (LegacyRandomSource) ----------------
struct LegacyRandom {
    int64_t seed;
    explicit LegacyRandom(int64_t s) { set_seed(s); }
    void set_seed(int64_t s) { seed = (s ^ 0x5DEECE66DLL) & ((1LL << 48) - 1); }
    int32_t next(int bits) {
        seed = (int64_t)(((uint64_t)seed * 0x5DEECE66DULL + 0xBULL) & ((1ULL << 48) - 1));
        return (int32_t)(seed >> (48 - bits));
    }
    int32_t next_int() { return next(32); }
    int32_t next_int(int32_t bound) {
        if ((bound & -bound) == bound) return (int32_t)(((int64_t)bound * (int64_t)next(31)) >> 31);
        int32_t j, k;
        do { j = next(31); k = j % bound; } while (j - k + (bound - 1) < 0);
        return k;
    }
    int64_t next_long() { return ((int64_t)next(32) << 32) + (int64_t)next(32); }
    double next_double() {
        int64_t l = ((int64_t)next(26) << 27) + (int64_t)next(27);
        return (double)l * 1.1102230246251565E-16;
    }
    float next_float() { return (float)next(24) * 5.9604645E-8f; }
    bool next_boolean() { return next(1) != 0; }
    void consume(int n) { for (int i = 0; i < n; i++) next_int(); }
};

}  // namespace vgen
