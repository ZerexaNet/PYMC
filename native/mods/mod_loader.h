// ============================================================
// PyMC - Mod Compatibility Layer: Mod Loader
//
// Provides a unified mod loader that can load Fabric, Forge,
// NeoForge, and Quilt mods and translate their API calls to
// PYMC internal operations.
//
// Architecture:
//   ModLoader
//     ├── Fabric API Bridge   - Fabric mod API translation
//     ├── Forge API Bridge    - Forge/NeoForge mod API translation
//     ├── Quilt API Bridge    - Quilt mod API translation (extends Fabric)
//     ├── JVM Interface       - JNI-based .jar loading & execution
//     └── Event Dispatcher    - Mod event -> PYMC event translation
//
// Mod identification:
//   - fabric.mod.json   -> Fabric mod
//   - quilt.mod.json    -> Quilt mod
//   - META-INF/mods.toml -> Forge/NeoForge mod
//     (NeoForge uses same location but different schema version)
//
// Loading pipeline:
//   1. Scan mods directory for .jar files
//   2. Identify mod type by inspecting jar contents
//   3. Parse mod metadata (ID, version, dependencies)
//   4. Resolve dependency graph (topological sort)
//   5. Initialize JVM if any mod requires it
//   6. Load and initialize each mod via appropriate bridge
//   7. Register API handlers for mod callbacks
//   8. Fire initialization events
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
    FABRIC,
    FORGE,
    NEOFORGE,
    QUILT
};

// Convert ModLoaderType to string (for debugging/logging)
inline const char* mod_loader_type_name(ModLoaderType type) {
    switch (type) {
        case ModLoaderType::FABRIC:   return "Fabric";
        case ModLoaderType::FORGE:    return "Forge";
        case ModLoaderType::NEOFORGE: return "NeoForge";
        case ModLoaderType::QUILT:    return "Quilt";
        default: return "Unknown";
    }
}

// ===========================================================
// ModInfo
// ===========================================================

struct ModInfo {
    std::string mod_id;           // Unique mod identifier (e.g. "sodium")
    std::string name;             // Human-readable mod name
    std::string version;          // Mod version string
    std::string description;      // Mod description
    ModLoaderType loader_type;    // Which loader this mod targets
    std::string entry_point;      // Main class for Forge, mod.json entry for Fabric
    std::vector<std::string> dependencies;    // Required mod IDs
    std::vector<std::string> soft_dependencies; // Optional mod IDs
    std::string jar_path;         // Path to the .jar file
    std::string mc_version;       // Target Minecraft version (e.g. "1.21.1")
    std::string loader_version;   // Minimum loader version required

    // Additional metadata from mod descriptor files
    std::map<std::string, std::string> extra_metadata;

    ModInfo() : loader_type(ModLoaderType::FABRIC) {}

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
    LOADED,        // Jar loaded into JVM/classloader
    INITIALIZED,   // Mod initializer called
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

    // Scan a directory for mod jars
    // Returns: list of ModInfo for all discovered mods
    std::vector<ModInfo> scan_mods_directory(const std::string& dir_path);

    // --- Mod Loading ---

    // Load a mod jar file
    // Returns: true if the mod was loaded successfully
    bool load_mod(const std::string& jar_path, ModLoaderType loader_type);

    // Load all discovered mods (in dependency order)
    // Returns: number of mods loaded successfully
    int load_all();

    // --- Lifecycle ---

    // Initialize all loaded mods (call entry points)
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

    // Parse Fabric mod metadata from jar (fabric.mod.json)
    bool parse_fabric_mod_json(const std::string& jar_path, ModInfo& info);

    // Parse Forge mod metadata from jar (META-INF/mods.toml)
    bool parse_forge_mods_toml(const std::string& jar_path, ModInfo& info);

    // Parse NeoForge mod metadata from jar (META-INF/mods.toml with neo schema)
    bool parse_neoforge_mods_toml(const std::string& jar_path, ModInfo& info);

    // Parse Quilt mod metadata from jar (quilt.mod.json)
    bool parse_quilt_mod_json(const std::string& jar_path, ModInfo& info);

    // --- Internal Helpers ---

    // Identify mod type from jar contents
    // Returns: ModLoaderType or throws if unidentifiable
    ModLoaderType identify_mod_type(const std::string& jar_path);

    // Read a file from within a .jar (ZIP archive)
    // Returns: file contents as string, or empty if not found
    std::string read_jar_file(const std::string& jar_path, const std::string& inner_path);

    // Parse JSON string into key-value map (minimal parser)
    std::map<std::string, std::string> parse_simple_json(const std::string& json_str);

    // Parse TOML string into key-value map (minimal parser)
    std::map<std::string, std::string> parse_simple_toml(const std::string& toml_str);

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
