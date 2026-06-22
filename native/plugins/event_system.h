// ============================================================
// PyMC - Paper Plugin Compatibility Layer: Event System
//
// Provides a Bukkit-compatible event bus that allows plugins
// to register listeners for game events and receive callbacks
// when those events fire.
//
// Architecture:
//   EventBus        - Central event dispatch hub
//   Event           - Base event with cancellation support
//   EventPriority   - Listener priority ordering
//   EventHandler    - Type-erased callback wrapper
//
// Event flow:
//   1. PYMC detects game action (player join, block break, etc.)
//   2. Event is created with relevant data
//   3. EventBus fires event to all registered listeners
//   4. Listeners are called in priority order (LOWEST→MONITOR)
//   5. Any listener can cancel the event
//   6. PYMC checks cancellation before proceeding
// ============================================================

#ifndef PYMC_EVENT_SYSTEM_H
#define PYMC_EVENT_SYSTEM_H

#include <string>
#include <map>
#include <vector>
#include <functional>
#include <mutex>
#include <algorithm>
#include <unordered_map>
#include <memory>
#include <any>

namespace pymc {
namespace plugins {

// ===========================================================
// EventPriority
// ===========================================================

enum class EventPriority {
    LOWEST  = 0,   // First to execute; other plugins can override
    LOW     = 1,
    NORMAL  = 2,   // Default priority
    HIGH    = 3,
    HIGHEST = 4,   // Last to modify the event
    MONITOR = 5     // Read-only; should not modify the event
};

// Convert priority to string (for debugging)
inline const char* event_priority_name(EventPriority p) {
    switch (p) {
        case EventPriority::LOWEST:  return "LOWEST";
        case EventPriority::LOW:     return "LOW";
        case EventPriority::NORMAL:  return "NORMAL";
        case EventPriority::HIGH:    return "HIGH";
        case EventPriority::HIGHEST: return "HIGHEST";
        case EventPriority::MONITOR: return "MONITOR";
        default: return "UNKNOWN";
    }
}

// ===========================================================
// Event
// ===========================================================

struct Event {
    // Event type name (e.g. "PlayerJoinEvent", "BlockBreakEvent")
    std::string name;

    // Event data key-value pairs (type-erased for flexibility)
    std::map<std::string, std::string> data;

    // Whether the event has been cancelled
    // Only cancellable events respect this flag
    bool cancelled = false;

    // Whether this event is cancellable
    bool cancellable = true;

    // The plugin that created this event (empty if PYMC-internal)
    std::string source_plugin;

    // Timestamp (game tick when event fired)
    long tick = 0;

    Event() = default;
    explicit Event(const std::string& n, bool cancellable_ = true)
        : name(n), cancellable(cancellable_) {}

    // Convenience data accessors
    void set_data(const std::string& key, const std::string& value) {
        data[key] = value;
    }

    std::string get_data(const std::string& key,
                         const std::string& default_val = "") const {
        auto it = data.find(key);
        return it != data.end() ? it->second : default_val;
    }

    bool has_data(const std::string& key) const {
        return data.find(key) != data.end();
    }

    // Cancel the event
    void cancel() {
        if (cancellable) cancelled = true;
    }

