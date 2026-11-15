#!/usr/bin/env python3
"""
Generate world/data/recipes.json: the vanilla Minecraft 1.21.1 crafting
recipes with every item tag resolved to concrete items.

Source: misode/mcmeta, branch ``1.21.1-summary`` (the vanilla data pack
recipes and item tags, one JSON file each).

    python3 tools/gen_recipe_data.py [cache_dir]

Output format:
    {"shaped":    [{"id", "pattern": [...], "key": {char: [items]}, "result": [item, count]}],
     "shapeless": [{"id", "ingredients": [[items], ...], "result": [item, count]}]}
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = "https://raw.githubusercontent.com/misode/mcmeta/1.21.1-summary/data/"
FILES = {"recipes": "recipe/data.min.json", "tags": "tag/item/data.min.json"}


def fetch(cache: Path, name: str) -> dict:
    path = cache / f"{name}.json"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SUMMARY + FILES[name], timeout=120) as response:
            path.write_bytes(response.read())
    return json.loads(path.read_text(encoding="utf-8"))


def ns(name: str) -> str:
    return name if ":" in name else "minecraft:" + name


class Tags:
    def __init__(self, raw: dict):
        self.raw = {ns(k): v for k, v in raw.items()}
        self.cache: dict[str, list[str]] = {}

    def items(self, tag: str, seen: frozenset = frozenset()) -> list[str]:
        tag = ns(tag)
        if tag in self.cache:
            return self.cache[tag]
        out: list[str] = []
        for value in self.raw.get(tag, {}).get("values", []):
            if isinstance(value, dict):
                value = value.get("id", "")
            if value.startswith("#"):
                if value[1:] not in seen:
                    out.extend(self.items(value[1:], seen | {tag}))
            else:
                out.append(ns(value))
        self.cache[tag] = list(dict.fromkeys(out))
        return self.cache[tag]


def ingredient(value, tags: Tags) -> list[str]:
    """An ingredient (item, tag, or a list of either) -> concrete item ids."""
    if isinstance(value, list):
        out: list[str] = []
        for part in value:
            out.extend(ingredient(part, tags))
        return list(dict.fromkeys(out))
    if isinstance(value, str):
        return tags.items(value[1:]) if value.startswith("#") else [ns(value)]
    if "item" in value:
        return [ns(value["item"])]
    if "tag" in value:
        return tags.items(value["tag"])
    return []


def result_of(recipe: dict):
    result = recipe["result"]
    if isinstance(result, str):
        return [ns(result), 1]
    return [ns(result.get("id") or result.get("item")), int(result.get("count", 1))]


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "recipe-cache"
    recipes = fetch(cache, "recipes")
    tags = Tags(fetch(cache, "tags"))
    shaped, shapeless = [], []
    for rid, recipe in sorted(recipes.items()):
        kind = recipe.get("type", "")
        if kind == "minecraft:crafting_shaped":
            key = {ch: ingredient(v, tags) for ch, v in recipe["key"].items()}
            if any(not items for items in key.values()):
                continue
            shaped.append({"id": ns(rid), "pattern": recipe["pattern"], "key": key,
                           "result": result_of(recipe)})
        elif kind == "minecraft:crafting_shapeless":
            ingredients = [ingredient(v, tags) for v in recipe["ingredients"]]
            if not ingredients or any(not items for items in ingredients):
                continue
            shapeless.append({"id": ns(rid), "ingredients": ingredients, "result": result_of(recipe)})
    out = {"version": "1.21.1", "shaped": shaped, "shapeless": shapeless}
    target = ROOT / "world" / "data" / "recipes.json"
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size // 1024} KiB): "
          f"{len(shaped)} shaped, {len(shapeless)} shapeless recipes")


if __name__ == "__main__":
    main()
