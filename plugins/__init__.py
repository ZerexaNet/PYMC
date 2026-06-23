# ============================================================
# PYMC Plugin System - Python-based plugin API for PYMC server
#
# PYMC Plugin System provides a Bukkit-inspired event system for
# Python plugins. It does NOT run Java Bukkit/Paper plugins,
# as those require a JVM which cannot be meaningfully embedded
# in a Python/C++ server.
#
# Architecture:
#   PluginManager
#     ├── Plugin Discovery  - Scan plugins/ for Python packages
#     ├── Metadata Parsing   - Read pymc_plugin.json descriptors
#     ├── Dependency Graph   - Topological sort for load ordering
#     ├── Lifecycle Manager  - load/enable/disable/unload
#     ├── Event Dispatcher   - Fire events with priority ordering
#     └── Command Registry   - Register and dispatch commands
#
# Plugin descriptor format (pymc_plugin.json):
#   {
#     "id": "my_plugin",
#     "name": "My Plugin",
#     "version": "1.0.0",
#     "description": "Does plugin things",
#     "main_class": "my_plugin.MainPlugin",
#     "api-version": "1.0",
#     "depend": ["other_plugin"],
#     "softdepend": ["optional_plugin"],
#     "authors": ["AuthorName"]
#   }
# ============================================================

import json
import logging
import os
import sys
import importlib
import importlib.util
import configparser
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any, Set
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger("pymc.plugins")


# ===========================================================
# Constants
# ===========================================================

class EventPriority(IntEnum):
    """Event handler priority. Lower values execute first."""
    LOWEST = 0     # First to execute; other plugins can override
    LOW = 1
    NORMAL = 2     # Default priority
    HIGH = 3
    HIGHEST = 4    # Last to modify the event
    MONITOR = 5    # Read-only; should not modify the event


class PluginState(IntEnum):
    """Lifecycle states for a PYMC plugin."""
    UNLOADED = 0
    LOADED = 1
    ENABLING = 2
    ENABLED = 3
    DISABLING = 4
    DISABLED = 5
    ERRORED = 6


# ===========================================================
# Event Types
# ===========================================================

class PluginEvent:
    """
    Event object passed to plugin event handlers.
    Inspired by Bukkit's event system but PYMC-native.
    """

    def __init__(self, name: str, data: Optional[Dict[str, Any]] = None,
                 cancellable: bool = True):
        self.name = name
        self.data = data or {}
        self.cancellable = cancellable
        self._cancelled = False

    def cancel(self):
        """Cancel this event (if cancellable)."""
        if self.cancellable:
            self._cancelled = True

    def uncancel(self):
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __repr__(self):
        return f"PluginEvent({self.name!r}, cancelled={self._cancelled})"


# Standard event names
class PluginEvents:
    # Server events
    SERVER_START = "ServerStartEvent"
    SERVER_STOP = "ServerStopEvent"

    # Player events
    PLAYER_JOIN = "PlayerJoinEvent"
    PLAYER_QUIT = "PlayerQuitEvent"
    PLAYER_KICK = "PlayerKickEvent"
    PLAYER_CHAT = "AsyncPlayerChatEvent"
    PLAYER_COMMAND = "PlayerCommandPreprocessEvent"
    PLAYER_MOVE = "PlayerMoveEvent"
    PLAYER_TELEPORT = "PlayerTeleportEvent"
    PLAYER_INTERACT = "PlayerInteractEvent"
    PLAYER_RESPAWN = "PlayerRespawnEvent"
    PLAYER_DEATH = "PlayerDeathEvent"
    PLAYER_GAME_MODE = "PlayerGameModeChangeEvent"

    # Block events
    BLOCK_BREAK = "BlockBreakEvent"
    BLOCK_PLACE = "BlockPlaceEvent"
    BLOCK_BURN = "BlockBurnEvent"
    BLOCK_REDSTONE = "BlockRedstoneEvent"
    SIGN_CHANGE = "SignChangeEvent"

    # Entity events
    ENTITY_DAMAGE = "EntityDamageEvent"
    ENTITY_DEATH = "EntityDeathEvent"
    ENTITY_SPAWN = "EntitySpawnEvent"
    PROJECTILE_HIT = "ProjectileHitEvent"

    # World events
    CHUNK_LOAD = "ChunkLoadEvent"
    CHUNK_UNLOAD = "ChunkUnloadEvent"
    WORLD_LOAD = "WorldLoadEvent"
    WEATHER_CHANGE = "WeatherChangeEvent"

    # Inventory events
    INVENTORY_CLICK = "InventoryClickEvent"
    CRAFT_ITEM = "CraftItemEvent"

    # Plugin events
    PLUGIN_ENABLE = "PluginEnableEvent"
    PLUGIN_DISABLE = "PluginDisableEvent"


