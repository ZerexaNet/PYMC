// ============================================================
// PyMC - C++ lightweight mob AI engine
//
// Long-lived stdin/stdout helper. Python keeps collision/network state; this
// process computes vanilla-inspired goal decisions: look-at-player, random
// stroll, hostile target chase, and zombie aggression timing.
// ============================================================

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

constexpr uint8_t kTickCommand = 'T';
constexpr uint32_t kResponsePayloadSize = 80;

enum MobType : int32_t {
    kPig = 0,
    kCow = 1,
    kSheep = 2,
    kZombie = 3,
    kSkeleton = 4,
    kCreeper = 5,
    kSpider = 6,
};

struct Profile {
    bool hostile;
    bool keep_distance;
    double speed;
    int wander_interval;
    double look_range;
    double follow_range;
    double preferred_distance;
};

struct PlayerInput {
    double x;
    double y;
    double z;
    uint8_t attackable;
};

struct MobInput {
    int32_t mob_type;
    int32_t entity_id;
    int32_t age_ticks;
    int32_t wander_cooldown;
    int32_t attack_cooldown;
    int32_t aggressive_ticks;
    int32_t look_time;
    int32_t has_target;
    double x;
    double y;
    double z;
    double yaw;
    double pitch;
    double vx;
    double vy;
    double vz;
    double target_x;
    double target_y;
    double target_z;
    uint32_t player_count;
};

struct AiOutput {
    int32_t ok = 1;
    double vx = 0.0;
    double vz = 0.0;
    double yaw = 0.0;
    double pitch = 0.0;
    int32_t wander_cooldown = 0;
    int32_t aggressive_ticks = 0;
    int32_t look_time = 0;
    int32_t has_target = 0;
    double target_x = 0.0;
    double target_y = 0.0;
    double target_z = 0.0;
    int32_t target_player_index = -1;
};

bool read_exact(void* buf, size_t n) {
    auto* p = static_cast<uint8_t*>(buf);
    while (n > 0) {
        size_t r = std::fread(p, 1, n, stdin);
        if (r == 0) {
            return false;
        }
        p += r;
        n -= r;
    }
    return true;
}

bool write_exact(const void* buf, size_t n) {
    const auto* p = static_cast<const uint8_t*>(buf);
    while (n > 0) {
        size_t w = std::fwrite(p, 1, n, stdout);
        if (w == 0) {
            return false;
        }
        p += w;
        n -= w;
    }
    return true;
}

template <typename T>
void append(std::vector<uint8_t>& out, const T& value) {
    const auto* p = reinterpret_cast<const uint8_t*>(&value);
    out.insert(out.end(), p, p + sizeof(T));
}

double clamp(double v, double low, double high) {
    return std::max(low, std::min(high, v));
}

double yaw_to(double from_x, double from_z, double to_x, double to_z) {
    const double dx = to_x - from_x;
    const double dz = to_z - from_z;
    return std::atan2(-dx, dz) * 180.0 / 3.14159265358979323846;
}

double pitch_to(double from_x, double from_y, double from_z,
                double to_x, double to_y, double to_z) {
    const double dx = to_x - from_x;
    const double dy = to_y - from_y;
    const double dz = to_z - from_z;
    const double horizontal = std::max(0.001, std::sqrt(dx * dx + dz * dz));
    return clamp(-std::atan2(dy, horizontal) * 180.0 / 3.14159265358979323846, -90.0, 90.0);
}

uint64_t mix64(uint64_t x) {
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return x;
}

uint64_t rng_seed(const MobInput& in, uint64_t salt) {
    uint64_t h = static_cast<uint64_t>(in.entity_id) * 0x9e3779b97f4a7c15ULL;
    h ^= static_cast<uint64_t>(in.age_ticks) * 0xbf58476d1ce4e5b9ULL;
    h ^= static_cast<uint64_t>(std::llround(in.x * 32.0)) * 0x94d049bb133111ebULL;
    h ^= static_cast<uint64_t>(std::llround(in.z * 32.0)) * 0x632be59bd9b4e019ULL;
    return mix64(h ^ salt);
}

double random01(const MobInput& in, uint64_t salt) {
    return static_cast<double>(rng_seed(in, salt) >> 11) *
           (1.0 / 9007199254740992.0);
}

int random_int(const MobInput& in, uint64_t salt, int bound) {
    if (bound <= 0) {
        return 0;
    }
    return static_cast<int>(rng_seed(in, salt) % static_cast<uint64_t>(bound));
}

Profile profile_for(int32_t mob_type) {
    switch (mob_type) {
        case kCow:
            return {false, false, 0.055, 120, 8.0, 0.0, 0.0};
        case kSheep:
            return {false, false, 0.055, 120, 8.0, 0.0, 0.0};
        case kZombie:
            return {true, false, 0.075, 120, 8.0, 35.0, 0.0};
        case kSkeleton:
            return {true, true, 0.070, 120, 8.0, 35.0, 12.0};
        case kCreeper:
            return {true, false, 0.078, 120, 8.0, 25.0, 0.0};
        case kSpider:
            return {true, false, 0.105, 100, 8.0, 24.0, 0.0};
        case kPig:
        default:
            return {false, false, 0.055, 120, 8.0, 0.0, 0.0};
    }
}

