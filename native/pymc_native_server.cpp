// ============================================================
// PyMC - Native Server Process
//
// Long-running C++ process that communicates with Python via
// shared memory IPC. Handles:
//   - Redstone simulation
//   - Light propagation
//   - Physics collision detection
//   - Terrain generation (delegated to existing terrain_gen)
//   - Mob AI (delegated to existing mob_ai)
//
// Protocol (over shared memory ring buffer):
//
//   Command format: [1 byte command type][variable payload]
//   Response format: [4 byte LE status][variable payload]
//
//   Commands:
//     0x01: TICK          - Process one tick for all engines
//     0x02: ADD_REDSTONE  - Add redstone component
//     0x03: REMOVE_REDSTONE - Remove redstone component
//     0x04: SET_POWER     - Set power level
//     0x05: CALC_LIGHT    - Calculate chunk lighting
//     0x06: UPDATE_LIGHT  - Incremental light update
//     0x07: SET_ENTITY    - Add/update physics entity
//     0x08: REMOVE_ENTITY - Remove physics entity
//     0x09: SET_BLOCKS    - Set block data for physics
//     0x0A: TICK_FLUIDS   - Process fluid simulation
//     0x0B: PING          - Keep-alive ping
//     0xFF: SHUTDOWN      - Graceful shutdown
//
// ============================================================

#include "../core/ipc_shm.h"
#include "../redstone/redstone_engine.h"
#include "../lighting/light_engine.h"
#include "../physics/physics_engine.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>
#include <string>
#include <vector>
#include <thread>
#include <chrono>
#include <atomic>

namespace {

// Command types
constexpr uint8_t CMD_TICK = 0x01;
constexpr uint8_t CMD_ADD_REDSTONE = 0x02;
constexpr uint8_t CMD_REMOVE_REDSTONE = 0x03;
constexpr uint8_t CMD_SET_POWER = 0x04;
constexpr uint8_t CMD_CALC_LIGHT = 0x05;
constexpr uint8_t CMD_UPDATE_LIGHT = 0x06;
constexpr uint8_t CMD_SET_ENTITY = 0x07;
constexpr uint8_t CMD_REMOVE_ENTITY = 0x08;
constexpr uint8_t CMD_SET_BLOCKS = 0x09;
constexpr uint8_t CMD_TICK_FLUIDS = 0x0A;
constexpr uint8_t CMD_PING = 0x0B;
constexpr uint8_t CMD_SHUTDOWN = 0xFF;

// Response status
constexpr uint32_t STATUS_OK = 0;
constexpr uint32_t STATUS_ERROR = 1;
constexpr uint32_t STATUS_UNKNOWN_CMD = 2;

// Global shutdown flag
std::atomic<bool> g_running{true};

void signal_handler(int sig) {
    g_running = false;
}

// Read a little-endian uint32 from buffer
uint32_t read_u32_le(const uint8_t* p) {
    return static_cast<uint32_t>(p[0])
         | (static_cast<uint32_t>(p[1]) << 8)
         | (static_cast<uint32_t>(p[2]) << 16)
         | (static_cast<uint32_t>(p[3]) << 24);
}

// Read a little-endian int32 from buffer
int32_t read_i32_le(const uint8_t* p) {
    return static_cast<int32_t>(read_u32_le(p));
}

// Read a little-endian float64 from buffer
double read_f64_le(const uint8_t* p) {
    double val;
    std::memcpy(&val, p, 8);
    return val;
}

// Read a little-endian uint16 from buffer
uint16_t read_u16_le(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}

// Write a little-endian uint32 to buffer
void write_u32_le(uint8_t* p, uint32_t v) {
    p[0] = v & 0xFF;
    p[1] = (v >> 8) & 0xFF;
    p[2] = (v >> 16) & 0xFF;
    p[3] = (v >> 24) & 0xFF;
}

// Write a little-endian int32 to buffer
void write_i32_le(uint8_t* p, int32_t v) {
    write_u32_le(p, static_cast<uint32_t>(v));
}

// Write a little-endian float64 to buffer
void write_f64_le(uint8_t* p, double v) {
    std::memcpy(p, &v, 8);
}

// Write a little-endian uint16 to buffer
void write_u16_le(uint8_t* p, uint16_t v) {
    p[0] = v & 0xFF;
    p[1] = (v >> 8) & 0xFF;
}

// Append to response vector
template<typename T>
void append_le(std::vector<uint8_t>& out, T val) {
    size_t old_size = out.size();
    out.resize(old_size + sizeof(T));
    if constexpr (sizeof(T) == 1) {
        out[old_size] = static_cast<uint8_t>(val);
    } else if constexpr (sizeof(T) == 2) {
        write_u16_le(&out[old_size], static_cast<uint16_t>(val));
    } else if constexpr (sizeof(T) == 4) {
        if constexpr (std::is_integral_v<T>) {
            write_i32_le(&out[old_size], static_cast<int32_t>(val));
        } else {
            std::memcpy(&out[old_size], &val, 4);
        }
    } else if constexpr (sizeof(T) == 8) {
        write_f64_le(&out[old_size], static_cast<double>(val));
    }
}

} // anonymous namespace

