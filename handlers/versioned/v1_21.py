# ============================================================
# PyMC - 1.21 版本处理器
# 处理 1.21.1 (协议 767) 和 1.21.4 (协议 770) 的协议差异
# ============================================================

"""
Version handler for Minecraft 1.21+ (Protocol 767, 770).
This is the native version and wraps the existing 1.21.1 implementation.
"""

import logging
import struct
import math
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double, write_short,
    write_uuid, write_identifier, write_position, write_angle,
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_21")


class VersionHandlerV1_21(VersionHandler):
    """Handler for Minecraft 1.21+ (protocol 767/770)."""

    PROTOCOL_VERSION = 767
    VERSION_NAME = "1.21.1"

    WORLD_MIN_Y = -64
    WORLD_HEIGHT = 384
    NUM_SECTIONS = 24

    HAS_CONFIGURATION_PHASE = True
    HAS_CHAT_SIGNING = True
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    async def send_join_game(self, conn, server):
        """Send Join Game packet (0x2B in 1.21.1)."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Is Hardcore (Boolean)
        payload.extend(write_boolean(False))

        # Dimension Count + Dimension Names
        dimension_names = [
            "minecraft:overworld",
            "minecraft:the_nether",
            "minecraft:the_end"
        ]
        payload.extend(write_varint(len(dimension_names)))
        for dim in dimension_names:
            payload.extend(write_identifier(dim))

        # Max Players (VarInt)
        payload.extend(write_varint(server.max_players))

        # View Distance (VarInt)
        payload.extend(write_varint(server.view_distance))

        # Simulation Distance (VarInt)
        payload.extend(write_varint(server.view_distance))

        # Reduced Debug Info (Boolean)
        payload.extend(write_boolean(False))

        # Enable Respawn Screen (Boolean)
        payload.extend(write_boolean(True))

        # Do Limited Crafting (Boolean)
        payload.extend(write_boolean(False))

        # Dimension Type (VarInt - registry index)
        payload.extend(write_varint(0))  # 0 = overworld

        # Dimension Name (Identifier)
        payload.extend(write_identifier("minecraft:overworld"))

        # Hashed Seed (Long)
        payload.extend(write_long(0))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Previous Game Mode (Byte)
        payload.extend(write_byte(-1))

        # Is Debug (Boolean)
        payload.extend(write_boolean(False))

        # Is Flat (Boolean)
        payload.extend(write_boolean(False))

        # Has Death Location (Boolean)
        payload.extend(write_boolean(False))

        # Portal Cooldown (VarInt)
        payload.extend(write_varint(0))

        # Enforces Secure Chat (Boolean)
        payload.extend(write_boolean(False))

        await conn.send_packet(pid, bytes(payload))

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data and Update Light packet for 1.21+."""
        payload = bytearray()

        # Chunk X, Z (Int)
        payload.extend(write_int(chunk_x))
        payload.extend(write_int(chunk_z))

        # Heightmaps (NBT)
        payload.extend(self.build_heightmap_nbt(heightmap_longs, heightmap_longs))

        # Chunk Data
        payload.extend(write_varint(len(chunk_data)))
        payload.extend(chunk_data)

        # Block Entities (VarInt count = 0)
        payload.extend(write_varint(0))

        # Light data
        if sky_light_arrays is not None and block_light_arrays is not None:
            self._write_light_data(payload, chunk_blocks, sky_light_arrays, block_light_arrays)
        else:
            self._write_full_bright_light(payload)

        return bytes(payload)

    def _write_full_bright_light(self, payload):
        """Write fully-bright light data (simplified, all sky light = 0xFF)."""
        all_bits = (1 << 26) - 1
        payload.extend(write_varint(1))
        payload.extend(write_long(all_bits))
        payload.extend(write_varint(1))
        payload.extend(write_long(all_bits))
        payload.extend(write_varint(0))
        payload.extend(write_varint(0))

        sky_light_section = bytes([0xFF] * 2048)
        light_section_count = 26
        payload.extend(write_varint(light_section_count))
        for _ in range(light_section_count):
            payload.extend(write_varint(2048))
            payload.extend(sky_light_section)

        block_light_section = bytes([0x00] * 2048)
        payload.extend(write_varint(light_section_count))
        for _ in range(light_section_count):
            payload.extend(write_varint(2048))
            payload.extend(block_light_section)

    def _write_light_data(self, payload, chunk_blocks, sky_arrays, block_arrays):
        """Write computed light data to the payload."""
        from handlers.play import _build_chunk_light_data

        if chunk_blocks is not None:
            sky_mask, block_mask, empty_sky_mask, empty_block_mask, sky_arrays, block_arrays = (
                _build_chunk_light_data(chunk_blocks)
            )
            payload.extend(write_varint(1))
            payload.extend(write_long(sky_mask))
            payload.extend(write_varint(1))
            payload.extend(write_long(block_mask))
            payload.extend(write_varint(1))
            payload.extend(write_long(empty_sky_mask))
            payload.extend(write_varint(1))
            payload.extend(write_long(empty_block_mask))

            payload.extend(write_varint(len(sky_arrays)))
            for arr in sky_arrays:
                payload.extend(write_varint(2048))
                payload.extend(arr)

            payload.extend(write_varint(len(block_arrays)))
            for arr in block_arrays:
                payload.extend(write_varint(2048))
                payload.extend(arr)
        else:
            self._write_full_bright_light(payload)
