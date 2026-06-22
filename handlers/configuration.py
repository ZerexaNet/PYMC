# ============================================================
# PyMC - 配置阶段处理器
# 发送注册表数据、完成配置并进入游戏阶段
# 现在包含多版本协议支持 (仅 1.20.2+ 使用配置阶段)
# ============================================================

import logging
from protocol.data_types import (
    write_string, write_varint, write_boolean, write_identifier
)
from protocol.nbt import (
    encode_nbt, NbtByte, NbtFloat, NbtLong, NbtDouble
)
from protocol.versions import has_configuration_phase
from network.connection import Connection, ConnectionState
from world.biomes import build_biome_registry_entries

logger = logging.getLogger("PyMC.配置")


def _build_damage_type_registry() -> dict:
    """
    构建 1.21.1 所需的基础伤害类型注册表。

    客户端在进入世界时会初始化 DamageSources。
    如果缺少 vanilla 预期的 key（例如 minecraft:in_fire），
    客户端或某些客户端模组会在收到 Join Game 包后直接崩溃。
    """
    damage_keys = [
        "in_fire",
        "campfire",
        "lightning_bolt",
        "on_fire",
        "lava",
        "hot_floor",
        "in_wall",
        "cramming",
        "drown",
        "starve",
        "cactus",
        "fall",
        "fly_into_wall",
        "out_of_world",
        "generic",
        "magic",
        "wither",
        "dragon_breath",
        "dry_out",
        "sweet_berry_bush",
        "freeze",
        "stalagmite",
        "falling_block",
        "falling_anvil",
        "falling_stalactite",
        "sting",
        "mob_attack",
        "mob_attack_no_aggro",
        "player_attack",
        "arrow",
        "trident",
        "mob_projectile",
        "spit",
        "wind_charge",
        "fireworks",
        "fireball",
        "unattributed_fireball",
        "wither_skull",
        "thrown",
        "indirect_magic",
        "thorns",
        "explosion",
        "player_explosion",
        "sonic_boom",
        "bad_respawn_point",
        "outside_border",
        "generic_kill",
    ]

    return {
        f"minecraft:{key}": {
            "message_id": key,
            "scaling": "never",
            "exhaustion": NbtFloat(0.0),
        }
        for key in damage_keys
    }


async def handle_configuration(conn: Connection, packet_id: int,
                                payload: bytes, server):
    """处理配置阶段的数据包。"""

    if packet_id == 0x00:
        # Client Information - 客户端设置信息
        logger.debug(f"收到客户端设置信息: {conn.username}")

    elif packet_id == 0x01:
        # Custom Payload (Plugin Message) - 品牌信息等
        logger.debug(f"收到插件消息: {conn.username}")

    elif packet_id == 0x03:
        # Finish Configuration - 客户端确认配置完成
        await _handle_finish_configuration(conn, server)

    elif packet_id == 0x07:
        # Known Packs
        logger.debug(f"收到已知资源包信息: {conn.username}")

    else:
        logger.debug(f"配置阶段忽略数据包: 0x{packet_id:02X}")


async def send_configuration_packets(conn: Connection, server):
    """
    发送配置阶段所需的所有数据包。
    仅在 1.20.2+ (配置阶段) 时调用。
    """
    if not has_configuration_phase(conn.protocol_version):
        logger.warning(f"尝试为不支持配置阶段的客户端 (协议 {conn.protocol_version}) 发送配置数据包")
        return

    # 1. 发送服务端品牌信息
    await _send_plugin_message(conn, "minecraft:brand", b'\x04PyMC')

    # 2. 发送已知资源包 (Known Packs)
    await _send_known_packs(conn)

    # 3. 发送注册表数据 (Registry Data)
    await _send_registry_data(conn)

    # 4. 发送完成配置信号
    await _send_finish_configuration(conn)


async def _send_plugin_message(conn: Connection, channel: str, data: bytes):
    """发送 Plugin Message 数据包 (配置阶段: 0x01)。"""
    payload = write_identifier(channel) + data
    await conn.send_packet(0x01, payload)


async def _send_known_packs(conn: Connection):
    """
    发送 Known Packs 数据包 (0x0E)。
    告诉客户端服务器知道的资源包。
    """
    # Adjust version string based on client protocol
    from protocol.versions import get_version_name
    version_str = get_version_name(conn.protocol_version)

    payload = bytearray()
    # 已知包数量: 1 (核心资源包)
    payload.extend(write_varint(1))
    payload.extend(write_string("minecraft"))   # 命名空间
    payload.extend(write_string("core"))        # ID
    payload.extend(write_string(version_str))   # 版本
    await conn.send_packet(0x0E, bytes(payload))


