// ============================================================
// PyMC - Plugin API: Plugin Loader
//
// Provides the core plugin loading infrastructure for PYMC
// native Python plugins.
//
// PYMC Plugin API provides a Bukkit-inspired event system for
// Python plugins. It does NOT run Java Bukkit/Paper plugins.
//
// Architecture:
//   PluginLoader
//     ├── EventBus       - Event dispatch system
//     ├── PyMCAPI        - Server API types (PyMCServer, PyMCPlayer, etc.)
//     └── PluginManager  - Lifecycle management
// ============================================================

#ifndef PYMC_PLUGIN_LOADER_H
#define PYMC_PLUGIN_LOADER_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <unordered_map>
#include <mutex>

#include "event_system.h"
#include "bukkit_api.h"

namespace pymc {
namespace plugins {

// ===========================================================
// PluginMetadata
// ===========================================================

struct PluginMetadata {
    std::string name;           // Plugin name
    std::string version;        // Plugin version
    std::string main_class;     // Python module/class entry point
    std::string api_version;    // Target PYMC API version (e.g. "1.21")
    std::string description;    // Human-readable description
    std::vector<std::string> authors;
    std::vector<std::string> depend;      // Hard dependencies
    std::vector<std::string> softdepend;  // Soft dependencies
    std::vector<std::string> loadbefore;  // Load before these
    std::string prefix;         // Log prefix
};

// ===========================================================
// PluginState
// ===========================================================

enum class PluginState {
    UNLOADED,
    LOADED,
    ENABLING,
    ENABLED,
    DISABLING,
    DISABLED,
    ERRORED
};

// ===========================================================
// PluginInstance
// ===========================================================

class PluginInstance {
public:
    PluginInstance(const std::string& package_path, const PluginMetadata& meta)
        : package_path_(package_path)
        , metadata_(meta)
        , state_(PluginState::UNLOADED)
        , event_bus_(std::make_shared<EventBus>())
    {}

    const std::string& package_path() const { return package_path_; }
    const PluginMetadata& metadata() const { return metadata_; }
    PluginState state() const { return state_; }
    void set_state(PluginState s) { state_ = s; }
    std::shared_ptr<EventBus> event_bus() { return event_bus_; }

    // Register a command handler for this plugin
    void register_command(const std::string& name,
                          std::function<void(const std::string&)> handler) {
        commands_[name] = handler;
    }

    // Check if plugin handles a command
    bool has_command(const std::string& name) const {
        return commands_.find(name) != commands_.end();
    }

    // Execute a command handler
    void execute_command(const std::string& name, const std::string& args) {
        auto it = commands_.find(name);
        if (it != commands_.end()) {
            it->second(args);
        }
    }

private:
    std::string package_path_;
    PluginMetadata metadata_;
    PluginState state_;
    std::shared_ptr<EventBus> event_bus_;
    std::unordered_map<std::string, std::function<void(const std::string&)>> commands_;
};

// ===========================================================
// PluginLoader
// ===========================================================

class PluginLoader {
public:
    PluginLoader();
    ~PluginLoader();

    // --- Initialization ---

    // Initialize the plugin system
    bool initialize();

    // Shut down the plugin system (disables all plugins)
    void shutdown();

    // --- Plugin Loading ---

    // Load a PYMC Python plugin from its package directory
    // Returns: true if the plugin was loaded successfully
    bool load_plugin(const std::string& package_path);

    // Load all plugins from a directory
    // Scans for Python packages with pymc_plugin.json or plugin.yml
    // Returns: number of plugins loaded successfully
    int load_plugins_from_dir(const std::string& plugins_dir);

    // --- Lifecycle ---

    // Call on_enable() for all loaded plugins
    void enable_all();

    // Call on_disable() for all loaded plugins
    void disable_all();

    // Enable a specific plugin by name
    bool enable_plugin(const std::string& name);

    // Disable a specific plugin by name
    bool disable_plugin(const std::string& name);

    // --- Event System ---

    // Fire an event to all registered listeners
    void fire_event(const Event& event);

    // Fire an event only to a specific plugin's listeners
    void fire_event_to_plugin(const std::string& plugin_name, const Event& event);

    // --- Query ---

    // Get list of loaded plugin names
    std::vector<std::string> get_plugin_names() const;

    // Check if a plugin is loaded
    bool is_plugin_loaded(const std::string& name) const;

    // Get plugin state
    PluginState get_plugin_state(const std::string& name) const;

    // Get the PyMCServer API interface
    PyMCServer& server_api() { return server_api_; }

    // Get total number of loaded plugins
    size_t plugin_count() const { return plugins_.size(); }

private:
    // Parse pymc_plugin.json from a plugin package
    bool parse_plugin_json(const std::string& package_path, PluginMetadata& out);

    // Resolve plugin dependencies (topological sort)
    bool resolve_dependencies(std::vector<std::string>& load_order);

    // Check if all dependencies for a plugin are satisfied
    bool check_dependencies(const PluginMetadata& meta) const;

    // Internal enable logic
    bool enable_plugin_internal(const std::shared_ptr<PluginInstance>& plugin);

    // Internal disable logic
    void disable_plugin_internal(const std::shared_ptr<PluginInstance>& plugin);

private:
    bool initialized_;
    PyMCServer server_api_;
    std::unordered_map<std::string, std::shared_ptr<PluginInstance>> plugins_;
    std::vector<std::string> load_order_;  // Dependency-sorted load order
    mutable std::mutex mutex_;
};

}  // namespace plugins
}  // namespace pymc

#endif  // PYMC_PLUGIN_LOADER_H
