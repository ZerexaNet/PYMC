import unittest
import uuid
from types import SimpleNamespace

from network.connection import Connection
from network.server import MinecraftServer


class LoginIdentityTests(unittest.TestCase):
    def test_offline_uuid_matches_java_name_uuid_vectors(self):
        vectors = {
            "Notch": "b50ad385-829d-3141-a216-7e7d7539ba7f",
            "Steve": "5627dd98-e6be-3c21-b8a8-e92344183641",
            "notch": "42653081-a90e-3475-b3d6-3550cdb43f8e",
        }
        for username, expected in vectors.items():
            conn = SimpleNamespace(username=username)
            actual = Connection.generate_offline_uuid(conn)
            self.assertEqual(actual, uuid.UUID(expected))


class OnlineModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_online_mode_fails_before_server_startup(self):
        server = SimpleNamespace(online_mode=True, running=False)
        with self.assertRaisesRegex(RuntimeError, "session authentication"):
            await MinecraftServer.start(server)
        self.assertFalse(server.running)


if __name__ == "__main__":
    unittest.main()