// ============================================================
// PyMC - Native Mod API: Mod Loader
//
// PYMC provides a Python-native mod API. It does NOT support
// Java Fabric/Forge/NeoForge/Quilt mods, as those require
// JVM + Mixin bytecode injection which cannot be replicated
// in a Python/C++ server.
//
// This mod loader discovers and loads PYMC native Python mods,
// manages their lifecycle, and dispatches events.
//
// Architecture:
//   ModLoader
//     ├── Mod Discovery     - Scan mods/ directory for Python packages
//     ├── Metadata Parsing   - Read pymc_mod.json descriptors
//     ├── Dependency Graph   - Topological sort for load ordering
//     ├── Lifecycle Manager  - load/enable/disable/unload
//     └── Event Dispatcher   - Fire events to mod callbacks
//
// Mod identification:
//   - pymc_mod.json        -> PYMC native mod descriptor
//   - __pymc_mod__.py      -> PYMC native mod entry point
//
// Loading pipeline:
//   1. Scan mods directory for Python packages
//   2. Parse mod metadata from pymc_mod.json (id, version, deps)
//   3. Resolve dependency graph (topological sort)
//   4. Load each mod package via Python importlib
//   5. Call mod lifecycle methods (on_load, on_enable, etc.)
//   6. Register event listeners from mod callbacks
//   7. Fire initialization events
// ============================================================

#ifndef PYMC_MOD_LOADER_H
#define PYMC_MOD_LOADER_H

#include <string>
#include <vector>
#include <map>
#include <functional>
#include <mutex>
#include <unordered_map>
#include <memory>

// ===========================================================
// ModLoaderType
// ===========================================================

enum class ModLoaderType {
    PYMC_NATIVE    // PYMC native Python mod
};

// Convert ModLoaderType to string (for debugging/logging)
inline const char* mod_loader_type_name(ModLoaderType type) {
    switch (type) {
        case ModLoaderType::PYMC_NATIVE: return "PYMC Native";
        default: return "Unknown";
    }
}

// ===========================================================
// ModInfo
// ===========================================================

struct ModInfo {
    std::string mod_id;           // Unique mod identifier (e.g. "my_cool_mod")
    std::string name;             // Human-readable mod name
    std::string version;          // Mod version string
    std::string description;      // Mod description
    ModLoaderType loader_type;    // Always PYMC_NATIVE for PYMC mods
    std::string entry_point;      // Python module/class entry point
    std::vector<std::string> dependencies;      // Required mod IDs
    std::vector<std::string> soft_dependencies;  // Optional mod IDs
    std::string package_path;     // Path to the Python package directory
    std::string api_version;      // Target PYMC mod API version
    std::string mc_version;       // Target Minecraft version (e.g. "1.21.1")

    // Additional metadata from pymc_mod.json
    std::map<std::string, std::string> extra_metadata;

    ModInfo() : loader_type(ModLoaderType::PYMC_NATIVE) {}

    // Check if this mod depends on another mod
    bool depends_on(const std::string& other_mod_id) const {
        for (const auto& dep : dependencies) {
            if (dep == other_mod_id) return true;
        }
        return false;
    }

    // Check if this mod has a soft dependency on another mod
    bool soft_depends_on(const std::string& other_mod_id) const {
        for (const auto& dep : soft_dependencies) {
            if (dep == other_mod_id) return true;
        }
        return false;
    }
};

// ===========================================================
// ModState
// ===========================================================

enum class ModState {
    DISCOVERED,    // Found on disk, metadata parsed
    LOADED,        // Python package imported successfully
    INITIALIZED,   // Mod on_load() called
    ENABLED,       // Mod is active and running
    DISABLED,      // Mod was enabled but now disabled
    ERRORED,       // Mod encountered an error
    UNLOADED       // Mod has been unloaded
};

inline const char* mod_state_name(ModState state) {
    switch (state) {
        case ModState::DISCOVERED:  return "Discovered";
        case ModState::LOADED:      return "Loaded";
        case ModState::INITIALIZED: return "Initialized";
        case ModState::ENABLED:     return "Enabled";
        case ModState::DISABLED:    return "Disabled";
        case ModState::ERRORED:     return "Errored";
        case ModState::UNLOADED:    return "Unloaded";
        default: return "Unknown";
    }
}

// ===========================================================
// ModInstance
// ===========================================================

class ModInstance {
public:
    ModInstance(const ModInfo& info)
        : info_(info), state_(ModState::DISCOVERED)
    {}

