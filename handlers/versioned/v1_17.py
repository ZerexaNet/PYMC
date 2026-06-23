# ============================================================
# PyMC - 1.17 版本处理器
# 处理 1.17.1 (协议 757) 和 1.18.2 (协议 758) 的协议差异
# 1.17 引入了 384 高度世界
# ============================================================

"""
Version handler for Minecraft 1.17.1/1.18.2 (Protocol 757/758).
Key differences from 1.21:
- No configuration phase
- Different Join Game packet format
- 384-height world (same as native, so chunk format is compatible)
- No chat signing
- Different packet IDs
"""

import logging
import struct
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double,
    write_uuid, write_identifier, write_position,
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray, NbtByte, NbtDouble, NbtFloat
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_17")


class VersionHandlerV1_17(VersionHandler):
    """Handler for Minecraft 1.17/1.18 (protocol 757/758)."""

    PROTOCOL_VERSION = 757
    VERSION_NAME = "1.17.1"

    WORLD_MIN_Y = -64
    WORLD_HEIGHT = 384
    NUM_SECTIONS = 24

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.17/1.18."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.17")
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

        # NBT: Dimension Codec (for 1.17+, this is sent in Join Game)
        # We send a minimal dimension codec
        payload.extend(encode_nbt(self._build_dimension_codec(), with_type=True))

        # NBT: Dimension Type (the current dimension)
        payload.extend(encode_nbt(self._build_overworld_dimension(), with_type=True))

        # Dimension Name (Identifier)
        payload.extend(write_identifier("minecraft:overworld"))

        # Hashed Seed (Long)
        payload.extend(write_long(0))

        # Max Players (VarInt)
        payload.extend(write_varint(server.max_players))

        # View Distance (VarInt)
        payload.extend(write_varint(server.view_distance))

        # Simulation Distance (VarInt) - 1.18+
        if conn.protocol_version >= 758:
            payload.extend(write_varint(server.view_distance))

        # Reduced Debug Info (Boolean)
        payload.extend(write_boolean(False))

        # Enable Respawn Screen (Boolean)
        payload.extend(write_boolean(True))

        # Is Debug (Boolean)
        payload.extend(write_boolean(False))

        # Is Flat (Boolean)
        payload.extend(write_boolean(False))

        await conn.send_packet(pid, bytes(payload))

    def _build_dimension_codec(self) -> dict:
        """Build a minimal dimension type registry codec for 1.17."""
        return {
            "minecraft:dimension_type": {
                "type": "minecraft:dimension_type",
                "value": [
                    {
                        "name": "minecraft:overworld",
                        "id": 0,
                        "element": {
                            "has_skylight": NbtByte(1),
                            "has_ceiling": NbtByte(0),
                            "ultrawarm": NbtByte(0),
                            "natural": NbtByte(1),
                            "coordinate_scale": NbtDouble(1.0),
                            "bed_works": NbtByte(1),
                            "respawn_anchor_works": NbtByte(0),
                            "min_y": NbtByte(0),
                            "height": 384,
                            "logical_height": 384,
                            "infiniburn": "minecraft:infiniburn_overworld",
                            "effects": "minecraft:overworld",
                            "ambient_light": NbtFloat(0.0),
                            "piglin_safe": NbtByte(0),
                            "has_raids": NbtByte(1),
                            "monster_spawn_light_level": 0,
                            "monster_spawn_block_light_limit": 0,
                        },
                    },
                    {
                        "name": "minecraft:the_nether",
                        "id": 1,
                        "element": {
                            "has_skylight": NbtByte(0),
                            "has_ceiling": NbtByte(1),
                            "ultrawarm": NbtByte(1),
                            "natural": NbtByte(0),
                            "coordinate_scale": NbtDouble(8.0),
                            "bed_works": NbtByte(0),
                            "respawn_anchor_works": NbtByte(1),
                            "min_y": NbtByte(0),
                            "height": 256,
                            "logical_height": 128,
                            "infiniburn": "minecraft:infiniburn_nether",
                            "effects": "minecraft:the_nether",
                            "ambient_light": NbtFloat(0.1),
                            "piglin_safe": NbtByte(1),
                            "has_raids": NbtByte(0),
                            "monster_spawn_light_level": 7,
                            "monster_spawn_block_light_limit": 15,
                            "fixed_time": NbtLong(18000),
                        },
                    },
                    {
                        "name": "minecraft:the_end",
                        "id": 2,
                        "element": {
                            "has_skylight": NbtByte(0),
                            "has_ceiling": NbtByte(0),
                            "ultrawarm": NbtByte(0),
                            "natural": NbtByte(0),
                            "coordinate_scale": NbtDouble(1.0),
                            "bed_works": NbtByte(0),
                            "respawn_anchor_works": NbtByte(0),
                            "min_y": NbtByte(0),
                            "height": 256,
                            "logical_height": 256,
                            "infiniburn": "minecraft:infiniburn_end",
                            "effects": "minecraft:the_end",
                            "ambient_light": NbtFloat(0.0),
                            "piglin_safe": NbtByte(0),
                            "has_raids": NbtByte(1),
                            "monster_spawn_light_level": 0,
                            "monster_spawn_block_light_limit": 0,
                            "fixed_time": NbtLong(6000),
                        },
                    },
                ],
            },
            "minecraft:worldgen/biome": {
                "type": "minecraft:worldgen/biome",
                "value": [
                    {
                        "name": "minecraft:plains",
                        "id": 0,
                        "element": {
                            "has_precipitation": NbtByte(1),
                            "temperature": NbtFloat(0.8),
                            "downfall": NbtFloat(0.4),
                            "effects": {
                                "sky_color": 7907327,
                                "water_color": 4159204,
                                "water_fog_color": 329011,
                                "fog_color": 12638463,
                            },
                        },
                    },
                ],
            },
        }

    def _build_overworld_dimension(self) -> dict:
        """Build the overworld dimension type NBT for Join Game."""
        return {
            "has_skylight": NbtByte(1),
            "has_ceiling": NbtByte(0),
            "ultrawarm": NbtByte(0),
            "natural": NbtByte(1),
            "coordinate_scale": NbtDouble(1.0),
            "bed_works": NbtByte(1),
            "respawn_anchor_works": NbtByte(0),
            "min_y": NbtByte(0),
            "height": 384,
            "logical_height": 384,
            "infiniburn": "minecraft:infiniburn_overworld",
            "effects": "minecraft:overworld",
            "ambient_light": NbtFloat(0.0),
            "piglin_safe": NbtByte(0),
            "has_raids": NbtByte(1),
            "monster_spawn_light_level": 0,
            "monster_spawn_block_light_limit": 0,
        }

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build Chunk Data and Update Light packet for 1.17/1.18."""
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
