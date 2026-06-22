// ============================================================
// PyMC - Plugin Loader C API Bridge Implementation
//
// Provides C-compatible stub API for Python ctypes bindings.
// Full PluginLoader/BukkitServer implementation requires JVM
// integration; these stubs allow the shared library to compile
// and load while the Python side handles actual plugin logic.
// ============================================================

#include "plugin_loader_api.h"
#include "event_system.h"

#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>

// ===========================================================
// Internal state
// ===========================================================

static bool g_initialized = false;
static int g_plugin_count = 0;

struct PythonCallback {
    std::string event_name;
    int priority;
    void (*callback)(const char* event_name, const char* data_json);
};

static std::vector<PythonCallback> g_python_callbacks;
static int g_next_handler_id = 0;

// ===========================================================
// Plugin Loader Lifecycle
// ===========================================================

int pymc_plugin_loader_initialize() {
    g_initialized = true;
    return 1;
}

void pymc_plugin_loader_shutdown() {
    g_initialized = false;
    g_plugin_count = 0;
    g_python_callbacks.clear();
}

// ===========================================================
// Plugin Loading (stubs — Python handles actual loading)
// ===========================================================

int pymc_plugin_loader_load_plugin(const char* jar_path) {
    if (!jar_path) return 0;
    // Stub: actual loading handled by Python ModManager
    g_plugin_count++;
    return 1;
}

int pymc_plugin_loader_load_plugins_from_dir(const char* plugins_dir) {
    if (!plugins_dir) return 0;
    // Stub: return 0 loaded; Python handles directory scanning
    return 0;
}

// ===========================================================
// Plugin Lifecycle
// ===========================================================

int pymc_plugin_loader_enable_all() {
    return g_initialized ? 1 : 0;
}

void pymc_plugin_loader_disable_all() {
    // No-op stub
}

int pymc_plugin_loader_enable_plugin(const char* name) {
    if (!name) return 0;
    return 1;  // Stub: always success
}

int pymc_plugin_loader_disable_plugin(const char* name) {
    // No-op stub
    return 1;
}

// ===========================================================
// Event System
// ===========================================================

int pymc_plugin_loader_fire_event(const char* event_name, const char* data_json) {
    if (!event_name) return 1;

    // Dispatch to all registered Python callbacks
    for (const auto& cb : g_python_callbacks) {
        if (cb.event_name == event_name || cb.event_name == "*") {
            cb.callback(event_name, data_json ? data_json : "");
        }
    }

    return 1;  // Not cancelled
}

int pymc_plugin_loader_register_listener(
    const char* event_name,
    int priority,
    void (*callback)(const char* event_name, const char* data_json))
{
    if (!event_name || !callback) return -1;

    int id = g_next_handler_id++;
    PythonCallback pcb;
    pcb.event_name = std::string(event_name);
    pcb.priority = priority;
    pcb.callback = callback;
    g_python_callbacks.push_back(pcb);

    return id;
}

int pymc_plugin_loader_unregister_handler(int /*handler_id*/) {
    return 0;
}

// ===========================================================
// Query
// ===========================================================

int pymc_plugin_loader_plugin_count() {
    return g_plugin_count;
}

int pymc_plugin_loader_is_plugin_loaded(const char* name) {
    if (!name) return 0;
    return 0;  // Stub: Python manages plugin state
}

int pymc_plugin_loader_get_plugin_state(const char* name) {
    if (!name) return 0;
    return 0;  // 0 = DISCOVERED (stub)
}

double pymc_plugin_loader_get_tps() {
    return 20.0;  // Stub: return ideal TPS
}

// ===========================================================
// Bukkit API Bridge (stubs — Python handles actual operations)
// ===========================================================

void pymc_plugin_loader_broadcast_message(const char* message) {
    // Stub: Python PluginManager handles broadcasting
}

int pymc_plugin_loader_dispatch_command(const char* command) {
    if (!command) return 0;
    return 0;  // Stub: not dispatched
}

int pymc_plugin_loader_online_player_count() {
    return 0;  // Stub
}

char* pymc_plugin_loader_get_online_players() {
    const char* empty = "[]";
    char* cstr = new char[3];
    std::strcpy(cstr, empty);
    return cstr;
}

char* pymc_plugin_loader_get_world_names() {
    const char* worlds = "[\"minecraft:overworld\"]";
    size_t len = std::strlen(worlds);
    char* cstr = new char[len + 1];
    std::strcpy(cstr, worlds);
    return cstr;
}

void pymc_plugin_loader_free_string(char* str) {
    delete[] str;
}

// ===========================================================
// Version Info
// ===========================================================

static const char* PLUGIN_LOADER_VERSION = "1.0.0";
static const int PLUGIN_LOADER_API_VERSION = 1;

const char* pymc_plugin_loader_get_version() {
    return PLUGIN_LOADER_VERSION;
}

int pymc_plugin_loader_get_api_version() {
    return PLUGIN_LOADER_API_VERSION;
}
