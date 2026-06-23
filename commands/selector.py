# ============================================================
# PyMC - Entity Selector System
# Parse and resolve vanilla entity selectors (@a, @p, @e, @s, @r)
# ============================================================

"""
Full vanilla entity selector syntax:

@a - All players
@p - Nearest player
@e - All entities
@s - Self (executing entity)
@r - Random player

With arguments:
@a[distance=..10, gamemode=creative, name=Steve, tag=admin, x=100, y=64, z=200, dx=10, dy=5, dz=10, sort=nearest, limit=5]
@e[type=zombie, distance=5..20]
"""

from __future__ import annotations

import math
import random
import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("PyMC.选择器")


@dataclass
class SelectorArgs:
    """Parsed selector arguments."""
    # Position
    x: float | None = None
    y: float | None = None
    z: float | None = None
    # Volume
    dx: float | None = None
    dy: float | None = None
    dz: float | None = None
    # Distance
    distance_min: float | None = None
    distance_max: float | None = None
    # Entity type
    type_name: str | None = None
    type_negate: bool = False
    # Player-specific
    gamemode: str | None = None
    gamemode_negate: bool = False
    name: str | None = None
    name_negate: bool = False
    # Tags
    tags: list[str] = field(default_factory=list)
    tags_negated: list[str] = field(default_factory=list)
    # Sorting and limit
    sort: str = "nearest"  # nearest, furthest, random, arbitrary
    limit: int | None = None
    # Level
    level_min: int | None = None
    level_max: int | None = None
    # Horizontal rotation
    y_rotation_min: float | None = None
    y_rotation_max: float | None = None
    # Vertical rotation
    x_rotation_min: float | None = None
    x_rotation_max: float | None = None
    # Predicate
    predicate: str | None = None
    # NBT
    nbt: str | None = None
    # Scores
    scores: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    # Advancements (not fully supported)
    advancements: dict[str, bool] = field(default_factory=dict)


def parse_int_range(value: str) -> tuple[int | None, int | None]:
    """Parse an integer range like '5..10', '..10', '5..', '5'."""
    if ".." in value:
        parts = value.split("..", 1)
        min_val = int(parts[0]) if parts[0] else None
        max_val = int(parts[1]) if parts[1] else None
        return (min_val, max_val)
    v = int(value)
    return (v, v)


def parse_float_range(value: str) -> tuple[float | None, float | None]:
    """Parse a float range like '5.0..10.0', '..10', '5..', '5.0'."""
    if ".." in value:
        parts = value.split("..", 1)
        min_val = float(parts[0]) if parts[0] else None
        max_val = float(parts[1]) if parts[1] else None
        return (min_val, max_val)
    v = float(value)
    return (v, v)


def parse_selector(selector_str: str) -> tuple[str, SelectorArgs | None]:
    """
    Parse a selector string like '@a[distance=..10,gamemode=creative]'.

    Returns:
        (selector_type, SelectorArgs) or (raw_name, None) if not a selector
    """
    match = re.match(r'^(@[apers])(\[.*\])?$', selector_str.strip())
    if not match:
        return (selector_str, None)

    selector_type = match.group(1)
    args_str = match.group(2)

    if args_str is None:
        return (selector_type, SelectorArgs())

    # Parse bracket content
    args_content = args_str[1:-1].strip()
    if not args_content:
        return (selector_type, SelectorArgs())

    args = SelectorArgs()

    # Split by comma, respecting nested brackets
    parts = _split_selector_args(args_content)

    for part in parts:
        part = part.strip()
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()

        # Handle negation prefix
        negate = key.startswith("!")
        if negate:
            key = key[1:]

        try:
            _apply_selector_arg(args, key, value, negate)
        except Exception as e:
            logger.debug(f"Selector arg parse error: {key}={value}: {e}")

    return (selector_type, args)


def _split_selector_args(content: str) -> list[str]:
    """Split selector arguments by comma, respecting brackets and quotes."""
    parts = []
    current = []
    depth = 0
    in_quotes = False

    for ch in content:
        if ch == '"' and depth == 0:
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == '[' and not in_quotes:
            depth += 1
            current.append(ch)
        elif ch == ']' and not in_quotes:
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0 and not in_quotes:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append(''.join(current))

    return parts


