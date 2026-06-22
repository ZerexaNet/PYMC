# ============================================================
# PyMC - Paper Plugin Compatibility Layer: Python Interface
#
# Provides a Python interface to the C++ plugin compatibility
# layer. Supports both Paper/Bukkit .jar plugins (via C++ JVM
# bridge) and native PYMC Python plugins.
#
# Architecture:
#   PluginManager
#     ├── Native Plugin Loader (C++ via ctypes)
#     │   ├── JVMBridge        - Minimal JVM for .jar execution
#     │   ├── EventBus         - Event dispatch system
#     │   ├── BukkitAPI        - API translation layer
#     │   └── PluginLoader     - .jar lifecycle management
#     └── Python Plugin Loader (always available)
#         ├── PyMCPlugin base  - Native Python plugin interface
#         └── Python EventBus  - Lightweight event system
# ============================================================

import ctypes
import ctypes.util
import logging
import os
import sys
import glob
import importlib
import importlib.util
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger("pymc.plugins")

# ===========================================================
# Constants
# ===========================================================

# Event priority levels (matching C++ EventPriority)
class EventPriority(IntEnum):
    LOWEST = 0
    LOW = 1
    NORMAL = 2
    HIGH = 3
    HIGHEST = 4
    MONITOR = 5


# Plugin state
class PluginState(IntEnum):
    UNLOADED = 0
    LOADED = 1
    ENABLING = 2
    ENABLED = 3
    DISABLING = 4
    DISABLED = 5
    ERRORED = 6


# Game mode
class GameMode(IntEnum):
    SURVIVAL = 0
    CREATIVE = 1
    ADVENTURE = 2
    SPECTATOR = 3


# ===========================================================
# Event Data
# ===========================================================

@dataclass
class Event:
    """Represents a game event that can be listened to by plugins."""
    name: str
    data: Dict[str, str] = field(default_factory=dict)
    cancelled: bool = False
    cancellable: bool = True
    source_plugin: str = ""
    tick: int = 0

    def set_data(self, key: str, value: str) -> None:
        self.data[key] = value

    def get_data(self, key: str, default: str = "") -> str:
        return self.data.get(key, default)

    def cancel(self) -> None:
        if self.cancellable:
            self.cancelled = True


# ===========================================================
# Common Event Names (Bukkit-compatible)
# ===========================================================

class EventNames:
    """Bukkit-compatible event name constants."""

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
    BLOCK_DAMAGE = "BlockDamageEvent"
    BLOCK_BURN = "BlockBurnEvent"
    BLOCK_REDSTONE = "BlockRedstoneEvent"
    BLOCK_EXPLODE = "BlockExplodeEvent"

    # Entity events
    ENTITY_DAMAGE = "EntityDamageEvent"
    ENTITY_DEATH = "EntityDeathEvent"
    ENTITY_SPAWN = "EntitySpawnEvent"
    ENTITY_EXPLODE = "EntityExplodeEvent"

    # World events
    CHUNK_LOAD = "ChunkLoadEvent"
    CHUNK_UNLOAD = "ChunkUnloadEvent"
    WEATHER_CHANGE = "WeatherChangeEvent"

    # Server events
    SERVER_COMMAND = "ServerCommandEvent"
    PLUGIN_ENABLE = "PluginEnableEvent"
    PLUGIN_DISABLE = "PluginDisableEvent"

    # Inventory events
    INVENTORY_CLICK = "InventoryClickEvent"
    INVENTORY_OPEN = "InventoryOpenEvent"
    INVENTORY_CLOSE = "InventoryCloseEvent"


# ===========================================================
# PyMCPlugin Base Class
# ===========================================================

