# ============================================================
# PyMC - level.dat / session.lock
# ============================================================

"""
World metadata persistence in the vanilla ``level.dat`` layout.

``level.dat`` is a gzip-compressed NBT file whose root compound contains a
``Data`` compound. PyMC reads and writes the fields it actually tracks (spawn
point, world time, weather, game rules, seed, difficulty, default game mode),
using the same names and types as the vanilla 1.21.1 server so the file can be
inspected with any NBT editor.

``session.lock`` guards the world directory against being opened by two
server processes at once, like the vanilla server does.
"""

from __future__ import annotations

import gzip
import logging
import os
import time
from pathlib import Path

from protocol.nbt import NbtByte, NbtLong, NbtFloat, NbtDouble, decode_nbt, encode_nbt

logger = logging.getLogger("pymc.level")

DATA_VERSION = 3955           # 1.21.1
LEVEL_STORAGE_VERSION = 19133  # Anvil
VERSION_NAME = "1.21.1"

_GAMEMODE_IDS = {"survival": 0, "creative": 1, "adventure": 2, "spectator": 3}
_GAMEMODE_NAMES = {v: k for k, v in _GAMEMODE_IDS.items()}
_DIFFICULTY_IDS = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}
_DIFFICULTY_NAMES = {v: k for k, v in _DIFFICULTY_IDS.items()}


def _plain(value):
    """Strip the decoder's NBT wrapper objects, recursively."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return value.value
    if hasattr(value, "values") and not isinstance(value, dict):
        return list(value.values)
    return value


class LevelData:
    """In-memory view of the parts of level.dat that PyMC uses."""

    def __init__(self):
        self.level_name: str = "world"
        self.seed: int = 0
        self.spawn: tuple[int, int, int] | None = None
        self.spawn_angle: float = 0.0
        self.game_time: int = 0
        self.day_time: int = 0
        self.raining: bool = False
        self.thundering: bool = False
        self.rain_time: int = 0
        self.thunder_time: int = 0
        self.clear_weather_time: int = 0
        self.gamerules: dict[str, str] = {}
        self.difficulty: str | None = None
        self.gamemode: str | None = None
        self.hardcore: bool = False
        self.last_played: int = 0
        self.existed: bool = False

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, world_dir: str | os.PathLike) -> "LevelData":
        """Load ``<world>/level.dat`` (falls back to ``level.dat_old``)."""
        level = cls()
        world_dir = Path(world_dir)
        for name in ("level.dat", "level.dat_old"):
            path = world_dir / name
            if not path.exists():
                continue
            try:
                with gzip.open(path, "rb") as f:
                    raw = f.read()
                root, _ = decode_nbt(raw, 0, with_type=True, with_name=True)
                level._apply(_plain(root or {}).get("Data", {}))
                level.existed = True
                return level
            except Exception as e:
                logger.error(f"Exception reading {path}: {e}")
        return level

    def _apply(self, data: dict) -> None:
        self.level_name = str(data.get("LevelName", self.level_name))
        if all(k in data for k in ("SpawnX", "SpawnY", "SpawnZ")):
            self.spawn = (int(data["SpawnX"]), int(data["SpawnY"]), int(data["SpawnZ"]))
        self.spawn_angle = float(data.get("SpawnAngle", 0.0))
        self.game_time = int(data.get("Time", 0))
        self.day_time = int(data.get("DayTime", self.game_time))
        self.raining = bool(data.get("raining", 0))
        self.thundering = bool(data.get("thundering", 0))
        self.rain_time = int(data.get("rainTime", 0))
        self.thunder_time = int(data.get("thunderTime", 0))
        self.clear_weather_time = int(data.get("clearWeatherTime", 0))
        self.hardcore = bool(data.get("hardcore", 0))
        self.last_played = int(data.get("LastPlayed", 0))
        if "Difficulty" in data:
            self.difficulty = _DIFFICULTY_NAMES.get(int(data["Difficulty"]))
        if "GameType" in data:
            self.gamemode = _GAMEMODE_NAMES.get(int(data["GameType"]))
        rules = data.get("GameRules", {})
        if isinstance(rules, dict):
            self.gamerules = {str(k): str(v) for k, v in rules.items()}
        seed = (data.get("WorldGenSettings") or {}).get("seed")
        if seed is None:
            seed = data.get("RandomSeed")
        if seed is not None:
            self.seed = int(seed)

    # ------------------------------------------------------------------

    def to_nbt(self) -> dict:
        spawn = self.spawn or (0, 64, 0)
        data = {
            "DataVersion": DATA_VERSION,
            "version": LEVEL_STORAGE_VERSION,
            "Version": {
                "Id": DATA_VERSION,
                "Name": VERSION_NAME,
                "Series": "main",
                "Snapshot": NbtByte(0),
            },
            "LevelName": self.level_name,
            "ServerBrands": ["PyMC"],
            "WasModded": NbtByte(1),
            "initialized": NbtByte(1),
            "allowCommands": NbtByte(1),
            "hardcore": NbtByte(1 if self.hardcore else 0),
            "Difficulty": NbtByte(_DIFFICULTY_IDS.get(self.difficulty or "easy", 1)),
            "DifficultyLocked": NbtByte(0),
            "GameType": _GAMEMODE_IDS.get(self.gamemode or "survival", 0),
            "SpawnX": int(spawn[0]),
            "SpawnY": int(spawn[1]),
            "SpawnZ": int(spawn[2]),
            "SpawnAngle": NbtFloat(self.spawn_angle),
            "Time": NbtLong(int(self.game_time)),
            "DayTime": NbtLong(int(self.day_time)),
            "LastPlayed": NbtLong(int(time.time() * 1000)),
            "raining": NbtByte(1 if self.raining else 0),
            "thundering": NbtByte(1 if self.thundering else 0),
            "rainTime": int(self.rain_time),
            "thunderTime": int(self.thunder_time),
            "clearWeatherTime": int(self.clear_weather_time),
            "GameRules": {k: str(v) for k, v in sorted(self.gamerules.items())},
            "WorldGenSettings": {
                "seed": NbtLong(int(self.seed)),
                "generate_features": NbtByte(1),
                "bonus_chest": NbtByte(0),
            },
            "BorderCenterX": NbtDouble(0.0),
            "BorderCenterZ": NbtDouble(0.0),
            "BorderSize": NbtDouble(59999968.0),
        }
        return {"Data": data}

    def save(self, world_dir: str | os.PathLike) -> None:
        """Atomically write level.dat, keeping the previous file as level.dat_old."""
        world_dir = Path(world_dir)
        world_dir.mkdir(parents=True, exist_ok=True)
        path = world_dir / "level.dat"
        tmp = world_dir / "level.dat_new"
        raw = encode_nbt(self.to_nbt(), with_type=True, root_name="")
        with gzip.open(tmp, "wb") as f:
            f.write(raw)
        if path.exists():
            try:
                path.replace(world_dir / "level.dat_old")
            except OSError:
                pass
        tmp.replace(path)


class SessionLockError(RuntimeError):
    pass


class SessionLock:
    """``session.lock``: exclusive lock on a world directory."""

    def __init__(self, world_dir: str | os.PathLike):
        self.path = Path(world_dir) / "session.lock"
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            handle.close()
            raise SessionLockError(
                f"{self.path}: already locked (possibly by other Minecraft instance?)"
            ) from e
        handle.seek(0)
        handle.truncate()
        handle.write("☃".encode("utf-8"))  # snowman, like vanilla
        handle.flush()
        self._file = handle

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
