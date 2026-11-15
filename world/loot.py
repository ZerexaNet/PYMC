"""
Vanilla 1.21.1 loot tables (world/data/loot_tables.json) for block and
entity drops: pools, weighted entries, conditions and item functions with
vanilla semantics (Fortune/Looting formulas, silk touch, shears, random
chances, explosion decay, crop ages, ...).
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "loot_tables.json")

# Cooked variants for furnace_smelt (mobs killed while on fire)
_SMELT = {
    "minecraft:beef": "minecraft:cooked_beef", "minecraft:porkchop": "minecraft:cooked_porkchop",
    "minecraft:chicken": "minecraft:cooked_chicken", "minecraft:mutton": "minecraft:cooked_mutton",
    "minecraft:rabbit": "minecraft:cooked_rabbit", "minecraft:cod": "minecraft:cooked_cod",
    "minecraft:salmon": "minecraft:cooked_salmon",
}


@dataclass
class LootContext:
    tool: object | None = None             # ItemStack used to break / kill
    block_state: dict = field(default_factory=dict)
    block_name: str | None = None
    explosion_radius: float | None = None  # set when broken by an explosion
    killed_by_player: bool = False
    on_fire: bool = False                  # the killed entity was burning
    is_baby: bool = False
    rng: random.Random = field(default_factory=random.Random)


def _ns(name: str) -> str:
    return name if ":" in name else "minecraft:" + name


class LootTables:
    def __init__(self, path: str = _DATA_PATH):
        self.tables: dict = {}
        self.item_tags: dict[str, list[str]] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.tables = data.get("tables", {})
            self.item_tags = {k: set(v) for k, v in data.get("item_tags", {}).items()}
        except (OSError, ValueError):
            pass

    @property
    def loaded(self) -> bool:
        return bool(self.tables)

    def has(self, table: str) -> bool:
        return table in self.tables

    # ------------------------------------------------------------------ public

    def roll(self, table: str, ctx: LootContext) -> list[tuple[str, int]]:
        """Generate the drops of a table: [(item_id, count), ...]."""
        spec = self.tables.get(table)
        if spec is None:
            return []
        out: list[list] = []
        for pool in spec.get("pools", []):
            if not self._conditions(pool.get("conditions"), ctx):
                continue
            rolls = self._int(pool.get("rolls", 1), ctx)
            for _ in range(max(0, rolls)):
                stack = self._roll_pool(pool, ctx)
                for item in stack:
                    for fn in pool.get("functions", []):
                        item = self._function(fn, item, ctx)
                    if item is not None:
                        out.append(item)
        if spec.get("functions"):
            processed = []
            for item in out:
                for fn in spec["functions"]:
                    item = self._function(fn, item, ctx)
                    if item is None:
                        break
                if item is not None:
                    processed.append(item)
            out = processed
        return [(name, count) for name, count in out if count > 0]

    # ----------------------------------------------------------------- pools

    def _roll_pool(self, pool: dict, ctx: LootContext) -> list[list]:
        candidates: list[tuple[dict, int]] = []
        for entry in pool.get("entries", []):
            self._expand(entry, ctx, candidates)
        if not candidates:
            return []
        if len(candidates) == 1:
            chosen = candidates[0][0]
        else:
            total = sum(weight for _, weight in candidates)
            if total <= 0:
                return []
            pick = ctx.rng.randrange(total)
            for chosen, weight in candidates:
                pick -= weight
                if pick < 0:
                    break
        return self._create(chosen, ctx)

    def _expand(self, entry: dict, ctx: LootContext, out: list) -> bool:
        """Collect the leaf entries an entry contributes; False if its conditions fail."""
        if not self._conditions(entry.get("conditions"), ctx):
            return False
        kind = entry.get("type", "minecraft:item")
        if kind == "minecraft:alternatives":
            for child in entry.get("children", []):
                if self._expand(child, ctx, out):
                    return True
            return False
        if kind == "minecraft:group":
            for child in entry.get("children", []):
                self._expand(child, ctx, out)
            return True
        if kind == "minecraft:sequence":
            for child in entry.get("children", []):
                if not self._expand(child, ctx, out):
                    break
            return True
        if kind == "minecraft:tag" and entry.get("expand"):
            for item in sorted(self.item_tags.get(_ns(entry["name"]), ())):
                out.append(({"type": "minecraft:item", "name": item,
                             "functions": entry.get("functions", [])}, int(entry.get("weight", 1))))
            return True
        out.append((entry, int(entry.get("weight", 1))))
        return True

    def _create(self, entry: dict, ctx: LootContext) -> list[list]:
        kind = entry.get("type", "minecraft:item")
        if kind == "minecraft:item":
            items = [[_ns(entry["name"]), 1]]
        elif kind == "minecraft:tag":
            items = [[item, 1] for item in sorted(self.item_tags.get(_ns(entry["name"]), ()))]
        elif kind == "minecraft:loot_table":
            value = entry.get("value") or entry.get("name")
            items = [list(drop) for drop in self.roll(str(value).split(":")[-1], ctx)] if value else []
        else:  # empty, dynamic (container contents are handled by the block itself)
            return []
        result = []
        for item in items:
            for fn in entry.get("functions", []):
                item = self._function(fn, item, ctx)
                if item is None:
                    break
            if item is not None:
                result.append(item)
        return result

    # ------------------------------------------------------------ conditions

    def _conditions(self, conditions, ctx: LootContext) -> bool:
        return all(self._condition(c, ctx) for c in (conditions or ()))

    def _condition(self, cond: dict, ctx: LootContext) -> bool:
        kind = cond.get("condition", "")
        if kind == "minecraft:survives_explosion":
            radius = ctx.explosion_radius
            return radius is None or radius <= 0 or ctx.rng.random() <= 1.0 / radius
        if kind == "minecraft:block_state_property":
            for prop, want in (cond.get("properties") or {}).items():
                have = str(ctx.block_state.get(prop, ""))
                if isinstance(want, dict):
                    try:
                        value = int(have)
                    except ValueError:
                        return False
                    if "min" in want and value < int(want["min"]):
                        return False
                    if "max" in want and value > int(want["max"]):
                        return False
                elif have != str(want).lower():
                    return False
            return True
        if kind == "minecraft:match_tool":
            return self._match_tool(cond.get("predicate") or {}, ctx.tool)
        if kind == "minecraft:any_of":
            return any(self._condition(c, ctx) for c in cond.get("terms", []))
        if kind == "minecraft:all_of":
            return all(self._condition(c, ctx) for c in cond.get("terms", []))
        if kind == "minecraft:inverted":
            return not self._condition(cond.get("term", {}), ctx)
        if kind == "minecraft:table_bonus":
            chances = cond.get("chances", [0.0])
            level = self._enchant(ctx.tool, cond.get("enchantment", ""))
            return ctx.rng.random() < chances[min(level, len(chances) - 1)]
        if kind == "minecraft:random_chance":
            return ctx.rng.random() < self._float(cond.get("chance", 0.0), ctx)
        if kind == "minecraft:random_chance_with_enchanted_bonus":
            level = self._enchant(ctx.tool, cond.get("enchantment", ""))
            if level <= 0:
                chance = float(cond.get("unenchanted_chance", 0.0))
            else:
                chance = self._level_value(cond.get("enchanted_chance", 0.0), level)
            return ctx.rng.random() < chance
        if kind == "minecraft:killed_by_player":
            return ctx.killed_by_player
        if kind == "minecraft:entity_properties":
            predicate = cond.get("predicate") or {}
            flags = predicate.get("flags") or {}
            if "is_on_fire" in flags and bool(flags["is_on_fire"]) != ctx.on_fire:
                return False
            if "is_baby" in flags and bool(flags["is_baby"]) != ctx.is_baby:
                return False
            # other entity predicates (type checks of the killer, equipment, ...) are not modelled
            return not (set(predicate) - {"flags"})
        if kind in ("minecraft:damage_source_properties", "minecraft:location_check",
                    "minecraft:weather_check", "minecraft:value_check", "minecraft:time_check"):
            return False
        return True

    def _match_tool(self, predicate: dict, tool) -> bool:
        item_id = None if tool is None or getattr(tool, "is_empty", True) else tool.item_id
        items = predicate.get("items")
        if items is not None:
            if item_id is None:
                return False
            if isinstance(items, str):
                allowed = self.item_tags.get(items[1:], set()) if items.startswith("#") else {_ns(items)}
            else:
                allowed = {_ns(i) for i in items}
            if item_id not in allowed:
                return False
        enchant_preds = (predicate.get("predicates") or {}).get("minecraft:enchantments") \
            or predicate.get("enchantments") or []
        for spec in enchant_preds:
            names = spec.get("enchantments")
            names = [names] if isinstance(names, str) else (names or [])
            levels = spec.get("levels", {"min": 1})
            low = levels.get("min", 1) if isinstance(levels, dict) else int(levels)
            high = levels.get("max", 255) if isinstance(levels, dict) else int(levels)
            if not any(low <= self._enchant(tool, n) <= high for n in names):
                return False
        return True

    # -------------------------------------------------------------- functions

    def _function(self, fn: dict, item: list, ctx: LootContext):
        if not self._conditions(fn.get("conditions"), ctx):
            return item
        kind = fn.get("function", "")
        name, count = item
        if kind == "minecraft:set_count":
            value = self._int(fn.get("count", 1), ctx)
            count = count + value if fn.get("add") else value
        elif kind == "minecraft:explosion_decay":
            radius = ctx.explosion_radius
            if radius and radius > 0:
                keep = 1.0 / radius
                count = sum(1 for _ in range(count) if ctx.rng.random() <= keep)
        elif kind in ("minecraft:enchanted_count_increase", "minecraft:looting_enchant"):
            level = self._enchant(ctx.tool, fn.get("enchantment", "minecraft:looting"))
            if level > 0:
                count += round(level * self._float(fn.get("count", 1), ctx))
                limit = int(fn.get("limit", 0) or 0)
                if limit > 0:
                    count = min(count, limit)
        elif kind == "minecraft:apply_bonus":
            level = self._enchant(ctx.tool, fn.get("enchantment", ""))
            formula = fn.get("formula", "")
            params = fn.get("parameters") or {}
            if formula == "minecraft:ore_drops":
                if level > 0:
                    bonus = ctx.rng.randrange(level + 2) - 1
                    count *= max(0, bonus) + 1
            elif formula == "minecraft:uniform_bonus_count":
                if level > 0:
                    count += ctx.rng.randrange(int(params.get("bonusMultiplier", 1)) * level + 1)
            elif formula == "minecraft:binomial_with_bonus_count":
                trials = level + int(params.get("extra", 0))
                p = float(params.get("probability", 0.5))
                count += sum(1 for _ in range(trials) if ctx.rng.random() < p)
        elif kind == "minecraft:limit_count":
            limit = fn.get("limit", {})
            if isinstance(limit, (int, float)):
                count = min(count, int(limit))
            else:
                if "min" in limit:
                    count = max(count, self._int(limit["min"], ctx))
                if "max" in limit:
                    count = min(count, self._int(limit["max"], ctx))
        elif kind == "minecraft:furnace_smelt":
            name = _SMELT.get(name, name)
        return [name, max(0, int(count))]

    # --------------------------------------------------------------- numbers

    def _float(self, value, ctx: LootContext) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        kind = value.get("type", "minecraft:uniform" if "min" in value else "minecraft:constant")
        if kind == "minecraft:constant":
            return float(value.get("value", 0))
        if kind == "minecraft:uniform":
            low, high = self._float(value.get("min", 0), ctx), self._float(value.get("max", 0), ctx)
            return low + ctx.rng.random() * (high - low)
        if kind == "minecraft:binomial":
            n = self._int(value.get("n", 0), ctx)
            p = self._float(value.get("p", 0.5), ctx)
            return float(sum(1 for _ in range(n) if ctx.rng.random() < p))
        return 0.0

    def _int(self, value, ctx: LootContext) -> int:
        if isinstance(value, (int, float)):
            return int(math.floor(value))
        kind = value.get("type", "minecraft:uniform" if "min" in value else "minecraft:constant")
        if kind == "minecraft:uniform":
            low = math.floor(self._float(value.get("min", 0), ctx))
            high = math.floor(self._float(value.get("max", 0), ctx))
            return ctx.rng.randint(low, high) if high >= low else low
        return int(math.floor(self._float(value, ctx)))

    @staticmethod
    def _level_value(value, level: int) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if value.get("type") == "minecraft:linear":
            return float(value.get("base", 0)) + float(value.get("per_level_above_first", 0)) * (level - 1)
        return float(value.get("value", 0))

    @staticmethod
    def _enchant(tool, name: str) -> int:
        if tool is None or getattr(tool, "is_empty", True):
            return 0
        enchantments = (getattr(tool, "nbt", None) or {}).get("enchantments", {}) or {}
        short = name.split(":")[-1]
        return int(enchantments.get(name, enchantments.get(short, 0)) or 0)


loot_tables = LootTables()