class PyMCPlugin:
    """
    Base class for native PYMC plugins (Python-only).

    Subclass this to create a PYMC-native plugin that doesn't
    require the JVM bridge. Python plugins are always available
    and have first-class access to PYMC's internal APIs.

    Example:
        class MyPlugin(PyMCPlugin):
            name = "MyPlugin"
            version = "1.0.0"

            def on_enable(self):
                self.register_listener(EventNames.PLAYER_JOIN, self.on_player_join)

            def on_player_join(self, event):
                player = event.get_data("player_name")
                self.server.broadcast_message(f"Welcome {player}!")
    """

    # Plugin metadata (override in subclass)
    name: str = "UnnamedPlugin"
    version: str = "0.0.1"
    description: str = ""
    author: str = ""
    api_version: str = "1.21"

    def __init__(self):
        self._enabled = False
        self._server = None
        self._manager = None
        self._registered_handlers: List[tuple] = []

    @property
    def server(self):
        """Get the PYMC server instance."""
        return self._server

    @property
    def plugin_manager(self):
        """Get the plugin manager."""
        return self._manager

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # --- Lifecycle ---

    def on_load(self) -> None:
        """Called when the plugin is loaded (before enable)."""
        pass

    def on_enable(self) -> None:
        """Called when the plugin is enabled."""
        pass

    def on_disable(self) -> None:
        """Called when the plugin is disabled."""
        pass

    def on_event(self, event_name: str, data: dict) -> None:
        """Called for any event this plugin listens to (generic handler)."""
        pass

    # --- Convenience Methods ---

    def register_listener(self, event_name: str,
                          handler: Callable[[Event], None],
                          priority: EventPriority = EventPriority.NORMAL) -> int:
        """Register an event listener for this plugin."""
        if self._manager is not None:
            handler_id = self._manager.register_listener(
                event_name, handler, priority, self.name
            )
            self._registered_handlers.append((handler_id, event_name))
            return handler_id
        return -1

    def unregister_listener(self, handler_id: int) -> bool:
        """Unregister a specific event listener."""
        if self._manager is not None:
            return self._manager.unregister_handler(handler_id)
        return False

    def register_command(self, command: str,
                         handler: Callable[[str, dict], bool]) -> None:
        """Register a command handler for this plugin."""
        if self._manager is not None:
            self._manager.register_command(command, handler, self.name)

    def log_info(self, msg: str) -> None:
        """Log an info message with plugin prefix."""
        logger.info(f"[{self.name}] {msg}")

    def log_warning(self, msg: str) -> None:
        """Log a warning message with plugin prefix."""
        logger.warning(f"[{self.name}] {msg}")

    def log_error(self, msg: str) -> None:
        """Log an error message with plugin prefix."""
        logger.error(f"[{self.name}] {msg}")


# ===========================================================
# PythonEventBus
# ===========================================================

class PythonEventBus:
    """
    Lightweight Python event bus for PYMC-native plugins.
    Used when the C++ plugin layer is not available.
    """

    def __init__(self):
        self._handlers: Dict[str, List[tuple]] = {}  # event_name -> [(id, priority, callback, plugin)]
        self._next_id = 0
        self._mutex = None  # threading.Lock if needed

    def register(self, event_name: str, handler: Callable[[Event], None],
                 priority: EventPriority = EventPriority.NORMAL,
                 plugin_name: str = "") -> int:
        """Register an event handler. Returns handler ID."""
        handler_id = self._next_id
        self._next_id += 1
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append((handler_id, priority, handler, plugin_name))
        # Sort by priority
        self._handlers[event_name].sort(key=lambda x: x[1])
        return handler_id

    def unregister(self, handler_id: int) -> bool:
        """Unregister a handler by ID."""
        for event_name, handlers in self._handlers.items():
            for i, (hid, _, _, _) in enumerate(handlers):
                if hid == handler_id:
                    handlers.pop(i)
                    return True
        return False

    def unregister_all(self, plugin_name: str) -> None:
        """Unregister all handlers for a plugin."""
        for event_name in list(self._handlers.keys()):
            self._handlers[event_name] = [
                h for h in self._handlers[event_name]
                if h[3] != plugin_name
            ]

    def fire(self, event: Event) -> Event:
        """Fire an event to all registered handlers."""
        handlers = self._handlers.get(event.name, [])
        for handler_id, priority, callback, plugin_name in handlers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in event handler for {event.name} "
                             f"(plugin={plugin_name}): {e}")
        return event

    def has_listeners(self, event_name: str) -> bool:
        return bool(self._handlers.get(event_name, []))

    def listener_count(self, event_name: str = None) -> int:
        if event_name:
            return len(self._handlers.get(event_name, []))
        return sum(len(h) for h in self._handlers.values())


# ===========================================================
# NativePluginLoader (C++ bridge via ctypes)
# ===========================================================

