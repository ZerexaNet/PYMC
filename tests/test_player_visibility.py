import struct
import unittest
import uuid
from types import SimpleNamespace

from handlers.play.entities import ENTITY_TYPE_IDS
from handlers.play.players import (
    PLAYER_ENTITY_TYPE,
    ROTATE_HEAD_PID,
    SET_ENTITY_DATA_PID,
    SPAWN_ENTITY_PID,
    build_player_metadata_payload,
    build_rotate_head_payload,
    build_spawn_player_payload,
    relay_player_movement,
    send_player_spawn,
    sync_player_visibility,
)
from protocol.data_types import read_varint


class FakeConn:
    def __init__(self, username, entity_id, x=0.0, z=0.0, version_handler=None):
        self.username = username
        self.entity_id = entity_id
        self.uuid = uuid.uuid4()
        self.x = x
        self.y = 64.0
        self.z = z
        self.yaw = 90.0
        self.pitch = 0.0
        self.on_ground = True
        self.alive = True
        self.version_handler = version_handler
        self.protocol_version = 767
        self.tracked_players = set()
        self.sent = []  # (packet_id, payload)

    async def send_packet(self, packet_id, payload=b""):
        self.sent.append((packet_id, payload))


def make_server(conns, view_distance=10, optimizer=None):
    return SimpleNamespace(
        view_distance=view_distance,
        network_optimizer=optimizer,
        get_online_players=lambda: list(conns),
    )


class EntityTypeIdTests(unittest.TestCase):
    """1.21.1 注册表 ID (minecraft-data pc/1.20.5, 1.21/1.21.1 共用)。"""

    def test_verified_ids(self):
        self.assertEqual(ENTITY_TYPE_IDS["item"], 58)
        self.assertEqual(ENTITY_TYPE_IDS["cow"], 22)
        self.assertEqual(ENTITY_TYPE_IDS["pig"], 77)
        self.assertEqual(ENTITY_TYPE_IDS["sheep"], 87)
        self.assertEqual(ENTITY_TYPE_IDS["zombie"], 124)
        self.assertEqual(PLAYER_ENTITY_TYPE, 128)


class SpawnPayloadTests(unittest.TestCase):
    def test_spawn_payload_layout(self):
        player = FakeConn("Alex", 42, x=1.5, z=-2.5)
        payload = build_spawn_player_payload(player)
        eid, offset = read_varint(payload, 0)
        self.assertEqual(eid, 42)
        # UUID (16 bytes) 之后是类型 VarInt
        type_id, _ = read_varint(payload, offset + 16)
        self.assertEqual(type_id, PLAYER_ENTITY_TYPE)

    def test_metadata_payload_shows_all_skin_parts(self):
        player = FakeConn("Alex", 42)
        payload = build_player_metadata_payload(player)
        eid, offset = read_varint(payload, 0)
        self.assertEqual(eid, 42)
        self.assertEqual(payload[offset], 17)      # skin parts index
        type_id, offset2 = read_varint(payload, offset + 1)
        self.assertEqual(type_id, 0)               # Byte
        self.assertEqual(payload[offset2], 0x7F)   # all layers
        self.assertEqual(payload[offset2 + 1], 0xFF)

    def test_rotate_head_payload(self):
        player = FakeConn("Alex", 42)
        player.yaw = 180.0
        payload = build_rotate_head_payload(player)
        eid, offset = read_varint(payload, 0)
        self.assertEqual(eid, 42)
        self.assertEqual(payload[offset], 128)  # 180° -> 180/360*256 = 128


class SpawnSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawn_sends_spawn_and_metadata(self):
        observer = FakeConn("Steve", 1)
        player = FakeConn("Alex", 2)
        await send_player_spawn(observer, player)
        pids = [pid for pid, _ in observer.sent]
        self.assertEqual(pids, [SPAWN_ENTITY_PID, SET_ENTITY_DATA_PID])
        self.assertIn(2, observer.tracked_players)

    async def test_spawn_is_idempotent(self):
        observer = FakeConn("Steve", 1)
        player = FakeConn("Alex", 2)
        await send_player_spawn(observer, player)
        await send_player_spawn(observer, player)
        self.assertEqual(len(observer.sent), 2)

    async def test_spawn_skipped_for_versioned_clients(self):
        observer = FakeConn("Steve", 1, version_handler=object())
        player = FakeConn("Alex", 2)
        await send_player_spawn(observer, player)
        self.assertEqual(observer.sent, [])

    async def test_visibility_sync_is_bidirectional(self):
        a = FakeConn("Steve", 1)
        b = FakeConn("Alex", 2)
        server = make_server([a, b])
        await sync_player_visibility(server, b)
        self.assertIn(2, a.tracked_players)
        self.assertIn(1, b.tracked_players)


class MovementRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_relay_sends_teleport_and_head_rotation(self):
        a = FakeConn("Steve", 1)
        b = FakeConn("Alex", 2)
        a.tracked_players.add(2)
        server = make_server([a, b])
        await relay_player_movement(server, b)
        pids = [pid for pid, _ in a.sent]
        self.assertIn(0x70, pids)          # entity_teleport (767)
        self.assertIn(ROTATE_HEAD_PID, pids)

    async def test_relay_skips_untracked_or_far_observers(self):
        near = FakeConn("Near", 1)
        far = FakeConn("Far", 3, x=10000.0)
        untracked = FakeConn("Untracked", 4)
        near.tracked_players.add(2)
        far.tracked_players.add(2)
        moved = FakeConn("Alex", 2)
        server = make_server([near, far, untracked, moved], view_distance=10)
        await relay_player_movement(server, moved)
        self.assertTrue(near.sent)
        self.assertEqual(far.sent, [])
        self.assertEqual(untracked.sent, [])

    async def test_relay_rate_limited_by_optimizer(self):
        a = FakeConn("Steve", 1)
        b = FakeConn("Alex", 2)
        a.tracked_players.add(2)
        optimizer = SimpleNamespace(should_send_movement=lambda conn: False)
        server = make_server([a, b], optimizer=optimizer)
        await relay_player_movement(server, b)
        self.assertEqual(a.sent, [])


if __name__ == "__main__":
    unittest.main()