    // Un-cancel the event
    void uncancel() {
        cancelled = false;
    }
};

// ===========================================================
// Common Event Types (Bukkit-compatible names)
// ===========================================================

namespace event_names {

// Player events
constexpr const char* PLAYER_JOIN          = "PlayerJoinEvent";
constexpr const char* PLAYER_QUIT          = "PlayerQuitEvent";
constexpr const char* PLAYER_KICK          = "PlayerKickEvent";
constexpr const char* PLAYER_CHAT          = "AsyncPlayerChatEvent";
constexpr const char* PLAYER_COMMAND       = "PlayerCommandPreprocessEvent";
constexpr const char* PLAYER_MOVE          = "PlayerMoveEvent";
constexpr const char* PLAYER_TELEPORT      = "PlayerTeleportEvent";
constexpr const char* PLAYER_INTERACT      = "PlayerInteractEvent";
constexpr const char* PLAYER_RESPAWN       = "PlayerRespawnEvent";
constexpr const char* PLAYER_DEATH         = "PlayerDeathEvent";
constexpr const char* PLAYER_GAME_MODE     = "PlayerGameModeChangeEvent";
constexpr const char* PLAYER_EXP_CHANGE    = "PlayerExpChangeEvent";
constexpr const char* PLAYER_LEVEL_CHANGE  = "PlayerLevelChangeEvent";
constexpr const char* PLAYER_TOGGLE_FLIGHT = "PlayerToggleFlightEvent";
constexpr const char* PLAYER_TOGGLE_SNEAK  = "PlayerToggleSneakEvent";
constexpr const char* PLAYER_TOGGLE_SPRINT = "PlayerToggleSprintEvent";
constexpr const char* PLAYER_PORTAL        = "PlayerPortalEvent";
constexpr const char* PLAYER_BED_ENTER     = "PlayerBedEnterEvent";
constexpr const char* PLAYER_FISH          = "PlayerFishEvent";
constexpr const char* PLAYER_ITEM_BREAK    = "PlayerItemBreakEvent";
constexpr const char* PLAYER_ITEM_HELD     = "PlayerItemHeldEvent";
constexpr const char* PLAYER_SWAP_HAND     = "PlayerSwapHandItemsEvent";
constexpr const char* PLAYER_EGG_THROW     = "PlayerEggThrowEvent";

// Block events
constexpr const char* BLOCK_BREAK          = "BlockBreakEvent";
constexpr const char* BLOCK_PLACE          = "BlockPlaceEvent";
constexpr const char* BLOCK_DAMAGE         = "BlockDamageEvent";
constexpr const char* BLOCK_BURN           = "BlockBurnEvent";
constexpr const char* BLOCK_IGNITE         = "BlockIgniteEvent";
constexpr const char* BLOCK_REDSTONE       = "BlockRedstoneEvent";
constexpr const char* BLOCK_EXPLODE        = "BlockExplodeEvent";
constexpr const char* BLOCK_DISPENSE       = "BlockDispenseEvent";
constexpr const char* BLOCK_FORM           = "BlockFormEvent";
constexpr const char* BLOCK_SPREAD         = "BlockSpreadEvent";
constexpr const char* BLOCK_FROM_TO        = "BlockFromToEvent";
constexpr const char* BLOCK_PHYSICS        = "BlockPhysicsEvent";
constexpr const char* BLOCK_MULTIPLACE     = "BlockMultiPlaceEvent";
constexpr const char* SIGN_CHANGE          = "SignChangeEvent";
constexpr const char* NOTE_PLAY            = "NotePlayEvent";

// Entity events
constexpr const char* ENTITY_DAMAGE        = "EntityDamageEvent";
constexpr const char* ENTITY_DAMAGE_BY_ENTITY = "EntityDamageByEntityEvent";
constexpr const char* ENTITY_DEATH         = "EntityDeathEvent";
constexpr const char* ENTITY_SPAWN         = "EntitySpawnEvent";
constexpr const char* ENTITY_REMOVE        = "EntityRemoveEvent";
constexpr const char* ENTITY_EXPLODE       = "EntityExplodeEvent";
constexpr const char* ENTITY_TARGET        = "EntityTargetEvent";
constexpr const char* ENTITY_SHOOT_BOW     = "EntityShootBowEvent";
constexpr const char* ENTITY_REGAIN_HEALTH = "EntityRegainHealthEvent";
constexpr const char* ENTITY_PORTAL_ENTER  = "EntityPortalEnterEvent";
constexpr const char* PROJECTILE_HIT       = "ProjectileHitEvent";
constexpr const char* PROJECTILE_LAUNCH    = "ProjectileLaunchEvent";
constexpr const char* FOOD_LEVEL_CHANGE    = "FoodLevelChangeEvent";

// World events
constexpr const char* CHUNK_LOAD           = "ChunkLoadEvent";
constexpr const char* CHUNK_UNLOAD         = "ChunkUnloadEvent";
constexpr const char* CHUNK_POPULATE        = "ChunkPopulateEvent";
constexpr const char* WORLD_LOAD           = "WorldLoadEvent";
constexpr const char* WORLD_UNLOAD         = "WorldUnloadEvent";
constexpr const char* WORLD_SAVE           = "WorldSaveEvent";
constexpr const char* WEATHER_CHANGE       = "WeatherChangeEvent";
constexpr const char* THUNDER_CHANGE       = "ThunderChangeEvent";
constexpr const char* TIME_CHANGE          = "TimeChangeEvent";

// Server events
constexpr const char* SERVER_COMMAND       = "ServerCommandEvent";
constexpr const char* REMOTE_COMMAND       = "RemoteServerCommandEvent";
constexpr const char* PLUGIN_ENABLE        = "PluginEnableEvent";
constexpr const char* PLUGIN_DISABLE       = "PluginDisableEvent";

// Inventory events
constexpr const char* INVENTORY_CLICK      = "InventoryClickEvent";
constexpr const char* INVENTORY_OPEN       = "InventoryOpenEvent";
constexpr const char* INVENTORY_CLOSE      = "InventoryCloseEvent";
constexpr const char* INVENTORY_DRAG       = "InventoryDragEvent";
constexpr const char* CRAFT_ITEM           = "CraftItemEvent";
constexpr const char* BREW_EVENT           = "BrewEvent";
constexpr const char* FURNACE_SMELT        = "FurnaceSmeltEvent";
constexpr const char* FURNACE_BURN         = "FurnaceBurnEvent";
constexpr const char* PREPARE_ANVIL        = "PrepareAnvilEvent";
constexpr const char* PREPARE_CRAFT        = "PrepareItemCraftEvent";

// Vehicle events
constexpr const char* VEHICLE_CREATE       = "VehicleCreateEvent";
constexpr const char* VEHICLE_DESTROY      = "VehicleDestroyEvent";
constexpr const char* VEHICLE_ENTER        = "VehicleEnterEvent";
constexpr const char* VEHICLE_EXIT         = "VehicleExitEvent";
constexpr const char* VEHICLE_MOVE         = "VehicleMoveEvent";
constexpr const char* VEHICLE_DAMAGE       = "VehicleDamageEvent";
constexpr const char* VEHICLE_COLLISION    = "VehicleEntityCollisionEvent";

// Hanging events
constexpr const char* HANGING_BREAK        = "HangingBreakEvent";
constexpr const char* HANGING_PLACE        = "HangingPlaceEvent";

}  // namespace event_names

// ===========================================================
// EventHandler
// ===========================================================

// Type-erased event handler that wraps a std::function
class EventHandler {
public:
    using Callback = std::function<void(Event&)>;

