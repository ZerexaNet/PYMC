// ============================================================
// PyMC - Native overworld generator (Minecraft Java 1.21.1)
//
// Child process of the Python server, binary protocol on stdin/stdout:
//
//   'C' + int32 chunk_x + int32 chunk_z + int64 seed
//        -> uint32 payload size + payload (one chunk)
//   'B' + int64 seed + uint32 count + count * (int32 x, int32 z)
//        -> uint32 count + count * payload
//   'S' + int64 seed
//        -> int32 x + int32 z   (vanilla Climate.findSpawnPosition)
//
//   payload (little endian):
//     uint16[98304] block states (y*256 + z*16 + x, y from -64)
//     int16[256]    heightmap: highest solid block per column (z*16 + x)
//     uint16[1536]  biomes (section*64 + y*16 + z*4 + x)
//
// Terrain shape, caves, aquifers, ore veins, biomes and surface rules are
// the vanilla algorithms driven by the vanilla worldgen data in
// world/data/worldgen_overworld.json (see tools/gen_worldgen_data.py).
//
// Build:  g++ -O2 -std=c++17 -ffp-contract=off -pthread -o terrain_gen terrain_gen.cpp
// (-ffp-contract=off keeps floating point bit-identical to Java.)
// ============================================================

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#ifdef _WIN32
// windows.h must not define min/max macros: they break std::min / std::max.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

#include "worldgen/features.h"
#include "worldgen/terrain.h"

using namespace vgen;

static const char* VERSION_STRING = "pymc-worldgen 2 (minecraft 1.21.1, vanilla noise router)";

static constexpr uint32_t BLOCKS_BYTES = BLOCKS_PER_CHUNK * 2;
static constexpr uint32_t HEIGHTMAP_BYTES = 256 * 2;
static constexpr uint32_t BIOME_BYTES = SECTIONS * 64 * 2;
static constexpr uint32_t PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES + BIOME_BYTES;

static bool read_exact(void* buf, size_t n) {
    uint8_t* p = (uint8_t*)buf;
    while (n > 0) {
        size_t r = fread(p, 1, n, stdin);
        if (r == 0) return false;
        p += r;
        n -= r;
    }
    return true;
}

static bool write_exact(const void* buf, size_t n) {
    const uint8_t* p = (const uint8_t*)buf;
    while (n > 0) {
        size_t w = fwrite(p, 1, n, stdout);
        if (w == 0) return false;
        p += w;
        n -= w;
    }
    return true;
}

static std::string executable_dir(const char* argv0) {
#ifdef _WIN32
    char buf[4096];
    DWORD len = GetModuleFileNameA(nullptr, buf, sizeof(buf));
    std::string path = len ? std::string(buf, len) : std::string(argv0);
#else
    char buf[4096];
    ssize_t len = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    std::string path = len > 0 ? std::string(buf, (size_t)len) : std::string(argv0);
#endif
    size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? std::string(".") : path.substr(0, slash);
}

static std::string find_data(const std::string& explicit_path, const char* argv0) {
    std::vector<std::string> candidates;
    if (!explicit_path.empty()) candidates.push_back(explicit_path);
    std::string dir = executable_dir(argv0);
    const char* rel = "world/data/worldgen_overworld.json";
    candidates.push_back(dir + "/../" + rel);
    candidates.push_back(dir + "/" + rel);
    candidates.push_back(dir + "/../../" + rel);
    candidates.push_back(rel);
    for (auto& c : candidates) {
        std::ifstream f(c, std::ios::binary);
        if (f.good()) return c;
    }
    return "";
}

struct ChunkKey {
    int x, z;
    bool operator==(const ChunkKey& o) const { return x == o.x && z == o.z; }
};
struct ChunkKeyHash {
    size_t operator()(const ChunkKey& k) const { return std::hash<int64_t>()(((int64_t)k.x << 32) ^ (uint32_t)k.z); }
};

class Generator {
public:
    Json data;
    int threads = 4;
    int64_t seed = INT64_MIN;
    std::unique_ptr<Terrain> terrain;
    std::unique_ptr<Features> features;
    std::unordered_map<ChunkKey, ChunkSummary, ChunkKeyHash> summaries;
    std::mutex mutex;

    void set_seed(int64_t s) {
        if (terrain && s == seed) return;
        seed = s;
        terrain = std::make_unique<Terrain>();
        terrain->init(data, seed);
        features = std::make_unique<Features>(*terrain);
        features->init(data);
        summaries.clear();
    }

    template <class F>
    void parallel(size_t n, F&& fn) {
        if (n == 0) return;
        unsigned workers = (unsigned)std::min<size_t>((size_t)std::max(1, threads), n);
        if (workers <= 1) {
            for (size_t i = 0; i < n; i++) fn(i);
            return;
        }
        std::atomic<size_t> next(0);
        std::vector<std::thread> pool;
        for (unsigned w = 0; w < workers; w++)
            pool.emplace_back([&]() {
                size_t i;
                while ((i = next.fetch_add(1)) < n) fn(i);
            });
        for (auto& t : pool) t.join();
    }

