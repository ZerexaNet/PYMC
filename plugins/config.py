"""Per-plugin configuration system for PYMC plugins and mods.

Each plugin gets its own JSON config file under a shared config directory.
Atomic writes (temp file + rename) guard against partial/corrupt saves.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_GITIGNORE_CONTENT = "# Auto-generated — ignore all plugin config files\n*\n!.gitignore\n"


class PluginConfig:
    """Per-plugin configuration backed by a JSON file.

    Usage::

        cfg = PluginConfig("my_plugin")
        cfg.set_defaults({"max_players": 20, "motd": "Hello!"})
        cfg.load()           # reads from disk or creates with defaults
        cfg.get_int("max_players")  # -> 20
        cfg.set("motd", "Welcome!")
        cfg.save()           # writes only if dirty

    The config directory (default ``plugins_config/``) is created
    automatically on first use.  A ``.gitignore`` is placed inside it so
    plugin configs are not accidentally committed.
    """

    def __init__(self, plugin_id: str, config_dir: str = "plugins_config"):
        self._plugin_id = plugin_id
        self._config_dir = Path(config_dir)
        self._file = self._config_dir / f"{plugin_id}.json"
        self._data: Dict[str, Any] = {}
        self._defaults: Dict[str, Any] = {}
        self._dirty: bool = False

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    def set_defaults(self, defaults: Dict[str, Any]) -> None:
        """Set default values.  Existing keys in ``_defaults`` are **not**
        overwritten so that later calls cannot silently change previously
        declared defaults.
        """
        for key, value in defaults.items():
            if key not in self._defaults:
                self._defaults[key] = value

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load config from disk.  If the file is missing it is created
        from defaults.  Missing keys that have defaults are back-filled.
        """
        self._ensure_config_dir()

        if self._file.exists():
            try:
                text = self._file.read_text(encoding="utf-8")
                self._data = json.loads(text)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to read config for %r, starting fresh: %s",
                    self._plugin_id,
                    exc,
                )
                self._data = {}
        else:
            self._data = {}

        # Back-fill any defaults that are absent from the file.
        changed = False
        for key, value in self._defaults.items():
            if key not in self._data:
                self._data[key] = value
                changed = True

        if changed:
            self._dirty = True
            self._write_to_disk()  # persist the back-filled defaults

    def save(self) -> None:
        """Save config to disk if it has been modified since the last save."""
        if self._dirty:
            self._write_to_disk()
            self._dirty = False

    def reload(self) -> None:
        """Reload the config from disk (discards unsaved in-memory changes)."""
        self._dirty = False
        self._data = {}
        self.load()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value, falling back to *default*."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value.  Marked dirty so the next ``save()`` writes."""
        if self._data.get(key) != value:
            self._data[key] = value
            self._dirty = True

    # -- typed helpers --------------------------------------------------

    def get_int(self, key: str, default: int = 0) -> int:
        val = self._data.get(key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self._data.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self._data.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return default

    def get_str(self, key: str, default: str = "") -> str:
        val = self._data.get(key, default)
        return str(val) if val is not None else default

    def get_list(self, key: str, default: Optional[list] = None) -> list:
        val = self._data.get(key, default if default is not None else [])
        return list(val) if isinstance(val, (list, tuple)) else (default if default is not None else [])

    def get_section(self, key: str) -> Dict[str, Any]:
        """Get a nested dict section.  Returns an empty dict if missing or not a dict."""
        val = self._data.get(key, {})
        return val if isinstance(val, dict) else {}

    # -- metadata helpers -----------------------------------------------

    def has(self, key: str) -> bool:
        return key in self._data

    def remove(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
            self._dirty = True

    def keys(self) -> List[str]:
        return list(self._data.keys())

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def file_path(self) -> str:
        return str(self._file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_config_dir(self) -> None:
        """Create the config directory and .gitignore if they don't exist."""
        if not self._config_dir.exists():
            self._config_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self._config_dir / ".gitignore"
        if not gitignore.exists():
            try:
                gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")
            except OSError:
                logger.debug("Could not write .gitignore in %s", self._config_dir)

    def _write_to_disk(self) -> None:
        """Atomic write: temp file in the same dir, then ``os.replace``."""
        self._ensure_config_dir()
        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=f"{self._plugin_id}_",
                dir=str(self._config_dir),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fp:
                    json.dump(self._data, fp, indent=2, ensure_ascii=False)
                    fp.write("\n")
                os.replace(tmp_path, str(self._file))
            except BaseException:
                # Clean up the temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._dirty = False
        except OSError as exc:
            logger.error("Failed to save config for %r: %s", self._plugin_id, exc)
