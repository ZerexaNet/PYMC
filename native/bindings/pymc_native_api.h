// ============================================================
// PyMC - C API Bridge for Python Bindings
//
// This header defines a C-compatible API that can be called
// from Python via ctypes/cffi. It provides both:
//   1. Direct in-process engine access (loaded as shared lib)
//   2. Shared memory IPC functions for out-of-process communication
//
// The shared library can be used in two modes:
//   A) Direct: Python loads the .so and calls engine functions directly
//   B) IPC: Python starts the native server process and communicates
//      via shared memory ring buffers
// ============================================================

#ifndef PYMC_NATIVE_API_H
#define PYMC_NATIVE_API_H

#include <cstdint>
#include <cstddef>

#ifdef _WIN32
#define PYMC_EXPORT __declspec(dllexport)
#else
#define PYMC_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ===========================================================
// Shared Memory IPC Functions
// ===========================================================

// Create a shared memory IPC channel.
// Returns: opaque handle, or NULL on failure.
//   name: unique name for the SHM objects
//   cmd_size: size of command buffer in bytes
//   resp_size: size of response buffer in bytes
//   create: 1 = creator (Python side), 0 = opener (C++ side)
PYMC_EXPORT void* pymc_ipc_channel_create(const char* name,
                                           uint32_t cmd_size,
                                           uint32_t resp_size,
                                           int create);

// Destroy an IPC channel.
PYMC_EXPORT void pymc_ipc_channel_destroy(void* handle);

// Send a command (Python -> C++).
// Returns: 1 on success, 0 if buffer full.
PYMC_EXPORT int pymc_ipc_send_command(void* handle,
                                       const uint8_t* data,
                                       uint32_t len);

// Receive a response (C++ -> Python).
// Returns: number of bytes read, 0 if empty.
PYMC_EXPORT uint32_t pymc_ipc_recv_response(void* handle,
                                             uint8_t* buffer,
                                             uint32_t max_len);

// Receive a command (C++ side).
// Returns: number of bytes read, 0 if empty.
PYMC_EXPORT uint32_t pymc_ipc_recv_command(void* handle,
                                            uint8_t* buffer,
                                            uint32_t max_len);

// Send a response (C++ side).
// Returns: 1 on success, 0 if buffer full.
PYMC_EXPORT int pymc_ipc_send_response(void* handle,
                                        const uint8_t* data,
                                        uint32_t len);

// Wait for data with timeout.
// Returns: 1 if data available, 0 on timeout.
PYMC_EXPORT int pymc_ipc_wait_for_command(void* handle, int timeout_ms);
PYMC_EXPORT int pymc_ipc_wait_for_response(void* handle, int timeout_ms);

// Check if channel is valid.
PYMC_EXPORT int pymc_ipc_is_valid(void* handle);

// ===========================================================
// Direct Engine Access (In-Process Mode)
// ===========================================================

// --- Redstone Engine ---

// Create/destroy a redstone engine instance.
PYMC_EXPORT void* pymc_redstone_create();
PYMC_EXPORT void pymc_redstone_destroy(void* engine);

// Add a redstone component.
// type: 0=wire, 1=torch, 2=repeater, 3=comparator, 4=piston,
//       5=sticky_piston, 6=observer, 7=lever, 8=button,
//       9=pressure_plate, 10=weighted_pressure_plate,
//       11=tripwire_hook, 12=tripwire, 13=daylight_detector,
//       14=redstone_block, 15=target, 16=lectern
// facing: 0=down, 1=up, 2=north, 3=south, 4=west, 5=east
PYMC_EXPORT void pymc_redstone_add_component(void* engine,
                                              int32_t x, int32_t y, int32_t z,
                                              uint8_t type, uint8_t facing);

// Remove a redstone component.
PYMC_EXPORT void pymc_redstone_remove_component(void* engine,
                                                  int32_t x, int32_t y, int32_t z);

// Set the power level of a component.
PYMC_EXPORT void pymc_redstone_set_power(void* engine,
                                          int32_t x, int32_t y, int32_t z,
                                          int32_t level);

// Get the power level of a component.
PYMC_EXPORT int32_t pymc_redstone_get_power(void* engine,
                                             int32_t x, int32_t y, int32_t z);

