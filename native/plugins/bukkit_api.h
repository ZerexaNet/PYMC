// ============================================================
// PyMC - Paper Plugin Compatibility Layer: Bukkit API Mappings
//
// Maps Bukkit API classes to PYMC internal operations.
// This provides the translation layer between Java Bukkit API
// calls and PYMC's C++/Python server operations.
//
// Architecture:
//   BukkitServer   → PYMC MinecraftServer calls
//   BukkitPlayer   → PYMC Connection operations
//   BukkitWorld    → PYMC WorldStorage + terrain operations
//   BukkitBlock    → PYMC block state operations
//   BukkitItem     → PYMC inventory operations
//   BukkitEntity   → PYMC entity operations
// ============================================================

#ifndef PYMC_BUKKIT_API_H
#define PYMC_BUKKIT_API_H

#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <memory>
#include <functional>
#include <cstdint>
#include <optional>
#include <cmath>

namespace pymc {
namespace plugins {

// ===========================================================
// Basic Types
// ===========================================================

struct Location {
    std::string world_name;
    double x, y, z;
    float pitch, yaw;

    Location()
        : x(0), y(64), z(0), pitch(0), yaw(0) {}

    Location(double x_, double y_, double z_)
        : x(x_), y(y_), z(z_), pitch(0), yaw(0) {}

    Location(const std::string& world, double x_, double y_, double z_)
        : world_name(world), x(x_), y(y_), z(z_), pitch(0), yaw(0) {}

    double distance(const Location& other) const {
        double dx = x - other.x;
        double dy = y - other.y;
        double dz = z - other.z;
        return std::sqrt(dx * dx + dy * dy + dz * dz);
    }

    int block_x() const { return static_cast<int>(std::floor(x)); }
    int block_y() const { return static_cast<int>(std::floor(y)); }
    int block_z() const { return static_cast<int>(std::floor(z)); }
};

enum class GameMode {
    SURVIVAL = 0,
    CREATIVE = 1,
    ADVENTURE = 2,
    SPECTATOR = 3
};

enum class Difficulty {
    PEACEFUL = 0,
    EASY = 1,
    NORMAL = 2,
    HARD = 3
};

enum class WeatherType {
    CLEAR,
    RAIN,
    THUNDER
};

enum class SoundCategory {
    MASTER,
    MUSIC,
    RECORDS,
    WEATHER,
    BLOCKS,
    HOSTILE,
    NEUTRAL,
    PLAYERS,
    AMBIENT,
    VOICE
};

// ===========================================================
// BlockData
// ===========================================================

struct BlockData {
    std::string material;       // e.g. "minecraft:stone"
    std::map<std::string, std::string> properties;  // block state properties

    BlockData() = default;
    explicit BlockData(const std::string& mat) : material(mat) {}

    bool is_air() const {
        return material == "minecraft:air" || material == "minecraft:cave_air";
    }

    // Get a block state property
    std::optional<std::string> get_property(const std::string& key) const {
        auto it = properties.find(key);
        if (it != properties.end()) return it->second;
        return std::nullopt;
    }

    // Set a block state property
    void set_property(const std::string& key, const std::string& value) {
        properties[key] = value;
    }
};

// ===========================================================
// BukkitBlock
// ===========================================================

class BukkitBlock {
public:
    BukkitBlock(const Location& loc, const BlockData& data)
        : location_(loc), data_(data) {}

    // Block position
    int x() const { return location_.block_x(); }
    int y() const { return location_.block_y(); }
    int z() const { return location_.block_z(); }
    const Location& location() const { return location_; }

    // Block data
    const BlockData& block_data() const { return data_; }
    void set_block_data(const BlockData& data) { data_ = data; }

