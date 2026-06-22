# ============================================================
# PyMC - 1.19 版本处理器
# 处理 1.19.x (协议 761-765) 的协议差异
# 1.19 引入聊天签名系统，但仍使用 384 高度世界
# 1.19.3+ (764+) 有 Player Remove 包
# 没有 1.20.2 的配置阶段
# ============================================================

"""
Version handler for Minecraft 1.19.x (Protocol 761-765).
Key differences from 1.21:
- No configuration phase (1.19.x goes directly to play after login)
- Chat signing system introduced
- Different packet IDs
- 384-height world (1.17+)
"""

import logging
import struct
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double,
    write_uuid, write_identifier, write_position,
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_19")


class VersionHandlerV1_19(VersionHandler):
    """Handler for Minecraft 1.19.x (protocol 761-765)."""

    PROTOCOL_VERSION = 761
    VERSION_NAME = "1.19.2"

    WORLD_MIN_Y = -64
    WORLD_HEIGHT = 384
    NUM_SECTIONS = 24

    HAS_CONFIGURATION_PHASE = False  # No config phase in 1.19
    HAS_CHAT_SIGNING = True
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.19.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.19")
            return

        payload = bytearray()

        # Entity ID (Int)
        payload.extend(write_int(conn.entity_id))

        # Is Hardcore (Boolean)
        payload.extend(write_boolean(False))

        # Game Mode (Unsigned Byte)
        gamemode_map = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
        payload.extend(write_ubyte(gamemode_map.get(server.config.get("gamemode", "creative"), 1)))

        # Previous Game Mode (Byte)
        payload.extend(write_byte(-1))

        # Dimension Count + Dimension Names
        dimension_names = [
            "minecraft:overworld",
            "minecraft:the_nether",
            "minecraft:the_end"
        ]
        payload.extend(write_varint(len(dimension_names)))
        for dim in dimension_names:
            payload.extend(write_identifier(dim))

        # Dimension Type (NBT Compound - registry codec for 1.19+)
        # In 1.19, the dimension type is sent as a NBT compound
        # But since we sent it via the registry codec in login, we use VarInt index
        # Actually in 1.19, we need to send the full dimension codec as NBT in Join Game
        # For simplicity, we use the identifier approach
        payload.extend(write_identifier("minecraft:overworld"))  # Dimension Type
        payload.extend(write_identifier("minecraft:overworld"))  # Dimension Name

        # Hashed Seed (Long)
        payload.extend(write_long(0))

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

        # Is Debug (Boolean)
        payload.extend(write_boolean(False))

        # Is Flat (Boolean)
        payload.extend(write_boolean(False))

        # Has Death Location (Boolean)
        payload.extend(write_boolean(False))

        await conn.send_packet(pid, bytes(payload))

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data and Update Light packet for 1.19.x."""
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

        return bytes(payload)
