# ============================================================
# PyMC - 1.16 版本处理器
# 处理 1.16.x (协议 736/754) 的协议差异
# 1.16 引入下界维度更新，使用 256 高度世界
# ============================================================

"""
Version handler for Minecraft 1.16.x (Protocol 736/754).
Key differences from 1.21:
- No configuration phase
- 256-height world (16 sections)
- Dimension codec sent in Join Game
- No chat signing
- Different packet IDs
"""

import logging
import struct
import math
from protocol.data_types import (
    write_varint, write_string, write_boolean, write_int, write_long,
    write_byte, write_ubyte, write_float, write_double,
    write_uuid, write_identifier, write_position, write_short,
)
from protocol.nbt import encode_nbt, NbtLong, NbtLongArray, NbtByte, NbtDouble, NbtFloat
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_16")


class VersionHandlerV1_16(VersionHandler):
    """Handler for Minecraft 1.16.x (protocol 736/754)."""

    PROTOCOL_VERSION = 736
    VERSION_NAME = "1.16.1"

    WORLD_MIN_Y = 0
    WORLD_HEIGHT = 256
    NUM_SECTIONS = 16

    HAS_CONFIGURATION_PHASE = False
    HAS_CHAT_SIGNING = False
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.16.x."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.16")
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

        # NBT: Dimension Codec
        payload.extend(encode_nbt(self._build_dimension_codec_1_16(), with_type=True))

        # NBT: Dimension Type
        payload.extend(encode_nbt(self._build_overworld_dimension_1_16(), with_type=True))

        # Dimension Name (Identifier)
        payload.extend(write_identifier("minecraft:overworld"))

        # Hashed Seed (Long)
        payload.extend(write_long(0))

        # Max Players (VarInt)
        payload.extend(write_varint(server.max_players))

        # View Distance (VarInt)
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

    def _build_dimension_codec_1_16(self) -> dict:
        """Build dimension codec for 1.16."""
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
                            "height": 256,
                            "logical_height": 256,
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

    def _build_overworld_dimension_1_16(self) -> dict:
        """Build overworld dimension NBT for 1.16 Join Game."""
        return {
            "has_skylight": NbtByte(1),
            "has_ceiling": NbtByte(0),
            "ultrawarm": NbtByte(0),
            "natural": NbtByte(1),
            "coordinate_scale": NbtDouble(1.0),
            "bed_works": NbtByte(1),
            "respawn_anchor_works": NbtByte(0),
            "min_y": NbtByte(0),
            "height": 256,
            "logical_height": 256,
            "infiniburn": "minecraft:infiniburn_overworld",
            "effects": "minecraft:overworld",
            "ambient_light": NbtFloat(0.0),
            "piglin_safe": NbtByte(0),
            "has_raids": NbtByte(1),
            "monster_spawn_light_level": 0,
            "monster_spawn_block_light_limit": 0,
        }

    def build_chunk_data_for_version(self, chunk_blocks, chunk_biomes=None):
        """
        Build chunk column data for 1.16 (256 height = 16 sections).
        We need to compress 384-height world data into 16 sections.
        Only use sections 4-19 (y=64 to y=319 in the 384 world = y_index 128 to 383)
        Actually: the 384-height world has y_index 0 = y=-64.
        For 256-height: we skip the first 4 sections (y=-64 to y=-1) and use sections 4-19.
        """
        return self._compress_384_to_256(chunk_blocks, chunk_biomes)

    def _compress_384_to_256(self, chunk_blocks, chunk_biomes=None):
        """
        Compress 384-height chunk data into 16 sections for pre-1.17 clients.
        Strategy: Skip the bottom 4 sections (y=-64 to y=-1), keep the rest.
        If there are blocks below y=0, they will be lost (client won't see them).
        """
        from world.chunk import build_section_from_blocks, encode_paletted_container_single
        from world.blocks import AIR
        from world.biomes import BIOME_NAME_TO_ID

        biome_plains = BIOME_NAME_TO_ID.get("minecraft:plains", 0)
        result = bytearray()

        # We have 24 sections in the 384-height world (indices 0-23)
        # Section 0 = y=-64 to y=-49, section 4 = y=0 to y=15
        # For 256-height, we need 16 sections (y=0 to y=255)
        # We use sections 4-19 from the 384 world

        for section_idx in range(16):
            # Map to 384-world section index (offset by 4)
            src_idx = section_idx + 4

            if src_idx < len(chunk_blocks):
                section_blocks = chunk_blocks[src_idx * 16:(src_idx + 1) * 16]
                biome_section = None
                if chunk_biomes is not None and src_idx < len(chunk_biomes):
                    biome_section = chunk_biomes[src_idx]
                result.extend(build_section_from_blocks(section_blocks, biome_section, biome_plains))
            else:
                # Empty section (air)
                result.extend(struct.pack('>h', 0))  # block count
                result.extend(encode_paletted_container_single(AIR))
                result.extend(encode_paletted_container_single(biome_plains))

        return bytes(result)

    def build_heightmap_for_version(self, chunk_blocks):
        """
        Build heightmap for 1.16 (256 height world).
        Heights must be relative to min_y=0, and fit in 9 bits.
        """
        from world.blocks import AIR, WATER
        from world.chunk import MIN_Y

        bits_per_entry = 9
        entries_per_long = 64 // bits_per_entry  # 7
        num_longs = math.ceil(256 / entries_per_long)  # 37

        heights = [0] * 256
        for z in range(16):
            for x in range(16):
                height = 0
                # Only scan from y=255 down to y=0 in world coords
                # In our array: y_index = world_y - MIN_Y
                # We scan from array index 255+64=319 down to 0+64=64
                for yi in range(min(319, len(chunk_blocks) - 1), 63, -1):
                    block = chunk_blocks[yi][z][x]
                    if block != AIR and block != WATER:
                        # Convert from array index to world Y, then to 256-height Y
                        world_y = yi + MIN_Y
                        height = max(0, world_y)  # Clamp to 0 minimum for 256-height
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
        """Build Chunk Data and Update Light packet for 1.16.x."""
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

        # Light data for 16+2=18 sections
        all_bits = (1 << 18) - 1
        payload.extend(write_varint(1))
        payload.extend(write_long(all_bits))
        payload.extend(write_varint(1))
        payload.extend(write_long(all_bits))
        payload.extend(write_varint(0))
        payload.extend(write_varint(0))

        sky_light_section = bytes([0xFF] * 2048)
        light_section_count = 18  # 16 + 2 boundary
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
