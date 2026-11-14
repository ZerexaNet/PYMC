# ============================================================
# PyMC - TCP 网络服务器
# 管理 TCP 监听、连接接入和数据包分发
# ============================================================

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Optional
from config import save_config
from admin.permissions import PermissionManager, UserCache
from admin.web import WebAdminServer
from .connection import Connection, ConnectionState
from handlers.handshake import handle_handshake
from handlers.status import handle_status
from handlers.login import handle_login
from handlers.configuration import handle_configuration
from handlers.play import handle_play
from world.storage import WorldStorage
from world.level_data import LevelData, SessionLock, SessionLockError
from world.terrain import TerrainGenerator
from world.terrain_native import NativeTerrainGenerator, _find_native_binary
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
mc_logger = logging.getLogger("minecraft.server")

MINECRAFT_VERSION = "1.21.1"


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
        self.host = str(config.get("server-ip", "") or "")
        self.port = config.get("server-port", 25565)
        self.motd = config.get("motd", "A Minecraft Server")
        self.max_players = config.get("max-players", 20)
        self.online_mode = config.get("online-mode", False)
        self.compression_threshold = config.get("network-compression-threshold", 256)
        self.view_distance = max(2, min(32, int(config.get("view-distance", 10))))
        self.simulation_distance = max(
            2, min(self.view_distance, int(config.get("simulation-distance", 10))))
        self.autosave_enabled = True
        self.chunk_generation_multithreading = config.get(
            "chunk-generation-multithreading", False
        )
        configured_workers = int(config.get("chunk-generation-workers", 0) or 0)
        self.chunk_generation_workers = (
            configured_workers if configured_workers > 0 else max(2, os.cpu_count() or 2)
        )
        self.join_immediate_radius = max(0, int(config.get("join-immediate-radius", 2)))

        # 世界存储: <universe>/<level-name>/
        world_name = str(config.get("level-name", "world") or "world")
        universe = str(config.get("universe", "") or "")
        self.level_name = world_name
        world_path = os.path.join(universe, world_name) if universe else world_name
        self.world_storage = WorldStorage(world_path)
        self.session_lock = SessionLock(self.world_storage.world_dir)

        # level.dat: 出生点、世界时间、天气、游戏规则、种子
        self.level_data = LevelData.load(self.world_storage.world_dir)
        self.level_data.level_name = world_name
        self.seed = self._resolve_seed()
        self.level_data.seed = self.seed

        self._time_manager = TimeManager(initial_time=0)
        self._gamerule_manager = GameruleManager(self.level_data.gamerules or None)
        if self.level_data.existed:
            self._time_manager.apply_level_data(self.level_data)
            if self.level_data.difficulty:
                config["difficulty"] = self.level_data.difficulty
        self.gamerules = self._gamerule_manager

        if self.level_data.spawn is not None:
            self.spawn_position = tuple(int(v) for v in self.level_data.spawn)
            self._spawn_resolved = True
        else:
            # 旧版本 PyMC 把出生点写在 server.properties 里
            self.spawn_position = (
                int(config.get("level-spawn-x", 0)),
                int(config.get("level-spawn-y", 100)),
                int(config.get("level-spawn-z", 0)),
            )
            self._spawn_resolved = False

        # 权限 / OP / 封禁 / 白名单 (原版 JSON 文件) 与玩家名缓存
        permissions_file = config.get("permissions-file", "permissions.json")
        base_dir = os.path.dirname(permissions_file)
        self.usercache = UserCache(os.path.join(base_dir, "usercache.json"))
        self.permissions = PermissionManager(
            permissions_file,
            default_op_level=int(config.get("op-permission-level", 4)),
            usercache=self.usercache,
        )
        whitelist = self.permissions.data["whitelist"]
        if whitelist.get("enabled") and not config.get("white-list", False):
            config["white-list"] = True      # 迁移旧 permissions.json 的开关
            save_config(config, config_path)
        whitelist["enabled"] = bool(config.get("white-list", False))
        self.permissions.on_whitelist_toggle = self._on_whitelist_toggle

        self.web_admin: WebAdminServer | None = None
        self.rcon = None
        self.loop: asyncio.AbstractEventLoop | None = None

        # 在线玩家列表
        self.connections: list[Connection] = []
        self.next_entity_id = 1

        # 服务器状态
        self.running = False
        self.accepting_players = False
        self.start_time = 0
        self._stopped = False
        self._stop_event: asyncio.Event | None = None
        self._ready_event = asyncio.Event()
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

    # ------------------------------------------------------------------
    # 世界时间 / 天气 (委托给 TimeManager, 保证 /time /weather 修改持久生效)
    # ------------------------------------------------------------------

    @property
    def world_time(self) -> int:
        return self._time_manager.time

    @world_time.setter
    def world_time(self, value: int):
        self._time_manager.set_time(int(value))

    @property
    def weather(self) -> str:
        return self._time_manager.weather

    @weather.setter
    def weather(self, value: str):
        self._time_manager.weather = value

    def _resolve_seed(self) -> int:
        """
        世界种子的来源优先级 (与原版一致: 已有世界以 level.dat 为准):
          1. level.dat 中记录的种子
          2. server.properties 的 level-seed
          3. 旧存档 (有区域文件但没有 level.dat): 沿用旧行为 0
          4. 全新世界: 随机种子
        """
        if self.level_data.existed:
            return int(self.level_data.seed)
        configured = str(self.config.get("level-seed", "") or "").strip()
        if configured:
            return parse_vanilla_seed(configured)
        region_dir = self.world_storage.region_dir
        try:
            has_regions = any(region_dir.iterdir())
        except OSError:
            has_regions = False
        if has_regions:
            return 0
        import random
        return random.SystemRandom().randint(-(1 << 63), (1 << 63) - 1)

    def _on_whitelist_toggle(self, enabled: bool):
        self.config["white-list"] = bool(enabled)
        save_config(self.config, self.config_path)

    def save_level_data(self):
        """把世界元数据写入 level.dat。"""
        level = self.level_data
        level.level_name = self.level_name
        level.seed = self.seed
        level.spawn = tuple(int(v) for v in self.spawn_position)
        level.difficulty = str(self.config.get("difficulty", "easy")).lower()
        level.gamemode = str(self.config.get("gamemode", "survival")).lower()
        level.hardcore = bool(self.config.get("hardcore", False))
        level.gamerules = {
            name: (str(value).lower() if isinstance(value, bool) else str(value))
            for name, value in self.gamerules.all_rules().items()
        }
        self._time_manager.write_level_data(level)
        try:
            level.save(self.world_storage.world_dir)
        except OSError as e:
            mc_logger.error(f"Failed to save level.dat: {e}")

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

    def broadcast_system_message(self, text, exclude: Connection = None,
                                 log: bool = False):
        """向所有在线玩家广播系统聊天消息 (字符串或文本组件)。"""
        if log:
            from protocol.text import plain_text
            logging.getLogger("minecraft.server").info(plain_text(text))
        for conn in self.get_online_players():
            if conn != exclude and conn.version_handler is not None:
                asyncio.ensure_future(conn.version_handler.send_system_chat(conn, text))

    async def queue_or_send(self, conn: Connection, packet_id: int, payload: bytes):
        """
        优先经网络优化器批量发送 (合并为单次 TCP write),
        优化器未启用时直接发送。用于高频广播路径 (如实体位置同步)。
        """
        optimizer = self.network_optimizer
        if optimizer is not None and optimizer.queue_packet(conn, packet_id, payload):
            return
        await conn.send_packet(packet_id, payload)

    async def set_weather(self, weather: str, duration: int = 0):
        """
        设置天气并立即同步到所有客户端。

        Args:
            weather: "clear" | "rain" | "thunder"
            duration: 持续 tick 数 (0 = 无限, 直到天气循环或手动变更)
        """
        old_weather = self.weather
        self._time_manager.set_weather(weather, duration)
        self.weather = self._time_manager.weather
        if self.weather == old_weather:
            return
        from handlers.play.weather import broadcast_weather_change
        await broadcast_weather_change(self, old_weather, self.weather)
        from plugins.bridge import hook_weather_change
        hook_weather_change(self, old_weather, self.weather)

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
            "flying": bool(getattr(conn, "flying", False)),
            "selected_slot": int(getattr(conn, "selected_hotbar_slot", 0)),
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
        """
        启动服务器并一直运行到 stop() 被调用。

        控制台输出顺序与原版专用服务端一致:
        Default game type -> Starting Minecraft server on -> Preparing level
        -> Preparing spawn area -> Done (N s)! For help, type "help"
        """
        if self.online_mode:
            from network import encryption
            if not encryption.available():
                raise RuntimeError(
                    "online-mode=true requires the 'cryptography' package "
                    "(pip install cryptography), or set online-mode=false"
                )
        self.running = True
        self._stopped = False
        self.start_time = time.time()
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()

        gamemode = str(self.config.get("gamemode", "survival")).upper()
        mc_logger.info(f"Default game type: {gamemode}")

        if self.online_mode:
            from network import encryption
            mc_logger.info("Generating keypair")
            self.keypair = encryption.ServerKeyPair()

        # --- 绑定端口 (与原版一样在加载世界之前) ---
        bind_host = self.host or None
        shown_host = self.host or "*"
        mc_logger.info(f"Starting Minecraft server on {shown_host}:{self.port}")
        try:
            self._server = await asyncio.start_server(
                self._handle_client, bind_host, self.port
            )
        except OSError as e:
            mc_logger.warning("**** FAILED TO BIND TO PORT!")
            mc_logger.warning(f"The exception was: {e}")
            mc_logger.warning("Perhaps a server is already running on that port?")
            self.running = False
            raise RuntimeError(f"Failed to bind to port {self.port}") from e

        if not self.online_mode:
            mc_logger.warning("**** SERVER IS RUNNING IN OFFLINE/INSECURE MODE!")
            mc_logger.warning("The server will make no attempt to authenticate usernames. Beware.")
            mc_logger.warning(
                "While this makes the game possible to play without internet access, "
                "it also opens up the ability for hackers to connect with any username they choose.")
            mc_logger.warning('To change this, set "online-mode" to "true" in the server.properties file.')

        # --- 加载世界 ---
        mc_logger.info(f'Preparing level "{self.level_name}"')
        try:
            self.session_lock.acquire()
        except SessionLockError as e:
            self.running = False
            self._server.close()
            raise RuntimeError(str(e)) from e

        # 初始化世界存储 (Anvil -> Linear 自动转换)
        self.world_storage.initialize()
        container_manager.load(str(self.world_storage.world_dir))
        self._initialize_terrain_generator()
        await self._pregenerate_spawn_area()
        self.save_level_data()

        # 初始化红石引擎
        if self.config.get("redstone-enabled", True):
            self.redstone_engine = RedstoneEngine(self)

        # 初始化流体系统
        if self.config.get("fluid-flow-enabled", True):
            self.fluid_system = FluidSystem(self)

        # 初始化网络优化器
        self.network_optimizer = PlayerNetworkOptimizer(self)
        await self.network_optimizer.start()

        # 初始化命令框架 (如果 main.py 没有提前初始化)
        if self.command_manager is None:
            from commands import CommandManager, register_all_vanilla_commands
            self.command_manager = CommandManager(self)
            register_all_vanilla_commands(self.command_manager)

        # Mod 管理器集成 (如果 main.py 没有提前初始化)
        if self.mod_manager is None:
            from mods.bridge import init_mod_system
            mods_dir = self.config.get("mods-directory", "mods")
            init_mod_system(self, mods_dir)

        # 插件管理器集成 (如果 main.py 没有提前初始化)
        if self.plugin_manager is None:
            from plugins.bridge import init_plugin_system
            plugins_dir = self.config.get("plugins-directory", "plugins")
            init_plugin_system(self, plugins_dir)

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

        if self.config.get("enable-rcon", False):
            from network.rcon import RconServer
            password = str(self.config.get("rcon.password", "") or "")
            if not password:
                mc_logger.warning("No rcon password set in server.properties, rcon disabled!")
            else:
                self.rcon = RconServer(self, self.host or "0.0.0.0",
                                       int(self.config.get("rcon.port", 25575)), password)
                await self.rcon.start()

        logger.debug(
            f"协议 767 (原生) | 兼容协议 {self.config.get('min-protocol-version', 47)}-"
            f"{self.config.get('max-protocol-version', 770)} | 压缩阈值 "
            f"{self.compression_threshold} | 地形引擎 "
            f"{'C++ 原生' if self._use_native_terrain else 'Python'}"
        )

        self.accepting_players = True
        self._ready_event.set()
        startup_time = time.time() - self.start_time
        mc_logger.info(f'Done ({startup_time:.3f}s)! For help, type "help"')

        from mods.bridge import hook_server_start
        try:
            hook_server_start(self)
        except Exception as e:
            logger.debug(f"hook_server_start failed: {e}")

        async with self._server:
            await self._stop_event.wait()

    async def wait_until_ready(self):
        """等待服务器完成启动 (控制台命令在此之前排队)。"""
        await self._ready_event.wait()

    def request_stop(self):
        """请求停止服务器 (/stop、Ctrl+C、SIGTERM、RCON 均走这里)。"""
        if self._stop_event is not None and not self._stop_event.is_set():
            mc_logger.info("Stopping the server")
            self._stop_event.set()
        self.accepting_players = False

    def _initialize_terrain_generator(self):
        """初始化地形生成器，并计算出生点高度。"""
        if self.terrain_generator is not None:
            return

        seed = int(getattr(self, "seed", parse_vanilla_seed(self.config.get("level-seed", 0))))

        # 与 world.terrain_native 共用跨平台查找逻辑，避免选中仓库中
        # 已提交的其它平台二进制（例如 macOS 上误选 Linux ELF）。
        explicit_native_path = _find_native_binary()

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
            logger.debug(f"使用 C++ 原生地形生成器 (种子: {seed})")
        elif use_vanilla:
            try:
                self.terrain_generator = VanillaTerrainGenerator(seed)
                self._use_native_terrain = False
                logger.info("Native terrain generator unavailable, using the (slow) Python generator")
            except Exception as e:
                logger.warning(f"Vanilla 地形生成器初始化失败: {e}，回退到基础生成器")
                self.terrain_generator = TerrainGenerator(seed)
                self._use_native_terrain = False
                logger.debug(f"使用纯 Python 地形生成器 (种子: {seed})")
        else:
            self.terrain_generator = TerrainGenerator(seed)
            self._use_native_terrain = False
            logger.debug(f"使用纯 Python 地形生成器 (种子: {seed})")

        if getattr(self, "_spawn_resolved", False):
            return  # 出生点来自 level.dat, 不重新计算
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
        self.config["gamemode"] = self.config.get("gamemode", "survival")
        self.config["chunk-generation-multithreading"] = self.chunk_generation_multithreading
        self.config["chunk-generation-workers"] = self.config.get("chunk-generation-workers", 0)
        self.config["join-immediate-radius"] = self.join_immediate_radius
        self.config["level-name"] = self.config.get("level-name", "world")
        save_config(self.config, self.config_path)
        self.save_level_data()   # 出生点保存在 level.dat

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
        """
        服务器启动时准备出生点周围的区块, 并解析出安全的世界出生点。

        只准备 join_immediate_radius 范围内的区块 (默认 5x5), 其余区块在玩家
        加入后按需流式加载。进度按原版格式输出 (Preparing spawn area: N%)。
        """
        mc_logger.info("Preparing start region for dimension minecraft:overworld")
        spawn_x, _, spawn_z = self.spawn_position
        center_cx = int(spawn_x) >> 4
        center_cz = int(spawn_z) >> 4

        pregen_radius = min(self.join_immediate_radius, 3)  # 最多 7x7 = 49 个
        chunk_coords = [
            (cx, cz)
            for cx in range(center_cx - pregen_radius, center_cx + pregen_radius + 1)
            for cz in range(center_cz - pregen_radius, center_cz + pregen_radius + 1)
        ]
        total = len(chunk_coords)
        progress = {"done": 0}

        def _generate_spawn_chunks():
            # 分小批生成, 以便汇报进度
            batch = max(1, total // 8)
            for index in range(0, total, batch):
                if not self.running:
                    break
                self.pregenerate_chunks(chunk_coords[index:index + batch])
                progress["done"] = min(total, index + batch)

        start = time.time()
        future = asyncio.get_running_loop().run_in_executor(None, _generate_spawn_chunks)
        worker_log = logging.getLogger("minecraft.worldgen")
        last_report = 0.0
        while not future.done():
            await asyncio.wait([future], timeout=0.25)
            now = time.time()
            if not future.done() and now - last_report >= 0.5:
                last_report = now
                worker_log.info(f"Preparing spawn area: {progress['done'] * 100 // total}%")
        await future
        mc_logger.info(f"Time elapsed: {int((time.time() - start) * 1000)} ms")

        if not getattr(self, "_spawn_resolved", False):
            # 首次创建世界: 在出生点附近寻找安全的落脚点并写入 level.dat
            from handlers.play.spawn import _resolve_spawn_location
            try:
                resolved = await asyncio.get_running_loop().run_in_executor(
                    None, _resolve_spawn_location, self, int(spawn_x), int(spawn_z))
                self.spawn_position = tuple(int(v) for v in resolved)
            except Exception as e:
                logger.warning(f"无法解析安全出生点, 使用地表高度: {e}")
            self._spawn_resolved = True

    async def stop(self):
        """停止服务器: 踢出玩家、保存玩家与世界、释放资源 (可重复调用)。"""
        if self._stopped:
            return
        self._stopped = True
        was_running = self.running
        self.running = False
        self.accepting_players = False
        self._ready_event.set()   # 释放仍在等待启动完成的控制台
        if self._stop_event is not None:
            self._stop_event.set()
        if not was_running:
            return

        mc_logger.info("Stopping server")

        from mods.bridge import hook_server_stop
        try:
            hook_server_stop(self)
        except Exception as e:
            logger.debug(f"hook_server_stop failed: {e}")

        if self.rcon is not None:
            await self.rcon.stop()
            self.rcon = None

        # 停止 TCP 监听, 不再接受新连接
        if self._server:
            self._server.close()

        mc_logger.info("Saving players")
        from protocol.text import translate
        for conn in list(self.connections):
            if conn.state == ConnectionState.PLAY and conn.username:
                self.save_player_state(conn)
            await conn.disconnect(translate("multiplayer.disconnect.server_shutdown"), log=False)
        # 让各连接的收尾逻辑 (离开消息等) 先跑完
        await asyncio.sleep(0)
        self.connections.clear()

        # 停止游戏循环
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except (asyncio.CancelledError, Exception):
                pass
            self._tick_task = None

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
        mc_logger.info("Saving worlds")
        mc_logger.info(
            f"Saving chunks for level 'ServerLevel[{self.level_name}]'/minecraft:overworld")
        container_manager.save(str(self.world_storage.world_dir))
        self.save_level_data()
        self.world_storage.close()
        mc_logger.info(f"ThreadedAnvilChunkStorage ({self.level_name}): All chunks are saved")

        if self.web_admin:
            self.web_admin.stop()
            self.web_admin = None

        if self._chunk_executor:
            self._chunk_executor.shutdown(wait=False, cancel_futures=True)
            self._chunk_executor = None

        if self.terrain_generator is not None and hasattr(self.terrain_generator, "shutdown"):
            self.terrain_generator.shutdown()
            self.terrain_generator = None

        self.entity_manager.shutdown()
        self.session_lock.release()

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
                except (ConnectionError, OSError):
                    break
                except ValueError as e:
                    logger.debug(f"数据包读取错误 [{conn.address}]: {e}")
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
                                 f"状态={conn.state.name} ID=0x{packet_id:02X}: {e}",
                                 exc_info=True)
                    await conn.disconnect({"translate": "multiplayer.disconnect.generic"})
                    break
        finally:
            # 清理连接
            conn.alive = False
            if conn in self.connections:
                self.connections.remove(conn)

            # 已进入游戏的玩家: 保存、广播离开消息、通知其他客户端
            if conn.username and conn.state == ConnectionState.PLAY:
                reason = conn.disconnect_reason or "Disconnected"
                mc_logger.info(f"{conn.username} lost connection: {reason}")
                if conn.joined:
                    conn.joined = False
                    self.save_player_state(conn)
                    from mods.bridge import hook_player_quit
                    hook_player_quit(self, conn)
                    from protocol.text import translate, player_name
                    self.broadcast_system_message(
                        translate("multiplayer.player.left", player_name(conn), color="yellow"),
                        exclude=conn, log=True,
                    )
                    await self._handle_player_leave(conn)
            elif conn.username and conn.state in (ConnectionState.LOGIN,
                                                  ConnectionState.CONFIGURATION):
                reason = conn.disconnect_reason or "Disconnected"
                logging.getLogger("minecraft.auth").debug(
                    f"{conn.username} ({conn.address}) lost connection: {reason}")

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
            other_conn.tracked_players.discard(conn.entity_id)
            player_remove_pid = get_clientbound_packet(other_conn.protocol_version, "player_remove")
            if player_remove_pid is not None:
                await other_conn.send_packet(player_remove_pid, remove_info)
            remove_entities_pid = get_clientbound_packet(other_conn.protocol_version, "remove_entities")
            if remove_entities_pid is not None:
                await other_conn.send_packet(remove_entities_pid, remove_entity)

    async def _game_loop(self):
        """
        服务器主游戏循环。
        目标: 20 TPS (每 tick 50ms)。落后过多时与原版一样输出
        "Can't keep up!" 警告并跳过积压的 tick。
        """
        tick_interval = 0.05  # 50ms per tick
        tick_count = 0
        keepalive_interval = 300  # 每 300 tick (15秒) 发一次心跳 (与原版一致)
        world_flush_interval = 200  # 每 10 秒尝试落盘一次脏区块
        autosave_interval = 6000  # 每 6000 tick (5分钟) 自动保存
        next_tick = time.monotonic()
        last_overload_warning = 0.0

        while self.running:
            tick_count += 1
            try:
                await self._run_tick(tick_count, keepalive_interval,
                                     world_flush_interval, autosave_interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Exception in server tick loop: {e}", exc_info=True)

            # 固定步长调度: 落后时追赶, 落后超过 2 秒则放弃积压的 tick
            next_tick += tick_interval
            now = time.monotonic()
            behind = now - next_tick
            if behind > 2.0:
                if now - last_overload_warning >= 15.0:
                    last_overload_warning = now
                    mc_logger.warning(
                        f"Can't keep up! Is the server overloaded? Running "
                        f"{int(behind * 1000)}ms or {int(behind / tick_interval)} ticks behind")
                next_tick = now
            await asyncio.sleep(max(0.0, next_tick - now))

    async def _run_tick(self, tick_count: int, keepalive_interval: int,
                        world_flush_interval: int, autosave_interval: int):
        """执行一个游戏刻。"""
        # 使用 TimeManager 推进时间
        self._time_manager.do_daylight_cycle = self.gamerules.get("doDaylightCycle", True)
        self._time_manager.do_weather_cycle = self.gamerules.get("doWeatherCycle", True)
        old_weather = self.weather
        old_time = self.world_time
        self._time_manager.tick()

        # Plugin hooks + client sync: weather/time change
        if self.weather != old_weather:
            from handlers.play.weather import broadcast_weather_change
            await broadcast_weather_change(self, old_weather, self.weather)
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

        # 自动保存世界数据 (原版同样静默进行)
        if self.autosave_enabled and tick_count % autosave_interval == 0:
            self.save_all_player_states()
            self.world_storage.flush()
            container_manager.save(str(self.world_storage.world_dir))
            self.save_level_data()

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

        # 雷暴落雷 (每 5 秒一次判定)
        if tick_count % 100 == 0:
            await self._tick_lightning()

        # Fluid system tick
        if self.fluid_system is not None:
            await self._tick_fluids(tick_count)

        # Watchdog heartbeat (every second = every 20 ticks)
        if self.watchdog_manager is not None and tick_count % 20 == 0:
            await self.watchdog_manager.send_heartbeat()

        # Network optimizer flush
        if self.network_optimizer is not None:
            await self.network_optimizer.flush_all()

        # Tab 列表延迟 (每 30 秒刷新一次)
        if tick_count % 600 == 0:
            await self._broadcast_latency()

        # 定期输出服务器指标 (仅调试)
        if self.metrics.should_report():
            report = self.metrics.report()
            logger.debug(report)

    async def _broadcast_latency(self):
        """Player Info Update (Update Latency): 刷新 Tab 列表里的信号格。"""
        from handlers.play.chat import build_player_info_update, INFO_LATENCY
        from protocol.packet_map import get_clientbound_packet
        players = self.get_online_players()
        for player in players:
            info = build_player_info_update(player, INFO_LATENCY)
            for other in players:
                if other.protocol_version < 761:
                    continue
                pid = get_clientbound_packet(other.protocol_version, "player_info")
                if pid is not None:
                    await other.send_packet(pid, info)

    async def _tick_lightning(self):
        """雷暴天气时在随机玩家附近落雷, 伤害落点附近的生物和玩家。"""
        if self.weather != "thunder":
            return
        players = self.get_online_players()
        if not players:
            return

        import random
        target_player = random.choice(players)
        lx = target_player.x + random.uniform(-24, 24)
        lz = target_player.z + random.uniform(-24, 24)
        ly = target_player.y

        bolt = self.entity_manager.create_lightning(lx, ly, lz)
        from handlers.play import broadcast_entity_spawn
        await broadcast_entity_spawn(self, bolt)
        logger.debug(
            f"闪电击中 ({lx:.1f}, {ly:.1f}, {lz:.1f}) "
            f"附近玩家 {target_player.username}"
        )

        # 伤害落点 3 格内的玩家
        from handlers.play import _damage_player
        for player in players:
            if player.gamemode in {"creative", "spectator"}:
                continue
            if bolt.distance_squared_to(player.x, player.y, player.z) <= 9.0:
                await _damage_player(player, 5.0, "闪电", self)

        # 伤害落点 3 格内的生物
        from handlers.play.combat import damage_mob
        for entity in self.entity_manager.list_entities():
            if entity.kind == "mob" and entity.entity_id != bolt.entity_id:
                if bolt.distance_squared_to(entity.x, entity.y, entity.z) <= 9.0:
                    damage_mob(self, entity, 5.0)

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

        # Process effects that require async work (note sounds, explosions,
        # item-drop broadcasts).
        for kind, payload in self.redstone_engine.drain_pending_effects():
            try:
                if kind == "note":
                    from world.block_behavior import NoteBlockBehavior
                    await NoteBlockBehavior._play_note(
                        self,
                        payload["x"], payload["y"], payload["z"],
                        payload.get("note", 0),
                    )
                elif kind == "explosion":
                    from world.block_behavior import TNTBehavior
                    await TNTBehavior._create_explosion(
                        self, payload["x"], payload["y"], payload["z"]
                    )
                elif kind == "entity_spawn":
                    entity = self.entity_manager.get_entity(payload.get("entity_id"))
                    if entity is not None:
                        from handlers.play.entities import broadcast_entity_spawn
                        await broadcast_entity_spawn(self, entity)
            except Exception as e:
                logger.warning(f"红石效果处理失败 ({kind}): {e}")

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
                await conn.disconnect({"translate": "disconnect.timeout"})
                continue
            conn.keepalive_id = keepalive_id
            conn.keepalive_pending = True
            conn.keepalive_sent_at = time.monotonic()
            # Use version-specific KeepAlive packet ID
            pid = get_clientbound_packet(conn.protocol_version, "keep_alive")
            if pid is not None:
                await conn.send_packet(pid, payload)

    async def _tick_players(self, tick_count: int):
        """处理最基础的玩家伤害、挂机超时与时间同步。"""
        from handlers.play import _damage_player, _send_time_update, _tick_damage_effects

        idle_minutes = int(self.config.get("player-idle-timeout", 0) or 0)
        now = time.monotonic()

        for conn in self.get_online_players():
            if not conn.joined:
                continue
            if getattr(conn, "_dead", False):
                continue
            if conn.y < -128:
                await _damage_player(conn, 4.0, "虚空", self)

            await _tick_damage_effects(conn, self, tick_count)

            if tick_count % 20 == 0:
                await _send_time_update(conn, self)

            if (idle_minutes > 0 and tick_count % 20 == 0 and conn.last_active
                    and now - conn.last_active > idle_minutes * 60
                    and not self.permissions.is_op(conn.username)):
                await conn.disconnect({"translate": "multiplayer.disconnect.idling"})

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
                    break

            if entity.kind == "mob" and entity.metadata.get("category") == "hostile":
                if getattr(entity, "attack_cooldown", 0) > 0:
                    continue
                profile = getattr(entity, "profile", {})
                is_ranged = bool(profile.get("ranged", False))
                for player in players:
                    if player.gamemode in {"creative", "spectator"}:
                        continue
                    attack_range = float(profile.get("attack_range", 1.7))
                    if entity.distance_squared_to(player.x, player.y, player.z) > attack_range * attack_range:
                        continue
                    entity.attack_cooldown = int(profile.get("attack_interval", 20))
                    damage = float(profile.get("attack_damage", 2.0))
                    mob_name = entity.metadata.get("mob_type", "生物")
                    reason = f"{mob_name}的箭" if is_ranged else mob_name
                    await _damage_player(player, damage, reason, self)
                    break

    async def _tick_entity_sync(self):
        """向客户端同步基础实体位置与移除。"""
        from handlers.play import (
            _send_entity_remove,
            _send_experience_orb_spawn,
            _send_generic_entity_spawn,
            _entity_within_tracking_range,
            broadcast_entity_remove,
        )

        removed_ids = self.entity_manager.consume_removed_ids()
        if removed_ids:
            await broadcast_entity_remove(self, removed_ids)

        entities = self.entity_manager.list_entities()
        live_entities = {
            entity.entity_id: entity
            for entity in entities
            if entity.kind in {"orb", "item", "mob", "lightning_bolt"}
        }

        for conn in self.get_online_players():
            stale_ids = [
                entity_id for entity_id in conn.tracked_entities
                if entity_id not in live_entities
            ]
            if stale_ids:
                conn.tracked_entities.difference_update(stale_ids)
                await _send_entity_remove(conn, stale_ids)

            for entity in live_entities.values():
                if not _entity_within_tracking_range(entity, conn, self.view_distance):
                    if entity.entity_id in conn.tracked_entities:
                        conn.tracked_entities.discard(entity.entity_id)
                        await _send_entity_remove(conn, [entity.entity_id])
                    continue
                if entity.entity_id not in conn.tracked_entities:
                    if entity.kind == "orb":
                        await _send_experience_orb_spawn(conn, entity)
                    else:
                        await _send_generic_entity_spawn(conn, entity)
                    conn.tracked_entities.add(entity.entity_id)
                    continue
                # 高频传送包走批量发送, 合并为单次 TCP write
                from handlers.play.entities import build_entity_teleport_payload
                from protocol.packet_map import get_clientbound_packet
                teleport_pid = get_clientbound_packet(
                    conn.protocol_version, "entity_teleport")
                if teleport_pid is not None:
                    await self.queue_or_send(
                        conn, teleport_pid, build_entity_teleport_payload(entity))
