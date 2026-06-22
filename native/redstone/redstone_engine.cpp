// ============================================================
// PyMC - Redstone Engine Implementation
// High-performance redstone simulation with dirty-flag tracking
// ============================================================

#include "redstone_engine.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace pymc {

RedstoneEngine::RedstoneEngine() = default;
RedstoneEngine::~RedstoneEngine() = default;

// ---- Component management ----

void RedstoneEngine::add_component(int x, int y, int z, ComponentType type, Facing facing) {
    BlockPos pos{x, y, z};
    auto& comp = components_[pos];
    comp.pos = pos;
    comp.type = type;
    comp.facing = facing;
    comp.power = 0;
    comp.powered = false;
    comp.dirty = true;
    comp.delay = 1;
    comp.delay_counter = 0;
    comp.output_power = 0;
    comp.side_input_power = 0;
    comp.compare_mode = true;
    comp.extended = false;
    comp.detection_counter = 0;
    comp.active = false;
    comp.active_ticks = 0;

    dirty_set_.insert(pos);
    mark_neighbors_dirty(pos);
}

void RedstoneEngine::remove_component(int x, int y, int z) {
    BlockPos pos{x, y, z};
    auto it = components_.find(pos);
    if (it != components_.end()) {
        mark_neighbors_dirty(pos);
        components_.erase(it);
        dirty_set_.erase(pos);
    }
}

void RedstoneEngine::set_power_level(int x, int y, int z, int level) {
    BlockPos pos{x, y, z};
    auto it = components_.find(pos);
    if (it != components_.end()) {
        it->second.power = static_cast<int8_t>(std::clamp(level, 0, 15));
        it->second.dirty = true;
        dirty_set_.insert(pos);
    }
}

int RedstoneEngine::get_power_level(int x, int y, int z) const {
    BlockPos pos{x, y, z};
    auto it = components_.find(pos);
    if (it != components_.end()) {
        return it->second.power;
    }
    return 0;
}

void RedstoneEngine::mark_dirty(int x, int y, int z) {
    BlockPos pos{x, y, z};
    auto it = components_.find(pos);
    if (it != components_.end()) {
        it->second.dirty = true;
        dirty_set_.insert(pos);
    }
}

// ---- Simulation ----

std::vector<RedstoneUpdate> RedstoneEngine::tick() {
    pending_updates_.clear();

    // Process delayed updates (repeaters, etc.)
    std::vector<DelayedUpdate> next_delayed;
    for (auto& du : delayed_updates_) {
        du.remaining_ticks--;
        if (du.remaining_ticks <= 0) {
            auto it = components_.find(du.pos);
            if (it != components_.end()) {
                it->second.output_power = du.target_power;
                it->second.dirty = true;
                dirty_set_.insert(du.pos);
            }
        } else {
            next_delayed.push_back(du);
        }
    }
    delayed_updates_ = std::move(next_delayed);

    // Process all dirty components using BFS-like propagation
    // We iterate up to 16 times to handle cascading updates
    for (int iteration = 0; iteration < 16 && !dirty_set_.empty(); iteration++) {
        auto current_dirty = std::move(dirty_set_);
        dirty_set_.clear();

        for (const auto& pos : current_dirty) {
            auto it = components_.find(pos);
            if (it == components_.end()) continue;

            auto& comp = it->second;
            comp.dirty = false;

            int old_power = comp.power;
            bool old_powered = comp.powered;

            switch (comp.type) {
                case ComponentType::WIRE:
                    update_wire(comp);
                    break;
                case ComponentType::TORCH:
                    update_torch(comp);
                    break;
                case ComponentType::REPEATER:
                    update_repeater(comp);
                    break;
                case ComponentType::COMPARATOR:
                    update_comparator(comp);
                    break;
                case ComponentType::PISTON:
                case ComponentType::STICKY_PISTON:
                    update_piston(comp);
                    break;
                case ComponentType::OBSERVER:
                    update_observer(comp);
                    break;
                case ComponentType::LEVER:
                case ComponentType::BUTTON:
                case ComponentType::PRESSURE_PLATE:
                case ComponentType::WEIGHTED_PRESSURE_PLATE:
                    // These are input devices; their power is set externally
                    if (comp.active) {
                        comp.powered = true;
                        comp.power = (comp.type == ComponentType::WEIGHTED_PRESSURE_PLATE)
                                     ? static_cast<int8_t>(std::min(15, static_cast<int>(comp.power))) : 15;
                    }
                    break;
                case ComponentType::REDSTONE_BLOCK:
                    comp.powered = true;
                    comp.power = 15;
                    break;
                default:
                    break;
            }

            // If power state changed, propagate to neighbors
            if (comp.power != old_power || comp.powered != old_powered) {
                propagate_signal(comp);
            }
        }
    }

    // Process any remaining delayed updates for buttons, etc.
    for (auto& [pos, comp] : components_) {
        if (comp.type == ComponentType::BUTTON && comp.active) {
            comp.active_ticks--;
            if (comp.active_ticks <= 0) {
                comp.active = false;
                comp.powered = false;
                comp.power = 0;
                dirty_set_.insert(pos);
                mark_neighbors_dirty(pos);
            }
        }
        if (comp.type == ComponentType::OBSERVER && comp.detection_counter > 0) {
            comp.detection_counter--;
            if (comp.detection_counter == 0) {
                comp.powered = false;
                comp.power = 0;
                dirty_set_.insert(pos);
                mark_neighbors_dirty(pos);
            }
        }
    }

    return pending_updates_;
}

