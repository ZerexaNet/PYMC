# ============================================================
# PyMC - 战斗系统
# 玩家攻击生物、生物死亡掉落与经验
# ============================================================

"""
战斗处理。

包括:
  - _handle_interact: 处理 Interact (serverbound 0x14) 攻击动作
  - damage_mob: 对生物造成伤害, 死亡时生成掉落物和经验球
  - WEAPON_DAMAGE: 手持武器伤害表

Interact 包格式 (1.21.1):
  Entity ID (VarInt), Type (VarInt: 0=interact, 1=attack, 2=interact_at),
  [type=2: target XYZ float x3], [type!=1: hand VarInt], sneaking (bool)
"""

import logging
import math
import random
import time

from protocol.data_types import read_varint
from network.connection import Connection

logger = logging.getLogger("PyMC.战斗")

INTERACT_TYPE_INTERACT = 0
INTERACT_TYPE_ATTACK = 1
INTERACT_TYPE_INTERACT_AT = 2

# 攻击判定距离 (平方), 比原版 3 格略宽松
ATTACK_RANGE_SQUARED = 16.0
# 攻击冷却 (秒), 防止客户端高频攻击包刷伤害
ATTACK_COOLDOWN_SECONDS = 0.4

# 手持武器伤害 (空手 = 1.0)
WEAPON_DAMAGE = {
    "minecraft:wooden_sword": 4.0, "minecraft:golden_sword": 4.0,
    "minecraft:stone_sword": 5.0, "minecraft:iron_sword": 6.0,
    "minecraft:diamond_sword": 7.0, "minecraft:netherite_sword": 8.0,
    "minecraft:wooden_axe": 7.0, "minecraft:golden_axe": 7.0,
    "minecraft:stone_axe": 9.0, "minecraft:iron_axe": 9.0,
    "minecraft:diamond_axe": 9.0, "minecraft:netherite_axe": 10.0,
    "minecraft:trident": 9.0, "minecraft:mace": 6.0,
}

_rng = random.Random()


def parse_interact(payload: bytes) -> tuple[int, int] | None:
    """解析 Interact 包, 返回 (entity_id, action_type)。"""
    try:
        entity_id, offset = read_varint(payload, 0)
        action_type, _ = read_varint(payload, offset)
        return entity_id, action_type
    except (IndexError, ValueError):
        return None


def get_attack_damage(conn: Connection) -> float:
    """根据手持物品计算攻击伤害 (含锋利附魔加成)。"""
    from world.item_properties import sharpness_damage_bonus
    inventory = getattr(conn, "inventory_obj", None)
    if inventory is not None:
        held = inventory.get_held_item_from_slot(conn.selected_hotbar_slot)
        if held is not None and not held.is_empty:
            base = WEAPON_DAMAGE.get(held.item_id, 1.0)
            return base + sharpness_damage_bonus(held)
    return 1.0


async def _handle_interact(conn: Connection, payload: bytes, server):
    """处理 Interact 包中的攻击动作。"""
    parsed = parse_interact(payload)
    if parsed is None:
        return
    entity_id, action_type = parsed
    if action_type != INTERACT_TYPE_ATTACK:
        return

    # 攻击冷却
    now = time.monotonic()
    last_attack = getattr(conn, "_last_attack_time", 0.0)
    if now - last_attack < ATTACK_COOLDOWN_SECONDS:
        return
    conn._last_attack_time = now

    entity = server.entity_manager.get_entity(entity_id)
    if entity is None or entity.kind != "mob":
        return
    if entity.distance_squared_to(conn.x, conn.y, conn.z) > ATTACK_RANGE_SQUARED:
        return

    damage = get_attack_damage(conn)
    killed = damage_mob(server, entity, damage, source=conn)

    # 生存/冒险模式下消耗武器耐久
    if conn.gamemode in ("survival", "adventure"):
        from world.item_properties import damage_held_item
        await damage_held_item(conn, server)

    if killed:
        from handlers.play.chat import send_system_message
        mob_name = entity.metadata.get("mob_type", "生物")
        await send_system_message(conn, f"[PyMC] 你击杀了 {mob_name}")


def damage_mob(server, entity, amount: float, source=None) -> bool:
    """
    对生物造成伤害。死亡时生成掉落物和经验球并移除实体。

    Returns:
        True 如果生物被击杀。
    """
    if entity.kind != "mob":
        return False
    entity.health -= float(amount)
    entity.metadata["health"] = entity.health
    if entity.health > 0:
        return False

    profile = getattr(entity, "profile", {})

    # 掉落物
    for drop in profile.get("drops", []):
        item_name, min_count, max_count = drop
        count = _rng.randint(min_count, max_count)
        if count <= 0:
            continue
        item = server.entity_manager.create_item(
            entity.x, entity.y + 0.3, entity.z, item_name, count)
        item.pickup_delay = 10  # 0.5s 拾取延迟, 避免死亡瞬间被吸走

    # 经验球
    xp_range = profile.get("xp", (0, 0))
    xp = _rng.randint(xp_range[0], xp_range[1]) if xp_range else 0
    if xp > 0:
        server.entity_manager.create_experience_orb(
            entity.x, entity.y + 0.3, entity.z, xp)

    server.entity_manager.remove_entity(entity.entity_id)
    logger.info(
        f"生物 {entity.metadata.get('mob_type', '?')} (id={entity.entity_id}) "
        f"被击杀, 掉落已生成"
    )
    return True
