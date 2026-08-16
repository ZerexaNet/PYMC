import unittest
from types import SimpleNamespace

from handlers.play import _is_serverbound_packet
from handlers.versioned import get_version_handler
from protocol.packet_map import get_clientbound_packet


class PlayDispatchTests(unittest.TestCase):
    def test_native_packet_ids_are_used_for_native_protocol(self):
        conn = SimpleNamespace(protocol_version=767)
        self.assertTrue(_is_serverbound_packet(conn, 0x1A, "keep_alive", 0x1A))
        self.assertTrue(_is_serverbound_packet(conn, 0x0C, "click_container", 0x0C))

    def test_native_packet_ids_do_not_leak_into_old_protocols(self):
        conn = SimpleNamespace(protocol_version=47)
        self.assertFalse(_is_serverbound_packet(conn, 0x1A, "keep_alive", 0x1A))
        self.assertTrue(_is_serverbound_packet(conn, 0x00, "keep_alive", 0x1A))

    def test_unknown_packet_name_does_not_match_old_protocol(self):
        conn = SimpleNamespace(protocol_version=340)
        self.assertFalse(_is_serverbound_packet(conn, 0x0C, "click_container", 0x0C))

    def test_1_21_4_uses_its_versioned_interaction_ids(self):
        conn = SimpleNamespace(protocol_version=770)
        self.assertTrue(_is_serverbound_packet(conn, 0x10, "click_container", 0x0C))
        self.assertTrue(_is_serverbound_packet(conn, 0x3D, "use_item", 0x29))
        self.assertFalse(_is_serverbound_packet(conn, 0x0C, "click_container", 0x0C))

    def test_grouped_handler_preserves_exact_negotiated_protocol(self):
        handler = get_version_handler(770)
        self.assertEqual(handler.PROTOCOL_VERSION, 770)
        self.assertEqual(
            handler.get_packet_id("keep_alive"),
            get_clientbound_packet(770, "keep_alive"),
        )

    def test_1_19_protocol_routes_to_1_19_handler(self):
        handler = get_version_handler(761)
        self.assertEqual(handler.__class__.__name__, "VersionHandlerV1_19")


if __name__ == "__main__":
    unittest.main()