double distance_squared(double ax, double ay, double az,
                        double bx, double by, double bz) {
    const double dx = ax - bx;
    const double dy = ay - by;
    const double dz = az - bz;
    return dx * dx + dy * dy + dz * dz;
}

int nearest_player(const MobInput& in,
                   const std::vector<PlayerInput>& players,
                   double radius,
                   bool attackable_only) {
    int best = -1;
    double best_dist = radius * radius;
    for (size_t i = 0; i < players.size(); ++i) {
        if (attackable_only && !players[i].attackable) {
            continue;
        }
        const double d = distance_squared(in.x, in.y, in.z, players[i].x, players[i].y, players[i].z);
        if (d < best_dist) {
            best = static_cast<int>(i);
            best_dist = d;
        }
    }
    return best;
}

void apply_wander(const MobInput& in, const Profile& p, AiOutput& out) {
    if (in.has_target) {
        const double dx = in.target_x - in.x;
        const double dz = in.target_z - in.z;
        const double dist = std::sqrt(dx * dx + dz * dz);
        if (dist < 0.7) {
            out.has_target = 0;
            out.vx = in.vx * 0.4;
            out.vz = in.vz * 0.4;
            return;
        }
        out.has_target = 1;
        out.target_x = in.target_x;
        out.target_y = in.target_y;
        out.target_z = in.target_z;
        out.vx = clamp(dx / dist * p.speed, -0.12, 0.12);
        out.vz = clamp(dz / dist * p.speed, -0.12, 0.12);
        out.yaw = yaw_to(in.x, in.z, in.target_x, in.target_z);
        return;
    }

    if (in.wander_cooldown > 0) {
        out.wander_cooldown = in.wander_cooldown - 1;
        out.vx = in.vx * 0.85;
        out.vz = in.vz * 0.85;
        return;
    }

    const double angle = random01(in, 0x1234) * 6.28318530717958647692;
    const double radius = 4.0 + random01(in, 0x5678) * 6.0;
    out.has_target = 1;
    out.target_x = in.x + std::cos(angle) * radius;
    out.target_y = in.y;
    out.target_z = in.z + std::sin(angle) * radius;
    out.wander_cooldown = std::max(20, p.wander_interval / 2 + random_int(in, 0x9abc, p.wander_interval + 1));
}

AiOutput tick_ai(const MobInput& in, const std::vector<PlayerInput>& players) {
    const Profile p = profile_for(in.mob_type);
    AiOutput out;
    out.vx = in.vx;
    out.vz = in.vz;
    out.yaw = in.yaw;
    out.pitch = in.pitch;
    out.wander_cooldown = in.wander_cooldown;
    out.aggressive_ticks = in.aggressive_ticks;
    out.look_time = in.look_time;
    out.has_target = in.has_target;
    out.target_x = in.target_x;
    out.target_y = in.target_y;
    out.target_z = in.target_z;

    if (p.hostile) {
        const int target = nearest_player(in, players, p.follow_range, true);
        if (target < 0) {
            out.aggressive_ticks = std::max(0, in.aggressive_ticks - 1);
            apply_wander(in, p, out);
            return out;
        }

        const PlayerInput& player = players[static_cast<size_t>(target)];
        const double dx = player.x - in.x;
        const double dz = player.z - in.z;
        const double dist = std::sqrt(dx * dx + dz * dz);
        if (dist > 0.001) {
            double dir_x = dx / dist;
            double dir_z = dz / dist;
            if (p.keep_distance) {
                if (dist < p.preferred_distance - 2.0) {
                    dir_x = -dir_x;
                    dir_z = -dir_z;
                } else if (dist <= p.preferred_distance + 2.0) {
                    const double strafe = (random01(in, 0x51ce1e70ULL) < 0.5) ? -1.0 : 1.0;
                    const double side_x = -dir_z * strafe;
                    const double side_z = dir_x * strafe;
                    dir_x = side_x * 0.85;
                    dir_z = side_z * 0.85;
                }
            }
            out.vx = clamp(dir_x * p.speed, -0.18, 0.18);
            out.vz = clamp(dir_z * p.speed, -0.18, 0.18);
            out.yaw = yaw_to(in.x, in.z, player.x, player.z);
            out.pitch = pitch_to(in.x, in.y, in.z, player.x, player.y + 1.62, player.z);
        }
        out.target_player_index = target;
        if (in.mob_type == kZombie) {
            const bool raising_arms = in.attack_cooldown > 0 && in.attack_cooldown < 10;
            out.aggressive_ticks = raising_arms ? 20 : std::min(20, in.aggressive_ticks + 1);
        } else if (in.mob_type == kCreeper) {
            out.aggressive_ticks = dist < 4.0 ? 30 : std::max(0, in.aggressive_ticks - 1);
        } else if (in.mob_type == kSkeleton || in.mob_type == kSpider) {
            out.aggressive_ticks = std::min(20, in.aggressive_ticks + 1);
        }
        return out;
    }

    if (in.look_time > 0) {
        const int target = nearest_player(in, players, p.look_range, false);
        out.look_time = in.look_time - 1;
        if (target >= 0) {
            const PlayerInput& player = players[static_cast<size_t>(target)];
            out.yaw = yaw_to(in.x, in.z, player.x, player.z);
            out.pitch = pitch_to(in.x, in.y, in.z, player.x, player.y + 1.62, player.z);
            out.vx = in.vx * 0.75;
            out.vz = in.vz * 0.75;
            out.target_player_index = target;
            return out;
        }
    }

    if (random01(in, 0xbeef) < 0.02) {
        const int target = nearest_player(in, players, p.look_range, false);
        if (target >= 0) {
            const PlayerInput& player = players[static_cast<size_t>(target)];
            out.look_time = 40 + random_int(in, 0xfeed, 40);
            out.yaw = yaw_to(in.x, in.z, player.x, player.z);
            out.pitch = pitch_to(in.x, in.y, in.z, player.x, player.y + 1.62, player.z);
            out.target_player_index = target;
            return out;
        }
    }

    apply_wander(in, p, out);
    return out;
}

