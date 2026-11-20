"""End-to-end test: a raw 1.21.1 client pings, logs in and chats over TCP."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from protocol.data_types import (
    read_string, read_varint, write_string, write_uuid, write_varint,
)
from protocol.packet import pack_packet, read_packet_async

REPO_ROOT = Path(__file__).resolve().parent.parent


def _native_terrain_available() -> bool:
    from world._native_binary import is_runnable_native_binary
    for name in ("terrain_gen", "terrain_gen.exe"):
        path = REPO_ROOT / "native" / name
        try:
            if path.exists() and is_runnable_native_binary(path):
                return True
        except Exception:
            pass
    return False


class RawClient:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.threshold = -1

    @classmethod
    async def connect(cls, port: int, next_state: int) -> "RawClient":
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        client = cls(reader, writer)
        handshake = (write_varint(767) + write_string("127.0.0.1")
                     + (port).to_bytes(2, "big") + write_varint(next_state))
        await client.send(0x00, handshake)
        return client

    async def send(self, packet_id: int, payload: bytes = b""):
        self.writer.write(pack_packet(packet_id, payload, self.threshold))
        await self.writer.drain()

    async def read(self):
        return await asyncio.wait_for(read_packet_async(self.reader, self.threshold), 20)

    def close(self):
        self.writer.close()


@unittest.skipUnless(_native_terrain_available(),
                     "native terrain generator not built (run build.sh / cmake)")
class EndToEndLoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from commands import CommandManager, register_all_vanilla_commands
        from config import DEFAULT_CONFIG
        from network.server import MinecraftServer

        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        config = dict(DEFAULT_CONFIG)
        config.update({
            "server-ip": "127.0.0.1", "server-port": 0,
            "level-seed": "12345", "view-distance": 2, "join-immediate-radius": 1,
            "motd": "E2E", "plugins-directory": "no-plugins", "mods-directory": "no-mods",
            "permissions-file": os.path.join(self.tmp.name, "permissions.json"),
        })
        self.server = MinecraftServer(config, config_path=os.path.join(self.tmp.name, "server.properties"))
        self.server.command_manager = CommandManager(self.server)
        register_all_vanilla_commands(self.server.command_manager)
        self.task = asyncio.create_task(self.server.start())
        await asyncio.wait_for(self.server.wait_until_ready(), 60)
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.request_stop()
        await asyncio.wait_for(self.task, 30)
        await self.server.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    async def test_status_ping(self):
        client = await RawClient.connect(self.port, 1)
        await client.send(0x00)
        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x00)
        status = json.loads(read_string(payload, 0)[0])
        self.assertEqual(status["version"], {"name": "1.21.1", "protocol": 767})
        self.assertEqual(status["description"], {"text": "E2E"})
        self.assertEqual(status["players"]["online"], 0)
        await client.send(0x01, (42).to_bytes(8, "big"))
        packet_id, payload = await client.read()
        self.assertEqual((packet_id, payload), (0x01, (42).to_bytes(8, "big")))
        client.close()

    async def test_login_join_chat_and_quit(self):
        client = await RawClient.connect(self.port, 2)
        await client.send(0x00, write_string("Tester") + write_uuid(uuid.uuid4()))

        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x03)                    # Set Compression
        client.threshold = read_varint(payload, 0)[0]
        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x02)                    # Login Success
        self.assertEqual(read_string(payload, 16)[0], "Tester")
        await client.send(0x03)                              # Login Acknowledged

        # --- configuration ---
        seen = []
        while True:
            packet_id, payload = await client.read()
            seen.append(packet_id)
            if packet_id == 0x03:                            # Finish Configuration
                break
        self.assertEqual(seen.count(0x07), 11)               # all synchronised registries
        self.assertIn(0x0D, seen)                            # Update Tags
        self.assertIn(0x0C, seen)                            # Feature Flags
        self.assertLess(seen.index(0x07), seen.index(0x0D))
        await client.send(0x03)                              # Acknowledge Finish Configuration

        # --- play ---
        play_ids = []
        joined = False
        for _ in range(400):
            packet_id, payload = await client.read()
            play_ids.append(packet_id)
            if packet_id == 0x6C and b"multiplayer.player.joined" in payload:
                joined = True
                break
        self.assertTrue(joined, f"no join message; got {sorted(set(play_ids))}")
        self.assertEqual(play_ids[0], 0x2B)                  # Login (play)
        for required in (0x11, 0x38, 0x0B, 0x27, 0x40, 0x56, 0x13, 0x3E):
            self.assertIn(required, play_ids, hex(required))
        self.assertEqual(len(self.server.get_online_players()), 1)

        # chat is broadcast as <name> message
        chat = (write_string("hello") + bytes(16) + b"\x00" + write_varint(0) + bytes(3))
        await client.send(0x06, chat)
        for _ in range(200):
            packet_id, payload = await client.read()
            if packet_id == 0x6C and b"chat.type.text" in payload:
                self.assertIn(b"hello", payload)
                break
        else:
            self.fail("chat message was not broadcast")

        # the world metadata files exist in vanilla layout
        world = Path(self.tmp.name, "world")
        self.assertTrue((world / "level.dat").exists())
        self.assertTrue((world / "session.lock").exists())
        self.assertTrue(Path(self.tmp.name, "usercache.json").exists())

        client.close()
        for _ in range(100):
            if not self.server.get_online_players():
                break
            await asyncio.sleep(0.05)
        self.assertEqual(self.server.get_online_players(), [])
        self.assertTrue(any(world.joinpath("playerdata").iterdir()))


def _cryptography_available() -> bool:
    from network import encryption
    return encryption.available()


@unittest.skipUnless(_native_terrain_available() and _cryptography_available(),
                     "needs the native terrain generator and the cryptography package")
class OnlineModeLoginTests(unittest.IsolatedAsyncioTestCase):
    """online-mode=true against a local stand-in for the Mojang session server."""

    PROFILE_ID = "069a79f444e94726a5befca90e38aaf5"

    async def asyncSetUp(self):
        from commands import CommandManager, register_all_vanilla_commands
        from config import DEFAULT_CONFIG
        from network.server import MinecraftServer

        self.requests = []

        async def session_server(reader, writer):
            request_line = (await reader.readline()).decode()
            while (await reader.readline()).strip():
                pass
            self.requests.append(request_line)
            body = json.dumps({
                "id": self.PROFILE_ID, "name": "Notch",
                "properties": [{"name": "textures", "value": "dGV4", "signature": "c2ln"}],
            }).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
            writer.close()

        self.session = await asyncio.start_server(session_server, "127.0.0.1", 0)
        session_port = self.session.sockets[0].getsockname()[1]
        self.old_env = os.environ.get("PYMC_SESSION_SERVER")
        os.environ["PYMC_SESSION_SERVER"] = f"http://127.0.0.1:{session_port}/hasJoined"

        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        config = dict(DEFAULT_CONFIG)
        config.update({
            "server-ip": "127.0.0.1", "server-port": 0,
            "online-mode": True, "level-seed": "1", "view-distance": 2,
            "join-immediate-radius": 1, "plugins-directory": "no-plugins",
            "mods-directory": "no-mods",
            "permissions-file": os.path.join(self.tmp.name, "permissions.json"),
        })
        self.server = MinecraftServer(config, config_path=os.path.join(self.tmp.name, "server.properties"))
        self.server.command_manager = CommandManager(self.server)
        register_all_vanilla_commands(self.server.command_manager)
        self.task = asyncio.create_task(self.server.start())
        await asyncio.wait_for(self.server.wait_until_ready(), 60)
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.request_stop()
        await asyncio.wait_for(self.task, 30)
        await self.server.stop()
        self.session.close()
        if self.old_env is None:
            os.environ.pop("PYMC_SESSION_SERVER", None)
        else:
            os.environ["PYMC_SESSION_SERVER"] = self.old_env
        os.chdir(self.cwd)
        self.tmp.cleanup()

    async def test_encrypted_login_uses_session_profile(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from network.encryption import DecryptingReader, StreamCipher, server_id_hash

        client = await RawClient.connect(self.port, 2)
        await client.send(0x00, write_string("notch") + write_uuid(uuid.uuid4()))

        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x01)                    # Encryption Request
        server_id, offset = read_string(payload, 0)
        key_length, offset = read_varint(payload, offset)
        public_der = payload[offset:offset + key_length]
        offset += key_length
        token_length, offset = read_varint(payload, offset)
        token = payload[offset:offset + token_length]
        self.assertEqual(server_id, "")

        public_key = serialization.load_der_public_key(public_der)
        secret = os.urandom(16)
        encrypted_secret = public_key.encrypt(secret, padding.PKCS1v15())
        encrypted_token = public_key.encrypt(token, padding.PKCS1v15())
        await client.send(0x01, write_varint(len(encrypted_secret)) + encrypted_secret
                          + write_varint(len(encrypted_token)) + encrypted_token)

        # everything from here on is AES/CFB8 encrypted in both directions
        cipher = StreamCipher(secret)
        client.reader = DecryptingReader(client.reader, cipher)
        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x03)                    # Set Compression
        client.threshold = read_varint(payload, 0)[0]
        packet_id, payload = await client.read()
        self.assertEqual(packet_id, 0x02)                    # Login Success
        self.assertEqual(payload[:16], uuid.UUID(self.PROFILE_ID).bytes)
        name, offset = read_string(payload, 16)
        self.assertEqual(name, "Notch")                      # canonical name from the profile
        property_count, offset = read_varint(payload, offset)
        self.assertEqual(property_count, 1)
        self.assertEqual(read_string(payload, offset)[0], "textures")

        expected_hash = server_id_hash("", secret, public_der)
        self.assertIn(f"serverId={expected_hash}", self.requests[0])
        self.assertIn("username=notch", self.requests[0])
        client.close()


if __name__ == "__main__":
    unittest.main()
