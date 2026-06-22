# ============================================================
# PyMC - 版本特定的数据包 ID 映射
# 不同 Minecraft 版本的数据包 ID 不同
# ============================================================

"""
Version-specific packet ID mappings for Minecraft protocol.

Each version has different packet IDs for the same logical packets.
This module provides the correct packet ID for the client's version.

Key packets tracked:
- CLIENTBOUND (server -> client):
  - join_game: Login (Join Game) packet
  - keep_alive: Keep Alive
  - chunk_data: Chunk Data and Update Light
  - player_position: Synchronize Player Position
  - system_chat: System Chat Message
  - player_info: Player Info Update
  - player_remove: Player Remove
  - spawn_position: Set Default Spawn Position
  - set_center_chunk: Set Center Chunk
  - game_event: Game Event (game state change)
  - update_time: Update Time
  - update_health: Update Health
  - set_experience: Set Experience
  - entity_teleport: Entity Teleport
  - remove_entities: Remove Entities
  - multi_block_change: Multi Block Change
  - block_update: Block Update
  - set_chunk_cache_radius: Set Chunk Cache Radius (view distance)

- SERVERBOUND (client -> server):
  - confirm_teleportation: Confirm Teleportation
  - chat_message: Chat Message
  - chat_command: Chat Command
  - keep_alive: Keep Alive
  - player_position: Player Position
  - player_position_rotation: Player Position and Rotation
  - player_rotation: Player Rotation
  - player_on_ground: Player On Ground
  - block_dig: Block Dig (Player Digging)
  - held_item_slot: Held Item Change
  - block_place: Use Item On / Block Place
  - chunk_batch_received: Chunk Batch Received
"""