# ===========================================================
# Plugin Info
# ===========================================================

@dataclass
class PluginInfo:
    """Metadata for a PYMC plugin."""
    plugin_id: str = ""
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    main_class: str = ""       # Python class path
    api_version: str = "1.0"
    depend: List[str] = field(default_factory=list)         # Hard dependencies
    softdepend: List[str] = field(default_factory=list)     # Soft dependencies
    loadbefore: List[str] = field(default_factory=list)     # Load before these
    authors: List[str] = field(default_factory=list)
    prefix: str = ""
    package_path: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def has_hard_dep(self, plugin_id: str) -> bool:
        return plugin_id in self.depend

    def has_soft_dep(self, plugin_id: str) -> bool:
        return plugin_id in self.softdepend


# ===========================================================
# PyMCServer - Server interface available to plugins
# ===========================================================

class PyMCServer:
    """
    Server interface that plugins can access via self.get_server().
    Provides safe, read-only or controlled-mutation access to server state.
    """

    def __init__(self):
        self._online_players: Dict[str, Dict] = {}  # name -> info dict
        self._tps: float = 20.0
        self._version: str = "1.21.1"
        self._running: bool = True
        self._worlds: Dict[str, Dict] = {}

    def broadcast(self, message: str):
        """Broadcast a chat message to all online players."""
        logger.info(f"[Broadcast] {message}")

    def dispatch_command(self, command: str) -> bool:
        """Execute a server command. Returns True on success."""
        logger.info(f"[Command] /{command}")
        return True

    def get_online_players(self) -> List[str]:
        """Get list of online player names."""
        return list(self._online_players.keys())

    def get_tps(self) -> float:
        """Get current server TPS (ticks per second). 20.0 = ideal."""
        return self._tps

    def get_world(self, name: str) -> Optional[Dict]:
        """Get world info by name."""
        return self._worlds.get(name)

    def get_plugin(self, plugin_id: str):
        """Get another plugin's main instance (for inter-plugin comms)."""
        # Resolved at PluginManager level
        return None

    def get_version(self) -> str:
        """Get PYMC server version."""
        return self._version

    def is_running(self) -> bool:
        return self._running


# ===========================================================
# PyMCPlugin Base Class
# ===========================================================

