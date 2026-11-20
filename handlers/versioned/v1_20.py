# ============================================================
# PyMC - 1.20 版本处理器
# 处理 1.20.1 (协议 766) 的协议差异
# 1.20.1 仍使用配置阶段，但数据包 ID 不同
# ============================================================

"""
Version handler for Minecraft 1.20.1 (Protocol 766).
Has configuration phase but different packet IDs than 1.21.
Uses the same 384-height world format.
"""

import logging
from protocol.data_types import (
    write_varint, write_boolean, write_int, write_long, write_byte,
    write_ubyte, write_identifier,
)
from handlers.versioned.base import VersionHandler

logger = logging.getLogger("PyMC.版本.1_20")


class VersionHandlerV1_20(VersionHandler):
    """Handler for Minecraft 1.20.1 (protocol 766)."""

    PROTOCOL_VERSION = 766
    VERSION_NAME = "1.20.1"

    WORLD_MIN_Y = -64
    WORLD_HEIGHT = 384
    NUM_SECTIONS = 24

    HAS_CONFIGURATION_PHASE = True
    HAS_CHAT_SIGNING = True
    HAS_FLATTENING = True
    HAS_DIMENSION_REGISTRY = True

    async def send_join_game(self, conn, server):
        """Send Join Game packet for 1.20.1."""
        pid = self.get_packet_id("join_game")
        if pid is None:
            logger.error("Cannot find join_game packet ID for 1.20.1")
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

    build_chunk_packet = VersionHandler.build_chunk_packet_full_light