def _apply_selector_arg(args: SelectorArgs, key: str, value: str, negate: bool):
    """Apply a single selector argument."""
    if key == "x":
        args.x = float(value)
    elif key == "y":
        args.y = float(value)
    elif key == "z":
        args.z = float(value)
    elif key == "dx":
        args.dx = float(value)
    elif key == "dy":
        args.dy = float(value)
    elif key == "dz":
        args.dz = float(value)
    elif key == "distance":
        args.distance_min, args.distance_max = parse_float_range(value)
    elif key == "type":
        args.type_name = value if ":" in value else f"minecraft:{value}"
        args.type_negate = negate
    elif key == "gamemode":
        gm = value.lower()
        if gm in ("survival", "creative", "adventure", "spectator", "0", "1", "2", "3"):
            mode_map = {"0": "survival", "1": "creative", "2": "adventure", "3": "spectator"}
            args.gamemode = mode_map.get(gm, gm)
            args.gamemode_negate = negate
    elif key == "name":
        args.name = value.strip('"')
        args.name_negate = negate
    elif key == "tag":
        if negate:
            args.tags_negated.append(value)
        else:
            args.tags.append(value)
    elif key == "sort":
        if value in ("nearest", "furthest", "random", "arbitrary"):
            args.sort = value
    elif key == "limit":
        args.limit = int(value)
    elif key == "level":
        args.level_min, args.level_max = parse_int_range(value)
    elif key == "x_rotation":
        args.x_rotation_min, args.x_rotation_max = parse_float_range(value)
    elif key == "y_rotation":
        args.y_rotation_min, args.y_rotation_max = parse_float_range(value)
    elif key == "predicate":
        args.predicate = value
    elif key == "nbt":
        args.nbt = value
    elif key == "scores":
        # scores={obj=5..10, obj2=3}
        inner = value.strip("{}")
        for score_part in inner.split(","):
            score_part = score_part.strip()
            if "=" in score_part:
                obj, range_str = score_part.split("=", 1)
                args.scores[obj.strip()] = parse_int_range(range_str.strip())


def resolve_selector(
    server,
    sender,
    selector_str: str,
    selector_args: SelectorArgs | None = None,
) -> list:
    """
    Resolve an entity selector to a list of matching entities/players.

    Args:
        server: MinecraftServer
        sender: Connection or None (console)
        selector_str: The selector string (e.g., '@a', '@e[type=zombie]')
        selector_args: Pre-parsed selector args, or None to parse

    Returns:
        List of matching Connection or Entity objects
    """
    if selector_args is None:
        _, selector_args = parse_selector(selector_str)
        if selector_args is None:
            # Not a selector, try to find a player by name
            player = server.find_player(selector_str)
            return [player] if player else []

    selector_type = selector_str.split("[")[0] if "[" in selector_str else selector_str

    # Base position for distance calculations
    if sender is not None:
        base_x, base_y, base_z = sender.x, sender.y, sender.z
    else:
        base_x, base_y, base_z = 0.0, 100.0, 0.0

    # Override base position if specified
    if selector_args.x is not None:
        base_x = selector_args.x
    if selector_args.y is not None:
        base_y = selector_args.y
    if selector_args.z is not None:
        base_z = selector_args.z

    # Collect candidates
    candidates = []

    if selector_type in ("@a", "@p", "@r"):
        # Player selectors
        candidates = list(server.get_online_players())
    elif selector_type == "@e":
        # All entities (including players)
        from world.entities import Entity
        candidates = list(server.entity_manager.list_entities())
        candidates.extend(server.get_online_players())
    elif selector_type == "@s":
        # Self
        if sender is not None:
            candidates = [sender]
        return candidates

    # Filter candidates
    filtered = []
    for entity in candidates:
        if _matches_selector(entity, selector_args, base_x, base_y, base_z, selector_type):
            filtered.append(entity)

    # Sort
    if selector_type == "@p" or selector_args.sort == "nearest":
        filtered.sort(key=lambda e: _distance_squared(e, base_x, base_y, base_z))
    elif selector_args.sort == "furthest":
        filtered.sort(key=lambda e: -_distance_squared(e, base_x, base_y, base_z))
    elif selector_args.sort == "random":
        random.shuffle(filtered)

    # Limit
    if selector_args.limit is not None:
        filtered = filtered[:selector_args.limit]

    # @p returns only nearest
    if selector_type == "@p" and not selector_args.limit:
        filtered = filtered[:1]

    # @r returns only one random
    if selector_type == "@r" and not selector_args.limit:
        filtered = filtered[:1]

    return filtered


def resolve_targets(
    server,
    sender,
    selector_str: str,
    *,
    allow_players: bool = True,
    allow_entities: bool = True,
    must_exist: bool = True,
) -> list:
    """
    High-level target resolution for commands.

    Like resolve_selector but with additional flexibility:
      - If selector_str is a player name, resolves to that player
      - If allow_players is False, filters out Connection objects
      - If allow_entities is False, filters out non-Connection objects
      - If must_exist is True and no targets found, returns empty list

    Args:
        server: MinecraftServer
        sender: Connection or None (console)
        selector_str: Selector string or player name
        allow_players: Whether to include player targets
        allow_entities: Whether to include non-player entity targets
        must_exist: If True, return empty list when no match found

    Returns:
        List of matching targets
    """
    targets = resolve_selector(server, sender, selector_str)

    # Filter by type
    if not allow_players:
        from network.connection import Connection
        targets = [t for t in targets if not isinstance(t, Connection)]
    if not allow_entities:
        from network.connection import Connection
        targets = [t for t in targets if isinstance(t, Connection)]

    return targets


