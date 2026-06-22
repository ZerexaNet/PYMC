// ============================================================
// PyMC - Mod Compatibility Layer: Fabric API Bridge
//
// Maps Fabric API calls to PYMC internal operations.
// This provides the translation layer between Fabric mod API
// calls (via Fabric API / Fabric Loader) and PYMC's C++/Python
// server operations.
//
// Architecture:
//   FabricAPIBridge
//     ├── Registry Bridge
//     │   ├── Block registration  -> PYMC block registry
//     │   ├── Item registration   -> PYMC item registry
//     │   ├── Biome registration  -> PYMC biome registry
//     │   └── Entity registration -> PYMC entity registry
//     ├── Event Bridge
//     │   ├── Server lifecycle    -> PYMC server events
//     │   ├── Player events       -> PYMC player events
//     │   ├── Block events        -> PYMC block events
//     │   ├── Chat events         -> PYMC chat events
//     │   └── Entity events       -> PYMC entity events
//     ├── Networking Bridge
//     │   ├── Server->Client packets -> PYMC packet writer
//     │   └── Client->Server packets -> PYMC packet handler
//     └── Resource Bridge
//         ├── Resource reload     -> PYMC resource system
//         └── Tag management      -> PYMC tag system
//
// Fabric API mapping:
//   net.fabricmc.fabric.api           -> PYMC operations
//   -----------------------------------------------
//   FabricBlockRegistry               -> register_block()
//   FabricItemRegistry                -> register_item()
//   FabricBiomeRegistry               -> register_biome()
//   ServerLifecycleEvents             -> on_server_start/stop()
//   ServerPlayerEvents                -> on_player_join/leave()
//   PlayerBlockBreakEvents            -> on_block_break()
//   BlockPlaceCallback                -> on_block_place()
//   ServerMessageEvents               -> on_chat_message()
//   FabricEntityTypes                 -> register_entity_type()
//   EntityDamageCallback              -> on_entity_damage()
//   PlayerDeathCallback               -> on_player_death()
//   CraftEvents                       -> on_craft()
// ============================================================

#ifndef PYMC_FABRIC_API_H
#define PYMC_FABRIC_API_H

#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <functional>
#include <memory>
#include <mutex>
#include <cstdint>
#include <optional>

namespace pymc {
namespace mods {

// ===========================================================
// Fabric Block Properties
// ===========================================================

struct FabricBlockProperties {
    std::string material = "stone";          // Material type
    std::string sound_group = "stone";       // Block sound group
    float hardness = 1.0f;                   // Block hardness (mining time)
    float resistance = 1.0f;                 // Blast resistance
    float slipperiness = 0.6f;              // Friction multiplier
    int light_level = 0;                     // Emitted light level (0-15)
    bool is_opaque = true;                   // Opaque blocks block light
    bool is_solid = true;                    // Solid blocks support other blocks
    bool is_full_cube = true;               // Full cube blocks have standard collision
    bool has_collision = true;              // Whether entities collide with this block
    bool is_air = false;                     // Air blocks are non-solid
    std::map<std::string, std::string> custom_properties;  // Custom block state properties

