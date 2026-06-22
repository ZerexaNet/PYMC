# ============================================================
# PyMC - Player Network Optimizer
# Optimize network communication for players
# ============================================================

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict
from typing import Any

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
            logger.info("Network packet batching disabled (network-packet-batching=false)")
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(f"Network optimizer started (batch interval={self.movement_batch_interval*1000:.0f}ms, "
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

        logger.info(f"Network optimizer stopped (batched={self._packets_batched}, "
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

    def optimize_chunk_order(self, conn, chunks: list) -> list:
        """
        Sort chunks by distance from player for smoother loading.

        Prioritizes chunks that are:
        1. Closer to the player (Manhattan distance)
        2. In the direction the player is facing

        Args:
            conn: Player connection (must have x, z, yaw attributes)
            chunks: List of (cx, cz) chunk coordinate tuples

        Returns:
            Sorted list of chunk coordinates
        """
        if not chunks:
            return chunks

        player_cx = int(conn.x) >> 4
        player_cz = int(conn.z) >> 4

        # Calculate facing direction (normalized)
        yaw_rad = math.radians(conn.yaw)
        facing_dx = -math.sin(yaw_rad)
        facing_dz = math.cos(yaw_rad)

        def chunk_priority(chunk_coord) -> float:
            cx, cz = chunk_coord
            # Manhattan distance
            dist = abs(cx - player_cx) + abs(cz - player_cz)

            # Direction bonus: chunks in the facing direction get priority
            dx = cx - player_cx
            dz = cz - player_cz
            if dx != 0 or dz != 0:
                length = math.sqrt(dx * dx + dz * dz)
                ndx, ndz = dx / length, dz / length
                facing_bonus = ndx * facing_dx + ndz * facing_dz
                dist -= facing_bonus * 2.0

            return dist

        return sorted(chunks, key=chunk_priority)

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

    def get_chunk_send_delay(self, conn) -> float:
        """Get the delay between chunk sends for a player."""
        return self.chunk_send_rate

    def should_send_chunk(self, conn) -> bool:
        """Check if we should send a chunk to this player now (rate limiting)."""
        key = conn.username if conn.username else conn.address
        now = time.time()

        last_send = self._last_chunk_send.get(key, 0.0)
        if now - last_send < self.chunk_send_rate:
            return False

        self._last_chunk_send[key] = now
        return True

    def get_stats(self) -> dict:
        """Get optimizer statistics."""
        total_queued = sum(len(q) for q in self.packet_queues.values())
        return {
            "packets_batched": self._packets_batched,
            "packets_sent_directly": self._packets_sent_directly,
            "movements_dropped": self._movements_dropped,
            "currently_queued": total_queued,
            "connections_with_queue": len([q for q in self.packet_queues.values() if q]),
            "movement_rate_hz": self._movement_rate_hz,
            "batch_interval_ms": self.movement_batch_interval * 1000,
            "chunk_send_rate_ms": self.chunk_send_rate * 1000,
        }

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

    def get_batch(self, conn_key: str) -> list[tuple[int, bytes]]:
        """Get and clear the batch for a connection."""
        return self._batches.pop(conn_key, [])

    def has_batch(self, conn_key: str) -> bool:
        """Check if there are queued packets for a connection."""
        return bool(self._batches.get(conn_key))

    def clear(self):
        """Clear all batches."""
        self._batches.clear()


class MovementInterpolator:
    """Interpolate between player positions for smooth rendering."""

    def __init__(self):
        self._positions: dict[str, list[tuple[float, float, float, float]]] = {}
        # username -> [(x, y, z, timestamp), ...]

    def record_position(self, username: str, x: float, y: float, z: float):
        """Record a player position."""
        if username not in self._positions:
            self._positions[username] = []

        self._positions[username].append((x, y, z, time.time()))

        # Keep only recent positions
        if len(self._positions[username]) > 10:
            self._positions[username] = self._positions[username][-10:]

    def get_interpolated_position(self, username: str, render_time: float) -> tuple[float, float, float] | None:
        """
        Get the interpolated position for a given render time.
        This helps smooth out movement when updates come at irregular intervals.
        """
        positions = self._positions.get(username, [])
        if not positions:
            return None

        # Find the two positions bracketing the render time
        before = None
        after = None

        for pos in positions:
            if pos[3] <= render_time:
                before = pos
            elif pos[3] > render_time and after is None:
                after = pos
                break

        if before is None:
            return None

        if after is None:
            return (before[0], before[1], before[2])

        # Linear interpolation
        t0 = before[3]
        t1 = after[3]
        alpha = (render_time - t0) / (t1 - t0) if t1 != t0 else 0.0
        alpha = max(0.0, min(1.0, alpha))

        x = before[0] + (after[0] - before[0]) * alpha
        y = before[1] + (after[1] - before[1]) * alpha
        z = before[2] + (after[2] - before[2]) * alpha

        return (x, y, z)
