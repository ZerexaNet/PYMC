"""Vanilla 1.21.1 redstone behaviour, including the quirks technical players use."""

import unittest

from rs_harness import World, S
from world.rs.core import blockpos_hash, java_hash_order


def row(w, xs, y=64, z=0):
    return [w.name(x, y, z) for x in xs]


class WireAndComponents(unittest.TestCase):
    def test_wire_decays_one_per_block(self):
        w = World()
        w.set(0, 64, 0, S("lever", face="floor", facing="east"))
        for x in range(1, 17):
            w.set(x, 64, 0, S("redstone_wire"))
        w.use(0, 64, 0)
        self.assertEqual([int(w.props(x, 64, 0)["power"]) for x in range(1, 17)], list(range(15, -1, -1)))
        w.use(0, 64, 0)
        self.assertTrue(all(w.props(x, 64, 0)["power"] == "0" for x in range(1, 17)))

    def test_lamp_turns_on_at_once_and_off_after_4_ticks(self):
        w = World()
        w.set(0, 64, 0, S("lever", face="floor", facing="east"))
        w.set(1, 64, 0, S("redstone_wire"))
        w.set(2, 64, 0, S("redstone_lamp"))
        w.use(0, 64, 0)
        self.assertEqual(w.props(2, 64, 0)["lit"], "true")
        w.use(0, 64, 0)
        w.tick(3)
        self.assertEqual(w.props(2, 64, 0)["lit"], "true")
        w.tick(1)
        self.assertEqual(w.props(2, 64, 0)["lit"], "false")

    def test_repeater_delay_and_lock(self):
        w = World()
        w.set(0, 64, 0, S("lever", face="floor", facing="east"))
        w.set(1, 64, 0, S("repeater", facing="west", delay="3"))
        w.use(0, 64, 0)
        w.tick(5)
        self.assertEqual(w.props(1, 64, 0)["powered"], "false")
        w.tick(1)
        self.assertEqual(w.props(1, 64, 0)["powered"], "true")
        # a powered repeater pointing into the side locks it
        w.set(1, 64, 2, S("lever", face="floor", facing="east"))
        w.set(1, 64, 1, S("repeater", facing="south"))
        w.use(1, 64, 2)
        w.tick(2)
        self.assertEqual(w.props(1, 64, 0)["locked"], "true")
        w.use(0, 64, 0)
        w.tick(10)
        self.assertEqual(w.props(1, 64, 0)["powered"], "true")   # locked: keeps its output

    def test_torch_inverts_after_2_ticks_and_burns_out(self):
        w = World()
        w.set(5, 64, 5, S("stone"))
        w.set(5, 65, 5, S("lever", face="floor", facing="north"))
        w.set(6, 64, 5, S("redstone_wall_torch", facing="east"))
        w.use(5, 65, 5)
        w.tick(1)
        self.assertEqual(w.props(6, 64, 5)["lit"], "true")
        w.tick(1)
        self.assertEqual(w.props(6, 64, 5)["lit"], "false")
        # torch that powers its own block via wire: a 1-tick clock that burns out
        w = World()
        w.set(0, 64, 0, S("stone"))
        w.set(0, 65, 0, S("redstone_torch"))
        w.set(1, 64, 0, S("redstone_wall_torch", facing="east"))
        w.set(1, 65, 0, S("redstone_wire"))
        w.set(2, 64, 0, S("stone"))
        lit_changes = 0
        last = w.props(1, 64, 0)["lit"]
        for _ in range(100):
            w.tick()
            now = w.props(1, 64, 0)["lit"]
            lit_changes += now != last
            last = now
        self.assertLess(lit_changes, 20)   # burnt out instead of toggling forever

    def test_observer_two_tick_pulse(self):
        w = World()
        w.set(0, 64, 0, S("observer", facing="east"))   # watches x=1, outputs to x=-1
        w.set(-1, 64, 0, S("redstone_lamp"))
        w.set(1, 64, 0, S("dirt"))
        states = []
        for _ in range(6):
            w.tick()
            states.append(w.props(0, 64, 0)["powered"])
        self.assertEqual(states, ["false", "true", "true", "false", "false", "false"])

    def test_comparator_container_and_subtract(self):
        from world.block_behavior import container_manager
        from world.inventory import ItemStack
        w = World()
        w.set(0, 64, 0, S("chest"))
        container = container_manager.get_or_create(0, 64, 0, "chest")
        for i in range(len(container.items)):
            container.items[i] = None
        container.items[0] = ItemStack("minecraft:stone", 64)
        w.set(1, 64, 0, S("comparator", facing="west"))
        w.tick(3)
        self.assertEqual(w.engine.comparator_outputs().get((1, 64, 0)), 1)       # 1 of 27 slots: 1
        for i in range(len(container.items)):
            container.items[i] = ItemStack("minecraft:stone", 64)
        w.engine.on_container_changed(0, 64, 0)
        w.tick(3)
        self.assertEqual(w.engine.comparator_outputs().get((1, 64, 0)), 15)
        w.set(1, 64, 1, S("redstone_wire"))
        w.set(1, 64, 2, S("redstone_wire"))
        w.set(1, 64, 3, S("redstone_block"))
        w.use(1, 64, 0)                                                    # subtract mode, side input 14
        w.tick(3)
        self.assertEqual(w.engine.comparator_outputs().get((1, 64, 0)), 1)
        container.items[:] = [None] * len(container.items)


