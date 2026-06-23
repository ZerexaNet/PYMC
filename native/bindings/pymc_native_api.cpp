// ============================================================
// PyMC - C API Bridge Implementation
// Implements the C-callable API defined in pymc_native_api.h
// ============================================================

#include "pymc_native_api.h"
#include "../core/ipc_shm.h"
#include "../redstone/redstone_engine.h"
#include "../lighting/light_engine.h"
#include "../physics/physics_engine.h"

#include <cstring>
#include <string>

// ===========================================================
// Version Info
// ===========================================================

static const char kVersion[] = "1.0.0";
static constexpr uint32_t kApiVersion = 1;

PYMC_EXPORT const char* pymc_get_version() { return kVersion; }
PYMC_EXPORT uint32_t pymc_get_api_version() { return kApiVersion; }

// ===========================================================
// Shared Memory IPC Functions
// ===========================================================

PYMC_EXPORT void* pymc_ipc_channel_create(const char* name,
                                           uint32_t cmd_size,
                                           uint32_t resp_size,
                                           int create) {
    try {
        auto* channel = new pymc::IPCChannel(name, cmd_size, resp_size, create != 0);
        if (!channel->is_valid()) {
            delete channel;
            return nullptr;
        }
        return channel;
    } catch (...) {
        return nullptr;
    }
}

PYMC_EXPORT void pymc_ipc_channel_destroy(void* handle) {
    if (handle) {
        delete static_cast<pymc::IPCChannel*>(handle);
    }
}

PYMC_EXPORT int pymc_ipc_send_command(void* handle,
                                       const uint8_t* data,
                                       uint32_t len) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    return channel && channel->send_command(data, len) ? 1 : 0;
}

PYMC_EXPORT uint32_t pymc_ipc_recv_response(void* handle,
                                             uint8_t* buffer,
                                             uint32_t max_len) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    if (!channel) return 0;
    return static_cast<uint32_t>(channel->recv_response(buffer, max_len));
}

PYMC_EXPORT uint32_t pymc_ipc_recv_command(void* handle,
                                            uint8_t* buffer,
                                            uint32_t max_len) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    if (!channel) return 0;
    return static_cast<uint32_t>(channel->recv_command(buffer, max_len));
}

PYMC_EXPORT int pymc_ipc_send_response(void* handle,
                                        const uint8_t* data,
                                        uint32_t len) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    return channel && channel->send_response(data, len) ? 1 : 0;
}

PYMC_EXPORT int pymc_ipc_wait_for_command(void* handle, int timeout_ms) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    return channel && channel->wait_for_command(timeout_ms) ? 1 : 0;
}

PYMC_EXPORT int pymc_ipc_wait_for_response(void* handle, int timeout_ms) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    return channel && channel->wait_for_response(timeout_ms) ? 1 : 0;
}

PYMC_EXPORT int pymc_ipc_is_valid(void* handle) {
    auto* channel = static_cast<pymc::IPCChannel*>(handle);
    return channel && channel->is_valid() ? 1 : 0;
}

// ===========================================================
// Redstone Engine
// ===========================================================

PYMC_EXPORT void* pymc_redstone_create() {
    try {
        return new pymc::RedstoneEngine();
    } catch (...) {
        return nullptr;
    }
}

PYMC_EXPORT void pymc_redstone_destroy(void* engine) {
    if (engine) {
        delete static_cast<pymc::RedstoneEngine*>(engine);
    }
}

PYMC_EXPORT void pymc_redstone_add_component(void* engine,
                                              int32_t x, int32_t y, int32_t z,
                                              uint8_t type, uint8_t facing) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (e) {
        e->add_component(x, y, z,
                         static_cast<pymc::ComponentType>(type),
                         static_cast<pymc::Facing>(facing));
    }
}

PYMC_EXPORT void pymc_redstone_remove_component(void* engine,
                                                  int32_t x, int32_t y, int32_t z) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (e) {
        e->remove_component(x, y, z);
    }
}

PYMC_EXPORT void pymc_redstone_set_power(void* engine,
                                          int32_t x, int32_t y, int32_t z,
                                          int32_t level) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (e) {
        e->set_power_level(x, y, z, level);
    }
}

PYMC_EXPORT int32_t pymc_redstone_get_power(void* engine,
                                             int32_t x, int32_t y, int32_t z) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (e) {
        return e->get_power_level(x, y, z);
    }
    return 0;
}

PYMC_EXPORT uint32_t pymc_redstone_tick(void* engine,
                                         int32_t* out_updates,
                                         uint32_t max_updates) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (!e) return 0;

    auto updates = e->tick();
    uint32_t count = std::min(static_cast<uint32_t>(updates.size()), max_updates);

    for (uint32_t i = 0; i < count; i++) {
        out_updates[i * 5 + 0] = updates[i].x;
        out_updates[i * 5 + 1] = updates[i].y;
        out_updates[i * 5 + 2] = updates[i].z;
        out_updates[i * 5 + 3] = updates[i].new_block_state;
        out_updates[i * 5 + 4] = updates[i].flags;
    }

    return count;
}

PYMC_EXPORT void pymc_redstone_clear(void* engine) {
    auto* e = static_cast<pymc::RedstoneEngine*>(engine);
    if (e) {
        e->clear();
    }
}

// ===========================================================
// Light Engine
// ===========================================================

PYMC_EXPORT void* pymc_light_create() {
    try {
        return new pymc::LightEngine();
    } catch (...) {
        return nullptr;
    }
}

PYMC_EXPORT void pymc_light_destroy(void* engine) {
    if (engine) {
        delete static_cast<pymc::LightEngine*>(engine);
    }
}

