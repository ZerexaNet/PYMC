// ============================================================
// PyMC - Mod Compatibility Layer: Forge API Bridge
//
// Maps Forge/NeoForge API calls to PYMC internal operations.
// This provides the translation layer between Forge mod API
// calls (via MinecraftForge.EVENT_BUS, Forge Registries,
// Capabilities, etc.) and PYMC's C++/Python server operations.
//
// Architecture:
//   ForgeAPIBridge
//     ├── Registry Bridge
//     │   ├── Forge Registry hooks -> PYMC registries
//     │   ├── DeferredRegister     -> PYMC deferred registration
//     │   └── RegistryObject       -> PYMC registry references
//     ├── Event Bridge
//     │   ├── MinecraftForge.EVENT_BUS -> PYMC event bus
//     │   ├── Forge Event classes      -> PYMC event data
//     │   └── Event cancellation       -> PYMC event cancellation
//     ├── Capability Bridge
//     │   ├── ICapabilityProvider  -> PYMC capability system
//     │   ├── IItemHandler         -> PYMC inventory system
//     │   ├── IFluidHandler        -> PYMC fluid system
//     │   └── IEnergyStorage       -> PYMC energy system
//     ├── Data Generation Bridge
//     │   ├── BlockStateProvider   -> PYMC block state data
//     │   ├── ItemModelProvider    -> PYMC item model data
//     │   └── RecipeProvider       -> PYMC recipe data
//     └── Config Bridge
//         ├── ForgeConfigSpec       -> PYMC config system
//         └── ModConfigSpec         -> PYMC per-mod config
//
// Forge API mapping:
//   net.minecraftforge                    -> PYMC operations
//   -------------------------------------------------------
//   ForgeRegistries.BLOCKS                -> register_block()
//   ForgeRegistries.ITEMS                 -> register_item()
//   MinecraftForge.EVENT_BUS              -> fire_forge_event()
//   CapabilityManager                     -> register_capability()
//   IItemHandler                          -> register_item_handler()
//   IFluidHandler                         -> register_fluid_handler()
//   IEnergyStorage                        -> register_energy_storage()
//   ForgeConfigSpec                       -> register_config()
//
// NeoForge differences:
//   - Uses same mods.toml location (META-INF/mods.toml)
//   - Different event bus organization
//   - NeoForgeRegistries instead of ForgeRegistries
//   - More modern capability system
// ============================================================

#ifndef PYMC_FORGE_API_H
#define PYMC_FORGE_FORGE_API_H

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
// Forge Block Properties
// ===========================================================

struct ForgeBlockProperties {
    std::string registry_name;               // Full registry name (namespace:path)
    std::string material = "stone";          // Material type
    std::string sound_type = "stone";        // Block sound type
    float hardness = 1.0f;                   // Block hardness
    float resistance = 1.0f;                 // Blast resistance
    float slipperiness = 0.6f;              // Friction
    int light_level = 0;                     // Emitted light (0-15)
    bool is_opaque = true;                   // Is opaque
    bool requires_tool = false;              // Requires specific tool to drop
    std::string harvest_tool = "";           // Tool type required (pickaxe, axe, etc.)
    int harvest_level = 0;                   // Tool tier required (0=wood, 1=stone, 2=iron, 3=diamond, 4=netherite)
    std::map<std::string, std::string> custom_properties;

    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["registry_name"] = registry_name;
        props["material"] = material;
        props["sound_type"] = sound_type;
        props["hardness"] = std::to_string(hardness);
        props["resistance"] = std::to_string(resistance);
        props["slipperiness"] = std::to_string(slipperiness);
        props["light_level"] = std::to_string(light_level);
        props["is_opaque"] = is_opaque ? "true" : "false";
        props["requires_tool"] = requires_tool ? "true" : "false";
        props["harvest_tool"] = harvest_tool;
        props["harvest_level"] = std::to_string(harvest_level);
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Forge Item Properties
// ===========================================================

struct ForgeItemProperties {
    std::string registry_name;
    std::string creative_tab = "";           // Creative mode tab
    int max_stack_size = 64;                 // Max stack size
    int max_damage = 0;                      // Max durability
    bool is_fire_resistant = false;          // Fire resistant
    bool can_repair = true;                  // Can be repaired in anvil
    std::string rarity = "common";           // Rarity level
    std::map<std::string, std::string> custom_properties;

