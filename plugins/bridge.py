# ============================================================
# PYMC Plugin Glue Layer — Bridge between PluginManager and
# the real MinecraftServer internals
#
# This module wires the plugin system into the server's actual
# event flow: chat, player join/quit, block break/place, etc.
# It also connects the plugin command registry to the server's
# CommandManager framework.
#
# Integration points:
#   1. ServerBridge — replaces the stub PyMCServer with a real
#      proxy that delegates to MinecraftServer
#   2. Hook functions — call from server code to fire plugin events
#   3. Command integration — plugin commands register in CommandManager
# ============================================================

import asyncio
import logging
from typing import Optional, Any, Dict, List, Callable

logger = logging.getLogger("pymc.plugins.bridge")


# ===========================================================
# ServerBridge — Real server proxy for plugins
# ===========================================================

class ServerBridge:
    """
    Proxy object that plugins receive via get_server().
    Delegates every call to the real MinecraftServer instance.
    """

    def __init__(self, server):
        # server is the MinecraftServer instance
        self._server = server

    # --- Chat ---

    def broadcast(self, message: str):
        """Broadcast a chat message to all online players."""
        self._server.broadcast_system_message(message)

    # --- Commands ---

    def dispatch_command(self, command: str) -> bool:
        """
        Execute a server command synchronously (fire-and-forget).
        For async execution, use dispatch_command_async().
        Returns True if the command was queued.
        """
        if self._server.loop is not None:
            asyncio.ensure_future(
                self._dispatch_command_async(command),
                loop=self._server.loop,
            )
            return True
        return False

    async def dispatch_command_async(self, command: str) -> bool:
        """Execute a server command and await the result."""
        return await self._dispatch_command_async(command)

    async def _dispatch_command_async(self, command: str) -> bool:
        from handlers.play import execute_server_command
        return await execute_server_command(self._server, command)

    # --- Player queries ---

    def get_online_players(self) -> List[str]:
        """Get list of online player names."""
        return [c.username for c in self._server.get_online_players()
                if c.username]

    def get_online_player_count(self) -> int:
        """Get the number of online players."""
        return len(self._server.get_online_players())

    def get_player(self, username: str):
        """
        Get a player's connection object by name.
        Returns a PlayerBridge wrapper or None.
        """
        conn = self._server.find_player(username)
        if conn is not None:
            return PlayerBridge(conn)
        return None

    # --- Server state ---

    def get_tps(self) -> float:
        """Get current server TPS. 20.0 = ideal."""
        if hasattr(self._server, 'metrics') and self._server.metrics:
            return self._server.metrics.get_tps()
        return 20.0

    def get_version(self) -> str:
        """Get PYMC server version."""
        return "1.21.1"

    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._server.running

    def get_max_players(self) -> int:
        """Get the max player limit."""
        return self._server.max_players

    def get_motd(self) -> str:
        """Get the server MOTD."""
        return self._server.motd

    # --- World ---

    def get_world_names(self) -> List[str]:
        """Get names of loaded worlds."""
        return [self._server.world_storage.world_name]

    def get_block_at(self, x: int, y: int, z: int) -> Optional[int]:
        """Get block state ID at world coordinates."""
        return self._server.get_block_at(x, y, z)

    def set_block_at(self, x: int, y: int, z: int, block_state: int):
        """Set a block at world coordinates and broadcast the change."""
        from world.editing import set_world_block
        set_world_block(self._server, x, y, z, block_state)

    # --- Plugin interop ---

    def get_plugin(self, plugin_id: str):
        """Get another plugin's main instance (for inter-plugin comms)."""
        pm = self._server.plugin_manager
        if pm is not None:
            return pm.get_plugin_instance(plugin_id)
        return None


# ===========================================================
# PlayerBridge — Safe wrapper around Connection for plugins
# ===========================================================

