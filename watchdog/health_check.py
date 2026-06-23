# ============================================================
# PyMC - Health Check System
# UDP-based health checking for the watchdog system
# ============================================================

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("PyMC.健康检查")


class HealthCheckServer:
    """UDP server for health checking."""

    def __init__(self, watchdog_manager, port: int):
        self.watchdog = watchdog_manager
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._running = False

    async def start(self):
        """Start the health check UDP server."""
        self._running = True
        loop = asyncio.get_running_loop()

        class _Protocol(asyncio.DatagramProtocol):
            def __init__(self, health_server: HealthCheckServer):
                self.health_server = health_server
                self.transport = None

            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                try:
                    message = data.decode('utf-8', errors='replace')
                    self.health_server._handle_request(message, addr)
                except Exception as e:
                    logger.debug(f"Health check request error: {e}")

            def error_received(self, exc):
                logger.debug(f"Health check protocol error: {exc}")

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _Protocol(self),
                local_addr=('0.0.0.0', self.port),
            )
            self._transport = transport
            logger.info(f"健康检查服务器已启动于 UDP 端口 {self.port}")
        except OSError as e:
            logger.warning(f"无法启动健康检查服务器于端口 {self.port}: {e}")

    async def stop(self):
        """Stop the health check server."""
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None

    def _handle_request(self, message: str, addr: tuple):
        """Handle an incoming health check request."""
        if message == "PYMC_PING":
            # Respond with health status
            status = self.watchdog.get_health_status()
            response = f"PYMC_HEALTH|{json.dumps(status)}"
            if self._transport:
                self._transport.sendto(response.encode('utf-8'), addr)
        elif message.startswith("PYMC_HB|"):
            # Forward to watchdog manager
            self.watchdog._handle_incoming_message(message, addr)


class HealthCheckClient:
    """Client for checking health of partner process."""

    def __init__(self, port: int, timeout: float = 2.0):
        self.port = port
        self.timeout = timeout

    async def check_health(self) -> dict | None:
        """Send a health check ping and return the response."""
        try:
            loop = asyncio.get_running_loop()

            # Create a temporary UDP socket
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)

            # Send ping
            await loop.run_in_executor(
                None,
                lambda: sock.sendto(b"PYMC_PING", ('127.0.0.1', self.port))
            )

            # Wait for response
            try:
                data, addr = await asyncio.wait_for(
                    loop.run_in_executor(None, sock.recvfrom, 4096),
                    timeout=self.timeout,
                )
                message = data.decode('utf-8', errors='replace')
                if message.startswith("PYMC_HEALTH|"):
                    json_str = message[len("PYMC_HEALTH|"):]
                    return json.loads(json_str)
            except asyncio.TimeoutError:
                return None
            finally:
                sock.close()

        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return None


class HealthMetrics:
    """Track health metrics over time."""

    def __init__(self, max_history: int = 60):
        self.max_history = max_history
        self.tps_history: list[tuple[float, float]] = []  # (timestamp, tps)
        self.player_history: list[tuple[float, int]] = []  # (timestamp, players)
        self.memory_history: list[tuple[float, float]] = []  # (timestamp, memory_mb)
        self.heartbeat_history: list[tuple[float, bool]] = []  # (timestamp, received)

    def record_tps(self, tps: float):
        """Record a TPS measurement."""
        self.tps_history.append((time.time(), tps))
        self._trim(self.tps_history)

    def record_players(self, count: int):
        """Record player count."""
        self.player_history.append((time.time(), count))
        self._trim(self.player_history)

    def record_memory(self, mb: float):
        """Record memory usage."""
        self.memory_history.append((time.time(), mb))
        self._trim(self.memory_history)

    def record_heartbeat(self, received: bool):
        """Record a heartbeat check result."""
        self.heartbeat_history.append((time.time(), received))
        self._trim(self.heartbeat_history)

    def get_average_tps(self, window_seconds: float = 60.0) -> float:
        """Get average TPS over the last N seconds."""
        cutoff = time.time() - window_seconds
        recent = [(t, v) for t, v in self.tps_history if t >= cutoff]
        if not recent:
            return 20.0
        return sum(v for _, v in recent) / len(recent)

    def get_tps_trend(self) -> str:
        """Get TPS trend (improving/stable/declining)."""
        if len(self.tps_history) < 6:
            return "stable"
        recent = self.tps_history[-6:]
        first_half = sum(v for _, v in recent[:3]) / 3
        second_half = sum(v for _, v in recent[3:]) / 3
        diff = second_half - first_half
        if diff > 2:
            return "improving"
        elif diff < -2:
            return "declining"
        return "stable"

    def _trim(self, history: list):
        """Trim history to max length."""
        while len(history) > self.max_history:
            history.pop(0)
