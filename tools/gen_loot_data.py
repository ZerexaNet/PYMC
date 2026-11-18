#!/usr/bin/env python3
"""
Generate world/data/loot_tables.json: the vanilla Minecraft 1.21.1 block and
entity loot tables, plus the item tags they reference.

Source: misode/mcmeta, branch ``1.21.1-summary``.

    python3 tools/gen_loot_data.py [cache_dir]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = "https://raw.githubusercontent.com/misode/mcmeta/1.21.1-summary/data/"
FILES = {"loot": "loot_table/data.min.json", "tags": "tag/item/data.min.json"}


def fetch(cache: Path, name: str) -> dict:
    path = cache / f"{name}.json"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SUMMARY + FILES[name], timeout=120) as response:
            path.write_bytes(response.read())
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_tags(raw: dict) -> dict[str, list[str]]:
    raw = {(k if ":" in k else "minecraft:" + k): v for k, v in raw.items()}
    done: dict[str, list[str]] = {}

    def items(tag: str, seen=()):
        if tag in done:
            return done[tag]
        out = []
        for value in raw.get(tag, {}).get("values", []):
            value = value.get("id", "") if isinstance(value, dict) else value
            if value.startswith("#"):
                if value[1:] not in seen:
                    out.extend(items(value[1:], seen + (tag,)))
            else:
                out.append(value if ":" in value else "minecraft:" + value)
        done[tag] = list(dict.fromkeys(out))
        return done[tag]

    for tag in raw:
        items(tag)
    return done


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "recipe-cache"
    loot = fetch(cache, "loot")
    tables = {k: v for k, v in loot.items() if k.startswith(("blocks/", "entities/"))}
    out = {"version": "1.21.1", "tables": tables, "item_tags": resolve_tags(fetch(cache, "tags"))}
    target = ROOT / "world" / "data" / "loot_tables.json"
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size // 1024} KiB): {len(tables)} loot tables")


if __name__ == "__main__":
    main()
