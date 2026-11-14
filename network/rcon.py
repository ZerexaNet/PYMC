# ============================================================
# PyMC - RCON (Source RCON 协议)
# ============================================================

"""
Remote console, wire-compatible with the vanilla server's RCON
(``enable-rcon`` / ``rcon.port`` / ``rcon.password`` in server.properties).

Packet layout (little endian):
    int32 length | int32 request id | int32 type | payload (ASCII/UTF-8) | 0x00 0x00

Types: 3 = login, 2 = command (client -> server) / auth response,
       0 = command response.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import struct

logger = logging.getLogger("minecraft.rcon")

TYPE_RESPONSE = 0
TYPE_COMMAND = 2
TYPE_LOGIN = 3
MAX_PAYLOAD = 4096       # vanilla splits responses at 4096 bytes
MAX_REQUEST = 1460 + 14  # vanilla rejects larger request packets


class RconServer:
    def __init__(self, server, host: str, port: int, password: str):
        self.server = server
        self.host = host
        self.port = port
        self.password = password
        self._listener: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        try:
            self._listener = await asyncio.start_server(self._handle, self.host, self.port)
        except OSError as e:
            logger.warning(f"Unable to initialise RCON on {self.host}:{self.port}: {e}")
            return
        logger.info(f"RCON running on {self.host}:{self.port}")

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        for writer in list(self._clients):
            try:
                writer.close()
            except Exception:
                pass
        self._clients.clear()

    @staticmethod
    def _pack(request_id: int, packet_type: int, payload: bytes) -> bytes:
        body = struct.pack("<ii", request_id, packet_type) + payload + b"\x00\x00"
        return struct.pack("<i", len(body)) + body

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        address = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        self._clients.add(writer)
        authenticated = False
        logger.debug(f"Thread RCON Client /{address} started")
        try:
            while True:
                header = await reader.readexactly(4)
                (length,) = struct.unpack("<i", header)
                if length < 10 or length > MAX_REQUEST:
                    break
                body = await reader.readexactly(length)
                request_id, packet_type = struct.unpack_from("<ii", body, 0)
                payload = body[8:-2].decode("utf-8", errors="replace")

                if packet_type == TYPE_LOGIN:
                    authenticated = hmac.compare_digest(
                        payload.encode("utf-8"), self.password.encode("utf-8"))
                    if authenticated:
                        writer.write(self._pack(request_id, TYPE_COMMAND, b""))
                    else:
                        logger.info(f"Rcon connection from /{address} failed authentication")
                        writer.write(self._pack(-1, TYPE_COMMAND, b""))
                    await writer.drain()
                elif packet_type == TYPE_COMMAND:
                    if not authenticated:
                        writer.write(self._pack(-1, TYPE_COMMAND, b""))
                        await writer.drain()
                        continue
                    output = await self._run_command(payload, address)
                    data = output.encode("utf-8")
                    # 至少发送一个 (可能为空的) 响应包
                    for start in range(0, max(1, len(data)), MAX_PAYLOAD):
                        writer.write(self._pack(
                            request_id, TYPE_RESPONSE, data[start:start + MAX_PAYLOAD]))
                    await writer.drain()
                else:
                    writer.write(self._pack(
                        request_id, TYPE_RESPONSE, f"Unknown request {packet_type:x}".encode()))
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self._clients.discard(writer)
            logger.debug(f"Thread RCON Client /{address} shutting down")
            try:
                writer.close()
            except Exception:
                pass

    async def _run_command(self, command: str, address: str) -> str:
        """Run a command as the RCON source and return everything it printed."""
        from commands.framework import capture_console_output
        from handlers.play.chat import execute_server_command

        command = command.strip()
        if command.startswith("/"):
            command = command[1:]
        if not command:
            return ""
        logger.debug(f"[Rcon: /{address}] {command}")
        with capture_console_output(source="Rcon") as lines:
            try:
                await execute_server_command(self.server, command)
            except Exception as e:
                logger.error(f"Error executing RCON command '{command}': {e}", exc_info=True)
                lines.append(f"Error executing: {command} ({e})")
        return "\n".join(lines)
