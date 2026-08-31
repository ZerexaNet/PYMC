import unittest
from types import SimpleNamespace

from world.inventory import ItemStack
from world.item_properties import (
    MAX_DURABILITY,
    add_enchantment,
    damage_item,
    get_enchantment_level,
    get_max_durability,
    sharpness_damage_bonus,
)


class DurabilityTableTests(unittest.TestCase):
    def test_tier_values(self):
        self.assertEqual(get_max_durability("minecraft:wooden_pickaxe"), 59)
        self.assertEqual(get_max_durability("minecraft:stone_sword"), 131)
        self.assertEqual(get_max_durability("minecraft:iron_axe"), 250)
        self.assertEqual(get_max_durability("minecraft:diamond_shovel"), 1561)
        self.assertEqual(get_max_durability("minecraft:netherite_sword"), 2031)

    def test_non_tool_has_no_durability(self):
        self.assertEqual(get_max_durability("minecraft:stone"), 0)
        self.assertEqual(get_max_durability("minecraft:apple"), 0)


class EnchantmentStorageTests(unittest.TestCase):
    def test_add_and_read(self):
        item = ItemStack("minecraft:iron_sword", 1)
        add_enchantment(item, "sharpness", 3)
        self.assertEqual(get_enchantment_level(item, "sharpness"), 3)
        self.assertEqual(get_enchantment_level(item, "unbreaking"), 0)

    def test_level_clamped(self):
        item = ItemStack("minecraft:iron_sword", 1)
        add_enchantment(item, "sharpness", 999)
        self.assertEqual(get_enchantment_level(item, "sharpness"), 255)

    def test_sharpness_bonus(self):
        item = ItemStack("minecraft:iron_sword", 1)
        self.assertEqual(sharpness_damage_bonus(item), 0.0)
        add_enchantment(item, "sharpness", 2)
        self.assertEqual(sharpness_damage_bonus(item), 1.5)


class DamageItemTests(unittest.TestCase):
    def test_durability_consumed_until_break(self):
        item = ItemStack("minecraft:wooden_sword", 1)
        for _ in range(58):
            self.assertFalse(damage_item(item))
        self.assertTrue(damage_item(item))  # 第 59 次损毁

    def test_non_tool_never_breaks(self):
        item = ItemStack("minecraft:stone", 64)
        self.assertFalse(damage_item(item, 100))

    def test_unbreaking_extends_life(self):
        # unbreaking 3: 每次仅 1/4 概率消耗, 59 次攻击几乎不可能耗尽 59 点耐久
        item = ItemStack("minecraft:wooden_sword", 1)
        add_enchantment(item, "unbreaking", 3)
        broke = any(damage_item(item) for _ in range(59))
        self.assertFalse(broke)
        self.assertLess(item.damage, 59)


if __name__ == "__main__":
    unittest.main()