class NativePluginLoader:
    """
    Interface to the C++ plugin compatibility layer.

    Attempts to load the pymc_plugin_loader shared library and
    use it for Paper/Bukkit .jar plugin compatibility. Falls
    back gracefully if the C++ layer is not available.
    """

    def __init__(self):
        self._lib = None
        self._available = False
        self._load_native_library()

    def _load_native_library(self) -> None:
        """Try to load the native plugin loader shared library."""
        try:
            lib_paths = [
                # Relative to the PYMC project root
                os.path.join(os.path.dirname(__file__), '..', 'native',
                             'libpymc_plugin_loader.so'),
                os.path.join(os.path.dirname(__file__), '..', 'native',
                             'libpymc_plugin_loader.dll'),
                # System paths
                'libpymc_plugin_loader.so',
                'pymc_plugin_loader',
            ]

            for path in lib_paths:
                try:
                    self._lib = ctypes.CDLL(path)
                    self._available = True
                    logger.info(f"Loaded native plugin loader from: {path}")
                    self._setup_functions()
                    return
                except OSError:
                    continue

            logger.info("Native plugin loader not available; "
                        "Paper/Bukkit .jar plugins will not be supported. "
                        "Python plugins are still available.")
        except Exception as e:
            logger.warning(f"Error loading native plugin loader: {e}")

    def _setup_functions(self) -> None:
        """Set up ctypes function signatures for the native library."""
        if not self._lib:
            return

        # pymc_plugin_loader_initialize() -> bool
        self._lib.pymc_plugin_loader_initialize.restype = ctypes.c_bool
        self._lib.pymc_plugin_loader_initialize.argtypes = []

        # pymc_plugin_loader_shutdown()
        self._lib.pymc_plugin_loader_shutdown.restype = None
        self._lib.pymc_plugin_loader_shutdown.argtypes = []

        # pymc_plugin_loader_load_plugin(jar_path: str) -> bool
        self._lib.pymc_plugin_loader_load_plugin.restype = ctypes.c_bool
        self._lib.pymc_plugin_loader_load_plugin.argtypes = [ctypes.c_char_p]

        # pymc_plugin_loader_enable_all() -> bool
        self._lib.pymc_plugin_loader_enable_all.restype = ctypes.c_bool
        self._lib.pymc_plugin_loader_enable_all.argtypes = []

        # pymc_plugin_loader_disable_all()
        self._lib.pymc_plugin_loader_disable_all.restype = None
        self._lib.pymc_plugin_loader_disable_all.argtypes = []

        # pymc_plugin_loader_fire_event(name: str, data_json: str) -> bool
        self._lib.pymc_plugin_loader_fire_event.restype = ctypes.c_bool
        self._lib.pymc_plugin_loader_fire_event.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p
        ]

    @property
    def available(self) -> bool:
        """Whether the native C++ plugin layer is available."""
        return self._available

    def initialize(self) -> bool:
        """Initialize the native plugin loader."""
        if not self._available:
            return False
        try:
            return self._lib.pymc_plugin_loader_initialize()
        except Exception as e:
            logger.error(f"Failed to initialize native plugin loader: {e}")
            self._available = False
            return False

    def shutdown(self) -> None:
        """Shut down the native plugin loader."""
        if not self._available:
            return
        try:
            self._lib.pymc_plugin_loader_shutdown()
        except Exception as e:
            logger.error(f"Error shutting down native plugin loader: {e}")

    def load_plugin(self, jar_path: str) -> bool:
        """Load a .jar plugin via the native loader."""
        if not self._available:
            return False
        try:
            return self._lib.pymc_plugin_loader_load_plugin(
                jar_path.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Error loading .jar plugin {jar_path}: {e}")
            return False

    def enable_all(self) -> bool:
        """Enable all native plugins."""
        if not self._available:
            return False
        try:
            return self._lib.pymc_plugin_loader_enable_all()
        except Exception as e:
            logger.error(f"Error enabling native plugins: {e}")
            return False

    def disable_all(self) -> None:
        """Disable all native plugins."""
        if not self._available:
            return
        try:
            self._lib.pymc_plugin_loader_disable_all()
        except Exception as e:
            logger.error(f"Error disabling native plugins: {e}")

    def fire_event(self, event_name: str, data: dict) -> bool:
        """Fire an event to native plugin listeners."""
        if not self._available:
            return False
        try:
            import json
            data_json = json.dumps(data)
            return self._lib.pymc_plugin_loader_fire_event(
                event_name.encode('utf-8'),
                data_json.encode('utf-8'),
            )
        except Exception as e:
            logger.error(f"Error firing native event {event_name}: {e}")
            return False


# ===========================================================
# PluginManager
# ===========================================================

class PluginManager:
    """
    Python interface to the C++ plugin compatibility layer.

    Manages both Paper/Bukkit .jar plugins (via the C++ native
    layer) and native PYMC Python plugins.

    Usage:
        pm = PluginManager(server)

        # Load a Bukkit .jar plugin (requires C++ native layer)
        pm.load_plugin("plugins/Essentials.jar")

        # Register a native Python plugin
        pm.register_pymc_plugin(MyPlugin())

        # Fire an event
        event = Event("PlayerJoinEvent", {"player_name": "Steve"})
        pm.fire_event(event)
    """

    def __init__(self, server=None):
        self.server = server
        self._native = NativePluginLoader()
        self._event_bus = PythonEventBus()
        self._pymc_plugins: Dict[str, PyMCPlugin] = {}
        self._command_handlers: Dict[str, tuple] = {}  # command -> (handler, plugin_name)
        self._jar_plugins: List[str] = []

        # Initialize the native loader
        if self._native.available:
            self._native.initialize()

    # --- .jar Plugin Support (requires C++ native layer) ---

    def load_plugin(self, jar_path: str) -> bool:
        """
        Load a .jar plugin file.

        Requires the C++ native plugin layer. If not available,
        logs a warning and returns False.

        Args:
            jar_path: Path to the .jar plugin file.

        Returns:
            True if the plugin was loaded successfully.
        """
        if not os.path.exists(jar_path):
            logger.error(f"Plugin .jar not found: {jar_path}")
            return False

        if not self._native.available:
            logger.warning(
                f"Cannot load .jar plugin '{jar_path}': "
                "native plugin layer not available. "
                "Only Python plugins are supported."
            )
            return False

        success = self._native.load_plugin(jar_path)
        if success:
            self._jar_plugins.append(jar_path)
            logger.info(f"Loaded .jar plugin: {jar_path}")
        else:
            logger.error(f"Failed to load .jar plugin: {jar_path}")
        return success

    def load_plugins_from_dir(self, plugins_dir: str) -> int:
        """
        Load all .jar files from a directory.

        Args:
            plugins_dir: Directory containing .jar plugin files.

        Returns:
            Number of plugins loaded successfully.
        """
        if not os.path.isdir(plugins_dir):
            logger.warning(f"Plugins directory not found: {plugins_dir}")
            return 0

        count = 0
        for jar_path in sorted(glob.glob(os.path.join(plugins_dir, "*.jar"))):
            if self.load_plugin(jar_path):
                count += 1

        # Also load Python plugins from the directory
        for py_path in sorted(glob.glob(os.path.join(plugins_dir, "*.py"))):
            try:
                self._load_python_plugin_file(py_path)
                count += 1
            except Exception as e:
                logger.error(f"Failed to load Python plugin {py_path}: {e}")

        return count

    def enable_all(self) -> None:
        """Enable all loaded plugins (both .jar and Python)."""
        # Enable native .jar plugins
        if self._native.available:
            self._native.enable_all()

        # Enable Python plugins
        for name, plugin in self._pymc_plugins.items():
            if not plugin.is_enabled:
                try:
                    plugin._enabled = True
                    plugin.on_enable()
                    logger.info(f"Enabled Python plugin: {name}")
                    # Fire plugin enable event
                    self.fire_event(Event(EventNames.PLUGIN_ENABLE,
                                          {"plugin_name": name}))
                except Exception as e:
                    plugin._enabled = False
                    logger.error(f"Error enabling plugin {name}: {e}")

    def disable_all(self) -> None:
        """Disable all loaded plugins (both .jar and Python)."""
        # Disable Python plugins (reverse order)
        for name in reversed(list(self._pymc_plugins.keys())):
            plugin = self._pymc_plugins[name]
            if plugin.is_enabled:
                try:
                    plugin.on_disable()
                    plugin._enabled = False
                    logger.info(f"Disabled Python plugin: {name}")
                    # Fire plugin disable event
                    self.fire_event(Event(EventNames.PLUGIN_DISABLE,
                                          {"plugin_name": name}))
                except Exception as e:
                    logger.error(f"Error disabling plugin {name}: {e}")

        # Unregister all Python plugin listeners
        for name, plugin in self._pymc_plugins.items():
            self._event_bus.unregister_all(name)

        # Disable native .jar plugins
        if self._native.available:
            self._native.disable_all()

    def fire_event(self, event: Event) -> bool:
        """
        Fire an event to all registered listeners.

        The event is dispatched to both Python and native .jar
        plugin listeners.

        Args:
            event: The event to fire.

        Returns:
            True if the event was NOT cancelled after processing.
        """
        # Fire to Python listeners
        self._event_bus.fire(event)

        # Fire to native .jar listeners
        if self._native.available:
            self._native.fire_event(event.name, event.data)

        return not event.cancelled

    # --- PYMC Python Plugin API (always available) ---

    def register_pymc_plugin(self, plugin: PyMCPlugin) -> None:
        """
        Register a native PYMC Python plugin.

        Args:
            plugin: An instance of PyMCPlugin (or subclass).
        """
        if not isinstance(plugin, PyMCPlugin):
            raise TypeError(f"Expected PyMCPlugin subclass, got {type(plugin)}")

        if plugin.name in self._pymc_plugins:
            logger.warning(f"Plugin '{plugin.name}' is already registered")
            return

        plugin._server = self.server
        plugin._manager = self
        plugin.on_load()
        self._pymc_plugins[plugin.name] = plugin
        logger.info(f"Registered Python plugin: {plugin.name} v{plugin.version}")

    def unregister_pymc_plugin(self, name: str) -> bool:
        """
        Unregister a Python plugin by name.

        Args:
            name: The plugin name.

        Returns:
            True if the plugin was found and unregistered.
        """
        if name not in self._pymc_plugins:
            return False

        plugin = self._pymc_plugins[name]
        if plugin.is_enabled:
            plugin.on_disable()
            plugin._enabled = False

        self._event_bus.unregister_all(name)
        del self._pymc_plugins[name]
        logger.info(f"Unregistered Python plugin: {name}")
        return True

    # --- Event Listener Registration ---

    def register_listener(self, event_name: str,
                          handler: Callable[[Event], None],
                          priority: EventPriority = EventPriority.NORMAL,
                          plugin_name: str = "") -> int:
        """
        Register an event listener.

        Args:
            event_name: Name of the event to listen for.
            handler: Callback function that receives an Event.
            priority: Listener priority (lower = called first).
            plugin_name: Name of the registering plugin.

        Returns:
            Handler ID (for later unregistration).
        """
        return self._event_bus.register(event_name, handler, priority, plugin_name)

    def unregister_handler(self, handler_id: int) -> bool:
        """Unregister a specific event handler by ID."""
        return self._event_bus.unregister(handler_id)

    # --- Command Registration ---

    def register_command(self, command: str,
                         handler: Callable[[str, dict], bool],
                         plugin_name: str = "") -> None:
        """
        Register a command handler.

        Args:
            command: The command name (without /).
            handler: Callback that receives (args_string, sender_info).
                     Returns True if the command was handled.
            plugin_name: Name of the registering plugin.
        """
        if command in self._command_handlers:
            logger.warning(f"Command '/{command}' is already registered, "
                           f"overwriting (was: {self._command_handlers[command][1]})")
        self._command_handlers[command] = (handler, plugin_name)

    def dispatch_command(self, command: str, sender_info: dict = None) -> bool:
        """
        Dispatch a command to registered handlers.

        Args:
            command: Full command string (with /).
            sender_info: Information about the command sender.

        Returns:
            True if the command was handled.
        """
        if sender_info is None:
            sender_info = {}

        # Strip leading /
        cmd = command.lstrip('/')
        parts = cmd.split(' ', 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Fire PlayerCommandPreprocessEvent
        event = Event(EventNames.PLAYER_COMMAND, {
            "command": cmd,
            "player": sender_info.get("name", ""),
        })
        self.fire_event(event)
        if event.cancelled:
            return False

        if cmd_name in self._command_handlers:
            handler, plugin_name = self._command_handlers[cmd_name]
            try:
                return handler(args, sender_info)
            except Exception as e:
                logger.error(f"Error executing command '/{cmd_name}' "
                             f"(plugin={plugin_name}): {e}")
                return False

        return False

    # --- Query ---

    def get_plugin(self, name: str) -> Optional[PyMCPlugin]:
        """Get a Python plugin by name."""
        return self._pymc_plugins.get(name)

    def get_plugin_names(self) -> List[str]:
        """Get names of all loaded plugins."""
        names = list(self._pymc_plugins.keys())
        names.extend(self._jar_plugins)
        return names

    def is_plugin_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        if name in self._pymc_plugins:
            return self._pymc_plugins[name].is_enabled
        return False

    def get_registered_commands(self) -> List[str]:
        """Get list of registered command names."""
        return list(self._command_handlers.keys())

    # --- Internal ---

    def _load_python_plugin_file(self, py_path: str) -> None:
        """Load a Python plugin from a .py file."""
        module_name = f"pymc_plugin_{os.path.basename(py_path).replace('.py', '')}"

        spec = importlib.util.spec_from_file_location(module_name, py_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin from {py_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find PyMCPlugin subclasses in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                    issubclass(attr, PyMCPlugin) and
                    attr is not PyMCPlugin):
                plugin = attr()
                self.register_pymc_plugin(plugin)
                return

        raise ImportError(f"No PyMCPlugin subclass found in {py_path}")

    def shutdown(self) -> None:
        """Shut down the plugin system completely."""
        self.disable_all()
        self._pymc_plugins.clear()
        self._command_handlers.clear()
        if self._native.available:
            self._native.shutdown()
