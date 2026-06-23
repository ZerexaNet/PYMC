# ============================================================
# PyMC - 1.8 版本处理器
# 处理 1.8.x (协议 47) 的协议差异
# 最古老的受支持版本，与最新版本差异最大
# ============================================================

"""
Version handler for Minecraft 1.8.x (Protocol 47).
Key differences from 1.21:
- No configuration phase
- No teleport confirmation
- 256-height world (16 sections)
- Pre-flattening: numeric block IDs
- Different position encoding
- Old chunk format
- No Set Center Chunk packet
- No view distance sync
- Different chat format
- Old player info format
- No separate Player Remove packet
"""

import logging
import struct
import math
import json
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double,
    write_uuid, write_identifier, write_position, write_short,
)
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_8")


class VersionHandlerV1_8(VersionHandler):
    """Handler for Minecraft 1.8.x (protocol 47)."""

    PROTOCOL_VERSION = 47
    VERSION_NAME = "1.8.9"

    WORLD_MIN_Y = 0
    WORLD_HEIGHT = 256
    NUM_SECTIONS = 16

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = False
    HAS_DIMENSION_REGISTRY = False

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.8.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.8")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Dimension (Byte) - 0=overworld, -1=nether, 1=end
        payload.extend(write_byte(0))

        # Difficulty (Unsigned Byte)
        difficulty_map = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}
        payload.extend(write_ubyte(difficulty_map.get(server.config.get("difficulty", "normal"), 2)))

        # Max Players (Unsigned Byte)
        payload.extend(write_ubyte(min(server.max_players, 255)))

        # Level Type (String)
        payload.extend(write_string(server.config.get("level-type", "default")))

        # Reduced Debug Info (Boolean)
        payload.extend(write_boolean(False))

        await conn.send_packet(pid, bytes(payload))

    async def send_synchronize_position(self, conn):
        """Send Player Position And Look for 1.8 (no teleport ID)."""
        from protocol.data_types import write_double, write_float, write_byte

        pid = self.get_packet_id("player_position")
        if pid is None:
            return

        payload = bytearray()
        payload.extend(write_double(conn.x))
        payload.extend(write_double(conn.y))
        payload.extend(write_double(conn.z))
        payload.extend(write_float(conn.yaw))
        payload.extend(write_float(conn.pitch))
        # Flags (Byte) - all absolute
        payload.extend(write_byte(0))

        # 1.8 does NOT have teleport ID
        await conn.send_packet(pid, bytes(payload))

    async def send_system_chat(self, conn, text, overlay=False):
        """Send chat message for 1.8 (JSON + position byte)."""
        from protocol.data_types import write_string, write_byte

        pid = self.get_packet_id("chat_message")
        if pid is None:
            return

        chat_json = json.dumps({"text": text}, ensure_ascii=False)
        payload = bytearray()
        payload.extend(write_string(chat_json))
        # 0=chat, 1=system, 2=action bar
        payload.extend(write_byte(2 if overlay else 0))
        await conn.send_packet(pid, bytes(payload))

    async def send_set_center_chunk(self, conn, chunk_x, chunk_z):
        """1.8 doesn't have Set Center Chunk - no-op."""
        pass

    async def send_set_chunk_cache_radius(self, conn, view_distance):
        """1.8 doesn't have Set Chunk Cache Radius - no-op."""
        pass

    async def send_remove_entities(self, conn, entity_ids):
        """Send Destroy Entities packet for 1.8."""
        pid = self.get_packet_id("remove_entities")
        if pid is None:
            return

        payload = bytearray()
        payload.extend(write_varint(len(entity_ids)))
        for eid in entity_ids:
            payload.extend(write_int(eid))  # 1.8 uses Int, not VarInt
        await conn.send_packet(pid, bytes(payload))

    async def send_game_event(self, conn, event, value):
        """Send Game State Change for 1.8."""
        from protocol.data_types import write_ubyte, write_float
        pid = self.get_packet_id("game_event")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_ubyte(event))
            payload.extend(write_float(value))
            await conn.send_packet(pid, bytes(payload))

    def build_chunk_data_for_version(self, chunk_blocks, chunk_biomes=None):
        """
        Build chunk data for 1.8 (pre-flattening, 256 height).
        Uses the same approach as 1.12: 13-bit block IDs, section bitmask.
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
                sections_data.append(self._build_section_1_8(section_blocks))
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

    def _build_section_1_8(self, section_blocks):
        """
        Build a chunk section for 1.8.
        Format: block data (4096 * 13 bits packed) + block light + sky light
        """
        bits_per_entry = 13
        entries_per_long = 64 // bits_per_entry  # 4
        num_longs = math.ceil(4096 / entries_per_long)  # 1024

        entries = []
        for y in range(16):
            for z in range(16):
                for x in range(16):
                    state_id = section_blocks[y][z][x]
                    entries.append(state_id & 0x1FFF)

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
        result.append(bits_per_entry)

        # Block data array
        result.extend(write_varint(num_longs))
        result.extend(long_array)

        # Block Light
        result.extend(bytes([0x00] * 2048))

        # Sky Light
        result.extend(bytes([0xFF] * 2048))

        return bytes(result)

    def build_heightmap_for_version(self, chunk_blocks):
        """1.8 doesn't use heightmaps in chunk data."""
        return []

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data packet for 1.8.x."""
        payload = bytearray()

        payload.extend(write_int(chunk_x))
        payload.extend(write_int(chunk_z))
        payload.extend(write_boolean(True))  # Full chunk

        payload.extend(chunk_data)

        # Block Entities
        payload.extend(write_varint(0))

        return bytes(payload)

    def build_heightmap_nbt(self, motion_blocking, world_surface):
        """1.8 doesn't use heightmaps."""
        return b''
