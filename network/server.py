# ============================================================
# PyMC - TCP 网络服务器
# 管理 TCP 监听、连接接入和数据包分发
# ============================================================

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from pathlib import Path
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
from world.biomes import BiomeSampler
from world.entities import EntityManager
from world.redstone import RedstoneEngine
from world.vanilla_terrain import VanillaTerrainGenerator
from world.inventory import PlayerInventory
from world.block_behavior import ContainerManager, container_manager
from world.fluids import FluidSystem
from watchdog import WatchdogManager, PlayerNetworkOptimizer
from .managers.gamerule import GameruleManager
from .managers.time import TimeManager
from .managers.scheduler import TickScheduler
from .managers.metrics import ServerMetrics
from .managers.protocol import PacketCache, PacketBatcher

logger = logging.getLogger("PyMC.服务器")


def parse_vanilla_seed(seed_value) -> int:
    """
    Parse level-seed like vanilla Java Edition.

    Numeric strings are parsed as signed 64-bit integers. Non-numeric strings
    fall back to Java String.hashCode(), promoted to long. Python's hash() is
    intentionally randomized between processes, so it cannot be used for
    reproducible Minecraft seeds.
    """
    if isinstance(seed_value, int):
        return seed_value
    text = str(seed_value or "").strip()
    if not text:
        return 0
    try:
        value = int(text)
        if -(1 << 63) <= value <= (1 << 63) - 1:
            return value
    except ValueError:
        pass

    h = 0
    for ch in text:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    return h


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
        # 使用 TimeManager 管理世界时间和天气
        self._time_manager = TimeManager(initial_time=1000)
        self._gamerule_manager = GameruleManager()

        # 向后兼容属性
        self.world_time = 1000
        self.weather = "clear"
        self.gamerules = self._gamerule_manager
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
        self.biome_sampler = None
        self._use_native_terrain = False
        self._chunk_executor: ThreadPoolExecutor | None = None
        self._process_executor: ProcessPoolExecutor | None = None
        self.entity_manager = EntityManager(self)
        self.redstone_engine: RedstoneEngine | None = None

        # 流体系统
        self.fluid_system: FluidSystem | None = None

        # 网络优化器
        self.network_optimizer: PlayerNetworkOptimizer | None = None

        # Watchdog
        self.watchdog_manager: WatchdogManager | None = None

        # Mod 和插件管理器
        self.mod_manager = None
        self.plugin_manager = None

        # 延迟任务调度器
        self.scheduler = TickScheduler()

        # 服务器指标
        self.metrics = ServerMetrics()

        # 协议优化
        self._packet_cache = PacketCache()

        # 命令框架
        self.command_manager = None  # Initialized in main.py

    def get_next_entity_id(self) -> int:
        """获取下一个可用的实体 ID。"""
        eid = self.next_entity_id
        self.next_entity_id += 1
        return eid

    def get_block_at(self, world_x: int, world_y: int, world_z: int) -> int | None:
        """读取世界坐标处的方块 ID。"""
        if world_y < -64 or world_y >= 320:
            return None
        chunk_x = int(world_x) >> 4
        chunk_z = int(world_z) >> 4
        chunk_blocks = self.world_storage.load_generated_chunk(chunk_x, chunk_z)
        if chunk_blocks is None:
            return None
        local_x = int(world_x) & 15
        local_z = int(world_z) & 15
        return int(chunk_blocks[world_y + 64][local_z][local_x])

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
        for conn in self.get_online_players():
            if conn != exclude and conn.version_handler is not None:
                asyncio.ensure_future(conn.version_handler.send_system_chat(conn, text))

    def save_player_state(self, conn: Connection):
        """保存单个玩家存档。"""
        if not conn.username:
            return

        # 基础玩家状态
        player_data = {
            "username": conn.username,
            "x": conn.x,
            "y": conn.y,
            "z": conn.z,
            "yaw": conn.yaw,
            "pitch": conn.pitch,
            "health": conn.health,
            "food": conn.food,
            "saturation": conn.saturation,
            "experience_total": conn.experience_total,
            "experience_level": conn.experience_level,
            "experience_progress": conn.experience_progress,
            "gamemode": conn.gamemode,
            "on_ground": conn.on_ground,
            "air_supply": conn.air_supply,
            "fire_ticks": conn.fire_ticks,
            "freeze_ticks": conn.freeze_ticks,
            "personal_spawn": list(conn.personal_spawn) if conn.personal_spawn is not None else None,
        }

        # 保存物品栏数据
        if hasattr(conn, 'inventory_obj') and conn.inventory_obj is not None:
            player_data["inventory"] = conn.inventory_obj.serialize_full()

        self.world_storage.save_player_data(str(conn.uuid), player_data)

    def save_all_player_states(self):
        """保存所有在线玩家存档。"""
        for conn in self.get_online_players():
            self.save_player_state(conn)

    async def start(self):
        """启动服务器。"""
        if self.online_mode:
            raise RuntimeError(
                "online-mode=true is not supported yet: encryption and Mojang "
                "session authentication are not implemented"
            )
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

        # 初始化红石引擎
        if self.config.get("redstone-enabled", True):
            self.redstone_engine = RedstoneEngine(self)
            logger.info("红石引擎已初始化")
        else:
            logger.info("红石引擎已禁用 (redstone-enabled=false)")

        # 初始化流体系统
        if self.config.get("fluid-flow-enabled", True):
            self.fluid_system = FluidSystem(self)
            logger.info("流体系统已初始化")
        else:
            logger.info("流体系统已禁用 (fluid-flow-enabled=false)")

        # 初始化网络优化器
        self.network_optimizer = PlayerNetworkOptimizer(self)
        await self.network_optimizer.start()

        # 初始化命令框架 (如果 main.py 没有提前初始化)
        if self.command_manager is None:
            from commands import CommandManager, register_all_vanilla_commands
            self.command_manager = CommandManager(self)
            register_all_vanilla_commands(self.command_manager)
            cmd_count = len(self.command_manager.commands)
            logger.info(f"命令框架已初始化: {cmd_count} 个命令已注册")

        # Mod 管理器集成 (如果 main.py 没有提前初始化)
        if self.mod_manager is None:
            from mods.bridge import init_mod_system
            mods_dir = self.config.get("mods-directory", "mods")
            init_mod_system(self, mods_dir)
            logger.info(f"Mod 管理器已初始化: {self.mod_manager.mod_count} 个 Mod 已启用")

        # 插件管理器集成 (如果 main.py 没有提前初始化)
        if self.plugin_manager is None:
            from plugins.bridge import init_plugin_system
            plugins_dir = self.config.get("plugins-directory", "plugins")
            init_plugin_system(self, plugins_dir)
            logger.info(f"插件管理器已初始化: {self.plugin_manager.plugin_count} 个插件已启用")

        # 启动游戏循环 (20 TPS)
        self._tick_task = asyncio.create_task(self._game_loop())

        if self.config.get("web-admin-enabled", True):
            try:
                self.web_admin = WebAdminServer(
                    self,
                    self.config.get("web-admin-host", "127.0.0.1"),
                    self.config.get("web-admin-port", 25568),
                    self.config.get("web-admin-allow-remote", False),
                )
                self.web_admin.start()
            except Exception as e:
                logger.error(f"启动 Web 管理台失败: {e}")
                self.web_admin = None

        addr = self._server.sockets[0].getsockname()
        logger.info(f"服务器已启动，监听 {addr[0]}:{addr[1]}")
        logger.info(f"游戏版本: 1.21.1 | 协议版本: 767 | 多版本支持: 1.8-1.21")
        logger.info(f"支持协议版本: {self.config.get('min-protocol-version', 47)} - {self.config.get('max-protocol-version', 770)}")
        logger.info(f"最大玩家数: {self.max_players}")
        logger.info(f"在线模式: {'开启' if self.online_mode else '关闭 (离线模式)'}")
        logger.info(f"数据包压缩阈值: {self.compression_threshold} 字节")
        if self.should_use_multithreaded_generation():
            logger.info(f"区块生成模式: 多线程 ({self.chunk_generation_workers} 线程)")
        else:
            mode = "单线程"
            if self._use_native_terrain:
                mode = f"原生生成器内部并行 ({max(2, os.cpu_count() or 2)} 线程)"
            logger.info(f"区块生成模式: {mode}")

        startup_time = time.time() - self.start_time
        logger.info(f"启动完成，用时 {startup_time:.1f}s")

        async with self._server:
            await self._server.serve_forever()

    def _initialize_terrain_generator(self):
        """初始化地形生成器，并计算出生点高度。"""
        if self.terrain_generator is not None:
            return

        seed = parse_vanilla_seed(self.config.get("level-seed", 0))

        explicit_native_path = None
        # Pick binary name based on current OS
        if os.name == "nt":
            binary_names = ["terrain_gen.exe", "terrain_gen"]
        else:
            binary_names = ["terrain_gen", "terrain_gen.exe"]
        search_roots = [
            Path.cwd(),
            Path(__file__).resolve().parent.parent,
            Path(getattr(os, "_MEIPASS", Path.cwd())),
        ]
        for root in search_roots:
            for relative in ("native", "."):
                base = root / relative
                for name in binary_names:
                    candidate = (base / name).resolve()
                    if candidate.exists() and candidate.is_file():
                        # Validate file format to avoid running wrong-arch binary
                        try:
                            with open(candidate, 'rb') as f:
                                magic = f.read(4)
                            if os.name == "nt" and magic[:2] != b'MZ':
                                continue  # Not a valid PE executable
                            elif os.name != "nt" and magic != b'\x7fELF':
                                continue  # Not a valid ELF executable
                        except Exception:
                            continue
                        explicit_native_path = str(candidate)
                        break
                if explicit_native_path:
                    break
            if explicit_native_path:
                break

        native_gen = NativeTerrainGenerator(
            seed,
            binary_path=explicit_native_path,
            worker_count=max(2, os.cpu_count() or 2),
        )
        self.biome_sampler = BiomeSampler(seed)

        # 选择地形生成器: 原生 > Vanilla > 纯 Python
        use_vanilla = self.config.get("vanilla-terrain", True)
        if native_gen.available:
            self.terrain_generator = native_gen
            self._use_native_terrain = True
            logger.info(f"使用 C++ 原生地形生成器 (种子: {seed})")
        elif use_vanilla:
            try:
                self.terrain_generator = VanillaTerrainGenerator(seed)
                self._use_native_terrain = False
                logger.info(f"使用 Vanilla 地形生成器 (种子: {seed})")
            except Exception as e:
                logger.warning(f"Vanilla 地形生成器初始化失败: {e}，回退到基础生成器")
                self.terrain_generator = TerrainGenerator(seed)
                self._use_native_terrain = False
                logger.info(f"使用纯 Python 地形生成器 (种子: {seed})")
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
        """是否启用 Python 侧多线程区块生成。"""
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

        loaded_chunk = storage.load_generated_chunk_with_biomes(cx, cz)
        if loaded_chunk is not None:
            chunk_blocks, chunk_biomes = loaded_chunk
        else:
            chunk_blocks, chunk_biomes = None, None
        was_loaded = chunk_blocks is not None

        if chunk_blocks is None:
            if self._use_native_terrain and hasattr(terrain, "generate_chunk_with_metadata"):
                chunk_blocks, _, chunk_biomes = terrain.generate_chunk_with_metadata(cx, cz)
            elif self._use_native_terrain:
                chunk_blocks, _ = terrain.generate_chunk_with_heightmap(cx, cz)
            else:
                chunk_blocks = terrain.generate_chunk(cx, cz)

        if chunk_biomes is None:
            chunk_biomes = self.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
        motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
        world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
        chunk_data = build_chunk_column_from_terrain(chunk_blocks, chunk_biomes)
        return (cx, cz, motion_blocking, world_surface, chunk_data, was_loaded, chunk_blocks, chunk_biomes)

    def generate_chunk_results(self, chunk_coords: list[tuple[int, int]]):
        """
        批量加载/生成区块。

        返回:
            (results, loaded, generated)
            results: [(cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks), ...]
        """
        results = []
        loaded = 0
        generated = 0
        storage = self.world_storage
        terrain = self.terrain_generator

        chunk_record_map = {}
        missing_coords: list[tuple[int, int]] = []

        for cx, cz in chunk_coords:
            loaded_chunk = storage.load_generated_chunk_with_biomes(cx, cz)
            if loaded_chunk is not None:
                chunk_blocks, chunk_biomes = loaded_chunk
                if chunk_biomes is None:
                    chunk_biomes = self.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
                motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
                world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
                chunk_data = build_chunk_column_from_terrain(chunk_blocks, chunk_biomes)
                chunk_record_map[(cx, cz)] = (
                    cx, cz, motion_blocking, world_surface, chunk_data, True, chunk_blocks, chunk_biomes
                )
            else:
                missing_coords.append((cx, cz))

        if missing_coords:
            if self._use_native_terrain and hasattr(terrain, "generate_chunks_with_metadata"):
                native_results = terrain.generate_chunks_with_metadata(missing_coords)
                for (cx, cz), (chunk_blocks, _, native_biomes) in zip(missing_coords, native_results):
                    chunk_biomes = native_biomes or self.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
                    motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
                    world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
                    chunk_data = build_chunk_column_from_terrain(chunk_blocks, chunk_biomes)
                    chunk_record_map[(cx, cz)] = (
                        cx, cz, motion_blocking, world_surface, chunk_data, False, chunk_blocks, chunk_biomes
                    )
            elif self._use_native_terrain and hasattr(terrain, "generate_chunks_with_heightmaps"):
                native_results = terrain.generate_chunks_with_heightmaps(missing_coords)
                for (cx, cz), (chunk_blocks, _) in zip(missing_coords, native_results):
                    chunk_biomes = self.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
                    motion_blocking = build_heightmap_from_terrain(chunk_blocks, include_water=False)
                    world_surface = build_heightmap_from_terrain(chunk_blocks, include_water=True)
                    chunk_data = build_chunk_column_from_terrain(chunk_blocks, chunk_biomes)
                    chunk_record_map[(cx, cz)] = (
                        cx, cz, motion_blocking, world_surface, chunk_data, False, chunk_blocks, chunk_biomes
                    )
            elif self.should_use_multithreaded_generation():
                executor = self._get_chunk_executor()
                generated_records = executor.map(
                    lambda pos: self._generate_or_load_chunk_result(*pos),
                    missing_coords,
                )
                for record in generated_records:
                    chunk_record_map[(record[0], record[1])] = record
            else:
                for cx, cz in missing_coords:
                    record = self._generate_or_load_chunk_result(cx, cz)
                    chunk_record_map[(cx, cz)] = record

        chunk_records = [chunk_record_map[(cx, cz)] for cx, cz in chunk_coords]

        for cx, cz, motion_blocking, world_surface, chunk_data, was_loaded, chunk_blocks, chunk_biomes in chunk_records:
            results.append((cx, cz, motion_blocking, world_surface, chunk_data, chunk_blocks))
            if was_loaded:
                loaded += 1
                continue
            self.world_storage.save_generated_chunk(cx, cz, chunk_blocks, chunk_biomes)
            generated += 1

        if generated:
            self.world_storage.flush()

        return results, loaded, generated

    def pregenerate_chunks(self, chunk_coords: list[tuple[int, int]]):
        """
        仅为存档预生成区块。

        与 generate_chunk_results 不同，这里不会构建 biome / heightmap / chunk packet，
        只做“检查缓存 -> 生成 -> 落盘”，避免启动阶段浪费大量 CPU 在网络编码上。
        """
        loaded = 0
        generated = 0
        storage = self.world_storage
        terrain = self.terrain_generator

        missing_coords: list[tuple[int, int]] = []
        for cx, cz in chunk_coords:
            if storage.load_generated_chunk(cx, cz) is not None:
                loaded += 1
            else:
                missing_coords.append((cx, cz))

        if not missing_coords:
            return loaded, generated

        generated_chunks: list[tuple[tuple[int, int], list[list[list[int]]], list[list[int]] | None]] = []
        if self._use_native_terrain and hasattr(terrain, "generate_chunks_with_metadata"):
            native_results = terrain.generate_chunks_with_metadata(missing_coords)
            generated_chunks = [
                ((cx, cz), chunk_blocks, native_biomes)
                for (cx, cz), (chunk_blocks, _, native_biomes) in zip(missing_coords, native_results)
            ]
        elif self._use_native_terrain and hasattr(terrain, "generate_chunks_with_heightmaps"):
            native_results = terrain.generate_chunks_with_heightmaps(missing_coords)
            generated_chunks = [
                ((cx, cz), chunk_blocks, None)
                for (cx, cz), (chunk_blocks, _) in zip(missing_coords, native_results)
            ]
        elif self.should_use_multithreaded_generation():
            executor = self._get_chunk_executor()
            generated_chunks = list(executor.map(
                lambda pos: (pos, terrain.generate_chunk(*pos), None),
                missing_coords,
            ))
        else:
            generated_chunks = [
                ((cx, cz), terrain.generate_chunk(cx, cz), None)
                for cx, cz in missing_coords
            ]

        for (cx, cz), chunk_blocks, native_biomes in generated_chunks:
            chunk_biomes = native_biomes or self.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
            storage.save_generated_chunk(cx, cz, chunk_blocks, chunk_biomes)
            generated += 1

        if generated:
            storage.flush()

        return loaded, generated

    async def _pregenerate_spawn_area(self):
        """服务器启动时预生成出生点周围的少量关键区块，确保玩家能进服。
        
        只预生成 join_immediate_radius 范围内的区块（默认 2 = 5x5 = 25 个），
        而不是完整视距范围。其余区块在玩家加入后按需流式加载。
        这样纯 Python 地形生成器也能在几秒内完成。
        """
        spawn_x, _, spawn_z = self.spawn_position
        center_cx = int(spawn_x) >> 4
        center_cz = int(spawn_z) >> 4
        
        # 只预生成小范围，确保玩家加入时有地面可站
        pregen_radius = min(self.join_immediate_radius, 3)  # 最多 7x7 = 49 个
        chunk_coords = [
            (cx, cz)
            for cx in range(center_cx - pregen_radius, center_cx + pregen_radius + 1)
            for cz in range(center_cz - pregen_radius, center_cz + pregen_radius + 1)
        ]

        logger.info(
            f"正在预生成出生点核心区块 {len(chunk_coords)} 个 "
            f"(中心={center_cx},{center_cz} 半径={pregen_radius})..."
        )

        def _generate_spawn_chunks():
            loaded, generated = self.pregenerate_chunks(chunk_coords)
            return loaded, generated

        start = time.time()
        loaded, generated = await asyncio.get_running_loop().run_in_executor(
            None, _generate_spawn_chunks
        )
        logger.info(
            f"出生点核心区块预生成完成: 已缓存 {loaded} 个, 新生成 {generated} 个, "
            f"耗时 {time.time() - start:.1f}s"
        )

    async def stop(self):
        """停止服务器。"""
        logger.info("正在关闭服务器...")
        self.running = False

        self.save_all_player_states()

        # 停止 Watchdog
        if self.watchdog_manager is not None:
            await self.watchdog_manager.stop()
            self.watchdog_manager = None

        # 禁用所有插件
        if self.plugin_manager is not None:
            from plugins.bridge import shutdown_plugin_system
            shutdown_plugin_system(self)
            self.plugin_manager = None

        # 卸载所有 Mod
        if self.mod_manager is not None:
            from mods.bridge import shutdown_mod_system
            shutdown_mod_system(self)
            self.mod_manager = None

        # 停止网络优化器
        if self.network_optimizer is not None:
            await self.network_optimizer.stop()
            self.network_optimizer = None

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

        if self.terrain_generator is not None and hasattr(self.terrain_generator, "shutdown"):
            self.terrain_generator.shutdown()
            self.terrain_generator = None

        self.entity_manager.shutdown()

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
                self.save_player_state(conn)
                # Plugin hook: fire PlayerQuitEvent
                from mods.bridge import hook_player_quit
                hook_player_quit(self, conn)
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
        from protocol.packet_map import get_clientbound_packet

        # 通知其他玩家移除该玩家
        remove_info = build_player_info_remove(conn)
        remove_entity = build_remove_entities([conn.entity_id])

        # Send to each player using their version-specific packet IDs
        for other_conn in self.get_online_players():
            if other_conn == conn:
                continue
            player_remove_pid = get_clientbound_packet(other_conn.protocol_version, "player_remove")
            if player_remove_pid is not None:
                await other_conn.send_packet(player_remove_pid, remove_info)
            remove_entities_pid = get_clientbound_packet(other_conn.protocol_version, "remove_entities")
            if remove_entities_pid is not None:
                await other_conn.send_packet(remove_entities_pid, remove_entity)

    async def _game_loop(self):
        """
        服务器主游戏循环。
        目标: 20 TPS (每 tick 50ms)。
        """
        tick_interval = 0.05  # 50ms per tick
        tick_count = 0
        keepalive_interval = 200  # 每 200 tick (10秒) 发一次心跳
        world_flush_interval = 200  # 每 10 秒尝试落盘一次脏区块
        autosave_interval = 6000  # 每 6000 tick (5分钟) 自动保存

        while self.running:
            tick_start = time.time()
            tick_count += 1

            # 使用 TimeManager 推进时间
            self._time_manager.do_daylight_cycle = self.gamerules.get("doDaylightCycle", True)
            old_weather = self.weather
            old_time = self.world_time
            self._time_manager.tick()
            self.world_time = self._time_manager.time
            self.weather = self._time_manager.weather

            # Plugin hooks: weather/time change
            if self.weather != old_weather:
                from plugins.bridge import hook_weather_change
                hook_weather_change(self, old_weather, self.weather)
            if self.world_time != old_time and tick_count % 200 == 0:
                from plugins.bridge import hook_time_change
                hook_time_change(self, old_time, self.world_time)

            # 更新指标
            self.metrics.tick()

            # 执行调度任务
            await self.scheduler.tick()

            # Plugin/mod tick hook
            from plugins.bridge import hook_server_tick
            hook_server_tick(self)
            if self.mod_manager is not None:
                from mods.bridge import hook_tick
                hook_tick(self)

            # Process active furnace-like containers.
            from world.block_behavior import container_manager
            container_manager.tick_furnaces(self)

            # 发送 KeepAlive 心跳
            if tick_count % keepalive_interval == 0:
                await self._send_keepalive()

            # 自动保存世界数据
            if self.autosave_enabled and tick_count % autosave_interval == 0:
                self.save_all_player_states()
                self.world_storage.flush()

            if self.autosave_enabled and tick_count % world_flush_interval == 0:
                if self.world_storage.has_dirty_regions():
                    self.world_storage.flush()

            # 清理无效连接
            self.connections = [c for c in self.connections if c.alive]

            # 基础玩家生存规则
            await self._tick_players(tick_count)
            self.entity_manager.tick()
            if self.gamerules.get("doMobSpawning", True) and tick_count % 200 == 0:
                self.entity_manager.spawn_natural_mobs()
            await self._tick_entity_interactions()
            if tick_count % 10 == 0:
                await self._tick_entity_sync()

            # Redstone tick (every 2 game ticks = 0.1s)
            if tick_count % 2 == 0:
                await self._tick_redstone()

            # Fluid system tick
            if self.fluid_system is not None:
                await self._tick_fluids(tick_count)

            # Watchdog heartbeat (every second = every 20 ticks)
            if self.watchdog_manager is not None and tick_count % 20 == 0:
                await self.watchdog_manager.send_heartbeat()

            # Network optimizer flush
            if self.network_optimizer is not None:
                await self.network_optimizer.flush_all()

            # 定期输出服务器指标
            if self.metrics.should_report():
                logger.info(self.metrics.report())

            # 计算 tick 用时，补偿延迟
            elapsed = time.time() - tick_start
            sleep_time = max(0, tick_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _tick_redstone(self):
        """Process a redstone tick and broadcast visual changes to players."""
        if self.redstone_engine is None:
            return

        self.redstone_engine.tick()

        # Broadcast block changes from redstone engine
        from handlers.play import _broadcast_block_change
        updates = self.redstone_engine.get_visual_updates()
        for x, y, z, new_state in updates:
            await _broadcast_block_change(self, x, y, z, new_state)

    async def _tick_fluids(self, tick_count: int):
        """Process fluid flow updates and broadcast visual changes."""
        if self.fluid_system is None:
            return

        self.fluid_system.tick()
        updates = getattr(self, "_fluid_updates", [])
        self._fluid_updates = []
        if not updates:
            return
        from handlers.play import _broadcast_block_change
        # Keep only the final state when a position changes repeatedly in one tick.
        final_updates = {}
        for x, y, z, new_state in updates:
            final_updates[(x, y, z)] = new_state
        for (x, y, z), new_state in final_updates.items():
            await _broadcast_block_change(self, x, y, z, new_state)

    async def _send_keepalive(self):
        """向所有在线玩家发送 KeepAlive 数据包。"""
        import struct
        from protocol.packet_map import get_clientbound_packet

        keepalive_id = int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF
        payload = struct.pack('>q', keepalive_id)

        for conn in self.get_online_players():
            if (conn.keepalive_pending
                    and time.monotonic() - conn.keepalive_sent_at > 30.0):
                await conn.disconnect("KeepAlive timeout")
                continue
            conn.keepalive_id = keepalive_id
            conn.keepalive_pending = True
            conn.keepalive_sent_at = time.monotonic()
            # Use version-specific KeepAlive packet ID
            pid = get_clientbound_packet(conn.protocol_version, "keep_alive")
            if pid is not None:
                await conn.send_packet(pid, payload)

    async def _tick_players(self, tick_count: int):
        """处理最基础的玩家伤害与时间同步。"""
        from handlers.play import _damage_player, _send_time_update, _tick_damage_effects

        for conn in self.get_online_players():
            if conn.y < -80:
                await _damage_player(conn, 20.0, "虚空", self)

            await _tick_damage_effects(conn, self, tick_count)

            if tick_count % 40 == 0:
                await _send_time_update(conn, self)

    async def _tick_entity_interactions(self):
        """处理实体与玩家的基础交互：拾取、经验、近战伤害。"""
        from handlers.play import (
            _add_player_experience,
            _damage_player,
            _send_collect_entity,
            send_system_message,
        )

        players = self.get_online_players()
        if not players:
            return

        for entity in list(self.entity_manager.list_entities()):
            if entity.kind in {"orb", "item"}:
                for player in players:
                    if entity.distance_squared_to(player.x, player.y, player.z) > 2.25:
                        continue
                    if entity.kind == "item" and getattr(entity, "pickup_delay", 0) > 0:
                        continue

                    count = int(entity.metadata.get("count", 1))
                    if entity.kind == "orb":
                        self.entity_manager.remove_entity(entity.entity_id)
                        await _send_collect_entity(player, entity.entity_id, player.entity_id, count)
                        await _add_player_experience(player, count)
                    else:
                        item_name = entity.metadata.get("item_name", "minecraft:stone")
                        inventory = getattr(player, "inventory_obj", None)
                        if inventory is None:
                            continue
                        from world.inventory import ItemStack, send_inventory_sync
                        leftover = inventory.add_item(ItemStack(item_name, count))
                        accepted = count - leftover
                        if accepted <= 0:
                            continue
                        player.inventory_state_id += 1
                        await _send_collect_entity(
                            player, entity.entity_id, player.entity_id, accepted
                        )
                        if leftover == 0:
                            self.entity_manager.remove_entity(entity.entity_id)
                        else:
                            entity.count = leftover
                            entity.metadata["count"] = leftover
                        await send_inventory_sync(player)
                        await send_system_message(
                            player, f"[PyMC] 拾取 {item_name} x{accepted}"
                        )
                    break

            if entity.kind == "mob" and entity.metadata.get("category") == "hostile":
                if getattr(entity, "attack_cooldown", 0) > 0:
                    continue
                for player in players:
                    if player.gamemode in {"creative", "spectator"}:
                        continue
                    attack_range = float(getattr(entity, "profile", {}).get("attack_range", 1.7))
                    if entity.distance_squared_to(player.x, player.y, player.z) > attack_range * attack_range:
                        continue
                    entity.attack_cooldown = int(getattr(entity, "profile", {}).get("attack_interval", 20))
                    damage = float(getattr(entity, "profile", {}).get("attack_damage", 2.0))
                    mob_name = entity.metadata.get("mob_type", "生物")
                    await _damage_player(player, damage, mob_name, self)
                    break

    async def _tick_entity_sync(self):
        """向客户端同步基础实体位置与移除。"""
        from handlers.play import (
            _send_entity_teleport,
            _send_experience_orb_spawn,
            _send_generic_entity_spawn,
            _entity_within_tracking_range,
            build_remove_entities,
            broadcast_entity_remove,
        )

        removed_ids = self.entity_manager.consume_removed_ids()
        if removed_ids:
            await broadcast_entity_remove(self, removed_ids)

        entities = self.entity_manager.list_entities()
        live_entities = {
            entity.entity_id: entity
            for entity in entities
            if entity.kind in {"orb", "item", "mob"}
        }

        for conn in self.get_online_players():
            stale_ids = [
                entity_id for entity_id in conn.tracked_entities
                if entity_id not in live_entities
            ]
            if stale_ids:
                conn.tracked_entities.difference_update(stale_ids)
                await conn.send_packet(0x42, build_remove_entities(stale_ids))

            for entity in live_entities.values():
                if not _entity_within_tracking_range(entity, conn, self.view_distance):
                    if entity.entity_id in conn.tracked_entities:
                        conn.tracked_entities.discard(entity.entity_id)
                        await conn.send_packet(0x42, build_remove_entities([entity.entity_id]))
                    continue
                if entity.entity_id not in conn.tracked_entities:
                    if entity.kind == "orb":
                        await _send_experience_orb_spawn(conn, entity)
                    else:
                        await _send_generic_entity_spawn(conn, entity)
                    conn.tracked_entities.add(entity.entity_id)
                    continue
                await _send_entity_teleport(conn, entity)
