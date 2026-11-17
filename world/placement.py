"""
Vanilla block placement (Block.getStateForPlacement) for the common
orientable blocks: facing from the player's view, attachment faces, slab and
stair halves, log axes, wall torches, doors, beds, waterlogging, and the
items whose block has a different name (redstone -> redstone_wire, ...).
"""

from __future__ import annotations

import math

from .chunk_io import BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK

# protocol face index -> (dx, dy, dz) and name
FACES = {0: (0, -1, 0), 1: (0, 1, 0), 2: (0, 0, -1), 3: (0, 0, 1), 4: (-1, 0, 0), 5: (1, 0, 0)}
FACE_NAMES = {0: "down", 1: "up", 2: "north", 3: "south", 4: "west", 5: "east"}
OPPOSITE = {"down": "up", "up": "down", "north": "south", "south": "north", "west": "east", "east": "west"}
CLOCKWISE = {"north": "east", "east": "south", "south": "west", "west": "north"}
DIR_VECTORS = {"down": (0, -1, 0), "up": (0, 1, 0), "north": (0, 0, -1), "south": (0, 0, 1),
               "west": (-1, 0, 0), "east": (1, 0, 0)}

# items whose placed block has another name
ITEM_TO_BLOCK = {
    "minecraft:redstone": "minecraft:redstone_wire",
    "minecraft:string": "minecraft:tripwire",
    "minecraft:wheat_seeds": "minecraft:wheat",
    "minecraft:carrot": "minecraft:carrots",
    "minecraft:potato": "minecraft:potatoes",
    "minecraft:beetroot_seeds": "minecraft:beetroots",
    "minecraft:melon_seeds": "minecraft:melon_stem",
    "minecraft:pumpkin_seeds": "minecraft:pumpkin_stem",
    "minecraft:sweet_berries": "minecraft:sweet_berry_bush",
    "minecraft:glow_berries": "minecraft:cave_vines",
    "minecraft:cocoa_beans": "minecraft:cocoa",
    "minecraft:torchflower_seeds": "minecraft:torchflower_crop",
    "minecraft:pitcher_pod": "minecraft:pitcher_crop",
}

WALL_VARIANTS = {
    "minecraft:torch": "minecraft:wall_torch",
    "minecraft:soul_torch": "minecraft:soul_wall_torch",
    "minecraft:redstone_torch": "minecraft:redstone_wall_torch",
}

LOOK_OPPOSITE_FACING = ("piston", "sticky_piston", "dispenser", "dropper", "barrel",
                        "command_block", "chain_command_block", "repeating_command_block", "crafter")
CLICKED_FACE_FACING = ("end_rod", "lightning_rod", "amethyst_cluster", "large_amethyst_bud",
                       "medium_amethyst_bud", "small_amethyst_bud", "shulker_box")
SAME_AS_PLAYER = ("_stairs", "_door", "_fence_gate", "_bed")


def horizontal_direction(yaw: float) -> str:
    """Direction.fromYRot: the horizontal direction the player faces."""
    return ("south", "west", "north", "east")[math.floor(yaw / 90.0 + 0.5) & 3]


def nearest_looking_direction(yaw: float, pitch: float) -> str:
    y, p = math.radians(yaw), math.radians(pitch)
    view = (-math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))
    return max(DIR_VECTORS, key=lambda d: sum(a * b for a, b in zip(view, DIR_VECTORS[d])))


def block_for_item(item_id: str) -> str | None:
    name = ITEM_TO_BLOCK.get(item_id, item_id)
    return name if name in BLOCK_NAME_TO_DEFAULT_STATE else None


def with_props(state: int, **changes) -> int:
    """Same block, some properties changed (unknown values leave the state as is)."""
    name, props = STATE_ID_TO_BLOCK.get(state, (None, {}))
    if name is None:
        return state
    merged = dict(props)
    for key, value in changes.items():
        if key in merged:
            merged[key] = str(value).lower()
    return BLOCK_KEY_TO_STATE_ID.get((name, tuple(sorted(merged.items()))), state)


def _state_for(name: str) -> int | None:
    return BLOCK_NAME_TO_DEFAULT_STATE.get(name)


