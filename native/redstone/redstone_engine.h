// ============================================================
// PyMC - High-Performance Redstone Simulation Engine
//
// Features:
//   - Spatial hash map for O(1) component lookup
//   - Dirty flag tracking: only recalculate changed components
//   - BFS-based signal propagation
//   - Support for all vanilla redstone components:
//     wire, torch, repeater, comparator, piston, observer,
//     lever, button, pressure plate, etc.
//   - Parallel-safe tick processing for independent subgraphs
// ============================================================

#ifndef PYMC_REDSTONE_ENGINE_H
#define PYMC_REDSTONE_ENGINE_H

#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <deque>
#include <array>
#include <functional>
#include <mutex>

namespace pymc {

// -----------------------------------------------------------
// Redstone component types
// -----------------------------------------------------------
enum class ComponentType : uint8_t {
    WIRE = 0,
    TORCH = 1,
    REPEATER = 2,
    COMPARATOR = 3,
    PISTON = 4,
    STICKY_PISTON = 5,
    OBSERVER = 6,
    LEVER = 7,
    BUTTON = 8,
    PRESSURE_PLATE = 9,
    WEIGHTED_PRESSURE_PLATE = 10,
    TRIPWIRE_HOOK = 11,
    TRIPWIRE = 12,
    DAYLIGHT_DETECTOR = 13,
    REDSTONE_BLOCK = 14,
    TARGET = 15,
    LECTERN = 16,
};

// Facing direction
enum class Facing : uint8_t {
    DOWN = 0,
    UP = 1,
    NORTH = 2,
    SOUTH = 3,
    WEST = 4,
    EAST = 5,
};

// 6 cardinal directions
constexpr int DIRECTION_COUNT = 6;
constexpr Facing ALL_DIRECTIONS[] = {
    Facing::DOWN, Facing::UP,
    Facing::NORTH, Facing::SOUTH,
    Facing::WEST, Facing::EAST
};

// Direction offsets [dir] -> {dx, dy, dz}
struct DirectionOffset {
    int dx, dy, dz;
};

constexpr DirectionOffset DIR_OFFSETS[] = {
    {0, -1, 0},   // DOWN
    {0,  1, 0},   // UP
    {0,  0, -1},  // NORTH
    {0,  0,  1},  // SOUTH
    {-1, 0,  0},  // WEST
    {1,  0,  0},  // EAST
};

// Get opposite facing
inline Facing opposite(Facing f) {
    switch (f) {
        case Facing::DOWN:  return Facing::UP;
        case Facing::UP:    return Facing::DOWN;
        case Facing::NORTH: return Facing::SOUTH;
        case Facing::SOUTH: return Facing::NORTH;
        case Facing::WEST:  return Facing::EAST;
        case Facing::EAST:  return Facing::WEST;
    }
    return Facing::NORTH;
}

// -----------------------------------------------------------
// Block position key for spatial hash map
// -----------------------------------------------------------
struct BlockPos {
    int32_t x, y, z;

    bool operator==(const BlockPos& o) const {
        return x == o.x && y == o.y && z == o.z;
    }
};

struct BlockPosHash {
    size_t operator()(const BlockPos& p) const {
        // FNV-1a inspired hash for 3D positions
        size_t h = 14695981039346656037ULL;
        h ^= static_cast<size_t>(p.x);
        h *= 1099511628211ULL;
        h ^= static_cast<size_t>(p.y);
        h *= 1099511628211ULL;
        h ^= static_cast<size_t>(p.z);
        h *= 1099511628211ULL;
        return h;
    }
};

// -----------------------------------------------------------
// Redstone component state
// -----------------------------------------------------------
struct RedstoneComponent {
    BlockPos pos;
    ComponentType type;
    Facing facing;

    // Signal level (0-15 for wire, 0/1 for most others)
    int8_t power;

    // Is this component currently outputting power?
    bool powered;

    // Is this component in a "dirty" state (needs recalculation)?
    bool dirty;

    // Repeater/comparator specific
    int8_t delay;           // Repeater delay (1-4 ticks)
    int8_t delay_counter;   // Current delay countdown
    int8_t output_power;    // Latched output power (for repeater/comparator)