    // Convenience
    const std::string& type() const { return data_.material; }
    bool is_air() const { return data_.is_air(); }

private:
    Location location_;
    BlockData data_;
};

// ===========================================================
// BukkitPlayer
// ===========================================================

class BukkitPlayer {
public:
    explicit BukkitPlayer(const std::string& uuid, const std::string& name)
        : uuid_(uuid), name_(name), location_("world", 0, 64, 0)
        , health_(20.0), max_health_(20.0), food_level_(20)
        , game_mode_(GameMode::SURVIVAL), online_(true)
        , experience_(0), experience_level_(0)
        , flying_(false), allow_flight_(false)
    {}

    // Identity
    const std::string& uuid() const { return uuid_; }
    const std::string& name() const { return name_; }

    // Location
    const Location& location() const { return location_; }
    void set_location(const Location& loc) { location_ = loc; }

    // Teleport the player
    void teleport(const Location& loc);

    // Health
    double health() const { return health_; }
    void set_health(double h) { health_ = std::max(0.0, std::min(h, max_health_)); }
    double max_health() const { return max_health_; }

    // Food
    int food_level() const { return food_level_; }
    void set_food_level(int f) { food_level_ = std::max(0, std::min(f, 20)); }

    // Game mode
    GameMode game_mode() const { return game_mode_; }
    void set_game_mode(GameMode mode) { game_mode_ = mode; }

    // Experience
    int experience_level() const { return experience_level_; }
    void set_experience_level(int lvl) { experience_level_ = std::max(0, lvl); }
    float experience() const { return experience_; }
    void set_experience(float exp) { experience_ = std::max(0.0f, std::min(exp, 1.0f)); }

    // Flight
    bool is_flying() const { return flying_; }
    void set_flying(bool fly) { flying_ = fly; }
    bool get_allow_flight() const { return allow_flight_; }
    void set_allow_flight(bool allow) { allow_flight_ = allow; }

    // Online status
    bool is_online() const { return online_; }
    void set_online(bool o) { online_ = o; }

    // Communication
    void send_message(const std::string& msg);
    void send_title(const std::string& title, const std::string& subtitle,
                    int fade_in = 10, int stay = 70, int fade_out = 20);
    void send_action_bar(const std::string& msg);

    // Inventory
    void give_item(const std::string& material, int amount = 1);
    void clear_inventory();

    // Permissions
    bool has_permission(const std::string& perm) const;
    void set_permission(const std::string& perm, bool value);

private:
    std::string uuid_;
    std::string name_;
    Location location_;
    double health_;
    double max_health_;
    int food_level_;
    GameMode game_mode_;
    bool online_;
    float experience_;
    int experience_level_;
    bool flying_;
    bool allow_flight_;
    std::map<std::string, bool> permissions_;
};

// ===========================================================
// BukkitWorld
// ===========================================================

class BukkitWorld {
public:
    explicit BukkitWorld(const std::string& name)
        : name_(name), difficulty_(Difficulty::NORMAL)
        , time_(0), full_time_(0), weather_(WeatherType::CLEAR)
        , thundering_(false), weather_duration_(0)
        , spawn_location_(name, 0, 64, 0)
        , sea_level_(63), min_height_(-64), max_height_(319)
    {}

    // Identity
    const std::string& name() const { return name_; }

    // World properties
    Difficulty difficulty() const { return difficulty_; }
    void set_difficulty(Difficulty d) { difficulty_ = d; }

    int sea_level() const { return sea_level_; }
    int min_height() const { return min_height_; }
    int max_height() const { return max_height_; }

    // Time
    long time() const { return time_; }
    void set_time(long t) { time_ = t % 24000; }
    long full_time() const { return full_time_; }
    void set_full_time(long t) { full_time_ = t; }

    // Weather
    WeatherType weather() const { return weather_; }
    void set_weather(WeatherType w) { weather_ = w; }
    bool is_thundering() const { return thundering_; }
    void set_thundering(bool t) { thundering_ = t; }
    int weather_duration() const { return weather_duration_; }
    void set_weather_duration(int d) { weather_duration_ = d; }

    // Spawn
    const Location& spawn_location() const { return spawn_location_; }
    void set_spawn_location(const Location& loc) { spawn_location_ = loc; }

