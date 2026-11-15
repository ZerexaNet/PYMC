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


def _held_item(conn: Connection):
    inventory = getattr(conn, "inventory_obj", None)
    if inventory is None:
        return None
    held = inventory.get_held_item_from_slot(conn.selected_hotbar_slot)
    return None if held is None or held.is_empty else held


def get_attack_damage(conn: Connection, strength: float = 1.0, critical: bool = False) -> float:
    """手持物品的近战伤害: 原版武器数值、攻击冷却蓄力、暴击与锋利加成。"""
    from world.combat_rules import melee_damage
    from world.item_properties import sharpness_damage_bonus
    held = _held_item(conn)
    bonus = sharpness_damage_bonus(held) if held is not None else 0.0
    return melee_damage(held.item_id if held is not None else None, bonus, strength, critical)


def _attack_strength_and_crit(conn: Connection) -> tuple[float, bool]:
    """Attack strength from the time since the last swing; crits need a full swing while falling."""
    from world.combat_rules import attack_strength
    now = time.monotonic()
    last = getattr(conn, "_last_attack_time", None)
    ticks = (now - last) * 20.0 if last is not None else 1000.0
    conn._last_attack_time = now
    held = _held_item(conn)
    strength = attack_strength(held.item_id if held is not None else None, ticks)
    falling = (not getattr(conn, "on_ground", True)
               and getattr(conn, "fall_start_y", conn.y) > conn.y
               and not getattr(conn, "sprinting", False))
    return strength, strength > 0.9 and falling


async def _broadcast_entity_hurt(server, entity_id: int, x: float, z: float,
                                 attacker: Connection | None = None,
                                 damage_type: str = "minecraft:player_attack",
                                 dead: bool = False):
    """Damage Event (+ 死亡时 Entity Event 3): 受击变红、音效和死亡动画。"""
    from protocol.data_types import write_varint, write_boolean, write_int, write_byte
    from protocol.gamedata import registry_index
    from protocol.packet_map import get_clientbound_packet
    type_id = registry_index("minecraft:damage_type").get(damage_type, 0)
    cause = (attacker.entity_id + 1) if attacker is not None else 0
    payload = (write_varint(entity_id) + write_varint(type_id) + write_varint(cause)
               + write_varint(cause) + write_boolean(False))
    for player in server.get_online_players():
        if player.protocol_version != 767:
            continue
        if entity_id not in player.tracked_entities and entity_id not in player.tracked_players:
            continue
        pid = get_clientbound_packet(player.protocol_version, "damage_event")
        if pid is not None:
            await player.send_packet(pid, payload)
        if dead:
            spid = get_clientbound_packet(player.protocol_version, "entity_status")
            if spid is not None:
                await player.send_packet(spid, write_int(entity_id) + write_byte(3))


def _knockback(attacker: Connection, strength: float = 0.4) -> tuple[float, float, float]:
    yaw = math.radians(attacker.yaw)
    return (-math.sin(yaw) * strength, 0.36, math.cos(yaw) * strength)