class PyMCPlugin:
    """
    Base class for PYMC native plugins. Plugin authors extend this
    class and implement lifecycle methods.

    Example plugin (in my_plugin/__init__.py):

        from pymc.plugins import PyMCPlugin, PluginEvents, EventPriority

        class MainPlugin(PyMCPlugin):
            def on_load(self):
                self.get_logger().info("My plugin is loading!")

            def on_enable(self):
                self.register_command("hello", self.cmd_hello)
                self.register_event_handler(
                    PluginEvents.PLAYER_JOIN,
                    self.on_player_join,
                    priority=EventPriority.NORMAL
                )

            def cmd_hello(self, args):
                self.get_server().broadcast("Hello from my plugin!")

            def on_player_join(self, event):
                player = event.get("player_name", "unknown")
                self.get_logger().info(f"Player joined: {player}")

            def on_disable(self):
                self.get_logger().info("My plugin is shutting down!")
    """

    def __init__(self):
        self._plugin_info: Optional[PluginInfo] = None
        self._manager: Optional['PluginManager'] = None
        self._server: Optional[PyMCServer] = None
        self._config: Dict[str, Any] = {}
        self._event_handlers: List[tuple] = []  # (event_name, handler, priority)
        self._commands: Dict[str, Callable] = {}

    @property
    def plugin_info(self) -> PluginInfo:
        return self._plugin_info

    # --- Lifecycle methods (override in subclass) ---

    def on_load(self):
        """Called when the plugin is first loaded. Read config, init resources."""
        pass

    def on_enable(self):
        """Called when the plugin is enabled. Register commands/events here."""
        pass

    def on_disable(self):
        """Called when the plugin is disabled. Clean up resources here."""
        pass

    # --- Accessors ---

    def get_server(self) -> PyMCServer:
        """Get the server interface."""
        return self._server or PyMCServer()

    def get_logger(self) -> logging.Logger:
        """Get a logger namespaced to this plugin."""
        if self._plugin_info:
            return logging.getLogger(f"pymc.plugins.{self._plugin_info.plugin_id}")
        return logger

    def get_config(self) -> Dict[str, Any]:
        """Get this plugin's configuration."""
        return self._config

    # --- Registration API ---

    def register_command(self, name: str, handler: Callable[[str], None]):
        """Register a command handler. handler receives the argument string."""
        self._commands[name] = handler
        if self._manager:
            self._manager._register_command(name, handler, self._plugin_info.plugin_id)
        self.get_logger().debug(f"Registered command: /{name}")

    def register_event_handler(self, event_name: str,
                               handler: Callable[[PluginEvent], None],
                               priority: EventPriority = EventPriority.NORMAL):
        """Register an event handler with a priority."""
        self._event_handlers.append((event_name, handler, priority))
        if self._manager:
            self._manager._register_event_handler(
                event_name, handler, priority, self._plugin_info.plugin_id
            )

    def register_listener(self, event_name: str,
                          handler: Callable[[PluginEvent], None]):
        """Convenience: register at NORMAL priority."""
        self.register_event_handler(event_name, handler, EventPriority.NORMAL)


# ===========================================================
# Plugin Instance (internal)
# ===========================================================

class _PluginInstance:
    """Internal tracking of a loaded plugin instance."""

    def __init__(self, info: PluginInfo, plugin_obj: PyMCPlugin):
        self.info = info
        self.plugin_obj = plugin_obj
        self.state = PluginState.UNLOADED
        self.error_message = ""

    @property
    def is_active(self) -> bool:
        return self.state in (PluginState.LOADED, PluginState.ENABLING, PluginState.ENABLED)

    @property
    def is_errored(self) -> bool:
        return self.state == PluginState.ERRORED


# ===========================================================
# Event Handler Entry (internal)
# ===========================================================

@dataclass
class _EventHandlerEntry:
    handler: Callable[[PluginEvent], None]
    priority: EventPriority
    plugin_id: str


# ===========================================================
# Plugin Manager
# ===========================================================

