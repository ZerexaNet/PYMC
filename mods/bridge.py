# ============================================================
# PYMC Mod System Glue Layer — Bridge between ModManager and
# the MinecraftServer internals
#
# This module wires the mod system into the server's actual
# event flow, mirroring the plugin bridge pattern but using
# the mod system's ModEvent / ModEvents types.
#
# Every hook function fires to BOTH the ModManager AND the
# PluginManager so that mods and plugins always receive the
# same server events.
#
# Integration points:
#   1. ModServerBridge — proxy that mods use to talk to the server
#   2. Hook functions   — call from server code to fire mod events
#   3. init_mod_system / shutdown_mod_system — lifecycle helpers
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from mods import ModEvent, ModEvents, ModManager, PyMCMod

logger = logging.getLogger("pymc.mods.bridge")


# ===========================================================
# ModServerBridge — Real server proxy for mods
# ===========================================================

class ModServerBridge:
    """
    Proxy object that mods receive through their manager.
    Delegates every call to the real MinecraftServer instance.

    Similar to plugins.bridge.ServerBridge but exposes the
    mod-specific registration API (register_block, get_mod, etc.).
    """

    def __init__(self, server):
        # server is the MinecraftServer instance
        self._server = server

    # --- Chat ---

    def broadcast(self, message: str):
        """Broadcast a system message to all online players."""
        self._server.broadcast_system_message(message)

    # --- Commands ---

    def dispatch_command(self, command: str) -> bool:
        """
        Execute a server command asynchronously (fire-and-forget).
        Returns True if the command was successfully queued.
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
        """Get a list of online player names."""
        return [c.username for c in self._server.get_online_players()
                if c.username]

    # --- Server state ---

    def get_tps(self) -> float:
        """Get current server TPS. 20.0 is ideal."""
        if hasattr(self._server, 'metrics') and self._server.metrics:
            return self._server.metrics.get_tps()
        return 20.0

    def get_version(self) -> str:
        """Get the PYMC protocol version string."""
        return "1.21.1"

    def is_running(self) -> bool:
        """Check if the server is currently running."""
        return self._server.running

    # --- World ---

    def get_block_at(self, x: int, y: int, z: int) -> Optional[int]:
        """Get block state ID at the given world coordinates."""
        return self._server.get_block_at(x, y, z)

    def set_block_at(self, x: int, y: int, z: int, block_state: int):
        """Set a block at world coordinates and broadcast the change."""
        from world.editing import set_world_block
        set_world_block(self._server, x, y, z, block_state)

    # --- Mod-specific registration ---

    def register_block(self, block_id: str, properties: Optional[Dict] = None):
        """
        Register a custom block in the server's block registry.
        Falls back to the ModManager's internal registry if the
        server block registry is not yet available.
        """
        # Try the server's block registry when available
        if hasattr(self._server, 'block_registry') and self._server.block_registry is not None:
            self._server.block_registry.register(block_id, properties or {})
            logger.debug(f"Registered block in server registry: {block_id}")
        else:
            # Fall back to ModManager's internal tracking
            mm = self._server.mod_manager
            if mm is not None:
                mm._register_block(block_id, properties or {})
                logger.debug(f"Registered block in mod registry: {block_id}")

    # --- Mod interop ---

    def get_mod(self, mod_id: str) -> Optional[PyMCMod]:
        """Get another mod's main instance (for inter-mod communication)."""
        mm = self._server.mod_manager
        if mm is not None:
            return mm.get_mod(mod_id)
        return None


# ===========================================================
# Hook functions — Fire ModEvents from server code
#
# Every hook:
#   1. Fires to the ModManager event system (ModEvent / ModEvents)
#   2. Delegates to the matching plugin hook so plugins also receive
#      the event via their own event system
# ===========================================================

def hook_server_start(server):
    """
    Fire SERVER_START to all mods, then to the plugin system.
    Not cancellable — the server is already starting.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(ModEvents.SERVER_START, {}, cancellable=False)
        mm.fire_event(event)

    # Also fire to the plugin system
    from plugins.bridge import hook_server_start as plugin_hook
    plugin_hook(server)


def hook_server_stop(server):
    """
    Fire SERVER_STOP to all mods, then to the plugin system.
    Not cancellable — the server is already stopping.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(ModEvents.SERVER_STOP, {}, cancellable=False)
        mm.fire_event(event)

    # Also fire to the plugin system
    from plugins.bridge import hook_server_stop as plugin_hook
    plugin_hook(server)


def hook_player_join(server, conn) -> bool:
    """
    Fire PLAYER_JOIN. Not cancellable (player is already in the game).
    Returns True always.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.PLAYER_JOIN,
            {
                "player_name": conn.username or "",
                "player_uuid": str(conn.uuid) if conn.uuid else "",
            },
            cancellable=False,
        )
        mm.fire_event(event)

    # Also fire to the plugin system
    from plugins.bridge import hook_player_join as plugin_hook
    return plugin_hook(server, conn)


def hook_player_quit(server, conn) -> bool:
    """
    Fire PLAYER_LEAVE. Not cancellable (player has already left).
    Returns True always.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.PLAYER_LEAVE,
            {
                "player_name": conn.username or "",
                "player_uuid": str(conn.uuid) if conn.uuid else "",
            },
            cancellable=False,
        )
        mm.fire_event(event)

    # Also fire to the plugin system
    from plugins.bridge import hook_player_quit as plugin_hook
    return plugin_hook(server, conn)