def placement_states(item_id: str, face: int, cursor: tuple[float, float, float],
                     yaw: float, pitch: float, place_pos: tuple[int, int, int],
                     existing_state: int, get_block) -> list[tuple[tuple[int, int, int], int]] | None:
    """
    States to place for using ``item_id`` on ``face`` (cursor = hit position
    inside the clicked block). Returns [(pos, state), ...] (the first entry is
    the main block; doors and beds add their second half), or None when the
    block cannot be placed there.
    """
    name = block_for_item(item_id)
    if name is None:
        return None
    face_name = FACE_NAMES.get(face, "up")
    horizontal = horizontal_direction(yaw)
    looking = nearest_looking_direction(yaw, pitch)
    hit_upper = cursor[1] > 0.5

    # torches / redstone torches on a wall
    if name in WALL_VARIANTS:
        if face_name == "down":
            return None
        if face_name != "up":
            wall = _state_for(WALL_VARIANTS[name])
            return [(place_pos, with_props(wall, facing=face_name))]

    state = _state_for(name)
    props = STATE_ID_TO_BLOCK.get(state, (name, {}))[1]
    short = name.split(":")[1]
    changes: dict = {}

    if "facing" in props:
        six_way = "up" in _values(name, "facing")
        if short == "observer":
            changes["facing"] = looking
        elif short in LOOK_OPPOSITE_FACING:
            changes["facing"] = OPPOSITE[looking]
        elif short == "hopper":
            target = OPPOSITE[face_name]
            changes["facing"] = "down" if target in ("up", "down") else target
        elif short in CLICKED_FACE_FACING or short.endswith("shulker_box"):
            changes["facing"] = face_name
        elif "face" in props:          # lever, buttons, grindstone
            if face_name == "up":
                changes.update(face="floor", facing=horizontal)
            elif face_name == "down":
                changes.update(face="ceiling", facing=horizontal)
            else:
                changes.update(face="wall", facing=face_name)
        elif short.endswith("_trapdoor"):
            if face_name in ("up", "down"):
                changes.update(facing=OPPOSITE[horizontal], half="top" if face_name == "down" else "bottom")
            else:
                changes.update(facing=face_name, half="top" if hit_upper else "bottom")
        elif short in ("ladder", "tripwire_hook") or short.endswith("_wall_sign") or short.endswith("wall_banner"):
            if face_name in ("up", "down"):
                return None
            changes["facing"] = face_name
        elif short == "anvil" or short.endswith("_anvil"):
            changes["facing"] = CLOCKWISE[horizontal]
        elif any(short.endswith(s) for s in SAME_AS_PLAYER):
            changes["facing"] = horizontal
        elif six_way:
            changes["facing"] = OPPOSITE[looking]
        else:
            changes["facing"] = OPPOSITE[horizontal]

    if "axis" in props:
        changes["axis"] = {"up": "y", "down": "y", "north": "z", "south": "z",
                           "west": "x", "east": "x"}[face_name]
    if short.endswith("_slab") and "type" in props:
        existing_name, existing_props = STATE_ID_TO_BLOCK.get(existing_state, ("", {}))
        if existing_name == name and existing_props.get("type") != "double":
            changes["type"] = "double"
        else:
            changes["type"] = "top" if face_name == "down" or (face_name != "up" and hit_upper) else "bottom"
    if short.endswith("_stairs") and "half" in props:
        changes["half"] = "top" if face_name == "down" or (face_name != "up" and hit_upper) else "bottom"
    if "rotation" in props and short.endswith("_sign"):
        if face_name in ("north", "south", "west", "east"):
            wall = _state_for(name.replace("_sign", "_wall_sign"))
            if wall is not None:
                return [(place_pos, with_props(wall, facing=face_name))]
        changes["rotation"] = math.floor((180.0 + yaw) * 16.0 / 360.0 + 0.5) & 15
    if "waterlogged" in props:
        existing_name, existing_props = STATE_ID_TO_BLOCK.get(existing_state, ("", {}))
        changes["waterlogged"] = existing_name == "minecraft:water" and existing_props.get("level", "0") == "0"

    state = with_props(state, **changes)
    result = [(place_pos, state)]

    x, y, z = place_pos
    if short.endswith("_door") and "half" in props:
        above = get_block(x, y + 1, z)
        if above is None or not _replaceable(above):
            return None
        result = [(place_pos, with_props(state, half="lower")),
                  ((x, y + 1, z), with_props(state, half="upper"))]
    elif short.endswith("_bed") and "part" in props:
        dx, _, dz = DIR_VECTORS[horizontal]
        head_pos = (x + dx, y, z + dz)
        head_block = get_block(*head_pos)
        if head_block is None or not _replaceable(head_block):
            return None
        result = [(place_pos, with_props(state, part="foot")), (head_pos, with_props(state, part="head"))]
    elif short in ("tall_grass", "large_fern", "sunflower", "lilac", "rose_bush", "peony") and "half" in props:
        above = get_block(x, y + 1, z)
        if above is None or not _replaceable(above):
            return None
        result = [(place_pos, with_props(state, half="lower")), ((x, y + 1, z), with_props(state, half="upper"))]
    return result


def _values(name: str, prop: str) -> set[str]:
    out = set()
    for state, (block, props) in _states_of(name):
        if prop in props:
            out.add(props[prop])
    return out


_STATES_BY_NAME: dict[str, list] = {}


def _states_of(name: str):
    if not _STATES_BY_NAME:
        for state, (block, props) in STATE_ID_TO_BLOCK.items():
            _STATES_BY_NAME.setdefault(block, []).append((state, (block, props)))
    return _STATES_BY_NAME.get(name, [])


def _replaceable(state: int) -> bool:
    from handlers.play.blocks import _is_replaceable
    return _is_replaceable(state)