async def _handle_interact(conn: Connection, payload: bytes, server):
    """处理 Interact 包中的攻击动作 (攻击生物 / PvP)。"""
    parsed = parse_interact(payload)
    if parsed is None:
        return
    entity_id, action_type = parsed
    if action_type != INTERACT_TYPE_ATTACK:
        return
    if conn.gamemode == "spectator":
        return

    # 原版不丢弃快速攻击, 而是按蓄力程度降低伤害 (最低 20%)
    strength, critical = _attack_strength_and_crit(conn)

    # --- PvP ---
    victim = next((p for p in server.get_online_players()
                   if p.entity_id == entity_id and p is not conn), None)
    if victim is not None:
        if not server.config.get("pvp", True):
            return
        if victim.gamemode in ("creative", "spectator") or getattr(victim, "_dead", False):
            return
        dx, dy, dz = victim.x - conn.x, victim.y - conn.y, victim.z - conn.z
        if dx * dx + dy * dy + dz * dz > ATTACK_RANGE_SQUARED:
            return
        from handlers.play.join import _damage_player
        await _damage_player(victim, get_attack_damage(conn, strength, critical),
                             f"player:{conn.username}", server)
        # 击退: Set Entity Velocity 发给被攻击的玩家本人
        from protocol.data_types import write_varint, write_short
        from protocol.packet_map import get_clientbound_packet
        vx, vy, vz = _knockback(conn)
        pid = get_clientbound_packet(victim.protocol_version, "entity_velocity")
        if pid is not None and not getattr(victim, "_dead", False):
            await victim.send_packet(pid, write_varint(victim.entity_id) + b"".join(
                write_short(max(-32768, min(32767, int(v * 8000)))) for v in (vx, vy, vz)))
        if conn.gamemode in ("survival", "adventure"):
            from world.item_properties import damage_held_item
            await damage_held_item(conn, server)
        return

    entity = server.entity_manager.get_entity(entity_id)
    if entity is None or entity.kind != "mob":
        return
    if entity.distance_squared_to(conn.x, conn.y, conn.z) > ATTACK_RANGE_SQUARED:
        return

    damage = get_attack_damage(conn, strength, critical)
    health_before = entity.health
    killed = damage_mob(server, entity, damage, source=conn)
    if not killed and entity.health >= health_before:
        return  # absorbed by the invulnerability window: no hurt effect, no knockback
    await _broadcast_entity_hurt(server, entity.entity_id, entity.x, entity.z,
                                 attacker=conn, dead=killed)
    if not killed:
        vx, vy, vz = _knockback(conn)
        entity.vx, entity.vy, entity.vz = vx, vy, vz
        entity.on_ground = False

    # 生存/冒险模式下消耗武器耐久
    if conn.gamemode in ("survival", "adventure"):
        from world.item_properties import damage_held_item
        await damage_held_item(conn, server)


def damage_mob(server, entity, amount: float, source=None) -> bool:
    """
    对生物造成伤害。死亡时生成掉落物和经验球并移除实体。

    Returns:
        True 如果生物被击杀。
    """
    if entity.kind != "mob":
        return False
    from world.combat_rules import damage_after_invulnerability
    amount, last_hurt, reset = damage_after_invulnerability(
        float(amount), getattr(entity, "invulnerable_ticks", 0), getattr(entity, "last_hurt", 0.0))
    if amount <= 0:
        return False
    entity.last_hurt = last_hurt
    if reset:
        entity.invulnerable_ticks = 20
    entity.health -= float(amount)
    entity.metadata["health"] = entity.health
    if entity.health > 0:
        return False

    profile = getattr(entity, "profile", {})

    # 掉落物: 原版生物战利品表 (抢夺附魔、仅玩家击杀掉落等), 没有表时用旧配置
    from world.loot import LootContext, loot_tables
    table = "entities/" + str(getattr(entity, "mob_type", "")).split(":")[-1]
    killer = source if source is not None and hasattr(source, "inventory_obj") else None
    if loot_tables.has(table):
        tool = None
        if killer is not None:
            held = killer.inventory_obj.get_held_item_from_slot(killer.selected_hotbar_slot)
            tool = None if held is None or held.is_empty else held
        ctx = LootContext(tool=tool, killed_by_player=killer is not None,
                          on_fire=getattr(entity, "fire_ticks", 0) > 0)
        if table == "entities/sheep" and not getattr(entity, "sheared", False):
            # a sheep's colour table (wool) includes the base sheep table (mutton)
            table = f"entities/sheep/{getattr(entity, 'color', 'white')}"
        drops = loot_tables.roll(table, ctx)
    else:
        drops = [(name, _rng.randint(lo, hi)) for name, lo, hi in profile.get("drops", [])]
    for item_name, count in drops:
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
    logger.debug(
        f"生物 {entity.metadata.get('mob_type', '?')} (id={entity.entity_id}) "
        f"被击杀, 掉落已生成"
    )
    return True
