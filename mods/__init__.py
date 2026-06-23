# ============================================================
# PYMC Native Mod System - Python-based mod API for PYMC server
#
# PYMC provides a Python-native mod API. It does NOT support
# Java Fabric/Forge/NeoForge/Quilt mods, as those require
# JVM + Mixin bytecode injection which cannot be replicated
# in a Python/C++ server.
#
# Architecture:
#   ModManager
#     ├── Mod Discovery     - Scan mods/ for Python packages
#     ├── Metadata Parsing   - Read pymc_mod.json descriptors
#     ├── Dependency Graph   - Topological sort for load ordering
#     ├── Lifecycle Manager  - load/enable/disable/unload
#     └── Event Dispatcher   - Fire events to mod callbacks
#
# Mod descriptor format (pymc_mod.json):
#   {
#     "id": "my_mod",
#     "name": "My Cool Mod",
#     "version": "1.0.0",
#     "description": "Does cool things",
#     "main_class": "my_mod.MainMod",   # Python class path
#     "api_version": "1.0",
#     "dependencies": ["other_mod"],
#     "mc_version": "1.21.1"
#   }
# ============================================================

import json
import logging
import os
import sys
import importlib
import importlib.util
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("pymc.mods")


# ===========================================================
# Mod State
# ===========================================================

class ModState(Enum):
    """Lifecycle states for a PYMC native mod."""
    DISCOVERED = "discovered"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERRORED = "errored"
    UNLOADED = "unloaded"


# ===========================================================
# Event Types
# ===========================================================

class ModEvent:
    """Event object passed to mod event handlers."""

    def __init__(self, name: str, data: Optional[Dict[str, Any]] = None,
                 cancellable: bool = True):
        self.name = name
        self.data = data or {}
        self.cancellable = cancellable
        self._cancelled = False

    def cancel(self):
        if self.cancellable:
            self._cancelled = True

    def uncancel(self):
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __repr__(self):
        return f"ModEvent({self.name!r}, cancelled={self._cancelled})"


# Standard event names
class ModEvents:
    SERVER_START = "server_start"
    SERVER_STOP = "server_stop"
    PLAYER_JOIN = "player_join"
    PLAYER_LEAVE = "player_leave"
    BLOCK_BREAK = "block_break"
    BLOCK_PLACE = "block_place"
    CHAT = "chat"
    ENTITY_DAMAGE = "entity_damage"
    ENTITY_DEATH = "entity_death"
    PLAYER_INTERACT = "player_interact"
    CHUNK_LOAD = "chunk_load"
    CHUNK_UNLOAD = "chunk_unload"
    TICK = "tick"
    CRAFT = "craft"


# ===========================================================
# Mod Info
# ===========================================================

@dataclass
class ModInfo:
    """Metadata for a PYMC native mod, parsed from pymc_mod.json."""
    mod_id: str = ""
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    main_class: str = ""       # Python class path, e.g. "my_mod.MainMod"
    api_version: str = "1.0"
    dependencies: List[str] = field(default_factory=list)
    soft_dependencies: List[str] = field(default_factory=list)
    mc_version: str = ""
    package_path: str = ""     # Absolute path to the mod package directory
    extra: Dict[str, Any] = field(default_factory=dict)

    def depends_on(self, mod_id: str) -> bool:
        return mod_id in self.dependencies

    def soft_depends_on(self, mod_id: str) -> bool:
        return mod_id in self.soft_dependencies


# ===========================================================
# PyMCMod Base Class
# ===========================================================