    // Convert to generic property map for PYMC
    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["material"] = material;
        props["sound_group"] = sound_group;
        props["hardness"] = std::to_string(hardness);
        props["resistance"] = std::to_string(resistance);
        props["slipperiness"] = std::to_string(slipperiness);
        props["light_level"] = std::to_string(light_level);
        props["is_opaque"] = is_opaque ? "true" : "false";
        props["is_solid"] = is_solid ? "true" : "false";
        props["is_full_cube"] = is_full_cube ? "true" : "false";
        props["has_collision"] = has_collision ? "true" : "false";
        props["is_air"] = is_air ? "true" : "false";
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Fabric Item Properties
// ===========================================================

struct FabricItemProperties {
    std::string group = "";                  // Item group (creative tab)
    int max_count = 64;                      // Max stack size
    int max_damage = 0;                      // Max durability (0 = not damageable)
    bool is_fireproof = false;              // Fireproof items don't burn
    bool is_food = false;                   // Whether this is a food item
    float food_nutrition = 0.0f;            // Food nutrition value
    float food_saturation = 0.0f;           // Food saturation modifier
    std::string rarity = "common";           // Item rarity
    std::map<std::string, std::string> custom_properties;

    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["group"] = group;
        props["max_count"] = std::to_string(max_count);
        props["max_damage"] = std::to_string(max_damage);
        props["is_fireproof"] = is_fireproof ? "true" : "false";
        props["is_food"] = is_food ? "true" : "false";
        props["food_nutrition"] = std::to_string(food_nutrition);
        props["food_saturation"] = std::to_string(food_saturation);
        props["rarity"] = rarity;
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Fabric Biome Properties
// ===========================================================

struct FabricBiomeProperties {
    float temperature = 0.5f;                // Biome temperature
    float downfall = 0.5f;                   // Rainfall amount
    std::string precipitation = "rain";      // rain, snow, or none
    std::string category = "plains";         // Biome category
    float depth = 0.125f;                    // Biome depth (for generation)
    float scale = 0.05f;                     // Biome scale (for generation)
    int grass_color = -1;                    // Override grass color (-1 = default)
    int foliage_color = -1;                  // Override foliage color (-1 = default)
    int water_color = 4159204;               // Water color
    int water_fog_color = 329011;            // Water fog color
    std::map<std::string, std::string> custom_properties;

    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["temperature"] = std::to_string(temperature);
        props["downfall"] = std::to_string(downfall);
        props["precipitation"] = precipitation;
        props["category"] = category;
        props["depth"] = std::to_string(depth);
        props["scale"] = std::to_string(scale);
        props["grass_color"] = std::to_string(grass_color);
        props["foliage_color"] = std::to_string(foliage_color);
        props["water_color"] = std::to_string(water_color);
        props["water_fog_color"] = std::to_string(water_fog_color);
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Fabric Entity Properties
// ===========================================================

struct FabricEntityProperties {
    bool can_spawn_far_from_player = false;  // Can spawn far from player
    int spawn_group = 0;                     // Spawn group ID
    float hit_box_width = 0.6f;             // Entity hitbox width
    float hit_box_height = 1.8f;            // Entity hitbox height
    int tracking_tick_interval = 3;          // Sync interval (ticks)
    int tracking_update_distance = 5;        // Sync distance (chunks)
    bool is_summonable = true;              // Can be summoned with /summon
    std::map<std::string, std::string> custom_properties;

    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["can_spawn_far_from_player"] = can_spawn_far_from_player ? "true" : "false";
        props["spawn_group"] = std::to_string(spawn_group);
        props["hit_box_width"] = std::to_string(hit_box_width);
        props["hit_box_height"] = std::to_string(hit_box_height);
        props["tracking_tick_interval"] = std::to_string(tracking_tick_interval);
        props["tracking_update_distance"] = std::to_string(tracking_update_distance);
        props["is_summonable"] = is_summonable ? "true" : "false";
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Fabric Event Callbacks
// ===========================================================

// Callback type for Fabric-style events (functional interfaces)
using FabricServerStartCallback = std::function<void()>;
using FabricServerStopCallback = std::function<void()>;
using FabricPlayerJoinCallback = std::function<void(const std::string& player_name)>;
using FabricPlayerLeaveCallback = std::function<void(const std::string& player_name)>;
using FabricBlockBreakCallback = std::function<bool(int x, int y, int z, const std::string& player)>;
using FabricBlockPlaceCallback = std::function<bool(int x, int y, int z, const std::string& block_id, const std::string& player)>;
using FabricChatCallback = std::function<bool(const std::string& message, const std::string& player)>;
using FabricPlayerDeathCallback = std::function<void(const std::string& player, const std::string& cause)>;
using FabricCraftCallback = std::function<void(const std::string& result_item, const std::string& player)>;
using FabricEntityDamageCallback = std::function<bool(const std::string& entity, double damage, const std::string& source)>;

// ===========================================================
// FabricAPIBridge
// ===========================================================

class FabricAPIBridge {
public:
    FabricAPIBridge();
    ~FabricAPIBridge();

    // --- Registry Bridge ---
    // Maps Fabric ServerModContainer / Registry operations to PYMC registries

    // Register a custom block
    // Maps: FabricBlockRegistry.register() -> PYMC block registry
    void register_block(const std::string& block_id, const std::map<std::string, std::string>& properties);

    // Register a custom item
    // Maps: FabricItemRegistry.register() -> PYMC item registry
    void register_item(const std::string& item_id, const std::map<std::string, std::string>& properties);

    // Register a custom biome
    // Maps: FabricBiomeRegistry.register() -> PYMC biome registry
    void register_biome(const std::string& biome_id, const std::map<std::string, std::string>& properties);

    // Register a custom entity type
    // Maps: FabricEntityTypes.register() -> PYMC entity registry
    void register_entity_type(const std::string& entity_id, const std::map<std::string, std::string>& properties);

    // Typed registration helpers (provide structured properties)
    void register_block(const std::string& block_id, const FabricBlockProperties& props);
    void register_item(const std::string& item_id, const FabricItemProperties& props);
    void register_biome(const std::string& biome_id, const FabricBiomeProperties& props);
    void register_entity_type(const std::string& entity_id, const FabricEntityProperties& props);

    // --- Event Bridge ---
    // Maps Fabric events to PYMC events

    // ServerLifecycleEvents.SERVER_STARTING / SERVER_STARTED
    void on_server_start();

    // ServerLifecycleEvents.SERVER_STOPPING / SERVER_STOPPED
    void on_server_stop();

