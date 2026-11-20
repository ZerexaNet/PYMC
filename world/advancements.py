# ============================================================
# PyMC - advancements (进度, 1.12+)
#
# Since 1.12 the achievements of 1.11 are advancements: a tree of goals
# that each have criteria. A player's progress lives in
# world/advancements/<uuid>.json (criterion name -> epoch milliseconds when it
# was obtained) and is sent to the client with the "advancements" packet.
#
# Criteria are "inventory_changed": a criterion is obtained when the player's
# inventory holds one of its items. The check runs every few ticks.
#
# The tree is a subset of the vanilla "story" branch. Titles and descriptions
# are vanilla translation keys, so the client shows its own localized text.
# ============================================================

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from time import time

from protocol.data_types import (write_boolean, write_float, write_int, write_long,
                                 write_string, write_varint)
from protocol.text import encode_component, translate

logger = logging.getLogger("PyMC.进度")

NAMESPACE = "minecraft:"
CHECK_INTERVAL = 20             # ticks between inventory checks
PROTOCOL_1_21_1 = 767           # the packet layout below is the 1.21.1 one
FRAME_TASK, FRAME_CHALLENGE, FRAME_GOAL = 0, 1, 2
_BACKGROUND_STONE = "minecraft:textures/gui/advancements/backgrounds/stone.png"


@dataclass(frozen=True)
class Advancement:
    key: str                                  # "story/root" (without namespace)
    icon: str                                 # item id shown on the tab
    criteria: dict                            # criterion name -> item ids that obtain it
    requirements: tuple                       # AND of OR-groups of criterion names
    parent: str | None = None
    frame: int = FRAME_TASK
    x: float = 0.0
    y: float = 0.0
    background: str | None = None
    toast: bool = True
    hidden: bool = False
    children: list = field(default_factory=list, compare=False)

    @property
    def id(self) -> str:
        return NAMESPACE + self.key

    @property
    def title_key(self) -> str:
        return "advancements." + self.key.replace("/", ".") + ".title"

    @property
    def description_key(self) -> str:
        return "advancements." + self.key.replace("/", ".") + ".description"


def _adv(key, icon, criteria, requirements=None, parent=None, **kw) -> Advancement:
    if requirements is None:
        requirements = tuple((name,) for name in criteria)   # every criterion is needed
    return Advancement(key, icon, {n: tuple(i) for n, i in criteria.items()},
                       tuple(tuple(g) for g in requirements), parent, **kw)


ADVANCEMENTS: tuple[Advancement, ...] = (
    _adv("story/root", "minecraft:grass_block",
         {"crafting_table": ("minecraft:crafting_table",)},
         parent=None, background=_BACKGROUND_STONE, toast=False, x=0.0, y=0.0),
    _adv("story/mine_stone", "minecraft:wooden_pickaxe",
         {"get_stone": ("minecraft:cobblestone",)},
         parent="story/root", x=1.0, y=0.0),
    _adv("story/upgrade_tools", "minecraft:stone_pickaxe",
         {"stone_pickaxe": ("minecraft:stone_pickaxe",)},
         parent="story/mine_stone", x=2.0, y=0.0),
    _adv("story/smelt_iron", "minecraft:iron_ingot",
         {"iron": ("minecraft:iron_ingot",)},
         parent="story/upgrade_tools", x=3.0, y=0.0),
    _adv("story/obtain_armor", "minecraft:iron_chestplate",
         {"iron_helmet": ("minecraft:iron_helmet",),
          "iron_chestplate": ("minecraft:iron_chestplate",),
          "iron_leggings": ("minecraft:iron_leggings",),
          "iron_boots": ("minecraft:iron_boots",)},
         requirements=[("iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots")],
         parent="story/smelt_iron", x=4.0, y=0.0),
    _adv("story/iron_tools", "minecraft:iron_pickaxe",
         {"iron_pickaxe": ("minecraft:iron_pickaxe",)},
         parent="story/smelt_iron", x=3.0, y=1.0),
    _adv("story/lava_bucket", "minecraft:lava_bucket",
         {"lava_bucket": ("minecraft:lava_bucket",)},
         parent="story/smelt_iron", x=3.0, y=-1.0),
    _adv("story/mine_diamond", "minecraft:diamond",
         {"diamond": ("minecraft:diamond",)},
         parent="story/iron_tools", x=4.0, y=1.0),
    _adv("story/shiny_gear", "minecraft:diamond_chestplate",
         {"diamond_helmet": ("minecraft:diamond_helmet",),
          "diamond_chestplate": ("minecraft:diamond_chestplate",),
          "diamond_leggings": ("minecraft:diamond_leggings",),
          "diamond_boots": ("minecraft:diamond_boots",)},
         requirements=[("diamond_helmet", "diamond_chestplate", "diamond_leggings", "diamond_boots")],
         parent="story/mine_diamond", x=5.0, y=1.0),
    # adventure tab: granted by events (see trigger), not by inventory contents
    _adv("adventure/root", "minecraft:map",
         {"killed_something": ()},
         background="minecraft:textures/gui/advancements/backgrounds/adventure.png",
         toast=False, x=0.0, y=0.0),
    _adv("adventure/kill_a_mob", "minecraft:iron_sword",
         {"killed_mob": ()},
         parent="adventure/root", x=1.0, y=0.0),
    _adv("adventure/enchant_item", "minecraft:enchanted_book",
         {"enchanted_item": ()},
         parent="adventure/root", x=1.0, y=1.0),
)

