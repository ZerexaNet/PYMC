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
        "dead_tube_coral_wall_fan", "tnt", "stone_slab", "oak_stairs", "stone_pressure_plate", "chest", "chest",
        "composter", "air"))
    if kind == "chest":
        return S(kind, facing=rng.choice(HORIZ), type=rng.choice(("single", "single", "left", "right")))
    if kind == "composter":
        return S(kind, level=str(rng.choice((0, 3, 6, 7, 8))))
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

class _ContainerWorld:
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


@unittest.skipUnless(HAVE_NATIVE, "native engine not built")
class NativeHoppers(_ContainerWorld, unittest.TestCase):
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


# ------------------------------------------------- double chests, composters, hopper minecarts

@unittest.skipUnless(HAVE_NATIVE, "native engine not built")
class NativeContainersPlus(_ContainerWorld, unittest.TestCase):
    def test_chests_join_and_split(self):
        from world.placement import placement_states
        x, y, z = self.BASE
        for native in (False, True):
            w = World(native=native)
            w.set(x, y, z, S("chest", facing="north"))
            # a player looking south (chests face the player: north) places a chest east of it: the two join
            (pos, state), = placement_states("minecraft:chest", 1, (0.5, 1.0, 0.5), 0.0, 0.0, (x + 1, y, z), 0,
                                             w.get)
            w.set(*pos, state)
            self.assertEqual((w.props(x, y, z)["type"], w.props(x + 1, y, z)["type"]), ("left", "right"))
            w.set(x + 1, y, z, 0)                       # breaking one half splits the other
            self.assertEqual(w.props(x, y, z)["type"], "single")

    def test_hopper_fills_double_chest_first_half_first(self):
        from world.block_behavior import container_view
        from world.inventory import ItemStack
        x, y, z = self.BASE
        left = self.place(0, 0, 0, "chest", "chest", facing="north", type="left")
        right = self.place(1, 0, 0, "chest", "chest", facing="north", type="right")
        view = container_view(x, y, z)
        self.assertEqual(len(view.items), 54)
        self.assertEqual(view.positions, ((x + 1, y, z), (x, y, z)))        # the RIGHT half comes first
        for i in range(27):
            right.items[i] = ItemStack("minecraft:stone", 64)
        hopper = self.place(0, 1, 0, "hopper", "hopper", facing="down")      # above the LEFT half
        hopper.items[0] = ItemStack("minecraft:dirt", 3)
        self.place(0, 0, 1, "comparator", facing="north")                    # reads the whole double chest
        self.w.tick(1 + 8 * 3 + 4)
        self.assertEqual(self.count(left, "minecraft:dirt"), 3)              # right half full: into the left
        self.assertEqual(self.w.engine.comparator_outputs().get((x, y, z + 1)), 8)   # 27.05/54 slots

    def test_hopper_below_double_chest_pulls_from_both_halves(self):
        from world.inventory import ItemStack
        left = self.place(0, 1, 0, "chest", "chest", facing="north", type="left")
        right = self.place(1, 1, 0, "chest", "chest", facing="north", type="right")
        left.items[5] = ItemStack("minecraft:stone", 1)
        right.items[3] = ItemStack("minecraft:dirt", 1)
        hopper = self.place(0, 0, 0, "hopper", "hopper", facing="down")
        self.place(0, -1, 0, "barrel", "barrel")
        self.w.tick(1)
        self.assertEqual(self.count(hopper, "minecraft:dirt"), 1)            # slot 3 of the first (right) half
        self.w.tick(8)
        self.assertEqual(self.count(right, "minecraft:dirt") + self.count(left), 0)

    def test_composter_with_hoppers(self):
        from world.inventory import ItemStack
        x, y, z = self.BASE
        top = self.place(0, 2, 0, "hopper", "hopper", facing="down")
        top.items[0] = ItemStack("minecraft:pumpkin_pie", 7)                 # chance 1.0: one level per item
        top.items[1] = ItemStack("minecraft:stone", 5)                       # not compostable: stays
        self.place(0, 1, 0, "composter")
        bottom = self.place(0, 0, 0, "hopper", "hopper", facing="east")
        out = self.place(1, 0, 0, "chest", "chest")
        self.place(1, 1, 1, "comparator", facing="north")                    # dummy, keeps chunk busy
        levels = []
        for _ in range(8 * 7 + 30):
            self.w.tick(1)
            levels.append(int(self.w.props(x, y + 1, z)["level"]))
        # 7 items -> level 7; 20 ticks later it is ready (8) and the hopper below empties it in that same tick
        # (block ticks run before block entities)
        self.assertEqual(levels.count(7), 20)
        self.assertEqual(levels[-1], 0)
        self.assertEqual(self.count(bottom, "minecraft:bone_meal") + self.count(out, "minecraft:bone_meal"), 1)
        self.assertEqual(self.count(top, "minecraft:stone"), 5)
        self.assertEqual(self.count(top, "minecraft:pumpkin_pie"), 0)

    def _cart(self, dx, dy, dz, variant="hopper_minecart"):
        from world.minecart import MinecartEntity
        x, y, z = self.BASE
        cart = MinecartEntity(self.w.server.get_next_entity_id(), x + dx + 0.5, y + dy + 0.0625, z + dz + 0.5, variant)
        self.w.entities.append(cart)
        return cart

    def test_hopper_minecart_sucks_every_tick(self):
        from world.inventory import ItemStack
        top = self.place(0, 1, 0, "chest", "chest")
        top.items[0] = ItemStack("minecraft:stone", 10)
        self.place(0, 0, 0, "rail")
        cart = self._cart(0, 0, 0)
        self.w.tick(4)
        self.assertEqual(self.count(cart.container), 4)                     # no cooldown: one item per tick
        # a powered activator rail locks it
        self.place(0, 0, 1, "redstone_block")
        self.w.set(self.BASE[0], self.BASE[1], self.BASE[2], S("activator_rail"))
        self.assertEqual(self.w.props(*self.BASE)["powered"], "true")
        cart.tick(self.w.server)
        self.assertFalse(cart.enabled)
        self.w.tick(4)
        self.assertEqual(self.count(cart.container), 4)

    def test_hoppers_push_into_and_pull_from_minecarts(self):
        from world.inventory import ItemStack
        self.place(0, 0, 0, "rail")
        cart = self._cart(0, 0, 0)
        feeder = self.place(-1, 0, 0, "hopper", "hopper", facing="east")    # pushes into the cart
        feeder.items[0] = ItemStack("minecraft:stone", 2)
        below = self.place(0, -1, 0, "hopper", "hopper", facing="down")     # pulls from the cart above
        self.place(0, -2, 0, "chest", "chest")
        self.w.tick(1)
        self.assertEqual(self.count(cart.container) + self.count(below), 1)
        self.w.tick(40)
        self.assertEqual(self.count(feeder), 0)
        self.assertEqual(self.count(cart.container), 0)

    def test_hopper_minecart_picks_up_items(self):
        from types import SimpleNamespace
        x, y, z = self.BASE
        self.place(0, 0, 0, "rail")
        cart = self._cart(0, 0, 0)
        item = SimpleNamespace(kind="item", entity_id=5, x=x + 0.6, y=y + 0.2, z=z + 0.4, alive=True,
                               item_name="minecraft:dirt", count=70, metadata={"item_name": "minecraft:dirt",
                                                                                "count": 70})
        self.w.entities.append(item)
        self.w.tick(1)
        self.assertEqual(self.count(cart.container, "minecraft:dirt"), 70)
        self.assertFalse(item.alive)


    def test_brewing_stand_faces(self):
        from world.inventory import ItemStack
        top = self.place(0, 2, 0, "hopper", "hopper", facing="down")
        top.items[0] = ItemStack("minecraft:dirt", 1)                        # not an ingredient: stays
        top.items[1] = ItemStack("minecraft:nether_wart", 2)
        side = self.place(-1, 1, 0, "hopper", "hopper", facing="east")
        side.items[0] = ItemStack("minecraft:potion", 3, 0, {"potion": "water"})
        side.items[1] = ItemStack("minecraft:blaze_powder", 1)
        stand = self.place(0, 1, 0, "brewing_stand", "brewing_stand")
        self.w.tick(80)
        # from above only the ingredient slot; from the side the bottles and the fuel
        self.assertEqual((stand.items[3].item_id, stand.items[3].count), ("minecraft:nether_wart", 2))
        self.assertEqual([stand.items[i].count for i in range(3)], [1, 1, 1])
        self.assertEqual(stand.items[4], None)
        self.assertEqual(self.count(top, "minecraft:dirt"), 1)
        self.assertEqual(self.count(side, "minecraft:potion"), 0)

    def test_brewing_makes_awkward_potions_and_state(self):
        from world.inventory import ItemStack
        from world.block_behavior import BREW_TIME
        stand = self.place(0, 1, 0, "brewing_stand", "brewing_stand")
        for i in range(3):
            stand.items[i] = ItemStack("minecraft:potion", 1, 0, {"potion": "water"})
        stand.items[3] = ItemStack("minecraft:nether_wart", 2)
        stand.items[4] = ItemStack("minecraft:blaze_powder", 1)
        self.w.tick(BREW_TIME - 1)
        self.assertEqual(stand.items[0].nbt, {"potion": "water"})          # not finished yet
        self.assertEqual(self.w.props(self.BASE[0], self.BASE[1] + 1, self.BASE[2])["has_bottle_0"], "true")
        self.w.tick(2)
        self.assertEqual([stand.items[i].nbt["potion"] for i in range(3)], ["awkward"] * 3)
        self.assertEqual(stand.items[3].count, 1)                          # one ingredient per brew
        self.assertIsNone(stand.items[4])                                  # the blaze powder went into the fuel
        self.assertEqual(stand.brew_fuel, 19)
        self.w.tick(BREW_TIME * 2)                                          # awkward + wart: nothing to brew
        self.assertEqual(stand.items[3].count, 1)
        self.assertEqual(stand.brew_time, 0)

    def test_brewing_needs_fuel_and_a_valid_mix(self):
        from world.inventory import ItemStack
        from world.block_behavior import BREW_TIME
        stand = self.place(0, 1, 0, "brewing_stand", "brewing_stand")
        stand.items[0] = ItemStack("minecraft:potion", 1, 0, {"potion": "awkward"})
        stand.items[3] = ItemStack("minecraft:glowstone_dust", 1)
        self.w.tick(5)
        self.assertEqual(stand.brew_time, 0)                                # no fuel: no brew
        stand.items[4] = ItemStack("minecraft:blaze_powder", 1)
        self.w.tick(BREW_TIME + 1)
        self.assertEqual(stand.items[0].nbt["potion"], "awkward")          # glowstone does not mix awkward potions
        self.assertEqual(stand.items[3].count, 1)                           # and nothing was used up
        self.assertEqual(stand.brew_fuel, 20)                               # fuel is only spent when a brew starts
        stand.items[3] = ItemStack("minecraft:glistering_melon_slice", 1)
        self.w.tick(BREW_TIME + 1)
        self.assertEqual(stand.items[0].nbt["potion"], "healing")
        self.assertIsNone(stand.items[3])

    def test_brewing_stand_survives_save_and_load(self):
        from world.block_behavior import ContainerData
        from world.inventory import ItemStack
        data = ContainerData(type="brewing_stand")
        data.brew_time, data.brew_fuel = 123, 7
        data.items[3] = ItemStack("minecraft:nether_wart", 1)
        loaded = ContainerData.from_dict(data.to_dict())
        self.assertEqual((loaded.brew_time, loaded.brew_fuel, loaded.items[3].item_id), (123, 7, "minecraft:nether_wart"))

    def test_detector_rail_sees_minecarts_in_both_engines(self):
        from world.inventory import ItemStack
        from world.minecart import MinecartEntity
        results = []
        for native in (False, True):
            w = World(native=native)
            w.set(0, 64, 0, S("detector_rail", shape="east_west"))
            w.set(0, 64, 1, S("comparator", facing="north"))
            w.set(0, 64, -1, S("redstone_lamp"))
            cart = MinecartEntity(50, 0.5, 64.0625, 0.5, "hopper_minecart")
            cart.container.items[0] = ItemStack("minecraft:stone", 64)
            w.entities.append(cart)
            cart.tick(w.server)
            w.tick(4)
            on = (w.props(0, 64, 0)["powered"], w.props(0, 64, -1)["lit"],
                  w.engine.comparator_outputs().get((0, 64, 1)))
            cart.alive = False
            w.tick(25)
            results.append((on, w.props(0, 64, 0)["powered"], w.props(0, 64, -1)["lit"]))
        self.assertEqual(results[0], ((("true", "true", 3), "false", "false")))   # 64 of 5*64 items: 3
        self.assertEqual(results[0], results[1])


