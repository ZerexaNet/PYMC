// ============================================================
// PyMC - Physics Engine
//
// High-performance physics simulation:
//   - AABB collision detection and resolution
//   - Entity-world collision with swept collision
//   - Fluid flow simulation
//   - Falling block entities (sand, gravel, anvils, etc.)
//   - Gravity and drag
//
// The engine operates on a "snapshot" model:
//   1. Python sends the current entity positions + nearby blocks
//   2. C++ runs physics tick
//   3. C++ returns updated positions + collision events
// ============================================================

#ifndef PYMC_PHYSICS_ENGINE_H
#define PYMC_PHYSICS_ENGINE_H

#include <cstdint>
#include <vector>
#include <array>
#include <unordered_map>
#include <functional>
#include <cmath>

namespace pymc {

// -----------------------------------------------------------
// Constants
// -----------------------------------------------------------
constexpr double GRAVITY = 0.08;            // Blocks per tick^2
constexpr double DRAG = 0.98;               // Velocity multiplier per tick
constexpr double MAX_VELOCITY = 3.92;       // Terminal velocity
constexpr double STEP_HEIGHT = 0.6;         // Max height to auto-step
constexpr double ENTITY_PADDING = 0.001;    // Collision padding

// -----------------------------------------------------------
// AABB (Axis-Aligned Bounding Box)
// -----------------------------------------------------------
struct AABB {
    double min_x, min_y, min_z;
    double max_x, max_y, max_z;

    double width()  const { return max_x - min_x; }
    double height() const { return max_y - min_y; }
    double depth()  const { return max_z - min_z; }

    // Expand the AABB by the given amount in all directions
    AABB expand(double dx, double dy, double dz) const {
        AABB result = *this;
        if (dx < 0) result.min_x += dx;
        else         result.max_x += dx;
        if (dy < 0) result.min_y += dy;
        else         result.max_y += dy;
        if (dz < 0) result.min_z += dz;
        else         result.max_z += dz;
        return result;
    }

    // Check if this AABB intersects another
    bool intersects(const AABB& other) const {
        return min_x < other.max_x && max_x > other.min_x &&
               min_y < other.max_y && max_y > other.min_y &&
               min_z < other.max_z && max_z > other.min_z;
    }

    // Move the AABB by the given offset
    AABB offset(double dx, double dy, double dz) const {
        return {min_x + dx, min_y + dy, min_z + dz,
                max_x + dx, max_y + dy, max_z + dz};
    }
};

// -----------------------------------------------------------
// Entity physics state
// -----------------------------------------------------------
struct PhysicsEntity {
    int32_t entity_id;
    double x, y, z;           // Position (center-bottom)
    double vx, vy, vz;        // Velocity
    AABB bounding_box;         // Relative to position
    bool on_ground;
    bool has_gravity;
    bool has_drag;
    double gravity_multiplier; // 1.0 = normal
    double drag_multiplier;    // 1.0 = normal

    // Entity type flags
    bool is_item;             // Item entities have special physics
    bool is_falling_block;    // Sand, gravel, etc.
    bool is_projectile;       // Arrows, etc.

    // Block state for falling block entities
    uint16_t block_state;

    PhysicsEntity()
        : entity_id(0), x(0), y(0), z(0)
        , vx(0), vy(0), vz(0)
        , bounding_box{-0.3, 0.0, -0.3, 0.3, 1.8, 0.3}
        , on_ground(false), has_gravity(true), has_drag(true)
        , gravity_multiplier(1.0), drag_multiplier(1.0)
        , is_item(false), is_falling_block(false), is_projectile(false)
        , block_state(0)
    {}

    // Get the world-space AABB
    AABB world_aabb() const {
        return bounding_box.offset(x, y, z);
    }
};

// -----------------------------------------------------------
// Block data for collision (sent from Python)
// -----------------------------------------------------------
struct BlockData {
    int32_t x, y, z;
    uint16_t block_state;
};

// -----------------------------------------------------------
// Collision result
// -----------------------------------------------------------
struct CollisionResult {
    double overlap_x, overlap_y, overlap_z;
    int32_t block_x, block_y, block_z;
    bool collided;
};

// -----------------------------------------------------------
// Physics update result
// -----------------------------------------------------------
struct PhysicsUpdate {
    int32_t entity_id;
    double new_x, new_y, new_z;
    double new_vx, new_vy, new_vz;
    bool on_ground;