    std::map<std::string, std::string> to_property_map() const {
        std::map<std::string, std::string> props;
        props["registry_name"] = registry_name;
        props["creative_tab"] = creative_tab;
        props["max_stack_size"] = std::to_string(max_stack_size);
        props["max_damage"] = std::to_string(max_damage);
        props["is_fire_resistant"] = is_fire_resistant ? "true" : "false";
        props["can_repair"] = can_repair ? "true" : "false";
        props["rarity"] = rarity;
        for (const auto& [k, v] : custom_properties) {
            props[k] = v;
        }
        return props;
    }
};

// ===========================================================
// Forge Capability Types
// ===========================================================

struct ForgeCapabilityData {
    std::string capability_name;             // Capability identifier
    std::string interface_class;             // Java interface class name
    std::string default_implementation;      // Default implementation class
    bool is_singleton = false;              // Single instance or per-tile-entity
    std::map<std::string, std::string> extra_data;
};

// ===========================================================
// Forge Item Handler (IItemHandler)
// ===========================================================

struct ForgeItemHandlerData {
    std::string block_id;                    // Block that provides this capability
    int slots = 0;                           // Number of inventory slots
    int stack_limit = 64;                    // Max stack size per slot
    bool is_input = true;                   // Can insert items
    bool is_output = true;                  // Can extract items
    std::map<int, std::string> slot_filters; // Slot index -> allowed item filter
};

// ===========================================================
// Forge Fluid Handler (IFluidHandler)
// ===========================================================

struct ForgeFluidHandlerData {
    std::string block_id;                    // Block that provides this capability
    int capacity = 0;                        // Total fluid capacity (mB)
    int max_drain = 0;                       // Max drain rate (mB/tick)
    int max_fill = 0;                        // Max fill rate (mB/tick)
    int tanks = 1;                           // Number of fluid tanks
    std::vector<std::string> allowed_fluids; // Empty = all fluids allowed
};

// ===========================================================
// Forge Energy Storage (IEnergyStorage)
// ===========================================================

struct ForgeEnergyStorageData {
    std::string block_id;                    // Block that provides this capability
    int capacity = 0;                        // Total energy capacity (FE)
    int max_receive = 0;                     // Max energy input rate (FE/tick)
    int max_extract = 0;                     // Max energy output rate (FE/tick)
    int initial_energy = 0;                  // Starting energy
    bool can_receive = true;                 // Can accept energy
    bool can_extract = true;                 // Can output energy
};

// ===========================================================
// Forge Event Result
// ===========================================================

// Result of a Forge event, mirrors net.minecraftforge.event.Event.Result
enum class ForgeEventResult {
    DEFAULT,    // No action specified (let default behavior proceed)
    ALLOW,      // Explicitly allow the action
    DENY        // Explicitly deny the action
};

// ===========================================================
// Forge Event Callbacks
// ===========================================================

using ForgeEntityJoinCallback = std::function<void(const std::string& entity_id)>;
using ForgeEntityLeaveCallback = std::function<void(const std::string& entity_id)>;
using ForgeBlockBreakCallback = std::function<ForgeEventResult(int x, int y, int z, const std::string& player)>;
using ForgeBlockPlaceCallback = std::function<ForgeEventResult(int x, int y, int z, const std::string& block_id)>;
using ForgePlayerInteractCallback = std::function<ForgeEventResult(const std::string& player, int x, int y, int z, const std::string& hand)>;
using ForgeLivingHurtCallback = std::function<ForgeEventResult(const std::string& entity, double amount, const std::string& source)>;
using ForgeLivingDeathCallback = std::function<void(const std::string& entity, const std::string& source)>;
using ForgeTickCallback = std::function<void()>;                          // ServerTickEvent
using ForgeChunkLoadCallback = std::function<void(int cx, int cz)>;
using ForgeChunkUnloadCallback = std::function<void(int cx, int cz)>;

// ===========================================================
// ForgeAPIBridge
// ===========================================================

class ForgeAPIBridge {
public:
    ForgeAPIBridge();
    ~ForgeAPIBridge();