    // Block operations → PYMC WorldStorage + terrain operations
    BukkitBlock get_block_at(int x, int y, int z);
    void set_block_at(int x, int y, int z, const BlockData& data);

    // Chunk operations → PYMC chunk system
    bool is_chunk_loaded(int cx, int cz) const;
    bool load_chunk(int cx, int cz);
    void unload_chunk(int cx, int cz);

    // Entity operations
    void spawn_entity(const std::string& entity_type, const Location& loc);
    std::vector<std::string> get_entities_in_chunk(int cx, int cz) const;

    // Player operations
    std::vector<std::shared_ptr<BukkitPlayer>> get_players() const;

    // Height
    int get_highest_block_y_at(int x, int z);

    // Biome
    std::string get_biome_at(int x, int z) const;
    void set_biome_at(int x, int z, const std::string& biome);

private:
    std::string name_;
    Difficulty difficulty_;
    long time_;
    long full_time_;
    WeatherType weather_;
    bool thundering_;
    int weather_duration_;
    Location spawn_location_;
    int sea_level_;
    int min_height_;
    int max_height_;
};

// ===========================================================
// BukkitServer
// ===========================================================

class BukkitServer {
public:
    BukkitServer()
        : server_name_("PYMC"), server_version_("1.21.1")
        , api_version_("1.21"), max_players_(20)
        , motd_("A PYMC Server"), tps_(20.0)
    {}

    // Server info
    const std::string& server_name() const { return server_name_; }
    const std::string& server_version() const { return server_version_; }
    const std::string& api_version() const { return api_version_; }
    const std::string& motd() const { return motd_; }
    void set_motd(const std::string& m) { motd_ = m; }

    // Players → PYMC Connection operations
    std::vector<std::string> get_online_players() const;
    std::shared_ptr<BukkitPlayer> get_player(const std::string& name) const;
    std::shared_ptr<BukkitPlayer> get_player_by_uuid(const std::string& uuid) const;
    int online_player_count() const;
    int max_players() const { return max_players_; }
    void set_max_players(int m) { max_players_ = m; }

    // Broadcast
    void broadcast_message(const std::string& msg);
    void broadcast_message(const std::string& msg, const std::string& permission);

    // Commands → PYMC command dispatcher
    bool dispatch_command(const std::string& cmd);
    bool dispatch_command(const std::string& cmd, const std::string& sender);

    // Worlds → PYMC WorldStorage
    std::vector<std::string> get_world_names() const;
    std::shared_ptr<BukkitWorld> get_world(const std::string& name) const;
    std::shared_ptr<BukkitWorld> create_world(const std::string& name);

    // Server properties
    double tps() const { return tps_; }
    bool is_running() const { return running_; }
    void shutdown();
    void set_shutdown(bool s) { running_ = !s; }

    // Plugin management
    bool is_plugin_enabled(const std::string& name) const;

    // Scheduler (simplified - maps to PYMC's tick loop)
    using TaskCallback = std::function<void()>;
    int schedule_sync_delayed_task(TaskCallback task, long delay_ticks = 0);
    int schedule_sync_repeating_task(TaskCallback task, long delay_ticks, long period_ticks);
    void cancel_task(int task_id);
    void cancel_all_tasks();

private:
    std::string server_name_;
    std::string server_version_;
    std::string api_version_;
    int max_players_;
    std::string motd_;
    double tps_;
    bool running_ = true;

    // Player registry (uuid -> player)
    mutable std::unordered_map<std::string, std::shared_ptr<BukkitPlayer>> players_;

    // World registry (name -> world)
    mutable std::unordered_map<std::string, std::shared_ptr<BukkitWorld>> worlds_;

    // Scheduler
    int next_task_id_ = 0;
    struct ScheduledTask {
        int id;
        TaskCallback callback;
        long execute_tick;
        long period;  // 0 = one-shot
        bool sync;    // always true for now
    };
    std::vector<ScheduledTask> scheduled_tasks_;
};

}  // namespace plugins
}  // namespace pymc

#endif  // PYMC_BUKKIT_API_H