def hook_player_chat(server, conn, message: str) -> bool:
    """
    Fire CHAT before the message is broadcast.
    Cancellable — if any mod or plugin cancels, the chat is suppressed.
    Returns True if the message should proceed.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.CHAT,
            {
                "player_name": conn.username or "",
                "player_uuid": str(conn.uuid) if conn.uuid else "",
                "message": message,
            },
            cancellable=True,
        )
        if not mm.fire_event(event):
            # A mod cancelled the event — skip plugins too
            return False

    # Also fire to the plugin system
    from plugins.bridge import hook_player_chat as plugin_hook
    return plugin_hook(server, conn, message)


def hook_block_break(server, conn, x: int, y: int, z: int,
                     block_state: int) -> bool:
    """
    Fire BLOCK_BREAK before the block is broken.
    Cancellable — mods or plugins can prevent the break.
    Returns True if the break should proceed.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.BLOCK_BREAK,
            {
                "player_name": conn.username or "",
                "player_uuid": str(conn.uuid) if conn.uuid else "",
                "x": x, "y": y, "z": z,
                "block_state": block_state,
            },
            cancellable=True,
        )
        if not mm.fire_event(event):
            return False

    # Also fire to the plugin system
    from plugins.bridge import hook_block_break as plugin_hook
    return plugin_hook(server, conn, x, y, z, block_state)


def hook_block_place(server, conn, x: int, y: int, z: int,
                     block_state: int) -> bool:
    """
    Fire BLOCK_PLACE before the block is placed.
    Cancellable — mods or plugins can prevent the placement.
    Returns True if the place should proceed.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.BLOCK_PLACE,
            {
                "player_name": conn.username or "",
                "player_uuid": str(conn.uuid) if conn.uuid else "",
                "x": x, "y": y, "z": z,
                "block_state": block_state,
            },
            cancellable=True,
        )
        if not mm.fire_event(event):
            return False

    # Also fire to the plugin system
    from plugins.bridge import hook_block_place as plugin_hook
    return plugin_hook(server, conn, x, y, z, block_state)


def hook_entity_damage(server, entity_id: int, damage: float,
                       source: str = "") -> bool:
    """
    Fire ENTITY_DAMAGE before damage is applied.
    Cancellable — mods or plugins can negate the damage.
    Returns True if the damage should be applied.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.ENTITY_DAMAGE,
            {
                "entity_id": entity_id,
                "damage": damage,
                "source": source,
            },
            cancellable=True,
        )
        if not mm.fire_event(event):
            return False

    # Also fire to the plugin system
    from plugins.bridge import hook_entity_damage as plugin_hook
    return plugin_hook(server, entity_id, damage, source)


def hook_entity_death(server, entity_id: int):
    """
    Fire ENTITY_DEATH. Not cancellable — the entity is already dead.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.ENTITY_DEATH,
            {"entity_id": entity_id},
            cancellable=False,
        )
        mm.fire_event(event)

    # Plugin system has no direct entity_death hook — skip


def hook_chunk_load(server, cx: int, cz: int):
    """
    Fire CHUNK_LOAD. Not cancellable — the chunk is already loaded.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.CHUNK_LOAD,
            {"chunk_x": cx, "chunk_z": cz},
            cancellable=False,
        )
        mm.fire_event(event)

    # Plugin system has no direct chunk_load hook — skip


def hook_chunk_unload(server, cx: int, cz: int):
    """
    Fire CHUNK_UNLOAD. Not cancellable — the chunk is already unloaded.
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(
            ModEvents.CHUNK_UNLOAD,
            {"chunk_x": cx, "chunk_z": cz},
            cancellable=False,
        )
        mm.fire_event(event)

    # Plugin system has no direct chunk_unload hook — skip


def hook_tick(server):
    """
    Fire TICK every game tick (~50 ms at 20 TPS).
    Not cancellable. Use for mod update logic that must run
    every tick (physics, animation, scheduled tasks, etc.).
    """
    mm = server.mod_manager
    if mm is not None:
        event = ModEvent(ModEvents.TICK, {}, cancellable=False)
        mm.fire_event(event)

    # Plugin system has no direct tick hook — skip


# ===========================================================
# Lifecycle — One-call setup and teardown
# ===========================================================

def init_mod_system(server, mods_dir: str = "mods") -> ModManager:
    """
    Initialize the full mod system and wire it into the server.

    Steps:
      1. Create ModManager with a ModServerBridge
      2. Discover mods in *mods_dir*
      3. Load all discovered mods (dependency order)
      4. Enable all loaded mods
      5. Store on server.mod_manager
      6. Fire SERVER_START event

    Returns the ModManager instance.

    Call once during server startup, before the game loop starts.
    """
    # 1. Create manager + bridge
    bridge = ModServerBridge(server)
    mm = ModManager(mods_dir=mods_dir)

    # Wire bridge into manager so mods can access the server
    mm._bridge = bridge

    # 5. Store on server early so mods can find each other during on_load
    server.mod_manager = mm

    # 2. Discover
    discovered = mm.discover_mods(mods_dir)
    logger.info(f"Discovered {len(discovered)} mod(s) in {mods_dir}")

    # 3. Load
    loaded = mm.load_all()
    logger.info(f"Loaded {loaded} mod(s)")

    # 4. Enable
    mm.enable_all()
    enabled = mm.mod_count
    logger.info(f"Enabled {enabled} mod(s)")

    # 6. Fire SERVER_START to mods + plugins
    hook_server_start(server)

    return mm


def shutdown_mod_system(server):
    """
    Shut down the mod system cleanly.

    Steps:
      1. Fire SERVER_STOP event
      2. Disable all mods (reverse load order)
    """
    mm = server.mod_manager
    if mm is None:
        return

    # 1. Fire SERVER_STOP to mods + plugins
    hook_server_stop(server)

    # 2. Disable all mods (shutdown_all also calls on_unload)
    mm.shutdown_all()

    logger.info("Mod system shut down")
