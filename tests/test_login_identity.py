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


class OnlineModeTests(unittest.TestCase):
    def test_server_hash_matches_known_vectors(self):
        # Reference digests from the protocol documentation (signed hex SHA-1).
        from network.encryption import server_id_hash
        self.assertEqual(server_id_hash("Notch", b"", b""),
                         "4ed1f46bbe04bc756bcb17c0c7ce3e4632f06a48")
        self.assertEqual(server_id_hash("jeb_", b"", b""),
                         "-7c9d5b0044c130109a5d7b5fb5c317c02b4e28c1")
        self.assertEqual(server_id_hash("simon", b"", b""),
                         "88e16a1019277b15d58faf0541e11910eb756f6")


if __name__ == "__main__":
    unittest.main()
