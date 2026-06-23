# ============================================================
# PyMC - VersionHandler 基类
# 所有版本处理器的基类，定义了版本化协议处理的接口
# ============================================================

"""
Base class for version-specific protocol handlers.
Subclasses override methods to handle version differences.
"""

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

    def get_packet_map(self) -> dict:
        """Return clientbound packet ID mappings for this version."""
        from protocol.packet_map import get_clientbound_map
        return get_clientbound_map(self.PROTOCOL_VERSION)

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

    async def send_keep_alive(self, conn, keep_alive_id):
        """Send a Keep Alive packet."""
        from protocol.data_types import write_long
        pid = self.get_packet_id("keep_alive")
        if pid is not None:
            await conn.send_packet(pid, write_long(keep_alive_id))

    async def send_system_chat(self, conn, text, overlay=False):
        """Send a system chat message in this version's format."""
        import json
        from protocol.data_types import write_string, write_boolean
        pid = self.get_packet_id("system_chat")
        if pid is None:
            # Fall back to old chat message format
            pid = self.get_packet_id("chat_message")
            if pid is None:
                return
            # Old chat format: JSON Chat + position byte
            chat_json = json.dumps({"text": text}, ensure_ascii=False)
            payload = bytearray()
            payload.extend(write_string(chat_json))
            payload.extend(write_byte(0 if not overlay else 2))  # 0=chat, 1=system, 2=action bar
            await conn.send_packet(pid, bytes(payload))
            return

        # 1.19+ system chat format
        chat_json = json.dumps({"text": text}, ensure_ascii=False)
        payload = bytearray()
        payload.extend(write_string(chat_json))
        payload.extend(write_boolean(overlay))
        await conn.send_packet(pid, bytes(payload))

    async def send_synchronize_position(self, conn):
        """Send Synchronize Player Position packet for this version."""
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

        if self.PROTOCOL_VERSION >= 767:
            # 1.21+ format: delta coordinates
            payload.extend(write_double(0.0))   # delta X
            payload.extend(write_double(0.0))   # delta Y
            payload.extend(write_double(0.0))   # delta Z

        payload.extend(write_float(conn.yaw))
        payload.extend(write_float(conn.pitch))

        if self.PROTOCOL_VERSION >= 47:
            flags = 0
            payload.extend(write_varint(flags))
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

    async def send_spawn_position(self, conn, x, y, z):
        """Send Set Default Spawn Position packet."""
        from protocol.data_types import write_position, write_float
        pid = self.get_packet_id("spawn_position")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_position(x, y, z))
            payload.extend(write_float(0.0))
            await conn.send_packet(pid, bytes(payload))

    async def send_update_time(self, conn, world_time):
        """Send Update Time packet."""
        from protocol.data_types import write_long
        pid = self.get_packet_id("update_time")
        if pid is not None:
            payload = bytearray()
            payload.extend(write_long(world_time))
            payload.extend(write_long(world_time))  # time of day
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

    async def send_player_info_update(self, conn, players, server):
        """Send Player Info Update packet (or equivalent for older versions)."""
        # This is version-specific and will be overridden
        pass

    async def send_player_info_remove(self, conn, uuids, server):
        """Send Player Info Remove packet (or equivalent for older versions)."""
        # This is version-specific
        pass

    async def handle_login_success(self, conn, server):
        """
        After Login Success is sent, handle the transition.
        For 1.20.2+, go to configuration phase.
        For older versions, go directly to play phase.
        """
        if self.HAS_CONFIGURATION_PHASE:
            # Wait for Login Acknowledged from client
            pass
        else:
            # Go directly to play
            from network.connection import ConnectionState
            conn.state = ConnectionState.PLAY

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
