# ============================================================
# PyMC - Player Network Optimizer
# Optimize network communication for players
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

logger = logging.getLogger("PyMC.network_optimizer")


class PlayerNetworkOptimizer:
    """
    Batch network packets and rate-limit movement updates.

    Features:
    - Packet batching: Coalesce multiple packets into one TCP write
    - Movement rate limiting: Only send position updates at configured Hz
    - Chunk send ordering: Prioritize nearby chunks by distance + facing
    """

    def __init__(self, server):
        self.server = server
        self.packet_queues: dict[str, list[bytes]] = {}  # per-player queues

        # Config-driven settings
        self.movement_batch_interval: float = 0.05  # 50ms batch window
        self.chunk_send_rate: float = 0.02  # 20ms between chunks
        self._flush_task: asyncio.Task | None = None
        self._running: bool = False

        # Movement rate limiting
        self._last_movement_send: dict[str, float] = {}  # username -> last send time
        self._movement_rate_hz: float = float(
            server.config.get('network-movement-rate-hz', 20.0)
        )

        # Chunk sending
        self._last_chunk_send: dict[str, float] = {}  # username -> last chunk send time

        # Statistics
        self._packets_batched: int = 0
        self._packets_sent_directly: int = 0
        self._movements_dropped: int = 0

    async def start(self):
        """Start the network optimizer."""
        if not self.server.config.get('network-packet-batching', True):
            logger.debug("Network packet batching disabled (network-packet-batching=false)")
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.debug(f"Network optimizer started (batch interval={self.movement_batch_interval*1000:.0f}ms, "
                     f"movement updates={self._movement_rate_hz:.0f}Hz)")

    async def stop(self):
        """Stop the network optimizer."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush any remaining packets
        await self.flush_all()

        logger.debug(f"Network optimizer stopped (batched={self._packets_batched}, "
                     f"direct={self._packets_sent_directly}, "
                     f"movements_dropped={self._movements_dropped})")

    def queue_packet(self, conn, packet_id: int, payload: bytes):
        """
        Queue packet for batched send.

        Instead of sending immediately, the packet is queued and
        all queued packets are flushed in one TCP write call.

        Args:
            conn: Player connection
            packet_id: Packet ID
            payload: Packet payload bytes
        """
        if not self._running:
            return False

        key = conn.username or conn.address
        if key not in self.packet_queues:
            self.packet_queues[key] = []

        # Prepend packet_id + length header and payload together
        from protocol.packet import pack_packet
        frame = pack_packet(packet_id, payload, conn.compression_threshold)
        self.packet_queues[key].append(frame)
        self._packets_batched += 1
        return True

    async def flush_all(self):
        """
        Send all queued packets as single TCP write per player.

        Coalesces all queued packets for each player into one
        write() call, reducing system call overhead.
        """
        for key in list(self.packet_queues.keys()):
            packets = self.packet_queues.get(key, [])
            if not packets:
                continue

            # Find the connection
            conn = None
            for player in self.server.get_online_players():
                if (player.username or player.address) == key:
                    conn = player
                    break

            if conn is None:
                # Connection no longer exists, discard
                self.packet_queues.pop(key, None)
                continue

            if not conn.alive:
                self.packet_queues.pop(key, None)
                continue

            try:
                # Combine all frames into single buffer
                buffer = bytearray()
                for frame in packets:
                    buffer.extend(frame)

                # Single write call
                conn.writer.write(bytes(buffer))
                await conn.writer.drain()
            except (ConnectionError, OSError) as e:
                logger.debug(f"Batched send failed [{conn.address}]: {e}")
                conn.alive = False

            # Clear the queue for this player
            self.packet_queues[key] = []

    def should_send_movement(self, conn) -> bool:
        """
        Rate-limit movement updates to other players.

        Only sends position updates at the configured Hz rate.
        Interpolate between positions for smooth rendering.
        """
        key = conn.username if conn.username else conn.address
        now = time.time()

        last_send = self._last_movement_send.get(key, 0.0)
        min_interval = 1.0 / self._movement_rate_hz

        if now - last_send < min_interval:
            self._movements_dropped += 1
            return False

        self._last_movement_send[key] = now
        return True

    async def _flush_loop(self):
        """Periodically flush all queued packets."""
        while self._running:
            try:
                await self.flush_all()
            except Exception as e:
                logger.debug(f"Flush loop error: {e}")
            await asyncio.sleep(self.movement_batch_interval)


class PacketBatcher:
    """Batch multiple packets for efficient sending."""

    def __init__(self):
        self._batches: dict[str, list[tuple[int, bytes]]] = defaultdict(list)

    def add(self, conn_key: str, packet_id: int, payload: bytes):
        """Add a packet to the batch."""
        self._batches[conn_key].append((packet_id, payload))

    def clear(self):
        """Clear all batches."""
        self._batches.clear()


