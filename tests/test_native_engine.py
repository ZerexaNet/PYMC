"""
The native (C++) engine against the Python reference engine.

* every vanilla redstone test runs again on the native engine;
* random circuits are built and ticked on both engines, which must leave
  exactly the same blocks behind tick by tick;
* native explosion rays / exposure equal the Python ones;
* vanilla hopper transfers.
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rs_harness import S, World  # noqa: E402

from world.rs.native import native_available  # noqa: E402

HAVE_NATIVE = native_available()

# tests that look inside the Python Level object
PYTHON_ONLY = {"test_zero_tick_sticky_piston_spits_block"}


def _native_variants():
    import test_redstone_vanilla as base
    made = {}
    for name in dir(base):
        cls = getattr(base, name)
        if not (isinstance(cls, type) and issubclass(cls, unittest.TestCase) and cls.__module__ == base.__name__):
            continue

        def setUp(self, _orig=cls.setUp):
            World.native = True
            _orig(self)

        def tearDown(self, _orig=cls.tearDown):
            World.native = False
            _orig(self)

        attrs = {"setUp": setUp, "tearDown": tearDown}
        for attr in dir(cls):
            if attr in PYTHON_ONLY:
                attrs[attr] = unittest.skip("inspects the Python engine's internals")(lambda self: None)
        variant = unittest.skipUnless(HAVE_NATIVE, "native engine not built")(
            type("Native" + name, (cls,), attrs))
        made["Native" + name] = variant
    return made


globals().update(_native_variants())


# ---------------------------------------------------------------- random circuits

HORIZ = ("north", "south", "west", "east")
ALL6 = HORIZ + ("up", "down")


def _random_state(rng):
    kind = rng.choice((
        "redstone_wire", "redstone_wire", "redstone_wire", "redstone_torch", "redstone_wall_torch", "repeater",
        "comparator", "observer", "piston", "sticky_piston", "slime_block", "honey_block", "stone", "stone",
        "glass", "redstone_block", "lever", "stone_button", "oak_button", "redstone_lamp", "note_block",
        "oak_trapdoor", "target", "rail", "powered_rail", "detector_rail", "dead_tube_coral_fan",
        "dead_tube_coral_wall_fan", "tnt", "stone_slab", "oak_stairs", "stone_pressure_plate", "air"))
    if kind in ("repeater",):
        return S(kind, facing=rng.choice(HORIZ), delay=str(rng.randint(1, 4)))
    if kind == "comparator":
        return S(kind, facing=rng.choice(HORIZ), mode=rng.choice(("compare", "subtract")))
    if kind in ("observer", "piston", "sticky_piston"):
        return S(kind, facing=rng.choice(ALL6))
    if kind in ("redstone_wall_torch", "dead_tube_coral_wall_fan"):
        return S(kind, facing=rng.choice(HORIZ))
    if kind in ("lever", "stone_button", "oak_button"):
        return S(kind, face=rng.choice(("floor", "wall", "ceiling")), facing=rng.choice(HORIZ))
    if kind == "stone_slab":
        return S(kind, type=rng.choice(("top", "bottom", "double")))
    if kind == "oak_stairs":
        return S(kind, facing=rng.choice(HORIZ), half=rng.choice(("top", "bottom")))
    if kind == "oak_trapdoor":
        return S(kind, facing=rng.choice(HORIZ), half=rng.choice(("top", "bottom")))
    if kind in ("rail", "powered_rail", "detector_rail"):
        shapes = ["north_south", "east_west", "ascending_east", "ascending_west", "ascending_north",
                  "ascending_south"]
        if kind == "rail":
            shapes += ["south_east", "south_west", "north_west", "north_east"]
        return S(kind, shape=rng.choice(shapes))
    return S(kind)


def _snapshot(w, size):
    return [w.get(x, y, z) for x in range(-1, size + 1) for y in range(63, 64 + size) for z in range(-1, size + 1)]


@unittest.skipUnless(HAVE_NATIVE, "native engine not built")
class RandomCircuits(unittest.TestCase):
    SIZE = 5

    def _run(self, seed):
        rng = random.Random(seed)
        script = []
        for _ in range(rng.randint(40, 120)):
            op = rng.random()
            pos = (rng.randrange(self.SIZE), 64 + rng.randrange(self.SIZE - 2), rng.randrange(self.SIZE))
            if op < 0.70:
                script.append(("set", pos, _random_state(rng)))
            elif op < 0.80:
                script.append(("poke", pos, _random_state(rng)))
            elif op < 0.92:
                script.append(("use", pos, None))
            else:
                script.append(("tick", rng.randint(1, 6), None))
        script.append(("tick", 40, None))
        worlds = (World(native=False), World(native=True))
        for step, (op, a, b) in enumerate(script):
            for w in worlds:
                if op == "set":
                    w.set(*a, b)
                elif op == "poke":
                    w.poke(*a, b)
                elif op == "use":
                    w.use(*a)
            if op == "tick":
                for _ in range(a):
                    for w in worlds:
                        w.tick()
                    self._compare(worlds, seed, step)
            else:
                self._compare(worlds, seed, step)

    def _compare(self, worlds, seed, step):
        py, nat = worlds
        a, b = _snapshot(py, self.SIZE), _snapshot(nat, self.SIZE)
        if a != b:
            from world.rs.core import name_of
            diffs = [(i, name_of(x), name_of(y)) for i, (x, y) in enumerate(zip(a, b)) if x != y][:5]
            self.fail(f"seed {seed}, step {step}: blocks differ {diffs}")
        self.assertEqual(len(py.entities), len(nat.entities), f"seed {seed}, step {step}: primed TNT differs")

    def test_random_circuits(self):
        for seed in range(300):
            self._run(seed)


# ------------------------------------------------------------------- explosions

@unittest.skipUnless(HAVE_NATIVE, "native engine not built")
class NativeExplosions(unittest.TestCase):
    def _world(self, seed):
        rng = random.Random(seed)
        w = World(native=False)
        palette = [0, 0, 0, S("stone"), S("dirt"), S("obsidian"), S("glass"), S("water"), S("oak_planks"),
                   S("tnt"), S("short_grass"), S("redstone_wire"), S("snow")]
        for x in range(-10, 11):
            for y in range(56, 74):
                for z in range(-10, 11):
                    w.storage.load_generated_chunk(x >> 4, z >> 4)[y + 64][z & 15][x & 15] = rng.choice(palette)
        return w

    def test_rays_and_exposure_match_python(self):
        from world import explosion
        from world.rs import native
        total = 0
        for seed in range(8):
            w = self._world(seed)
            rng = random.Random(seed)
            center = (rng.uniform(-2, 2), rng.uniform(62, 68), rng.uniform(-2, 2))
            power = rng.choice((2.0, 3.0, 4.0, 6.0))

            def get_block(x, y, z):
                if y < -64 or y > 319:
                    return None
                return w.get(x, y, z)

            def get_chunk(cx, cz):
                return w.storage.load_generated_chunk(cx, cz)

            # the Python version draws one value per ray from its generator; give C++ the same values
            py = set(explosion.affected_blocks(get_block, *center, power, random.Random(seed + 100)))
            r = random.Random(seed + 100)
            nat = native.explosion_blocks(get_chunk, *center, power, [r.random() for _ in range(1352)])
            total += len(py)
            self.assertEqual(len(nat), len(set(nat)))
            self.assertEqual(py, set(nat), f"seed {seed}")
            ctx = native.ExposureContext(get_chunk, center[0], center[1], center[2], power * 2)
            for _ in range(10):
                fx, fy, fz = center[0] + rng.uniform(-6, 6), center[1] + rng.uniform(-3, 3), center[2] + rng.uniform(-6, 6)
                box = ((fx - 0.3, fy, fz - 0.3), (fx + 0.3, fy + 1.8, fz + 0.3))
                self.assertAlmostEqual(explosion._exposure(get_block, center, box), ctx.exposure(center, box),
                                       places=12)
        self.assertGreater(total, 100)


# ---------------------------------------------------------------------- hoppers

@unittest.skipUnless(HAVE_NATIVE, "native engine not built")
class NativeHoppers(unittest.TestCase):
    BASE = (200, 64, 200)

    def setUp(self):
        from world.block_behavior import container_manager
        self.manager = container_manager
        self._saved = dict(container_manager.containers)
        container_manager.containers.clear()
        self.w = World(native=True)

    def tearDown(self):
        self.manager.containers.clear()
        self.manager.containers.update(self._saved)

    def place(self, dx, dy, dz, block, kind=None, **props):
        x, y, z = self.BASE[0] + dx, self.BASE[1] + dy, self.BASE[2] + dz
        self.w.set(x, y, z, S(block, **props))
        if kind:
            container = self.manager.create_container(x, y, z, kind)
            return container
        return None

    @staticmethod
    def count(container, item="minecraft:stone"):
        return sum(s.count for s in container.items if s is not None and not s.is_empty and s.item_id == item)

    def test_chest_to_hopper_to_chest(self):
        from world.inventory import ItemStack
        top = self.place(0, 1, 0, "chest", "chest")
        top.items[0] = ItemStack("minecraft:stone", 5)
        hopper = self.place(0, 0, 0, "hopper", "hopper", facing="east")
        out = self.place(1, 0, 0, "chest", "chest")
        self.w.tick(1)
        # first tick: nothing to push yet, one item pulled from above
        self.assertEqual((self.count(top), self.count(hopper), self.count(out)), (4, 1, 0))
        self.w.tick(8)
        # every 8 game ticks the hopper pushes one item and pulls the next one
        self.assertEqual((self.count(top), self.count(hopper), self.count(out)), (3, 1, 1))
        self.w.tick(8 * 10)
        self.assertEqual((self.count(top), self.count(hopper), self.count(out)), (0, 0, 5))

    def test_powered_hopper_is_locked(self):
        from world.inventory import ItemStack
        top = self.place(0, 1, 0, "chest", "chest")
        top.items[0] = ItemStack("minecraft:stone", 5)
        hopper = self.place(0, 0, 0, "hopper", "hopper", facing="down")
        self.place(1, 0, 0, "redstone_block")
        self.assertEqual(self.w.props(self.BASE[0], self.BASE[1], self.BASE[2])["enabled"], "false")
        self.w.tick(40)
        self.assertEqual(self.count(top), 5)
        self.assertEqual(self.count(hopper), 0)

    def test_comparator_follows_hopper_contents(self):
        from world.inventory import ItemStack
        top = self.place(0, 1, 0, "chest", "chest")
        top.items[0] = ItemStack("minecraft:stone", 64)
        self.place(0, 0, 0, "hopper", "hopper", facing="down")
        self.place(1, 0, 0, "comparator", facing="west")
        self.w.tick(1 + 8 * 4 + 3)
        # 5 items in a 5-slot hopper: 1 + floor(5/64/5 * 14) = 1
        outputs = self.w.engine.comparator_outputs()
        self.assertEqual(outputs.get((self.BASE[0] + 1, self.BASE[1], self.BASE[2])), 1)

    def test_hopper_chain_cooldown(self):
        """An item entering an empty hopper waits there 8 game ticks (cooldown 7 when the target ticked first)."""
        from world.inventory import ItemStack
        first = self.place(0, 0, 0, "hopper", "hopper", facing="east")
        second = self.place(1, 0, 0, "hopper", "hopper", facing="east")
        out = self.place(2, 0, 0, "chest", "chest")
        first.items[0] = ItemStack("minecraft:stone", 1)
        arrived = None
        for t in range(1, 40):
            self.w.tick(1)
            if self.count(out) and arrived is None:
                arrived = t
        self.assertEqual(self.count(first) + self.count(second), 0)
        self.assertEqual(arrived, 8)      # pushed into the second hopper on tick 1, out on tick 8

    def test_furnace_faces(self):
        from world.inventory import ItemStack
        top = self.place(0, 2, 0, "chest", "chest")
        top.items[0] = ItemStack("minecraft:coal", 2)
        top.items[1] = ItemStack("minecraft:raw_iron", 2)
        self.place(0, 1, 0, "hopper", "hopper", facing="down")
        side = self.place(-1, 0, 0, "hopper", "hopper", facing="east")
        side.items[0] = ItemStack("minecraft:stone", 1)        # not a fuel: stays in the side hopper
        side.items[1] = ItemStack("minecraft:coal", 1)
        furnace = self.place(0, 0, 0, "furnace", "furnace")
        self.w.tick(60)
        # from above everything goes into the input slot, from the side only fuel into the fuel slot
        self.assertEqual(furnace.items[0].item_id, "minecraft:coal")
        self.assertEqual(furnace.items[1].item_id, "minecraft:coal")
        self.assertEqual(self.count(side), 1)

    def test_picks_up_item_entities(self):
        from types import SimpleNamespace
        hopper = self.place(0, 0, 0, "hopper", "hopper", facing="down")
        x, y, z = self.BASE
        item = SimpleNamespace(kind="item", x=x + 0.5, y=y + 1.0, z=z + 0.5, item_name="minecraft:stone", count=3,
                               metadata={"item_name": "minecraft:stone", "count": 3}, alive=True)
        self.w.entities.append(item)
        self.w.tick(1)
        self.assertEqual(self.count(hopper), 3)
        self.assertFalse(item.alive)