class MinecartMovement(unittest.TestCase):
    def _track(self, w, length=30):
        for x in range(-length, length):
            w.set(x, 64, 0, S("rail", shape="east_west"))

    def test_minecarts_bump_into_each_other(self):
        from world.minecart import MinecartEntity
        w = World(native=False)
        self._track(w)
        a = MinecartEntity(1, 0.5, 64.0625, 0.5, "minecart")
        b = MinecartEntity(2, 3.5, 64.0625, 0.5, "minecart")
        a.yaw = b.yaw = 0.0
        a.vx = 0.3
        w.entities.extend([a, b])
        for _ in range(30):
            for cart in (a, b):
                cart.tick(w.server)
        self.assertGreater(b.vx, 0.0)                                       # b got pushed along
        self.assertGreater(b.x, 3.5)
        self.assertGreater(b.x - a.x, 0.9)                                  # they do not pass through

    def test_player_pushes_minecart(self):
        from types import SimpleNamespace
        from world.minecart import MinecartEntity
        w = World(native=False)
        self._track(w)
        cart = MinecartEntity(1, 0.5, 64.0625, 0.5, "minecart")
        player = SimpleNamespace(x=-0.2, y=64.0, z=0.5, gamemode="survival", vehicle=None)
        w.server.get_online_players = lambda: [player]
        for _ in range(10):
            cart.tick(w.server)
        self.assertGreater(cart.x, 0.6)

    def test_riding_and_steering(self):
        from types import SimpleNamespace
        from world.minecart import MinecartEntity, dismount, mount
        w = World(native=False)
        self._track(w)
        cart = MinecartEntity(1, 0.5, 64.0625, 0.5, "minecart")
        player = SimpleNamespace(x=0.0, y=64.0, z=0.0, yaw=-90.0, gamemode="survival", alive=True)
        player.vehicle = None
        self.assertTrue(mount(cart, player))
        player.vehicle_input = (1.0, 0.0)                                     # W, looking east (yaw -90)
        for _ in range(40):
            cart.tick(w.server)
        self.assertGreater(cart.x, 2.0)
        self.assertAlmostEqual(player.x, cart.x)
        self.assertIs(dismount(player), cart)
        self.assertIsNone(cart.passenger)
        hopper_cart = MinecartEntity(2, 5.5, 64.0625, 0.5, "hopper_minecart")
        self.assertFalse(mount(hopper_cart, player))                         # only plain minecarts carry players

    def test_rides_along_rails_and_curves(self):
        from world.minecart import MinecartEntity
        w = World(native=False)
        for x in range(0, 4):
            w.set(x, 64, 0, S("rail", shape="east_west"))
        w.set(4, 64, 0, S("rail", shape="south_west"))
        for z in range(1, 10):
            w.set(4, 64, z, S("rail", shape="north_south"))
        cart = MinecartEntity(1, 0.5, 64.0625, 0.5, "minecart")
        cart.vx = 0.4
        for _ in range(60):
            cart.tick(w.server)
        self.assertAlmostEqual(cart.x, 4.5, places=6)                        # turned the corner
        self.assertGreater(cart.z, 1.0)

    def test_powered_rail_starts_from_a_wall(self):
        from world.minecart import MinecartEntity
        w = World(native=False)
        w.set(-1, 64, 0, S("stone"))
        w.set(0, 64, 1, S("redstone_block"))
        w.set(0, 64, 0, S("powered_rail", shape="east_west"))
        for x in range(1, 20):
            w.set(x, 64, 0, S("rail", shape="east_west"))
        cart = MinecartEntity(1, 0.5, 64.0625, 0.5, "minecart")
        for _ in range(40):
            cart.tick(w.server)
        self.assertGreater(cart.x, 3.0)

    def test_save_and_load(self):
        import tempfile
        from world.inventory import ItemStack
        from world.minecart import MinecartEntity, load_minecarts, save_minecarts
        w = World(native=False)
        cart = MinecartEntity(7, 3.5, 64.0625, 2.5, "hopper_minecart")
        cart.container.items[2] = ItemStack("minecraft:diamond", 5)
        w.entities.append(cart)
        with tempfile.TemporaryDirectory() as d:
            save_minecarts(w.server, d)
            w2 = World(native=False)
            self.assertEqual(load_minecarts(w2.server, d), 1)
        loaded = w2.entities[0]
        self.assertEqual((loaded.variant, loaded.x, loaded.container.items[2].item_id,
                          loaded.container.items[2].count), ("hopper_minecart", 3.5, "minecraft:diamond", 5))