int main(int argc, char* argv[]) {
    // Parse arguments
    const char* shm_name = "/pymc_native";
    size_t cmd_size = 16 * 1024 * 1024;    // 16 MB command buffer
    size_t resp_size = 16 * 1024 * 1024;   // 16 MB response buffer

    for (int i = 1; i < argc; i++) {
        if (std::string(argv[i]) == "--name" && i + 1 < argc) {
            shm_name = argv[++i];
        } else if (std::string(argv[i]) == "--cmd-size" && i + 1 < argc) {
            cmd_size = std::stoul(argv[++i]);
        } else if (std::string(argv[i]) == "--resp-size" && i + 1 < argc) {
            resp_size = std::stoul(argv[++i]);
        }
    }

    // Install signal handlers
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    fprintf(stderr, "[PYMC Native] Starting with SHM name: %s\n", shm_name);
    fprintf(stderr, "[PYMC Native] Command buffer: %zu MB, Response buffer: %zu MB\n",
            cmd_size / (1024*1024), resp_size / (1024*1024));

    // Open IPC channel (C++ is the consumer: create=false)
    pymc::IPCChannel channel(shm_name, cmd_size, resp_size, false);
    if (!channel.is_valid()) {
        fprintf(stderr, "[PYMC Native] Failed to open IPC channel\n");
        return 1;
    }

    fprintf(stderr, "[PYMC Native] IPC channel opened successfully\n");

    // Initialize engines
    pymc::RedstoneEngine redstone;
    pymc::LightEngine lighting;
    pymc::PhysicsEngine physics;

    fprintf(stderr, "[PYMC Native] All engines initialized, entering main loop\n");

    // Main command loop
    uint8_t cmd_buffer[256 * 1024];  // 256 KB for individual commands
    std::vector<uint8_t> response;

    while (g_running) {
        // Wait for a command with 100ms timeout
        if (!channel.wait_for_command(100)) {
            continue;  // Timeout, check g_running
        }

        // Read the command
        size_t cmd_len = channel.recv_command(cmd_buffer, sizeof(cmd_buffer));
        if (cmd_len == 0) {
            continue;
        }

        const uint8_t* cmd = cmd_buffer;
        uint8_t cmd_type = cmd[0];
        const uint8_t* payload = cmd + 1;
        size_t payload_len = cmd_len - 1;

        response.clear();
        // Reserve space for status
        response.resize(4);

        switch (cmd_type) {
        case CMD_PING: {
            write_u32_le(response.data(), STATUS_OK);
            append_le<uint8_t>(response, 1);  // pong = 1
            break;
        }

        case CMD_SHUTDOWN: {
            write_u32_le(response.data(), STATUS_OK);
            channel.send_response(response.data(), response.size());
            g_running = false;
            continue;
        }

        case CMD_TICK: {
            // Process one tick for all engines

            // Redstone tick
            auto redstone_updates = redstone.tick();

            // Physics tick
            auto physics_updates = physics.tick();

            // Build response
            write_u32_le(response.data(), STATUS_OK);

            // Redstone updates
            append_le<uint32_t>(response, static_cast<uint32_t>(redstone_updates.size()));
            for (const auto& upd : redstone_updates) {
                append_le<int32_t>(response, upd.x);
                append_le<int32_t>(response, upd.y);
                append_le<int32_t>(response, upd.z);
                append_le<int32_t>(response, upd.new_block_state);
                append_le<int32_t>(response, upd.flags);
            }

            // Physics updates
            append_le<uint32_t>(response, static_cast<uint32_t>(physics_updates.size()));
            for (const auto& upd : physics_updates) {
                append_le<int32_t>(response, upd.entity_id);
                append_le<double>(response, upd.new_x);
                append_le<double>(response, upd.new_y);
                append_le<double>(response, upd.new_z);
                append_le<double>(response, upd.new_vx);
                append_le<double>(response, upd.new_vy);
                append_le<double>(response, upd.new_vz);
                append_le<uint8_t>(response, upd.on_ground ? 1 : 0);
                append_le<uint8_t>(response, upd.landed ? 1 : 0);
                if (upd.landed) {
                    append_le<uint16_t>(response, upd.landed_block_state);
                    append_le<int32_t>(response, upd.landed_x);
                    append_le<int32_t>(response, upd.landed_y);
                    append_le<int32_t>(response, upd.landed_z);
                }
            }

            break;
        }

        case CMD_ADD_REDSTONE: {
            // Payload: [4 x][4 y][4 z][1 type][1 facing]
            if (payload_len < 10) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            int32_t x = read_i32_le(payload);
            int32_t y = read_i32_le(payload + 4);
            int32_t z = read_i32_le(payload + 8);
            auto type = static_cast<pymc::ComponentType>(payload[12]);
            auto facing = static_cast<pymc::Facing>(payload[13]);

            redstone.add_component(x, y, z, type, facing);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_REMOVE_REDSTONE: {
            if (payload_len < 12) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            int32_t x = read_i32_le(payload);
            int32_t y = read_i32_le(payload + 4);
            int32_t z = read_i32_le(payload + 8);

            redstone.remove_component(x, y, z);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_SET_POWER: {
            if (payload_len < 16) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            int32_t x = read_i32_le(payload);
            int32_t y = read_i32_le(payload + 4);
            int32_t z = read_i32_le(payload + 8);
            int32_t level = read_i32_le(payload + 12);

            redstone.set_power_level(x, y, z, level);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_CALC_LIGHT: {
            // Payload: flat block array (98304 * 2 = 196608 bytes)
            constexpr size_t expected_size = pymc::LIGHT_CHUNK_SECTIONS * 16 * 16 * 16 * 2;
            if (payload_len < expected_size) {
                write_u32_le(response.data(), STATUS_ERROR);
                append_le<uint32_t>(response, static_cast<uint32_t>(payload_len));
                append_le<uint32_t>(response, static_cast<uint32_t>(expected_size));
                break;
            }

            // Convert to uint16 array
            std::vector<uint16_t> blocks(pymc::LIGHT_CHUNK_SECTIONS * 16 * 16 * 16);
            for (size_t i = 0; i < blocks.size(); i++) {
                blocks[i] = read_u16_le(payload + i * 2);
            }

            std::vector<uint8_t> sky_light(pymc::LIGHT_SECTION_COUNT * 4096);
            std::vector<uint8_t> block_light(pymc::LIGHT_SECTION_COUNT * 4096);

            lighting.calculate_chunk_lighting(
                blocks.data(),
                sky_light.data(),
                block_light.data()
            );

            write_u32_le(response.data(), STATUS_OK);
            // Append sky light data
            response.insert(response.end(), sky_light.begin(), sky_light.end());
            // Append block light data
            response.insert(response.end(), block_light.begin(), block_light.end());
            break;
        }

        case CMD_UPDATE_LIGHT: {
            if (payload_len < 14) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            int32_t x = read_i32_le(payload);
            int32_t y = read_i32_le(payload + 4);
            int32_t z = read_i32_le(payload + 8);
            uint16_t old_block = read_u16_le(payload + 12);
            uint16_t new_block = read_u16_le(payload + 14);

            auto updates = lighting.update_block_light(x, y, z, old_block, new_block);

            write_u32_le(response.data(), STATUS_OK);
            append_le<uint32_t>(response, static_cast<uint32_t>(updates.size()));
            for (const auto& upd : updates) {
                append_le<int32_t>(response, upd.x);
                append_le<int32_t>(response, upd.y);
                append_le<int32_t>(response, upd.z);
                append_le<uint8_t>(response, upd.new_sky_light);
                append_le<uint8_t>(response, upd.new_block_light);
            }
            break;
        }

        case CMD_SET_ENTITY: {
            // Payload: [4 entity_id][8 x][8 y][8 z][8 vx][8 vy][8 vz]
            //          [8 bb_min_x][8 bb_min_y][8 bb_min_z]
            //          [8 bb_max_x][8 bb_max_y][8 bb_max_z]
            //          [1 on_ground][1 has_gravity][1 is_item][1 is_falling_block]
            //          [2 block_state]
            constexpr size_t expected = 4 + 6*8 + 6*8 + 4 + 2;
            if (payload_len < expected) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }

            pymc::PhysicsEntity entity;
            entity.entity_id = read_i32_le(payload);
            entity.x = read_f64_le(payload + 4);
            entity.y = read_f64_le(payload + 12);
            entity.z = read_f64_le(payload + 20);
            entity.vx = read_f64_le(payload + 28);
            entity.vy = read_f64_le(payload + 36);
            entity.vz = read_f64_le(payload + 44);
            entity.bounding_box.min_x = read_f64_le(payload + 52);
            entity.bounding_box.min_y = read_f64_le(payload + 60);
            entity.bounding_box.min_z = read_f64_le(payload + 68);
            entity.bounding_box.max_x = read_f64_le(payload + 76);
            entity.bounding_box.max_y = read_f64_le(payload + 84);
            entity.bounding_box.max_z = read_f64_le(payload + 92);
            entity.on_ground = payload[100] != 0;
            entity.has_gravity = payload[101] != 0;
            entity.is_item = payload[102] != 0;
            entity.is_falling_block = payload[103] != 0;
            entity.block_state = read_u16_le(payload + 104);

            physics.set_entity(entity);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_REMOVE_ENTITY: {
            if (payload_len < 4) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            int32_t entity_id = read_i32_le(payload);
            physics.remove_entity(entity_id);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_SET_BLOCKS: {
            // Payload: [4 count][count * (4 x + 4 y + 4 z + 2 block_state)]
            if (payload_len < 4) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }
            uint32_t count = read_u32_le(payload);
            size_t expected = 4 + count * 14;
            if (payload_len < expected) {
                write_u32_le(response.data(), STATUS_ERROR);
                break;
            }

            std::vector<pymc::BlockData> blocks(count);
            const uint8_t* p = payload + 4;
            for (uint32_t i = 0; i < count; i++) {
                blocks[i].x = read_i32_le(p);
                blocks[i].y = read_i32_le(p + 4);
                blocks[i].z = read_i32_le(p + 8);
                blocks[i].block_state = read_u16_le(p + 12);
                p += 14;
            }

            physics.set_blocks(blocks);
            write_u32_le(response.data(), STATUS_OK);
            break;
        }

        case CMD_TICK_FLUIDS: {
            auto fluid_updates = physics.tick_fluids();

            write_u32_le(response.data(), STATUS_OK);
            append_le<uint32_t>(response, static_cast<uint32_t>(fluid_updates.size()));
            for (const auto& upd : fluid_updates) {
                append_le<int32_t>(response, upd.x);
                append_le<int32_t>(response, upd.y);
                append_le<int32_t>(response, upd.z);
                append_le<uint16_t>(response, upd.new_block_state);
                append_le<int8_t>(response, upd.new_fluid_level);
            }
            break;
        }

        default: {
            write_u32_le(response.data(), STATUS_UNKNOWN_CMD);
            append_le<uint8_t>(response, cmd_type);
            break;
        }
        }

        // Send response
        if (!channel.send_response(response.data(), response.size())) {
            fprintf(stderr, "[PYMC Native] Failed to send response\n");
            // If the response buffer is full, the Python side is probably stuck
            // We'll continue trying
        }
    }

    fprintf(stderr, "[PYMC Native] Shutting down gracefully\n");
    return 0;
}
