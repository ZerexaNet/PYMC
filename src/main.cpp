#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace worldgen {

constexpr uint64_t kGoldenRatio64 = 0x9E3779B97F4A7C15ULL;
constexpr uint64_t kSilverRatio64 = 0x6A09E667F3BCC909ULL;
constexpr uint32_t kProtocolMagic = 0x4E475752U;  // "RWGN" little-endian
constexpr uint16_t kProtocolVersion = 1;

constexpr uint16_t kReqInit = 1;
constexpr uint16_t kReqSampleColumn = 2;
constexpr uint16_t kReqSampleRegion = 3;
constexpr uint16_t kReqPing = 4;
constexpr uint16_t kReqShutdown = 5;

constexpr uint16_t kRespFlag = 0x8000U;
constexpr uint16_t kRespError = 0xFFFFU;

inline uint64_t mixStafford13(uint64_t x) {
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

inline std::pair<uint64_t, uint64_t> upgradeSeedTo128(uint64_t seed) {
    uint64_t lo = seed ^ kSilverRatio64;
    uint64_t hi = lo + kGoldenRatio64;
    return {mixStafford13(lo), mixStafford13(hi)};
}

inline uint64_t fnv1a64(std::string_view s, uint64_t basis) {
    constexpr uint64_t prime = 1099511628211ULL;
    uint64_t h = basis;
    for (unsigned char c : s) {
        h ^= static_cast<uint64_t>(c);
        h *= prime;
    }
    return h;
}

class Xoroshiro128PlusPlus {
public:
    Xoroshiro128PlusPlus(uint64_t seedLo, uint64_t seedHi)
        : seedLo_(seedLo), seedHi_(seedHi) {
        if ((seedLo_ | seedHi_) == 0ULL) {
            seedLo_ = kGoldenRatio64;
            seedHi_ = kSilverRatio64;
        }
    }

    uint64_t nextU64() {
        const uint64_t s0 = seedLo_;
        uint64_t s1 = seedHi_;
        const uint64_t out = std::rotl(s0 + s1, 17) + s0;
        s1 ^= s0;
        seedLo_ = std::rotl(s0, 49) ^ s1 ^ (s1 << 21);
        seedHi_ = std::rotl(s1, 28);
        return out;
    }

    int nextInt(int bound) {
        if (bound <= 0) {
            return 0;
        }
        uint64_t u = static_cast<uint32_t>(nextU64());
        uint64_t m = u * static_cast<uint64_t>(bound);
        uint64_t l = m & 0xFFFFFFFFULL;
        if (l < static_cast<uint64_t>(bound)) {
            const uint32_t threshold =
                static_cast<uint32_t>((0U - static_cast<uint32_t>(bound)) %
                                      static_cast<uint32_t>(bound));
            while (l < threshold) {
                u = static_cast<uint32_t>(nextU64());
                m = u * static_cast<uint64_t>(bound);
                l = m & 0xFFFFFFFFULL;
            }
        }
        return static_cast<int>(m >> 32);
    }

    double nextDouble() {
        return static_cast<double>(nextU64() >> 11) *
               (1.0 / 9007199254740992.0);
    }

private:
    uint64_t seedLo_;
    uint64_t seedHi_;
};

class HashRandomFactory {
public:
    explicit HashRandomFactory(int64_t worldSeed) {
        auto [lo, hi] = upgradeSeedTo128(static_cast<uint64_t>(worldSeed));
        seedLo_ = lo;
        seedHi_ = hi;
    }

    HashRandomFactory(uint64_t lo, uint64_t hi) : seedLo_(lo), seedHi_(hi) {}

    HashRandomFactory child(std::string_view key) const {
        auto [h0, h1] = hash2x64(key);
        return HashRandomFactory(seedLo_ ^ h0, seedHi_ ^ h1);
    }

    Xoroshiro128PlusPlus fromHash(std::string_view key) const {
        auto [h0, h1] = hash2x64(key);
        return Xoroshiro128PlusPlus(seedLo_ ^ h0, seedHi_ ^ h1);
    }

private:
    static std::pair<uint64_t, uint64_t> hash2x64(std::string_view key) {
        uint64_t h0 = fnv1a64(key, 1469598103934665603ULL);
        uint64_t h1 = fnv1a64(key, 7809847782465536322ULL);
        h0 = mixStafford13(h0);
        h1 = mixStafford13(h1 ^ (h0 + kGoldenRatio64));
        return {h0, h1};
    }

    uint64_t seedLo_;
    uint64_t seedHi_;
};

inline int fastFloor(double v) {
    int i = static_cast<int>(v);
    return (v < static_cast<double>(i)) ? (i - 1) : i;
}

inline double smoothstep(double t) {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

inline double lerp(double t, double a, double b) { return a + t * (b - a); }

inline double clampedLerp(double a, double b, double t) {
    if (t < 0.0) {
        return a;
    }
    if (t > 1.0) {
        return b;
    }
    return lerp(t, a, b);
}

class ImprovedNoise {
public:
    explicit ImprovedNoise(Xoroshiro128PlusPlus& rng) {
        xo_ = rng.nextDouble() * 256.0;
        yo_ = rng.nextDouble() * 256.0;
        zo_ = rng.nextDouble() * 256.0;
        for (int i = 0; i < 256; ++i) {
            p_[i] = static_cast<uint8_t>(i);
        }
        for (int i = 0; i < 256; ++i) {
            int j = i + rng.nextInt(256 - i);
            std::swap(p_[i], p_[j]);
        }
    }

    double noise(double x, double y, double z) const {
        return noise(x, y, z, 0.0, 0.0);
    }

    double noise(double x, double y, double z, double yScale, double yMax) const {
        const double xs = x + xo_;
        const double ys = y + yo_;
        const double zs = z + zo_;

        const int xFloor = fastFloor(xs);
        const int yFloor = fastFloor(ys);
        const int zFloor = fastFloor(zs);

        const double xFrac = xs - static_cast<double>(xFloor);
        double yFrac = ys - static_cast<double>(yFloor);
        const double zFrac = zs - static_cast<double>(zFloor);

        double yQuantizedOffset = 0.0;
        if (yScale != 0.0) {
            double yAnchor = yFrac;
            if (yMax >= 0.0 && yMax < yFrac) {
                yAnchor = yMax;
            }
            yQuantizedOffset = std::floor(yAnchor / yScale + 1.0e-7) * yScale;
        }

        yFrac -= yQuantizedOffset;
        return sampleAndLerp(xFloor, yFloor, zFloor, xFrac, yFrac, zFrac, ys - static_cast<double>(yFloor));
    }

private:
    static constexpr std::array<std::array<int, 3>, 16> kGradient = {{
        {{1, 1, 0}},  {{-1, 1, 0}}, {{1, -1, 0}},  {{-1, -1, 0}},
        {{1, 0, 1}},  {{-1, 0, 1}}, {{1, 0, -1}},  {{-1, 0, -1}},
        {{0, 1, 1}},  {{0, -1, 1}}, {{0, 1, -1}},  {{0, -1, -1}},
        {{1, 1, 0}},  {{0, -1, 1}}, {{-1, 1, 0}},  {{0, -1, -1}},
    }};

    int p(int idx) const { return static_cast<int>(p_[idx & 0xFF]); }

    static double gradDot(int h, double x, double y, double z) {
        const auto& g = kGradient[h & 0x0F];
        return static_cast<double>(g[0]) * x + static_cast<double>(g[1]) * y +
               static_cast<double>(g[2]) * z;
    }

    double sampleAndLerp(int xFloor,
                         int yFloor,
                         int zFloor,
                         double xFrac,
                         double yFrac,
                         double zFrac,
                         double ySmoothInput) const {
        const int x0 = p(xFloor);
        const int x1 = p(xFloor + 1);
        const int a = p(x0 + yFloor);
        const int b = p(x0 + yFloor + 1);
        const int c = p(x1 + yFloor);
        const int d = p(x1 + yFloor + 1);

        const double n000 = gradDot(p(a + zFloor), xFrac, yFrac, zFrac);
        const double n100 = gradDot(p(c + zFloor), xFrac - 1.0, yFrac, zFrac);
        const double n010 = gradDot(p(b + zFloor), xFrac, yFrac - 1.0, zFrac);
        const double n110 = gradDot(p(d + zFloor), xFrac - 1.0, yFrac - 1.0, zFrac);
        const double n001 = gradDot(p(a + zFloor + 1), xFrac, yFrac, zFrac - 1.0);
        const double n101 = gradDot(p(c + zFloor + 1), xFrac - 1.0, yFrac, zFrac - 1.0);
        const double n011 = gradDot(p(b + zFloor + 1), xFrac, yFrac - 1.0, zFrac - 1.0);
        const double n111 = gradDot(p(d + zFloor + 1), xFrac - 1.0, yFrac - 1.0, zFrac - 1.0);

        const double u = smoothstep(xFrac);
        const double v = smoothstep(ySmoothInput);
        const double w = smoothstep(zFrac);

        const double x00 = lerp(u, n000, n100);
        const double x10 = lerp(u, n010, n110);
        const double x01 = lerp(u, n001, n101);
        const double x11 = lerp(u, n011, n111);
        const double y0 = lerp(v, x00, x10);
        const double y1 = lerp(v, x01, x11);
        return lerp(w, y0, y1);
    }

    std::array<uint8_t, 256> p_{};
    double xo_{0.0};
    double yo_{0.0};
    double zo_{0.0};
};

struct NoiseParameters {
    int firstOctave;
    std::vector<double> amplitudes;
};

class PerlinNoise {
public:
    PerlinNoise(const HashRandomFactory& seedFactory,
                int firstOctave,
                const std::vector<double>& amplitudes,
                std::string_view label)
        : firstOctave_(firstOctave), amplitudes_(amplitudes) {
        const int count = static_cast<int>(amplitudes_.size());
        levels_.reserve(count);
        hasLevel_.assign(count, false);
        for (int i = 0; i < count; ++i) {
            levels_.emplace_back(nullptr);
        }

        const HashRandomFactory octaveFactory = seedFactory.child(label);
        for (int i = 0; i < count; ++i) {
            if (amplitudes_[i] == 0.0) {
                continue;
            }
            const int octave = firstOctave_ + i;
            Xoroshiro128PlusPlus rng =
                octaveFactory.fromHash("octave_" + std::to_string(octave));
            levels_[i] = std::make_unique<ImprovedNoise>(rng);
            hasLevel_[i] = true;
        }

        const int octaveShift = -firstOctave_;
        lowestFreqInputFactor_ = std::pow(2.0, -octaveShift);
        lowestFreqValueFactor_ =
            std::pow(2.0, count - 1) / (std::pow(2.0, count) - 1.0);
    }

    double getValue(double x, double y, double z) const {
        double value = 0.0;
        double freq = lowestFreqInputFactor_;
        double amp = lowestFreqValueFactor_;
        for (size_t i = 0; i < levels_.size(); ++i) {
            if (hasLevel_[i]) {
                value += amplitudes_[i] *
                         levels_[i]->noise(wrap(x * freq), wrap(y * freq), wrap(z * freq)) * amp;
            }
            freq *= 2.0;
            amp /= 2.0;
        }
        return value;
    }

    const ImprovedNoise* getOctaveNoise(int octaveFromTop) const {
        const int idx = static_cast<int>(levels_.size()) - 1 - octaveFromTop;
        if (idx < 0 || idx >= static_cast<int>(levels_.size())) {
            return nullptr;
        }
        return hasLevel_[idx] ? levels_[idx].get() : nullptr;
    }

    static double wrap(double v) {
        constexpr double wrapRange = 33554432.0;
        return v - std::floor(v / wrapRange + 0.5) * wrapRange;
    }

private:
    int firstOctave_;
    std::vector<double> amplitudes_;
    std::vector<std::unique_ptr<ImprovedNoise>> levels_;
    std::vector<bool> hasLevel_;
    double lowestFreqInputFactor_{1.0};
    double lowestFreqValueFactor_{1.0};
};

class NormalNoise {
public:
    NormalNoise(const HashRandomFactory& baseFactory,
                std::string_view noiseKey,
                const NoiseParameters& params)
        : first_(baseFactory.child(std::string(noiseKey) + ":a"),
                 params.firstOctave,
                 params.amplitudes,
                 "first"),
          second_(baseFactory.child(std::string(noiseKey) + ":b"),
                  params.firstOctave,
                  params.amplitudes,
                  "second") {
        int minIdx = std::numeric_limits<int>::max();
        int maxIdx = std::numeric_limits<int>::min();
        for (int i = 0; i < static_cast<int>(params.amplitudes.size()); ++i) {
            if (params.amplitudes[i] == 0.0) {
                continue;
            }
            minIdx = std::min(minIdx, i);
            maxIdx = std::max(maxIdx, i);
        }
        if (minIdx == std::numeric_limits<int>::max()) {
            minIdx = 0;
            maxIdx = 0;
        }
        const double expectedDeviation =
            0.1 * (1.0 + 1.0 / static_cast<double>((maxIdx - minIdx) + 1));
        valueFactor_ = (1.0 / 6.0) / expectedDeviation;
    }

    double getValue(double x, double y, double z) const {
        constexpr double inputFactor = 1.0181268882175227;
        const double sx = x * inputFactor;
        const double sy = y * inputFactor;
        const double sz = z * inputFactor;
        return (first_.getValue(x, y, z) + second_.getValue(sx, sy, sz)) * valueFactor_;
    }

private:
    PerlinNoise first_;
    PerlinNoise second_;
    double valueFactor_{1.0};
};

class OctaveNoise5 {
public:
    OctaveNoise5(const HashRandomFactory& factory, std::string_view key) {
        layers_.reserve(5);
        HashRandomFactory sub = factory.child(key);
        for (int i = 0; i < 5; ++i) {
            Xoroshiro128PlusPlus rng =
                sub.fromHash("layer_" + std::to_string(i));
            layers_.emplace_back(rng);
        }
    }

    double noise3D(double x, double y, double z) const {
        double out = 0.0;
        double freq = 1.0;
        double amp = 1.0;
        for (const auto& n : layers_) {
            out += n.noise(x * freq, y * freq, z * freq) * amp;
            freq *= 2.0;
            amp *= 0.5;
        }
        return out;
    }

private:
    std::vector<ImprovedNoise> layers_;
};

enum class BiomeId : int16_t {
    None = 0,
    Plains,
    SunflowerPlains,
    SnowyPlains,
    IceSpikes,
    Desert,
    Swamp,
    MangroveSwamp,
    Forest,
    FlowerForest,
    BirchForest,
    DarkForest,
    OldGrowthBirchForest,
    OldGrowthPineTaiga,
    OldGrowthSpruceTaiga,
    Taiga,
    SnowyTaiga,
    Savanna,
    SavannaPlateau,
    WindsweptHills,
    WindsweptGravellyHills,
    WindsweptForest,
    WindsweptSavanna,
    Jungle,
    SparseJungle,
    BambooJungle,
    Badlands,
    ErodedBadlands,
    WoodedBadlands,
    Meadow,
    CherryGrove,
    Grove,
    SnowySlopes,
    FrozenPeaks,
    JaggedPeaks,
    StonyPeaks,
    River,
    FrozenRiver,
    Beach,
    SnowyBeach,
    StonyShore,
    WarmOcean,
    LukewarmOcean,
    DeepLukewarmOcean,
    Ocean,
    DeepOcean,
    ColdOcean,
    DeepColdOcean,
    FrozenOcean,
    DeepFrozenOcean,
    MushroomFields,
    DripstoneCaves,
    LushCaves,
    DeepDark,
};

const char* biomeName(BiomeId id) {
    switch (id) {
        case BiomeId::Plains:
            return "plains";
        case BiomeId::SunflowerPlains:
            return "sunflower_plains";
        case BiomeId::SnowyPlains:
            return "snowy_plains";
        case BiomeId::IceSpikes:
            return "ice_spikes";
        case BiomeId::Desert:
            return "desert";
        case BiomeId::Swamp:
            return "swamp";
        case BiomeId::MangroveSwamp:
            return "mangrove_swamp";
        case BiomeId::Forest:
            return "forest";
        case BiomeId::FlowerForest:
            return "flower_forest";
        case BiomeId::BirchForest:
            return "birch_forest";
        case BiomeId::DarkForest:
            return "dark_forest";
        case BiomeId::OldGrowthBirchForest:
            return "old_growth_birch_forest";
        case BiomeId::OldGrowthPineTaiga:
            return "old_growth_pine_taiga";
        case BiomeId::OldGrowthSpruceTaiga:
            return "old_growth_spruce_taiga";
        case BiomeId::Taiga:
            return "taiga";
        case BiomeId::SnowyTaiga:
            return "snowy_taiga";
        case BiomeId::Savanna:
            return "savanna";
        case BiomeId::SavannaPlateau:
            return "savanna_plateau";
        case BiomeId::WindsweptHills:
            return "windswept_hills";
        case BiomeId::WindsweptGravellyHills:
            return "windswept_gravelly_hills";
        case BiomeId::WindsweptForest:
            return "windswept_forest";
        case BiomeId::WindsweptSavanna:
            return "windswept_savanna";
        case BiomeId::Jungle:
            return "jungle";
        case BiomeId::SparseJungle:
            return "sparse_jungle";
        case BiomeId::BambooJungle:
            return "bamboo_jungle";
        case BiomeId::Badlands:
            return "badlands";
        case BiomeId::ErodedBadlands:
            return "eroded_badlands";
        case BiomeId::WoodedBadlands:
            return "wooded_badlands";
        case BiomeId::Meadow:
            return "meadow";
        case BiomeId::CherryGrove:
            return "cherry_grove";
        case BiomeId::Grove:
            return "grove";
        case BiomeId::SnowySlopes:
            return "snowy_slopes";
        case BiomeId::FrozenPeaks:
            return "frozen_peaks";
        case BiomeId::JaggedPeaks:
            return "jagged_peaks";
        case BiomeId::StonyPeaks:
            return "stony_peaks";
        case BiomeId::River:
            return "river";
        case BiomeId::FrozenRiver:
            return "frozen_river";
        case BiomeId::Beach:
            return "beach";
        case BiomeId::SnowyBeach:
            return "snowy_beach";
        case BiomeId::StonyShore:
            return "stony_shore";
        case BiomeId::WarmOcean:
            return "warm_ocean";
        case BiomeId::LukewarmOcean:
            return "lukewarm_ocean";
        case BiomeId::DeepLukewarmOcean:
            return "deep_lukewarm_ocean";
        case BiomeId::Ocean:
            return "ocean";
        case BiomeId::DeepOcean:
            return "deep_ocean";
        case BiomeId::ColdOcean:
            return "cold_ocean";
        case BiomeId::DeepColdOcean:
            return "deep_cold_ocean";
        case BiomeId::FrozenOcean:
            return "frozen_ocean";
        case BiomeId::DeepFrozenOcean:
            return "deep_frozen_ocean";
        case BiomeId::MushroomFields:
            return "mushroom_fields";
        case BiomeId::DripstoneCaves:
            return "dripstone_caves";
        case BiomeId::LushCaves:
            return "lush_caves";
        case BiomeId::DeepDark:
            return "deep_dark";
        default:
            return "plains";
    }
}

std::pair<double, double> biomeHeightParams(BiomeId biome) {
    switch (biome) {
        case BiomeId::DeepOcean:
        case BiomeId::DeepColdOcean:
        case BiomeId::DeepFrozenOcean:
        case BiomeId::DeepLukewarmOcean:
            return {-1.8, 0.10};
        case BiomeId::Ocean:
        case BiomeId::ColdOcean:
        case BiomeId::FrozenOcean:
        case BiomeId::LukewarmOcean:
        case BiomeId::WarmOcean:
            return {-1.0, 0.10};
        case BiomeId::Beach:
        case BiomeId::SnowyBeach:
            return {0.0, 0.02};
        case BiomeId::River:
        case BiomeId::FrozenRiver:
            return {-0.35, 0.05};
        case BiomeId::MushroomFields:
            return {0.20, 0.30};
        case BiomeId::Swamp:
        case BiomeId::MangroveSwamp:
            return {-0.20, 0.08};
        case BiomeId::SnowySlopes:
        case BiomeId::FrozenPeaks:
        case BiomeId::JaggedPeaks:
        case BiomeId::StonyPeaks:
            return {1.30, 0.70};
        case BiomeId::Meadow:
        case BiomeId::Grove:
        case BiomeId::CherryGrove:
            return {0.55, 0.30};
        case BiomeId::WindsweptHills:
        case BiomeId::WindsweptForest:
        case BiomeId::WindsweptGravellyHills:
        case BiomeId::WindsweptSavanna:
            return {1.00, 0.50};
        case BiomeId::Badlands:
        case BiomeId::ErodedBadlands:
        case BiomeId::WoodedBadlands:
            return {0.30, 0.20};
        case BiomeId::SavannaPlateau:
            return {0.35, 0.20};
        case BiomeId::Desert:
        case BiomeId::Plains:
        case BiomeId::SunflowerPlains:
        case BiomeId::SnowyPlains:
            return {0.125, 0.05};
        case BiomeId::Forest:
        case BiomeId::FlowerForest:
        case BiomeId::BirchForest:
        case BiomeId::DarkForest:
        case BiomeId::Jungle:
        case BiomeId::SparseJungle:
        case BiomeId::BambooJungle:
            return {0.10, 0.20};
        case BiomeId::Taiga:
        case BiomeId::SnowyTaiga:
        case BiomeId::OldGrowthBirchForest:
        case BiomeId::OldGrowthPineTaiga:
        case BiomeId::OldGrowthSpruceTaiga:
            return {0.20, 0.20};
        case BiomeId::IceSpikes:
            return {0.45, 0.50};
        default:
            return {0.125, 0.05};
    }
}

struct ClimateRange {
    float min;
    float max;
};

ClimateRange span(float a, float b) {
    return (a <= b) ? ClimateRange{a, b} : ClimateRange{b, a};
}

ClimateRange span(const ClimateRange& a, const ClimateRange& b) {
    return {std::min(a.min, b.min), std::max(a.max, b.max)};
}

ClimateRange point(float v) { return {v, v}; }

struct ClimatePoint {
    ClimateRange temperature;
    ClimateRange humidity;
    ClimateRange continentalness;
    ClimateRange erosion;
    ClimateRange depth;
    ClimateRange weirdness;
    float offset;
    BiomeId biome;
};

inline float rangeDistance(const ClimateRange& r, float value) {
    if (value < r.min) {
        return r.min - value;
    }
    if (value > r.max) {
        return value - r.max;
    }
    return 0.0f;
}

class OverworldBiomeTable {
public:
    OverworldBiomeTable() {
        initRanges();
        initBiomeTables();
        points_.reserve(8192);
        addBiomes();
    }

    BiomeId resolve(float temperature,
                    float humidity,
                    float continentalness,
                    float erosion,
                    float depth,
                    float weirdness) const {
        float best = std::numeric_limits<float>::infinity();
        BiomeId result = BiomeId::Plains;
        for (const auto& p : points_) {
            float d = 0.0f;
            d += square(rangeDistance(p.temperature, temperature));
            d += square(rangeDistance(p.humidity, humidity));
            d += square(rangeDistance(p.continentalness, continentalness));
            d += square(rangeDistance(p.erosion, erosion));
            d += square(rangeDistance(p.depth, depth));
            d += square(rangeDistance(p.weirdness, weirdness));
            d += square(p.offset);
            if (d < best) {
                best = d;
                result = p.biome;
            }
        }
        return result;
    }

private:
    static float square(float v) { return v * v; }

    void initRanges() {
        fullRange_ = span(-1.0f, 1.0f);
        temperatures_ = {
            span(-1.0f, -0.45f),
            span(-0.45f, -0.15f),
            span(-0.15f, 0.2f),
            span(0.2f, 0.55f),
            span(0.55f, 1.0f),
        };
        humidities_ = {
            span(-1.0f, -0.35f),
            span(-0.35f, -0.1f),
            span(-0.1f, 0.1f),
            span(0.1f, 0.3f),
            span(0.3f, 1.0f),
        };
        erosions_ = {
            span(-1.0f, -0.78f),
            span(-0.78f, -0.375f),
            span(-0.375f, -0.2225f),
            span(-0.2225f, 0.05f),
            span(0.05f, 0.45f),
            span(0.45f, 0.55f),
            span(0.55f, 1.0f),
        };
        frozenRange_ = temperatures_[0];
        unfrozenRange_ = span(temperatures_[1], temperatures_[4]);
        mushroomFieldsContinentalness_ = span(-1.2f, -1.05f);
        deepOceanContinentalness_ = span(-1.05f, -0.455f);
        oceanContinentalness_ = span(-0.455f, -0.19f);
        coastContinentalness_ = span(-0.19f, -0.11f);
        inlandContinentalness_ = span(-0.11f, 0.55f);
        nearInlandContinentalness_ = span(-0.11f, 0.03f);
        midInlandContinentalness_ = span(0.03f, 0.3f);
        farInlandContinentalness_ = span(0.3f, 1.0f);
    }

    void initBiomeTables() {
        oceans_ = {{
            {BiomeId::DeepFrozenOcean, BiomeId::DeepColdOcean, BiomeId::DeepOcean,
             BiomeId::DeepLukewarmOcean, BiomeId::WarmOcean},
            {BiomeId::FrozenOcean, BiomeId::ColdOcean, BiomeId::Ocean,
             BiomeId::LukewarmOcean, BiomeId::WarmOcean},
        }};

        middleBiomes_ = {{
            {BiomeId::SnowyPlains, BiomeId::SnowyPlains, BiomeId::SnowyPlains,
             BiomeId::SnowyTaiga, BiomeId::Taiga},
            {BiomeId::Plains, BiomeId::Plains, BiomeId::Forest, BiomeId::Taiga,
             BiomeId::OldGrowthSpruceTaiga},
            {BiomeId::FlowerForest, BiomeId::Plains, BiomeId::Forest,
             BiomeId::BirchForest, BiomeId::DarkForest},
            {BiomeId::Savanna, BiomeId::Savanna, BiomeId::Forest, BiomeId::Jungle,
             BiomeId::Jungle},
            {BiomeId::Desert, BiomeId::Desert, BiomeId::Desert, BiomeId::Desert,
             BiomeId::Desert},
        }};

        middleBiomesVariant_ = {{
            {BiomeId::IceSpikes, BiomeId::None, BiomeId::SnowyTaiga, BiomeId::None,
             BiomeId::None},
            {BiomeId::None, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::OldGrowthPineTaiga},
            {BiomeId::SunflowerPlains, BiomeId::None, BiomeId::None,
             BiomeId::OldGrowthBirchForest, BiomeId::None},
            {BiomeId::None, BiomeId::None, BiomeId::Plains, BiomeId::SparseJungle,
             BiomeId::BambooJungle},
            {BiomeId::None, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::None},
        }};

        plateauBiomes_ = {{
            {BiomeId::SnowyPlains, BiomeId::SnowyPlains, BiomeId::SnowyPlains,
             BiomeId::SnowyTaiga, BiomeId::SnowyTaiga},
            {BiomeId::Meadow, BiomeId::Meadow, BiomeId::Forest, BiomeId::Taiga,
             BiomeId::OldGrowthSpruceTaiga},
            {BiomeId::Meadow, BiomeId::Meadow, BiomeId::Meadow, BiomeId::Meadow,
             BiomeId::DarkForest},
            {BiomeId::SavannaPlateau, BiomeId::SavannaPlateau, BiomeId::Forest,
             BiomeId::Forest, BiomeId::Jungle},
            {BiomeId::Badlands, BiomeId::Badlands, BiomeId::Badlands,
             BiomeId::WoodedBadlands, BiomeId::WoodedBadlands},
        }};

        plateauBiomesVariant_ = {{
            {BiomeId::IceSpikes, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::None},
            {BiomeId::CherryGrove, BiomeId::None, BiomeId::Meadow, BiomeId::Meadow,
             BiomeId::OldGrowthPineTaiga},
            {BiomeId::CherryGrove, BiomeId::CherryGrove, BiomeId::Forest,
             BiomeId::BirchForest, BiomeId::None},
            {BiomeId::None, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::None},
            {BiomeId::ErodedBadlands, BiomeId::ErodedBadlands, BiomeId::None,
             BiomeId::None, BiomeId::None},
        }};

        shatteredBiomes_ = {{
            {BiomeId::WindsweptGravellyHills, BiomeId::WindsweptGravellyHills,
             BiomeId::WindsweptHills, BiomeId::WindsweptForest,
             BiomeId::WindsweptForest},
            {BiomeId::WindsweptGravellyHills, BiomeId::WindsweptGravellyHills,
             BiomeId::WindsweptHills, BiomeId::WindsweptForest,
             BiomeId::WindsweptForest},
            {BiomeId::WindsweptHills, BiomeId::WindsweptHills, BiomeId::WindsweptHills,
             BiomeId::WindsweptForest, BiomeId::WindsweptForest},
            {BiomeId::None, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::None},
            {BiomeId::None, BiomeId::None, BiomeId::None, BiomeId::None,
             BiomeId::None},
        }};
    }

    void addBiomes() {
        addOffCoastBiomes();
        addInlandBiomes();
        addUndergroundBiomes();
    }

    void addOffCoastBiomes() {
        addSurfaceBiome(fullRange_,
                       fullRange_,
                       mushroomFieldsContinentalness_,
                       fullRange_,
                       fullRange_,
                       0.0f,
                       BiomeId::MushroomFields);
        for (int i = 0; i < 5; ++i) {
            const ClimateRange t = temperatures_[i];
            addSurfaceBiome(t,
                           fullRange_,
                           deepOceanContinentalness_,
                           fullRange_,
                           fullRange_,
                           0.0f,
                           oceans_[0][i]);
            addSurfaceBiome(t,
                           fullRange_,
                           oceanContinentalness_,
                           fullRange_,
                           fullRange_,
                           0.0f,
                           oceans_[1][i]);
        }
    }

    void addInlandBiomes() {
        addMidSlice(span(-1.0f, -0.93333334f));
        addHighSlice(span(-0.93333334f, -0.7666667f));
        addPeaks(span(-0.7666667f, -0.56666666f));
        addHighSlice(span(-0.56666666f, -0.4f));
        addMidSlice(span(-0.4f, -0.26666668f));
        addLowSlice(span(-0.26666668f, -0.05f));
        addValleys(span(-0.05f, 0.05f));
        addLowSlice(span(0.05f, 0.26666668f));
        addMidSlice(span(0.26666668f, 0.4f));
        addHighSlice(span(0.4f, 0.56666666f));
        addPeaks(span(0.56666666f, 0.7666667f));
        addHighSlice(span(0.7666667f, 0.93333334f));
        addMidSlice(span(0.93333334f, 1.0f));
    }

    void addPeaks(const ClimateRange& weird) {
        for (int ti = 0; ti < 5; ++ti) {
            const ClimateRange t = temperatures_[ti];
            for (int hi = 0; hi < 5; ++hi) {
                const ClimateRange h = humidities_[hi];
                const BiomeId middle = pickMiddleBiome(ti, hi, weird);
                const BiomeId middleOrBadlands = pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
                const BiomeId middleOrBadlandsOrSlope =
                    pickMiddleBiomeOrBadlandsIfHotOrSlopeIfCold(ti, hi, weird);
                const BiomeId plateau = pickPlateauBiome(ti, hi, weird);
                const BiomeId shattered = pickShatteredBiome(ti, hi, weird);
                const BiomeId windsweptSavanna =
                    maybePickWindsweptSavannaBiome(ti, hi, weird, shattered);
                const BiomeId peak = pickPeakBiome(ti, hi, weird);

                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, farInlandContinentalness_),
                               erosions_[0],
                               weird,
                               0.0f,
                               peak);
                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, nearInlandContinentalness_),
                               erosions_[1],
                               weird,
                               0.0f,
                               middleOrBadlandsOrSlope);
                addSurfaceBiome(t,
                               h,
                               span(midInlandContinentalness_, farInlandContinentalness_),
                               erosions_[1],
                               weird,
                               0.0f,
                               peak);
                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, nearInlandContinentalness_),
                               span(erosions_[2], erosions_[3]),
                               weird,
                               0.0f,
                               middle);
                addSurfaceBiome(t,
                               h,
                               span(midInlandContinentalness_, farInlandContinentalness_),
                               erosions_[2],
                               weird,
                               0.0f,
                               plateau);
                addSurfaceBiome(t,
                               h,
                               midInlandContinentalness_,
                               erosions_[3],
                               weird,
                               0.0f,
                               middleOrBadlands);
                addSurfaceBiome(t,
                               h,
                               farInlandContinentalness_,
                               erosions_[3],
                               weird,
                               0.0f,
                               plateau);
                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, farInlandContinentalness_),
                               erosions_[4],
                               weird,
                               0.0f,
                               middle);
                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, nearInlandContinentalness_),
                               erosions_[5],
                               weird,
                               0.0f,
                               windsweptSavanna);
                addSurfaceBiome(t,
                               h,
                               span(midInlandContinentalness_, farInlandContinentalness_),
                               erosions_[5],
                               weird,
                               0.0f,
                               shattered);
                addSurfaceBiome(t,
                               h,
                               span(coastContinentalness_, farInlandContinentalness_),
                               erosions_[6],
                               weird,
                               0.0f,
                               middle);
            }
        }
    }

    void addHighSlice(const ClimateRange& weird) {
        for (int ti = 0; ti < 5; ++ti) {
            const ClimateRange t = temperatures_[ti];
            for (int hi = 0; hi < 5; ++hi) {
                const ClimateRange h = humidities_[hi];
                const BiomeId middle = pickMiddleBiome(ti, hi, weird);
                const BiomeId middleOrBadlands = pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
                const BiomeId middleOrBadlandsOrSlope =
                    pickMiddleBiomeOrBadlandsIfHotOrSlopeIfCold(ti, hi, weird);
                const BiomeId plateau = pickPlateauBiome(ti, hi, weird);
                const BiomeId shattered = pickShatteredBiome(ti, hi, weird);
                const BiomeId windsweptSavanna =
                    maybePickWindsweptSavannaBiome(ti, hi, weird, middle);
                const BiomeId slope = pickSlopeBiome(ti, hi, weird);
                const BiomeId peak = pickPeakBiome(ti, hi, weird);

                addSurfaceBiome(t, h, coastContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, middle);
                addSurfaceBiome(t, h, nearInlandContinentalness_, erosions_[0], weird, 0.0f, slope);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[0], weird, 0.0f, peak);
                addSurfaceBiome(t, h, nearInlandContinentalness_, erosions_[1], weird, 0.0f, middleOrBadlandsOrSlope);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[1], weird, 0.0f, slope);
                addSurfaceBiome(t, h, span(coastContinentalness_, nearInlandContinentalness_), span(erosions_[2], erosions_[3]), weird, 0.0f, middle);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[2], weird, 0.0f, plateau);
                addSurfaceBiome(t, h, midInlandContinentalness_, erosions_[3], weird, 0.0f, middleOrBadlands);
                addSurfaceBiome(t, h, farInlandContinentalness_, erosions_[3], weird, 0.0f, plateau);
                addSurfaceBiome(t, h, span(coastContinentalness_, farInlandContinentalness_), erosions_[4], weird, 0.0f, middle);
                addSurfaceBiome(t, h, span(coastContinentalness_, nearInlandContinentalness_), erosions_[5], weird, 0.0f, windsweptSavanna);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[5], weird, 0.0f, shattered);
                addSurfaceBiome(t, h, span(coastContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, middle);
            }
        }
    }

    void addMidSlice(const ClimateRange& weird) {
        addSurfaceBiome(fullRange_, fullRange_, coastContinentalness_, span(erosions_[0], erosions_[2]), weird, 0.0f, BiomeId::StonyShore);
        addSurfaceBiome(span(temperatures_[1], temperatures_[2]), fullRange_, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::Swamp);
        addSurfaceBiome(span(temperatures_[3], temperatures_[4]), fullRange_, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::MangroveSwamp);

        for (int ti = 0; ti < 5; ++ti) {
            const ClimateRange t = temperatures_[ti];
            for (int hi = 0; hi < 5; ++hi) {
                const ClimateRange h = humidities_[hi];
                const BiomeId middle = pickMiddleBiome(ti, hi, weird);
                const BiomeId middleOrBadlands = pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
                const BiomeId middleOrBadlandsOrSlope =
                    pickMiddleBiomeOrBadlandsIfHotOrSlopeIfCold(ti, hi, weird);
                const BiomeId shattered = pickShatteredBiome(ti, hi, weird);
                const BiomeId plateau = pickPlateauBiome(ti, hi, weird);
                const BiomeId beach = pickBeachBiome(ti, hi);
                const BiomeId windsweptSavanna =
                    maybePickWindsweptSavannaBiome(ti, hi, weird, middle);
                const BiomeId shatteredCoast = pickShatteredCoastBiome(ti, hi, weird);
                const BiomeId slope = pickSlopeBiome(ti, hi, weird);

                addSurfaceBiome(t, h, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[0], weird, 0.0f, slope);
                addSurfaceBiome(t, h, span(nearInlandContinentalness_, midInlandContinentalness_), erosions_[1], weird, 0.0f, middleOrBadlandsOrSlope);
                addSurfaceBiome(t, h, farInlandContinentalness_, erosions_[1], weird, 0.0f, (ti == 0) ? slope : plateau);
                addSurfaceBiome(t, h, nearInlandContinentalness_, erosions_[2], weird, 0.0f, middle);
                addSurfaceBiome(t, h, midInlandContinentalness_, erosions_[2], weird, 0.0f, middleOrBadlands);
                addSurfaceBiome(t, h, farInlandContinentalness_, erosions_[2], weird, 0.0f, plateau);
                addSurfaceBiome(t, h, span(coastContinentalness_, nearInlandContinentalness_), erosions_[3], weird, 0.0f, middle);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[3], weird, 0.0f, middleOrBadlands);

                if (weird.max < 0.0f) {
                    addSurfaceBiome(t, h, coastContinentalness_, erosions_[4], weird, 0.0f, beach);
                    addSurfaceBiome(t, h, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[4], weird, 0.0f, middle);
                } else {
                    addSurfaceBiome(t, h, span(coastContinentalness_, farInlandContinentalness_), erosions_[4], weird, 0.0f, middle);
                }

                addSurfaceBiome(t, h, coastContinentalness_, erosions_[5], weird, 0.0f, shatteredCoast);
                addSurfaceBiome(t, h, nearInlandContinentalness_, erosions_[5], weird, 0.0f, windsweptSavanna);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[5], weird, 0.0f, shattered);

                if (weird.max < 0.0f) {
                    addSurfaceBiome(t, h, coastContinentalness_, erosions_[6], weird, 0.0f, beach);
                } else {
                    addSurfaceBiome(t, h, coastContinentalness_, erosions_[6], weird, 0.0f, middle);
                }

                if (ti == 0) {
                    addSurfaceBiome(t, h, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, middle);
                }
            }
        }
    }

    void addLowSlice(const ClimateRange& weird) {
        addSurfaceBiome(fullRange_, fullRange_, coastContinentalness_, span(erosions_[0], erosions_[2]), weird, 0.0f, BiomeId::StonyShore);
        addSurfaceBiome(span(temperatures_[1], temperatures_[2]), fullRange_, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::Swamp);
        addSurfaceBiome(span(temperatures_[3], temperatures_[4]), fullRange_, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::MangroveSwamp);

        for (int ti = 0; ti < 5; ++ti) {
            const ClimateRange t = temperatures_[ti];
            for (int hi = 0; hi < 5; ++hi) {
                const ClimateRange h = humidities_[hi];
                const BiomeId middle = pickMiddleBiome(ti, hi, weird);
                const BiomeId middleOrBadlands = pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
                const BiomeId middleOrBadlandsOrSlope =
                    pickMiddleBiomeOrBadlandsIfHotOrSlopeIfCold(ti, hi, weird);
                const BiomeId beach = pickBeachBiome(ti, hi);
                const BiomeId windsweptSavanna =
                    maybePickWindsweptSavannaBiome(ti, hi, weird, middle);
                const BiomeId shatteredCoast = pickShatteredCoastBiome(ti, hi, weird);

                addSurfaceBiome(t, h, nearInlandContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, middleOrBadlands);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), span(erosions_[0], erosions_[1]), weird, 0.0f, middleOrBadlandsOrSlope);
                addSurfaceBiome(t, h, nearInlandContinentalness_, span(erosions_[2], erosions_[3]), weird, 0.0f, middle);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), span(erosions_[2], erosions_[3]), weird, 0.0f, middleOrBadlands);
                addSurfaceBiome(t, h, coastContinentalness_, span(erosions_[3], erosions_[4]), weird, 0.0f, beach);
                addSurfaceBiome(t, h, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[4], weird, 0.0f, middle);
                addSurfaceBiome(t, h, coastContinentalness_, erosions_[5], weird, 0.0f, shatteredCoast);
                addSurfaceBiome(t, h, nearInlandContinentalness_, erosions_[5], weird, 0.0f, windsweptSavanna);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), erosions_[5], weird, 0.0f, middle);
                addSurfaceBiome(t, h, coastContinentalness_, erosions_[6], weird, 0.0f, beach);
                if (ti == 0) {
                    addSurfaceBiome(t, h, span(nearInlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, middle);
                }
            }
        }
    }

    void addValleys(const ClimateRange& weird) {
        addSurfaceBiome(frozenRange_, fullRange_, coastContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, weird.max < 0.0f ? BiomeId::StonyShore : BiomeId::FrozenRiver);
        addSurfaceBiome(unfrozenRange_, fullRange_, coastContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, weird.max < 0.0f ? BiomeId::StonyShore : BiomeId::River);
        addSurfaceBiome(frozenRange_, fullRange_, nearInlandContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, BiomeId::FrozenRiver);
        addSurfaceBiome(unfrozenRange_, fullRange_, nearInlandContinentalness_, span(erosions_[0], erosions_[1]), weird, 0.0f, BiomeId::River);
        addSurfaceBiome(frozenRange_, fullRange_, span(coastContinentalness_, farInlandContinentalness_), span(erosions_[2], erosions_[5]), weird, 0.0f, BiomeId::FrozenRiver);
        addSurfaceBiome(unfrozenRange_, fullRange_, span(coastContinentalness_, farInlandContinentalness_), span(erosions_[2], erosions_[5]), weird, 0.0f, BiomeId::River);
        addSurfaceBiome(frozenRange_, fullRange_, coastContinentalness_, erosions_[6], weird, 0.0f, BiomeId::FrozenRiver);
        addSurfaceBiome(unfrozenRange_, fullRange_, coastContinentalness_, erosions_[6], weird, 0.0f, BiomeId::River);
        addSurfaceBiome(span(temperatures_[1], temperatures_[2]), fullRange_, span(inlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::Swamp);
        addSurfaceBiome(span(temperatures_[3], temperatures_[4]), fullRange_, span(inlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::MangroveSwamp);
        addSurfaceBiome(frozenRange_, fullRange_, span(inlandContinentalness_, farInlandContinentalness_), erosions_[6], weird, 0.0f, BiomeId::FrozenRiver);

        for (int ti = 0; ti < 5; ++ti) {
            const ClimateRange t = temperatures_[ti];
            for (int hi = 0; hi < 5; ++hi) {
                const ClimateRange h = humidities_[hi];
                const BiomeId middleOrBadlands = pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
                addSurfaceBiome(t, h, span(midInlandContinentalness_, farInlandContinentalness_), span(erosions_[0], erosions_[1]), weird, 0.0f, middleOrBadlands);
            }
        }
    }

    void addUndergroundBiomes() {
        addUndergroundBiome(fullRange_, fullRange_, span(0.8f, 1.0f), fullRange_, fullRange_, 0.0f, BiomeId::DripstoneCaves);
        addUndergroundBiome(fullRange_, span(0.7f, 1.0f), fullRange_, fullRange_, fullRange_, 0.0f, BiomeId::LushCaves);
        addBottomBiome(fullRange_, fullRange_, fullRange_, span(erosions_[0], erosions_[1]), fullRange_, 0.0f, BiomeId::DeepDark);
    }

    BiomeId pickMiddleBiome(int ti, int hi, const ClimateRange& weird) const {
        if (weird.max < 0.0f) {
            return middleBiomes_[ti][hi];
        }
        const BiomeId v = middleBiomesVariant_[ti][hi];
        return v == BiomeId::None ? middleBiomes_[ti][hi] : v;
    }

    BiomeId pickMiddleBiomeOrBadlandsIfHot(int ti, int hi, const ClimateRange& weird) const {
        return (ti == 4) ? pickBadlandsBiome(hi, weird) : pickMiddleBiome(ti, hi, weird);
    }

    BiomeId pickMiddleBiomeOrBadlandsIfHotOrSlopeIfCold(int ti,
                                                         int hi,
                                                         const ClimateRange& weird) const {
        return (ti == 0) ? pickSlopeBiome(ti, hi, weird)
                         : pickMiddleBiomeOrBadlandsIfHot(ti, hi, weird);
    }

    BiomeId maybePickWindsweptSavannaBiome(int ti,
                                           int hi,
                                           const ClimateRange& weird,
                                           BiomeId fallback) const {
        if (ti > 1 && hi < 4 && weird.max >= 0.0f) {
            return BiomeId::WindsweptSavanna;
        }
        return fallback;
    }

    BiomeId pickShatteredCoastBiome(int ti, int hi, const ClimateRange& weird) const {
        const BiomeId base =
            (weird.max >= 0.0f) ? pickMiddleBiome(ti, hi, weird) : pickBeachBiome(ti, hi);
        return maybePickWindsweptSavannaBiome(ti, hi, weird, base);
    }

    BiomeId pickBeachBiome(int ti, int /*hi*/) const {
        if (ti == 0) {
            return BiomeId::SnowyBeach;
        }
        if (ti == 4) {
            return BiomeId::Desert;
        }
        return BiomeId::Beach;
    }

    BiomeId pickBadlandsBiome(int hi, const ClimateRange& weird) const {
        if (hi < 2) {
            return (weird.max < 0.0f) ? BiomeId::Badlands : BiomeId::ErodedBadlands;
        }
        if (hi < 3) {
            return BiomeId::Badlands;
        }
        return BiomeId::WoodedBadlands;
    }

    BiomeId pickPlateauBiome(int ti, int hi, const ClimateRange& weird) const {
        if (weird.max >= 0.0f) {
            const BiomeId v = plateauBiomesVariant_[ti][hi];
            if (v != BiomeId::None) {
                return v;
            }
        }
        return plateauBiomes_[ti][hi];
    }

    BiomeId pickPeakBiome(int ti, int hi, const ClimateRange& weird) const {
        if (ti <= 2) {
            return weird.max < 0.0f ? BiomeId::JaggedPeaks : BiomeId::FrozenPeaks;
        }
        if (ti == 3) {
            return BiomeId::StonyPeaks;
        }
        return pickBadlandsBiome(hi, weird);
    }

    BiomeId pickSlopeBiome(int ti, int hi, const ClimateRange& weird) const {
        if (ti >= 3) {
            return pickPlateauBiome(ti, hi, weird);
        }
        if (hi <= 1) {
            return BiomeId::SnowySlopes;
        }
        return BiomeId::Grove;
    }

    BiomeId pickShatteredBiome(int ti, int hi, const ClimateRange& weird) const {
        const BiomeId candidate = shatteredBiomes_[ti][hi];
        return candidate == BiomeId::None ? pickMiddleBiome(ti, hi, weird) : candidate;
    }

    void addSurfaceBiome(const ClimateRange& t,
                         const ClimateRange& h,
                         const ClimateRange& c,
                         const ClimateRange& e,
                         const ClimateRange& w,
                         float offset,
                         BiomeId biome) {
        points_.push_back({t, h, c, e, point(0.0f), w, offset, biome});
        points_.push_back({t, h, c, e, point(1.0f), w, offset, biome});
    }

    void addUndergroundBiome(const ClimateRange& t,
                             const ClimateRange& h,
                             const ClimateRange& c,
                             const ClimateRange& e,
                             const ClimateRange& w,
                             float offset,
                             BiomeId biome) {
        points_.push_back({t, h, c, e, span(0.2f, 0.9f), w, offset, biome});
    }

    void addBottomBiome(const ClimateRange& t,
                        const ClimateRange& h,
                        const ClimateRange& c,
                        const ClimateRange& e,
                        const ClimateRange& w,
                        float offset,
                        BiomeId biome) {
        points_.push_back({t, h, c, e, point(1.1f), w, offset, biome});
    }

    ClimateRange fullRange_{};
    std::array<ClimateRange, 5> temperatures_{};
    std::array<ClimateRange, 5> humidities_{};
    std::array<ClimateRange, 7> erosions_{};
    ClimateRange frozenRange_{};
    ClimateRange unfrozenRange_{};
    ClimateRange mushroomFieldsContinentalness_{};
    ClimateRange deepOceanContinentalness_{};
    ClimateRange oceanContinentalness_{};
    ClimateRange coastContinentalness_{};
    ClimateRange inlandContinentalness_{};
    ClimateRange nearInlandContinentalness_{};
    ClimateRange midInlandContinentalness_{};
    ClimateRange farInlandContinentalness_{};

    std::array<std::array<BiomeId, 5>, 2> oceans_{};
    std::array<std::array<BiomeId, 5>, 5> middleBiomes_{};
    std::array<std::array<BiomeId, 5>, 5> middleBiomesVariant_{};
    std::array<std::array<BiomeId, 5>, 5> plateauBiomes_{};
    std::array<std::array<BiomeId, 5>, 5> plateauBiomesVariant_{};
    std::array<std::array<BiomeId, 5>, 5> shatteredBiomes_{};

    std::vector<ClimatePoint> points_;
};

inline float peaksAndValleys(float weirdness) {
    return -(std::abs(std::abs(weirdness) - 0.6666667f) - 0.33333334f) * 3.0f;
}

struct ClimateSample {
    float temperature;
    float humidity;
    float continentalness;
    float erosion;
    float weirdness;
    float peaksValleys;
};

struct ColumnSample {
    int32_t x;
    int32_t z;
    int32_t height;
    BiomeId biome;
    ClimateSample climate;
};

class WorldGenerator {
public:
    explicit WorldGenerator(int64_t seed)
        : seed_(seed),
          rootFactory_(seed),
          noiseLow_(rootFactory_.child("terrain"), "low"),
          noiseHigh_(rootFactory_.child("terrain"), "high"),
          noiseSelector_(rootFactory_.child("terrain"), "selector"),
          noiseDetail_(rootFactory_.child("terrain"), "detail"),
          tempNoise_(rootFactory_, "temperature", makeTemperatureParams()),
          humidityNoise_(rootFactory_, "vegetation", makeHumidityParams()),
          continentalNoise_(rootFactory_, "continentalness", makeContinentalParams()),
          erosionNoise_(rootFactory_, "erosion", makeErosionParams()),
          ridgeNoise_(rootFactory_, "ridge", makeRidgeParams()) {}

    ColumnSample sampleColumn(int32_t x, int32_t z) const {
        const ClimateSample climate = sampleClimate(x, z);
        const BiomeId biome = biomeTable_.resolve(climate.temperature,
                                                  climate.humidity,
                                                  climate.continentalness,
                                                  climate.erosion,
                                                  0.0f,
                                                  climate.weirdness);

        const double wx = static_cast<double>(x);
        const double wz = static_cast<double>(z);
        const double low = noiseLow_.noise3D(wx / 80.0, 0.0, wz / 80.0) * 1.6;
        const double high = noiseHigh_.noise3D(wx / 60.0, 0.0, wz / 60.0) * 1.6;
        const double selectorRaw = noiseSelector_.noise3D(wx / 500.0, 0.0, wz / 500.0);
        const double selector = std::clamp((selectorRaw + 1.0) * 0.5, 0.0, 1.0);
        const double blended = low * (1.0 - selector) + high * selector;
        const double detail = noiseDetail_.noise3D(wx / 25.0, 0.0, wz / 25.0);

        const auto [baseHeight, variation] = biomeHeightParams(biome);

        double h = 63.0 + 2.0 + baseHeight * 20.0 + blended * 16.0 +
                   (selector - 0.5) * 6.0;
        h += detail * (variation * 8.0 + 3.0);
        h = std::clamp(h, 5.0, 250.0);

        ColumnSample out{};
        out.x = x;
        out.z = z;
        out.height = static_cast<int32_t>(std::lround(h));
        out.biome = biome;
        out.climate = climate;
        return out;
    }

    int64_t seed() const { return seed_; }

private:
    static NoiseParameters makeTemperatureParams() {
        return NoiseParameters{-10, {1.5, 0.0, 1.0, 0.0, 0.0, 0.0}};
    }

    static NoiseParameters makeHumidityParams() {
        return NoiseParameters{-8, {1.0, 1.0, 0.0, 0.0, 0.0, 0.0}};
    }

    static NoiseParameters makeContinentalParams() {
        return NoiseParameters{-9, {1.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0}};
    }

    static NoiseParameters makeErosionParams() {
        return NoiseParameters{-9, {1.0, 1.0, 0.0, 1.0, 1.0}};
    }

    static NoiseParameters makeRidgeParams() {
        return NoiseParameters{-7, {1.0, 2.0, 1.0, 0.0, 0.0, 0.0}};
    }

    ClimateSample sampleClimate(int32_t x, int32_t z) const {
        // Java biome noise is sampled in quart space + extra scale.
        const double qx = static_cast<double>(x) / 16.0;
        const double qz = static_cast<double>(z) / 16.0;

        ClimateSample c{};
        c.temperature = static_cast<float>(tempNoise_.getValue(qx, 0.0, qz));
        c.humidity = static_cast<float>(humidityNoise_.getValue(qx, 0.0, qz));
        c.continentalness = static_cast<float>(continentalNoise_.getValue(qx, 0.0, qz));
        c.erosion = static_cast<float>(erosionNoise_.getValue(qx, 0.0, qz));
        c.weirdness = static_cast<float>(ridgeNoise_.getValue(qx, 0.0, qz));
        c.peaksValleys = peaksAndValleys(c.weirdness);
        return c;
    }

    int64_t seed_;
    HashRandomFactory rootFactory_;
    OverworldBiomeTable biomeTable_;

    OctaveNoise5 noiseLow_;
    OctaveNoise5 noiseHigh_;
    OctaveNoise5 noiseSelector_;
    OctaveNoise5 noiseDetail_;

    NormalNoise tempNoise_;
    NormalNoise humidityNoise_;
    NormalNoise continentalNoise_;
    NormalNoise erosionNoise_;
    NormalNoise ridgeNoise_;
};

bool readExact(std::istream& in, uint8_t* dst, size_t n) {
    in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
    return in.good() || in.gcount() == static_cast<std::streamsize>(n);
}

bool writeExact(std::ostream& out, const uint8_t* src, size_t n) {
    out.write(reinterpret_cast<const char*>(src), static_cast<std::streamsize>(n));
    return out.good();
}

uint16_t loadU16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) |
           (static_cast<uint16_t>(p[1]) << 8);
}

