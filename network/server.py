# ============================================================
# PyMC - TCP 网络服务器
# 管理 TCP 监听、连接接入和数据包分发
# ============================================================

import asyncio
import logging
import time
from typing import Optional
from admin.permissions import PermissionManager
from admin.web import WebAdminServer
from .connection import Connection, ConnectionState
from handlers.handshake import handle_handshake
from handlers.status import handle_status
from handlers.login import handle_login
from handlers.configuration import handle_configuration
from handlers.play import handle_play
from world.storage import WorldStorage

logger = logging.getLogger("PyMC.服务器")


class MinecraftServer:
    """
    Minecraft TCP 服务器。
    管理所有客户端连接和游戏循环。
    """

    def __init__(self, config: dict):
        self.config = config
        self.host = config.get("server-ip", "0.0.0.0")
        self.port = config.get("server-port", 25565)
        self.motd = config.get("motd", "PyMC - Python Minecraft 服务器")
        self.max_players = config.get("max-players", 20)
        self.online_mode = config.get("online-mode", False)
        self.compression_threshold = config.get("network-compression-threshold", 256)
        self.view_distance = config.get("view-distance", 10)
        self.autosave_enabled = True
        self.world_time = 1000
        self.weather = "clear"
        self.spawn_position = (0, 100, 0)

        # 世界存储
        world_name = config.get("level-name", "world")
        self.world_storage = WorldStorage(world_name)
        self.permissions = PermissionManager(config.get("permissions-file", "permissions.json"))
        self.web_admin: WebAdminServer | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

        # 在线玩家列表
        self.connections: list[Connection] = []
        self.next_entity_id = 1

        # 服务器状态
        self.running = False
        self.start_time = 0
        self._server: Optional[asyncio.Server] = None
        self._tick_task: Optional[asyncio.Task] = None

    def get_next_entity_id(self) -> int:
        """获取下一个可用的实体 ID。"""
        eid = self.next_entity_id
        self.next_entity_id += 1
        return eid

    def get_online_players(self) -> list[Connection]:
        """获取所有在线玩家 (已进入 Play 状态)。"""
        return [c for c in self.connections
                if c.alive and c.state == ConnectionState.PLAY and c.username]

    def find_player(self, username: str) -> Connection | None:
        """按名称查找在线玩家（不区分大小写）。"""
        target = username.lower()
        for conn in self.get_online_players():
            if conn.username.lower() == target:
                return conn
        return None

    def broadcast_packet(self, packet_id: int, payload: bytes,
                         exclude: Connection = None):
        """向所有在线玩家广播数据包。"""
        for conn in self.get_online_players():
            if conn != exclude:
                asyncio.ensure_future(conn.send_packet(packet_id, payload))

    def broadcast_system_message(self, text: str, exclude: Connection = None):
        """向所有在线玩家广播系统聊天消息。"""
        from handlers.play import build_system_message_payload
        self.broadcast_packet(0x6C, build_system_message_payload(text), exclude=exclude)

    async def start(self):
        """启动服务器。"""
        self.running = True
        self.start_time = time.time()
        self.loop = asyncio.get_running_loop()

        # 初始化世界存储 (Anvil -> Linear 自动转换)
        self.world_storage.initialize()

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port
        )

        # 启动游戏循环 (20 TPS)
        self._tick_task = asyncio.create_task(self._game_loop())

        if self.config.get("web-admin-enabled", True):
            try:
                self.web_admin = WebAdminServer(
                    self,
                    self.config.get("web-admin-host", "0.0.0.0"),
                    self.config.get("web-admin-port", 25568),
                )
                self.web_admin.start()
            except Exception as e:
                logger.error(f"启动 Web 管理台失败: {e}")
                self.web_admin = None

        addr = self._server.sockets[0].getsockname()
        logger.info(f"服务器已启动，监听 {addr[0]}:{addr[1]}")
        logger.info(f"游戏版本: 1.21.1 | 协议版本: 767")
        logger.info(f"最大玩家数: {self.max_players}")
        logger.info(f"在线模式: {'开启' if self.online_mode else '关闭 (离线模式)'}")
        logger.info(f"数据包压缩阈值: {self.compression_threshold} 字节")

        startup_time = time.time() - self.start_time
        logger.info(f"启动完成，用时 {startup_time:.1f}s")

        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        """停止服务器。"""
        logger.info("正在关闭服务器...")
        self.running = False

        # 保存世界数据
        logger.info("正在保存世界数据...")
        self.world_storage.close()
        logger.info("世界数据已保存")

        if self.web_admin:
            self.web_admin.stop()
            self.web_admin = None

        # 断开所有连接
        for conn in list(self.connections):
            await conn.disconnect("服务器关闭")
        self.connections.clear()

        # 停止游戏循环
        if self._tick_task:
            self._tick_task.cancel()

        # 停止 TCP 监听
        if self._server:
            self._server.close()

        logger.info("服务器已关闭")

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        """处理新客户端连接。"""
        conn = Connection(reader, writer, self)
        self.connections.append(conn)

        try:
            while conn.alive and self.running:
                try:
                    packet_id, payload = await conn.read_packet()
                except asyncio.IncompleteReadError:
                    # 客户端断开连接
                    break
                except ValueError as e:
                    logger.warning(f"数据包读取错误 [{conn.address}]: {e}")
                    break

                # 根据连接状态分发数据包
                try:
                    if conn.state == ConnectionState.HANDSHAKE:
                        await handle_handshake(conn, packet_id, payload)
                    elif conn.state == ConnectionState.STATUS:
                        await handle_status(conn, packet_id, payload, self)
                    elif conn.state == ConnectionState.LOGIN:
                        await handle_login(conn, packet_id, payload, self)
                    elif conn.state == ConnectionState.CONFIGURATION:
                        await handle_configuration(conn, packet_id, payload, self)
                    elif conn.state == ConnectionState.PLAY:
                        await handle_play(conn, packet_id, payload, self)
                except Exception as e:
                    logger.error(f"处理数据包异常 [{conn.address}] "
                                 f"状态={conn.state.name} ID=0x{packet_id:02X}: {e}")
                    import traceback
                    traceback.print_exc()
                    break
        finally:
            # 清理连接
            conn.alive = False
            if conn in self.connections:
                self.connections.remove(conn)

            # 如果玩家已登录，通知其他玩家
            if conn.username and conn.state == ConnectionState.PLAY:
                logger.info(f"玩家 {conn.username} 离开了游戏")
                await self._handle_player_leave(conn)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_player_leave(self, conn: Connection):
        """处理玩家离开游戏。"""
        from handlers.play import build_player_info_remove, build_remove_entities
        # 通知其他玩家移除该玩家
        remove_info = build_player_info_remove(conn)
        remove_entity = build_remove_entities([conn.entity_id])
        self.broadcast_packet(0x3D, remove_info)  # Player Info Remove
        self.broadcast_packet(0x42, remove_entity)  # Remove Entities

    async def _game_loop(self):
        """
        服务器主游戏循环。
        目标: 20 TPS (每 tick 50ms)。
        """
        tick_interval = 0.05  # 50ms per tick
        tick_count = 0
        keepalive_interval = 200  # 每 200 tick (10秒) 发一次心跳
        autosave_interval = 6000  # 每 6000 tick (5分钟) 自动保存

        while self.running:
            tick_start = time.time()
            tick_count += 1

            # 发送 KeepAlive 心跳
            if tick_count % keepalive_interval == 0:
                await self._send_keepalive()

            # 自动保存世界数据
            if self.autosave_enabled and tick_count % autosave_interval == 0:
                self.world_storage.flush()

            # 清理无效连接
            self.connections = [c for c in self.connections if c.alive]

            # 计算 tick 用时，补偿延迟
            elapsed = time.time() - tick_start
            sleep_time = max(0, tick_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _send_keepalive(self):
        """向所有在线玩家发送 KeepAlive 数据包。"""
        import struct
        keepalive_id = int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF
        payload = struct.pack('>q', keepalive_id)

        for conn in self.get_online_players():
            conn.keepalive_id = keepalive_id
            await conn.send_packet(0x26, payload)  # KeepAlive (Play, Clientbound)