def resolve_one_target(
    server,
    sender,
    selector_str: str,
    *,
    fallback_to_self: bool = False,
):
    """
    Resolve a selector to a single target.

    Returns the first match, or None if not found.
    If fallback_to_self is True and no target found, returns the sender.
    """
    targets = resolve_selector(server, sender, selector_str)
    if targets:
        return targets[0]
    # Try as player name
    player = server.find_player(selector_str)
    if player:
        return player
    if fallback_to_self and sender:
        return sender
    return None


def is_selector(raw: str) -> bool:
    """Check if a string is a vanilla selector (starts with @)."""
    return bool(re.match(r'^@[apers](\[.*\])?$', raw.strip()))


def _distance_squared(entity, x: float, y: float, z: float) -> float:
    """Calculate squared distance from an entity to a position."""
    ex = entity.x if hasattr(entity, 'x') else 0.0
    ey = entity.y if hasattr(entity, 'y') else 0.0
    ez = entity.z if hasattr(entity, 'z') else 0.0
    return (ex - x) ** 2 + (ey - y) ** 2 + (ez - z) ** 2


def _matches_selector(
    entity,
    args: SelectorArgs,
    base_x: float,
    base_y: float,
    base_z: float,
    selector_type: str,
) -> bool:
    """Check if an entity matches the selector criteria."""
    from network.connection import Connection

    ex = getattr(entity, 'x', 0.0)
    ey = getattr(entity, 'y', 0.0)
    ez = getattr(entity, 'z', 0.0)

    # Distance check
    if args.distance_min is not None or args.distance_max is not None:
        dist = math.sqrt(_distance_squared(entity, base_x, base_y, base_z))
        if args.distance_min is not None and dist < args.distance_min:
            return False
        if args.distance_max is not None and dist > args.distance_max:
            return False

    # Volume check
    if args.dx is not None or args.dy is not None or args.dz is not None:
        if args.dx is not None:
            if not (base_x <= ex <= base_x + args.dx):
                return False
        if args.dy is not None:
            if not (base_y <= ey <= base_y + args.dy):
                return False
        if args.dz is not None:
            if not (base_z <= ez <= base_z + args.dz):
                return False

    # Entity type check
    if args.type_name is not None:
        from world.entities import MobEntity
        entity_type = None
        if isinstance(entity, Connection):
            entity_type = "minecraft:player"
        elif isinstance(entity, MobEntity):
            entity_type = f"minecraft:{getattr(entity, 'mob_type', 'unknown')}"
        elif hasattr(entity, 'kind'):
            entity_type = f"minecraft:{entity.kind}"

        if entity_type is not None:
            matches_type = entity_type == args.type_name
            if args.type_negate:
                if matches_type:
                    return False
            else:
                if not matches_type:
                    return False

    # Gamemode check (players only)
    if args.gamemode is not None:
        if not isinstance(entity, Connection):
            return False
        gm = getattr(entity, 'gamemode', '')
        matches_gm = gm == args.gamemode
        if args.gamemode_negate:
            if matches_gm:
                return False
        else:
            if not matches_gm:
                return False

    # Name check
    if args.name is not None:
        name = getattr(entity, 'username', '') or getattr(entity, 'custom_name', '') or ''
        matches_name = name.lower() == args.name.lower()
        if args.name_negate:
            if matches_name:
                return False
        else:
            if not matches_name:
                return False

    # Tag check
    if args.tags or args.tags_negated:
        entity_tags = set(getattr(entity, '_tags', set()))
        for tag in args.tags:
            if tag not in entity_tags:
                return False
        for tag in args.tags_negated:
            if tag in entity_tags:
                return False

    # Level check (players only)
    if args.level_min is not None or args.level_max is not None:
        if isinstance(entity, Connection):
            level = getattr(entity, 'experience_level', 0)
            if args.level_min is not None and level < args.level_min:
                return False
            if args.level_max is not None and level > args.level_max:
                return False
        else:
            return False

    # Rotation check
    if args.y_rotation_min is not None or args.y_rotation_max is not None:
        yaw = getattr(entity, 'yaw', 0.0)
        if args.y_rotation_min is not None and yaw < args.y_rotation_min:
            return False
        if args.y_rotation_max is not None and yaw > args.y_rotation_max:
            return False

    if args.x_rotation_min is not None or args.x_rotation_max is not None:
        pitch = getattr(entity, 'pitch', 0.0)
        if args.x_rotation_min is not None and pitch < args.x_rotation_min:
            return False
        if args.x_rotation_max is not None and pitch > args.x_rotation_max:
            return False

    return True
