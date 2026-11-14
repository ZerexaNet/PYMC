"""Tests for the vanilla-compatible server shell and 1.21.1 protocol data."""

import asyncio
import gzip
import json
import os
import struct
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from protocol.data_types import read_string, read_varint, write_string, write_varint


class PacketIdTests(unittest.TestCase):
    """IDs cross-checked with minecraft-data 1.21.1 protocol.json."""

    def test_serverbound_play_ids(self):
        from protocol.packet_map import get_serverbound_packet as sb
        expected = {
            "confirm_teleportation": 0x00, "chat_command": 0x04, "signed_chat_command": 0x05,
            "chat_message": 0x06, "chunk_batch_received": 0x08, "client_command": 0x09,
            "client_settings": 0x0A, "tab_complete": 0x0B, "click_container": 0x0E,
            "close_container": 0x0F, "custom_payload": 0x12, "interact": 0x16,
            "keep_alive": 0x18, "player_position": 0x1A, "player_position_rotation": 0x1B,
            "player_rotation": 0x1C, "player_on_ground": 0x1D, "player_abilities": 0x23,
            "block_dig": 0x24, "entity_action": 0x25, "held_item_slot": 0x2F,
            "set_creative_mode_slot": 0x32, "arm_animation": 0x36, "block_place": 0x38,
            "use_item": 0x39,
        }
        for name, packet_id in expected.items():
            self.assertEqual(sb(767, name), packet_id, name)

    def test_serverbound_ids_are_unique(self):
        from protocol.packet_map import SERVERBOUND_PACKETS
        ids = [v for v in SERVERBOUND_PACKETS[767].values() if v is not None]
        self.assertEqual(len(ids), len(set(ids)))

    def test_clientbound_spot_checks(self):
        from protocol.packet_map import get_clientbound_packet as cb
        self.assertEqual(cb(767, "system_chat"), 0x6C)
        self.assertEqual(cb(767, "declare_commands"), 0x11)
        self.assertEqual(cb(767, "acknowledge_player_digging"), 0x05)
        self.assertEqual(cb(767, "set_chunk_cache_radius"), 0x55)
        self.assertEqual(cb(767, "damage_event"), 0x1A)


class TextComponentTests(unittest.TestCase):
    def test_modern_clients_get_nbt(self):
        from protocol.text import encode_component
        data = encode_component({"translate": "chat.type.text", "with": ["Steve", "hi"]}, 767)
        self.assertEqual(data[0], 10)                     # TAG_Compound, no root name
        self.assertIn(b"chat.type.text", data)
        self.assertNotIn(b"{", data[:2])

    def test_plain_string_is_a_string_tag(self):
        from protocol.text import encode_component
        data = encode_component("hello", 767)
        self.assertEqual(data, b"\x08\x00\x05hello")

    def test_legacy_clients_get_json(self):
        from protocol.text import encode_component
        text, offset = read_string(encode_component("hello", 47), 0)
        self.assertEqual(json.loads(text), {"text": "hello"})

    def test_json_strings_and_legacy_prefix(self):
        from protocol.text import to_component
        self.assertEqual(to_component('{"text":"x","color":"red"}'), {"text": "x", "color": "red"})
        self.assertEqual(to_component("[PyMC] saved"), {"text": "saved"})

    def test_plain_text_renders_translations(self):
        from protocol.text import plain_text, translate
        self.assertEqual(
            plain_text(translate("multiplayer.player.joined", "Steve", color="yellow")),
            "Steve joined the game")
        self.assertEqual(
            plain_text(translate("chat.type.text", "Steve", "hi \u00a7cthere")), "<Steve> hi there")
        self.assertEqual(
            plain_text(translate("commands.list.players", 1, 20, "Steve")),
            "There are 1 of a max of 20 players online: Steve")