class PluginManager:
    """
    Manages PYMC native Python plugins: discovery, loading,
    lifecycle, event dispatch, and command routing.

    Usage:
        manager = PluginManager()
        manager.discover_plugins("/path/to/plugins")
        manager.load_all()
        manager.enable_all()
        # ... server runs, events are fired ...
        manager.shutdown_all()
    """

    # Descriptor filenames to look for (in order of preference)
    PLUGIN_DESCRIPTORS = ["pymc_plugin.json", "plugin.yml"]

    def __init__(self, plugins_dir: Optional[str] = None, server: Optional[PyMCServer] = None):
        self._plugins: Dict[str, _PluginInstance] = {}
        self._load_order: List[str] = []
        self._discovered: List[PluginInfo] = []
        self._event_listeners: Dict[str, List[_EventHandlerEntry]] = {}
        self._commands: Dict[str, tuple] = {}  # command -> (handler, plugin_id)
        self._server = server or PyMCServer()
        self._plugins_dir = plugins_dir

    # --- Discovery ---

    def discover_plugins(self, plugins_dir: Optional[str] = None) -> List[PluginInfo]:
        """
        Scan a directory for PYMC native plugin packages.
        Looks for directories containing pymc_plugin.json or plugin.yml.
        """
        search_dir = plugins_dir or self._plugins_dir
        if not search_dir:
            logger.warning("No plugins directory specified")
            return []

        search_path = Path(search_dir)
        if not search_path.is_dir():
            logger.warning(f"Plugins directory does not exist: {search_dir}")
            return []

        discovered = []
        for entry in sorted(search_path.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith('_') or entry.name.startswith('.'):
                continue

            info = self._parse_plugin_descriptor(entry)
            if info:
                discovered.append(info)
                logger.info(f"Discovered plugin: {info.plugin_id} v{info.version} ({info.name})")

        self._discovered = discovered
        return discovered

    # --- Loading ---

    def load_all(self) -> int:
        """Load all discovered plugins in dependency order. Returns count loaded."""
        order = self._resolve_dependency_order()
        loaded = 0
        for plugin_id in order:
            if self.load_plugin(plugin_id):
                loaded += 1
        return loaded

    def load_plugin(self, plugin_id: str) -> bool:
        """Load a specific plugin by its ID. Returns True on success."""
        info = self._find_discovered(plugin_id)
        if not info:
            logger.error(f"Plugin not found: {plugin_id}")
            return False

        if plugin_id in self._plugins:
            logger.warning(f"Plugin already loaded: {plugin_id}")
            return True

        # Check hard dependencies
        for dep_id in info.depend:
            if dep_id not in self._plugins:
                logger.error(f"Plugin {plugin_id} missing dependency: {dep_id}")
                instance = _PluginInstance(info, PyMCPlugin())
                instance.state = PluginState.ERRORED
                instance.error_message = f"Missing dependency: {dep_id}"
                self._plugins[plugin_id] = instance
                return False

        # Import the plugin package
        try:
            plugin_obj = self._import_plugin(info)
            if plugin_obj is None:
                return False

            instance = _PluginInstance(info, plugin_obj)
            plugin_obj._plugin_info = info
            plugin_obj._manager = self
            plugin_obj._server = self._server
            instance.state = PluginState.LOADED

            # Call on_load
            plugin_obj.on_load()
            instance.state = PluginState.LOADED

            self._plugins[plugin_id] = instance
            self._load_order.append(plugin_id)
            logger.info(f"Loaded plugin: {plugin_id} v{info.version}")
            return True

        except Exception as e:
            logger.exception(f"Failed to load plugin {plugin_id}: {e}")
            instance = _PluginInstance(info, PyMCPlugin())
            instance.state = PluginState.ERRORED
            instance.error_message = str(e)
            self._plugins[plugin_id] = instance
            return False

    # --- Lifecycle ---

    def enable_all(self):
        """Enable all loaded plugins."""
        for plugin_id in list(self._load_order):
            self.enable_plugin(plugin_id)

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a specific plugin. Returns True on success."""
        instance = self._plugins.get(plugin_id)
        if not instance:
            logger.error(f"Cannot enable unknown plugin: {plugin_id}")
            return False

        if instance.state == PluginState.ENABLED:
            return True

        if instance.state not in (PluginState.LOADED, PluginState.DISABLED):
            logger.error(f"Cannot enable plugin {plugin_id} in state {instance.state}")
            return False

        try:
            instance.state = PluginState.ENABLING
            instance.plugin_obj.on_enable()
            instance.state = PluginState.ENABLED
            # Fire plugin enable event
            self.fire_event_simple(PluginEvents.PLUGIN_ENABLE,
                                   {"plugin_id": plugin_id},
                                   cancellable=False)
            logger.info(f"Enabled plugin: {plugin_id}")
            return True
        except Exception as e:
            logger.exception(f"Failed to enable plugin {plugin_id}: {e}")
            instance.state = PluginState.ERRORED
            instance.error_message = str(e)
            return False

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a specific plugin. Returns True on success."""
        instance = self._plugins.get(plugin_id)
        if not instance:
            return False

        if instance.state != PluginState.ENABLED:
            return True

        try:
            instance.state = PluginState.DISABLING
            instance.plugin_obj.on_disable()
            # Unregister all event handlers for this plugin
            self._unregister_plugin_events(plugin_id)
            # Unregister commands
            self._unregister_plugin_commands(plugin_id)
            instance.state = PluginState.DISABLED
            # Fire plugin disable event
            self.fire_event_simple(PluginEvents.PLUGIN_DISABLE,
                                   {"plugin_id": plugin_id},
                                   cancellable=False)
            logger.info(f"Disabled plugin: {plugin_id}")
            return True
        except Exception as e:
            logger.exception(f"Error disabling plugin {plugin_id}: {e}")
            instance.state = PluginState.ERRORED
            instance.error_message = str(e)
            return False

    def shutdown_all(self):
        """Disable all plugins in reverse load order."""
        for plugin_id in reversed(self._load_order):
            self.disable_plugin(plugin_id)
        logger.info("All plugins shut down")

    # --- Event System ---

    def fire_event(self, event: PluginEvent) -> bool:
        """
        Fire an event to all registered listeners in priority order.
        Returns True if the event was NOT cancelled.
        """
        listeners = self._event_listeners.get(event.name, [])
        # Sort by priority (lower = first)
        sorted_listeners = sorted(listeners, key=lambda e: e.priority)

        for entry in sorted_listeners:
            instance = self._plugins.get(entry.plugin_id)
            if not instance or not instance.is_active:
                continue
            try:
                entry.handler(event)
            except Exception as e:
                logger.exception(
                    f"Error in event handler for {event.name} "
                    f"from plugin {entry.plugin_id}: {e}"
                )
        return not event.cancelled

    def fire_event_simple(self, event_name: str,
                          data: Optional[Dict[str, Any]] = None,
                          cancellable: bool = True) -> bool:
        """Convenience: fire an event by name with data."""
        event = PluginEvent(event_name, data, cancellable)
        return self.fire_event(event)

    # --- Command System ---

    def dispatch_command(self, command: str, args: str = "") -> bool:
        """
        Dispatch a command to the registered handler.
        Returns True if a handler was found and executed.
        """
        entry = self._commands.get(command)
        if entry is None:
            logger.debug(f"No handler for command: /{command}")
            return False

        handler, plugin_id = entry
        instance = self._plugins.get(plugin_id)
        if not instance or not instance.is_active:
            logger.warning(f"Plugin {plugin_id} for command /{command} is not active")
            return False

        try:
            handler(args)
            return True
        except Exception as e:
            logger.exception(f"Error executing command /{command} from plugin {plugin_id}: {e}")
            return False

    # --- Query ---

    def is_plugin_loaded(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins and self._plugins[plugin_id].is_active

    def get_plugin(self, plugin_id: str) -> Optional[PyMCPlugin]:
        instance = self._plugins.get(plugin_id)
        return instance.plugin_obj if instance else None

    def get_plugin_state(self, plugin_id: str) -> Optional[PluginState]:
        instance = self._plugins.get(plugin_id)
        return instance.state if instance else None

    def get_loaded_plugins(self) -> List[str]:
        return [pid for pid, inst in self._plugins.items() if inst.is_active]

    @property
    def plugin_count(self) -> int:
        return len([i for i in self._plugins.values() if i.is_active])

    def get_registered_commands(self) -> List[str]:
        return list(self._commands.keys())

    # --- Inter-plugin communication ---

    def get_plugin_instance(self, plugin_id: str) -> Optional[PyMCPlugin]:
        """Get another plugin's main instance for inter-plugin communication."""
        return self.get_plugin(plugin_id)

    # --- Internal: Registration callbacks ---

    def _register_command(self, name: str, handler: Callable, plugin_id: str):
        if name in self._commands:
            existing_plugin = self._commands[name][1]
            logger.warning(f"Command /{name} already registered by {existing_plugin}, "
                           f"overwriting with {plugin_id}")
        self._commands[name] = (handler, plugin_id)

    def _register_event_handler(self, event_name: str, handler: Callable,
                                priority: EventPriority, plugin_id: str):
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(
            _EventHandlerEntry(handler=handler, priority=priority, plugin_id=plugin_id)
        )

    def _unregister_plugin_events(self, plugin_id: str):
        """Remove all event handlers for a plugin."""
        for event_name in list(self._event_listeners.keys()):
            self._event_listeners[event_name] = [
                e for e in self._event_listeners[event_name]
                if e.plugin_id != plugin_id
            ]
            if not self._event_listeners[event_name]:
                del self._event_listeners[event_name]

    def _unregister_plugin_commands(self, plugin_id: str):
        """Remove all commands registered by a plugin."""
        to_remove = [cmd for cmd, (_, pid) in self._commands.items() if pid == plugin_id]
        for cmd in to_remove:
            del self._commands[cmd]

    # --- Internal: Discovery helpers ---

    def _parse_plugin_descriptor(self, package_path: Path) -> Optional[PluginInfo]:
        """Parse plugin descriptor from a plugin package directory."""
        # Try pymc_plugin.json first
        json_desc = package_path / "pymc_plugin.json"
        if json_desc.exists():
            return self._parse_json_descriptor(json_desc, package_path)

        # Try plugin.yml (YAML-style, but we parse it simply)
        yml_desc = package_path / "plugin.yml"
        if yml_desc.exists():
            return self._parse_yml_descriptor(yml_desc, package_path)

        return None

    def _parse_json_descriptor(self, descriptor: Path, package_path: Path) -> Optional[PluginInfo]:
        try:
            with open(descriptor, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to parse {descriptor}: {e}")
            return None

        plugin_id = data.get("id", data.get("name", ""))
        if not plugin_id:
            logger.error(f"Plugin descriptor missing 'id': {descriptor}")
            return None

        # Normalize id (replace spaces with underscores, lowercase)
        plugin_id = plugin_id.lower().replace(' ', '_')

        return PluginInfo(
            plugin_id=plugin_id,
            name=data.get("name", plugin_id),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            main_class=data.get("main_class", data.get("main", plugin_id)),
            api_version=data.get("api-version", data.get("api_version", "1.0")),
            depend=data.get("depend", []),
            softdepend=data.get("softdepend", []),
            loadbefore=data.get("loadbefore", []),
            authors=data.get("authors", []),
            prefix=data.get("prefix", ""),
            package_path=str(package_path),
            extra={k: v for k, v in data.items()
                   if k not in ("id", "name", "version", "description",
                                "main_class", "main", "api-version", "api_version",
                                "depend", "softdepend", "loadbefore",
                                "authors", "prefix")},
        )

    def _parse_yml_descriptor(self, descriptor: Path, package_path: Path) -> Optional[PluginInfo]:
        """Minimal YAML-like parser for plugin.yml (Bukkit format)."""
        try:
            with open(descriptor, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as e:
            logger.error(f"Failed to read {descriptor}: {e}")
            return None

        # Simple YAML key: value parser (doesn't handle nested structures well)
        data: Dict[str, Any] = {}
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                key, _, value = line.partition(':')
                key = key.strip()
                value = value.strip()
                # Handle list values (simplified)
                if value.startswith('[') and value.endswith(']'):
                    value = [v.strip().strip('"\'') for v in value[1:-1].split(',') if v.strip()]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                data[key] = value

        plugin_name = data.get("name", "")
        if not plugin_name:
            logger.error(f"Plugin descriptor missing 'name': {descriptor}")
            return None

        plugin_id = plugin_name.lower().replace(' ', '_')

        return PluginInfo(
            plugin_id=plugin_id,
            name=plugin_name,
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            main_class=data.get("main", plugin_id),
            api_version=data.get("api-version", "1.0"),
            depend=data.get("depend", []) if isinstance(data.get("depend"), list) else [],
            softdepend=data.get("softdepend", []) if isinstance(data.get("softdepend"), list) else [],
            loadbefore=data.get("loadbefore", []) if isinstance(data.get("loadbefore"), list) else [],
            authors=data.get("authors", []) if isinstance(data.get("authors"), list) else [],
            prefix=data.get("prefix", ""),
            package_path=str(package_path),
        )

    def _find_discovered(self, plugin_id: str) -> Optional[PluginInfo]:
        for info in self._discovered:
            if info.plugin_id == plugin_id:
                return info
        return None

    def _import_plugin(self, info: PluginInfo) -> Optional[PyMCPlugin]:
        """Import a Python plugin package and instantiate the main class."""
        pkg_path = Path(info.package_path)
        pkg_name = pkg_path.name

        # Add parent directory to sys.path
        parent = str(pkg_path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        try:
            mod_module = importlib.import_module(pkg_name)
        except ImportError as e:
            logger.error(f"Failed to import plugin package {pkg_name}: {e}")
            return None

        # Resolve main_class
        main_class_path = info.main_class
        cls = None

        if '.' in main_class_path:
            parts = main_class_path.rsplit('.', 1)
            try:
                sub_module = importlib.import_module(parts[0])
                cls = getattr(sub_module, parts[1], None)
            except (ImportError, AttributeError) as e:
                logger.error(f"Failed to resolve main_class {main_class_path}: {e}")
                return None
        else:
            cls = getattr(mod_module, main_class_path, None)

        if cls is None:
            # Fallback: look for a PyMCPlugin subclass in the module
            for attr_name in dir(mod_module):
                attr = getattr(mod_module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, PyMCPlugin)
                        and attr is not PyMCPlugin):
                    cls = attr
                    break

        if cls is None:
            logger.error(f"No plugin class found in {pkg_name} "
                         f"(expected main_class={main_class_path} or PyMCPlugin subclass)")
            return None

        try:
            instance = cls()
            if not isinstance(instance, PyMCPlugin):
                logger.error(f"Main class {main_class_path} is not a PyMCPlugin subclass")
                return None
            return instance
        except Exception as e:
            logger.error(f"Failed to instantiate plugin class {main_class_path}: {e}")
            return None

    # --- Internal: Dependency resolution ---

    def _resolve_dependency_order(self) -> List[str]:
        """Topological sort of discovered plugins based on dependencies."""
        plugin_ids = {info.plugin_id for info in self._discovered}

        # Build adjacency list and in-degrees
        adj: Dict[str, List[str]] = {pid: [] for pid in plugin_ids}
        in_deg: Dict[str, int] = {pid: 0 for pid in plugin_ids}

        for info in self._discovered:
            for dep in info.depend:
                if dep in plugin_ids:
                    adj[dep].append(info.plugin_id)
                    in_deg[info.plugin_id] += 1

        # Kahn's algorithm
        queue = sorted([pid for pid in plugin_ids if in_deg[pid] == 0])
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            for neighbor in sorted(adj[current]):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        # Add plugins with missing deps at the end
        for info in self._discovered:
            if info.plugin_id not in result:
                missing = [d for d in info.depend if d not in plugin_ids]
                if missing:
                    logger.warning(f"Plugin {info.plugin_id} has missing dependencies: {missing}")
                result.append(info.plugin_id)

        return result