    // --- Registry Bridge ---
    // Maps Forge Registry hooks -> PYMC registries

    // Register a custom block via ForgeRegistries.BLOCKS
    void register_block(const std::string& block_id,
                        const std::map<std::string, std::string>& properties);

    // Register a custom block with typed properties
    void register_block(const std::string& block_id, const ForgeBlockProperties& props);

    // Register a custom item via ForgeRegistries.ITEMS
    void register_item(const std::string& item_id,
                       const std::map<std::string, std::string>& properties);

    // Register a custom item with typed properties
    void register_item(const std::string& item_id, const ForgeItemProperties& props);

    // Register a capability type
    // Maps: CapabilityManager.register() -> PYMC capability registry
    void register_capability(const std::string& capability_name,
                              const std::map<std::string, std::string>& properties);

    // Register a capability with typed data
    void register_capability(const ForgeCapabilityData& data);

    // --- Event Bridge ---
    // Maps MinecraftForge.EVENT_BUS -> PYMC event bus

    // EntityJoinWorldEvent
    void on_entity_join_world(const std::string& entity_id);

    // EntityLeaveWorldEvent
    void on_entity_leave_world(const std::string& entity_id);

    // BlockBreakEvent (fires BEFORE the block is broken)
    // Returns: ALLOW, DENY, or DEFAULT
    ForgeEventResult on_block_break_event(int x, int y, int z, const std::string& player);

    // BlockPlaceEvent (fires BEFORE the block is placed)
    // Returns: ALLOW, DENY, or DEFAULT
    ForgeEventResult on_block_place_event(int x, int y, int z, const std::string& block_id);

    // PlayerInteractEvent (player right-clicks a block)
    // Returns: ALLOW, DENY, or DEFAULT
    ForgeEventResult on_player_interact(const std::string& player, int x, int y, int z,
                                         const std::string& hand);

    // LivingHurtEvent (entity is about to take damage)
    // Returns: ALLOW, DENY, or DEFAULT
    ForgeEventResult on_living_hurt(const std::string& entity, double amount,
                                     const std::string& source);

    // LivingDeathEvent (entity dies)
    void on_living_death(const std::string& entity, const std::string& source);

    // ServerTickEvent (fires every server tick)
    void on_tick_event();

    // ChunkEvent.Load
    void on_chunk_load(int cx, int cz);

    // ChunkEvent.Unload
    void on_chunk_unload(int cx, int cz);

    // --- Callback Registration ---
    // Register Forge-style event listeners (mirrors MinecraftForge.EVENT_BUS.register)

    void register_entity_join_callback(ForgeEntityJoinCallback cb);
    void register_entity_leave_callback(ForgeEntityLeaveCallback cb);
    void register_block_break_callback(ForgeBlockBreakCallback cb);
    void register_block_place_callback(ForgeBlockPlaceCallback cb);
    void register_player_interact_callback(ForgePlayerInteractCallback cb);
    void register_living_hurt_callback(ForgeLivingHurtCallback cb);
    void register_living_death_callback(ForgeLivingDeathCallback cb);
    void register_tick_callback(ForgeTickCallback cb);
    void register_chunk_load_callback(ForgeChunkLoadCallback cb);
    void register_chunk_unload_callback(ForgeChunkUnloadCallback cb);

    // --- Capability Bridge ---
    // Maps Forge Capabilities -> PYMC capability system

    // Register IItemHandler capability for a block
    // Maps: IItemHandler -> PYMC inventory system
    void register_item_handler(const std::string& block_id, int slots);

    // Register IItemHandler with full data
    void register_item_handler(const ForgeItemHandlerData& data);

    // Register IFluidHandler capability for a block
    // Maps: IFluidHandler -> PYMC fluid system
    void register_fluid_handler(const std::string& block_id, int capacity);

    // Register IFluidHandler with full data
    void register_fluid_handler(const ForgeFluidHandlerData& data);

