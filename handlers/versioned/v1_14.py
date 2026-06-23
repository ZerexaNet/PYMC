# ============================================================
# PyMC - 1.14 版本处理器
# 处理 1.14.x (协议 498) 和 1.15.x (协议 578) 的协议差异
# ============================================================

"""
Version handler for Minecraft 1.14.x/1.15.x (Protocol 498/578).
Key differences from 1.21:
- No configuration phase
- 256-height world (16 sections)
- Uses flattened block states
- Different packet IDs
- No chat signing
"""

import logging
import struct
import math
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double,
    write_uuid, write_identifier, write_position,
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_14")


class VersionHandlerV1_14(VersionHandler):
    """Handler for Minecraft 1.14.x/1.15.x (protocol 498/578)."""

    PROTOCOL_VERSION = 498
    VERSION_NAME = "1.14.4"

    WORLD_MIN_Y = 0
    WORLD_HEIGHT = 256
    NUM_SECTIONS = 16

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = False

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.14.x/1.15.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.14")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Previous Game Mode (Byte)
        payload.extend(write_byte(-1))

        # Dimension Count + Dimension Names (1.16+ style)
        # 1.14 just uses an Int for dimension
        payload.extend(write_int(0))  # 0 = overworld

        # Hashed Seed (Long)
        payload.extend(write_long(0))

        # Max Players (VarInt)
        payload.extend(write_varint(server.max_players))

        # Level Type (String)
        payload.extend(write_string(server.config.get("level-type", "default")))

        # View Distance (VarInt)
        payload.extend(write_varint(server.view_distance))

        # Reduced Debug Info (Boolean)
        payload.extend(write_boolean(False))

        # Enable Respawn Screen (Boolean)
        payload.extend(write_boolean(True))

        await conn.send_packet(pid, bytes(payload))

    def build_chunk_data_for_version(self, chunk_blocks, chunk_biomes=None):
        """Build chunk data for 1.14 (256 height, 16 sections)."""
        from world.chunk import build_section_from_blocks, encode_paletted_container_single
        from world.blocks import AIR
        from world.biomes import BIOME_NAME_TO_ID

        biome_plains = BIOME_NAME_TO_ID.get("minecraft:plains", 0)
        result = bytearray()

        # Section bitmask
        section_mask = 0
        sections_data = []

        for section_idx in range(16):
            src_idx = section_idx + 4
            if src_idx < len(chunk_blocks):
                section_blocks = chunk_blocks[src_idx * 16:(src_idx + 1) * 16]
            else:
                section_blocks = None

            has_blocks = False
            if section_blocks is not None:
                for y in range(16):
                    for z in range(16):
                        for x in range(16):
                            if section_blocks[y][z][x] != AIR:
                                has_blocks = True
                                break
                        if has_blocks:
                            break
                    if has_blocks:
                        break

            if has_blocks:
                section_mask |= (1 << section_idx)
                biome_section = None
                if chunk_biomes is not None and src_idx < len(chunk_biomes):
                    biome_section = chunk_biomes[src_idx]
                sections_data.append(build_section_from_blocks(section_blocks, biome_section, biome_plains))
            else:
                sections_data.append(None)

        result.extend(write_varint(section_mask))

        for data in sections_data:
            if data is not None:
                result.extend(data)

        # Biomes (4x4x4 per section for 1.15+, or 256 bytes for 1.14)
        if conn_protocol_ge_578():
            # 1.15+ uses 4x4x4 biome sections
            for _ in range(16):
                result.extend(encode_paletted_container_single(biome_plains))
        else:
            # 1.14 uses 256-byte biome array
            result.extend(bytes([biome_plains & 0xFF] * 256))

        return bytes(result)

    def build_heightmap_for_version(self, chunk_blocks):
        """Build heightmap for 1.14 (256 height)."""
        from world.blocks import AIR, WATER
        from world.chunk import MIN_Y

        bits_per_entry = 9
        entries_per_long = 64 // bits_per_entry
        num_longs = math.ceil(256 / entries_per_long)

        heights = [0] * 256
        for z in range(16):
            for x in range(16):
                height = 0
                for yi in range(min(319, len(chunk_blocks) - 1), 63, -1):
                    block = chunk_blocks[yi][z][x]
                    if block != AIR and block != WATER:
                        world_y = yi + MIN_Y
                        height = max(0, world_y)
                        break
                heights[x + z * 16] = height

        longs = []
        for long_index in range(num_longs):
            long_val = 0
            for i in range(entries_per_long):
                entry_index = long_index * entries_per_long + i
                if entry_index < 256:
                    long_val |= (heights[entry_index] & 0x1FF) << (i * bits_per_entry)
            if long_val >= (1 << 63):
                long_val -= (1 << 64)
            longs.append(long_val)

        return longs

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data and Update Light packet for 1.14/1.15."""
        payload = bytearray()

        payload.extend(write_int(chunk_x))
        payload.extend(write_int(chunk_z))

        # Heightmaps (NBT) - 1.14+ has heightmaps
        if heightmap_longs:
            payload.extend(self.build_heightmap_nbt(heightmap_longs, heightmap_longs))

        # Chunk data
        payload.extend(chunk_data)

        # Block Entities
        payload.extend(write_varint(0))

        return bytes(payload)

    def build_heightmap_nbt(self, motion_blocking, world_surface):
        """Build heightmap NBT for 1.14+."""
        heightmap_nbt = {
            "MOTION_BLOCKING": NbtLongArray(motion_blocking),
            "WORLD_SURFACE": NbtLongArray(world_surface),
        }
        return encode_nbt(heightmap_nbt, with_type=True)


def conn_protocol_ge_578():
    """Helper: check if we're dealing with 1.15+ protocol."""
    # This will be called from instance method with actual conn
    return False  # Default, will be overridden by actual check
