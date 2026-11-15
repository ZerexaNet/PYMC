"""
Vanilla 1.21.1 damage rules: weapon damage and attack speed, attack-strength
scaling, critical hits, armor/toughness, protection enchantments,
difficulty scaling of mob damage and the invulnerability window.
"""

from __future__ import annotations

# --- attacks ---------------------------------------------------------------

_TIERS = ("wooden", "stone", "iron", "golden", "diamond", "netherite")

ATTACK_DAMAGE: dict[str, float] = {"minecraft:trident": 9.0, "minecraft:mace": 6.0}
ATTACK_SPEED: dict[str, float] = {"minecraft:trident": 1.1, "minecraft:mace": 0.6}
for _tier, _sword, _axe, _pick, _shovel, _axe_speed, _hoe_speed in (
        ("wooden", 4, 7, 2, 2.5, 0.8, 1.0),
        ("stone", 5, 9, 3, 3.5, 0.8, 2.0),
        ("iron", 6, 9, 4, 4.5, 0.9, 3.0),
        ("golden", 4, 7, 2, 2.5, 1.0, 1.0),
        ("diamond", 7, 9, 5, 5.5, 1.0, 4.0),
        ("netherite", 8, 10, 6, 6.5, 1.0, 4.0)):
    ATTACK_DAMAGE[f"minecraft:{_tier}_sword"] = float(_sword)
    ATTACK_DAMAGE[f"minecraft:{_tier}_axe"] = float(_axe)
    ATTACK_DAMAGE[f"minecraft:{_tier}_pickaxe"] = float(_pick)
    ATTACK_DAMAGE[f"minecraft:{_tier}_shovel"] = float(_shovel)
    ATTACK_DAMAGE[f"minecraft:{_tier}_hoe"] = 1.0
    ATTACK_SPEED[f"minecraft:{_tier}_sword"] = 1.6
    ATTACK_SPEED[f"minecraft:{_tier}_axe"] = _axe_speed
    ATTACK_SPEED[f"minecraft:{_tier}_pickaxe"] = 1.2
    ATTACK_SPEED[f"minecraft:{_tier}_shovel"] = 1.0
    ATTACK_SPEED[f"minecraft:{_tier}_hoe"] = _hoe_speed

FIST_DAMAGE = 1.0
FIST_SPEED = 4.0


def attack_strength(item_id: str | None, ticks_since_swing: float) -> float:
    """Player.getAttackStrengthScale(0.5): 0..1, full after 20/attack_speed ticks."""
    speed = ATTACK_SPEED.get(item_id or "", FIST_SPEED)
    period = 20.0 / speed
    return max(0.0, min(1.0, (ticks_since_swing + 0.5) / period))


def melee_damage(item_id: str | None, enchant_bonus: float, strength: float, critical: bool) -> float:
    """Player.attack(): base*(0.2+0.8*s^2) + enchant*s, crits x1.5."""
    base = ATTACK_DAMAGE.get(item_id or "", FIST_DAMAGE)
    damage = base * (0.2 + strength * strength * 0.8)
    if critical:
        damage *= 1.5
    return damage + enchant_bonus * strength


# --- armor -----------------------------------------------------------------

# (helmet, chestplate, leggings, boots), toughness
_ARMOR_MATERIALS = {
    "leather": ((1, 3, 2, 1), 0.0),
    "chainmail": ((2, 5, 4, 1), 0.0),
    "iron": ((2, 6, 5, 2), 0.0),
    "golden": ((2, 5, 3, 1), 0.0),
    "diamond": ((3, 8, 6, 3), 2.0),
    "netherite": ((3, 8, 6, 3), 3.0),
}
ARMOR: dict[str, tuple[int, float]] = {"minecraft:turtle_helmet": (2, 0.0)}
for _material, (_points, _toughness) in _ARMOR_MATERIALS.items():
    for _piece, _value in zip(("helmet", "chestplate", "leggings", "boots"), _points):
        ARMOR[f"minecraft:{_material}_{_piece}"] = (_value, _toughness)

# damage types (PyMC reasons) that ignore armor: #minecraft:bypasses_armor
BYPASSES_ARMOR = {"摔落", "窒息", "溺水", "燃烧", "冰冻", "饥饿", "虚空", "凋零", "魔法", "kill"}
FIRE_REASONS = {"火焰", "燃烧", "岩浆", "高温地面"}
FALL_REASONS = {"摔落"}


def _enchant(item, name: str) -> int:
    if item is None:
        return 0
    enchantments = (getattr(item, "nbt", None) or {}).get("enchantments", {}) or {}
    return int(enchantments.get(name, enchantments.get("minecraft:" + name, 0)) or 0)


def armor_totals(armor_items) -> tuple[float, float]:
    points = toughness = 0.0
    for item in armor_items:
        if item is None or getattr(item, "is_empty", True):
            continue
        value, tough = ARMOR.get(item.item_id, (0, 0.0))
        points += value
        toughness += tough
    return points, toughness


def apply_armor(damage: float, armor: float, toughness: float) -> float:
    """CombatRules.getDamageAfterAbsorb."""
    if armor <= 0:
        return damage
    f = max(armor - damage / (2.0 + toughness / 4.0), armor * 0.2)
    f = min(f, 20.0)
    return damage * (1.0 - f / 25.0)


def protection_factor(armor_items, reason: str, projectile: bool = False, explosion: bool = False) -> int:
    epf = 0
    for item in armor_items:
        epf += _enchant(item, "protection")
        if reason in FIRE_REASONS:
            epf += 2 * _enchant(item, "fire_protection")
        if reason in FALL_REASONS:
            epf += 3 * _enchant(item, "feather_falling")
        if projectile:
            epf += 2 * _enchant(item, "projectile_protection")
        if explosion:
            epf += 2 * _enchant(item, "blast_protection")
    return min(20, epf)


def scale_for_difficulty(damage: float, difficulty: str) -> float:
    """Damage from mobs scales with difficulty (Player.hurt)."""
    if difficulty == "peaceful":
        return 0.0
    if difficulty == "easy":
        return min(damage / 2.0 + 1.0, damage)
    if difficulty == "hard":
        return damage * 1.5
    return damage


def final_player_damage(amount: float, reason: str, armor_items, difficulty: str,
                        from_mob: bool, projectile: bool = False, explosion: bool = False) -> float:
    if from_mob:
        amount = scale_for_difficulty(amount, difficulty)
    if amount <= 0:
        return 0.0
    if reason not in BYPASSES_ARMOR:
        points, toughness = armor_totals(armor_items)
        amount = apply_armor(amount, points, toughness)
    epf = protection_factor(armor_items, reason, projectile, explosion)
    if epf > 0:
        amount *= 1.0 - epf / 25.0
    return max(0.0, amount)


# --- invulnerability window ------------------------------------------------

INVULNERABLE_TICKS = 20     # LivingEntity.invulnerableTime after being hurt
HURT_WINDOW = 10            # damage is ignored while invulnerableTime > 10 ...


def damage_after_invulnerability(amount: float, invulnerable_ticks: int, last_hurt: float):
    """
    (damage to apply, new last_hurt, reset_timer) following LivingEntity.hurt:
    inside the window only the part above the previous hit gets through.
    """
    if invulnerable_ticks > HURT_WINDOW:
        if amount <= last_hurt:
            return 0.0, last_hurt, False
        return amount - last_hurt, amount, False
    return amount, amount, True
