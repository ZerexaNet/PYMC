"""Block collision classes derived from blocks.json (shared by mobs, spawning, physics)."""

from __future__ import annotations

import json
from functools import lru_cache


@lru_cache(maxsize=1)
def no_collision_states() -> frozenset[int]:
    """States an entity can walk through: air, plants, torches, fluids, fire, ..."""
    from .chunk_io import _find_blocks_json
    ids: set[int] = set()
    with open(_find_blocks_json(), "r", encoding="utf-8") as f:
        for block in json.load(f):
            name = block["name"]
            # a single snow layer has no collision box in vanilla; powder snow is walkable-into
            if block.get("boundingBox") == "empty" or name in ("powder_snow",):
                ids.update(range(block["minStateId"], block["maxStateId"] + 1))
            elif name == "snow":
                ids.add(block["minStateId"])  # layers=1
    return frozenset(ids)
