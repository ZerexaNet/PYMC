"""
Potion registry ids (minecraft:potion, a static registry of the 1.21.1 client).

The id of a potion is its index in world/data/potions.json, the registration order of the
registry. Potion contents (the potion's name) travel in the potion_contents item component.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "potions.json"


@lru_cache(maxsize=1)
def _names() -> tuple[str, ...]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return tuple(json.load(f)["names"])


def protocol_id(name: str) -> int | None:
    """Registry id of a potion (``awkward``, ``minecraft:long_swiftness``, ...)."""
    short = name.split(":", 1)[-1]
    names = _names()
    return names.index(short) if short in names else None


def name_of_protocol_id(index: int) -> str | None:
    names = _names()
    return names[index] if 0 <= index < len(names) else None