    // Register IEnergyStorage capability for a block
    // Maps: IEnergyStorage -> PYMC energy system
    void register_energy_storage(const std::string& block_id, int capacity, int max_transfer);

    // Register IEnergyStorage with full data
    void register_energy_storage(const ForgeEnergyStorageData& data);

    // --- Config Bridge ---
    // Maps ForgeConfigSpec -> PYMC config system

    // Register a mod configuration
    void register_config(const std::string& mod_id,
                         const std::map<std::string, std::string>& config_defaults);

    // Get a config value
    std::optional<std::string> get_config_value(const std::string& mod_id,
                                                 const std::string& key) const;

    // Set a config value
    void set_config_value(const std::string& mod_id, const std::string& key,
                          const std::string& value);

    // --- Data Generation Bridge ---
    // Maps Forge data generation -> PYMC data system

    // Register a block state definition
    void register_blockstate(const std::string& block_id,
                              const std::map<std::string, std::vector<std::string>>& variants);

    // Register an item model
    void register_item_model(const std::string& item_id, const std::string& parent_model);

    // Register a recipe
    void register_recipe(const std::string& recipe_id,
                          const std::map<std::string, std::string>& recipe_data);

    // --- Query ---

    // Get registered block IDs
    std::vector<std::string> get_registered_blocks() const;

    // Get registered item IDs
    std::vector<std::string> get_registered_items() const;

    // Get registered capability names
    std::vector<std::string> get_registered_capabilities() const;

    // Get item handler data for a block
    std::optional<ForgeItemHandlerData> get_item_handler(const std::string& block_id) const;

    // Get fluid handler data for a block
    std::optional<ForgeFluidHandlerData> get_fluid_handler(const std::string& block_id) const;

    // Get energy storage data for a block
    std::optional<ForgeEnergyStorageData> get_energy_storage(const std::string& block_id) const;

    // Check if a block is registered
    bool is_block_registered(const std::string& block_id) const;

    // Check if an item is registered
    bool is_item_registered(const std::string& item_id) const;

private:
    // Registered blocks (block_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> blocks_;

    // Registered items (item_id -> properties)
    std::unordered_map<std::string, std::map<std::string, std::string>> items_;

    // Registered capabilities (capability_name -> data)
    std::unordered_map<std::string, ForgeCapabilityData> capabilities_;

    // Item handlers (block_id -> handler data)
    std::unordered_map<std::string, ForgeItemHandlerData> item_handlers_;

    // Fluid handlers (block_id -> handler data)
    std::unordered_map<std::string, ForgeFluidHandlerData> fluid_handlers_;

    // Energy storages (block_id -> storage data)
    std::unordered_map<std::string, ForgeEnergyStorageData> energy_storages_;

    // Mod configs (mod_id -> key -> value)
    std::unordered_map<std::string, std::map<std::string, std::string>> configs_;

    // Blockstate definitions (block_id -> variants)
    std::unordered_map<std::string, std::map<std::string, std::vector<std::string>>> blockstates_;

    // Item models (item_id -> parent_model)
    std::unordered_map<std::string, std::string> item_models_;

    // Recipes (recipe_id -> data)
    std::unordered_map<std::string, std::map<std::string, std::string>> recipes_;

    // Event callbacks
    std::vector<ForgeEntityJoinCallback> entity_join_callbacks_;
    std::vector<ForgeEntityLeaveCallback> entity_leave_callbacks_;
    std::vector<ForgeBlockBreakCallback> block_break_callbacks_;
    std::vector<ForgeBlockPlaceCallback> block_place_callbacks_;
    std::vector<ForgePlayerInteractCallback> player_interact_callbacks_;
    std::vector<ForgeLivingHurtCallback> living_hurt_callbacks_;
    std::vector<ForgeLivingDeathCallback> living_death_callbacks_;
    std::vector<ForgeTickCallback> tick_callbacks_;
    std::vector<ForgeChunkLoadCallback> chunk_load_callbacks_;
    std::vector<ForgeChunkUnloadCallback> chunk_unload_callbacks_;

    // Mutex for thread safety
    mutable std::mutex mutex_;
};

}  // namespace mods
}  // namespace pymc

#endif  // PYMC_FORGE_API_H
