#!/usr/bin/env python3
"""Regenerate protocol/data/*.json for Minecraft Java 1.21.1 (protocol 767).

Inputs (not vendored, fetch them first):

  * PrismarineJS minecraft-data   (npm i minecraft-data)
      data/pc/1.21.1/{loginPacket,items,language,protocol}.json
      data/pc/1.20.5/entities.json
  * misode/mcmeta, branch ``1.21.1-summary``
      commands/data.min.json
      data/tag/<registry>/data.min.json

Usage:
    python tools/gen_protocol_data.py <minecraft-data/data/pc> <mcmeta-summary-dir>

``<mcmeta-summary-dir>`` holds the mcmeta files with ``/`` replaced by ``_``
(e.g. ``data_tag_block_data.min.json``) or in their original layout.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "protocol" / "data"

# Registries the vanilla server synchronises during configuration.
SYNCED_REGISTRIES = [
    "minecraft:worldgen/biome", "minecraft:chat_type", "minecraft:trim_pattern",
    "minecraft:trim_material", "minecraft:wolf_variant", "minecraft:painting_variant",
    "minecraft:dimension_type", "minecraft:damage_type", "minecraft:banner_pattern",
    "minecraft:enchantment", "minecraft:jukebox_song",
]

# Tag registries sent in Update Tags. Static registries are resolved to numeric
# protocol IDs here; data-driven ones keep names (IDs depend on send order).
STATIC_TAGS = ["block", "item", "fluid", "entity_type"]
DYNAMIC_TAGS = ["worldgen/biome", "enchantment", "damage_type",
                "banner_pattern", "painting_variant"]

FLUID_IDS = {"minecraft:empty": 0, "minecraft:flowing_water": 1, "minecraft:water": 2,
             "minecraft:flowing_lava": 3, "minecraft:lava": 4}

LANG_PREFIXES = (
    "multiplayer.", "death.", "commands.", "command.", "chat.", "gameMode.",
    "argument.", "disconnect.", "entity.minecraft.", "gamerule.",
    "options.difficulty.", "parsing.", "permissions.", "sleep.", "block.minecraft.bed",
    "block.minecraft.spawn", "block.minecraft.set_spawn", "container.", "effect.minecraft.",
    "enchantment.minecraft.", "advancements.", "chat_screen.", "connect.",
)


def dump(name: str, obj) -> None:
    path = OUT / name
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {path.name}: {path.stat().st_size // 1024} KiB")


def load_mcmeta(root: Path, rel: str):
    for cand in (root / rel, root / rel.replace("/", "_")):
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8"))
    raise FileNotFoundError(rel)


def flatten_tags(raw: dict) -> dict:
    """Resolve '#tag' references; returns {tag: [entry, ...]} with namespaced ids."""
    def ns(v: str) -> str:
        return v if ":" in v else "minecraft:" + v

    resolved: dict = {}

    def resolve(tag: str, stack=()):
        if tag in resolved:
            return resolved[tag]
        out = []
        for value in raw[tag]["values"]:
            if isinstance(value, dict):
                value = value["id"]
            if value.startswith("#"):
                ref = value[1:].split(":", 1)[-1]
                if ref in stack or ref not in raw:
                    continue
                out.extend(resolve(ref, stack + (tag,)))
            else:
                out.append(ns(value))
        seen = set()
        resolved[tag] = [v for v in out if not (v in seen or seen.add(v))]
        return resolved[tag]

    for tag in raw:
        resolve(tag)
    return {"minecraft:" + k: v for k, v in sorted(resolved.items())}


def main():
    md = Path(sys.argv[1])
    mcmeta = Path(sys.argv[2])
    OUT.mkdir(parents=True, exist_ok=True)

    # --- registries ---
    codec = json.loads((md / "1.21.1/loginPacket.json").read_text())["dimensionCodec"]
    registries = {}
    for reg in SYNCED_REGISTRIES:
        registries[reg] = {e["key"]: e["value"] for e in codec[reg]["entries"]}
    dump("registries_767.json", registries)

    # --- items / entity types ---
    items = json.loads((md / "1.21.1/items.json").read_text())
    assert [i["id"] for i in items] == list(range(len(items)))
    dump("items_767.json", {
        "names": [i["name"] for i in items],
        "stack_sizes": {i["name"]: i["stackSize"] for i in items if i["stackSize"] != 64},
        "durability": {i["name"]: i["maxDurability"] for i in items if i.get("maxDurability")},
    })
    item_ids = {"minecraft:" + i["name"]: i["id"] for i in items}

    entities = json.loads((md / "1.20.5/entities.json").read_text())
    assert [e["id"] for e in entities] == list(range(len(entities)))
    dump("entity_types_767.json", [e["name"] for e in entities])
    entity_ids = {"minecraft:" + e["name"]: e["id"] for e in entities}

    blocks = json.loads((md / "1.21.1/blocks.json").read_text())
    block_ids = {"minecraft:" + b["name"]: b["id"] for b in blocks}

    # --- tags ---
    id_maps = {"block": block_ids, "item": item_ids, "fluid": FLUID_IDS, "entity_type": entity_ids}
    tags = {}
    for reg in STATIC_TAGS:
        flat = flatten_tags(load_mcmeta(mcmeta, f"data/tag/{reg}/data.min.json"))
        tags["minecraft:" + reg] = {t: [id_maps[reg][v] for v in vals] for t, vals in flat.items()}
    for reg in DYNAMIC_TAGS:
        tags["minecraft:" + reg] = flatten_tags(load_mcmeta(mcmeta, f"data/tag/{reg}/data.min.json"))
    dump("tags_767.json", tags)

    # --- commands ---
    tree = load_mcmeta(mcmeta, "commands/data.min.json")
    proto = json.loads((md / "1.21.1/protocol.json").read_text())
    parsers = None

    def find_parsers(node):
        nonlocal parsers
        if parsers is not None:
            return
        if isinstance(node, list):
            if (len(node) == 2 and node[0] == "mapper" and isinstance(node[1], dict)
                    and "brigadier:bool" in node[1].get("mappings", {}).values()):
                parsers = {v: int(k) for k, v in node[1]["mappings"].items()}
                return
            for child in node:
                find_parsers(child)
        elif isinstance(node, dict):
            for child in node.values():
                find_parsers(child)

    find_parsers(proto)
    assert parsers, "parser id table not found"
    dump("commands_767.json", {"parsers": parsers, "tree": tree})

    # --- language subset (console rendering of translatable components) ---
    lang = json.loads((md / "1.21.1/language.json").read_text())
    dump("lang_en_us.json", {k: v for k, v in sorted(lang.items()) if k.startswith(LANG_PREFIXES)})


if __name__ == "__main__":
    main()
