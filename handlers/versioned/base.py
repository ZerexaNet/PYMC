# ============================================================
# PyMC - VersionHandler 基类
# 所有版本处理器的基类，定义了版本化协议处理的接口
# ============================================================

"""
Base class for version-specific protocol handlers.
Subclasses override methods to handle version differences.
"""

from protocol.data_types import write_int, write_long, write_varint
from protocol.nbt import encode_nbt, NbtLongArray


class VersionHandler:
    """
    Base class for version-specific protocol handlers.
    Subclasses override methods to handle version differences.
    """

    # Subclasses should override these
    PROTOCOL_VERSION = 767
    VERSION_NAME = "1.21.1"

    # World parameters
    WORLD_MIN_Y = -64
    WORLD_HEIGHT = 384
    NUM_SECTIONS = 24

    # Protocol capabilities
    HAS_CONFIGURATION_PHASE = True
    HAS_CHAT_SIGNING = True
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    def __init__(self, protocol_version: int | None = None):
        # Grouped handlers share payload logic, but packet IDs must use the
        # exact protocol negotiated with this connection.
        if protocol_version is not None:
            self.PROTOCOL_VERSION = protocol_version

    def get_packet_id(self, packet_name: str) -> int | None:
        """Get a clientbound packet ID by name for this version."""
        from protocol.packet_map import get_clientbound_packet
        return get_clientbound_packet(self.PROTOCOL_VERSION, packet_name)

    async def send_join_game(self, conn, server):
        """Send the Join Game (Login) packet in this version's format."""
        raise NotImplementedError

    def build_chunk_packet(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Build a Chunk Data packet for this version."""
        raise NotImplementedError

    def build_heightmap_nbt(self, motion_blocking, world_surface):
        """Build the heightmap NBT compound for this version."""
        heightmap_nbt = {
            "MOTION_BLOCKING": NbtLongArray(motion_blocking),
            "WORLD_SURFACE": NbtLongArray(world_surface),
        }
        return encode_nbt(heightmap_nbt, with_type=True)

    async def send_system_chat(self, conn, text, overlay=False):
        """Send a system chat message in this version's format.

        ``text`` may be a plain string or a text component (dict / JSON).
        1.20.3+ clients receive NBT, older clients a JSON string.
        """
        from protocol.data_types import write_boolean, write_byte, write_varint
        from protocol.text import encode_component
        pid = self.get_packet_id("system_chat")
        if pid is None:
            # Pre-1.19: legacy Chat Message (JSON + position byte)
            pid = self.get_packet_id("chat_message")
            if pid is None:
                return
            payload = bytearray()
            payload.extend(encode_component(text, self.PROTOCOL_VERSION))
            payload.extend(write_byte(0 if not overlay else 2))  # 0=chat, 2=action bar
            if self.PROTOCOL_VERSION >= 735:
                payload.extend(bytes(16))  # 1.16+: sender UUID
            await conn.send_packet(pid, bytes(payload))
            return

        payload = bytearray()
        payload.extend(encode_component(text, self.PROTOCOL_VERSION))
        if self.PROTOCOL_VERSION == 759:
            payload.extend(write_varint(2 if overlay else 1))  # 1.19: chat type id
        else:
            payload.extend(write_boolean(overlay))
        await conn.send_packet(pid, bytes(payload))

    async def send_synchronize_position(self, conn):
        """Send Synchronize Player Position packet for this version.

        Format reference (per protocol version):
          < 1.20 (protocol < 763):
            Double X, Y, Z, Delta X, Y, Z, Float Yaw, Pitch, Byte Flags, VarInt Teleport ID
          1.20 - 1.20.1 (protocol 763):
            Double X, Y, Z, Float Yaw, Pitch, Byte Flags, VarInt Teleport ID
            (delta coordinates removed in 1.20)
          1.20.2+ (protocol >= 764):
            Double X, Y, Z, Float Yaw, Pitch, Byte Flags, VarInt Teleport ID
            (same as 1.20 — no delta coordinates)
          1.21+ (protocol >= 767):
            Double X, Y, Z, Float Yaw, Pitch, Byte Flags, VarInt Teleport ID
            (unchanged from 1.20.2)

        The bug that caused 'found 24 bytes extra whilst reading packet
        clientbound/minecraft:player_position' was sending the three
        delta-Double fields on 1.21+ — that's exactly 24 bytes of extra
        payload the 1.21 client doesn't expect.
        """
        from protocol.data_types import (
            write_double, write_float, write_varint, write_byte
        )
        pid = self.get_packet_id("player_position")
        if pid is None:
            return

        conn.teleport_id = (conn.teleport_id + 1) & 0x7FFFFFFF

        payload = bytearray()
        payload.extend(write_double(conn.x))
        payload.extend(write_double(conn.y))
        payload.extend(write_double(conn.z))

        # Delta coordinates only exist in pre-1.20 (protocol < 763)
        # 1.20+ removed them. NEVER send delta on 1.21+.
        if self.PROTOCOL_VERSION < 763:
            payload.extend(write_double(0.0))   # delta X
            payload.extend(write_double(0.0))   # delta Y
            payload.extend(write_double(0.0))   # delta Z

        payload.extend(write_float(conn.yaw))
        payload.extend(write_float(conn.pitch))

        if self.PROTOCOL_VERSION >= 47:
            flags = 0
            # Flags is a Byte (signed 8-bit) on all modern versions
            payload.extend(write_byte(flags))
            payload.extend(write_varint(conn.teleport_id))

        await conn.send_packet(pid, bytes(payload))

    async def send_game_event(self, conn, event, value):
        """Send Game Event packet."""
        from protocol.data_types import write_ubyte, write_float
        pid = self.get_packet_id("game_event")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_ubyte(event))
            payload.extend(write_float(value))
            await conn.send_packet(pid, bytes(payload))

    async def send_update_health(self, conn):
        """Send Update Health packet."""
        from protocol.data_types import write_float, write_varint
        pid = self.get_packet_id("update_health")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_float(conn.health))
            payload.extend(write_varint(conn.food))
            payload.extend(write_float(conn.saturation))
            await conn.send_packet(pid, bytes(payload))

    async def send_set_experience(self, conn):
        """Send Set Experience packet."""
        from protocol.data_types import write_float, write_varint
        pid = self.get_packet_id("set_experience")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_float(conn.experience_progress))
            payload.extend(write_varint(conn.experience_level))
            payload.extend(write_varint(conn.experience_total))
            await conn.send_packet(pid, bytes(payload))

    async def send_update_time(self, conn, world_age, day_time=None):
        """Send Update Time packet (world age + time of day)."""
        from protocol.data_types import write_long
        if day_time is None:
            day_time = world_age
        pid = self.get_packet_id("update_time")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_long(int(world_age)))
            payload.extend(write_long(int(day_time)))
            await conn.send_packet(pid, bytes(payload))

    async def send_set_center_chunk(self, conn, chunk_x, chunk_z):
        """Send Set Center Chunk packet."""
        from protocol.data_types import write_varint
        pid = self.get_packet_id("set_center_chunk")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_varint(chunk_x))
            payload.extend(write_varint(chunk_z))
            await conn.send_packet(pid, bytes(payload))

    async def send_set_chunk_cache_radius(self, conn, view_distance):
        """Send Set Chunk Cache Radius packet."""
        from protocol.data_types import write_varint
        pid = self.get_packet_id("set_chunk_cache_radius")
        if pid is not None:
            await conn.send_packet(pid, write_varint(view_distance))

    async def send_remove_entities(self, conn, entity_ids):
        """Send Remove Entities packet."""
        from protocol.data_types import write_varint
        pid = self.get_packet_id("remove_entities")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_varint(len(entity_ids)))
            for eid in entity_ids:
                payload.extend(write_varint(eid))
            await conn.send_packet(pid, bytes(payload))

    def build_chunk_packet_full_light(self, chunk_x, chunk_z, chunk_data, heightmap_longs,
                           chunk_blocks=None, sky_light_arrays=None,
                           block_light_arrays=None):
        """Chunk Data and Update Light packet with full light masks (1.17 and later layout)."""
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

    def build_chunk_data_for_version(self, chunk_blocks, chunk_biomes=None):
        """
        Build chunk column data appropriate for this version.
        For pre-1.17 versions, this must compress 24 sections into 16.
        """
        from world.chunk import build_chunk_column_from_terrain
        return build_chunk_column_from_terrain(chunk_blocks, chunk_biomes)

    def build_heightmap_for_version(self, chunk_blocks):
        """
        Build heightmap data appropriate for this version.
        For pre-1.17 versions, height values must fit in 9 bits (max 256).
        """
        from world.chunk import build_heightmap_from_terrain
        return build_heightmap_from_terrain(chunk_blocks)