PYMC_EXPORT void pymc_light_calculate_chunk(void* engine,
                                             const uint16_t* blocks,
                                             uint8_t* sky_light_out,
                                             uint8_t* block_light_out) {
    auto* e = static_cast<pymc::LightEngine*>(engine);
    if (e) {
        e->calculate_chunk_lighting(blocks, sky_light_out, block_light_out);
    }
}

PYMC_EXPORT uint32_t pymc_light_update_block(void* engine,
                                               int32_t x, int32_t y, int32_t z,
                                               uint16_t old_block, uint16_t new_block,
                                               int32_t* out_updates,
                                               uint32_t max_updates) {
    auto* e = static_cast<pymc::LightEngine*>(engine);
    if (!e) return 0;

    auto updates = e->update_block_light(x, y, z, old_block, new_block);
    uint32_t count = std::min(static_cast<uint32_t>(updates.size()), max_updates);

    for (uint32_t i = 0; i < count; i++) {
        out_updates[i * 5 + 0] = updates[i].x;
        out_updates[i * 5 + 1] = updates[i].y;
        out_updates[i * 5 + 2] = updates[i].z;
        out_updates[i * 5 + 3] = updates[i].new_sky_light;
        out_updates[i * 5 + 4] = updates[i].new_block_light;
    }

    return count;
}

PYMC_EXPORT void pymc_light_set_block_info(void* engine,
                                            uint16_t block_state,
                                            uint8_t sky_type,
                                            uint8_t block_type,
                                            uint8_t emitted_light,
                                            uint8_t filter_level) {
    auto* e = static_cast<pymc::LightEngine*>(engine);
    if (e) {
        pymc::BlockLightInfo info;
        info.sky_type = static_cast<pymc::LightType>(sky_type);
        info.block_type = static_cast<pymc::LightType>(block_type);
        info.emitted_light = emitted_light;
        info.filter_level = filter_level;
        e->set_block_info(block_state, info);
    }
}

// ===========================================================
// Physics Engine
// ===========================================================

PYMC_EXPORT void* pymc_physics_create() {
    try {
        return new pymc::PhysicsEngine();
    } catch (...) {
        return nullptr;
    }
}

PYMC_EXPORT void pymc_physics_destroy(void* engine) {
    if (engine) {
        delete static_cast<pymc::PhysicsEngine*>(engine);
    }
}

PYMC_EXPORT void pymc_physics_set_entity(void* engine,
                                          const struct PymcPhysicsEntity* entity) {
    auto* e = static_cast<pymc::PhysicsEngine*>(engine);
    if (!e || !entity) return;

    pymc::PhysicsEntity pe;
    pe.entity_id = entity->entity_id;
    pe.x = entity->x;
    pe.y = entity->y;
    pe.z = entity->z;
    pe.vx = entity->vx;
    pe.vy = entity->vy;
    pe.vz = entity->vz;
    pe.bounding_box = {
        entity->bb_min_x, entity->bb_min_y, entity->bb_min_z,
        entity->bb_max_x, entity->bb_max_y, entity->bb_max_z
    };
    pe.on_ground = entity->on_ground != 0;
    pe.has_gravity = entity->has_gravity != 0;
    pe.is_item = entity->is_item != 0;
    pe.is_falling_block = entity->is_falling_block != 0;
    pe.block_state = entity->block_state;

    e->set_entity(pe);
}

PYMC_EXPORT void pymc_physics_remove_entity(void* engine, int32_t entity_id) {
    auto* e = static_cast<pymc::PhysicsEngine*>(engine);
    if (e) {
        e->remove_entity(entity_id);
    }
}

PYMC_EXPORT void pymc_physics_set_blocks(void* engine,
                                          const int32_t* xyz_data,
                                          const uint16_t* block_states,
                                          uint32_t count) {
    auto* e = static_cast<pymc::PhysicsEngine*>(engine);
    if (!e) return;

    std::vector<pymc::BlockData> blocks(count);
    for (uint32_t i = 0; i < count; i++) {
        blocks[i].x = xyz_data[i * 3];
        blocks[i].y = xyz_data[i * 3 + 1];
        blocks[i].z = xyz_data[i * 3 + 2];
        blocks[i].block_state = block_states[i];
    }

    e->set_blocks(blocks);
}

PYMC_EXPORT uint32_t pymc_physics_tick(void* engine,
                                        struct PymcPhysicsUpdate* out_updates,
                                        uint32_t max_updates) {
    auto* e = static_cast<pymc::PhysicsEngine*>(engine);
    if (!e) return 0;

    auto updates = e->tick();
    uint32_t count = std::min(static_cast<uint32_t>(updates.size()), max_updates);

    for (uint32_t i = 0; i < count; i++) {
        out_updates[i].entity_id = updates[i].entity_id;
        out_updates[i].new_x = updates[i].new_x;
        out_updates[i].new_y = updates[i].new_y;
        out_updates[i].new_z = updates[i].new_z;
        out_updates[i].new_vx = updates[i].new_vx;
        out_updates[i].new_vy = updates[i].new_vy;
        out_updates[i].new_vz = updates[i].new_vz;
        out_updates[i].on_ground = updates[i].on_ground ? 1 : 0;
        out_updates[i].landed = updates[i].landed ? 1 : 0;
        out_updates[i].landed_block_state = updates[i].landed_block_state;
        out_updates[i].landed_x = updates[i].landed_x;
        out_updates[i].landed_y = updates[i].landed_y;
        out_updates[i].landed_z = updates[i].landed_z;
    }

    return count;
}

PYMC_EXPORT void pymc_physics_clear_blocks(void* engine) {
    auto* e = static_cast<pymc::PhysicsEngine*>(engine);
    if (e) {
        e->clear_blocks();
    }
}
