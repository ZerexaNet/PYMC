# ============================================================
# PyMC - 1.13 版本处理器
# 处理 1.13.x (协议 404) 的协议差异
# 1.13 引入了扁平化 (Flattening)
# ============================================================

"""
Version handler for Minecraft 1.13.x (Protocol 404).
Key differences from 1.21:
- No configuration phase
- 256-height world (16 sections)
- Flattening introduced (block states are namespaced IDs)
- Different chunk format (still uses palette encoding)
- Old chunk format without separate biome palette (biomes stored differently)
- Different packet IDs
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

logger = logging.getLogger("PyMC.版本.1_13")


class VersionHandlerV1_13(VersionHandler):
    """Handler for Minecraft 1.13.x (protocol 404)."""

    PROTOCOL_VERSION = 404
    VERSION_NAME = "1.13.2"

    WORLD_MIN_Y = 0
    WORLD_HEIGHT = 256
    NUM_SECTIONS = 16

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = True  # 1.13 introduced flattening
    HAS_DIMENSION_REGISTRY = False

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.13.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.13")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Dimension (Int) - 0=overworld, -1=nether, 1=end
        payload.extend(write_int(0))

        # Difficulty (Unsigned Byte) - 0=peaceful, 1=easy, 2=normal, 3=hard
        difficulty_map = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}
        payload.extend(write_ubyte(difficulty_map.get(server.config.get("difficulty", "normal"), 2)))

        # Max Players (Unsigned Byte)
        payload.extend(write_ubyte(min(server.max_players, 255)))

        # Level Type (String)
        payload.extend(write_string(server.config.get("level-type", "default")))

        # View Distance (VarInt)
        payload.extend(write_varint(server.view_distance))

        # Reduced Debug Info (Boolean)
        payload.extend(write_boolean(False))

        await conn.send_packet(pid, bytes(payload))

    def build_chunk_data_for_version(self, chunk_blocks, chunk_biomes=None):
        """
        Build chunk data for 1.13 (256 height, 16 sections).
        1.13 uses the flattened block state IDs with palette encoding.
        Biome data is stored as a 256-byte array at the end of the chunk.
        """
        from world.blocks import AIR
        from world.biomes import BIOME_NAME_TO_ID

        biome_plains = BIOME_NAME_TO_ID.get("minecraft:plains", 0)
        result = bytearray()

        # Section bitmask - determine which sections are non-empty
        section_mask = 0
        sections_data = []

        for section_idx in range(16):
            src_idx = section_idx + 4  # Offset into 384-height world
            if src_idx < len(chunk_blocks):
                section_blocks = chunk_blocks[src_idx * 16:(src_idx + 1) * 16]
            else:
                # Empty section
                section_blocks = None

            # Check if section has any non-air blocks
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
                sections_data.append(self._build_section_1_13(section_blocks, biome_plains))
            else:
                sections_data.append(None)

        # Write section bitmask as VarInt
        result.extend(write_varint(section_mask))

        # Write section data (only non-empty sections)
        for data in sections_data:
            if data is not None:
                result.extend(data)

        # Biomes array (256 bytes, one per column)
        biome_byte = biome_plains & 0xFF  # Clamp to byte
        result.extend(bytes([biome_byte] * 256))

        return bytes(result)

    def _build_section_1_13(self, section_blocks, biome_id):
        """Build a single chunk section for 1.13 format."""
        from world.chunk import encode_paletted_container_indirect, encode_paletted_container_single
        from world.blocks import AIR

        # Build palette for this section
        palette_map = {}
        palette = []
        entries = []
        non_air_count = 0

        for y in range(16):
            for z in range(16):
                for x in range(16):
                    block_id = section_blocks[y][z][x]
                    if block_id != AIR:
                        non_air_count += 1
                    if block_id not in palette_map:
                        palette_map[block_id] = len(palette)
                        palette.append(block_id)
                    entries.append(palette_map[block_id])

        result = bytearray()
        # Block count (Short) - new in 1.13+
        result.extend(struct.pack('>h', non_air_count))

        # Block states (Paletted Container)
        if len(palette) == 1:
            result.extend(encode_paletted_container_single(palette[0]))
        else:
            result.extend(encode_paletted_container_indirect(entries, palette, 4096))

        # No separate biome palette in 1.13 chunk sections - biomes are at chunk level

        return bytes(result)

    def build_heightmap_for_version(self, chunk_blocks):
        """Build heightmap for 1.13 (256 height, min_y=0)."""
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
        """Build Chunk Data packet for 1.13.x (no Update Light yet)."""
        payload = bytearray()

        # Chunk X, Z (Int)
        payload.extend(write_int(chunk_x))
        payload.extend(write_int(chunk_z))

        # Chunk data already includes the bitmask and sections
        payload.extend(chunk_data)

        # Block Entities (VarInt count = 0)
        payload.extend(write_varint(0))

        return bytes(payload)

    def build_heightmap_nbt(self, motion_blocking, world_surface):
        """1.13 doesn't use heightmaps in chunk data."""
        return b''