    EventHandler(EventPriority priority, Callback callback,
                 const std::string& plugin_name = "")
        : priority_(priority)
        , callback_(std::move(callback))
        , plugin_name_(plugin_name)
        , active_(true)
    {}

    // Call the handler
    void operator()(Event& event) {
        if (active_) {
            callback_(event);
        }
    }

    EventPriority priority() const { return priority_; }
    const std::string& plugin_name() const { return plugin_name_; }
    bool is_active() const { return active_; }
    void set_active(bool a) { active_ = a; }

    // Comparison for priority ordering
    bool operator<(const EventHandler& other) const {
        return static_cast<int>(priority_) < static_cast<int>(other.priority_);
    }

private:
    EventPriority priority_;
    Callback callback_;
    std::string plugin_name_;
    bool active_;
};

// ===========================================================
// EventBus
// ===========================================================

class EventBus {
public:
    EventBus() = default;
    ~EventBus() = default;

    // --- Listener Registration ---

    // Register a listener for a specific event type
    // Returns: handler ID (for later unregistration)
    int register_listener(const std::string& event_name,
                          EventPriority priority,
                          EventHandler::Callback handler,
                          const std::string& plugin_name = "");

    // Convenience: register at NORMAL priority
    int register_listener(const std::string& event_name,
                          EventHandler::Callback handler,
                          const std::string& plugin_name = "");

    // Unregister a specific handler by ID
    bool unregister_handler(int handler_id);

    // Unregister all handlers for a plugin
    void unregister_all(const std::string& plugin_name);

    // Unregister all handlers for a specific event
    void unregister_event(const std::string& event_name);

    // --- Event Firing ---

