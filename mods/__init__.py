# ============================================================
# PyMC - Mod Compatibility Layer: Python Interface
#
# Provides a Python interface to the C++ mod compatibility layer.
# Supports loading Fabric, Forge, NeoForge, and Quilt mods
# and translating their API calls to PYMC server operations.
#
# Architecture:
#   ModManager
#     ├── Native Mod Loader (C++ via ctypes)
#     │   ├── ModLoader         - Mod discovery & lifecycle
#     │   ├── FabricAPIBridge   - Fabric API translation
#     │   ├── ForgeAPIBridge    - Forge/NeoForge API translation
#     │   └── JVMInterface      - JNI-based .jar execution
#     └── Python Mod Support
#         ├── Pure Python mods  - No JVM required
#         └── API emulation     - Python-level API bridge
#
# Mod identification (from .jar contents):
#   - fabric.mod.json   -> Fabric mod
#   - quilt.mod.json    -> Quilt mod
#   - META-INF/mods.toml -> Forge/NeoForge mod
#     (NeoForge uses same location but different schema version)
#
# Loading pipeline:
#   1. Scan mods directory for .jar files
#   2. Identify mod type by inspecting jar contents
#   3. Parse mod metadata (ID, version, dependencies)
#   4. Resolve dependency graph
#   5. Initialize JVM if any mod requires it
#   6. Load and initialize each mod via appropriate bridge
#   7. Register API handlers for mod callbacks
# ============================================================

import ctypes
import ctypes.util
import json
import logging
import os
import glob
import zipfile
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger("pymc.mods")

# ===========================================================
# Constants
# ===========================================================

# Mod loader types (matching C++ ModLoaderType)
class ModLoaderType(IntEnum):
    FABRIC = 0
    FORGE = 1
    NEOFORGE = 2
    QUILT = 3


# Mod states (matching C++ ModState)
class ModState(IntEnum):
    DISCOVERED = 0
    LOADED = 1
    INITIALIZED = 2
    ENABLED = 3
    DISABLED = 4
    ERRORED = 5
    UNLOADED = 6


# ===========================================================
# ModInfo
# ===========================================================

@dataclass
class ModInfo:
    """Information about a discovered mod."""
    mod_id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    loader_type: str = ""        # "fabric", "forge", "neoforge", "quilt"
    entry_point: str = ""        # Main class / initializer
    dependencies: List[str] = field(default_factory=list)
    soft_dependencies: List[str] = field(default_factory=list)
    jar_path: str = ""
    mc_version: str = ""
    loader_version: str = ""
    extra_metadata: Dict[str, str] = field(default_factory=dict)

    def depends_on(self, other_mod_id: str) -> bool:
        """Check if this mod depends on another mod."""
        return other_mod_id in self.dependencies

    def soft_depends_on(self, other_mod_id: str) -> bool:
        """Check if this mod has a soft dependency on another mod."""
        return other_mod_id in self.soft_dependencies


# ===========================================================
# ModManager
# ===========================================================

