"""Advancements (1.12+): progress from the inventory, commands, saving, and the 1.21.1 packet layout."""

import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path

from protocol.data_types import read_varint
from world import advancements as adv
from world.inventory import ItemStack


class _FakeConn(types.SimpleNamespace):
    async def send_packet(self, packet_id, payload):
        self.sent.append((packet_id, payload))


def _conn(items=(), uuid="0f0e0d0c-0b0a-0908-0706-050403020100", pv=767):
    slots = [None] * 36
    for i, item in enumerate(items):
        slots[i] = ItemStack(item, 1)
    return _FakeConn(
        username="Steve", uuid=uuid, protocol_version=pv,
        inventory_obj=types.SimpleNamespace(slots=slots),
        advancement_progress=None, sent=[],
    )


def _server(world_dir: Path):
    async def _noop(*a, **k):
        return None
    return types.SimpleNamespace(
        world_storage=types.SimpleNamespace(world_dir=world_dir),
        broadcast_system_message=lambda *a, **k: None,
    )


class ProgressTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.server = _server(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_tree_is_connected(self):
        self.assertEqual(adv.BY_KEY["story/root"].parent, None)
        for a in adv.ADVANCEMENTS:
            if a.parent is not None:
                self.assertIn(a.parent, adv.BY_KEY)

    def test_inventory_grants_criteria_and_completes(self):
        conn = _conn(["minecraft:cobblestone"])
        conn.advancement_progress = {}
        changed, completed = adv.check_inventory(conn)
        self.assertEqual([a.key for a in changed], ["story/mine_stone"])
        self.assertEqual([a.key for a in completed], ["story/mine_stone"])
        self.assertIn("get_stone", conn.advancement_progress["story/mine_stone"])
        # nothing new the second time
        self.assertEqual(adv.check_inventory(conn), ([], []))

    def test_diamond_branch(self):
        conn = _conn(["minecraft:diamond"])
        conn.advancement_progress = {}
        _, completed = adv.check_inventory(conn)
        keys = {a.key for a in completed}
        self.assertIn("story/mine_diamond", keys)
        self.assertNotIn("story/shiny_gear", keys)

    def test_obtain_armor_needs_one_piece(self):
        conn = _conn(["minecraft:iron_boots"])
        conn.advancement_progress = {}
        _, completed = adv.check_inventory(conn)
        self.assertIn("story/obtain_armor", [a.key for a in completed])

    def test_from_until_through(self):
        conn = _conn()
        conn.advancement_progress = {}
        n = asyncio.run(adv.apply(self.server, conn, "grant", "from", "story/upgrade_tools"))
        expected = {"story/upgrade_tools"} | {a.key for a in adv.descendants("story/upgrade_tools")}
        self.assertEqual(set(conn.advancement_progress), expected)
        self.assertIn("story/shiny_gear", expected)
        self.assertEqual(n, len(expected))
        conn.advancement_progress = {}
        asyncio.run(adv.apply(self.server, conn, "grant", "through", "story/upgrade_tools"))
        self.assertEqual(set(conn.advancement_progress), {"story/root", "story/mine_stone",
                                                          "story/upgrade_tools"})
        asyncio.run(adv.apply(self.server, conn, "revoke", "everything"))
        self.assertEqual(conn.advancement_progress, {})

    def test_only_criterion_and_revoke(self):
        conn = _conn()
        conn.advancement_progress = {}
        asyncio.run(adv.apply(self.server, conn, "grant", "only", "story/obtain_armor", "iron_boots"))
        self.assertEqual(list(conn.advancement_progress["story/obtain_armor"]), ["iron_boots"])
        # one piece of armour is enough (the requirement is an OR of the four pieces)
        self.assertTrue(adv.is_complete(conn, "story/obtain_armor"))
        asyncio.run(adv.apply(self.server, conn, "revoke", "only", "story/obtain_armor"))
        self.assertNotIn("story/obtain_armor", conn.advancement_progress)

    def test_unknown_advancement_is_rejected(self):
        conn = _conn()
        conn.advancement_progress = {}
        with self.assertRaises(ValueError):
            asyncio.run(adv.apply(self.server, conn, "grant", "only", "story/nope"))

    def test_save_and_load_round_trip(self):
        conn = _conn(["minecraft:stone_pickaxe"])
        conn.advancement_progress = {}
        adv.check_inventory(conn)
        adv.save(self.server, conn)
        path = Path(self._tmp.name) / "advancements" / f"{conn.uuid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("minecraft:story/upgrade_tools", data)
        self.assertTrue(data["minecraft:story/upgrade_tools"]["done"])

        fresh = _conn(uuid=conn.uuid)
        adv.load(self.server, fresh)
        self.assertEqual(fresh.advancement_progress, conn.advancement_progress)

    def test_unknown_entries_in_saved_file_are_dropped(self):
        cleaned = adv._clean({"minecraft:story/root": {"criteria": {"crafting_table": 5, "bogus": 1}},
                              "minecraft:nope/x": {"criteria": {"a": 1}}, "story/mine_stone": "bad"})
        self.assertEqual(cleaned, {"story/root": {"crafting_table": 5}})


def _decode_update(data: bytes) -> dict:
    """Read an advancements packet with the 1.21.1 layout; fails if the layout is off."""
    import struct
    from protocol.nbt import decode_nbt
    from world.inventory import decode_slot_entry

    def string(pos):
        n, pos = read_varint(data, pos)
        return data[pos:pos + n].decode("utf-8"), pos + n

    def boolean(pos):
        return data[pos] != 0, pos + 1

    reset, pos = boolean(0)
    count, pos = read_varint(data, pos)
    entries = []
    for _ in range(count):
        ident, pos = string(pos)
        has_parent, pos = boolean(pos)
        parent = None
        if has_parent:
            parent, pos = string(pos)
        has_display, pos = boolean(pos)
        display = None
        if has_display:
            title, pos = decode_nbt(data, pos, with_type=True, with_name=False)
            desc, pos = decode_nbt(data, pos, with_type=True, with_name=False)
            icon, pos = decode_slot_entry(data, pos)
            frame, pos = read_varint(data, pos)
            flags, = struct.unpack_from(">i", data, pos)
            pos += 4
            background = None
            if flags & 1:
                background, pos = string(pos)
            x, y = struct.unpack_from(">ff", data, pos)
            pos += 8
            display = {"title": title, "desc": desc, "icon": icon.item_id, "frame": frame,
                       "flags": flags, "background": background, "x": x, "y": y}
        groups, pos = read_varint(data, pos)
        requirements = []
        for _ in range(groups):
            k, pos = read_varint(data, pos)
            group = []
            for _ in range(k):
                name, pos = string(pos)
                group.append(name)
            requirements.append(group)
        telemetry, pos = boolean(pos)
        entries.append({"id": ident, "parent": parent, "display": display,
                        "requirements": requirements, "telemetry": telemetry})
    removed, pos = read_varint(data, pos)
    removed_ids = []
    for _ in range(removed):
        name, pos = string(pos)
        removed_ids.append(name)
    progress_count, pos = read_varint(data, pos)
    progress = {}
    for _ in range(progress_count):
        ident, pos = string(pos)
        criteria_count, pos = read_varint(data, pos)
        criteria = {}
        for _ in range(criteria_count):
            name, pos = string(pos)
            obtained, pos = boolean(pos)
            when = None
            if obtained:
                when, = struct.unpack_from(">q", data, pos)
                pos += 8
            criteria[name] = when
        progress[ident] = criteria
    return {"reset": reset, "entries": entries, "removed": removed_ids,
            "progress": progress, "end": pos}


class EventTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.announced = []
        self.server = types.SimpleNamespace(
            world_storage=types.SimpleNamespace(world_dir=Path(self._tmp.name)),
            broadcast_system_message=lambda text, **k: self.announced.append(text),
        )
        adv._pending.clear()

    def tearDown(self):
        self._tmp.cleanup()
        adv._pending.clear()

    def test_hostile_kill_grants_both(self):
        conn = _conn()
        conn.advancement_progress = {}
        adv.on_mob_killed(conn, types.SimpleNamespace(profile={"category": "hostile"}))
        self.assertTrue(adv.is_complete(conn, "adventure/root"))
        self.assertTrue(adv.is_complete(conn, "adventure/kill_a_mob"))

    def test_passive_kill_grants_only_the_root(self):
        conn = _conn()
        conn.advancement_progress = {}
        adv.on_mob_killed(conn, types.SimpleNamespace(profile={"category": "passive"}))
        self.assertTrue(adv.is_complete(conn, "adventure/root"))
        self.assertNotIn("adventure/kill_a_mob", conn.advancement_progress)

    def test_event_before_join_is_ignored(self):
        conn = _conn()          # no progress loaded yet
        adv.trigger(conn, "adventure/root", "killed_something")
        self.assertEqual(adv._pending, [])

    def test_flush_sends_once_and_announces_completions(self):
        conn = _conn()
        conn.advancement_progress = {}
        adv.on_mob_killed(conn, types.SimpleNamespace(profile={"category": "hostile"}))
        asyncio.run(adv.flush(self.server))
        self.assertEqual(adv._pending, [])
        self.assertEqual(len(conn.sent), 1)                  # one update for both advancements
        self.assertEqual(len(self.announced), 2)             # both completed now
        asyncio.run(adv.flush(self.server))                  # nothing pending: nothing sent
        self.assertEqual(len(conn.sent), 1)

    def test_enchant_event(self):
        conn = _conn()
        conn.advancement_progress = {}
        adv.trigger(conn, "adventure/enchant_item", "enchanted_item")
        self.assertTrue(adv.is_complete(conn, "adventure/enchant_item"))
        adv.trigger(conn, "adventure/enchant_item", "enchanted_item")   # already done: no new event
        self.assertEqual(len(adv._pending), 1)


class PacketTests(unittest.TestCase):

    def test_full_packet_round_trips_with_the_1_21_1_layout(self):
        conn = _conn()
        conn.advancement_progress = {"story/root": {"crafting_table": 1700000000000}}
        payload = adv._encode(conn, True, adv.ADVANCEMENTS, [a.key for a in adv.ADVANCEMENTS],
                              conn.advancement_progress)
        got = _decode_update(payload)
        self.assertEqual(got["end"], len(payload))            # the layout consumes every byte
        self.assertTrue(got["reset"])
        self.assertEqual([e["id"] for e in got["entries"]], [a.id for a in adv.ADVANCEMENTS])
        root = got["entries"][0]
        self.assertIsNone(root["parent"])
        self.assertEqual(root["display"]["icon"], "minecraft:grass_block")
        self.assertEqual(root["display"]["title"], {"translate": "advancements.story.root.title"})
        self.assertEqual(root["requirements"], [["crafting_table"]])
        self.assertEqual(got["entries"][1]["parent"], "minecraft:story/root")
        self.assertEqual(got["progress"]["minecraft:story/root"], {"crafting_table": 1700000000000})
        self.assertEqual(got["progress"]["minecraft:story/mine_stone"], {"get_stone": None})

    def test_partial_update_is_not_a_reset(self):
        conn = _conn()
        conn.advancement_progress = {}
        payload = adv._encode(conn, False, [adv.BY_KEY["story/mine_stone"]], ["story/mine_stone"], {})
        got = _decode_update(payload)
        self.assertFalse(got["reset"])
        self.assertEqual(got["end"], len(payload))
        self.assertEqual(len(got["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