bool read_tick_request(MobInput& in, std::vector<PlayerInput>& players) {
    if (!read_exact(&in.mob_type, sizeof(in.mob_type))) return false;
    if (!read_exact(&in.entity_id, sizeof(in.entity_id))) return false;
    if (!read_exact(&in.age_ticks, sizeof(in.age_ticks))) return false;
    if (!read_exact(&in.wander_cooldown, sizeof(in.wander_cooldown))) return false;
    if (!read_exact(&in.attack_cooldown, sizeof(in.attack_cooldown))) return false;
    if (!read_exact(&in.aggressive_ticks, sizeof(in.aggressive_ticks))) return false;
    if (!read_exact(&in.look_time, sizeof(in.look_time))) return false;
    if (!read_exact(&in.has_target, sizeof(in.has_target))) return false;
    if (!read_exact(&in.x, sizeof(in.x))) return false;
    if (!read_exact(&in.y, sizeof(in.y))) return false;
    if (!read_exact(&in.z, sizeof(in.z))) return false;
    if (!read_exact(&in.yaw, sizeof(in.yaw))) return false;
    if (!read_exact(&in.pitch, sizeof(in.pitch))) return false;
    if (!read_exact(&in.vx, sizeof(in.vx))) return false;
    if (!read_exact(&in.vy, sizeof(in.vy))) return false;
    if (!read_exact(&in.vz, sizeof(in.vz))) return false;
    if (!read_exact(&in.target_x, sizeof(in.target_x))) return false;
    if (!read_exact(&in.target_y, sizeof(in.target_y))) return false;
    if (!read_exact(&in.target_z, sizeof(in.target_z))) return false;
    if (!read_exact(&in.player_count, sizeof(in.player_count))) return false;

    if (in.player_count > 256) {
        return false;
    }
    players.resize(in.player_count);
    for (uint32_t i = 0; i < in.player_count; ++i) {
        if (!read_exact(&players[i].x, sizeof(players[i].x))) return false;
        if (!read_exact(&players[i].y, sizeof(players[i].y))) return false;
        if (!read_exact(&players[i].z, sizeof(players[i].z))) return false;
        if (!read_exact(&players[i].attackable, sizeof(players[i].attackable))) return false;
    }
    return true;
}

bool write_response(const AiOutput& out) {
    std::vector<uint8_t> payload;
    payload.reserve(kResponsePayloadSize);
    append(payload, out.ok);
    append(payload, out.vx);
    append(payload, out.vz);
    append(payload, out.yaw);
    append(payload, out.pitch);
    append(payload, out.wander_cooldown);
    append(payload, out.aggressive_ticks);
    append(payload, out.look_time);
    append(payload, out.has_target);
    append(payload, out.target_x);
    append(payload, out.target_y);
    append(payload, out.target_z);
    append(payload, out.target_player_index);
    if (payload.size() != kResponsePayloadSize) {
        return false;
    }
    uint32_t size = kResponsePayloadSize;
    return write_exact(&size, sizeof(size)) &&
           write_exact(payload.data(), payload.size());
}

}  // namespace

int main() {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    setvbuf(stdin, nullptr, _IONBF, 0);
    setvbuf(stdout, nullptr, _IONBF, 0);

    while (true) {
        uint8_t command = 0;
        if (!read_exact(&command, 1)) {
            break;
        }
        if (command != kTickCommand) {
            break;
        }

        MobInput input{};
        std::vector<PlayerInput> players;
        if (!read_tick_request(input, players)) {
            break;
        }

        const AiOutput out = tick_ai(input, players);
        if (!write_response(out)) {
            break;
        }
        std::fflush(stdout);
    }

    return 0;
}