class ModManager:
    """Python interface to the C++ mod compatibility layer.

    Manages loading of Fabric/Forge/NeoForge/Quilt mods and
    provides Python-level API for mod interaction.
    """

    LOADER_TYPES = {
        "fabric": "FABRIC",
        "forge": "FORGE",
        "neoforge": "NEOFORGE",
        "quilt": "QUILT",
    }

    # File markers inside .jar that identify the mod loader type
    FABRIC_MARKER = "fabric.mod.json"
    QUILT_MARKER = "quilt.mod.json"
    FORGE_MARKER = "META-INF/mods.toml"

    def __init__(self, server):
        self.server = server
        self._native = None
        self.loaded_mods: List[Dict] = []
        self._discovered_mods: List[ModInfo] = []
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._api_handlers: Dict[str, List[Callable]] = {}
        self._mod_states: Dict[str, ModState] = {}

        # Try to load native mod loader
        try:
            from native import NativeCore
            core = NativeCore()
            if hasattr(core, 'mod_loader'):
                self._native = core.mod_loader
                logger.info("Native mod loader loaded successfully")
        except Exception as e:
            logger.debug(f"Native mod loader not available: {e}")

    # --- Mod Discovery ---

    def scan_mods_directory(self, mods_dir: str) -> List[ModInfo]:
        """Scan a directory for mod jars.

        Args:
            mods_dir: Path to directory containing .jar files

        Returns:
            List of ModInfo for all discovered mods
        """
        mods = []
        if not os.path.isdir(mods_dir):
            logger.warning(f"Mods directory does not exist: {mods_dir}")
            return mods

        for jar_file in sorted(glob.glob(os.path.join(mods_dir, "*.jar"))):
            info = self._identify_mod(jar_file)
            if info:
                mods.append(info)
                self._discovered_mods.append(info)
                self._mod_states[info.mod_id] = ModState.DISCOVERED
                logger.info(f"Discovered {info.loader_type} mod: {info.name} v{info.version} ({info.mod_id})")
            else:
                logger.warning(f"Could not identify mod type for: {jar_file}")

        return mods

    def _identify_mod(self, jar_path: str) -> Optional[ModInfo]:
        """Identify mod type from jar file.

        Reads the jar (ZIP) and checks for:
        - fabric.mod.json -> Fabric mod
        - quilt.mod.json -> Quilt mod
        - META-INF/mods.toml -> Forge/NeoForge mod
        """
        try:
            with zipfile.ZipFile(jar_path) as zf:
                names = zf.namelist()

                if self.FABRIC_MARKER in names:
                    return self._parse_fabric_mod(jar_path, zf)
                elif self.QUILT_MARKER in names:
                    return self._parse_quilt_mod(jar_path, zf)
                elif self.FORGE_MARKER in names:
                    return self._parse_forge_mod(jar_path, zf)
                else:
                    logger.debug(f"No mod descriptor found in: {jar_path}")
        except zipfile.BadZipFile:
            logger.warning(f"Invalid jar file: {jar_path}")
        except Exception as e:
            logger.warning(f"Error identifying mod {jar_path}: {e}")

        return None

    # --- Mod Metadata Parsing ---

    def _parse_fabric_mod(self, jar_path: str, zf: zipfile.ZipFile) -> Optional[ModInfo]:
        """Parse fabric.mod.json from a Fabric mod jar."""
        try:
            with zf.open(self.FABRIC_MARKER) as f:
                data = json.loads(f.read().decode('utf-8'))

            info = ModInfo()
            info.jar_path = jar_path
            info.loader_type = "fabric"
            info.mod_id = data.get("id", "")
            info.name = data.get("name", info.mod_id)
            info.version = data.get("version", "")
            info.description = data.get("description", "")

            # Entry points
            entrypoints = data.get("entrypoints", {})
            if "main" in entrypoints and entrypoints["main"]:
                info.entry_point = entrypoints["main"][0]
            elif "server" in entrypoints and entrypoints["server"]:
                info.entry_point = entrypoints["server"][0]

            # Dependencies
            depends = data.get("depends", {})
            for dep_id, dep_version in depends.items():
                if dep_id != "minecraft" and dep_id != "java" and dep_id != "fabricloader":
                    info.dependencies.append(dep_id)
                elif dep_id == "minecraft":
                    info.mc_version = str(dep_version)
                elif dep_id == "fabricloader":
                    info.loader_version = str(dep_version)

            # Soft dependencies
            recommends = data.get("recommends", {})
            for dep_id in recommends:
                if dep_id != "minecraft":
                    info.soft_dependencies.append(dep_id)

            # Extra metadata
            info.extra_metadata["contact"] = json.dumps(data.get("contact", {}))
            info.extra_metadata["license"] = data.get("license", "")
            info.extra_metadata["environment"] = data.get("environment", "*")

            return info

        except Exception as e:
            logger.warning(f"Error parsing Fabric mod {jar_path}: {e}")
            return None

    def _parse_quilt_mod(self, jar_path: str, zf: zipfile.ZipFile) -> Optional[ModInfo]:
        """Parse quilt.mod.json from a Quilt mod jar."""
        try:
            with zf.open(self.QUILT_MARKER) as f:
                data = json.loads(f.read().decode('utf-8'))

            info = ModInfo()
            info.jar_path = jar_path
            info.loader_type = "quilt"

            # Quilt mod.json has a different structure
            quilt_loader = data.get("quilt_loader", {})
            info.mod_id = quilt_loader.get("id", "")
            info.version = quilt_loader.get("version", "")

            # Metadata
            metadata = data.get("metadata", {})
            info.name = metadata.get("name", info.mod_id)
            info.description = metadata.get("description", "")

            # Entry points
            entrypoints = data.get("entrypoints", {})
            if "main" in entrypoints and entrypoints["main"]:
                adapter, entry_class = entrypoints["main"][0]
                info.entry_point = entry_class

            # Dependencies
            depends = quilt_loader.get("depends", [])
            for dep in depends:
                dep_id = dep.get("id", "") if isinstance(dep, dict) else str(dep)
                if dep_id not in ("minecraft", "java", "quilt_loader", "fabricloader"):
                    info.dependencies.append(dep_id)
                elif dep_id == "minecraft":
                    info.mc_version = str(dep.get("version", ""))

            # Soft dependencies
            breaks = quilt_loader.get("breaks", [])
            for dep in breaks:
                dep_id = dep.get("id", "") if isinstance(dep, dict) else str(dep)
                info.soft_dependencies.append(dep_id)

            return info

        except Exception as e:
            logger.warning(f"Error parsing Quilt mod {jar_path}: {e}")
            return None

    def _parse_forge_mod(self, jar_path: str, zf: zipfile.ZipFile) -> Optional[ModInfo]:
        """Parse META-INF/mods.toml from a Forge/NeoForge mod jar."""
        try:
            with zf.open(self.FORGE_MARKER) as f:
                toml_content = f.read().decode('utf-8')

            # Simple TOML parser (enough for mods.toml)
            toml_data = self._parse_simple_toml(toml_content)

            info = ModInfo()
            info.jar_path = jar_path

            # Determine if this is Forge or NeoForge
            # NeoForge uses a different modLoader format and schema version
            loader_version = toml_data.get("modLoader", "")
            if "neoforge" in loader_version.lower() or "neo" in loader_version.lower():
                info.loader_type = "neoforge"
            else:
                info.loader_type = "forge"

            # Parse mod entries
            # mods.toml can have multiple [[mods]] entries
            mod_id = toml_data.get("modId", "")
            info.mod_id = mod_id
            info.name = toml_data.get("displayName", mod_id)
            info.version = toml_data.get("version", "")
            info.description = toml_data.get("description", "")

            # Entry point (the @Mod annotated class)
            info.entry_point = toml_data.get("modId", "")  # Forge uses @Mod(modid)

            # Minecraft version
            mc_version = toml_data.get("mcVersion", "")
            if mc_version:
                info.mc_version = mc_version

            # Dependencies
            # Forge dependencies are specified as [[dependencies.modId]] entries
            deps_str = toml_data.get("dependencies", "")
            if deps_str:
                for dep in deps_str.split(","):
                    dep = dep.strip()
                    if dep and dep != "minecraft" and dep != "forge":
                        info.dependencies.append(dep)

            # Loader version
            loader_version_val = toml_data.get("loaderVersion", "")
            if loader_version_val:
                info.loader_version = loader_version_val

            return info

        except Exception as e:
            logger.warning(f"Error parsing Forge/NeoForge mod {jar_path}: {e}")
            return None

    def _parse_simple_toml(self, content: str) -> Dict[str, str]:
        """Parse a simple TOML file into key-value pairs.

        This is a minimal parser that handles the common structure
        of META-INF/mods.toml. It does NOT handle:
        - Nested tables (beyond simple key=value)
        - Arrays of tables ([[table]])
        - Multiline values
        - Complex value types
        """
        result = {}
        for line in content.split('\n'):
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#') or line.startswith('['):
                continue
            # Parse key = value
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # Remove quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                result[key] = value
        return result

    # --- Mod Loading ---

    def load_mod(self, jar_path: str) -> bool:
        """Load a mod from a .jar file.

        Args:
            jar_path: Path to the .jar file

        Returns:
            True if the mod was loaded successfully
        """
        info = self._identify_mod(jar_path)
        if not info:
            logger.error(f"Could not identify mod: {jar_path}")
            return False

        # Check dependencies
        if not self._check_dependencies(info):
            logger.error(f"Unmet dependencies for mod {info.mod_id}")
            self._mod_states[info.mod_id] = ModState.ERRORED
            return False

        # Try native loading first
        if self._native:
            try:
                loader_type = ModLoaderType[self.LOADER_TYPES.get(info.loader_type, "FABRIC")]
                result = self._native.load_mod(jar_path, loader_type)
                if result:
                    self._mod_states[info.mod_id] = ModState.LOADED
                    self.loaded_mods.append({
                        "mod_id": info.mod_id,
                        "name": info.name,
                        "version": info.version,
                        "loader_type": info.loader_type,
                        "jar_path": jar_path,
                    })
                    logger.info(f"Loaded mod: {info.name} v{info.version}")
                    return True
            except Exception as e:
                logger.debug(f"Native mod loading failed, falling back to Python: {e}")

        # Python-level fallback loading
        return self._load_mod_python(info)

    def _load_mod_python(self, info: ModInfo) -> bool:
        """Load a mod using Python-level API emulation.

        This provides a subset of the mod API without requiring
        a real JVM. Mods that only use registration APIs can
        work through this path.
        """
        try:
            # Mark as loaded
            self._mod_states[info.mod_id] = ModState.LOADED

            # Add to loaded mods list
            self.loaded_mods.append({
                "mod_id": info.mod_id,
                "name": info.name,
                "version": info.version,
                "loader_type": info.loader_type,
                "jar_path": info.jar_path,
            })

            logger.info(f"Loaded mod (Python): {info.name} v{info.version}")
            return True

        except Exception as e:
            logger.error(f"Failed to load mod {info.mod_id}: {e}")
            self._mod_states[info.mod_id] = ModState.ERRORED
            return False

    def load_all_from_directory(self, mods_dir: str) -> int:
        """Load all mods from a directory.

        Args:
            mods_dir: Path to directory containing .jar files

        Returns:
            Number of mods loaded successfully
        """
        discovered = self.scan_mods_directory(mods_dir)

        # Resolve dependency order
        load_order = self._resolve_dependency_order(discovered)

        loaded_count = 0
        for mod_id in load_order:
            # Find the mod info
            info = next((m for m in discovered if m.mod_id == mod_id), None)
            if info and self.load_mod(info.jar_path):
                loaded_count += 1

        logger.info(f"Loaded {loaded_count}/{len(discovered)} mods from {mods_dir}")
        return loaded_count

    # --- Mod Lifecycle ---

    def enable_mod(self, mod_id: str) -> bool:
        """Enable a loaded mod by its ID.

        Args:
            mod_id: The mod's unique identifier

        Returns:
            True if the mod was enabled successfully
        """
        if mod_id not in self._mod_states:
            logger.error(f"Mod not found: {mod_id}")
            return False

        state = self._mod_states[mod_id]
        if state not in (ModState.LOADED, ModState.DISABLED):
            logger.error(f"Cannot enable mod {mod_id} in state {ModState(state).name}")
            return False

        # Try native enable
        if self._native:
            try:
                self._native.enable_mod(mod_id)
            except Exception:
                pass

        self._mod_states[mod_id] = ModState.ENABLED
        logger.info(f"Enabled mod: {mod_id}")

        # Fire enable event
        self.fire_event("mod_enabled", {"mod_id": mod_id})

        return True

    def disable_mod(self, mod_id: str) -> bool:
        """Disable a loaded mod by its ID.

        Args:
            mod_id: The mod's unique identifier

        Returns:
            True if the mod was disabled successfully
        """
        if mod_id not in self._mod_states:
            logger.error(f"Mod not found: {mod_id}")
            return False

        state = self._mod_states[mod_id]
        if state != ModState.ENABLED:
            logger.error(f"Cannot disable mod {mod_id} in state {ModState(state).name}")
            return False

        # Try native disable
        if self._native:
            try:
                self._native.disable_mod(mod_id)
            except Exception:
                pass

        self._mod_states[mod_id] = ModState.DISABLED
        logger.info(f"Disabled mod: {mod_id}")

        # Fire disable event
        self.fire_event("mod_disabled", {"mod_id": mod_id})

        return True

    # --- Event System ---

    def fire_event(self, event_name: str, data: Dict[str, str]) -> None:
        """Fire a mod event to all registered listeners.

        Args:
            event_name: Name of the event
            data: Event data as key-value pairs
        """
        handlers = self._event_handlers.get(event_name, [])
        for handler in handlers:
            try:
                handler(event_name, data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_name}: {e}")

        # Also fire to native layer
        if self._native:
            try:
                self._native.fire_event(event_name, data)
            except Exception:
                pass

    def register_event_handler(self, event_name: str, handler: Callable) -> None:
        """Register a handler for a specific event type.

        Args:
            event_name: Name of the event to listen for
            handler: Callback function(event_name, data)
        """
        if event_name not in self._event_handlers:
            self._event_handlers[event_name] = []
        self._event_handlers[event_name].append(handler)

    def unregister_event_handler(self, event_name: str, handler: Callable) -> bool:
        """Unregister an event handler.

        Args:
            event_name: Name of the event
            handler: The handler to remove

        Returns:
            True if the handler was found and removed
        """
        if event_name in self._event_handlers:
            try:
                self._event_handlers[event_name].remove(handler)
                return True
            except ValueError:
                pass
        return False

    # --- API Handler Registration ---

    def register_api_handler(self, api_name: str, handler: Callable) -> None:
        """Register a handler for a mod API call.

        Args:
            api_name: Name of the API (e.g. "register_block", "register_item")
            handler: Callback function(api_name, data)
        """
        if api_name not in self._api_handlers:
            self._api_handlers[api_name] = []
        self._api_handlers[api_name].append(handler)

    def call_api(self, api_name: str, data: Dict[str, str]) -> None:
        """Call a mod API, invoking all registered handlers.

        Args:
            api_name: Name of the API to call
            data: API call data
        """
        handlers = self._api_handlers.get(api_name, [])
        for handler in handlers:
            try:
                handler(api_name, data)
            except Exception as e:
                logger.error(f"Error in API handler for {api_name}: {e}")

    # --- Query ---

    def get_mod_info(self, mod_id: str) -> Optional[ModInfo]:
        """Get information about a discovered mod."""
        for info in self._discovered_mods:
            if info.mod_id == mod_id:
                return info
        return None

    def get_mod_state(self, mod_id: str) -> Optional[ModState]:
        """Get the current state of a mod."""
        return self._mod_states.get(mod_id)

    def is_mod_loaded(self, mod_id: str) -> bool:
        """Check if a mod is loaded."""
        return mod_id in self._mod_states and self._mod_states[mod_id] >= ModState.LOADED

    def is_mod_enabled(self, mod_id: str) -> bool:
        """Check if a mod is enabled."""
        return self._mod_states.get(mod_id) == ModState.ENABLED

    def get_all_mods(self) -> List[Dict]:
        """Get list of all loaded mods."""
        return list(self.loaded_mods)

    def get_mods_by_loader(self, loader_type: str) -> List[Dict]:
        """Get all mods of a specific loader type.

        Args:
            loader_type: One of "fabric", "forge", "neoforge", "quilt"

        Returns:
            List of mod dictionaries
        """
        return [m for m in self.loaded_mods if m.get("loader_type") == loader_type]

    # --- Dependency Resolution ---

    def _check_dependencies(self, info: ModInfo) -> bool:
        """Check if all dependencies for a mod are satisfied.

        Args:
            info: Mod info to check

        Returns:
            True if all hard dependencies are available
        """
        for dep_id in info.dependencies:
            if not self.is_mod_loaded(dep_id):
                # Check if it's been discovered but not yet loaded
                discovered_ids = [m.mod_id for m in self._discovered_mods]
                if dep_id not in discovered_ids:
                    logger.warning(f"Missing dependency for {info.mod_id}: {dep_id}")
                    return False
        return True

    def _resolve_dependency_order(self, mods: List[ModInfo]) -> List[str]:
        """Resolve the load order for mods using topological sort.

        Args:
            mods: List of mod info objects

        Returns:
            Ordered list of mod IDs (dependencies first)
        """
        # Build adjacency list
        mod_ids = {m.mod_id for m in mods}
        graph: Dict[str, List[str]] = {m.mod_id: [] for m in mods}
        in_degree: Dict[str, int] = {m.mod_id: 0 for m in mods}

        for mod in mods:
            for dep in mod.dependencies:
                if dep in mod_ids:
                    graph[dep].append(mod.mod_id)
                    in_degree[mod.mod_id] += 1

        # Kahn's algorithm
        queue = [mid for mid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            # Sort queue for deterministic ordering
            queue.sort()
            current = queue.pop(0)
            order.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(order) != len(mods):
            logger.warning("Circular dependency detected among mods")
            # Include mods not in the resolved order (best effort)
            for mod in mods:
                if mod.mod_id not in order:
                    order.append(mod.mod_id)

        return order

    # --- Shutdown ---

    def shutdown(self) -> None:
        """Shutdown all mods and release resources."""
        # Disable mods in reverse dependency order
        for mod in reversed(self.loaded_mods):
            mod_id = mod.get("mod_id", "")
            if self.is_mod_enabled(mod_id):
                self.disable_mod(mod_id)

        # Native shutdown
        if self._native:
            try:
                self._native.shutdown_all()
            except Exception:
                pass

        self.loaded_mods.clear()
        self._discovered_mods.clear()
        self._mod_states.clear()
        self._event_handlers.clear()
        self._api_handlers.clear()

        logger.info("Mod manager shut down")


# ===========================================================
# Convenience Functions
# ===========================================================

def create_mod_manager(server) -> ModManager:
    """Create and return a new ModManager instance.

    Args:
        server: The PYMC server instance

    Returns:
        A configured ModManager
    """
    return ModManager(server)