class Pistons(unittest.TestCase):
    def test_push_and_sticky_pull(self):
        w = World()
        w.set(0, 64, 0, S("sticky_piston", facing="east"))
        w.set(1, 64, 0, S("dirt"))
        w.set(2, 64, 0, S("oak_planks"))
        w.set(0, 64, 1, S("redstone_block"))
        w.tick(3)
        self.assertEqual(row(w, range(0, 4)), ["sticky_piston", "piston_head", "dirt", "oak_planks"])
        w.set(0, 64, 1, S("air"))
        w.tick(3)
        self.assertEqual(row(w, range(0, 4)), ["sticky_piston", "dirt", "air", "oak_planks"])

    def test_push_limit_immovable_and_destroyed_blocks(self):
        w = World()
        w.set(0, 64, 0, S("piston", facing="east"))
        for x in range(1, 14):
            w.set(x, 64, 0, S("dirt"))
        w.set(0, 64, 1, S("redstone_block"))
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "false")
        w = World()
        w.set(0, 64, 0, S("piston", facing="east"))
        w.set(1, 64, 0, S("obsidian"))
        w.set(0, 64, 1, S("redstone_block"))
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "false")
        w = World()
        w.set(0, 64, 0, S("piston", facing="east"))
        w.set(1, 64, 0, S("poppy"))
        w.set(0, 64, 1, S("redstone_block"))
        w.tick(3)
        self.assertEqual(row(w, range(0, 3)), ["piston", "piston_head", "air"])

    def test_quasi_connectivity_bud(self):
        w = World()
        w.set(0, 64, 0, S("piston", facing="east"))
        w.set(0, 65, 0, S("glass"))
        w.set(0, 65, 1, S("redstone_block"))
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "false")   # powered only by QC: no update yet
        w.set(-1, 64, 0, S("dirt"))                                 # block update
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "true")
        w.set(0, 65, 1, S("air"))
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "true")    # BUD: stays out
        w.set(-1, 64, 0, S("air"))
        w.tick(3)
        self.assertEqual(w.props(0, 64, 0)["extended"], "false")

    def test_zero_tick_sticky_piston_spits_block(self):
        w = World()
        w.set(0, 64, 0, S("sticky_piston", facing="east"))
        w.set(1, 64, 0, S("gold_block"))
        level = w.engine.level
        chunk = w.storage.load_generated_chunk(0, 0)
        level.game_time += 1
        chunk[128][1][0] = S("redstone_block")
        level._chunks.clear()
        piston = level.block(w.get(0, 64, 0))
        piston.check_if_extend(level, (0, 64, 0), w.get(0, 64, 0))
        level.run_block_events()
        chunk[128][1][0] = 0
        level._chunks.clear()
        piston.check_if_extend(level, (0, 64, 0), w.get(0, 64, 0))
        self.assertEqual(level._events[0][2], 2)        # fast retraction event
        level.run_block_events()
        level.tick_block_entities()
        w.engine._finish_step()
        w.tick(3)
        self.assertEqual(row(w, range(0, 3)), ["sticky_piston", "air", "gold_block"])


class Consumers(unittest.TestCase):
    def test_redstone_primes_tnt_and_opens_doors(self):
        w = World()
        w.set(0, 64, 0, S("tnt"))
        w.set(1, 64, 0, S("redstone_block"))
        self.assertEqual(w.name(0, 64, 0), "air")
        self.assertEqual(w.entities[0].kind, "tnt")
        w = World()
        w.set(0, 64, 0, S("oak_door", half="lower", facing="north"))
        w.set(0, 65, 0, S("oak_door", half="upper", facing="north"))
        w.set(1, 64, 0, S("lever", face="floor", facing="east"))
        w.use(1, 64, 0)
        self.assertEqual(w.props(0, 64, 0)["open"], "true")
        self.assertEqual(w.props(0, 65, 0)["open"], "true")   # upper half follows via shape update

    def test_dispenser_quasi_connectivity_and_note_block(self):
        w = World()
        w.set(0, 64, 0, S("dispenser", facing="east"))
        w.set(0, 65, 0, S("glass"))
        w.set(0, 66, 0, S("redstone_block"))   # powers the block above the dispenser: QC
        w.set(-1, 64, 0, S("dirt"))
        self.assertEqual(w.props(0, 64, 0)["triggered"], "true")
        w = World()
        w.set(0, 64, 0, S("note_block"))
        w.set(1, 64, 0, S("redstone_block"))
        w.tick()
        self.assertEqual(w.engine.drain_block_actions()[0][1], "minecraft:note_block")