class PlayerBridge:
    """
    Read-only wrapper around a Connection object.
    Gives plugins safe access to player data without
    exposing the raw connection.
    """

    def __init__(self, conn):
        self._conn = conn

    @property
    def name(self) -> str:
        return self._conn.username or ""

    @property
    def uuid(self):
        return self._conn.uuid

    @property
    def x(self) -> float:
        return self._conn.x

    @property
    def y(self) -> float:
        return self._conn.y

    @property
    def z(self) -> float:
        return self._conn.z

    @property
    def yaw(self) -> float:
        return self._conn.yaw

    @property
    def pitch(self) -> float:
        return self._conn.pitch

    @property
    def gamemode(self) -> int:
        return self._conn.gamemode

    @property
    def health(self) -> float:
        return self._conn.health

    @property
    def food(self) -> int:
        return self._conn.food

    @property
    def on_ground(self) -> bool:
        return self._conn.on_ground

    @property
    def entity_id(self) -> int:
        return self._conn.entity_id

    @property
    def protocol_version(self) -> int:
        return self._conn.protocol_version

    async def send_message(self, text: str):
        """Send a system chat message to this player."""
        from handlers.play.chat import send_system_message
        await send_system_message(self._conn, text)

    def kick(self, reason: str = "Kicked by plugin"):
        """Disconnect this player."""
        self._conn.alive = False


# ===========================================================
# Event Hooks — Call these from server code
# ===========================================================

def hook_player_join(server, conn) -> bool:
    """
    Fire the PlayerJoinEvent. Call after a player successfully
    joins the game. Returns True if the event was NOT cancelled.
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_JOIN,
        {
            "player_name": conn.username or "",
            "player_uuid": str(conn.uuid) if conn.uuid else "",
            "player": PlayerBridge(conn),
        },
        cancellable=False,  # Can't cancel a join after they're in
    )
    return pm.fire_event(event)


def hook_player_quit(server, conn) -> bool:
    """
    Fire the PlayerQuitEvent. Call when a player disconnects.
    Returns True if the event was NOT cancelled.
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_QUIT,
        {
            "player_name": conn.username or "",
            "player_uuid": str(conn.uuid) if conn.uuid else "",
            "player": PlayerBridge(conn),
        },
        cancellable=False,
    )
    return pm.fire_event(event)