class PyMCMod:
    """
    Base class for PYMC native mods. Mod authors extend this class
    and implement lifecycle methods.

    Example mod (in my_mod/__init__.py or my_mod/main.py):

        from pymc.mods import PyMCMod, ModEvents

        class MainMod(PyMCMod):
            def on_load(self):
                self.logger.info("My mod is loading!")

            def on_enable(self):
                self.register_event_handler(ModEvents.PLAYER_JOIN, self.on_player_join)
                self.register_block("my_mod:custom_block", {
                    "material": "stone",
                    "hardness": 2.0,
                })

            def on_player_join(self, event):
                self.logger.info(f"Player joined: {event.data.get('player')}")

            def on_disable(self):
                self.logger.info("My mod is shutting down!")
    """

    def __init__(self):
        self._mod_info: Optional[ModInfo] = None
        self._manager: Optional['ModManager'] = None
        self._event_handlers: List[tuple] = []  # (event_name, handler)

    @property
    def mod_info(self) -> ModInfo:
        return self._mod_info

    @property
    def logger(self) -> logging.Logger:
        if self._mod_info:
            return logging.getLogger(f"pymc.mods.{self._mod_info.mod_id}")
        return logger

    # --- Lifecycle methods (override in subclass) ---

    def on_load(self):
        """Called when the mod is first loaded. Register blocks/items here."""
        pass

    def on_enable(self):
        """Called when the mod is enabled. Register event handlers here."""
        pass

    def on_disable(self):
        """Called when the mod is disabled. Clean up resources here."""
        pass

    def on_unload(self):
        """Called when the mod is being unloaded. Final cleanup."""
        pass

    # --- Registration API ---

    def register_block(self, block_id: str, properties: Optional[Dict] = None):
        """Register a custom block with the server."""
        if self._manager:
            self._manager._register_block(block_id, properties or {})
            self.logger.debug(f"Registered block: {block_id}")
        else:
            self.logger.warning(f"Cannot register block {block_id}: no manager")

    def register_item(self, item_id: str, properties: Optional[Dict] = None):
        """Register a custom item with the server."""
        if self._manager:
            self._manager._register_item(item_id, properties or {})
            self.logger.debug(f"Registered item: {item_id}")
        else:
            self.logger.warning(f"Cannot register item {item_id}: no manager")

    def register_biome(self, biome_id: str, properties: Optional[Dict] = None):
        """Register a custom biome with the server."""
        if self._manager:
            self._manager._register_biome(biome_id, properties or {})
            self.logger.debug(f"Registered biome: {biome_id}")
        else:
            self.logger.warning(f"Cannot register biome {biome_id}: no manager")

    def register_event_handler(self, event_name: str, handler: Callable[[ModEvent], None]):
        """Register a handler for a specific event type."""
        self._event_handlers.append((event_name, handler))
        if self._manager:
            self._manager._register_event_handler(event_name, handler, self._mod_info.mod_id)


# ===========================================================
# Mod Instance (internal)
# ===========================================================

class _ModInstance:
    """Internal tracking of a loaded mod instance."""

    def __init__(self, info: ModInfo, mod_obj: PyMCMod):
        self.info = info
        self.mod_obj = mod_obj
        self.state = ModState.DISCOVERED
        self.error_message = ""

    @property
    def is_active(self) -> bool:
        return self.state in (ModState.LOADED, ModState.ENABLED)

    @property
    def is_errored(self) -> bool:
        return self.state == ModState.ERRORED


# ===========================================================
# Mod Manager
# ===========================================================