    const ModInfo& info() const { return info_; }
    ModState state() const { return state_; }
    void set_state(ModState s) { state_ = s; }

    const std::string& mod_id() const { return info_.mod_id; }
    ModLoaderType loader_type() const { return info_.loader_type; }

    // Check if this mod is in an active state
    bool is_active() const {
        return state_ == ModState::ENABLED || state_ == ModState::INITIALIZED;
    }

    // Check if this mod is in a recoverable error state
    bool is_errored() const { return state_ == ModState::ERRORED; }

    // Set/get error message (when state is ERRORED)
    void set_error(const std::string& err) { error_message_ = err; }
    const std::string& error() const { return error_message_; }

private:
    ModInfo info_;
    ModState state_;
    std::string error_message_;
};

// ===========================================================
// ModLoader
// ===========================================================

class ModLoader {
public:
    ModLoader();
    ~ModLoader();

    // --- Mod Discovery ---

    // Scan a directory for PYMC native mod packages
    // Looks for directories containing pymc_mod.json or __pymc_mod__.py
    // Returns: list of ModInfo for all discovered mods
    std::vector<ModInfo> scan_mods_directory(const std::string& dir_path);

    // --- Mod Loading ---

    // Load a PYMC native mod from its package directory
    // Returns: true if the mod was loaded successfully
    bool load_mod(const std::string& package_path);

    // Load all discovered mods (in dependency order)
    // Returns: number of mods loaded successfully
    int load_all();

    // --- Lifecycle ---

    // Initialize all loaded mods (call on_load callbacks)
    // Returns: true if all mods initialized successfully
    bool initialize_all();

    // Enable a specific mod by ID
    bool enable_mod(const std::string& mod_id);

    // Disable a specific mod by ID
    bool disable_mod(const std::string& mod_id);

    // Shutdown all mods (disable in reverse dependency order)
    void shutdown_all();

    // --- Query ---

    // Get all loaded mods
    const std::vector<ModInfo>& get_loaded_mods() const;

    // Get a mod instance by ID
    std::shared_ptr<ModInstance> get_mod(const std::string& mod_id) const;

    // Check if a mod is loaded
    bool is_mod_loaded(const std::string& mod_id) const;

    // Get mod state
    ModState get_mod_state(const std::string& mod_id) const;

    // Get number of loaded mods
    size_t mod_count() const { return mods_.size(); }

    // --- API Handler Registration ---

    // Register a mod API callback
    // When a mod calls an API method, the handler is invoked
    void register_api_handler(const std::string& api_name,
                              std::function<void(const std::map<std::string, std::string>&)> handler);

    // --- Event Dispatch ---

    // Fire a mod event to all registered listeners
    void fire_event(const std::string& event_name,
                    const std::map<std::string, std::string>& data);

    // Register a listener for a specific event type
    // Returns: listener ID for later unregistration
    int register_event_listener(const std::string& event_name,
                                std::function<void(const std::map<std::string, std::string>&)> listener);

    // Unregister an event listener by ID
    bool unregister_event_listener(int listener_id);

    // --- Dependency Resolution ---

    // Resolve the dependency order for all loaded mods
    // Returns: ordered list of mod IDs (dependencies first)
    std::vector<std::string> resolve_dependency_order() const;

    // Check if all dependencies for a mod are satisfied
    bool check_dependencies(const ModInfo& info) const;

private:
    // --- Mod Metadata Parsing ---

    // Parse PYMC mod metadata from pymc_mod.json
    bool parse_pymc_mod_json(const std::string& package_path, ModInfo& info);

    // --- Internal Helpers ---

    // Topological sort for dependency resolution
    bool topological_sort(const std::vector<std::string>& mod_ids,
                          std::vector<std::string>& out_order) const;

private:
    // All loaded mods (mod_id -> instance)
    std::unordered_map<std::string, std::shared_ptr<ModInstance>> mods_;

    // Ordered list of mod IDs (dependency-sorted)
    std::vector<std::string> load_order_;

    // Discovered mods (from scan, before loading)
    std::vector<ModInfo> discovered_mods_;

    // API handlers (api_name -> handler function)
    std::map<std::string, std::function<void(const std::map<std::string, std::string>&)>> api_handlers_;

    // Event listeners (event_name -> list of (id, handler))
    std::map<std::string, std::vector<std::pair<int, std::function<void(const std::map<std::string, std::string>&)>>>> event_listeners_;

    // Next event listener ID
    int next_listener_id_ = 0;

    // Mutex for thread safety
    mutable std::mutex mutex_;
};

#endif  // PYMC_MOD_LOADER_H
