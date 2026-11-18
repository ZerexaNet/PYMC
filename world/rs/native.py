"""
Native (C++) vanilla engine: block updates / redstone, hoppers and explosions.

native/vanilla is a line-by-line port of world/rs (same update order, same
quasi-connectivity, BUD, 0-tick and TNT-duplication behaviour) and adds the
vanilla hopper block entity. NativeRedstoneEngine has the same interface as
RedstoneEngine; the Python engine stays as the fallback and as the reference
the native one is tested against (tests/test_native_engine.py).

Set PYMC_NATIVE_ENGINE=0 to force the Python engine.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
from array import array
from itertools import chain
from pathlib import Path

from . import RedstoneEngine, _holds_placeable_item, registry
from .core import DIRECTIONS, name_of

logger = logging.getLogger("PyMC.红石")

ABI_VERSION = 3

LOAD_CHUNK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint16))
CONTAINER_SIGNAL = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
ENTITY_COUNT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
INV_GET = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.POINTER(ctypes.c_int32), ctypes.c_int)
CAN_PLACE = ctypes.CFUNCTYPE(ctypes.c_int, *([ctypes.c_int] * 7))
TAKE = ctypes.CFUNCTYPE(None, *([ctypes.c_int] * 6))
GIVE = ctypes.CFUNCTYPE(None, *([ctypes.c_int] * 7))
PICKUP = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
COMPOST = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_int)

CHUNK_BYTES = 384 * 16 * 16 * 2

FX_DROP, FX_SOUND, FX_NOTE, FX_DISPENSE, FX_PRIME_TNT, FX_BURNOUT = 1, 2, 3, 4, 5, 6
SOUNDS = {1: "minecraft:block.lever.click", 2: "minecraft:block.stone_button.click_on",
          3: "minecraft:block.wooden_button.click_on", 4: "minecraft:block.piston.extend",
          5: "minecraft:block.piston.contract", 6: "minecraft:block.composter.fill",
          7: "minecraft:block.composter.fill_success", 8: "minecraft:block.composter.empty",
          9: "minecraft:block.composter.ready"}
FURNACES = ("furnace", "blast_furnace", "smoker")
DIR_NAMES = ("down", "up", "north", "south", "west", "east")

# ----------------------------------------------------------------- loading

_lib = None
_lib_lock = threading.Lock()
_lib_failed = False


def _candidates() -> list[Path]:
    from .._native_build import build_cache_dir, vanilla_library_name
    name = vanilla_library_name()
    roots = [Path(__file__).resolve().parent.parent.parent, Path.cwd(), Path(sys.argv[0]).resolve().parent,
             Path(sys.executable).resolve().parent]
    compiled = globals().get("__compiled__")
    if compiled is not None and hasattr(compiled, "containing_dir"):
        roots.insert(0, Path(compiled.containing_dir).resolve())
    found = []
    for root in roots:
        for rel in ("native", "build/stage/native", "."):
            found.append(root / rel / name)
    found.append(build_cache_dir() / name)
    return found


def _try_load(path: Path):
    try:
        lib = ctypes.CDLL(str(path))
        if lib.vrs_version() != ABI_VERSION:
            return None
    except (OSError, AttributeError):
        return None
    _declare(lib)
    return lib


def _declare(lib):
    i, i32p, d = ctypes.c_int, ctypes.POINTER(ctypes.c_int32), ctypes.c_double
    lib.vrs_init.argtypes = [ctypes.c_char_p]
    lib.vrs_set_callbacks.argtypes = [LOAD_CHUNK, CONTAINER_SIGNAL, ENTITY_COUNT]
    lib.vrs_set_hopper_callbacks.argtypes = [INV_GET, CAN_PLACE, TAKE, GIVE, PICKUP, COMPOST, i]
    lib.vrs_tick_hopper_minecarts.argtypes = [i32p, ctypes.POINTER(d), ctypes.POINTER(ctypes.c_uint8), i]
    for name in ("vrs_drain_changes", "vrs_drain_effects", "vrs_drain_actions", "vrs_drain_hopper_changes",
                 "vrs_export_ticks", "vrs_export_comparators"):
        getattr(lib, name).argtypes = [i32p, i]
    lib.vrs_tick_hoppers.argtypes = [i32p, i]
    lib.vrs_block_changed.argtypes = [i, i, i, i, i, i]
    lib.vrs_game_time.restype = ctypes.c_int64
    lib.vrs_set_game_time.argtypes = [ctypes.c_int64]
    lib.vrs_block_index.argtypes = [ctypes.c_char_p]
    lib.vrs_explosion_blocks.argtypes = [i, i32p, ctypes.POINTER(ctypes.c_void_p), i, i, d, d, d, d,
                                         ctypes.POINTER(d), i32p, i]
    lib.vrs_exposure.argtypes = [i, i32p, ctypes.POINTER(ctypes.c_void_p), i, i] + [d] * 9
    lib.vrs_exposure.restype = d


def load_library():
    """The native engine library (built from source when needed), or None."""
    global _lib, _lib_failed
    if _lib is not None or _lib_failed:
        return _lib
    with _lib_lock:
        if _lib is not None or _lib_failed:
            return _lib
        if os.environ.get("PYMC_NATIVE_ENGINE", "1") in ("0", "false", "no", "off"):
            _lib_failed = True
            return None
        from .._native_build import build_vanilla_library
        from ..chunk_io import _find_blocks_json
        lib = None
        source_tree = (Path(__file__).resolve().parent.parent.parent / "native" / "vanilla" / "api.cpp").exists()
        if source_tree:
            built = build_vanilla_library()       # rebuilds when the sources changed
            if built:
                lib = _try_load(Path(built))
        if lib is None:
            for path in _candidates():
                if path.exists():
                    lib = _try_load(path)
                    if lib is not None:
                        break
        if lib is None or not lib.vrs_init(_find_blocks_json().encode("utf-8")):
            logger.info("Native redstone/hopper/explosion engine unavailable; using the Python engine")
            _lib_failed = True
            return None
        _lib = lib
        logger.info("Native redstone/hopper/explosion engine loaded")
        return _lib


def native_available() -> bool:
    return load_library() is not None


def _flat(chunk) -> array:
    """[y][z][x] block lists (or a flat array) -> flat uint16 array."""
    if isinstance(chunk, array) and chunk.typecode == "H":
        return chunk
    return array("H", chain.from_iterable(chain.from_iterable(chunk)))


# ------------------------------------------------------------- explosions

def explosion_blocks(get_chunk, x: float, y: float, z: float, power: float, rand: list[float]):
    """Explosion.explode() block rays in C++. get_chunk(cx, cz) -> chunk or None."""
    lib = load_library()
    if lib is None:
        return None
    reach = power * 1.3 / 0.22500001 * 0.3 + 2
    keys, ptrs, ymin, rows, _keep = _chunk_set(get_chunk, x, y, z, reach)
    out = (ctypes.c_int32 * (3 * 65536))()
    rnd = (ctypes.c_double * len(rand))(*rand)
    n = lib.vrs_explosion_blocks(len(_keep), keys, ptrs, ymin, rows, x, y, z, power, rnd, out, 65536)
    return [(out[k * 3], out[k * 3 + 1], out[k * 3 + 2]) for k in range(max(0, n))]


class ExposureContext:
    """Chunk slices around an explosion for repeated getSeenPercent calls."""

    def __init__(self, get_chunk, x: float, y: float, z: float, reach: float):
        self.lib = load_library()
        self.chunks = _chunk_set(get_chunk, x, y, z, reach + 3) if self.lib is not None else None

    def exposure(self, center, box) -> float:
        (x0, y0, z0), (x1, y1, z1) = box
        keys, ptrs, ymin, rows, keep = self.chunks
        return self.lib.vrs_exposure(len(keep), keys, ptrs, ymin, rows, center[0], center[1], center[2],
                                     x0, y0, z0, x1, y1, z1)


def _chunk_set(get_chunk, x: float, y: float, z: float, reach: float):
    """The rows of the chunks within reach, as flat uint16 buffers."""
    import math
    ymin = max(-64, math.floor(y - reach))
    ymax = min(319, math.floor(y + reach))
    rows = max(0, ymax - ymin + 1)
    keys, buffers = [], []
    for cx in range(math.floor(x - reach) >> 4, (math.floor(x + reach) >> 4) + 1):
        for cz in range(math.floor(z - reach) >> 4, (math.floor(z + reach) >> 4) + 1):
            chunk = get_chunk(cx, cz)
            if chunk is None:
                continue
            keys.extend((cx, cz))
            if isinstance(chunk, array):
                buffers.append(chunk[(ymin + 64) * 256:(ymax + 65) * 256])
            else:
                buffers.append(array("H", chain.from_iterable(chain.from_iterable(chunk[ymin + 64:ymax + 65]))))
    key_arr = (ctypes.c_int32 * max(1, len(keys)))(*keys)
    ptr_arr = (ctypes.c_void_p * max(1, len(buffers)))(*[b.buffer_info()[0] for b in buffers])
    return key_arr, ptr_arr, ymin, rows, buffers


# ------------------------------------------------------------------ engine

class NativeRedstoneEngine(RedstoneEngine):
    """RedstoneEngine on top of native/vanilla (plus vanilla hoppers)."""

    REFRESH_TICKS = 100     # re-read chunks from storage this often (writes that bypass the engine)

    def __init__(self, server):
        lib = load_library()
        if lib is None:
            raise RuntimeError("native engine unavailable")
        lib.vrs_reset()                                        # fresh state for this server
        self.lib = lib
        self.server = server
        self.level = None
        self.visual_updates: list = []
        self.pending_effects: list = []
        self.block_actions: list = []
        self._item_keys: dict = {}
        self._item_proto: list = [None]
        self._ticks_since_refresh = 0
        self._buf = (ctypes.c_int32 * (6 * 4096))()
        from ..inventory import ItemStack
        bone_meal = self._item_key(ItemStack("minecraft:bone_meal", 1))
        self._callbacks = (LOAD_CHUNK(self._cb_load_chunk), CONTAINER_SIGNAL(self._cb_container_signal),
                           ENTITY_COUNT(self._cb_entity_count), INV_GET(self._cb_inv_get),
                           CAN_PLACE(self._cb_can_place), TAKE(self._cb_take), GIVE(self._cb_give),
                           PICKUP(self._cb_pickup), COMPOST(self._cb_compost))
        lib.vrs_set_callbacks(*self._callbacks[:3])
        lib.vrs_set_hopper_callbacks(*self._callbacks[3:], bone_meal)
        self._block_names = self._registry_names()
        self._load_ticks()

    @staticmethod
    def _registry_names() -> dict:
        from ..chunk_io import _find_blocks_json
        with open(_find_blocks_json(), "r", encoding="utf-8") as f:
            return {b["id"]: "minecraft:" + b["name"] for b in json.load(f)}

    # -------------------------------------------------------------- callbacks

    def _cb_load_chunk(self, cx, cz, out):
        try:
            storage = getattr(self.server, "world_storage", None)
            chunk = storage.load_generated_chunk(cx, cz) if storage is not None else None
            if chunk is None:
                return 0
            flat = _flat(chunk)
            if len(flat) != CHUNK_BYTES // 2:
                return 0
            ctypes.memmove(out, flat.buffer_info()[0], CHUNK_BYTES)
            return 1
        except Exception:
            logger.exception("native engine: chunk load failed")
            return 0

    def _cb_container_signal(self, x, y, z):
        try:
            from .blocks import container_signal
            return container_signal((x, y, z))
        except Exception:
            return 0

    def _cb_entity_count(self, x, y, z, mode):
        try:
            if mode == 3:
                from types import SimpleNamespace
                return int(registry().get("minecraft:tripwire")._entities_inside(
                    SimpleNamespace(server=self.server), (x, y, z)))
            return _plate_count(self.server, x, y, z, mode)
        except Exception:
            logger.exception("native engine: entity query failed")
            return 0

    def _item_key(self, stack) -> int:
        """Small integer for an item kind (id + damage + components); equal keys stack together."""
        ident = (stack.item_id, stack.damage, repr(sorted(stack.nbt.items())) if stack.nbt else "")
        key = self._item_keys.get(ident)
        if key is None:
            key = len(self._item_proto)
            self._item_keys[ident] = key
            proto = stack.copy()
            proto.count = 1
            self._item_proto.append(proto)
        return key

    def _owner_container(self, kind, a, b, c):
        """The ContainerData holding an owner's slots (kind 0: block at a,b,c; kind 1: entity a)."""
        if kind == 1:
            manager = getattr(self.server, "entity_manager", None)
            entity = manager.get_entity(a) if manager is not None else None
            if entity is None or not getattr(entity, "alive", True):
                return None
            return getattr(entity, "container", None)
        from ..block_behavior import container_manager
        return container_manager.get_container(a, b, c)

    def _cb_inv_get(self, kind, a, b, c, face, out, cap):
        """Slots of the container at a block (block container, else a container minecart there) or of an entity."""
        try:
            records = []          # (owner kind, a, b, c, slot, stack, flags)
            if kind == 1:
                container = self._owner_container(1, a, 0, 0)
                if container is None:
                    return -1
                records = [(1, a, 0, 0, i, stack, 5) for i, stack in enumerate(container.items)]
            else:
                from ..block_behavior import container_view
                view = container_view(a, b, c)
                if view is not None:
                    records = self._block_slots(view, (a, b, c), face)
                else:
                    from ..minecart import container_minecarts_at
                    carts = container_minecarts_at(self.server, a, b, c)
                    if not carts:
                        return -1
                    cart = carts[0]
                    records = [(1, cart.entity_id, 0, 0, i, stack, 5) for i, stack in enumerate(cart.container.items)]
            n = 0
            for okind, oa, ob, oc, slot, stack, flags in records[:cap]:
                empty = stack is None or stack.is_empty
                base = n * 9
                out[base] = okind
                out[base + 1] = oa
                out[base + 2] = ob
                out[base + 3] = oc
                out[base + 4] = slot
                out[base + 5] = 0 if empty else self._item_key(stack)
                out[base + 6] = 0 if empty else stack.count
                out[base + 7] = 64 if empty else stack.max_stack_size
                out[base + 8] = flags
                n += 1
            return n
        except Exception:
            logger.exception("native engine: container read failed")
            return -1

    @staticmethod
    def _block_slots(view, pos, face):
        items = view.items
        if getattr(view, "type", "") in FURNACES and len(items) >= 3:
            # AbstractFurnaceBlockEntity.getSlotsForFace
            records = []
            for slot in {0: [2, 1], 1: [0], 6: [0, 1, 2]}.get(face, [1]):
                stack = items[slot]
                if slot == 2:
                    flags = 4                           # result: take only
                elif slot == 1:
                    flags = 2                           # fuel: fuel items only; empty buckets come out downwards
                    if face == 0 and stack is not None and not stack.is_empty \
                            and stack.item_id in ("minecraft:bucket", "minecraft:water_bucket"):
                        flags |= 4
                else:
                    flags = 1 | 4
                records.append((0, pos[0], pos[1], pos[2], slot, stack, flags))
            return records
        owner_of = getattr(view, "owner_of", None)
        records = []
        for index in range(len(items)):
            if owner_of is not None:
                (ox, oy, oz), slot = owner_of(index)
            else:
                (ox, oy, oz), slot = pos, index
            records.append((0, ox, oy, oz, slot, items[index], 1 | 4))
        return records

    def _cb_can_place(self, kind, a, b, c, slot, item, face):
        try:
            from ..crafting import FUEL_VALUES
            proto = self._item_proto[item]
            return 1 if proto is not None and (FUEL_VALUES.get(proto.item_id, 0) > 0
                                               or proto.item_id == "minecraft:bucket") else 0
        except Exception:
            return 0

    def _cb_take(self, kind, a, b, c, slot, count):
        try:
            container = self._owner_container(kind, a, b, c)
            if container is None:
                return
            stack = container.items[slot]
            if stack is None or stack.is_empty:
                return
            stack.count -= count
            if stack.count <= 0:
                container.items[slot] = None
        except Exception:
            logger.exception("native engine: hopper take failed")

    def _cb_give(self, kind, a, b, c, slot, item, count):
        try:
            container = self._owner_container(kind, a, b, c)
            proto = self._item_proto[item] if 0 < item < len(self._item_proto) else None
            if container is None or proto is None:
                return
            existing = container.items[slot]
            if existing is None or existing.is_empty:
                stack = proto.copy()
                stack.count = count
                container.items[slot] = stack
            else:
                existing.count += count
        except Exception:
            logger.exception("native engine: hopper give failed")

    def _cb_compost(self, item):
        proto = self._item_proto[item] if 0 < item < len(self._item_proto) else None
        if proto is None:
            return 0.0
        from ..composter import compost_chance
        return compost_chance(proto.item_id)

    def _cb_pickup(self, kind, a, b, c):
        """HopperBlockEntity.addItem(container, ItemEntity) for the items in the suck area."""
        try:
            from ..inventory import ItemStack
            manager = getattr(self.server, "entity_manager", None)
            if manager is None:
                return 0
            if kind == 1:
                cart = manager.get_entity(a)
                container = getattr(cart, "container", None)
                if container is None:
                    return 0
                (x0, y0, z0), (x1, y1, z1) = cart.bounding_box()
                box = (x0 - 0.25, y0, z0 - 0.25, x1 + 0.25, y1, z1 + 0.25)
            else:
                from ..block_behavior import container_manager
                container = container_manager.get_container(a, b, c)
                if container is None:
                    return 0
                box = (a, b + 0.6875, c, a + 1, b + 2, c + 1)       # Hopper.SUCK shape
            absorbed = False
            for entity in manager.list_entities():
                if entity.kind != "item" or not getattr(entity, "alive", True):
                    continue
                if not (box[0] <= entity.x < box[3] and box[1] <= entity.y < box[4] and box[2] <= entity.z < box[5]):
                    continue
                item_name = getattr(entity, "item_name", None) or entity.metadata.get("item_name")
                remaining = int(getattr(entity, "count", entity.metadata.get("count", 1)))
                max_size = ItemStack(item_name, 1).max_stack_size
                for index, stack in enumerate(container.items):
                    if remaining <= 0:
                        break
                    if stack is None or stack.is_empty:
                        put = min(remaining, max_size)
                        container.items[index] = ItemStack(item_name, put)
                        remaining -= put
                    elif stack.item_id == item_name and not stack.nbt and stack.count < max_size:
                        put = min(remaining, max_size - stack.count)
                        stack.count += put
                        remaining -= put
                if remaining <= 0:
                    entity.alive = False
                    entity.count = 0
                    absorbed = True
                else:
                    entity.count = remaining
                    entity.metadata["count"] = remaining
            return 1 if absorbed else 0
        except Exception:
            logger.exception("native engine: hopper pickup failed")
            return 0

    # ------------------------------------------------------------------ steps

    def tick(self):
        lib = self.lib
        self._ticks_since_refresh += 1
        if self._ticks_since_refresh >= self.REFRESH_TICKS:
            self._ticks_since_refresh = 0
            lib.vrs_invalidate_all()
        if not lib.vrs_tick():
            logger.warning("Native redstone tick failed")
        hoppers = self._hopper_positions()
        if hoppers:
            arr = (ctypes.c_int32 * (len(hoppers) * 3))(*chain.from_iterable(hoppers))
            lib.vrs_tick_hoppers(arr, len(hoppers))
        try:
            from ..minecart import hopper_minecarts
            carts = hopper_minecarts(self.server)
        except Exception:
            carts = []
        if carts:
            n = len(carts)
            ids = (ctypes.c_int32 * n)(*[c.entity_id for c in carts])
            xyz = (ctypes.c_double * (3 * n))(*chain.from_iterable((c.x, c.y, c.z) for c in carts))
            enabled = (ctypes.c_uint8 * n)(*[1 if c.enabled else 0 for c in carts])
            lib.vrs_tick_hopper_minecarts(ids, xyz, enabled, n)
        self._finish_step()

    def _hopper_positions(self) -> list:
        try:
            from ..block_behavior import container_manager
        except Exception:
            return []
        return [pos for pos, c in container_manager.containers.items() if c.type == "hopper"]

    def on_block_change(self, x: int, y: int, z: int, old_block, new_block, by_player: bool = True):
        old, new = int(old_block or 0), int(new_block or 0)
        storage = getattr(self.server, "world_storage", None)
        if storage is not None:
            chunk = storage.load_generated_chunk(int(x) >> 4, int(z) >> 4)
            if chunk is not None:
                new = int(chunk[int(y) + 64][int(z) & 15][int(x) & 15])
        if not self.lib.vrs_block_changed(int(x), int(y), int(z), old, new, 1 if by_player else 0):
            logger.warning(f"Native redstone update failed after change at {(x, y, z)}")
        self._finish_step()

    def mirror_block(self, x: int, y: int, z: int, state: int):
        self.lib.vrs_mirror_block(int(x), int(y), int(z), int(state))

    def invalidate_chunk(self, cx: int, cz: int):
        self.lib.vrs_invalidate_chunk(int(cx), int(cz))

    def invalidate_all(self):
        self.lib.vrs_invalidate_all()

    def on_container_changed(self, x: int, y: int, z: int):
        self.lib.vrs_container_changed(int(x), int(y), int(z))
        self._finish_step()

    def on_player_interact(self, x: int, y: int, z: int, player) -> bool:
        storage = getattr(self.server, "world_storage", None)
        state = self.lib.vrs_get_block(int(x), int(y), int(z))
        if name_of(state) == "minecraft:redstone_wire" and _holds_placeable_item(player):
            return False
        handled = bool(self.lib.vrs_use(int(x), int(y), int(z)))
        self._finish_step()
        return handled

    def on_entity_move(self, x: int, y: int, z: int):
        self.lib.vrs_entity_inside(int(x), int(y), int(z))
        if self.lib.vrs_pending_changes():
            self._finish_step()

    # ---------------------------------------------------------------- outputs

    def _drain(self, fn, width):
        buf = self._buf
        cap = len(buf) // width
        rows = []
        while True:
            n = fn(buf, cap)
            rows.extend(tuple(buf[k * width:(k + 1) * width]) for k in range(n))
            if n < cap:
                return rows

    def _finish_step(self):
        lib = self.lib
        for kind, x, y, z, a, b in self._drain(lib.vrs_drain_effects, 6):
            pos = (x, y, z)
            if kind == FX_DROP:
                self.pending_effects.append(("drop", {"pos": pos, "state": a}))
            elif kind == FX_SOUND:
                self.pending_effects.append(("sound", {"pos": pos, "sound": SOUNDS.get(a, ""), "pitch": b / 100.0}))
            elif kind == FX_NOTE:
                self.pending_effects.append(("note", {"x": x, "y": y, "z": z, "note": a}))
            elif kind == FX_BURNOUT:
                self.pending_effects.append(("torch_burnout", {"pos": pos}))
            elif kind == FX_PRIME_TNT:
                manager = getattr(self.server, "entity_manager", None)
                if manager is not None:
                    manager.create_tnt(x + 0.5, y, z + 0.5)
            elif kind == FX_DISPENSE:
                self._dispense({"pos": pos, "facing": DIR_NAMES[a] if 0 <= a < 6 else "north",
                                "block": "minecraft:dropper" if b else "minecraft:dispenser"})
        for x, y, z, block_id, event, param in self._drain(lib.vrs_drain_actions, 6):
            self.block_actions.append(((x, y, z), self._block_names.get(block_id, "minecraft:air"), event, param))
        for kind, a, b, c in self._drain(lib.vrs_drain_hopper_changes, 4):
            if kind == 0:
                self.pending_effects.append(("container_changed", {"pos": (a, b, c)}))
            else:
                self.pending_effects.append(("container_changed", {"entity_id": a}))
        changes = self._drain(lib.vrs_drain_changes, 4)
        if changes:
            self._apply_changes(changes)

    def _apply_changes(self, changes):
        storage = getattr(self.server, "world_storage", None)
        final: dict = {}
        for x, y, z, state in changes:
            final[(x, y, z)] = state
        if storage is not None:
            chunks: dict = {}
            for (x, y, z), state in final.items():
                key = (x >> 4, z >> 4)
                chunk = chunks.get(key)
                if chunk is None:
                    chunk = storage.load_generated_chunk(*key)
                    if chunk is None:
                        continue
                    chunks[key] = chunk
                chunk[y + 64][z & 15][x & 15] = state
            for (cx, cz), chunk in chunks.items():
                storage.save_generated_chunk(cx, cz, chunk)
        self.visual_updates.extend((x, y, z, s) for (x, y, z), s in final.items())

    def drain_block_actions(self) -> list:
        actions, self.block_actions = self.block_actions, []
        return actions

    def _dispense(self, payload):
        from ..block_behavior import container_manager
        from .core import VEC
        x, y, z = payload["pos"]
        container = container_manager.get_container(x, y, z)
        if container is None:
            return
        for index, stack in enumerate(container.items):
            if stack is None or stack.is_empty:
                continue
            item_name = stack.item_id
            stack.count -= 1
            if stack.count <= 0:
                container.items[index] = None
            dx, dy, dz = VEC.get(payload.get("facing") or "north", (0, 0, -1))
            manager = getattr(self.server, "entity_manager", None)
            if manager is not None:
                entity = manager.create_item(x + 0.5 + dx * 0.7, y + 0.5 + dy * 0.7 - 0.15, z + 0.5 + dz * 0.7,
                                             item_name=item_name, count=1)
                entity.vx, entity.vy, entity.vz = dx * 0.2, 0.1 + dy * 0.2, dz * 0.2
                self.pending_effects.append(("entity_spawn", {"entity_id": entity.entity_id}))
            self.pending_effects.append(("sound", {"pos": (x, y, z), "sound": "minecraft:block.dispenser.dispense"}))
            self.lib.vrs_container_changed(x, y, z)
            return
        self.pending_effects.append(("sound", {"pos": (x, y, z), "sound": "minecraft:block.dispenser.fail"}))

    # ------------------------------------------------------------ persistence

    def save(self):
        self.lib.vrs_finish_pistons()
        self._finish_step()
        path = self._ticks_path()
        if path is None:
            return
        index_names = {}
        ticks = []
        for x, y, z, block, delay, priority in self._drain_export(self.lib.vrs_export_ticks, 6):
            name = index_names.get(block)
            if name is None:
                name = index_names[block] = self._index_name(block)
            ticks.append([[x, y, z], name, delay, priority])
        comparators = [[[x, y, z], v] for x, y, z, v in self._drain_export(self.lib.vrs_export_comparators, 4)]
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"ticks": ticks, "comparators": comparators}, f)
            os.replace(path + ".tmp", path)
        except OSError as e:
            logger.warning(f"Could not save scheduled redstone ticks: {e}")

    def _drain_export(self, fn, width):
        count = max(self.lib.vrs_tick_count(), 1) + 4096
        buf = (ctypes.c_int32 * (count * width))()
        n = fn(buf, count)
        return [tuple(buf[k * width:(k + 1) * width]) for k in range(n)]

    def _index_name(self, block_index: int) -> str:
        if not hasattr(self, "_index_to_name"):
            from ..chunk_io import _find_blocks_json
            with open(_find_blocks_json(), "r", encoding="utf-8") as f:
                self._index_to_name = ["minecraft:" + b["name"] for b in json.load(f)]
        return self._index_to_name[block_index] if 0 <= block_index < len(self._index_to_name) else ""

    def _load_ticks(self):
        path = self._ticks_path()
        if path is None or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for pos, block, delay, priority in data.get("ticks", []):
            index = self.lib.vrs_block_index(str(block).encode("utf-8"))
            if index >= 0:
                self.lib.vrs_schedule_tick(int(pos[0]), int(pos[1]), int(pos[2]), index, max(1, int(delay)),
                                           int(priority))
        for pos, value in data.get("comparators", []):
            self.lib.vrs_set_comparator(int(pos[0]), int(pos[1]), int(pos[2]), int(value))

    def comparator_outputs(self) -> dict:
        return {(x, y, z): v for x, y, z, v in self._drain_export(self.lib.vrs_export_comparators, 4)}

    def get_status(self) -> dict:
        return {"scheduled_ticks": self.lib.vrs_tick_count(), "moving_pistons": self.lib.vrs_moving_count(),
                "native": True}


def _plate_count(server, x, y, z, mode) -> int:
    """Entities on a pressure plate (mode 0 any, 1 living only, 2 weighted: items count by stack size)."""
    count = 0
    for player in server.get_online_players() if hasattr(server, "get_online_players") else ():
        if getattr(player, "gamemode", "") == "spectator" or getattr(player, "_dead", False):
            continue
        if x - 0.3 < player.x < x + 1.3 and z - 0.3 < player.z < z + 1.3 and y - 0.1 <= player.y < y + 0.3:
            count += 1
    manager = getattr(server, "entity_manager", None)
    if manager is not None:
        for entity in manager.list_entities():
            if mode == 1 and entity.kind != "mob":
                continue
            if x <= entity.x < x + 1 and z <= entity.z < z + 1 and y - 0.1 <= entity.y < y + 0.3:
                count += int(entity.metadata.get("count", 1)) if entity.kind == "item" else 1
    return count


def create_engine(server):
    """The native engine when it can be loaded, the Python reference engine otherwise."""
    if load_library() is not None:
        try:
            return NativeRedstoneEngine(server)
        except Exception:
            logger.exception("Native engine failed to start; using the Python engine")
    return RedstoneEngine(server)
