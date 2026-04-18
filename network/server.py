# ============================================================
# PyMC - TCP 网络服务器
# 管理 TCP 监听、连接接入和数据包分发
# ============================================================

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from config import save_config
from admin.permissions import PermissionManager
from admin.web import WebAdminServer
from .connection import Connection, ConnectionState
from handlers.handshake import handle_handshake
from handlers.status import handle_status
from handlers.login import handle_login
from handlers.configuration import handle_configuration
from handlers.play import handle_play
from world.storage import WorldStorage
from world.terrain import TerrainGenerator
from world.terrain_native import NativeTerrainGenerator
from world.chunk import build_chunk_column_from_terrain, build_heightmap_from_terrain

logger = logging.getLogger("PyMC.服务器")


class MinecraftServer:
    """
    Minecraft TCP 服务器。
    管理所有客户端连接和游戏循环。
    """

    def __init__(self, config: dict, config_path: str = "server.properties"):
        self.config = config
        self.config_path = config_path
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
        self.spawn_position = (
            int(config.get("level-spawn-x", 0)),
            int(config.get("level-spawn-y", 100)),
            int(config.get("level-spawn-z", 0)),
        )
        self.chunk_generation_multithreading = config.get(
            "chunk-generation-multithreading", False
        )
        configured_workers = int(config.get("chunk-generation-workers", 0) or 0)
        self.chunk_generation_workers = (
            configured_workers if configured_workers > 0 else max(2, os.cpu_count() or 2)
        )
        self.join_immediate_radius = max(0, int(config.get("join-immediate-radius", 2)))

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
        self.terrain_generator = None
        self._use_native_terrain = False
        self._chunk_executor: ThreadPoolExecutor | None = None

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
        self._initialize_terrain_generator()
        await self._pregenerate_spawn_area()

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
        if self.should_use_multithreaded_generation():
            logger.info(f"区块生成模式: 多线程 ({self.chunk_generation_workers} 线程)")
        else:
            mode = "单线程"
            if self.chunk_generation_multithreading and self._use_native_terrain:
                mode += " (原生生成器当前使用单线程)"
            logger.info(f"区块生成模式: {mode}")

        startup_time = time.time() - self.start_time
        logger.info(f"启动完成，用时 {startup_time:.1f}s")

        async with self._server:
            await self._server.serve_forever()

    def _initialize_terrain_generator(self):
        """初始化地形生成器，并计算出生点高度。"""
        if self.terrain_generator is not None:
            return

        seed = self.config.get("level-seed", 0)
        if isinstance(seed, str):
            try:
                seed = int(seed)
            except ValueError:
                seed = hash(seed)

        native_gen = NativeTerrainGenerator(seed)
        if native_gen.available:
            self.terrain_generator = native_gen
            self._use_native_terrain = True
            logger.info(f"使用 C++ 原生地形生成器 (种子: {seed})")
        else:
            self.terrain_generator = TerrainGenerator(seed)
            self._use_native_terrain = False
            logger.info(f"使用纯 Python 地形生成器 (种子: {seed})")

        spawn_x, _, spawn_z = self.spawn_position
        if self._use_native_terrain:
            _, hmap = self.terrain_generator.generate_chunk_with_heightmap(
                int(spawn_x) >> 4, int(spawn_z) >> 4
            )
            spawn_y = hmap[int(spawn_z) & 15][int(spawn_x) & 15] + 2
        else:
            spawn_y = self.terrain_generator.get_terrain_height(int(spawn_x), int(spawn_z)) + 2
        self.spawn_position = (int(spawn_x), int(spawn_y), int(spawn_z))

    def save_runtime_config(self):
        """将运行时配置写回 server.properties。"""
        self.config["difficulty"] = self.config.get("difficulty", "normal")
        self.config["gamemode"] = self.config.get("gamemode", "creative")
        self.config["chunk-generation-multithreading"] = self.chunk_generation_multithreading
        self.config["chunk-generation-workers"] = self.config.get("chunk-generation-workers", 0)
        self.config["join-immediate-radius"] = self.join_immediate_radius
        self.config["level-name"] = self.config.get("level-name", "world")
        self.config["level-spawn-x"] = int(self.spawn_position[0])
        self.config["level-spawn-y"] = int(self.spawn_position[1])
        self.config["level-spawn-z"] = int(self.spawn_position[2])
        save_config(self.config, self.config_path)

    def should_use_multithreaded_generation(self) -> bool:
        """是否启用多线程区块生成。"""
        return self.chunk_generation_multithreading and not self._use_native_terrain

    def _get_chunk_executor(self) -> ThreadPoolExecutor:
        """懒初始化区块生成线程池。"""
        if self._chunk_executor is None:
            self._chunk_executor = ThreadPoolExecutor(
                max_workers=self.chunk_generation_workers,
                thread_name_prefix="PyMCChunkGen",
            )
        return self._chunk_executor

    def _generate_or_load_chunk_result(self, cx: int, cz: int):
        """
        加载或生成单个区块，并返回网络发送所需的预编码结果。

        返回:
            (cx, cz, motion_blocking, world_surface, chunk_data, was_loaded, chunk_blocks)
        """
        storage = self.world_storage
        terrain = self.terrain_generator

        chunk_blocks = storage.load_generated_chunk(cx, cz)
        was_loaded = chunk_blocks is not None

        if chunk_blocks is None:
            if self._use_native_terrain:
                chunk_blocks, _ = terrain.generate_chunk_with_heightmap(cx, cz)
            else:
                chunk_blocks = terrain.generate_chunk(cx, cz)

        motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
        world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
        chunk_data = build_chunk_column_from_terrain(chunk_blocks)
        return (cx, cz, motion_blocking, world_surface, chunk_data, was_loaded, chunk_blocks)

    def generate_chunk_results(self, chunk_coords: list[tuple[int, int]]):
        """
        批量加载/生成区块。

        返回:
            (results, loaded, generated)
            results: [(cx, cz, motion_blocking, world_surface, chunk_data), ...]
        """
        results = []
        loaded = 0
        generated = 0

        if self.should_use_multithreaded_generation():
            executor = self._get_chunk_executor()
            chunk_records = list(executor.map(
                lambda pos: self._generate_or_load_chunk_result(*pos),
                chunk_coords,
            ))
        else:
            chunk_records = [
                self._generate_or_load_chunk_result(cx, cz)
                for cx, cz in chunk_coords
            ]

        for cx, cz, motion_blocking, world_surface, chunk_data, was_loaded, chunk_blocks in chunk_records:
            results.append((cx, cz, motion_blocking, world_surface, chunk_data))
            if was_loaded:
                loaded += 1
                continue
            self.world_storage.save_generated_chunk(cx, cz, chunk_blocks)
            generated += 1

        if generated:
            self.world_storage.flush()

        return results, loaded, generated

    async def _pregenerate_spawn_area(self):
        """服务器启动时预生成出生点视距范围内的区块，并写入 Linear V2。"""
        spawn_x, _, spawn_z = self.spawn_position
        center_cx = int(spawn_x) >> 4
        center_cz = int(spawn_z) >> 4
        chunk_coords = [
            (cx, cz)
            for cx in range(center_cx - self.view_distance, center_cx + self.view_distance + 1)
            for cz in range(center_cz - self.view_distance, center_cz + self.view_distance + 1)
        ]

        logger.info(
            f"正在检查出生点区块缓存 {len(chunk_coords)} 个 "
            f"(中心={center_cx},{center_cz} 视距={self.view_distance})..."
        )

        def _generate_spawn_chunks():
            _, loaded, generated = self.generate_chunk_results(chunk_coords)
            return loaded, generated

        start = time.time()
        loaded, generated = await asyncio.get_running_loop().run_in_executor(
            None, _generate_spawn_chunks
        )
        logger.info(
            f"出生点区块预生成完成: 已缓存 {loaded} 个, 新生成 {generated} 个, "
            f"耗时 {time.time() - start:.1f}s"
        )

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

        if self._chunk_executor:
            self._chunk_executor.shutdown(wait=False, cancel_futures=False)
            self._chunk_executor = None

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