    // Fire an event to all registered listeners in priority order
    void fire_event(Event& event);

    // Fire an event (copy, returns the event after processing)
    Event fire_event_copy(const Event& event);

    // --- Query ---

    // Check if any listeners are registered for an event
    bool has_listeners(const std::string& event_name) const;

    // Get number of listeners for an event
    size_t listener_count(const std::string& event_name) const;

    // Get total number of listeners across all events
    size_t total_listener_count() const;

    // Get all event names that have listeners
    std::vector<std::string> registered_event_names() const;

private:
    // Re-sort handlers for an event (called after registration changes)
    void sort_handlers(const std::string& event_name);

private:
    // event_name -> list of (handler_id, handler)
    std::unordered_map<std::string,
                       std::vector<std::pair<int, EventHandler>>> handlers_;

    // Next handler ID
    int next_handler_id_ = 0;

    // Mutex for thread safety
    mutable std::mutex mutex_;
};

// ===========================================================
// Inline Implementations
// ===========================================================

inline int EventBus::register_listener(
    const std::string& event_name,
    EventPriority priority,
    EventHandler::Callback handler,
    const std::string& plugin_name)
{
    std::lock_guard<std::mutex> lock(mutex_);
    int id = next_handler_id_++;
    auto& list = handlers_[event_name];
    list.emplace_back(id, EventHandler(priority, std::move(handler), plugin_name));
    sort_handlers(event_name);
    return id;
}

inline int EventBus::register_listener(
    const std::string& event_name,
    EventHandler::Callback handler,
    const std::string& plugin_name)
{
    return register_listener(event_name, EventPriority::NORMAL,
                             std::move(handler), plugin_name);
}

inline bool EventBus::unregister_handler(int handler_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& [name, list] : handlers_) {
        auto it = std::remove_if(list.begin(), list.end(),
            [handler_id](const auto& pair) {
                return pair.first == handler_id;
            });
        if (it != list.end()) {
            list.erase(it, list.end());
            return true;
        }
    }
    return false;
}

inline void EventBus::unregister_all(const std::string& plugin_name) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& [name, list] : handlers_) {
        auto it = std::remove_if(list.begin(), list.end(),
            [&plugin_name](const auto& pair) {
                return pair.second.plugin_name() == plugin_name;
            });
        list.erase(it, list.end());
    }
}

inline void EventBus::unregister_event(const std::string& event_name) {
    std::lock_guard<std::mutex> lock(mutex_);
    handlers_.erase(event_name);
}

inline void EventBus::fire_event(Event& event) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = handlers_.find(event.name);
    if (it == handlers_.end()) return;

    for (auto& [id, handler] : it->second) {
        if (!handler.is_active()) continue;
        // MONITOR handlers should not modify the event,
        // but we can't enforce this in C++ - it's a convention
        handler(event);
        // If event is cancelled and handler is MONITOR, still fire
        // (MONITOR is for reading, not cancelling)
    }
}

inline Event EventBus::fire_event_copy(const Event& event) {
    Event copy = event;
    fire_event(copy);
    return copy;
}

inline bool EventBus::has_listeners(const std::string& event_name) const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = handlers_.find(event_name);
    return it != handlers_.end() && !it->second.empty();
}

inline size_t EventBus::listener_count(const std::string& event_name) const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = handlers_.find(event_name);
    return it != handlers_.end() ? it->second.size() : 0;
}

inline size_t EventBus::total_listener_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    size_t total = 0;
    for (const auto& [name, list] : handlers_) {
        total += list.size();
    }
    return total;
}

inline std::vector<std::string> EventBus::registered_event_names() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> names;
    names.reserve(handlers_.size());
    for (const auto& [name, list] : handlers_) {
        if (!list.empty()) {
            names.push_back(name);
        }
    }
    return names;
}

inline void EventBus::sort_handlers(const std::string& event_name) {
    auto it = handlers_.find(event_name);
    if (it == handlers_.end()) return;
    std::stable_sort(it->second.begin(), it->second.end(),
        [](const auto& a, const auto& b) {
            return a.second < b.second;
        });
}

}  // namespace plugins
}  // namespace pymc

#endif  // PYMC_EVENT_SYSTEM_H