uint32_t loadU32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

uint64_t loadU64(const uint8_t* p) {
    return static_cast<uint64_t>(loadU32(p)) |
           (static_cast<uint64_t>(loadU32(p + 4)) << 32);
}

int32_t loadI32(const uint8_t* p) { return static_cast<int32_t>(loadU32(p)); }
int64_t loadI64(const uint8_t* p) { return static_cast<int64_t>(loadU64(p)); }

void appendU16(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v & 0xFF));
    out.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
}

void appendU32(std::vector<uint8_t>& out, uint32_t v) {
    out.push_back(static_cast<uint8_t>(v & 0xFF));
    out.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    out.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
    out.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
}

void appendU64(std::vector<uint8_t>& out, uint64_t v) {
    appendU32(out, static_cast<uint32_t>(v & 0xFFFFFFFFULL));
    appendU32(out, static_cast<uint32_t>((v >> 32) & 0xFFFFFFFFULL));
}

void appendI32(std::vector<uint8_t>& out, int32_t v) {
    appendU32(out, static_cast<uint32_t>(v));
}

void appendI64(std::vector<uint8_t>& out, int64_t v) {
    appendU64(out, static_cast<uint64_t>(v));
}

void appendF32(std::vector<uint8_t>& out, float v) {
    uint32_t bits = 0;
    std::memcpy(&bits, &v, sizeof(float));
    appendU32(out, bits);
}