# Clientbound packet IDs for each protocol version
CLIENTBOUND_PACKETS = {
    # --- 1.8.9 (Protocol 47) ---
    47: {
        "join_game": 0x01,
        "keep_alive": 0x00,
        "chunk_data": 0x21,
        "player_position": 0x08,
        "chat_message": 0x02,       # Chat Message (old format)
        "player_info": 0x38,
        "player_remove": None,       # No separate remove in 1.8
        "spawn_position": 0x05,
        "set_center_chunk": None,    # No center chunk in 1.8
        "game_event": 0x1B,
        "update_time": 0x03,
        "update_health": 0x06,
        "set_experience": 0x1F,
        "entity_teleport": 0x18,
        "remove_entities": 0x13,
        "multi_block_change": 0x22,
        "block_update": 0x23,
        "set_chunk_cache_radius": None,  # No view distance sync in 1.8
        "system_chat": None,         # Uses chat_message instead
        "player_abilities": 0x39,
        "held_item_change": 0x3E,
        "window_items": 0x30,
        "disconnect": 0x40,
        "entity_metadata": 0x1C,
        "entity_velocity": 0x12,
        "entity_status": 0x1A,
    },

    # --- 1.12.2 (Protocol 340) ---
    340: {
        "join_game": 0x23,
        "keep_alive": 0x1F,
        "chunk_data": 0x20,
        "player_position": 0x2E,
        "chat_message": 0x0F,
        "player_info": 0x2E,
        "player_remove": None,
        "spawn_position": 0x43,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x46,
        "update_health": 0x3D,
        "set_experience": 0x3E,
        "entity_teleport": 0x4A,
        "remove_entities": 0x31,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x2C,
        "held_item_change": 0x3B,
        "window_items": 0x14,
        "disconnect": 0x1A,
        "entity_metadata": 0x3A,
        "entity_velocity": 0x3D,
        "entity_status": 0x39,
    },

    # --- 1.13.2 (Protocol 404) ---
    404: {
        "join_game": 0x25,
        "keep_alive": 0x21,
        "chunk_data": 0x22,
        "player_position": 0x30,
        "chat_message": 0x0E,
        "player_info": 0x30,
        "player_remove": None,
        "spawn_position": 0x45,
        "set_center_chunk": None,
        "game_event": 0x20,
        "update_time": 0x48,
        "update_health": 0x3F,
        "set_experience": 0x40,
        "entity_teleport": 0x4C,
        "remove_entities": 0x33,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x2E,
        "held_item_change": 0x3D,
        "window_items": 0x15,
        "disconnect": 0x1B,
        "entity_metadata": 0x3C,
        "entity_velocity": 0x3F,
        "entity_status": 0x3B,
    },

    # --- 1.14.4 (Protocol 498) ---
    498: {
        "join_game": 0x26,
        "keep_alive": 0x20,
        "chunk_data": 0x21,
        "player_position": 0x35,
        "chat_message": 0x0E,
        "player_info": 0x33,
        "player_remove": None,
        "spawn_position": 0x4D,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x4E,
        "update_health": 0x44,
        "set_experience": 0x45,
        "entity_teleport": 0x56,
        "remove_entities": 0x37,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x31,
        "held_item_change": 0x40,
        "window_items": 0x14,
        "disconnect": 0x1A,
        "entity_metadata": 0x3F,
        "entity_velocity": 0x42,
        "entity_status": 0x3C,
    },

    # --- 1.15.2 (Protocol 578) ---
    578: {
        "join_game": 0x26,
        "keep_alive": 0x21,
        "chunk_data": 0x22,
        "player_position": 0x36,
        "chat_message": 0x0E,
        "player_info": 0x34,
        "player_remove": None,
        "spawn_position": 0x4E,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x4F,
        "update_health": 0x45,
        "set_experience": 0x46,
        "entity_teleport": 0x57,
        "remove_entities": 0x38,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x32,
        "held_item_change": 0x41,
        "window_items": 0x14,
        "disconnect": 0x1A,
        "entity_metadata": 0x40,
        "entity_velocity": 0x43,
        "entity_status": 0x3D,
    },

    # --- 1.16.1 (Protocol 736) ---
    736: {
        "join_game": 0x25,
        "keep_alive": 0x20,
        "chunk_data": 0x21,
        "player_position": 0x35,
        "chat_message": 0x0E,
        "player_info": 0x33,
        "player_remove": None,
        "spawn_position": 0x4D,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x4E,
        "update_health": 0x44,
        "set_experience": 0x45,
        "entity_teleport": 0x56,
        "remove_entities": 0x37,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x31,
        "held_item_change": 0x40,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x3F,
        "entity_velocity": 0x42,
        "entity_status": 0x3C,
    },

    # --- 1.16.2 (Protocol 754) ---
    754: {
        "join_game": 0x26,
        "keep_alive": 0x21,
        "chunk_data": 0x22,
        "player_position": 0x36,
        "chat_message": 0x0E,
        "player_info": 0x34,
        "player_remove": None,
        "spawn_position": 0x4E,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x4F,
        "update_health": 0x45,
        "set_experience": 0x46,
        "entity_teleport": 0x57,
        "remove_entities": 0x38,
        "multi_block_change": 0x0F,
        "block_update": 0x0B,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x32,
        "held_item_change": 0x41,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x40,
        "entity_velocity": 0x43,
        "entity_status": 0x3D,
    },

    # --- 1.17.1 (Protocol 757) ---
    757: {
        "join_game": 0x26,
        "keep_alive": 0x21,
        "chunk_data": 0x22,
        "player_position": 0x38,
        "chat_message": 0x0F,
        "player_info": 0x36,
        "player_remove": None,
        "spawn_position": 0x4A,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x58,
        "update_health": 0x49,
        "set_experience": 0x4A,
        "entity_teleport": 0x61,
        "remove_entities": 0x3C,
        "multi_block_change": 0x3B,
        "block_update": 0x0C,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x33,
        "held_item_change": 0x43,
        "window_items": 0x14,
        "disconnect": 0x1A,
        "entity_metadata": 0x44,
        "entity_velocity": 0x47,
        "entity_status": 0x3E,
    },

    # --- 1.18.2 (Protocol 758) ---
    758: {
        "join_game": 0x26,
        "keep_alive": 0x22,
        "chunk_data": 0x22,
        "player_position": 0x39,
        "chat_message": 0x0F,
        "player_info": 0x36,
        "player_remove": None,
        "spawn_position": 0x4A,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x59,
        "update_health": 0x49,
        "set_experience": 0x4A,
        "entity_teleport": 0x62,
        "remove_entities": 0x3C,
        "multi_block_change": 0x3B,
        "block_update": 0x0C,
        "set_chunk_cache_radius": None,
        "system_chat": None,
        "player_abilities": 0x33,
        "held_item_change": 0x43,
        "window_items": 0x14,
        "disconnect": 0x1A,
        "entity_metadata": 0x44,
        "entity_velocity": 0x47,
        "entity_status": 0x3E,
    },

    # --- 1.19.2 (Protocol 761) ---
    761: {
        "join_game": 0x27,
        "keep_alive": 0x23,
        "chunk_data": 0x22,
        "player_position": 0x3C,
        "chat_message": None,         # Replaced by system_chat and player_chat
        "player_info": 0x38,
        "player_remove": None,
        "spawn_position": 0x4D,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x5C,
        "update_health": 0x4D,
        "set_experience": 0x4E,
        "entity_teleport": 0x69,
        "remove_entities": 0x3D,
        "multi_block_change": 0x3C,
        "block_update": 0x0C,
        "set_chunk_cache_radius": None,
        "system_chat": 0x62,
        "player_abilities": 0x35,
        "held_item_change": 0x48,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x4C,
        "entity_velocity": 0x4F,
        "entity_status": 0x44,
    },

    # --- 1.19.3 (Protocol 764) ---
    764: {
        "join_game": 0x28,
        "keep_alive": 0x24,
        "chunk_data": 0x22,
        "player_position": 0x3E,
        "chat_message": None,
        "player_info": 0x39,
        "player_remove": 0x3A,
        "spawn_position": 0x4E,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x5D,
        "update_health": 0x4E,
        "set_experience": 0x4F,
        "entity_teleport": 0x6B,
        "remove_entities": 0x3C,
        "multi_block_change": 0x3C,
        "block_update": 0x0C,
        "set_chunk_cache_radius": None,
        "system_chat": 0x64,
        "player_abilities": 0x36,
        "held_item_change": 0x49,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x4D,
        "entity_velocity": 0x50,
        "entity_status": 0x45,
    },

    # --- 1.19.4 (Protocol 765) ---
    765: {
        "join_game": 0x29,
        "keep_alive": 0x25,
        "chunk_data": 0x23,
        "player_position": 0x3F,
        "chat_message": None,
        "player_info": 0x3A,
        "player_remove": 0x3B,
        "spawn_position": 0x4F,
        "set_center_chunk": None,
        "game_event": 0x1E,
        "update_time": 0x5E,
        "update_health": 0x4F,
        "set_experience": 0x50,
        "entity_teleport": 0x6C,
        "remove_entities": 0x3D,
        "multi_block_change": 0x3D,
        "block_update": 0x0C,
        "set_chunk_cache_radius": None,
        "system_chat": 0x65,
        "player_abilities": 0x37,
        "held_item_change": 0x4A,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x4E,
        "entity_velocity": 0x51,
        "entity_status": 0x46,
    },

    # --- 1.20.1 (Protocol 766) ---
    766: {
        "join_game": 0x2A,
        "keep_alive": 0x24,
        "chunk_data": 0x24,
        "player_position": 0x3F,
        "chat_message": None,
        "player_info": 0x3B,
        "player_remove": 0x3C,
        "spawn_position": 0x50,
        "set_center_chunk": 0x4E,
        "game_event": 0x1E,
        "update_time": 0x5F,
        "update_health": 0x50,
        "set_experience": 0x51,
        "entity_teleport": 0x6D,
        "remove_entities": 0x3E,
        "multi_block_change": 0x3E,
        "block_update": 0x0C,
        "set_chunk_cache_radius": 0x51,
        "system_chat": 0x67,
        "player_abilities": 0x38,
        "held_item_change": 0x4B,
        "window_items": 0x15,
        "disconnect": 0x1A,
        "entity_metadata": 0x4F,
        "entity_velocity": 0x52,
        "entity_status": 0x47,
    },

    # --- 1.21.1 (Protocol 767) - NATIVE ---
    767: {
        "join_game": 0x2B,
        "keep_alive": 0x26,
        "chunk_data": 0x27,
        "player_position": 0x40,
        "chat_message": None,
        "player_info": 0x3E,
        "player_remove": 0x3D,
        "spawn_position": 0x56,
        "set_center_chunk": 0x54,
        "game_event": 0x22,
        "update_time": 0x64,
        "update_health": 0x5D,
        "set_experience": 0x5C,
        "entity_teleport": 0x70,
        "remove_entities": 0x42,
        "multi_block_change": 0x49,
        "block_update": 0x0C,
        "set_chunk_cache_radius": 0x55,
        "system_chat": 0x6C,
        "player_abilities": 0x3A,
        "held_item_change": 0x4E,
        "window_items": 0x11,
        "disconnect": 0x1D,
        "entity_metadata": 0x52,
        "entity_velocity": 0x55,
        "entity_status": 0x4A,
    },

    # --- 1.21.4 (Protocol 770) ---
    770: {
        "join_game": 0x2C,
        "keep_alive": 0x27,
        "chunk_data": 0x28,
        "player_position": 0x41,
        "chat_message": None,
        "player_info": 0x3F,
        "player_remove": 0x3E,
        "spawn_position": 0x57,
        "set_center_chunk": 0x55,
        "game_event": 0x23,
        "update_time": 0x65,
        "update_health": 0x5E,
        "set_experience": 0x5D,
        "entity_teleport": 0x71,
        "remove_entities": 0x43,
        "multi_block_change": 0x4A,
        "block_update": 0x0D,
        "set_chunk_cache_radius": 0x56,
        "system_chat": 0x6D,
        "player_abilities": 0x3B,
        "held_item_change": 0x4F,
        "window_items": 0x11,
        "disconnect": 0x1E,
        "entity_metadata": 0x53,
        "entity_velocity": 0x56,
        "entity_status": 0x4B,
    },
}

