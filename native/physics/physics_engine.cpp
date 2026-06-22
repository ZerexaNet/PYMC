// ============================================================
// PyMC - Physics Engine Implementation
// AABB collision, gravity, drag, fluid flow, falling blocks
// ============================================================

#include "physics_engine.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>

namespace pymc {

// Well-known block IDs
static constexpr uint16_t BL_AIR = 0;
static constexpr uint16_t BL_STONE = 1;
static constexpr uint16_t BL_WATER = 80;
static constexpr uint16_t BL_LAVA = 96;
static constexpr uint16_t BL_SAND = 112;
static constexpr uint16_t BL_GRAVEL = 118;
static constexpr uint16_t BL_ANVIL = 1658;
static constexpr uint16_t BL_SNOW_LAYER = 562;
static constexpr uint16_t BL_SLAB_BOTTOM = 928;
static constexpr uint16_t BL_SLAB_TOP = 929;
static constexpr uint16_t BL_CACTUS = 658;

PhysicsEngine::PhysicsEngine() {
    init_default_shapes();
}

PhysicsEngine::~PhysicsEngine() = default;

// ===========================================================
// Entity management
// ===========================================================

void PhysicsEngine::set_entity(const PhysicsEntity& entity) {
    entities_[entity.entity_id] = entity;
}

void PhysicsEngine::remove_entity(int32_t entity_id) {
    entities_.erase(entity_id);
}

// ===========================================================
// Block data management
// ===========================================================

void PhysicsEngine::set_blocks(const std::vector<BlockData>& blocks) {
    for (const auto& bd : blocks) {
        blocks_[{bd.x, bd.y, bd.z}] = bd.block_state;
    }
}

void PhysicsEngine::clear_blocks() {
    blocks_.clear();
}

// ===========================================================
// Physics tick
// ===========================================================

std::vector<PhysicsUpdate> PhysicsEngine::tick() {
    std::vector<PhysicsUpdate> updates;
    updates.reserve(entities_.size());

    for (auto& [id, entity] : entities_) {
        PhysicsUpdate update;
        update.entity_id = id;
        update.new_x = entity.x;
        update.new_y = entity.y;
        update.new_z = entity.z;
        update.new_vx = entity.vx;
        update.new_vy = entity.vy;
        update.new_vz = entity.vz;
        update.on_ground = entity.on_ground;
        update.collided_x = false;
        update.collided_y = false;
        update.collided_z = false;
        update.landed = false;
        update.landed_block_state = 0;
        update.landed_x = update.landed_y = update.landed_z = 0;

        // Apply gravity and drag
        apply_forces(entity);

        // Resolve collisions with world blocks
        resolve_collisions(entity, update);

        // Handle falling blocks
        if (entity.is_falling_block && entity.on_ground) {
            update.landed = true;
            update.landed_block_state = entity.block_state;
            update.landed_x = static_cast<int32_t>(std::floor(entity.x));
            update.landed_y = static_cast<int32_t>(std::floor(entity.y));
            update.landed_z = static_cast<int32_t>(std::floor(entity.z));
        }

        // Item entities: apply extra drag when on ground
        if (entity.is_item && entity.on_ground) {
            entity.vx *= 0.6;
            entity.vz *= 0.6;
        }

        update.new_x = entity.x;
        update.new_y = entity.y;
        update.new_z = entity.z;
        update.new_vx = entity.vx;
        update.new_vy = entity.vy;
        update.new_vz = entity.vz;
        update.on_ground = entity.on_ground;

        updates.push_back(update);
    }

    return updates;
}

// ===========================================================
// Force application
// ===========================================================

void PhysicsEngine::apply_forces(PhysicsEntity& entity) {
    // Gravity
    if (entity.has_gravity) {
        double g = GRAVITY * entity.gravity_multiplier;
        entity.vy = std::clamp(entity.vy - g, -MAX_VELOCITY, MAX_VELOCITY);
    }

    // Drag
    if (entity.has_drag) {
        double d = DRAG * entity.drag_multiplier;
        entity.vx *= d;
        entity.vy *= d;
        entity.vz *= d;
    }

    // Item entities: extra gravity
    if (entity.is_item) {
        entity.vy = std::clamp(entity.vy - 0.04, -MAX_VELOCITY, MAX_VELOCITY);
    }
}

// ===========================================================
// Collision resolution
// ===========================================================

void PhysicsEngine::resolve_collisions(PhysicsEntity& entity, PhysicsUpdate& update) {
    // Move in each axis separately for proper sliding collision

    // X axis
    entity.x += entity.vx;
    AABB entity_box = entity.world_aabb();
    auto collisions = get_potential_collisions(entity_box);
    for (const auto& block_aabb : collisions) {
        if (entity_box.intersects(block_aabb)) {
            if (entity.vx > 0) {
                entity.x = block_aabb.min_x - entity.bounding_box.max_x - ENTITY_PADDING;
            } else if (entity.vx < 0) {
                entity.x = block_aabb.max_x - entity.bounding_box.min_x + ENTITY_PADDING;
            }
            entity.vx = 0;
            update.collided_x = true;
            entity_box = entity.world_aabb();
        }
    }

    // Y axis
    entity.y += entity.vy;
    entity_box = entity.world_aabb();
    collisions = get_potential_collisions(entity_box);
    bool hit_ground = false;
    for (const auto& block_aabb : collisions) {
        if (entity_box.intersects(block_aabb)) {
            if (entity.vy < 0) {
                entity.y = block_aabb.max_y - entity.bounding_box.min_y + ENTITY_PADDING;
                hit_ground = true;
            } else if (entity.vy > 0) {
                entity.y = block_aabb.min_y - entity.bounding_box.max_y - ENTITY_PADDING;
            }
            entity.vy = 0;
            update.collided_y = true;
            entity_box = entity.world_aabb();
        }
    }

    // Auto-step: if we hit a wall but there's a 1-block gap above
    if (update.collided_x && !update.collided_y && entity.on_ground) {
        // Try stepping up
        double old_y = entity.y;
        entity.y += STEP_HEIGHT;
        AABB step_box = entity.world_aabb();
        bool can_step = true;
        auto step_collisions = get_potential_collisions(step_box);
        for (const auto& block_aabb : step_collisions) {
            if (step_box.intersects(block_aabb)) {
                can_step = false;
                break;
            }
        }
        if (can_step) {
            // Step succeeded — resolve X again
            entity.x += entity.vx;
        } else {
            // Step failed — revert Y
            entity.y = old_y;
        }
    }

    entity.on_ground = hit_ground || (entity.on_ground && update.collided_y);

    // Z axis
    entity.z += entity.vz;
    entity_box = entity.world_aabb();
    collisions = get_potential_collisions(entity_box);
    for (const auto& block_aabb : collisions) {
        if (entity_box.intersects(block_aabb)) {
            if (entity.vz > 0) {
                entity.z = block_aabb.min_z - entity.bounding_box.max_z - ENTITY_PADDING;
            } else if (entity.vz < 0) {
                entity.z = block_aabb.max_z - entity.bounding_box.min_z + ENTITY_PADDING;
            }
            entity.vz = 0;
            update.collided_z = true;
            entity_box = entity.world_aabb();
        }
    }

    // Check if still on ground (detect floor below)
    if (!hit_ground && entity.on_ground) {
        AABB ground_check = entity.world_aabb();
        ground_check.min_y -= 0.05;
        ground_check.max_y = ground_check.min_y + 0.05;
        auto ground_collisions = get_potential_collisions(ground_check);
        entity.on_ground = !ground_collisions.empty();
    }

    // Apply friction when on ground
    if (entity.on_ground) {
        entity.vx *= 0.6;
        entity.vz *= 0.6;
    }
}

std::vector<AABB> PhysicsEngine::get_potential_collisions(const AABB& entity_aabb) const {
    std::vector<AABB> result;

    // Calculate block range that could overlap with the entity
    int32_t min_bx = static_cast<int32_t>(std::floor(entity_aabb.min_x));
    int32_t max_bx = static_cast<int32_t>(std::floor(entity_aabb.max_x));
    int32_t min_by = static_cast<int32_t>(std::floor(entity_aabb.min_y));
    int32_t max_by = static_cast<int32_t>(std::floor(entity_aabb.max_y));
    int32_t min_bz = static_cast<int32_t>(std::floor(entity_aabb.min_z));
    int32_t max_bz = static_cast<int32_t>(std::floor(entity_aabb.max_z));

    for (int32_t bx = min_bx; bx <= max_bx; bx++) {
        for (int32_t by = min_by; by <= max_by; by++) {
            for (int32_t bz = min_bz; bz <= max_bz; bz++) {
                uint16_t block = get_block_at(bx, by, bz);
                if (block == BL_AIR) continue;

                BlockShape shape = get_block_shape(block);
                if (shape == BlockShape::EMPTY || shape == BlockShape::FLUID) continue;

                AABB block_aabb;
                if (get_block_aabb(block, block_aabb)) {
                    // Transform to world coordinates
                    block_aabb = block_aabb.offset(
                        static_cast<double>(bx),
                        static_cast<double>(by),
                        static_cast<double>(bz)
                    );
                    result.push_back(block_aabb);
                }
            }
        }
    }

    return result;
}

CollisionResult PhysicsEngine::swept_aabb(const AABB& entity, const AABB& block,
                                           double dx, double dy, double dz) const {
    CollisionResult result;
    result.overlap_x = result.overlap_y = result.overlap_z = 0;
    result.block_x = result.block_y = result.block_z = 0;
    result.collided = false;

    // Expand block by entity size
    AABB expanded = block;
    expanded.min_x -= entity.width() / 2;
    expanded.max_x += entity.width() / 2;
    expanded.min_y -= entity.height() / 2;
    expanded.max_y += entity.height() / 2;
    expanded.min_z -= entity.depth() / 2;
    expanded.max_z += entity.depth() / 2;

    // Calculate entry/exit times for each axis
    double t_min = 0.0;
    double t_max = 1.0;
    int collision_axis = -1;

    // X axis
    if (std::abs(dx) < 1e-10) {
        if (entity.min_x > expanded.max_x || entity.max_x < expanded.min_x) {
            return result;  // No collision
        }
    } else {
        double t_entry_x = (dx > 0) ?
            (expanded.min_x - entity.max_x) / dx :
            (expanded.max_x - entity.min_x) / dx;
        double t_exit_x = (dx > 0) ?
            (expanded.max_x - entity.min_x) / dx :
            (expanded.min_x - entity.max_x) / dx;
        if (t_entry_x > t_min) { t_min = t_entry_x; collision_axis = 0; }
        if (t_exit_x < t_max) t_max = t_exit_x;
    }

    // Y axis
    if (std::abs(dy) < 1e-10) {
        if (entity.min_y > expanded.max_y || entity.max_y < expanded.min_y) {
            return result;
        }
    } else {
        double t_entry_y = (dy > 0) ?
            (expanded.min_y - entity.max_y) / dy :
            (expanded.max_y - entity.min_y) / dy;
        double t_exit_y = (dy > 0) ?
            (expanded.max_y - entity.min_y) / dy :
            (expanded.min_y - entity.max_y) / dy;
        if (t_entry_y > t_min) { t_min = t_entry_y; collision_axis = 1; }
        if (t_exit_y < t_max) t_max = t_exit_y;
    }

    // Z axis
    if (std::abs(dz) < 1e-10) {
        if (entity.min_z > expanded.max_z || entity.max_z < expanded.min_z) {
            return result;
        }
    } else {
        double t_entry_z = (dz > 0) ?
            (expanded.min_z - entity.max_z) / dz :
            (expanded.max_z - entity.min_z) / dz;
        double t_exit_z = (dz > 0) ?
            (expanded.max_z - entity.min_z) / dz :
            (expanded.min_z - entity.max_z) / dz;
        if (t_entry_z > t_min) { t_min = t_entry_z; collision_axis = 2; }
        if (t_exit_z < t_max) t_max = t_exit_z;
    }

    if (t_min > t_max || t_min > 1.0 || t_min < 0.0) {
        return result;  // No collision within this tick
    }

    result.collided = true;
    result.block_x = static_cast<int32_t>(std::floor((block.min_x + block.max_x) / 2));
    result.block_y = static_cast<int32_t>(std::floor((block.min_y + block.max_y) / 2));
    result.block_z = static_cast<int32_t>(std::floor((block.min_z + block.max_z) / 2));

    if (collision_axis == 0) result.overlap_x = dx * (1.0 - t_min);
    if (collision_axis == 1) result.overlap_y = dy * (1.0 - t_min);
    if (collision_axis == 2) result.overlap_z = dz * (1.0 - t_min);

    return result;
}

// ===========================================================
// Block property lookup
// ===========================================================

bool PhysicsEngine::is_solid(int32_t x, int32_t y, int32_t z) const {
    uint16_t block = get_block_at(x, y, z);
    if (block == BL_AIR) return false;
    BlockShape shape = get_block_shape(block);
    return shape == BlockShape::FULL || shape == BlockShape::PARTIAL;
}

uint16_t PhysicsEngine::get_block_at(int32_t x, int32_t y, int32_t z) const {
    auto it = blocks_.find({x, y, z});
    return it != blocks_.end() ? it->second : BL_AIR;
}

BlockShape PhysicsEngine::get_block_shape(uint16_t block_state) const {
    // Air, water, lava: no collision
    if (block_state == BL_AIR || block_state == BL_WATER || block_state == BL_LAVA) {
        return BlockShape::EMPTY;
    }

    // Most blocks are full cubes
    // Special cases for partial blocks are handled in get_block_aabb
    return BlockShape::FULL;
}

bool PhysicsEngine::get_block_aabb(uint16_t block_state, AABB& out) const {
    if (block_state == BL_AIR) return false;
    if (block_state == BL_WATER || block_state == BL_LAVA) return false;

    // Default: full 1x1x1 cube
    out = {0.0, 0.0, 0.0, 1.0, 1.0, 1.0};

    // Special cases for partial blocks
    // Slabs (bottom)
    if (block_state == BL_SLAB_BOTTOM) {
        out = {0.0, 0.0, 0.0, 1.0, 0.5, 1.0};
    }
    // Slabs (top)
    if (block_state == BL_SLAB_TOP) {
        out = {0.0, 0.5, 0.0, 1.0, 1.0, 1.0};
    }
    // Snow layers
    if (block_state == BL_SNOW_LAYER) {
        out = {0.0, 0.0, 0.0, 1.0, 0.125, 1.0};
    }
    // Cactus: slightly smaller
    if (block_state == BL_CACTUS) {
        out = {0.0625, 0.0, 0.0625, 0.9375, 1.0, 0.9375};
    }

    return true;
}

bool PhysicsEngine::is_fluid(uint16_t block_state) const {
    return block_state == BL_WATER || block_state == BL_LAVA;
}

// ===========================================================
// Fluid simulation
// ===========================================================

void PhysicsEngine::add_fluid_source(int x, int y, int z, uint16_t block_state, int8_t level) {
    fluid_sources_.push_back({x, y, z, block_state, level});
}

void PhysicsEngine::remove_fluid_source(int x, int y, int z) {
    fluid_sources_.erase(
        std::remove_if(fluid_sources_.begin(), fluid_sources_.end(),
            [x, y, z](const FluidSource& f) {
                return f.x == x && f.y == y && f.z == z;
            }),
        fluid_sources_.end());
}

std::vector<FluidUpdate> PhysicsEngine::tick_fluids() {
    std::vector<FluidUpdate> updates;

    for (const auto& source : fluid_sources_) {
        bool is_lava = (source.block_state == BL_LAVA);

        // Fluid flows horizontally and downward
        // Level decreases by 1 each block from source (max 7 for water, 3 for lava)
        int max_level = is_lava ? 3 : 7;
        int flow_rate = is_lava ? 2 : 1;  // Lava flows slower

        // Flow downward first
        int32_t below_x = source.x;
        int32_t below_y = source.y - 1;
        int32_t below_z = source.z;

        if (!is_solid(below_x, below_y, below_z) &&
            get_block_at(below_x, below_y, below_z) != source.block_state) {
            FluidUpdate down;
            down.x = below_x;
            down.y = below_y;
            down.z = below_z;
            down.new_block_state = source.block_state;
            down.new_fluid_level = 0;  // Falling fluid = source level
            updates.push_back(down);
        } else {
            // Flow horizontally
            static constexpr int dx[] = {-1, 1, 0, 0};
            static constexpr int dz[] = {0, 0, -1, 1};

            for (int d = 0; d < 4; d++) {
                int32_t nx = source.x + dx[d];
                int32_t nz = source.z + dz[d];

                if (!is_solid(nx, source.y, nz) &&
                    get_block_at(nx, source.y, nz) != source.block_state) {
                    FluidUpdate horizontal;
                    horizontal.x = nx;
                    horizontal.y = source.y;
                    horizontal.z = nz;
                    horizontal.new_block_state = source.block_state;
                    horizontal.new_fluid_level = static_cast<int8_t>(
                        std::min(source.level + 1, max_level));
                    updates.push_back(horizontal);
                }
            }
        }
    }

    return updates;
}

// ===========================================================
// Default shape initialization
// ===========================================================

void PhysicsEngine::init_default_shapes() {
    // Block shapes are determined dynamically by get_block_shape()
    // This method is for future extension with custom block registries
}

}  // namespace pymc