void writeFrame(std::ostream& out,
                uint16_t type,
                const std::vector<uint8_t>& payload) {
    std::vector<uint8_t> header;
    header.reserve(12);
    appendU32(header, kProtocolMagic);
    appendU16(header, kProtocolVersion);
    appendU16(header, type);
    appendU32(header, static_cast<uint32_t>(payload.size()));
    writeExact(out, header.data(), header.size());
    if (!payload.empty()) {
        writeExact(out, payload.data(), payload.size());
    }
    out.flush();
}

void writeError(std::ostream& out, int32_t code, std::string_view message) {
    std::vector<uint8_t> payload;
    appendI32(payload, code);
    appendU32(payload, static_cast<uint32_t>(message.size()));
    payload.insert(payload.end(), message.begin(), message.end());
    writeFrame(out, kRespError, payload);
}

}  // namespace worldgen

int main() {
    using namespace worldgen;

    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::unique_ptr<WorldGenerator> generator;

    while (true) {
        uint8_t headerBuf[12];
        if (!readExact(std::cin, headerBuf, sizeof(headerBuf))) {
            break;
        }

        const uint32_t magic = loadU32(headerBuf);
        const uint16_t version = loadU16(headerBuf + 4);
        const uint16_t reqType = loadU16(headerBuf + 6);
        const uint32_t payloadLen = loadU32(headerBuf + 8);

        if (magic != kProtocolMagic) {
            writeError(std::cout, 1001, "bad magic");
            break;
        }
        if (version != kProtocolVersion) {
            writeError(std::cout, 1002, "unsupported protocol version");
            break;
        }

        std::vector<uint8_t> payload(payloadLen);
        if (payloadLen > 0 && !readExact(std::cin, payload.data(), payloadLen)) {
            writeError(std::cout, 1003, "truncated payload");
            break;
        }

        if (reqType == kReqInit) {
            if (payload.size() != 8) {
                writeError(std::cout, 2001, "init payload must be 8 bytes");
                continue;
            }
            const int64_t seed = loadI64(payload.data());
            generator = std::make_unique<WorldGenerator>(seed);

            std::vector<uint8_t> out;
            appendI32(out, 0);
            appendI64(out, seed);
            writeFrame(std::cout, static_cast<uint16_t>(kRespFlag | kReqInit), out);
            continue;
        }

        if (reqType == kReqPing) {
            std::vector<uint8_t> out = payload;
            writeFrame(std::cout, static_cast<uint16_t>(kRespFlag | kReqPing), out);
            continue;
        }

        if (reqType == kReqShutdown) {
            std::vector<uint8_t> out;
            appendI32(out, 0);
            writeFrame(std::cout, static_cast<uint16_t>(kRespFlag | kReqShutdown), out);
            break;
        }

        if (!generator) {
            writeError(std::cout, 2002, "generator not initialized");
            continue;
        }

        if (reqType == kReqSampleColumn) {
            if (payload.size() != 8) {
                writeError(std::cout, 3001, "column payload must be 8 bytes");
                continue;
            }
            const int32_t x = loadI32(payload.data());
            const int32_t z = loadI32(payload.data() + 4);
            const ColumnSample s = generator->sampleColumn(x, z);

            std::vector<uint8_t> out;
            appendI32(out, s.x);
            appendI32(out, s.z);
            appendI32(out, s.height);
            appendU16(out, static_cast<uint16_t>(s.biome));
            appendU16(out, 0);
            appendF32(out, s.climate.temperature);
            appendF32(out, s.climate.humidity);
            appendF32(out, s.climate.continentalness);
            appendF32(out, s.climate.erosion);
            appendF32(out, s.climate.weirdness);
            appendF32(out, s.climate.peaksValleys);
            writeFrame(std::cout, static_cast<uint16_t>(kRespFlag | kReqSampleColumn), out);
            continue;
        }

        if (reqType == kReqSampleRegion) {
            if (payload.size() != 16) {
                writeError(std::cout, 3002, "region payload must be 16 bytes");
                continue;
            }
            const int32_t x0 = loadI32(payload.data());
            const int32_t z0 = loadI32(payload.data() + 4);
            const int32_t width = loadI32(payload.data() + 8);
            const int32_t depth = loadI32(payload.data() + 12);

            if (width <= 0 || depth <= 0 || width > 1024 || depth > 1024) {
                writeError(std::cout, 3003, "region width/depth out of range");
                continue;
            }

            std::vector<uint8_t> out;
            out.reserve(static_cast<size_t>(16 + width * depth * 4));
            appendI32(out, x0);
            appendI32(out, z0);
            appendI32(out, width);
            appendI32(out, depth);

            for (int32_t dz = 0; dz < depth; ++dz) {
                for (int32_t dx = 0; dx < width; ++dx) {
                    const ColumnSample s = generator->sampleColumn(x0 + dx, z0 + dz);
                    appendU16(out, static_cast<uint16_t>(s.biome));
                    appendU16(out, static_cast<uint16_t>(std::clamp(s.height, 0, 65535)));
                }
            }

            writeFrame(std::cout, static_cast<uint16_t>(kRespFlag | kReqSampleRegion), out);
            continue;
        }

        writeError(std::cout, 4001, "unknown request type");
    }

    return 0;
}