class JavaOrdering(unittest.TestCase):
    def test_blockpos_hash_and_hashset_order(self):
        self.assertEqual(blockpos_hash((1, 2, 3)), (2 + 3 * 31) * 31 + 1)
        positions = [(0, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0)]
        order = java_hash_order(positions)
        self.assertEqual(sorted(order), sorted(positions))
        self.assertEqual(order[0], (0, 0, 0))          # bucket 0 first


class Placement(unittest.TestCase):
    def test_vanilla_placement_states(self):
        from world.placement import placement_states
        from world.rs.core import props_of, name_of
        air = lambda *a: 0

        def place(item, face, yaw=180.0, pitch=0.0, cursor=(0.5, 0.5, 0.5)):
            result = placement_states("minecraft:" + item, face, cursor, yaw, pitch, (0, 64, 0), 0, air)
            return [(name_of(s).split(":")[1], props_of(s)) for _, s in result]

        self.assertEqual(place("piston", 1)[0][1]["facing"], "south")            # looking north
        self.assertEqual(place("piston", 1, pitch=80)[0][1]["facing"], "up")
        self.assertEqual(place("observer", 1)[0][1]["facing"], "north")
        self.assertEqual(place("repeater", 1, yaw=0)[0][1]["facing"], "north")
        self.assertEqual(place("redstone_torch", 5)[0], ("redstone_wall_torch", {"facing": "east", "lit": "true"}))
        self.assertEqual(place("lever", 0)[0][1]["face"], "ceiling")
        self.assertEqual(place("redstone", 1)[0][0], "redstone_wire")
        self.assertEqual(place("oak_slab", 2, cursor=(0.5, 0.8, 0.5))[0][1]["type"], "top")
        door = place("oak_door", 1, yaw=270)
        self.assertEqual([d[1]["half"] for d in door], ["lower", "upper"])


if __name__ == "__main__":
    unittest.main()


class Tripwire(unittest.TestCase):
    def build(self):
        w = World()
        w.set(-1, 64, 0, S("stone"))
        w.set(5, 64, 0, S("stone"))
        w.set(0, 64, 0, S("tripwire_hook", facing="east"))
        w.set(4, 64, 0, S("tripwire_hook", facing="west"))
        for x in (1, 2, 3):
            w.set(x, 64, 0, S("tripwire"))
        return w

    def test_hooks_attach_and_detach(self):
        w = self.build()
        self.assertEqual([w.props(x, 64, 0)["attached"] for x in range(5)], ["true"] * 5)
        w.set(5, 64, 0, S("air"))          # support gone: hook drops, line detaches
        self.assertEqual(w.name(4, 64, 0), "air")
        self.assertEqual([w.props(x, 64, 0)["attached"] for x in range(4)], ["false"] * 4)

    def test_piston_breaks_string_and_hooks_recheck_after_10_ticks(self):
        w = self.build()
        w.set(2, 64, 1, S("piston", facing="north"))
        w.engine.drain_pending_effects()
        w.set(3, 64, 1, S("redstone_block"))
        w.tick(15)
        self.assertEqual(w.name(2, 64, 0), "piston_head")
        drops = [e for e in w.engine.drain_pending_effects() if e[0] == "drop"]
        self.assertEqual(len(drops), 1)
        self.assertEqual(w.props(0, 64, 0)["attached"], "false")


class TntDuplication(unittest.TestCase):
    def test_budded_tnt_moved_by_slime_is_duplicated(self):
        """Vanilla TNT duping: states are captured before the push, an update primes the
        budded TNT inside that window, and the moving piston still places the TNT."""
        w = World()
        w.set(0, 65, 0, S("sticky_piston", facing="east"))
        w.set(1, 65, 0, S("slime_block"))
        w.set(3, 65, 1, S("stone"))
        w.set(2, 65, 1, S("dead_tube_coral_wall_fan", facing="west"))
        w.set(1, 65, 1, S("tnt"))
        # budded: powered by a redstone block that never updated it
        w.poke(0, 65, 1, S("redstone_block"))
        w.set(0, 66, 0, S("redstone_block"))
        w.tick(4)
        self.assertEqual(w.name(2, 65, 1), "tnt")                       # the block moved on
        self.assertEqual([e.kind for e in w.entities], ["tnt"])         # and a primed copy exists