// ---- Internal simulation methods ----

void RedstoneEngine::update_wire(RedstoneComponent& comp) {
    int max_input = get_strongest_input(comp);

    // Wire power decreases by 1 per block from source
    int new_power = std::max(0, max_input - 1);

    // Direct power sources override
    if (comp.active) {
        new_power = std::max(new_power, static_cast<int>(comp.power));
    }

    comp.power = static_cast<int8_t>(std::clamp(new_power, 0, 15));
    comp.powered = comp.power > 0;
}

void RedstoneEngine::update_torch(RedstoneComponent& comp) {
    // A torch is ON when its input is OFF, and vice versa
    int input_power = get_input_from_dir(comp.pos, opposite(comp.facing));
    bool input_powered = input_power > 0;

    bool should_be_on = !input_powered;
    comp.powered = should_be_on;
    comp.power = should_be_on ? 15 : 0;
}

void RedstoneEngine::update_repeater(RedstoneComponent& comp) {
    int input_power = get_input_from_dir(comp.pos, opposite(comp.facing));
    bool input_powered = input_power > 0;

    int target_output = input_powered ? 15 : 0;

    if (target_output != comp.output_power) {
        // Schedule the output change after the delay
        delayed_updates_.push_back({
            comp.pos,
            static_cast<int8_t>(target_output),
            comp.delay
        });
    }

    // Current output remains until delay expires
    comp.powered = comp.output_power > 0;
    comp.power = comp.output_power;
}

void RedstoneEngine::update_comparator(RedstoneComponent& comp) {
    int back_input = get_input_from_dir(comp.pos, opposite(comp.facing));
    int side_a = get_input_from_dir(comp.pos, Facing::WEST);  // Simplified
    int side_b = get_input_from_dir(comp.pos, Facing::EAST);  // Simplified
    int max_side = std::max(side_a, side_b);

    int output;
    if (comp.compare_mode) {
        output = (back_input >= max_side) ? back_input : 0;
    } else {
        output = std::max(0, back_input - max_side);
    }

    comp.output_power = static_cast<int8_t>(std::clamp(output, 0, 15));
    comp.power = comp.output_power;
    comp.powered = comp.power > 0;
}

void RedstoneEngine::update_piston(RedstoneComponent& comp) {
    int input_power = get_strongest_input(comp);
    bool should_extend = input_power > 0;

    if (should_extend != comp.extended) {
        comp.extended = should_extend;
        // Generate block update for piston extension/retraction
        int dx = DIR_OFFSETS[static_cast<int>(comp.facing)].dx;
        int dy = DIR_OFFSETS[static_cast<int>(comp.facing)].dy;
        int dz = DIR_OFFSETS[static_cast<int>(comp.facing)].dz;

        if (should_extend) {
            // Push block in front of piston
            add_update(comp.pos.x + dx, comp.pos.y + dy, comp.pos.z + dz,
                       comp.type == ComponentType::STICKY_PISTON ? -2 : -1, 0x01);
        }
        add_update(comp.pos.x, comp.pos.y, comp.pos.z,
                   should_extend ? -3 : -4, 0x02);  // Piston head update
    }
}

