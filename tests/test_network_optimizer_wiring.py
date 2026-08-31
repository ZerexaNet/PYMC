import unittest
from types import SimpleNamespace

from network.server import MinecraftServer


class FakeConn:
    def __init__(self):
        self.username = "Steve"
        self.address = "127.0.0.1:25565"
        self.compression_threshold = -1
        self.alive = True
        self.sent = []

    async def send_packet(self, packet_id, payload=b""):
        self.sent.append((packet_id, payload))


class FakeOptimizer:
    def __init__(self, accept=True):
        self.accept = accept
        self.queued = []

    def queue_packet(self, conn, packet_id, payload):
        if not self.accept:
            return False
        self.queued.append((conn, packet_id, payload))
        return True


class QueueOrSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_queues_when_optimizer_running(self):
        conn = FakeConn()
        optimizer = FakeOptimizer()
        server = SimpleNamespace(network_optimizer=optimizer)
        await MinecraftServer.queue_or_send(server, conn, 0x70, b"abc")
        self.assertEqual(len(optimizer.queued), 1)
        self.assertEqual(optimizer.queued[0][1], 0x70)
        self.assertEqual(conn.sent, [])

    async def test_direct_send_when_optimizer_absent(self):
        conn = FakeConn()
        server = SimpleNamespace(network_optimizer=None)
        await MinecraftServer.queue_or_send(server, conn, 0x70, b"abc")
        self.assertEqual(conn.sent, [(0x70, b"abc")])

    async def test_direct_send_when_queue_rejects(self):
        conn = FakeConn()
        optimizer = FakeOptimizer(accept=False)
        server = SimpleNamespace(network_optimizer=optimizer)
        await MinecraftServer.queue_or_send(server, conn, 0x70, b"abc")
        self.assertEqual(conn.sent, [(0x70, b"abc")])


if __name__ == "__main__":
    unittest.main()
