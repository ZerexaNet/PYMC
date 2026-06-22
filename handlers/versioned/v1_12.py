# ============================================================
# PyMC - 1.12 版本处理器
# 处理 1.12.x (协议 340) 的协议差异
# ============================================================

"""
Version handler for Minecraft 1.12.x (Protocol 340).
Key differences from 1.21:
- No configuration phase
- 256-height world (16 sections)
- Pre-flattening: uses numeric block IDs instead of namespaced IDs
- Different chunk format (old format without separate biome palette)
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
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_12")


class VersionHandlerV1_12(VersionHandler):
    """Handler for Minecraft 1.12.x (protocol 340)."""

    PROTOCOL_VERSION = 340
    VERSION_NAME = "1.12.2"

    WORLD_MIN_Y = 0
    WORLD_HEIGHT = 256
    NUM_SECTIONS = 16

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = False  # Pre-flattening!
    HAS_DIMENSION_REGISTRY = False

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.12.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.12")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Dimension (Int) - 0=overworld, -1=nether, 1=end
        payload.extend(write_int(0))

        # Difficulty (Unsigned Byte)
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
        Build chunk data for 1.12 (pre-flattening, 256 height).
        Pre-flattening format: block IDs are stored as 13-bit (block_id << 4 | data) per entry.
        """
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
                sections_data.append(self._build_section_pre_flattening(section_blocks))
            else:
                sections_data.append(None)

        result.extend(write_varint(section_mask))

        for data in sections_data:
            if data is not None:
                result.extend(data)

        # Biomes (256-byte array)
        biome_byte = biome_plains & 0xFF
        result.extend(bytes([biome_byte] * 256))

        return bytes(result)

    def _build_section_pre_flattening(self, section_blocks):
        """
        Build a chunk section in pre-flattening format.
        Uses 13-bit per block: (block_id << 4 | data_value).
        In pre-flattening, block state IDs map to (id << 4 | data).
        We approximate by using state_id >> 4 for the block ID
        and state_id & 0xF for the data value.
        """
        # Pack 4096 blocks into 13-bit entries in a Long array
        # 4096 * 13 bits = 53248 bits = 832 longs
        bits_per_entry = 13
        entries_per_long = 64 // bits_per_entry  # 4
        num_longs = math.ceil(4096 / entries_per_long)  # 1024

        entries = []
        for y in range(16):
            for z in range(16):
                for x in range(16):
                    # Convert flattened state ID to old (id, data) format
                    state_id = section_blocks[y][z][x]
                    # Best effort: use state_id directly as it encodes old format
                    entries.append(state_id & 0x1FFF)  # 13-bit mask

        # Build long array
        long_array = bytearray()
        entry_mask = (1 << bits_per_entry) - 1
        for long_index in range(num_longs):
            long_val = 0
            for i in range(entries_per_long):
                entry_index = long_index * entries_per_long + i
                if entry_index < len(entries):
                    value = entries[entry_index] & entry_mask
                    long_val |= value << (i * bits_per_entry)
            if long_val >= (1 << 63):
                long_val -= (1 << 64)
            long_array.extend(struct.pack('>q', long_val))

        result = bytearray()
        # Bits per block (Byte)
        result.append(bits_per_entry)
        # Palette (VarInt size + entries) - no palette for direct encoding
        # With bits_per_entry=13, we use direct encoding (no palette)
        # Block light (2048 bytes = half-nibble array)
        # We skip block light in the section data, it's sent separately
        # Actually in 1.12, the section data includes blocks + block_light + sky_light

        # Block data array (VarInt length + Long array)
        result.extend(write_varint(num_longs))
        result.extend(long_array)

        # Block Light (2048 bytes, nibble array)
        result.extend(bytes([0x00] * 2048))

        # Sky Light (2048 bytes, nibble array) - only in overworld
        result.extend(bytes([0xFF] * 2048))

        return bytes(result)

    def build_heightmap_for_version(self, chunk_blocks):
        """1.12 doesn't use heightmaps in chunk data."""
        return []

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data packet for 1.12.x."""
        payload = bytearray()

        payload.extend(write_int(chunk_x))
        payload.extend(write_int(chunk_z))
        payload.extend(write_boolean(True))  # Full chunk

        # Chunk data (includes bitmask, sections, biomes)
        payload.extend(chunk_data)

        # Block Entities
        payload.extend(write_varint(0))

        return bytes(payload)

    def build_heightmap_nbt(self, motion_blocking, world_surface):
        """1.12 doesn't use heightmaps in chunk data."""
        return b''
