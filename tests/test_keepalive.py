import struct
import time
import unittest
from types import SimpleNamespace

from handlers.play.movement import _handle_keepalive


class KeepAliveTests(unittest.TestCase):
    def make_connection(self):
        return SimpleNamespace(
            username="Tester",
            keepalive_id=123,
            keepalive_pending=True,
            keepalive_sent_at=time.monotonic() - 0.01,
            keepalive_rtt_ms=None,
        )

    def test_matching_response_clears_pending_and_records_rtt(self):
        conn = self.make_connection()
        self.assertTrue(_handle_keepalive(conn, struct.pack(">q", 123)))
        self.assertFalse(conn.keepalive_pending)
        self.assertGreaterEqual(conn.keepalive_rtt_ms, 0.0)

    def test_mismatched_response_is_rejected(self):
        conn = self.make_connection()
        self.assertFalse(_handle_keepalive(conn, struct.pack(">q", 456)))
        self.assertTrue(conn.keepalive_pending)

    def test_truncated_response_is_rejected(self):
        conn = self.make_connection()
        self.assertFalse(_handle_keepalive(conn, b"\x00"))
        self.assertTrue(conn.keepalive_pending)


if __name__ == "__main__":
    unittest.main()