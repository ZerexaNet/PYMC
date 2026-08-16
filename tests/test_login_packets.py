import unittest
import uuid
from types import SimpleNamespace

from handlers.login import _send_login_success
from protocol.data_types import read_string, read_varint


class FakeConnection(SimpleNamespace):
    async def send_packet(self, packet_id, payload=b""):
        self.sent = (packet_id, payload)


class LoginSuccessPacketTests(unittest.IsolatedAsyncioTestCase):
    async def encode(self, protocol_version):
        conn = FakeConnection(
            protocol_version=protocol_version,
            uuid=uuid.UUID("b50ad385-829d-3141-a216-7e7d7539ba7f"),
            username="Notch",
            sent=None,
        )
        await _send_login_success(conn)
        self.assertEqual(conn.sent[0], 0x02)
        return conn.sent[1]

    async def test_1_8_uses_string_uuid_without_properties(self):
        payload = await self.encode(47)
        uuid_text, offset = read_string(payload, 0)
        username, offset = read_string(payload, offset)
        self.assertEqual(uuid_text, "b50ad385-829d-3141-a216-7e7d7539ba7f")
        self.assertEqual(username, "Notch")
        self.assertEqual(offset, len(payload))

    async def test_1_16_uses_binary_uuid_without_properties(self):
        payload = await self.encode(736)
        self.assertEqual(payload[:16], uuid.UUID("b50ad385-829d-3141-a216-7e7d7539ba7f").bytes)
        username, offset = read_string(payload, 16)
        self.assertEqual(username, "Notch")
        self.assertEqual(offset, len(payload))

    async def test_1_19_3_includes_empty_properties(self):
        payload = await self.encode(761)
        username, offset = read_string(payload, 16)
        properties, offset = read_varint(payload, offset)
        self.assertEqual(username, "Notch")
        self.assertEqual(properties, 0)
        self.assertEqual(offset, len(payload))

    async def test_1_21_1_includes_strict_flag(self):
        payload = await self.encode(767)
        _, offset = read_string(payload, 16)
        _, offset = read_varint(payload, offset)
        self.assertEqual(payload[offset:], b"\x01")

    async def test_1_21_4_omits_strict_flag(self):
        payload = await self.encode(770)
        _, offset = read_string(payload, 16)
        _, offset = read_varint(payload, offset)
        self.assertEqual(offset, len(payload))


if __name__ == "__main__":
    unittest.main()