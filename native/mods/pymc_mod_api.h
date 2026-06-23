// ============================================================
// PyMC - Native Mod API: C API Bridge
//
// Defines the C API for PYMC native mods, exposed via ctypes
// to Python. This is the interface that PYMC Python mods use
// to interact with the C++ server core.
//
// PYMC provides a Python-native mod API. It does NOT support
// Java Fabric/Forge/NeoForge/Quilt mods, as those require
// JVM + Mixin bytecode injection which cannot be replicated
// in a Python/C++ server.
//
// Architecture:
//   C API Functions (extern "C")
//     ├── Registration
//     │   ├── pymc_mod_register_block()       - Custom blocks
//     │   ├── pymc_mod_register_item()        - Custom items
//     │   ├── pymc_mod_register_biome()       - Custom biomes
//     │   └── pymc_mod_register_entity_type() - Custom entities
//     ├── Events
//     │   ├── pymc_mod_register_event_listener() - Event callbacks
//     │   └── pymc_mod_fire_event()              - Fire events
//     └── Server Query
//         ├── pymc_mod_get_server_tps()       - Server TPS
//         ├── pymc_mod_get_online_players()   - Online count
//         ├── pymc_mod_broadcast_message()    - Broadcast chat
//         └── pymc_mod_dispatch_command()     - Execute command
// ============================================================

#ifndef PYMC_MOD_API_H
#define PYMC_MOD_API_H

#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

// ===========================================================
// Property Structures
// ===========================================================

// Block properties for registration
struct BlockProperties {
    const char* material;       // e.g. "stone", "wood", "metal"
    const char* sound_group;    // e.g. "stone", "wood", "grass"
    float hardness;             // Mining hardness (0 = instant, -1 = unbreakable)
    float resistance;           // Blast resistance
    float slipperiness;         // Friction multiplier (0.0 - 1.0)
    int   light_level;          // Emitted light level (0-15)
    int   is_opaque;            // Whether block blocks light
    int   is_solid;             // Whether block supports other blocks
    int   has_collision;        // Whether entities collide with block
    int   is_air;               // Whether this is an air-like block
};

// Item properties for registration
struct ItemProperties {
    const char* group;          // Item group / creative tab
    int   max_count;            // Max stack size (1-64)
    int   max_damage;           // Max durability (0 = not damageable)
    int   is_fireproof;         // Whether item resists fire
    int   is_food;              // Whether this is a food item
    float food_nutrition;       // Food nutrition value
    float food_saturation;      // Food saturation modifier
    const char* rarity;         // "common", "uncommon", "rare", "epic"
};

// ===========================================================
// Registration Functions
// ===========================================================

// Register a custom block with the server
// block_id: unique identifier (e.g. "mymod:custom_block")
// props: block property struct
// Returns: 0 on success, non-zero on failure
int pymc_mod_register_block(const char* block_id, const struct BlockProperties* props);

// Register a custom item with the server
// item_id: unique identifier (e.g. "mymod:custom_item")
// props: item property struct
// Returns: 0 on success, non-zero on failure
int pymc_mod_register_item(const char* item_id, const struct ItemProperties* props);

// Register a custom biome with the server
// biome_id: unique identifier (e.g. "mymod:crystal_forest")
// temperature: biome temperature (0.0 - 2.0)
// downfall: rainfall amount (0.0 - 1.0)
// precipitation: "rain", "snow", or "none"
// Returns: 0 on success, non-zero on failure
int pymc_mod_register_biome(const char* biome_id, float temperature,
                            float downfall, const char* precipitation);

// Register a custom entity type with the server
// entity_id: unique identifier (e.g. "mymod:golem")
// width: entity hitbox width
// height: entity hitbox height
// is_summonable: whether /summon can create this entity
// Returns: 0 on success, non-zero on failure
int pymc_mod_register_entity_type(const char* entity_id, float width,
                                  float height, int is_summonable);

// ===========================================================
// Event Functions
// ===========================================================

// Callback type for event listeners
// event_name: name of the event that fired
// data_json: JSON-encoded event data (key-value pairs)
// Returns: 0 to continue, non-zero to cancel (if cancellable)
typedef int (*pymc_event_callback)(const char* event_name, const char* data_json);

// Register a callback for a specific event type
// event_name: event to listen for (e.g. "block_break", "player_join")
// callback: function pointer to call when event fires
// Returns: listener ID (>= 0) on success, -1 on failure
int pymc_mod_register_event_listener(const char* event_name,
                                     pymc_event_callback callback);

// Fire an event to all registered listeners
// event_name: event type to fire
// data_json: JSON-encoded event data
// Returns: 0 if no listener cancelled, non-zero if cancelled
int pymc_mod_fire_event(const char* event_name, const char* data_json);

// ===========================================================
// Server Query Functions
// ===========================================================

// Get the current server TPS (ticks per second)
// Returns: TPS as double (20.0 = ideal)
double pymc_mod_get_server_tps(void);

// Get the number of currently online players
// Returns: player count
int pymc_mod_get_online_players(void);

// Broadcast a chat message to all online players
// message: the message to broadcast
// Returns: 0 on success, non-zero on failure
int pymc_mod_broadcast_message(const char* message);

// Dispatch a server command as if typed in console
// command: the command string (without leading /)
// Returns: 0 on success, non-zero on failure
int pymc_mod_dispatch_command(const char* command);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // PYMC_MOD_API_H