void RedstoneEngine::update_observer(RedstoneComponent& comp) {
    // Observers detect changes in the block they're facing
    // Detection is handled externally (Python sends a "block changed" event)
    // Here we just manage the pulse output
    if (comp.powered && comp.detection_counter > 0) {
        // Still in detection pulse
        return;
    }
}

void RedstoneEngine::propagate_signal(RedstoneComponent& comp) {
    mark_neighbors_dirty(comp.pos);

    // Generate a block state update for this component
    // The actual block state encoding is handled by the Python side
    add_update(comp.pos.x, comp.pos.y, comp.pos.z,
               comp.powered ? 1 : 0, 0x01);
}

int RedstoneEngine::get_strongest_input(const RedstoneComponent& comp) const {
    int max_power = 0;
    for (int d = 0; d < DIRECTION_COUNT; d++) {
        Facing dir = ALL_DIRECTIONS[d];
        int power = get_input_from_dir(comp.pos, dir);
        max_power = std::max(max_power, power);
    }
    return max_power;
}

int RedstoneEngine::get_input_from_dir(const BlockPos& pos, Facing from_dir) const {
    // Get the power signal coming FROM the direction `from_dir`
    // That means we look at the neighbor in that direction
    int d = static_cast<int>(from_dir);
    BlockPos neighbor{
        pos.x + DIR_OFFSETS[d].dx,
        pos.y + DIR_OFFSETS[d].dy,
        pos.z + DIR_OFFSETS[d].dz
    };

    auto it = components_.find(neighbor);
    if (it == components_.end()) return 0;

    const auto& ncomp = it->second;

    // Different component types propagate differently
    switch (ncomp.type) {
        case ComponentType::WIRE:
            return ncomp.power;
        case ComponentType::TORCH:
            return ncomp.powered ? 15 : 0;
        case ComponentType::REPEATER:
            // Repeater only outputs in its facing direction
            if (ncomp.facing == from_dir) {
                return ncomp.powered ? 15 : 0;
            }
            return 0;
        case ComponentType::COMPARATOR:
            // Comparator outputs in its facing direction
            if (ncomp.facing == from_dir) {
                return ncomp.output_power;
            }
            return 0;
        case ComponentType::LEVER:
        case ComponentType::BUTTON:
        case ComponentType::PRESSURE_PLATE:
        case ComponentType::WEIGHTED_PRESSURE_PLATE:
        case ComponentType::DAYLIGHT_DETECTOR:
        case ComponentType::REDSTONE_BLOCK:
            return ncomp.powered ? 15 : 0;
        default:
            return 0;
    }
}

void RedstoneEngine::add_update(int x, int y, int z, int new_block_state, int flags) {
    pending_updates_.push_back({x, y, z, new_block_state, flags});
}

void RedstoneEngine::mark_neighbors_dirty(const BlockPos& pos) {
    for (int d = 0; d < DIRECTION_COUNT; d++) {
        BlockPos neighbor{
            pos.x + DIR_OFFSETS[d].dx,
            pos.y + DIR_OFFSETS[d].dy,
            pos.z + DIR_OFFSETS[d].dz
        };
        if (components_.count(neighbor)) {
            auto& comp = components_.at(neighbor);
            comp.dirty = true;
            dirty_set_.insert(neighbor);
        }
    }
}

// ---- Query ----

bool RedstoneEngine::has_component(int x, int y, int z) const {
    return components_.count({x, y, z}) > 0;
}

const RedstoneComponent* RedstoneEngine::get_component(int x, int y, int z) const {
    auto it = components_.find({x, y, z});
    return it != components_.end() ? &it->second : nullptr;
}

std::vector<RedstoneUpdate> RedstoneEngine::get_pending_updates() const {
    return pending_updates_;
}

void RedstoneEngine::clear() {
    components_.clear();
    dirty_set_.clear();
    pending_updates_.clear();
    delayed_updates_.clear();
}

}  // namespace pymc