    // Collision events
    bool collided_x, collided_y, collided_z;

    // For falling blocks that have landed
    bool landed;
    uint16_t landed_block_state;
    int32_t landed_x, landed_y, landed_z;
};

// -----------------------------------------------------------
// Fluid flow update
// -----------------------------------------------------------
struct FluidUpdate {
    int32_t x, y, z;
    uint16_t new_block_state;   // The fluid block to place
    int8_t new_fluid_level;     // Fluid level (0-7 for water/lava)
};

// -----------------------------------------------------------
// Block collision shape
// -----------------------------------------------------------
enum class BlockShape : uint8_t {
    EMPTY = 0,         // No collision (air, etc.)
    FULL = 1,          // Full 1x1x1 cube
    PARTIAL = 2,       // Has a custom AABB (slabs, stairs, etc.)
    FLUID = 3,         // Fluid block (water, lava) — special handling
};

// -----------------------------------------------------------
// PhysicsEngine — main class
// -----------------------------------------------------------
class PhysicsEngine {
public:
    PhysicsEngine();
    ~PhysicsEngine();

    // ---- Entity management ----

    // Add or update an entity
    void set_entity(const PhysicsEntity& entity);

    // Remove an entity
    void remove_entity(int32_t entity_id);

    // ---- Block data management ----

    // Set blocks for collision detection.
    // Python sends only the blocks near entities.
    void set_blocks(const std::vector<BlockData>& blocks);

    // Clear all block data (call when chunks unload)
    void clear_blocks();

    // ---- Simulation ----

    // Process one physics tick.
    // Returns updated entity positions and collision events.
    std::vector<PhysicsUpdate> tick();

    // ---- Block property lookup ----

    // Get the collision shape of a block
    BlockShape get_block_shape(uint16_t block_state) const;

    // Get the collision AABB of a block (in block-local coordinates)
    // Returns true if the block has collision, false if empty
    bool get_block_aabb(uint16_t block_state, AABB& out) const;

    // Check if a block is a fluid
    bool is_fluid(uint16_t block_state) const;

    // ---- Fluid simulation ----

    // Process fluid flow for all tracked fluid blocks
    std::vector<FluidUpdate> tick_fluids();

    // Add a fluid source block
    void add_fluid_source(int x, int y, int z, uint16_t block_state, int8_t level);

    // Remove a fluid source
    void remove_fluid_source(int x, int y, int z);

private:
    // Entity map
    std::unordered_map<int32_t, PhysicsEntity> entities_;

    // Block data (spatial hash for fast lookup)
    struct BlockKey {
        int32_t x, y, z;
        bool operator==(const BlockKey& o) const {
            return x == o.x && y == o.y && z == o.z;
        }
    };

    struct BlockKeyHash {
        size_t operator()(const BlockKey& k) const {
            size_t h = 14695981039346656037ULL;
            h ^= static_cast<size_t>(k.x); h *= 1099511628211ULL;
            h ^= static_cast<size_t>(k.y); h *= 1099511628211ULL;
            h ^= static_cast<size_t>(k.z); h *= 1099511628211ULL;
            return h;
        }
    };

    std::unordered_map<BlockKey, uint16_t, BlockKeyHash> blocks_;

    // Fluid sources
    struct FluidSource {
        int32_t x, y, z;
        uint16_t block_state;
        int8_t level;
    };
    std::vector<FluidSource> fluid_sources_;

    // ---- Internal methods ----

    // Apply gravity and drag to an entity
    void apply_forces(PhysicsEntity& entity);

    // Resolve entity-world collisions
    void resolve_collisions(PhysicsEntity& entity, PhysicsUpdate& update);

    // Get all block AABBs that could collide with the given entity AABB
    std::vector<AABB> get_potential_collisions(const AABB& entity_aabb) const;

    // Swept AABB collision test
    CollisionResult swept_aabb(const AABB& entity, const AABB& block,
                               double dx, double dy, double dz) const;

    // Check if a block position is solid
    bool is_solid(int32_t x, int32_t y, int32_t z) const;

    // Get block state at position (0 = air if not tracked)
    uint16_t get_block_at(int32_t x, int32_t y, int32_t z) const;

    // Initialize default block shapes
    void init_default_shapes();
};

}  // namespace pymc

#endif  // PYMC_PHYSICS_ENGINE_H