# Serverbound packet IDs for each protocol version
SERVERBOUND_PACKETS = {
    47: {
        "confirm_teleportation": None,   # No teleport confirm in 1.8
        "chat_message": 0x01,
        "chat_command": None,
        "keep_alive": 0x00,
        "player_position": 0x04,
        "player_position_rotation": 0x06,
        "player_rotation": 0x05,
        "player_on_ground": None,
        "block_dig": 0x07,
        "held_item_slot": 0x09,
        "block_place": 0x08,
        "chunk_batch_received": None,
    },
    340: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": None,
        "keep_alive": 0x0C,
        "player_position": 0x0E,
        "player_position_rotation": 0x10,
        "player_rotation": 0x0F,
        "player_on_ground": None,
        "block_dig": 0x13,
        "held_item_slot": 0x1E,
        "block_place": 0x1D,
        "chunk_batch_received": None,
    },
    404: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": None,
        "keep_alive": 0x0E,
        "player_position": 0x11,
        "player_position_rotation": 0x13,
        "player_rotation": 0x12,
        "player_on_ground": None,
        "block_dig": 0x15,
        "held_item_slot": 0x21,
        "block_place": 0x29,
        "chunk_batch_received": None,
    },
    498: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": None,
        "keep_alive": 0x0F,
        "player_position": 0x11,
        "player_position_rotation": 0x13,
        "player_rotation": 0x12,
        "player_on_ground": None,
        "block_dig": 0x16,
        "held_item_slot": 0x24,
        "block_place": 0x2C,
        "chunk_batch_received": None,
    },
    578: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": None,
        "keep_alive": 0x0F,
        "player_position": 0x11,
        "player_position_rotation": 0x13,
        "player_rotation": 0x12,
        "player_on_ground": None,
        "block_dig": 0x16,
        "held_item_slot": 0x24,
        "block_place": 0x2C,
        "chunk_batch_received": None,
    },
    736: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": 0x02,
        "keep_alive": 0x0F,
        "player_position": 0x11,
        "player_position_rotation": 0x13,
        "player_rotation": 0x12,
        "player_on_ground": None,
        "block_dig": 0x16,
        "held_item_slot": 0x23,
        "block_place": 0x2C,
        "chunk_batch_received": None,
    },
    754: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": 0x02,
        "keep_alive": 0x10,
        "player_position": 0x12,
        "player_position_rotation": 0x14,
        "player_rotation": 0x13,
        "player_on_ground": None,
        "block_dig": 0x17,
        "held_item_slot": 0x24,
        "block_place": 0x2E,
        "chunk_batch_received": None,
    },
    757: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x03,
        "chat_command": 0x02,
        "keep_alive": 0x10,
        "player_position": 0x12,
        "player_position_rotation": 0x14,
        "player_rotation": 0x13,
        "player_on_ground": None,
        "block_dig": 0x17,
        "held_item_slot": 0x24,
        "block_place": 0x2E,
        "chunk_batch_received": None,
    },
    758: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x04,
        "chat_command": 0x03,
        "keep_alive": 0x11,
        "player_position": 0x13,
        "player_position_rotation": 0x15,
        "player_rotation": 0x14,
        "player_on_ground": None,
        "block_dig": 0x1A,
        "held_item_slot": 0x25,
        "block_place": 0x31,
        "chunk_batch_received": None,
    },
    761: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x05,
        "chat_command": 0x03,
        "signed_chat_command": 0x04,
        "keep_alive": 0x12,
        "player_position": 0x14,
        "player_position_rotation": 0x16,
        "player_rotation": 0x15,
        "player_on_ground": None,
        "block_dig": 0x1C,
        "held_item_slot": 0x27,
        "block_place": 0x33,
        "chunk_batch_received": None,
    },
    764: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x05,
        "chat_command": 0x03,
        "signed_chat_command": 0x04,
        "keep_alive": 0x13,
        "player_position": 0x15,
        "player_position_rotation": 0x17,
        "player_rotation": 0x16,
        "player_on_ground": None,
        "block_dig": 0x1D,
        "held_item_slot": 0x28,
        "block_place": 0x34,
        "chunk_batch_received": None,
    },
    765: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x05,
        "chat_command": 0x03,
        "signed_chat_command": 0x04,
        "keep_alive": 0x14,
        "player_position": 0x16,
        "player_position_rotation": 0x18,
        "player_rotation": 0x17,
        "player_on_ground": None,
        "block_dig": 0x1E,
        "held_item_slot": 0x29,
        "block_place": 0x35,
        "chunk_batch_received": None,
    },
    766: {
        "confirm_teleportation": 0x00,
        "chat_message": 0x05,
        "chat_command": 0x03,
        "signed_chat_command": 0x04,
        "keep_alive": 0x14,
        "player_position": 0x16,
        "player_position_rotation": 0x18,
        "player_rotation": 0x17,
        "player_on_ground": None,
        "block_dig": 0x1E,
        "held_item_slot": 0x29,
        "block_place": 0x35,
        "chunk_batch_received": None,
    },
    767: {
        "confirm_teleportation": 0x00,
        "chat_command": 0x05,
        "signed_chat_command": 0x06,
        "chat_message": 0x07,
        "keep_alive": 0x1A,
        "player_position": 0x1C,
        "player_position_rotation": 0x1D,
        "player_rotation": 0x1E,
        "player_on_ground": 0x1F,
        "block_dig": 0x26,
        "held_item_slot": 0x31,
        "block_place": 0x3A,
        "chunk_batch_received": 0x09,
    },
    770: {
        "confirm_teleportation": 0x00,
        "chat_command": 0x05,
        "signed_chat_command": 0x06,
        "chat_message": 0x07,
        "keep_alive": 0x1B,
        "player_position": 0x1D,
        "player_position_rotation": 0x1E,
        "player_rotation": 0x1F,
        "player_on_ground": 0x20,
        "block_dig": 0x27,
        "held_item_slot": 0x32,
        "block_place": 0x3B,
        "chunk_batch_received": 0x09,
    },
}