class ConfigTests(unittest.TestCase):
    def test_vanilla_layout_and_roundtrip(self):
        import config
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "server.properties")
            loaded = config.load_config(path)
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "#Minecraft server properties")
            keys = [line.split("=", 1)[0] for line in lines[2:]]
            self.assertEqual(keys, sorted(keys))
            for key in ("motd", "white-list", "enable-rcon", "rcon.port", "pvp",
                        "spawn-protection", "max-players", "level-seed", "online-mode"):
                self.assertIn(key, keys)

            loaded["motd"] = "A: b=c #1\nsecond \u4e2d\u6587"
            loaded["custom-key"] = "kept"
            config.save_config(loaded, path)
            again = config.load_config(path)
            self.assertEqual(again["motd"], "A: b=c #1\nsecond \u4e2d\u6587")
            self.assertEqual(again["custom-key"], "kept")
            self.assertIs(again["white-list"], False)
            self.assertEqual(again["rcon.port"], 25575)

    def test_legacy_spawn_keys_are_read_but_not_written(self):
        import config
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "server.properties")
            Path(path).write_text("level-spawn-x=12\nview-distance=6\n", encoding="utf-8")
            loaded = config.load_config(path)
            self.assertEqual(loaded["level-spawn-x"], 12)
            self.assertEqual(loaded["view-distance"], 6)
            self.assertNotIn("level-spawn-x", Path(path).read_text(encoding="utf-8"))