    // Comparator specific
    int8_t side_input_power; // Power from side inputs
    bool compare_mode;       // true = compare, false = subtract

    // Piston specific
    bool extended;

    // Observer specific
    int8_t detection_counter; // Ticks since last detection

    // Button/lever/pressure plate
    bool active;             // Is the switch currently on?
    int16_t active_ticks;    // Remaining active ticks (for buttons)

    RedstoneComponent()
        : pos{0, 0, 0}
        , type(ComponentType::WIRE)
        , facing(Facing::NORTH)
        , power(0)
        , powered(false)
        , dirty(false)
        , delay(1)
        , delay_counter(0)
        , output_power(0)
        , side_input_power(0)
        , compare_mode(true)
        , extended(false)
        , detection_counter(0)
        , active(false)
        , active_ticks(0)
    {}
};

// -----------------------------------------------------------
// Update record — sent back to Python to apply world changes
// -----------------------------------------------------------
struct RedstoneUpdate {
    int32_t x, y, z;
    int32_t new_block_state;  // The new block state ID to set
    int32_t flags;            // Update flags (notify neighbors, etc.)
};

// -----------------------------------------------------------
// RedstoneEngine — main simulation class
// -----------------------------------------------------------
class RedstoneEngine {
public:
    RedstoneEngine();
    ~RedstoneEngine();

    // ---- Component management ----

    // Add a redstone component at the given position.
    void add_component(int x, int y, int z, ComponentType type, Facing facing = Facing::NORTH);

    // Remove a component.
    void remove_component(int x, int y, int z);

    // Set the power level of a component directly (e.g., from a lever).
    void set_power_level(int x, int y, int z, int level);

    // Get the current power level.
    int get_power_level(int x, int y, int z) const;

    // Mark a component as needing recalculation.
    void mark_dirty(int x, int y, int z);

    // ---- Simulation ----

    // Process one redstone tick.
    // Returns the list of block state updates to apply.
    std::vector<RedstoneUpdate> tick();

    // ---- Query ----

    // Check if a position has a redstone component.
    bool has_component(int x, int y, int z) const;

    // Get component at position (nullptr if none).
    const RedstoneComponent* get_component(int x, int y, int z) const;

    // Get all pending updates since last tick.
    std::vector<RedstoneUpdate> get_pending_updates() const;

    // Get the number of active components.
    size_t component_count() const { return components_.size(); }

    // Clear all components.
    void clear();

private:
    // Spatial hash map of all redstone components
    std::unordered_map<BlockPos, RedstoneComponent, BlockPosHash> components_;

    // Set of positions that need recalculation this tick
    std::unordered_set<BlockPos, BlockPosHash> dirty_set_;

    // Pending block state updates
    std::vector<RedstoneUpdate> pending_updates_;

    // ---- Internal simulation methods ----

    // Calculate the power output of a component
    int calculate_output_power(RedstoneComponent& comp);

    // Propagate signal from a component to its neighbors
    void propagate_signal(RedstoneComponent& comp);

    // Update a wire component's power based on neighbors
    void update_wire(RedstoneComponent& comp);

    // Update a torch component
    void update_torch(RedstoneComponent& comp);

    // Update a repeater component
    void update_repeater(RedstoneComponent& comp);

    // Update a comparator component
    void update_comparator(RedstoneComponent& comp);

    // Update a piston component
    void update_piston(RedstoneComponent& comp);

    // Update an observer component
    void update_observer(RedstoneComponent& comp);

    // Get the strongest signal a component can receive from its neighbors
    int get_strongest_input(const RedstoneComponent& comp) const;

    // Get directional input power
    int get_input_from_dir(const BlockPos& pos, Facing from_dir) const;

    // Add an update to the pending list
    void add_update(int x, int y, int z, int new_block_state, int flags = 0);

    // Mark neighbors as dirty
    void mark_neighbors_dirty(const BlockPos& pos);

    // Schedule a delayed update (for repeaters/comparators)
    struct DelayedUpdate {
        BlockPos pos;
        int8_t target_power;
        int8_t remaining_ticks;
    };
    std::vector<DelayedUpdate> delayed_updates_;
};

}  // namespace pymc

#endif  // PYMC_REDSTONE_ENGINE_H