def hook_player_chat(server, conn, message: str) -> bool:
    """
    Fire the AsyncPlayerChatEvent BEFORE the message is broadcast.
    Returns True if the message should be sent (NOT cancelled).
    Plugins can cancel the message or modify it.
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_CHAT,
        {
            "player_name": conn.username or "",
            "player_uuid": str(conn.uuid) if conn.uuid else "",
            "message": message,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    result = pm.fire_event(event)
    # If the event was not cancelled, allow the chat
    # Plugins can also modify event.data["message"]
    return result


def hook_player_command(server, conn, command: str) -> bool:
    """
    Fire the PlayerCommandPreprocessEvent BEFORE the command executes.
    Returns True if the command should proceed (NOT cancelled).
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_COMMAND,
        {
            "player_name": conn.username or "",
            "command": command,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_block_break(server, conn, x: int, y: int, z: int,
                     block_state: int) -> bool:
    """
    Fire the BlockBreakEvent BEFORE the block is broken.
    Returns True if the break should proceed (NOT cancelled).
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.BLOCK_BREAK,
        {
            "player_name": conn.username or "",
            "x": x, "y": y, "z": z,
            "block_state": block_state,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_block_place(server, conn, x: int, y: int, z: int,
                     block_state: int) -> bool:
    """
    Fire the BlockPlaceEvent BEFORE the block is placed.
    Returns True if the place should proceed (NOT cancelled).
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.BLOCK_PLACE,
        {
            "player_name": conn.username or "",
            "x": x, "y": y, "z": z,
            "block_state": block_state,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_player_death(server, conn, cause: str = ""):
    """Fire the PlayerDeathEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_DEATH,
        {
            "player_name": conn.username or "",
            "cause": cause,
            "player": PlayerBridge(conn),
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_entity_damage(server, entity_id: int, damage: float,
                       source: str = "") -> bool:
    """
    Fire the EntityDamageEvent. Returns True if damage should
    be applied (NOT cancelled).
    """
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.ENTITY_DAMAGE,
        {
            "entity_id": entity_id,
            "damage": damage,
            "source": source,
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_server_start(server):
    """Fire the ServerStartEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(PluginEvents.SERVER_START, {}, cancellable=False)
    pm.fire_event(event)


def hook_server_stop(server):
    """Fire the ServerStopEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(PluginEvents.SERVER_STOP, {}, cancellable=False)
    pm.fire_event(event)


def hook_player_kick(server, conn, reason: str = ""):
    """Fire the PlayerKickEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_KICK,
        {
            "player_name": conn.username or "",
            "reason": reason,
            "player": PlayerBridge(conn),
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_player_move(server, conn, from_x: float, from_y: float, from_z: float,
                     to_x: float, to_y: float, to_z: float):
    """Fire the PlayerMoveEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_MOVE,
        {
            "player_name": conn.username or "",
            "from_x": from_x, "from_y": from_y, "from_z": from_z,
            "to_x": to_x, "to_y": to_y, "to_z": to_z,
            "player": PlayerBridge(conn),
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_player_teleport(server, conn, from_x: float, from_y: float, from_z: float,
                         to_x: float, to_y: float, to_z: float) -> bool:
    """Fire the PlayerTeleportEvent. Returns True if teleport should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_TELEPORT,
        {
            "player_name": conn.username or "",
            "from_x": from_x, "from_y": from_y, "from_z": from_z,
            "to_x": to_x, "to_y": to_y, "to_z": to_z,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_player_interact(server, conn, x: int, y: int, z: int,
                         action: str = "right_click", hand: str = "main") -> bool:
    """Fire the PlayerInteractEvent. Returns True if interaction should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_INTERACT,
        {
            "player_name": conn.username or "",
            "x": x, "y": y, "z": z,
            "action": action,
            "hand": hand,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_player_respawn(server, conn):
    """Fire the PlayerRespawnEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_RESPAWN,
        {
            "player_name": conn.username or "",
            "player": PlayerBridge(conn),
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_player_gamemode_change(server, conn, old_gamemode: int,
                                new_gamemode: int) -> bool:
    """Fire the PlayerGameModeChangeEvent. Returns True if change should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PLAYER_GAME_MODE,
        {
            "player_name": conn.username or "",
            "old_gamemode": old_gamemode,
            "new_gamemode": new_gamemode,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_entity_spawn(server, entity_id: int, entity_type: str = "",
                      x: float = 0, y: float = 0, z: float = 0) -> bool:
    """Fire the EntitySpawnEvent. Returns True if spawn should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.ENTITY_SPAWN,
        {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "x": x, "y": y, "z": z,
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_entity_death(server, entity_id: int, cause: str = ""):
    """Fire the EntityDeathEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.ENTITY_DEATH,
        {
            "entity_id": entity_id,
            "cause": cause,
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_projectile_hit(server, entity_id: int, x: int, y: int, z: int):
    """Fire the ProjectileHitEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.PROJECTILE_HIT,
        {
            "entity_id": entity_id,
            "x": x, "y": y, "z": z,
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_block_burn(server, x: int, y: int, z: int, block_state: int):
    """Fire the BlockBurnEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.BLOCK_BURN,
        {
            "x": x, "y": y, "z": z,
            "block_state": block_state,
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_block_redstone(server, x: int, y: int, z: int,
                        old_power: int, new_power: int):
    """Fire the BlockRedstoneEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.BLOCK_REDSTONE,
        {
            "x": x, "y": y, "z": z,
            "old_power": old_power,
            "new_power": new_power,
        },
        cancellable=False,
    )
    pm.fire_event(event)


def hook_sign_change(server, conn, x: int, y: int, z: int,
                     lines: list) -> bool:
    """Fire the SignChangeEvent. Returns True if change should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.SIGN_CHANGE,
        {
            "player_name": conn.username or "",
            "x": x, "y": y, "z": z,
            "lines": lines,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_chunk_load(server, cx: int, cz: int):
    """Fire the ChunkLoadEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.CHUNK_LOAD,
        {"chunk_x": cx, "chunk_z": cz},
        cancellable=False,
    )
    pm.fire_event(event)


def hook_chunk_unload(server, cx: int, cz: int):
    """Fire the ChunkUnloadEvent."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.CHUNK_UNLOAD,
        {"chunk_x": cx, "chunk_z": cz},
        cancellable=False,
    )
    pm.fire_event(event)


def hook_weather_change(server, old_weather: str, new_weather: str) -> bool:
    """Fire the WeatherChangeEvent. Returns True if change should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.WEATHER_CHANGE,
        {"old_weather": old_weather, "new_weather": new_weather},
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_time_change(server, old_time: int, new_time: int) -> bool:
    """Fire the TimeChangeEvent. Returns True if change should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.TIME_CHANGE,
        {"old_time": old_time, "new_time": new_time},
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_inventory_click(server, conn, slot: int, item_id: str = "",
                         click_type: str = "left") -> bool:
    """Fire the InventoryClickEvent. Returns True if click should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.INVENTORY_CLICK,
        {
            "player_name": conn.username or "",
            "slot": slot,
            "item_id": item_id,
            "click_type": click_type,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_craft_item(server, conn, result_item: str, recipe_id: str = "") -> bool:
    """Fire the CraftItemEvent. Returns True if craft should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.CRAFT_ITEM,
        {
            "player_name": conn.username or "",
            "result_item": result_item,
            "recipe_id": recipe_id,
            "player": PlayerBridge(conn),
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_fluid_place(server, x: int, y: int, z: int,
                     fluid_type: str = "water") -> bool:
    """Fire the FluidPlaceEvent. Returns True if placement should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.FLUID_PLACE,
        {"x": x, "y": y, "z": z, "fluid_type": fluid_type},
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_fluid_flow(server, from_x: int, from_y: int, from_z: int,
                    to_x: int, to_y: int, to_z: int,
                    fluid_type: str = "water") -> bool:
    """Fire the FluidFlowEvent. Returns True if flow should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.FLUID_FLOW,
        {
            "from_x": from_x, "from_y": from_y, "from_z": from_z,
            "to_x": to_x, "to_y": to_y, "to_z": to_z,
            "fluid_type": fluid_type,
        },
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_gamerule_change(server, rule_name: str, old_value, new_value) -> bool:
    """Fire the GameRuleChangeEvent. Returns True if change should proceed."""
    pm = server.plugin_manager
    if pm is None:
        return True
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(
        PluginEvents.GAMERULE_CHANGE,
        {"rule_name": rule_name, "old_value": old_value, "new_value": new_value},
        cancellable=True,
    )
    return pm.fire_event(event)


def hook_server_tick(server):
    """Fire the ServerTickEvent. Called every game tick."""
    pm = server.plugin_manager
    if pm is None:
        return
    from plugins import PluginEvents, PluginEvent
    event = PluginEvent(PluginEvents.SERVER_TICK, {}, cancellable=False)
    pm.fire_event(event)

    # Also tick the scheduler
    sched = getattr(server, '_plugin_scheduler', None)
    if sched is not None:
        sched.tick()


# ===========================================================
# Command Integration — Wire plugin commands into CommandManager
# ===========================================================

def register_plugin_commands(server):
    """
    Scan all enabled plugins for registered commands and register
    them as Command objects in the server's CommandManager.

    This is called once after all plugins are enabled.
    """
    pm = server.plugin_manager
    cm = server.command_manager
    if pm is None or cm is None:
        return

    from commands.framework import Command, CommandContext
    from commands import SUCCESS, FAILURE

    plugin_commands = pm.get_registered_commands()

    for cmd_name in plugin_commands:
        # Skip if already registered by vanilla
        if cm.get_command(cmd_name) is not None:
            logger.debug(f"Plugin command /{cmd_name} skipped — "
                         f"already registered by vanilla or another plugin")
            continue

        entry = pm._commands.get(cmd_name)
        if entry is None:
            continue

        handler, plugin_id = entry

        # Create a Command object that wraps the plugin's handler
        async def _make_executor(h, pid):
            async def _exec(ctx: CommandContext) -> int:
                try:
                    # Plugin handlers are sync — call them with the arg string
                    args = ctx.remaining_input
                    h(args)
                    return SUCCESS
                except Exception as e:
                    logger.exception(f"Plugin {pid} command error: {e}")
                    return FAILURE
            return _exec

        # We can't use async closure directly in a loop, so bind via default arg
        cmd = Command(
            name=cmd_name,
            description=f"Plugin command ({plugin_id})",
            category="plugin",
        )

        # Bind the handler
        _handler = handler
        _plugin_id = plugin_id

        async def _plugin_executor(ctx: CommandContext,
                                    __h=_handler, __pid=_plugin_id) -> int:
            try:
                args = ctx.remaining_input
                __h(args)
                return SUCCESS
            except Exception as e:
                logger.exception(f"Plugin {__pid} command error: /{ctx.command.name}: {e}")
                return FAILURE

        cmd.execute(_plugin_executor)
        cm.register(cmd)
        logger.info(f"Registered plugin command: /{cmd_name} (from {plugin_id})")


# ===========================================================
# Initialization — Wire everything together
# ===========================================================

def init_plugin_system(server, plugins_dir: str = "plugins") -> 'PluginManager':
    """
    Initialize the full plugin system and wire it into the server.

    Returns the PluginManager instance.

    Call this once during server startup, after CommandManager
    is initialized but before the game loop starts.
    """
    from plugins import PluginManager
    from plugins.scheduler import PluginScheduler

    # Create PluginManager with a real ServerBridge
    bridge = ServerBridge(server)
    pm = PluginManager(plugins_dir=plugins_dir, server=bridge)

    # Store on server
    server.plugin_manager = pm

    # Create and store scheduler
    scheduler = PluginScheduler(server)
    server._plugin_scheduler = scheduler

    # Discover and load plugins
    discovered = pm.discover_plugins(plugins_dir)
    logger.info(f"Discovered {len(discovered)} plugins in {plugins_dir}")

    loaded = pm.load_all()
    logger.info(f"Loaded {loaded} plugins")

    pm.enable_all()
    enabled = pm.plugin_count
    logger.info(f"Enabled {enabled} plugins")

    # Register plugin commands into CommandManager
    register_plugin_commands(server)

    # Best-effort Bukkit/Paper .jar bridge.
    server.java_plugin_bridge = None
    try:
        from plugins.java_plugin import JavaPluginBridge, discover_jar_plugins
        if discover_jar_plugins(plugins_dir):
            java_bridge = JavaPluginBridge(
                plugins_dir,
                on_broadcast=server.broadcast_system_message,
            )
            if java_bridge.start():
                results = java_bridge.load_all()
                enabled_java = [r.get("name") for r in results if r.get("status") == "enabled"]
                if enabled_java:
                    logger.info(f"Java Bukkit/Paper 插件已通过桥接层加载: {enabled_java}")
                server.java_plugin_bridge = java_bridge
    except Exception as e:
        logger.warning(f"初始化 Java 插件桥接层失败: {e}")

    # Fire server start event
    hook_server_start(server)

    return pm


def shutdown_plugin_system(server):
    """
    Shut down the plugin system cleanly.
    Fire ServerStopEvent, disable all plugins, unregister commands.
    """
    pm = server.plugin_manager
    if pm is None:
        return

    # Fire server stop event
    hook_server_stop(server)

    java_bridge = getattr(server, 'java_plugin_bridge', None)
    if java_bridge is not None:
        java_bridge.stop()
        server.java_plugin_bridge = None

    # Disable all plugins
    pm.shutdown_all()

    # Unregister plugin commands from CommandManager
    cm = server.command_manager
    if cm is not None:
        plugin_cmd_names = pm.get_registered_commands()
        for cmd_name in plugin_cmd_names:
            cmd = cm.get_command(cmd_name)
            if cmd is not None and getattr(cmd, 'category', '') == 'plugin':
                cm.unregister(cmd_name)
                logger.debug(f"Unregistered plugin command: /{cmd_name}")

    logger.info("Plugin system shut down")