class PermissionFileTests(unittest.TestCase):
    def test_vanilla_json_files(self):
        from admin.permissions import PermissionManager, offline_uuid
        with tempfile.TemporaryDirectory() as tmp:
            manager = PermissionManager(os.path.join(tmp, "permissions.json"))
            self.assertTrue(manager.op("Steve"))
            self.assertFalse(manager.op("steve"))
            manager.ban_player("Griefer", "being rude", source="Steve")
            manager.ban_ip("10.0.0.9")
            manager.add_whitelist("Alex")

            ops = json.loads(Path(tmp, "ops.json").read_text())
            self.assertEqual(ops, [{"uuid": str(offline_uuid("Steve")), "name": "Steve",
                                    "level": 4, "bypassesPlayerLimit": False}])
            banned = json.loads(Path(tmp, "banned-players.json").read_text())[0]
            self.assertEqual((banned["name"], banned["reason"], banned["source"], banned["expires"]),
                             ("Griefer", "being rude", "Steve", "forever"))
            self.assertRegex(banned["created"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \+0000$")
            self.assertEqual(json.loads(Path(tmp, "banned-ips.json").read_text())[0]["ip"], "10.0.0.9")
            self.assertEqual(json.loads(Path(tmp, "whitelist.json").read_text())[0]["name"], "Alex")
            self.assertNotIn("ops", json.loads(Path(tmp, "permissions.json").read_text()))

            reloaded = PermissionManager(os.path.join(tmp, "permissions.json"))
            self.assertEqual(reloaded.get_op_level("STEVE"), 4)
            self.assertTrue(reloaded.is_banned("griefer"))
            self.assertTrue(reloaded.is_whitelisted("alex"))

    def test_login_checks_use_vanilla_messages(self):
        from admin.permissions import PermissionManager
        from protocol.text import plain_text
        with tempfile.TemporaryDirectory() as tmp:
            manager = PermissionManager(os.path.join(tmp, "permissions.json"))
            manager.ban_player("Griefer", "being rude")
            self.assertEqual(plain_text(manager.check_login("griefer", "1.1.1.1")),
                             "You are banned from this server.\nReason: being rude")
            manager.data["whitelist"]["enabled"] = True
            self.assertEqual(plain_text(manager.check_login("Stranger", "1.1.1.1")),
                             "You are not white-listed on this server!")
            manager.op("Admin")
            self.assertIsNone(manager.check_login("Admin", "1.1.1.1"))

    def test_legacy_permissions_json_is_migrated(self):
        from admin.permissions import PermissionManager
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "permissions.json").write_text(json.dumps({
                "ops": ["Old"],
                "bans": {"players": {"bad": {"name": "Bad", "reason": "r"}}, "ips": {}},
                "whitelist": {"enabled": True, "players": ["W"]},
            }))
            manager = PermissionManager(os.path.join(tmp, "permissions.json"))
            self.assertTrue(manager.is_op("old"))
            self.assertTrue(manager.is_banned("Bad"))
            self.assertTrue(manager.data["whitelist"]["enabled"])
            self.assertTrue(Path(tmp, "ops.json").exists())

    def test_usercache(self):
        from admin.permissions import UserCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = UserCache(os.path.join(tmp, "usercache.json"))
            player_uuid = uuid.uuid4()
            cache.record("Steve", player_uuid)
            again = UserCache(os.path.join(tmp, "usercache.json"))
            self.assertEqual(again.lookup("steve"), str(player_uuid))
            self.assertEqual(again.name_for("STEVE"), "Steve")
            entry = json.loads(Path(tmp, "usercache.json").read_text())[0]
            self.assertEqual(set(entry), {"name", "uuid", "expiresOn"})


class LevelDataTests(unittest.TestCase):
    def test_roundtrip_and_backup(self):
        from world.level_data import LevelData
        with tempfile.TemporaryDirectory() as tmp:
            level = LevelData()
            level.spawn = (1, 70, -3)
            level.game_time = 123456789012
            level.day_time = 18000
            level.raining = True
            level.rain_time = 500
            level.gamerules = {"keepInventory": "true"}
            level.seed = -5
            level.difficulty = "hard"
            level.save(tmp)
            level.save(tmp)
            self.assertTrue(Path(tmp, "level.dat_old").exists())
            with gzip.open(Path(tmp, "level.dat"), "rb") as f:
                raw = f.read()
            self.assertEqual(raw[:3], b"\x0a\x00\x00")       # named (empty) root compound

            loaded = LevelData.load(tmp)
            self.assertTrue(loaded.existed)
            self.assertEqual(loaded.spawn, (1, 70, -3))
            self.assertEqual(loaded.game_time, 123456789012)
            self.assertEqual(loaded.day_time, 18000)
            self.assertTrue(loaded.raining)
            self.assertEqual(loaded.gamerules, {"keepInventory": "true"})
            self.assertEqual(loaded.seed, -5)
            self.assertEqual(loaded.difficulty, "hard")

    def test_session_lock_is_exclusive(self):
        from world.level_data import SessionLock, SessionLockError
        with tempfile.TemporaryDirectory() as tmp:
            first = SessionLock(tmp)
            first.acquire()
            with self.assertRaises(SessionLockError):
                SessionLock(tmp).acquire()
            first.release()
            second = SessionLock(tmp)
            second.acquire()
            second.release()

    def test_time_manager_tracks_days_and_weather(self):
        from network.managers.time import TimeManager
        from world.level_data import LevelData
        manager = TimeManager(initial_time=0)
        manager.day_time_total = 24000 * 3 + 500
        manager.age = 99
        manager.set_weather("thunder", 1000)
        self.assertEqual(manager.time, 500)
        self.assertEqual(manager.get_day_count(), 3)
        level = LevelData()
        manager.write_level_data(level)
        self.assertTrue(level.raining and level.thundering)
        restored = TimeManager(initial_time=0)
        restored.apply_level_data(level)
        self.assertEqual((restored.day_time_total, restored.age, restored.weather),
                         (24000 * 3 + 500, 99, "thunder"))


class RegistryDataTests(unittest.TestCase):
    def test_all_synced_registries_present(self):
        from protocol.gamedata import synced_registries
        registries = synced_registries()
        for name in ("minecraft:dimension_type", "minecraft:worldgen/biome", "minecraft:chat_type",
                     "minecraft:damage_type", "minecraft:painting_variant", "minecraft:wolf_variant",
                     "minecraft:trim_pattern", "minecraft:trim_material",
                     "minecraft:banner_pattern", "minecraft:enchantment", "minecraft:jukebox_song"):
            self.assertIn(name, registries)
            self.assertGreater(len(registries[name]), 0)

    def test_overworld_spans_minus_64_to_320(self):
        from protocol.gamedata import synced_registries
        from protocol.nbt import decode_nbt
        entries = synced_registries()["minecraft:dimension_type"]
        self.assertEqual(entries[0][0], "minecraft:overworld")   # index 0 is used in Login
        value, _ = decode_nbt(entries[0][1], 0, with_type=True, with_name=False)
        self.assertEqual(value["min_y"], -64)
        self.assertEqual(value["height"], 384)

    def test_biome_ids_match_world_storage(self):
        from protocol.gamedata import registry_index
        from world.biomes import BIOME_NAME_TO_ID
        index = registry_index("minecraft:worldgen/biome")
        for name, biome_id in BIOME_NAME_TO_ID.items():
            self.assertEqual(index[name], biome_id, name)

    def test_tags_payload(self):
        from handlers.configuration import build_tags_payload
        from protocol.gamedata import tags
        all_tags = tags()
        self.assertEqual(sorted(all_tags["minecraft:fluid"]["minecraft:water"]), [1, 2])
        self.assertIn("minecraft:mineable/pickaxe", all_tags["minecraft:block"])
        self.assertIn("minecraft:climbable", all_tags["minecraft:block"])

        payload = build_tags_payload()
        count, offset = read_varint(payload, 0)
        self.assertEqual(count, len(all_tags))
        for _ in range(count):
            _registry, offset = read_string(payload, offset)
            tag_count, offset = read_varint(payload, offset)
            for _ in range(tag_count):
                _name, offset = read_string(payload, offset)
                entries, offset = read_varint(payload, offset)
                for _ in range(entries):
                    _, offset = read_varint(payload, offset)
        self.assertEqual(offset, len(payload))

    def test_item_table(self):
        from world.inventory import item_name_to_protocol_id, protocol_id_to_item_name, ItemStack
        self.assertEqual(item_name_to_protocol_id("minecraft:stone"), 1)
        self.assertEqual(item_name_to_protocol_id("minecraft:grass_block"), 27)
        self.assertEqual(protocol_id_to_item_name(item_name_to_protocol_id("minecraft:diamond_sword")),
                         "minecraft:diamond_sword")
        self.assertEqual(ItemStack("minecraft:ender_pearl", 1).max_stack_size, 16)
        self.assertEqual(ItemStack("minecraft:iron_pickaxe", 1).max_stack_size, 1)
        self.assertEqual(ItemStack("minecraft:iron_ingot", 1).max_stack_size, 64)
        self.assertEqual(ItemStack("minecraft:iron_pickaxe", 1).max_durability, 250)


def _decode_command_tree(payload: bytes):
    """Minimal Commands packet decoder (enough to validate structure)."""
    from protocol.gamedata import load_data
    parsers = {v: k for k, v in load_data("commands_767.json")["parsers"].items()}
    count, offset = read_varint(payload, 0)
    nodes = []
    for _ in range(count):
        flags = payload[offset]
        offset += 1
        child_count, offset = read_varint(payload, offset)
        children = []
        for _ in range(child_count):
            child, offset = read_varint(payload, offset)
            children.append(child)
        node = {"flags": flags, "children": children}
        if flags & 0x08:
            node["redirect"], offset = read_varint(payload, offset)
        kind = flags & 0x03
        if kind in (1, 2):
            node["name"], offset = read_string(payload, offset)
        if kind == 2:
            parser_id, offset = read_varint(payload, offset)
            parser = parsers[parser_id]
            node["parser"] = parser
            if parser in ("brigadier:float", "brigadier:double", "brigadier:integer", "brigadier:long"):
                size = {"brigadier:float": 4, "brigadier:double": 8,
                        "brigadier:integer": 4, "brigadier:long": 8}[parser]
                limits = payload[offset]
                offset += 1 + size * bin(limits & 3).count("1")
            elif parser == "brigadier:string":
                _, offset = read_varint(payload, offset)
            elif parser in ("minecraft:entity", "minecraft:score_holder"):
                offset += 1
            elif parser == "minecraft:time":
                offset += 4
            elif parser.startswith("minecraft:resource"):
                if parser != "minecraft:resource_location":
                    _, offset = read_string(payload, offset)
            if flags & 0x10:
                node["suggestions"], offset = read_string(payload, offset)
        nodes.append(node)
    root, offset = read_varint(payload, offset)
    return nodes, root, offset


class CommandTreeTests(unittest.TestCase):
    def test_tree_is_well_formed(self):
        from commands.brigadier import build_commands_payload
        payload = build_commands_payload(
            ["gamemode", "tp", "teleport", "execute", "give", "time", "msg", "tell", "w", "pymcext"])
        nodes, root, offset = _decode_command_tree(payload)
        self.assertEqual(offset, len(payload))
        self.assertEqual(nodes[root]["flags"] & 0x03, 0)
        top = {nodes[i]["name"]: nodes[i] for i in nodes[root]["children"]}
        self.assertEqual(set(top), {"gamemode", "tp", "teleport", "execute", "give", "time",
                                    "msg", "tell", "w", "pymcext"})
        # tp is an alias: it redirects to the teleport node
        self.assertEqual(nodes[top["tp"]["redirect"]]["name"], "teleport")
        # /gamemode <gamemode> [<target>]
        mode = nodes[top["gamemode"]["children"][0]]
        self.assertEqual(mode["parser"], "minecraft:gamemode")
        self.assertTrue(mode["flags"] & 0x04)
        # non-vanilla commands get a greedy argument with server-side suggestions
        extra = nodes[top["pymcext"]["children"][0]]
        self.assertEqual((extra["parser"], extra["suggestions"]),
                         ("brigadier:string", "minecraft:ask_server"))
        for node in nodes:
            for child in node["children"]:
                self.assertLess(child, len(nodes))


class InventoryLayoutTests(unittest.TestCase):
    def test_window_order_and_hotbar_first(self):
        from world.inventory import ItemStack, PlayerInventory, player_window_slots
        inventory = PlayerInventory()
        self.assertEqual(inventory.add_item(ItemStack("minecraft:stone", 70)), 0)
        self.assertEqual(inventory.get_slot(0).count, 64)        # hotbar first, like vanilla
        self.assertEqual(inventory.get_slot(1).count, 6)
        inventory.set_slot(39, ItemStack("minecraft:iron_helmet", 1))
        inventory.set_slot(40, ItemStack("minecraft:shield", 1))
        window = player_window_slots(inventory)
        self.assertEqual(len(window), 46)
        self.assertEqual(window[36].count, 64)                   # hotbar slot 0
        self.assertEqual(window[5].item_id, "minecraft:iron_helmet")
        self.assertEqual(window[45].item_id, "minecraft:shield")
        self.assertIsNone(window[0])

    def test_slot_encoding(self):
        from world.inventory import ItemStack, decode_slot_entry, encode_slot_entry
        self.assertEqual(encode_slot_entry(None), b"\x00")
        pickaxe = ItemStack("minecraft:iron_pickaxe", 1, damage=12)
        decoded, offset = decode_slot_entry(encode_slot_entry(pickaxe))
        self.assertEqual((decoded.item_id, decoded.count, decoded.damage),
                         ("minecraft:iron_pickaxe", 1, 12))
        self.assertEqual(offset, len(encode_slot_entry(pickaxe)))


class LightingTests(unittest.TestCase):
    def setUp(self):
        from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE as states
        self.states = states
        self.blocks = [[[0] * 16 for _ in range(16)] for _ in range(64)]
        stone = states["minecraft:stone"]
        for y in range(11):
            for z in range(16):
                for x in range(16):
                    self.blocks[y][z][x] = stone

    def light(self):
        from world.lighting import compute_light
        sky, block = compute_light(self.blocks)
        return (lambda x, y, z: sky[y * 256 + z * 16 + x],
                lambda x, y, z: block[y * 256 + z * 16 + x])

    def test_sky_light_passes_plants_and_filters_through_leaves(self):
        self.blocks[11][0][0] = self.states["minecraft:short_grass"]
        leaves = self.states["minecraft:oak_leaves"]
        for z in range(4, 9):
            for x in range(4, 9):
                self.blocks[14][z][x] = leaves
        sky, _ = self.light()
        self.assertEqual(sky(2, 12, 2), 15)
        self.assertEqual(sky(0, 11, 0), 15)       # inside the grass tuft
        self.assertEqual(sky(6, 14, 6), 14)       # leaves filter one level
        self.assertGreaterEqual(sky(6, 11, 6), 12)  # shade under the canopy, not darkness
        self.assertEqual(sky(3, 5, 3), 0)         # solid stone

    def test_sky_light_spreads_under_overhangs(self):
        stone = self.states["minecraft:stone"]
        for z in range(16):
            for x in range(10, 16):
                self.blocks[13][z][x] = stone
        sky, _ = self.light()
        self.assertEqual(sky(10, 12, 5), 14)
        self.assertEqual(sky(15, 12, 5), 9)

    def test_block_light_from_torch(self):
        self.blocks[5][8][8] = self.states["minecraft:torch"]
        self.blocks[5][8][9] = 0
        self.blocks[5][8][10] = 0
        _, block = self.light()
        self.assertEqual([block(8, 5, 8), block(9, 5, 8), block(10, 5, 8)], [14, 13, 12])
        self.assertEqual(block(8, 6, 8), 0)

    def test_packet_layout(self):
        from world.lighting import build_light_sections
        sky_mask, block_mask, empty_sky, empty_block, sky_arrays, block_arrays = \
            build_light_sections(self.blocks)
        sections = len(self.blocks) // 16 + 2
        self.assertEqual(sky_mask | empty_sky, (1 << sections) - 1)
        self.assertEqual(sky_mask & empty_sky, 0)
        self.assertEqual(len(sky_arrays), bin(sky_mask).count("1"))
        self.assertEqual(len(block_arrays), bin(block_mask).count("1"))
        self.assertTrue(all(len(a) == 2048 for a in sky_arrays))
        self.assertTrue(sky_mask & (1 << (sections - 1)))     # section above the world


class StatusResponseTests(unittest.TestCase):
    def make_server(self, **config):
        players = [SimpleNamespace(username="Steve", uuid=uuid.uuid4(), allow_server_listing=True)]
        return SimpleNamespace(config=config, motd="Hello", max_players=20,
                               get_online_players=lambda: players)

    def test_vanilla_fields(self):
        from handlers.status import build_status_response
        response = build_status_response(self.make_server(), 767)
        self.assertEqual(response["version"], {"name": "1.21.1", "protocol": 767})
        self.assertEqual(response["description"], {"text": "Hello"})
        self.assertEqual(response["players"]["online"], 1)
        self.assertEqual(response["players"]["sample"][0]["name"], "Steve")
        self.assertIs(response["enforcesSecureChat"], False)

    def test_unsupported_client_sees_native_protocol(self):
        from handlers.status import build_status_response
        self.assertEqual(build_status_response(self.make_server(), 9999)["version"]["protocol"], 767)

    def test_hide_online_players(self):
        from handlers.status import build_status_response
        response = build_status_response(self.make_server(**{"hide-online-players": True}), 767)
        self.assertNotIn("sample", response["players"])


class EncryptionTests(unittest.TestCase):
    def setUp(self):
        from network import encryption
        if not encryption.available():
            self.skipTest("cryptography is not installed")

    def test_rsa_and_stream_cipher(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from network.encryption import ServerKeyPair, StreamCipher
        pair = ServerKeyPair()
        public = serialization.load_der_public_key(pair.public_der)
        secret = os.urandom(16)
        self.assertEqual(pair.decrypt(public.encrypt(secret, padding.PKCS1v15())), secret)

        server, client = StreamCipher(secret), StreamCipher(secret)
        message = b"x" * 1000 + b"minecraft"
        ciphertext = server.encrypt(message[:500]) + server.encrypt(message[500:])
        self.assertNotEqual(ciphertext, message)
        self.assertEqual(client.decrypt(ciphertext[:7]) + client.decrypt(ciphertext[7:]), message)


class RconTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_and_command(self):
        from commands import CommandManager
        from commands.framework import Command, SUCCESS
        from network.rcon import RconServer

        server = SimpleNamespace(
            permissions=SimpleNamespace(has_permission=lambda *a: True, is_op=lambda n: False),
            gamerules={}, config={}, get_online_players=lambda: [], java_plugin_bridge=None)
        server.command_manager = CommandManager(server)

        async def _echo(ctx):
            await ctx.reply({"translate": "commands.list.players", "with": ["0", "20", ""]})
            await ctx.reply("second line")
            return SUCCESS

        command = Command(name="list")
        command._execute_func = _echo
        server.command_manager.register(command)

        rcon = RconServer(server, "127.0.0.1", 0, "s3cret")
        await rcon.start()
        port = rcon._listener.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        async def exchange(request_id, kind, body):
            data = struct.pack("<ii", request_id, kind) + body.encode() + b"\x00\x00"
            writer.write(struct.pack("<i", len(data)) + data)
            await writer.drain()
            (length,) = struct.unpack("<i", await reader.readexactly(4))
            packet = await reader.readexactly(length)
            rid, rkind = struct.unpack_from("<ii", packet)
            return rid, rkind, packet[8:-2].decode()

        try:
            self.assertEqual((await exchange(1, 3, "wrong"))[0], -1)
            self.assertEqual((await exchange(2, 3, "s3cret"))[0], 2)
            rid, rkind, output = await exchange(3, 2, "list")
            self.assertEqual((rid, rkind), (3, 0))
            self.assertEqual(output, "There are 0 of a max of 20 players online: \nsecond line")
            _, _, output = await exchange(4, 2, "doesnotexist")
            self.assertIn("Unknown or incomplete command", output)
        finally:
            writer.close()
            await rcon.stop()


class LogFormatTests(unittest.TestCase):
    def test_vanilla_line_format_and_archive(self):
        import logging
        from serverlog import VanillaFormatter, archive_latest_log
        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "Can't keep up!", None, None)
        record.threadName = "Server thread"
        self.assertRegex(VanillaFormatter().format(record),
                         r"^\[\d\d:\d\d:\d\d\] \[Server thread/WARN\]: Can't keep up!$")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "latest.log").write_text("old run\n")
            archive = archive_latest_log(tmp)
            self.assertRegex(archive.name, r"^\d{4}-\d\d-\d\d-1\.log\.gz$")
            self.assertFalse(Path(tmp, "latest.log").exists())
            with gzip.open(archive, "rt") as f:
                self.assertEqual(f.read(), "old run\n")


if __name__ == "__main__":
    unittest.main()