    void generate(const std::vector<ChunkKey>& coords, std::vector<TerrainChunk>& out) {
        out.assign(coords.size(), TerrainChunk());
        parallel(coords.size(), [&](size_t i) { terrain->generate(coords[i].x, coords[i].z, out[i]); });

        std::unordered_map<ChunkKey, size_t, ChunkKeyHash> requested;
        for (size_t i = 0; i < coords.size(); i++) requested[coords[i]] = i;
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (summaries.size() > 20000) summaries.clear();
            for (size_t i = 0; i < coords.size(); i++) summaries[coords[i]] = summarize(out[i]);
        }
        std::vector<ChunkKey> missing;
        {
            std::set<std::pair<int, int>> seen;
            std::lock_guard<std::mutex> lock(mutex);
            for (auto& c : coords)
                for (int dz = -1; dz <= 1; dz++)
                    for (int dx = -1; dx <= 1; dx++) {
                        ChunkKey k{c.x + dx, c.z + dz};
                        if (summaries.count(k) || !seen.insert({k.x, k.z}).second) continue;
                        missing.push_back(k);
                    }
        }
        std::vector<ChunkSummary> extra(missing.size());
        parallel(missing.size(), [&](size_t i) {
            TerrainChunk tmp;
            terrain->generate(missing[i].x, missing[i].z, tmp);
            extra[i] = summarize(tmp);
        });
        {
            std::lock_guard<std::mutex> lock(mutex);
            for (size_t i = 0; i < missing.size(); i++) summaries[missing[i]] = extra[i];
        }
        parallel(coords.size(), [&](size_t i) {
            auto lookup = [&](int x, int z) -> const ChunkSummary& { return summaries.at(ChunkKey{x, z}); };
            features->decorate(out[i], lookup);
        });
    }
};

static void write_payload(const TerrainChunk& c, std::vector<uint8_t>& buf) {
    buf.resize(PAYLOAD_SIZE);
    std::memcpy(buf.data(), c.blocks.data(), BLOCKS_BYTES);
    int16_t* hm = (int16_t*)(buf.data() + BLOCKS_BYTES);
    for (int z = 0; z < 16; z++)
        for (int x = 0; x < 16; x++) {
            int h = MIN_Y + 1;
            for (int y = MAX_Y; y >= MIN_Y; y--) {
                uint16_t b = c.blocks[block_index(x, y, z)];
                if (b != 0 && b != 80 && b != 96 && !(b >= 81 && b <= 95) && !(b >= 97 && b <= 111)) { h = y; break; }
            }
            hm[z * 16 + x] = (int16_t)h;
        }
    std::memcpy(buf.data() + BLOCKS_BYTES + HEIGHTMAP_BYTES, c.biomes.data(), BIOME_BYTES);
}

int main(int argc, char** argv) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    std::string data_path;
    int threads = (int)std::thread::hardware_concurrency();
    if (threads <= 0) threads = 4;
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--version") == 0) {
            printf("%s\n", VERSION_STRING);
            return 0;
        }
        if (std::strcmp(argv[i], "--threads") == 0 && i + 1 < argc) threads = std::max(1, std::atoi(argv[++i]));
        else if (std::strcmp(argv[i], "--data") == 0 && i + 1 < argc) data_path = argv[++i];
    }
    std::string path = find_data(data_path, argv[0]);
    if (path.empty()) {
        fprintf(stderr, "terrain_gen: cannot find world/data/worldgen_overworld.json (use --data)\n");
        return 2;
    }
    Generator gen;
    gen.threads = threads;
    try {
        std::ifstream f(path, std::ios::binary);
        std::stringstream ss;
        ss << f.rdbuf();
        std::string text = ss.str();
        gen.data = JsonParser(text).parse();
    } catch (const std::exception& e) {
        fprintf(stderr, "terrain_gen: failed to load %s: %s\n", path.c_str(), e.what());
        return 2;
    }

    setvbuf(stdout, nullptr, _IOFBF, 1 << 20);
    std::vector<uint8_t> payload;
    try {
        while (true) {
            uint8_t command = 0;
            if (!read_exact(&command, 1)) break;
            if (command == 'C') {
                uint8_t req[16];
                if (!read_exact(req, 16)) break;
                int32_t cx, cz;
                int64_t seed;
                std::memcpy(&cx, req, 4);
                std::memcpy(&cz, req + 4, 4);
                std::memcpy(&seed, req + 8, 8);
                gen.set_seed(seed);
                std::vector<TerrainChunk> out;
                gen.generate({ChunkKey{cx, cz}}, out);
                write_payload(out[0], payload);
                uint32_t size = PAYLOAD_SIZE;
                if (!write_exact(&size, 4) || !write_exact(payload.data(), payload.size())) break;
                fflush(stdout);
            } else if (command == 'B') {
                int64_t seed;
                uint32_t count;
                if (!read_exact(&seed, 8) || !read_exact(&count, 4)) break;
                gen.set_seed(seed);
                std::vector<ChunkKey> coords(count);
                for (uint32_t i = 0; i < count; i++) {
                    int32_t xz[2];
                    if (!read_exact(xz, 8)) return 0;
                    coords[i] = {xz[0], xz[1]};
                }
                std::vector<TerrainChunk> out;
                gen.generate(coords, out);
                if (!write_exact(&count, 4)) break;
                bool ok = true;
                for (uint32_t i = 0; i < count && ok; i++) {
                    write_payload(out[i], payload);
                    ok = write_exact(payload.data(), payload.size());
                }
                if (!ok) break;
                fflush(stdout);
            } else if (command == 'S') {
                int64_t seed;
                if (!read_exact(&seed, 8)) break;
                gen.set_seed(seed);
                int x = 0, z = 0;
                gen.terrain->find_spawn(x, z);
                int32_t out[2] = {x, z};
                if (!write_exact(out, 8)) break;
                fflush(stdout);
            } else {
                break;
            }
        }
    } catch (const std::exception& e) {
        fprintf(stderr, "terrain_gen: %s\n", e.what());
        return 3;
    }
    return 0;
}