def get_clientbound_packet(protocol_version: int, packet_name: str) -> int | None:
    """
    Get the clientbound packet ID for a specific protocol version and packet name.

    Args:
        protocol_version: The client's protocol version
        packet_name: The logical packet name (e.g. "join_game", "keep_alive")

    Returns:
        The packet ID, or None if the packet doesn't exist in this version
    """
    version_packets = CLIENTBOUND_PACKETS.get(protocol_version)
    if version_packets is None:
        # Fall back to native version
        version_packets = CLIENTBOUND_PACKETS.get(767)
    if version_packets is None:
        return None
    return version_packets.get(packet_name)


def get_serverbound_packet(protocol_version: int, packet_name: str) -> int | None:
    """
    Get the serverbound packet ID for a specific protocol version and packet name.

    Args:
        protocol_version: The client's protocol version
        packet_name: The logical packet name

    Returns:
        The packet ID, or None if the packet doesn't exist in this version
    """
    version_packets = SERVERBOUND_PACKETS.get(protocol_version)
    if version_packets is None:
        version_packets = SERVERBOUND_PACKETS.get(767)
    if version_packets is None:
        return None
    return version_packets.get(packet_name)


def get_clientbound_map(protocol_version: int) -> dict:
    """Get the full clientbound packet map for a protocol version."""
    return CLIENTBOUND_PACKETS.get(protocol_version, CLIENTBOUND_PACKETS.get(767, {}))


def get_serverbound_map(protocol_version: int) -> dict:
    """Get the full serverbound packet map for a protocol version."""
    return SERVERBOUND_PACKETS.get(protocol_version, SERVERBOUND_PACKETS.get(767, {}))


def build_serverbound_reverse_map(protocol_version: int) -> dict[int, str]:
    """
    Build a reverse mapping from serverbound packet ID -> packet name.
    Used for dispatching incoming packets from the client.
    """
    forward_map = get_serverbound_map(protocol_version)
    reverse = {}
    for name, pid in forward_map.items():
        if pid is not None:
            reverse[pid] = name
    return reverse
