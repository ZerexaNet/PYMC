# ============================================================
# PyMC - 物品属性: 耐久与附魔
# ============================================================

"""
工具/武器/装备的耐久度与附魔效果。

- MAX_DURABILITY: 各类可损耗物品的最大耐久
- damage_held_item: 消耗手持物品耐久, 耐久耗尽时损毁
- 附魔存储在 ItemStack.nbt["enchantments"] = {name: level}
- 已接入效果:
  - sharpness (锋利): 攻击伤害 +0.5*level + 0.5
  - unbreaking (耐久): 1/(level+1) 概率才消耗耐久
"""

import logging
import random

logger = logging.getLogger("PyMC.物品")

_rng = random.Random()

# --- 工具/武器最大耐久 (Java 版数值) ---
_TIER_DURABILITY = {
    "wooden": 59, "golden": 32, "stone": 131,
    "iron": 250, "diamond": 1561, "netherite": 2031,
}
_TOOL_KINDS = ("sword", "pickaxe", "axe", "shovel", "hoe")

MAX_DURABILITY: dict[str, int] = {
    f"minecraft:{tier}_{kind}": durability
    for tier, durability in _TIER_DURABILITY.items()
    for kind in _TOOL_KINDS
}
MAX_DURABILITY.update({
    "minecraft:bow": 384, "minecraft:crossbow": 465,
    "minecraft:trident": 250, "minecraft:mace": 500,
    "minecraft:shears": 238, "minecraft:shield": 336,
    "minecraft:flint_and_steel": 64, "minecraft:fishing_rod": 64,
    "minecraft:elytra": 432,
    # 盔甲 (头盔/胸甲/护腿/靴子)
    "minecraft:leather_helmet": 55, "minecraft:leather_chestplate": 80,
    "minecraft:leather_leggings": 75, "minecraft:leather_boots": 65,
    "minecraft:golden_helmet": 77, "minecraft:golden_chestplate": 112,
    "minecraft:golden_leggings": 105, "minecraft:golden_boots": 91,
    "minecraft:chainmail_helmet": 165, "minecraft:chainmail_chestplate": 240,
    "minecraft:chainmail_leggings": 225, "minecraft:chainmail_boots": 195,
    "minecraft:iron_helmet": 165, "minecraft:iron_chestplate": 240,
    "minecraft:iron_leggings": 225, "minecraft:iron_boots": 195,
    "minecraft:diamond_helmet": 363, "minecraft:diamond_chestplate": 528,
    "minecraft:diamond_leggings": 495, "minecraft:diamond_boots": 429,
    "minecraft:netherite_helmet": 407, "minecraft:netherite_chestplate": 592,
    "minecraft:netherite_leggings": 555, "minecraft:netherite_boots": 481,
    "minecraft:turtle_helmet": 275,
})


def get_max_durability(item_id: str) -> int:
    """物品最大耐久, 不可损耗物品返回 0。"""
    return MAX_DURABILITY.get(item_id, 0)


def get_enchantment_level(item, name: str) -> int:
    """读取物品附魔等级, 无该附魔返回 0。"""
    if item is None:
        return 0
    enchantments = item.nbt.get("enchantments", {})
    return int(enchantments.get(name, 0))


def add_enchantment(item, name: str, level: int):
    """给物品添加附魔 (存储在 NBT 中)。"""
    if "enchantments" not in item.nbt:
        item.nbt["enchantments"] = {}
    item.nbt["enchantments"][name] = max(1, min(255, int(level)))


def sharpness_damage_bonus(item) -> float:
    """锋利附魔的攻击伤害加成 (Java 1.9+: 0.5*level + 0.5)。"""
    level = get_enchantment_level(item, "sharpness")
    return 0.5 * level + 0.5 if level > 0 else 0.0


def damage_item(item, amount: int = 1) -> bool:
    """
    消耗物品耐久 (应用耐久附魔)。

    Returns:
        True 如果物品损毁。
    """
    max_durability = get_max_durability(item.item_id)
    if max_durability <= 0:
        return False

    unbreaking = get_enchantment_level(item, "unbreaking")
    for _ in range(max(1, amount)):
        if unbreaking > 0 and _rng.random() > 1.0 / (unbreaking + 1):
            continue  # 耐久附魔: 本次不消耗
        item.damage += 1

    if item.damage >= max_durability:
        return True
    return False


async def damage_held_item(conn, server, amount: int = 1) -> bool:
    """
    消耗玩家手持物品的耐久。损毁时清空槽位并同步物品栏。

    Returns:
        True 如果物品损毁。
    """
    inventory = getattr(conn, "inventory_obj", None)
    if inventory is None:
        return False
    slot = conn.selected_hotbar_slot
    item = inventory.get_slot(slot)
    if item is None or item.is_empty:
        return False

    if not damage_item(item, amount):
        return False

    # 物品损毁
    inventory.set_slot(slot, None)
    logger.info(f"{conn.username} 的 {item.item_id} 已损毁")
    from handlers.play.chat import send_system_message
    await send_system_message(conn, f"[PyMC] 你的 {item.item_id} 已损毁")
    from world.inventory import send_inventory_sync
    await send_inventory_sync(conn)
    return True
