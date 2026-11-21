"""
Generate world/data/enchantments.json from the 1.21.1 data the server already ships
(protocol/data/registries_767.json, tags_767.json, items_767.json).

Each enchantment keeps its registry order (= the numeric id the client assigns), its
cost formulas (cost(level) = base + per_level_above_first * (level - 1)), weight, anvil
cost, the item tags that accept it, and its exclusive set.

Usage: python3 tools/gen_enchantment_data.py
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "protocol" / "data"
OUT = Path(__file__).resolve().parent.parent / "world" / "data" / "enchantments.json"


def _value(node):
    return node["value"] if isinstance(node, dict) and "value" in node else node


def main():
    registry = json.loads((DATA / "registries_767.json").read_text(encoding="utf-8"))["minecraft:enchantment"]
    tags = json.loads((DATA / "tags_767.json").read_text(encoding="utf-8"))
    items = json.loads((DATA / "items_767.json").read_text(encoding="utf-8"))["names"]
    ench_tags = tags["minecraft:enchantment"]
    item_tags = tags["minecraft:item"]
    names = [key.split(":", 1)[1] for key in registry]

    def tag_items(ref: str) -> list[str]:
        tag = ref.lstrip("#")
        return [items[i].split(":")[-1] if ":" in items[i] else items[i] for i in item_tags.get(tag, [])]

    def tag_enchants(ref: str) -> list[str]:
        return [e.split(":", 1)[-1] for e in ench_tags.get(ref.lstrip("#"), [])]

    def cost(node):
        value = _value(node)
        return [int(value["base"]["value"]), int(value["per_level_above_first"]["value"])]

    out = []
    for index, (key, entry) in enumerate(registry.items()):
        v = _value(entry)
        name = key.split(":", 1)[1]
        supported = _value(v["supported_items"])
        primary = _value(v.get("primary_items", v["supported_items"]))
        exclusive = _value(v["exclusive_set"]) if "exclusive_set" in v else None
        out.append({
            "id": index,
            "name": name,
            "max_level": int(_value(v["max_level"])),
            "min_cost": cost(v["min_cost"]),
            "max_cost": cost(v["max_cost"]),
            "weight": int(_value(v["weight"])),
            "anvil_cost": int(_value(v["anvil_cost"])),
            "supported": tag_items(supported),
            "primary": tag_items(primary),
            "exclusive": tag_enchants(exclusive) if exclusive else [],
            "treasure": name in tag_enchants("#minecraft:treasure"),
            "curse": name in tag_enchants("#minecraft:curse"),
            "tradeable": name in tag_enchants("#minecraft:tradeable"),
            "in_enchanting_table": name in tag_enchants("#minecraft:in_enchanting_table"),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} enchantments to {OUT}")


if __name__ == "__main__":
    main()