// Process one redstone tick.
// out_updates: buffer to receive updates (array of int32_t, 5 per update: x,y,z,new_state,flags)
// max_updates: maximum number of updates to return
// Returns: actual number of updates written.
PYMC_EXPORT uint32_t pymc_redstone_tick(void* engine,
                                         int32_t* out_updates,
                                         uint32_t max_updates);

// Clear all components.
PYMC_EXPORT void pymc_redstone_clear(void* engine);

// --- Light Engine ---

// Create/destroy a light engine instance.
PYMC_EXPORT void* pymc_light_create();
PYMC_EXPORT void pymc_light_destroy(void* engine);

// Calculate lighting for an entire chunk.
// blocks: flat array of 98304 uint16_t (y*256+z*16+x ordering)
// sky_light_out: output, LIGHT_SECTIONS * 4096 bytes
// block_light_out: output, LIGHT_SECTIONS * 4096 bytes
PYMC_EXPORT void pymc_light_calculate_chunk(void* engine,
                                             const uint16_t* blocks,
                                             uint8_t* sky_light_out,
                                             uint8_t* block_light_out);

// Incremental update when a block changes.
// out_updates: buffer for LightUpdate structs (5 int32_t each: x,y,z,sky_light,block_light)
// max_updates: max number of updates
// Returns: actual number of updates.
PYMC_EXPORT uint32_t pymc_light_update_block(void* engine,
                                               int32_t x, int32_t y, int32_t z,
                                               uint16_t old_block, uint16_t new_block,
                                               int32_t* out_updates,
                                               uint32_t max_updates);

// Register custom block light info.
PYMC_EXPORT void pymc_light_set_block_info(void* engine,
                                            uint16_t block_state,
                                            uint8_t sky_type,
                                            uint8_t block_type,
                                            uint8_t emitted_light,
                                            uint8_t filter_level);

// --- Physics Engine ---

// Create/destroy a physics engine instance.
PYMC_EXPORT void* pymc_physics_create();
PYMC_EXPORT void pymc_physics_destroy(void* engine);

// Entity data for set_entity
struct PymcPhysicsEntity {
    int32_t entity_id;
    double x, y, z;
    double vx, vy, vz;
    double bb_min_x, bb_min_y, bb_min_z;
    double bb_max_x, bb_max_y, bb_max_z;
    uint8_t on_ground;
    uint8_t has_gravity;
    uint8_t is_item;
    uint8_t is_falling_block;
    uint16_t block_state;
};

// Physics update result
struct PymcPhysicsUpdate {
    int32_t entity_id;
    double new_x, new_y, new_z;
    double new_vx, new_vy, new_vz;
    uint8_t on_ground;
    uint8_t landed;
    uint16_t landed_block_state;
    int32_t landed_x, landed_y, landed_z;
};

// Set an entity.
PYMC_EXPORT void pymc_physics_set_entity(void* engine,
                                          const struct PymcPhysicsEntity* entity);

// Remove an entity.
PYMC_EXPORT void pymc_physics_remove_entity(void* engine, int32_t entity_id);

// Set block data for collision.
// blocks: array of {int32_t x, int32_t y, int32_t z, uint16_t block_state}
// count: number of entries
PYMC_EXPORT void pymc_physics_set_blocks(void* engine,
                                          const int32_t* xyz_data,
                                          const uint16_t* block_states,
                                          uint32_t count);

// Process one physics tick.
// out_updates: buffer for PymcPhysicsUpdate results
// max_updates: max number of results
// Returns: actual number of updates.
PYMC_EXPORT uint32_t pymc_physics_tick(void* engine,
                                        struct PymcPhysicsUpdate* out_updates,
                                        uint32_t max_updates);

// Clear all block data.
PYMC_EXPORT void pymc_physics_clear_blocks(void* engine);

// ===========================================================
// Version Info
// ===========================================================

PYMC_EXPORT const char* pymc_get_version();
PYMC_EXPORT uint32_t pymc_get_api_version();

#ifdef __cplusplus
}
#endif

#endif  // PYMC_NATIVE_API_H