    // ServerPlayerEvents.PLAYER_JOIN (after authentication)
    void on_player_join(const std::string& player_name);

    // ServerPlayerEvents.PLAYER_LEAVE / PLAYER_DISCONNECT
    void on_player_leave(const std::string& player_name);

    // PlayerBlockBreakEvents.BEFORE / AFTER
    // Returns: true if the break should be allowed (before event can cancel)
    bool on_block_break(int x, int y, int z, const std::string& player);

    // BlockPlaceCallback.BLOCK_PLACE
    // Returns: true if the place should be allowed
    bool on_block_place(int x, int y, int z, const std::string& block_id, const std::string& player);

    // ServerMessageEvents.ALLOW_CHAT_MESSAGE / CHAT_MESSAGE
    // Returns: true if the message should be sent
    bool on_chat_message(const std::string& message, const std::string& player);

    // PlayerDeathCallback (custom Fabric event)
    void on_player_death(const std::string& player, const std::string& cause);

    // CraftEvents (custom Fabric event)
    void on_craft(const std::string& result_item, const std::string& player);

    // EntityDamageCallback (custom Fabric event)
    // Returns: true if the damage should be applied
    bool on_entity_damage(const std::string& entity, double damage, const std::string& source);

    // --- Callback Registration ---
    // Register Fabric-style event callbacks (mirrors Fabric API registration)

    void register_server_start_callback(FabricServerStartCallback cb);
    void register_server_stop_callback(FabricServerStopCallback cb);
    void register_player_join_callback(FabricPlayerJoinCallback cb);
    void register_player_leave_callback(FabricPlayerLeaveCallback cb);
    void register_block_break_callback(FabricBlockBreakCallback cb);
    void register_block_place_callback(FabricBlockPlaceCallback cb);
    void register_chat_callback(FabricChatCallback cb);
    void register_player_death_callback(FabricPlayerDeathCallback cb);
    void register_craft_callback(FabricCraftCallback cb);
    void register_entity_damage_callback(FabricEntityDamageCallback cb);

    // --- Networking Bridge ---
    // Maps Fabric networking API to PYMC packet operations

    // Register a server->client packet type
    void register_server_packet(const std::string& channel_id, const std::string& packet_class);

    // Register a client->server packet handler
    void register_client_packet_handler(const std::string& channel_id,
                                         std::function<void(const std::string& player,
                                                           const std::vector<uint8_t>& data)> handler);

    // Send a packet to a specific player
    void send_packet_to_player(const std::string& player, const std::string& channel_id,
                               const std::vector<uint8_t>& data);

    // Send a packet to all players
    void send_packet_to_all(const std::string& channel_id, const std::vector<uint8_t>& data);

    // --- Resource Bridge ---
    // Maps Fabric resource reload API to PYMC resource system

    // Register a resource reload listener
    void register_resource_reload_listener(const std::string& listener_id,
                                            std::function<void()> on_reload);

    // Trigger resource reload
    void reload_resources();

    // --- Query ---

    // Get registered block IDs
    std::vector<std::string> get_registered_blocks() const;

    // Get registered item IDs
    std::vector<std::string> get_registered_items() const;

    // Get registered biome IDs
    std::vector<std::string> get_registered_biomes() const;

    // Get registered entity type IDs
    std::vector<std::string> get_registered_entity_types() const;

    // Check if a block is registered
    bool is_block_registered(const std::string& block_id) const;

    // Check if an item is registered
    bool is_item_registered(const std::string& item_id) const;

private:
    // Registered blocks (block_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> blocks_;

    // Registered items (item_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> items_;

    // Registered biomes (biome_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> biomes_;

    // Registered entity types (entity_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> entity_types_;

    // Event callbacks
    std::vector<FabricServerStartCallback> server_start_callbacks_;
    std::vector<FabricServerStopCallback> server_stop_callbacks_;
    std::vector<FabricPlayerJoinCallback> player_join_callbacks_;
    std::vector<FabricPlayerLeaveCallback> player_leave_callbacks_;
    std::vector<FabricBlockBreakCallback> block_break_callbacks_;
    std::vector<FabricBlockPlaceCallback> block_place_callbacks_;
    std::vector<FabricChatCallback> chat_callbacks_;
    std::vector<FabricPlayerDeathCallback> player_death_callbacks_;
    std::vector<FabricCraftCallback> craft_callbacks_;
    std::vector<FabricEntityDamageCallback> entity_damage_callbacks_;

    // Networking
    std::unordered_map<std::string, std::vector<std::pair<std::string,
        std::function<void(const std::string&, const std::vector<uint8_t>&)>>>> client_packet_handlers_;

    // Resource reload listeners
    std::unordered_map<std::string, std::function<void()>> resource_reload_listeners_;

    // Mutex for thread safety
    mutable std::mutex mutex_;
};

}  // namespace mods
}  // namespace pymc

#endif  // PYMC_FABRIC_API_H