class ModManager:
    """
    Manages PYMC native Python mods: discovery, loading, lifecycle,
    and event dispatch.

    Usage:
        manager = ModManager()
        manager.discover_mods("/path/to/mods")
        manager.load_all()
        manager.enable_all()
        # ... server runs ...
        manager.shutdown_all()
    """

    # Descriptor filename to look for
    MOD_DESCRIPTOR = "pymc_mod.json"
    MOD_ENTRY_FILE = "__pymc_mod__.py"

    def __init__(self, mods_dir: Optional[str] = None):
        self._mods: Dict[str, _ModInstance] = {}
        self._load_order: List[str] = []
        self._discovered: List[ModInfo] = []
        self._event_listeners: Dict[str, List[tuple]] = {}  # event -> [(handler, mod_id)]
        self._blocks: Dict[str, Dict] = {}
        self._items: Dict[str, Dict] = {}
        self._biomes: Dict[str, Dict] = {}
        self._next_listener_id = 0
        self._mods_dir = mods_dir

    # --- Discovery ---

    def scan_mods_directory(self, mods_dir: str) -> List[ModInfo]:
        """Compatibility method: discover mods from a directory."""
        return self.discover_mods(mods_dir)

    def discover_mods(self, mods_dir: Optional[str] = None) -> List[ModInfo]:
        """
        Scan a directory for PYMC native mod packages.
        Looks for directories containing pymc_mod.json or __pymc_mod__.py.
        """
        search_dir = mods_dir or self._mods_dir
        if not search_dir:
            logger.warning("No mods directory specified")
            return []

        search_path = Path(search_dir)
        if not search_path.is_dir():
            logger.warning(f"Mods directory does not exist: {search_dir}")
            return []

        discovered = []
        for entry in sorted(search_path.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith('_') or entry.name.startswith('.'):
                continue

            info = self._parse_mod_descriptor(entry)
            if info:
                discovered.append(info)
                logger.info(f"Discovered mod: {info.mod_id} v{info.version} ({info.name})")
            else:
                # Check for __pymc_mod__.py as fallback
                entry_file = entry / self.MOD_ENTRY_FILE
                if entry_file.exists():
                    info = ModInfo(
                        mod_id=entry.name,
                        name=entry.name,
                        version="0.0.0",
                        main_class=f"{entry.name}",
                        package_path=str(entry),
                    )
                    discovered.append(info)
                    logger.info(f"Discovered mod (entry file): {info.mod_id}")

        self._discovered = discovered
        return discovered

    # --- Loading ---

    def load_all(self) -> int:
        """Load all discovered mods in dependency order. Returns count of loaded mods."""
        order = self._resolve_dependency_order()
        loaded = 0
        for mod_id in order:
            if self.load_mod(mod_id):
                loaded += 1
        return loaded

    def load_mod(self, mod_id: str) -> bool:
        """Load a specific mod by its ID. Returns True on success."""
        info = self._find_discovered(mod_id)
        if not info:
            logger.error(f"Mod not found: {mod_id}")
            return False

        if mod_id in self._mods:
            logger.warning(f"Mod already loaded: {mod_id}")
            return True

        # Check hard dependencies
        for dep_id in info.dependencies:
            if dep_id not in self._mods:
                logger.error(f"Mod {mod_id} missing dependency: {dep_id}")
                instance = _ModInstance(info, PyMCMod())
                instance.state = ModState.ERRORED
                instance.error_message = f"Missing dependency: {dep_id}"
                self._mods[mod_id] = instance
                return False

        # Import the mod package
        try:
            mod_obj = self._import_mod(info)
            if mod_obj is None:
                return False

            instance = _ModInstance(info, mod_obj)
            mod_obj._mod_info = info
            mod_obj._manager = self
            instance.state = ModState.LOADED

            # Call on_load
            mod_obj.on_load()
            instance.state = ModState.LOADED

            self._mods[mod_id] = instance
            self._load_order.append(mod_id)
            logger.info(f"Loaded mod: {mod_id} v{info.version}")
            return True

        except Exception as e:
            logger.exception(f"Failed to load mod {mod_id}: {e}")
            instance = _ModInstance(info, PyMCMod())
            instance.state = ModState.ERRORED
            instance.error_message = str(e)
            self._mods[mod_id] = instance
            return False

    # --- Lifecycle ---

    def enable_all(self):
        """Enable all loaded mods."""
        for mod_id in list(self._load_order):
            self.enable_mod(mod_id)

    def enable_mod(self, mod_id: str) -> bool:
        """Enable a specific mod. Returns True on success."""
        instance = self._mods.get(mod_id)
        if not instance:
            logger.error(f"Cannot enable unknown mod: {mod_id}")
            return False

        if instance.state == ModState.ENABLED:
            return True

        if instance.state not in (ModState.LOADED, ModState.DISCOVERED, ModState.DISABLED):
            logger.error(f"Cannot enable mod {mod_id} in state {instance.state}")
            return False

        try:
            instance.mod_obj.on_enable()
            instance.state = ModState.ENABLED
            logger.info(f"Enabled mod: {mod_id}")
            return True
        except Exception as e:
            logger.exception(f"Failed to enable mod {mod_id}: {e}")
            instance.state = ModState.ERRORED
            instance.error_message = str(e)
            return False

    def disable_mod(self, mod_id: str) -> bool:
        """Disable a specific mod. Returns True on success."""
        instance = self._mods.get(mod_id)
        if not instance:
            return False

        if instance.state != ModState.ENABLED:
            return True

        try:
            instance.mod_obj.on_disable()
            instance.state = ModState.DISABLED
            logger.info(f"Disabled mod: {mod_id}")
            return True
        except Exception as e:
            logger.exception(f"Error disabling mod {mod_id}: {e}")
            instance.state = ModState.ERRORED
            instance.error_message = str(e)
            return False

    def shutdown_all(self):
        """Disable all mods in reverse load order."""
        for mod_id in reversed(self._load_order):
            self.disable_mod(mod_id)
        for mod_id in reversed(self._load_order):
            instance = self._mods.get(mod_id)
            if instance and instance.state in (ModState.DISABLED, ModState.ERRORED):
                try:
                    instance.mod_obj.on_unload()
                    instance.state = ModState.UNLOADED
                except Exception as e:
                    logger.exception(f"Error unloading mod {mod_id}: {e}")
        logger.info("All mods shut down")

    # --- Event Dispatch ---

    def fire_event(self, event: ModEvent) -> bool:
        """
        Fire an event to all registered listeners.
        Returns True if the event was NOT cancelled.
        """
        listeners = self._event_listeners.get(event.name, [])
        for handler, mod_id in listeners:
            instance = self._mods.get(mod_id)
            if not instance or not instance.is_active:
                continue
            try:
                handler(event)
            except Exception as e:
                logger.exception(f"Error in event handler for {event.name} from mod {mod_id}: {e}")
        return not event.cancelled

    def fire_event_simple(self, event_name: str,
                          data: Optional[Dict[str, Any]] = None,
                          cancellable: bool = True) -> bool:
        """Convenience: fire an event by name with data."""
        event = ModEvent(event_name, data, cancellable)
        return self.fire_event(event)

    # --- Query ---

    def is_mod_loaded(self, mod_id: str) -> bool:
        return mod_id in self._mods and self._mods[mod_id].is_active

    def get_mod(self, mod_id: str) -> Optional[PyMCMod]:
        instance = self._mods.get(mod_id)
        return instance.mod_obj if instance else None

    def get_mod_state(self, mod_id: str) -> Optional[ModState]:
        instance = self._mods.get(mod_id)
        return instance.state if instance else None

    def get_loaded_mods(self) -> List[str]:
        return [mid for mid, inst in self._mods.items() if inst.is_active]

    @property
    def mod_count(self) -> int:
        return len([i for i in self._mods.values() if i.is_active])

    @property
    def registered_blocks(self) -> Dict[str, Dict]:
        return dict(self._blocks)

    @property
    def registered_items(self) -> Dict[str, Dict]:
        return dict(self._items)

    @property
    def registered_biomes(self) -> Dict[str, Dict]:
        return dict(self._biomes)

    # --- Internal: Registration callbacks ---

    def _register_block(self, block_id: str, properties: Dict):
        self._blocks[block_id] = properties
        logger.debug(f"Block registered: {block_id}")

    def _register_item(self, item_id: str, properties: Dict):
        self._items[item_id] = properties
        logger.debug(f"Item registered: {item_id}")

    def _register_biome(self, biome_id: str, properties: Dict):
        self._biomes[biome_id] = properties
        logger.debug(f"Biome registered: {biome_id}")

    def _register_event_handler(self, event_name: str, handler: Callable, mod_id: str):
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append((handler, mod_id))

    # --- Internal: Discovery helpers ---

    def _parse_mod_descriptor(self, package_path: Path) -> Optional[ModInfo]:
        """Parse pymc_mod.json from a mod package directory."""
        descriptor = package_path / self.MOD_DESCRIPTOR
        if not descriptor.exists():
            return None

        try:
            with open(descriptor, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to parse {descriptor}: {e}")
            return None

        mod_id = data.get("id", "")
        if not mod_id:
            logger.error(f"Mod descriptor missing 'id': {descriptor}")
            return None

        return ModInfo(
            mod_id=mod_id,
            name=data.get("name", mod_id),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            main_class=data.get("main_class", mod_id),
            api_version=data.get("api_version", "1.0"),
            dependencies=data.get("dependencies", []),
            soft_dependencies=data.get("soft_dependencies", []),
            mc_version=data.get("mc_version", ""),
            package_path=str(package_path),
            extra={k: v for k, v in data.items()
                   if k not in ("id", "name", "version", "description",
                                "main_class", "api_version", "dependencies",
                                "soft_dependencies", "mc_version")},
        )

    def _find_discovered(self, mod_id: str) -> Optional[ModInfo]:
        for info in self._discovered:
            if info.mod_id == mod_id:
                return info
        return None

    def _import_mod(self, info: ModInfo) -> Optional[PyMCMod]:
        """Import a Python mod package and instantiate the main class."""
        pkg_path = Path(info.package_path)
        pkg_name = pkg_path.name

        # Add parent directory to sys.path so we can import the package
        parent = str(pkg_path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        try:
            # Import the package
            mod_module = importlib.import_module(pkg_name)
        except ImportError as e:
            logger.error(f"Failed to import mod package {pkg_name}: {e}")
            return None

        # Resolve main_class
        main_class_path = info.main_class
        if '.' in main_class_path:
            # e.g. "my_mod.MainMod" -> module=my_mod, class=MainMod
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
            # Fallback: look for a PyMCMod subclass in the module
            for attr_name in dir(mod_module):
                attr = getattr(mod_module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, PyMCMod)
                        and attr is not PyMCMod):
                    cls = attr
                    break

        if cls is None:
            logger.error(f"No mod class found in {pkg_name} "
                         f"(expected main_class={main_class_path} or PyMCMod subclass)")
            return None

        try:
            instance = cls()
            if not isinstance(instance, PyMCMod):
                logger.error(f"Main class {main_class_path} is not a PyMCMod subclass")
                return None
            return instance
        except Exception as e:
            logger.error(f"Failed to instantiate mod class {main_class_path}: {e}")
            return None

    # --- Internal: Dependency resolution ---

    def _resolve_dependency_order(self) -> List[str]:
        """Topological sort of discovered mods based on dependencies."""
        mod_ids = {info.mod_id for info in self._discovered}
        graph: Dict[str, Set[str]] = {info.mod_id: set(info.dependencies)
                                      for info in self._discovered}

        # Kahn's algorithm
        in_degree = {mid: 0 for mid in mod_ids}
        for mid, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 0  # ensure dep exists in in_degree
                # Count how many mods depend on each mod
        for mid, deps in graph.items():
            for dep in deps:
                if dep in mod_ids:
                    pass  # dep is a known mod

        # Actually compute in-degrees properly
        adj: Dict[str, List[str]] = {mid: [] for mid in mod_ids}
        in_deg = {mid: 0 for mid in mod_ids}
        for info in self._discovered:
            for dep in info.dependencies:
                if dep in mod_ids:
                    adj[dep].append(info.mod_id)
                    in_deg[info.mod_id] += 1

        queue = [mid for mid in mod_ids if in_deg[mid] == 0]
        queue.sort()  # deterministic order
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            for neighbor in sorted(adj[current]):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        # Add mods with missing deps at the end (they'll fail to load)
        for info in self._discovered:
            if info.mod_id not in result:
                missing = [d for d in info.dependencies if d not in mod_ids]
                if missing:
                    logger.warning(f"Mod {info.mod_id} has missing dependencies: {missing}")
                result.append(info.mod_id)

        return result
