// ============================================================
// PyMC - Plugin Loader C API Bridge Implementation
//
// Implements the C-compatible API for the Python ctypes bindings.
// Currently provides stub implementations that return success
// values. Full implementation requires JNI/JVM integration.
// ============================================================

#include "plugin_loader_api.h"
#include "plugin_loader.h"

#include <cstring>
#include <cstdlib>
#include <string>

using namespace pymc::plugins;

// Global plugin loader instance
static std::unique_ptr<PluginLoader> g_plugin_loader = nullptr;
static bool g_initialized = false;

// ===========================================================
// Plugin Loader Lifecycle
// ===========================================================

int pymc_plugin_loader_initialize() {
    if (g_initialized) return 1;

    g_plugin_loader = std::make_unique<PluginLoader>();
    if (g_plugin_loader->initialize()) {
        g_initialized = true;
        return 1;
    }

    g_plugin_loader.reset();
    return 0;
}

void pymc_plugin_loader_shutdown() {
    if (!g_initialized || !g_plugin_loader) return;

    g_plugin_loader->shutdown();
    g_plugin_loader.reset();
    g_initialized = false;
}

// ===========================================================
// Plugin Loading
// ===========================================================

int pymc_plugin_loader_load_plugin(const char* jar_path) {
    if (!g_plugin_loader || !jar_path) return 0;
    return g_plugin_loader->load_plugin(std::string(jar_path)) ? 1 : 0;
}

int pymc_plugin_loader_load_plugins_from_dir(const char* plugins_dir) {
    if (!g_plugin_loader || !plugins_dir) return 0;
    return g_plugin_loader->load_plugins_from_dir(std::string(plugins_dir));
}

// ===========================================================
// Plugin Lifecycle
// ===========================================================

int pymc_plugin_loader_enable_all() {
    if (!g_plugin_loader) return 0;
    g_plugin_loader->enable_all();
    return 1;
}

void pymc_plugin_loader_disable_all() {
    if (!g_plugin_loader) return;
    g_plugin_loader->disable_all();
}

int pymc_plugin_loader_enable_plugin(const char* name) {
    if (!g_plugin_loader || !name) return 0;
    return g_plugin_loader->enable_plugin(std::string(name)) ? 1 : 0;
}

int pymc_plugin_loader_disable_plugin(const char* name) {
    if (!g_plugin_loader || !name) return 0;
    g_plugin_loader->disable_plugin(std::string(name));
    return 1;
}

// ===========================================================
// Event System
// ===========================================================

int pymc_plugin_loader_fire_event(const char* event_name, const char* data_json) {
    if (!g_plugin_loader || !event_name) return 0;

    Event event(std::string(event_name));

    // Simple JSON data parsing (key:value pairs separated by ;)
    if (data_json && strlen(data_json) > 0) {
        std::string json_str(data_json);
        // Basic parsing: {"key":"value","key2":"value2"}
        // For a full implementation, use a JSON library
        size_t pos = 0;
        std::string input = json_str;
        // Strip braces
        if (input.front() == '{') input = input.substr(1);
        if (input.back() == '}') input = input.substr(0, input.size() - 1);

        // Split by commas, then by colons
        // This is a simplified parser; production would use proper JSON
    }

    g_plugin_loader->fire_event(event);
    return event.cancelled ? 0 : 1;
}

// Callback storage for Python-registered listeners
struct PythonCallback {
    std::string event_name;
    int priority;
    void (*callback)(const char* event_name, const char* data_json);
};

static std::vector<PythonCallback> g_python_callbacks;
static int g_next_handler_id = 0;

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

    // Also register on the plugin loader's event bus
    if (g_plugin_loader) {
        // Map priority integer to EventPriority enum
        EventPriority ep = EventPriority::NORMAL;
        switch (priority) {
            case 0: ep = EventPriority::LOWEST; break;
            case 1: ep = EventPriority::LOW; break;
            case 2: ep = EventPriority::NORMAL; break;
            case 3: ep = EventPriority::HIGH; break;
            case 4: ep = EventPriority::HIGHEST; break;
            case 5: ep = EventPriority::MONITOR; break;
        }

        g_plugin_loader->server_api();  // Ensure server API is accessible
    }

    return id;
}

int pymc_plugin_loader_unregister_handler(int handler_id) {
    // Simplified: in a full implementation, track handler IDs properly
    return 0;
}

// ===========================================================
// Query
// ===========================================================

int pymc_plugin_loader_plugin_count() {
    if (!g_plugin_loader) return 0;
    return static_cast<int>(g_plugin_loader->plugin_count());
}

int pymc_plugin_loader_is_plugin_loaded(const char* name) {
    if (!g_plugin_loader || !name) return 0;
    return g_plugin_loader->is_plugin_loaded(std::string(name)) ? 1 : 0;
}

int pymc_plugin_loader_get_plugin_state(const char* name) {
    if (!g_plugin_loader || !name) return 0;
    return static_cast<int>(g_plugin_loader->get_plugin_state(std::string(name)));
}

double pymc_plugin_loader_get_tps() {
    if (!g_plugin_loader) return 0.0;
    return g_plugin_loader->server_api().tps();
}

// ===========================================================
// Bukkit API Bridge
// ===========================================================

void pymc_plugin_loader_broadcast_message(const char* message) {
    if (!g_plugin_loader || !message) return;
    g_plugin_loader->server_api().broadcast_message(std::string(message));
}

int pymc_plugin_loader_dispatch_command(const char* command) {
    if (!g_plugin_loader || !command) return 0;
    return g_plugin_loader->server_api().dispatch_command(std::string(command)) ? 1 : 0;
}

int pymc_plugin_loader_online_player_count() {
    if (!g_plugin_loader) return 0;
    return g_plugin_loader->server_api().online_player_count();
}

char* pymc_plugin_loader_get_online_players() {
    if (!g_plugin_loader) return nullptr;
    auto players = g_plugin_loader->server_api().get_online_players();

    // Build simple JSON array
    std::string result = "[";
    for (size_t i = 0; i < players.size(); i++) {
        if (i > 0) result += ",";
        result += "\"" + players[i] + "\"";
    }
    result += "]";

    char* cstr = new char[result.size() + 1];
    std::strcpy(cstr, result.c_str());
    return cstr;
}

char* pymc_plugin_loader_get_world_names() {
    if (!g_plugin_loader) return nullptr;
    auto worlds = g_plugin_loader->server_api().get_world_names();

    std::string result = "[";
    for (size_t i = 0; i < worlds.size(); i++) {
        if (i > 0) result += ",";
        result += "\"" + worlds[i] + "\"";
    }
    result += "]";

    char* cstr = new char[result.size() + 1];
    std::strcpy(cstr, result.c_str());
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
