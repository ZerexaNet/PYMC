# ============================================================
# PyMC - Watchdog Process Manager
# Manages dual-process mutual protection with UDP heartbeats
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from typing import Any

logger = logging.getLogger("PyMC.watchdog")


class WatchdogManager:
    """
    Dual-process mutual protection system.

    Two processes watch each other via UDP heartbeats.
    If one crashes, the other restarts it.

    Heartbeat protocol:
        PYMC_HB|{pid}|{tps}|{players}|{mem_mb}|{timestamp}

    Control messages:
        PYMC_RESTART|{config_path}  - Restart command
        PYMC_SHUTDOWN|{pid}         - Coordinated shutdown
    """

    def __init__(self, server):
        self.server = server
        self.partner_pid: int | None = None
        self.health_port: int = int(server.config.get('watchdog-health-port', 25569))
        self.max_missed: int = int(server.config.get('watchdog-max-missed-heartbeats', 5))
        self.heartbeat_interval: float = 1.0  # seconds
        self.missed_heartbeats: int = 0
        self._running: bool = False
        self._heartbeat_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._health_server: asyncio.DatagramTransport | None = None
        self.start_time: float = time.time()

        # Partner health info (latest from heartbeat)
        self._partner_tps: float = 0.0
        self._partner_players: int = 0
        self._partner_memory_mb: float = 0.0
        self._partner_last_seen: float = 0.0

        # UDP socket
        self._sock: socket.socket | None = None
        self._partner_port: int = self.health_port + 1

    async def start(self):
        """
        Start watchdog - UDP health server + heartbeat sender + monitor.

        Starts three components:
        1. UDP server on health_port to receive partner heartbeats
        2. Heartbeat sender to partner's health_port
        3. Monitor task that watches for missed heartbeats

        If partner dies, it will be restarted automatically.
        """
        if not self.server.config.get('watchdog-enabled', False):
            logger.info("Watchdog disabled (watchdog-enabled=false)")
            return

        self._running = True
        self.start_time = time.time()

        # Get partner PID from config
        partner_pid = self.server.config.get('watchdog-partner-pid', 0)
        if partner_pid and partner_pid != 0:
            self.partner_pid = int(partner_pid)
            logger.info(f"Watchdog: partner process PID={self.partner_pid}")

        # Start health check UDP server
        await self._start_health_server()

        # Start heartbeat sender
        self._heartbeat_task = asyncio.create_task(self._send_heartbeat_loop())

        # Start heartbeat monitor
        self._monitor_task = asyncio.create_task(self._monitor_partner_loop())

        logger.info(f"Watchdog started (port={self.health_port}, "
                     f"partner_port={self._partner_port}, "
                     f"max_missed={self.max_missed})")

    async def stop(self):
        """Stop the watchdog system."""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        if self._health_server:
            self._health_server.close()

        logger.info("Watchdog stopped")

    # ============================================================
    # Public API (matching spec)
    # ============================================================

    async def send_heartbeat(self):
        """
        Send UDP heartbeat to partner process.

        Format: PYMC_HB|{pid}|{tps}|{players}|{mem_mb}|{timestamp}
        """
        status = self.get_health_status()
        message = (
            f"PYMC_HB|{status['pid']}|{status['tps']:.1f}|"
            f"{status['players']}|{status['memory_mb']:.0f}|"
            f"{status['uptime_seconds']:.0f}"
        )

        try:
            loop = asyncio.get_running_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            await loop.run_in_executor(
                None,
                lambda: sock.sendto(
                    message.encode('utf-8'),
                    ('127.0.0.1', self._partner_port)
                )
            )
            sock.close()
        except Exception as e:
            logger.debug(f"Heartbeat send failed: {e}")

    async def monitor_partner(self):
        """
        Watch for partner heartbeats. Restart if too many missed.

        If missed heartbeats exceed max_missed:
        1. Kill old partner process (SIGKILL)
        2. Start new partner with same config
        3. Wait for first heartbeat from new partner
        """
        if self.partner_pid is not None:
            # Check if partner process is alive via OS signal
            if not self._is_process_alive(self.partner_pid):
                logger.warning(f"Partner process PID={self.partner_pid} is dead, "
                              "attempting restart...")
                await self.restart_partner()
                self.missed_heartbeats = 0
                return

        # Check missed heartbeats
        self.missed_heartbeats += 1
        if self.missed_heartbeats > self.max_missed:
            logger.warning(f"Partner missed {self.missed_heartbeats} heartbeats, "
                          "attempting restart...")
            await self.restart_partner()
            self.missed_heartbeats = 0

    async def handle_heartbeat(self, data: str, addr: tuple):
        """
        Handle incoming heartbeat from partner.

        Args:
            data: The heartbeat message string
            addr: The source address tuple (host, port)
        """
        self.missed_heartbeats = 0  # Reset counter

        # Parse heartbeat: PYMC_HB|{pid}|{tps}|{players}|{mem_mb}|{ts}
        parts = data.split("|")
        if len(parts) >= 5:
            try:
                partner_pid = int(parts[1])
                tps = float(parts[2])
                players = int(parts[3])
                memory_mb = float(parts[4])

                if self.partner_pid is None:
                    self.partner_pid = partner_pid
                    logger.info(f"Watchdog: discovered partner PID={partner_pid}")

                # Store partner health info
                self._partner_tps = tps
                self._partner_players = players
                self._partner_memory_mb = memory_mb
                self._partner_last_seen = time.time()

                logger.debug(f"Partner heartbeat: PID={partner_pid}, "
                            f"TPS={tps:.1f}, players={players}, "
                            f"memory={memory_mb:.0f}MB")
            except (ValueError, IndexError):
                pass

    def get_health_status(self) -> dict:
        """
        Return current health status.

        Returns:
            dict with: pid, tps, players, memory_mb, uptime_seconds
        """
        return {
            "pid": os.getpid(),
            "tps": self.server.metrics.get_tps() if hasattr(self.server, 'metrics') else 20.0,
            "players": len(self.server.get_online_players()),
            "memory_mb": self._get_memory_usage(),
            "uptime_seconds": time.time() - self.start_time,
        }

    async def graceful_shutdown(self):
        """
        Coordinated shutdown - notify partner first.

        Sends PYMC_SHUTDOWN message to partner, waits briefly,
        then stops the local watchdog.
        """
        logger.info("Initiating coordinated shutdown...")

        # Notify partner to also shut down
        try:
            loop = asyncio.get_running_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            message = f"PYMC_SHUTDOWN|{os.getpid()}"
            await loop.run_in_executor(
                None,
                lambda: sock.sendto(
                    message.encode('utf-8'),
                    ('127.0.0.1', self._partner_port)
                )
            )
            sock.close()
            logger.info("Shutdown notification sent to partner")
        except Exception as e:
            logger.debug(f"Failed to send shutdown notification: {e}")

        # Wait briefly for partner acknowledgment
        await asyncio.sleep(2)

        # Both shut down cleanly
        await self.stop()

    # ============================================================
    # Internal implementation
    # ============================================================

    async def _start_health_server(self):
        """Start the UDP health check server."""
        loop = asyncio.get_running_loop()

        class HealthProtocol(asyncio.DatagramProtocol):
            def __init__(self, watchdog: WatchdogManager):
                self.watchdog = watchdog

            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                message = data.decode('utf-8', errors='replace')
                self.watchdog._handle_incoming_message(message, addr)

            def error_received(self, exc):
                logger.debug(f"Health server error: {exc}")

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: HealthProtocol(self),
                local_addr=('0.0.0.0', self.health_port),
            )
            self._health_server = transport
            logger.info(f"Health check UDP server started on port {self.health_port}")
        except OSError as e:
            logger.warning(f"Cannot start health server: {e} (port may be in use)")
            # Try alternate port (swap health and partner ports)
            try:
                alt_port = self._partner_port
                self._partner_port = self.health_port
                self.health_port = alt_port
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: HealthProtocol(self),
                    local_addr=('0.0.0.0', self.health_port),
                )
                self._health_server = transport
                logger.info(f"Health check UDP server started on alternate port {self.health_port}")
            except OSError as e2:
                logger.error(f"Cannot start health server (alternate port also failed): {e2}")

    def _handle_incoming_message(self, message: str, addr: tuple):
        """Handle incoming UDP message."""
        try:
            if message.startswith("PYMC_HB|"):
                # Heartbeat from partner - use public API
                asyncio.ensure_future(self.handle_heartbeat(message, addr))
            elif message.startswith("PYMC_HEALTH|"):
                # Health check response
                pass
            elif message.startswith("PYMC_RESTART|"):
                # Restart command
                self._handle_restart_command(message)
            elif message.startswith("PYMC_SHUTDOWN|"):
                # Coordinated shutdown
                self._handle_shutdown_command(message)
        except Exception as e:
            logger.debug(f"Error handling incoming message: {e}")

    def _handle_restart_command(self, message: str):
        """Handle a restart command from the partner."""
        parts = message.split("|")
        if len(parts) >= 2:
            config_path = parts[1]
            logger.warning(f"Received restart command from partner, config: {config_path}")
            asyncio.ensure_future(self.restart_partner())

    def _handle_shutdown_command(self, message: str):
        """Handle a coordinated shutdown command."""
        logger.info("Received shutdown command from partner")
        self._running = False
        asyncio.ensure_future(self.server.stop())

    async def _send_heartbeat_loop(self):
        """Send periodic heartbeats to the partner process."""
        while self._running:
            try:
                await self.send_heartbeat()
            except Exception as e:
                logger.debug(f"Heartbeat send failed: {e}")
            await asyncio.sleep(self.heartbeat_interval)

    async def _monitor_partner_loop(self):
        """Watch partner's heartbeats. Restart if dead."""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self.monitor_partner()
            except Exception as e:
                logger.debug(f"Monitor error: {e}")

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    async def restart_partner(self):
        """
        Restart the partner process.

        1. Kill old partner process (SIGKILL)
        2. Start new partner with same config
        3. Wait for first heartbeat from new partner
        """
        import subprocess
        import sys

        logger.info("Restarting partner process...")

        # Kill any remaining partner process
        if self.partner_pid is not None:
            try:
                os.kill(self.partner_pid, 9)  # SIGKILL
                logger.info(f"Killed old partner process PID={self.partner_pid}")
            except (ProcessLookupError, PermissionError, OSError):
                pass

        # Start new process with same configuration
        try:
            config_path = getattr(self.server, 'config_path', 'server.properties')
            cmd = [
                sys.executable,
                os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'main.py')),
            ]

            # Set partner PID for the new process
            env = os.environ.copy()
            env['PYMC_HEALTH_PORT'] = str(self._partner_port)
            env['PYMC_PARTNER_PORT'] = str(self.health_port)
            env['PYMC_PARTNER_PID'] = str(os.getpid())

            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.partner_pid = process.pid
            logger.info(f"Started new partner process PID={process.pid}")

            # Notify connected players
            self.server.broadcast_system_message("[PyMC] Partner process restarted")

            # Wait for first heartbeat
            self.missed_heartbeats = 0
            max_wait = 30  # 30 seconds
            waited = 0
            while waited < max_wait and self._running:
                await asyncio.sleep(1)
                waited += 1
                if self.missed_heartbeats == 0:
                    logger.info("Partner process reported healthy")
                    return

            logger.warning(f"Partner process did not report healthy within {max_wait}s")

        except Exception as e:
            logger.error(f"Failed to restart partner process: {e}")

    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import resource
            # RSS in KB on Linux
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if usage > 1024 * 1024:  # Already in bytes (macOS)
                return usage / (1024 * 1024)
            return usage / 1024  # KB to MB
        except Exception:
            try:
                # Try /proc/self/status on Linux
                with open('/proc/self/status', 'r') as f:
                    for line in f:
                        if line.startswith('VmRSS:'):
                            return int(line.split()[1]) / 1024  # KB to MB
            except Exception:
                pass
            return 0.0

    def check_partner_health(self) -> dict:
        """Check the health of the partner process."""
        if self.partner_pid is None:
            return {"status": "no_partner", "alive": False}

        alive = self._is_process_alive(self.partner_pid)
        return {
            "status": "alive" if alive else "dead",
            "pid": self.partner_pid,
            "alive": alive,
            "missed_heartbeats": self.missed_heartbeats,
            "tps": self._partner_tps,
            "players": self._partner_players,
            "memory_mb": self._partner_memory_mb,
            "last_seen": self._partner_last_seen,
        }