BY_KEY: dict[str, Advancement] = {a.key: a for a in ADVANCEMENTS}
for _a in ADVANCEMENTS:
    if _a.parent is not None:
        BY_KEY[_a.parent].children.append(_a)


def descendants(key: str) -> list[Advancement]:
    out, stack = [], list(BY_KEY[key].children)
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(node.children)
    return out


def ancestors(key: str) -> list[Advancement]:
    out, parent = [], BY_KEY[key].parent
    while parent is not None:
        out.append(BY_KEY[parent])
        parent = BY_KEY[parent].parent
    return out


# ------------------------------------------------------------ progress state

def _clean(raw) -> dict:
    """Keep only known advancements and criteria from a saved file."""
    progress: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return progress
    for key, entry in raw.items():
        adv = BY_KEY.get(key.removeprefix(NAMESPACE))
        if adv is None or not isinstance(entry, dict):
            continue
        criteria = entry.get("criteria", {})
        if not isinstance(criteria, dict):
            continue
        for name, when in criteria.items():
            if name in adv.criteria and isinstance(when, int):
                progress.setdefault(adv.key, {})[name] = when
    return progress


def _path(server, player_uuid) -> Path:
    return Path(server.world_storage.world_dir) / "advancements" / f"{player_uuid}.json"


def load(server, conn) -> None:
    """Read the player's progress into conn.advancement_progress (empty when there is none)."""
    progress: dict = {}
    try:
        path = _path(server, conn.uuid)
        if path.exists():
            progress = _clean(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        logger.warning(f"无法读取 {conn.username} 的进度: {e}")
    conn.advancement_progress = progress


def save(server, conn) -> None:
    progress = getattr(conn, "advancement_progress", None)
    if progress is None or getattr(conn, "uuid", None) is None:
        return
    data = {NAMESPACE + key: {"criteria": {name: when for name, when in criteria.items()},
                              "done": is_done(BY_KEY[key], criteria)}
            for key, criteria in progress.items() if criteria}
    path = _path(server, conn.uuid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.warning(f"无法保存 {conn.username} 的进度: {e}")


def is_done(adv: Advancement, criteria: dict) -> bool:
    return all(any(name in criteria for name in group) for group in adv.requirements)


def is_complete(conn, key: str) -> bool:
    return is_done(BY_KEY[key], conn.advancement_progress.get(key, {}))


def _inventory_items(conn) -> set[str]:
    inv = getattr(conn, "inventory_obj", None)
    if inv is None:
        return set()
    return {slot.item_id for slot in inv.slots if slot is not None and not slot.is_empty}


def check_inventory(conn) -> tuple[list[Advancement], list[Advancement]]:
    """
    Grant the criteria the inventory satisfies.
    Returns (advancements whose progress changed, advancements completed now).
    """
    progress = conn.advancement_progress
    items = _inventory_items(conn)
    if not items:
        return [], []
    now = int(time() * 1000)
    before = {a.key: is_done(a, progress.get(a.key, {})) for a in ADVANCEMENTS}
    changed = []
    for adv in ADVANCEMENTS:
        criteria = progress.setdefault(adv.key, {})
        added = False
        for name, wanted in adv.criteria.items():
            if name not in criteria and any(item in items for item in wanted):
                criteria[name] = now
                added = True
        if added:
            changed.append(adv)
    for adv in ADVANCEMENTS:
        if not progress.get(adv.key):
            progress.pop(adv.key, None)
    completed = [a for a in changed
                 if not before[a.key] and is_done(a, progress.get(a.key, {}))]
    return changed, completed


# ------------------------------------------------------------ packets

def _encode(conn, reset: bool, advs, progress_keys, progress: dict) -> bytes:
    from world.inventory import ItemStack, encode_slot_entry
    pv = conn.protocol_version
    out = bytearray(write_boolean(reset))
    out += write_varint(len(advs))
    for adv in advs:
        out += write_string(adv.id)
        if adv.parent is None:
            out += write_boolean(False)
        else:
            out += write_boolean(True) + write_string(NAMESPACE + adv.parent)
        out += write_boolean(True)                                   # display info
        out += encode_component(translate(adv.title_key), pv)
        out += encode_component(translate(adv.description_key), pv)
        out += encode_slot_entry(ItemStack(adv.icon, 1))
        out += write_varint(adv.frame)
        flags = (1 if adv.background else 0) | (2 if adv.toast else 0) | (4 if adv.hidden else 0)
        out += write_int(flags)
        if adv.background:
            out += write_string(adv.background)
        out += write_float(adv.x) + write_float(adv.y)
        out += write_varint(len(adv.requirements))                   # requirements
        for group in adv.requirements:
            out += write_varint(len(group))
            for name in group:
                out += write_string(name)
        out += write_boolean(False)                                  # sendsTelemetryEvent
    out += write_varint(0)                                           # removed
    out += write_varint(len(progress_keys))
    for key in progress_keys:
        adv = BY_KEY[key]
        criteria = progress.get(key, {})
        out += write_string(adv.id)
        out += write_varint(len(adv.criteria))
        for name in adv.criteria:
            out += write_string(name)
            when = criteria.get(name)
            if when is None:
                out += write_boolean(False)
            else:
                out += write_boolean(True) + write_long(when)
    return bytes(out)


async def _send(conn, payload: bytes) -> None:
    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "advancements")
    if pid is None or conn.protocol_version != PROTOCOL_1_21_1:
        return     # other protocol versions are not implemented yet
    await conn.send_packet(pid, payload)


async def send_full(conn) -> None:
    """The whole tree and this player's progress (sent on join)."""
    progress = conn.advancement_progress
    keys = [a.key for a in ADVANCEMENTS]
    await _send(conn, _encode(conn, True, ADVANCEMENTS, keys, progress))


async def send_update(conn, advs) -> None:
    """Only the given advancements (after a grant or revoke)."""
    if not advs:
        return
    keys = [a.key for a in advs]
    await _send(conn, _encode(conn, False, advs, keys, conn.advancement_progress))


async def on_join(server, conn) -> None:
    load(server, conn)
    await send_full(conn)


def _announce(server, conn, adv: Advancement) -> None:
    if adv.hidden:
        return
    server.broadcast_system_message(
        translate("chat.type.advancement.task", conn.username, translate(adv.title_key)))


async def tick(server, tick_count: int) -> None:
    """Every tick: send the events that happened since the last tick.
    Every CHECK_INTERVAL ticks: grant what the inventories already satisfy."""
    await flush(server)
    if tick_count % CHECK_INTERVAL:
        return
    for conn in server.get_online_players():
        if getattr(conn, "advancement_progress", None) is None:
            continue
        changed, completed = check_inventory(conn)
        if not changed:
            continue
        await send_update(conn, changed)
        save(server, conn)
        for adv in completed:
            _announce(server, conn, adv)


# ------------------------------------------------------------ events

_pending: list[tuple[object, str, bool]] = []   # (conn, advancement key, done before the event)


def trigger(conn, key: str, criterion: str) -> None:
    """
    An event happened for this player. Safe to call from synchronous game code:
    the progress changes now, the client is told by flush() on the next tick.
    """
    adv = BY_KEY.get(key)
    progress = getattr(conn, "advancement_progress", None)
    if adv is None or progress is None or criterion not in adv.criteria:
        return
    criteria = progress.setdefault(key, {})
    if criterion in criteria:
        return
    before = is_done(adv, criteria)
    criteria[criterion] = int(time() * 1000)
    _pending.append((conn, key, before))


async def flush(server) -> None:
    """Send the progress changed by trigger() since the last flush, and announce completions."""
    if not _pending:
        return
    batch = _pending[:]
    _pending.clear()
    per_conn: dict[int, tuple[object, list[Advancement]]] = {}
    completed: list[tuple[object, Advancement]] = []
    for conn, key, before in batch:
        if not getattr(conn, "alive", True):
            continue
        adv = BY_KEY[key]
        entry = per_conn.setdefault(id(conn), (conn, []))
        if adv not in entry[1]:
            entry[1].append(adv)
        if not before and is_done(adv, conn.advancement_progress.get(key, {})):
            completed.append((conn, adv))
    for conn, advs in per_conn.values():
        await send_update(conn, advs)
        save(server, conn)
    for conn, adv in completed:
        _announce(server, conn, adv)


def on_mob_killed(conn, mob) -> None:
    """A player killed a mob (called from the damage code)."""
    trigger(conn, "adventure/root", "killed_something")
    if getattr(mob, "profile", {}).get("category") == "hostile":
        trigger(conn, "adventure/kill_a_mob", "killed_mob")


# ------------------------------------------------------------ commands

def _set(conn, key: str, criteria: list[str] | None, grant: bool) -> None:
    """Grant or revoke the criteria (all of the advancement when criteria is None)."""
    adv = BY_KEY[key]
    progress = conn.advancement_progress
    names = list(adv.criteria) if criteria is None else criteria
    now = int(time() * 1000)
    current = progress.setdefault(key, {})
    for name in names:
        if name not in adv.criteria:
            continue
        if grant:
            current.setdefault(name, now)
        else:
            current.pop(name, None)
    if not current:
        progress.pop(key, None)


async def apply(server, conn, action: str, mode: str, target: str | None = None,
                criterion: str | None = None) -> int:
    """
    Run one /advancement grant|revoke for one player. Returns how many advancements
    changed. Modes: everything, only <adv> [criterion], from <adv>, until <adv>,
    through <adv>.
    """
    grant = action == "grant"
    if getattr(conn, "advancement_progress", None) is None:
        load(server, conn)
    if mode == "everything":
        keys = [a.key for a in ADVANCEMENTS]
    else:
        if target is None or target.removeprefix(NAMESPACE) not in BY_KEY:
            raise ValueError(f"未知进度: {target}")
        key = target.removeprefix(NAMESPACE)
        if mode == "only":
            keys = [key]
        elif mode == "from":
            keys = [key] + [a.key for a in descendants(key)]
        elif mode == "until":
            keys = [a.key for a in ancestors(key)]
        elif mode == "through":
            keys = [a.key for a in ancestors(key)] + [key]
        else:
            raise ValueError(f"未知模式: {mode}")
    criteria = [criterion] if criterion and mode == "only" else None
    changed = []
    for key in keys:
        before = dict(conn.advancement_progress.get(key, {}))
        _set(conn, key, criteria if mode == "only" else None, grant)
        if conn.advancement_progress.get(key, {}) != before:
            changed.append(BY_KEY[key])
    save(server, conn)
    await send_update(conn, changed)
    return len(changed)
