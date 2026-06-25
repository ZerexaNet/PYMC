// ============================================================
// PyMC - Plugin Loader C API Bridge
//
// Provides a C-compatible API that can be called from Python
// via ctypes to interact with the plugin compatibility layer.
// ============================================================

#ifdef _WIN32
#define PYMC_EXPORT __declspec(dllexport)
#else
#define PYMC_EXPORT __attribute__((visibility("default")))
#endif

#include <cstdint>
#include <cstddef>

#ifdef __cplusplus
extern "C" {
#endif

// ===========================================================
// Plugin Loader Lifecycle
// ===========================================================

// Initialize the plugin loader system (sets up JVM bridge, API mappings)
// Returns: 1 on success, 0 on failure
PYMC_EXPORT int pymc_plugin_loader_initialize();

// Shut down the plugin loader (disables all plugins, tears down JVM)
PYMC_EXPORT void pymc_plugin_loader_shutdown();

// ===========================================================
// Plugin Loading
// ===========================================================

// Load a .jar plugin file
// jar_path: path to the .jar file
// Returns: 1 if loaded successfully, 0 on failure
PYMC_EXPORT int pymc_plugin_loader_load_plugin(const char* jar_path);

// Load all .jar files from a directory
// plugins_dir: directory containing .jar files
// Returns: number of plugins loaded successfully
PYMC_EXPORT int pymc_plugin_loader_load_plugins_from_dir(const char* plugins_dir);

// ===========================================================
// Plugin Lifecycle
// ===========================================================

// Enable all loaded plugins
// Returns: 1 on success, 0 on failure
PYMC_EXPORT int pymc_plugin_loader_enable_all();

// Disable all loaded plugins
PYMC_EXPORT void pymc_plugin_loader_disable_all();

// Enable a specific plugin by name
// Returns: 1 on success, 0 on failure (not found or error)
PYMC_EXPORT int pymc_plugin_loader_enable_plugin(const char* name);

// Disable a specific plugin by name
// Returns: 1 on success, 0 on failure
PYMC_EXPORT int pymc_plugin_loader_disable_plugin(const char* name);

// ===========================================================
// Event System
// ===========================================================

// Fire an event to all registered listeners
// event_name: name of the event (e.g. "PlayerJoinEvent")
// data_json: JSON string with event data
// Returns: 1 if event was NOT cancelled, 0 if cancelled
PYMC_EXPORT int pymc_plugin_loader_fire_event(const char* event_name,
                                                const char* data_json);

// Register a Python-side event listener
// event_name: name of the event
// priority: 0=LOWEST, 1=LOW, 2=NORMAL, 3=HIGH, 4=HIGHEST, 5=MONITOR
// callback: function pointer called with (event_name, data_json)
// Returns: handler ID, or -1 on failure
PYMC_EXPORT int pymc_plugin_loader_register_listener(
    const char* event_name,
    int priority,
    void (*callback)(const char* event_name, const char* data_json));

// Unregister a listener by handler ID
// Returns: 1 on success, 0 on failure
PYMC_EXPORT int pymc_plugin_loader_unregister_handler(int handler_id);

// ===========================================================
// Query
// ===========================================================

// Get the number of loaded plugins
PYMC_EXPORT int pymc_plugin_loader_plugin_count();

// Check if a plugin is loaded
// Returns: 1 if loaded, 0 if not
PYMC_EXPORT int pymc_plugin_loader_is_plugin_loaded(const char* name);

// Get plugin state (0=UNLOADED, 1=LOADED, 2=ENABLING, 3=ENABLED,
//                  4=DISABLING, 5=DISABLED, 6=ERRORED)
PYMC_EXPORT int pymc_plugin_loader_get_plugin_state(const char* name);

// Get the server TPS
PYMC_EXPORT double pymc_plugin_loader_get_tps();

// ===========================================================
// Bukkit API Bridge
// ===========================================================

// Broadcast a message to all online players
PYMC_EXPORT void pymc_plugin_loader_broadcast_message(const char* message);

// Dispatch a server command
// Returns: 1 if command was handled, 0 if not
PYMC_EXPORT int pymc_plugin_loader_dispatch_command(const char* command);

// Get online player count
PYMC_EXPORT int pymc_plugin_loader_online_player_count();

// Get online player names as a JSON array string
// Caller must free the returned string with pymc_plugin_loader_free_string
PYMC_EXPORT char* pymc_plugin_loader_get_online_players();

// Get world names as a JSON array string
// Caller must free the returned string with pymc_plugin_loader_free_string
PYMC_EXPORT char* pymc_plugin_loader_get_world_names();

// Free a string returned by the plugin loader API
PYMC_EXPORT void pymc_plugin_loader_free_string(char* str);

// ===========================================================
// Version Info
// ===========================================================

PYMC_EXPORT const char* pymc_plugin_loader_get_version();
PYMC_EXPORT int pymc_plugin_loader_get_api_version();

#ifdef __cplusplus
}
#endif