async def _send_registry_data(conn: Connection):
    """
    发送所有必需的注册表数据。
    1.20.2+ 使用 Registry Data 数据包 (0x07) 逐个发送注册表。
    """

    # --- 维度类型注册表 ---
    await _send_single_registry(conn, "minecraft:dimension_type", {
        "minecraft:overworld": {
            "has_skylight": NbtByte(1),
            "has_ceiling": NbtByte(0),
            "ultrawarm": NbtByte(0),
            "natural": NbtByte(1),
            "coordinate_scale": NbtDouble(1.0),
            "bed_works": NbtByte(1),
            "respawn_anchor_works": NbtByte(0),
            "min_y": 0,
            "height": 384,
            "logical_height": 384,
            "infiniburn": "#minecraft:infiniburn_overworld",
            "effects": "minecraft:overworld",
            "ambient_light": NbtFloat(0.0),
            "piglin_safe": NbtByte(0),
            "has_raids": NbtByte(1),
            "monster_spawn_light_level": 0,
            "monster_spawn_block_light_limit": 0,
        },
        "minecraft:the_nether": {
            "has_skylight": NbtByte(0),
            "has_ceiling": NbtByte(1),
            "ultrawarm": NbtByte(1),
            "natural": NbtByte(0),
            "coordinate_scale": NbtDouble(8.0),
            "bed_works": NbtByte(0),
            "respawn_anchor_works": NbtByte(1),
            "min_y": 0,
            "height": 256,
            "logical_height": 128,
            "infiniburn": "#minecraft:infiniburn_nether",
            "effects": "minecraft:the_nether",
            "ambient_light": NbtFloat(0.1),
            "piglin_safe": NbtByte(1),
            "has_raids": NbtByte(0),
            "monster_spawn_light_level": 7,
            "monster_spawn_block_light_limit": 15,
            "fixed_time": NbtLong(18000),
        },
        "minecraft:the_end": {
            "has_skylight": NbtByte(0),
            "has_ceiling": NbtByte(0),
            "ultrawarm": NbtByte(0),
            "natural": NbtByte(0),
            "coordinate_scale": NbtDouble(1.0),
            "bed_works": NbtByte(0),
            "respawn_anchor_works": NbtByte(0),
            "min_y": 0,
            "height": 256,
            "logical_height": 256,
            "infiniburn": "#minecraft:infiniburn_end",
            "effects": "minecraft:the_end",
            "ambient_light": NbtFloat(0.0),
            "piglin_safe": NbtByte(0),
            "has_raids": NbtByte(1),
            "monster_spawn_light_level": 0,
            "monster_spawn_block_light_limit": 0,
            "fixed_time": NbtLong(6000),
        },
    })

    # --- 生物群系注册表 ---
    await _send_single_registry(
        conn,
        "minecraft:worldgen/biome",
        build_biome_registry_entries()
    )

    # --- 聊天类型注册表 ---
    await _send_single_registry(conn, "minecraft:chat_type", {
        "minecraft:chat": {
            "chat": {
                "translation_key": "chat.type.text",
                "parameters": ["sender", "content"],
            },
            "narration": {
                "translation_key": "chat.type.text.narrate",
                "parameters": ["sender", "content"],
            }
        },
    })

    # --- 伤害类型注册表 ---
    await _send_single_registry(
        conn,
        "minecraft:damage_type",
        _build_damage_type_registry()
    )

    # --- 画作种类注册表 (可为空但必须发送) ---
    await _send_single_registry(conn, "minecraft:painting_variant", {
        "minecraft:kebab": {
            "asset_id": "minecraft:kebab",
            "width": 1,
            "height": 1,
        },
    })

    # --- 狼变种注册表 ---
    await _send_single_registry(conn, "minecraft:wolf_variant", {
        "minecraft:pale": {
            "wild_texture": "minecraft:entity/wolf/wolf",
            "tame_texture": "minecraft:entity/wolf/wolf_tame",
            "angry_texture": "minecraft:entity/wolf/wolf_angry",
            "biomes": "minecraft:plains",
        },
    })


async def _send_single_registry(conn: Connection, registry_id: str,
                                 entries: dict):
    """
    发送单个注册表的 Registry Data 数据包 (0x07)。
    
    格式:
        - Identifier: 注册表 ID
        - VarInt: 条目数量
        - 每个条目:
            - Identifier: 条目 ID
            - Boolean: 是否有数据
            - NBT: 条目数据 (如果有)
    """
    payload = bytearray()
    payload.extend(write_identifier(registry_id))
    payload.extend(write_varint(len(entries)))

    for entry_id, entry_data in entries.items():
        payload.extend(write_identifier(entry_id))
        payload.extend(write_boolean(True))  # 有数据
        payload.extend(encode_nbt(entry_data, with_type=True))

    await conn.send_packet(0x07, bytes(payload))


async def _send_finish_configuration(conn: Connection):
    """发送 Finish Configuration 数据包 (0x03)。"""
    await conn.send_packet(0x03, b'')


async def _handle_finish_configuration(conn: Connection, server):
    """
    处理 Finish Configuration 数据包 (0x03)。
    客户端确认配置完成，进入游戏阶段。
    """
    conn.state = ConnectionState.PLAY
    logger.info(f"玩家 {conn.username} 完成配置，进入游戏")

    # 发送 Play 阶段的初始数据包
    from handlers.play import send_join_game
    await send_join_game(conn, server)
