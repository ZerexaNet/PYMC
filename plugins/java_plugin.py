# ============================================================
# PyMC - Java Bukkit/Paper plugin bridge (glue layer)
# ============================================================
"""Best-effort Java plugin support.

PyMC does not embed a JVM or reimplement the full Paper server, but it can
host a small in-process bridge process that:

  * loads ``.jar`` plugins with a real Paper API on the classpath,
  * calls ``JavaPlugin.onLoad/onEnable/onDisable``,
  * dispatches commands registered in ``plugin.yml``,
  * forwards broadcasts and simple events back to Python.

The bridge is intentionally a compatibility glue layer. Plugins that only
use the standard Paper ``JavaPlugin`` lifecycle, logger, simple commands and
basic server queries will work. Plugins that depend on unimplemented Paper
internals (NMS, complex world APIs, GUI constructors, ...) will fail with a
logged error instead of being silently ignored.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("pymc.plugins.java")

BRIDGE_DIR = Path(__file__).resolve().parent.parent / "native" / "plugins" / "java"
BRIDGE_JAR = BRIDGE_DIR / "pymc-bukkit-bridge.jar"
BRIDGE_SOURCE = BRIDGE_DIR / "PyMCBukkitBridge.java"
LIB_DIR = BRIDGE_DIR / "lib"


def find_java() -> str | None:
    """Return a usable ``java`` executable, if one is available."""
    candidate = os.environ.get("PYMC_JAVA") or "java"
    return shutil.which(candidate)


def discover_jar_plugins(plugins_dir: str | os.PathLike) -> list[Path]:
    """List Bukkit/Paper ``.jar`` candidates in the plugins directory."""
    root = Path(plugins_dir)
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.jar") if p.is_file())


def describe_jar(jar_path: str | os.PathLike) -> dict:
    """Read ``plugin.yml`` from a jar without invoking the JVM."""
    path = Path(jar_path)
    info = {"jar": str(path), "name": path.stem, "main": None, "version": "0.0.0"}
    try:
        with zipfile.ZipFile(path) as zf:
            if "plugin.yml" not in zf.namelist():
                return info
            for raw in zf.read("plugin.yml").decode("utf-8", errors="replace").splitlines():
                line = raw.strip()
                if line.startswith("#") or ":" not in line:
                    continue
                if not raw[:1].isspace():
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key in ("name", "main", "version"):
                        info[key] = value
    except Exception as e:
        logger.debug(f"Failed to read {path}: {e}")
    return info


def _jar_classpath() -> str:
    jars = [BRIDGE_JAR]
    if LIB_DIR.exists():
        jars.extend(sorted(LIB_DIR.glob("*.jar")))
    return os.pathsep.join(str(p.resolve()) for p in jars)


class JavaPluginBridge:
    """Small subprocess wrapper around ``PyMCBukkitBridge``."""

    def __init__(self, plugins_dir: str, on_broadcast: Callable[[str], None] | None = None):
        self.plugins_dir = Path(plugins_dir)
        self.on_broadcast = on_broadcast
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._events: list[dict] = []
        self._event_cv = threading.Condition(threading.Lock())
        self._reader: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        java = find_java()
        if java is None:
            logger.info("未找到 Java 运行时，跳过 Bukkit/Paper .jar 插件桥接")
            return False

        self._ensure_bridge_jar()
        if not BRIDGE_JAR.exists():
            logger.warning("Java 桥接 jar 不可用，跳过 Bukkit/Paper 插件")
            return False

        try:
            self._proc = subprocess.Popen(
                [java, "-Xmx256m", "-XX:MaxMetaspaceSize=192m",
                 "-cp", _jar_classpath(), "PyMCBukkitBridge", str(self.plugins_dir.resolve())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception as e:
            logger.warning(f"启动 Java 插件桥接失败: {e}")
            self._proc = None
            return False

        self._reader = threading.Thread(target=self._read_loop, name="PyMC-JavaPluginBridge", daemon=True)
        self._reader.start()

        ready = self._wait_event("ready", timeout=10.0)
        if ready is None:
            logger.error("Java 插件桥接子进程未就绪")
            self.stop()
            return False
        return True

    def _ensure_bridge_jar(self) -> None:
        if BRIDGE_JAR.exists():
            # Recompile when the source is newer than the shipped jar.
            try:
                if BRIDGE_SOURCE.exists() and BRIDGE_SOURCE.stat().st_mtime > BRIDGE_JAR.stat().st_mtime:
                    self._compile_bridge()
            except OSError:
                pass
            return
        self._compile_bridge()

    def _compile_bridge(self) -> None:
        javac = shutil.which("javac")
        if javac is None:
            logger.warning("未找到 javac，无法从源码编译 Java 桥接层")
            return
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        cp = os.pathsep.join(str(p) for p in sorted(LIB_DIR.glob("*.jar")))
        build_dir = BRIDGE_DIR / "build"
        try:
            import shutil as _shutil
            _shutil.rmtree(build_dir, ignore_errors=True)
            build_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [javac, "-d", str(build_dir), "-cp", cp, str(BRIDGE_SOURCE)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.error(f"Java 桥接源码编译失败: {result.stderr or result.stdout}")
                return
            subprocess.run(
                ["jar", "cfe", str(BRIDGE_JAR), "PyMCBukkitBridge",
                 "-C", str(build_dir), "."],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except Exception as e:
            logger.warning(f"编译 Java 桥接层失败: {e}")

    def load_all(self) -> list[dict]:
        if self._proc is None and not self.start():
            return []
        if not self.available:
            return []
        self._clear_event("loaded")
        if not self._send({"cmd": "load_all"}):
            return []
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            event, data = self._wait_event("loaded", deadline - time.monotonic())
            if event is None:
                return []
            if isinstance(data, dict) and "plugins" in data:
                return data.get("plugins", [])
        return []

    def status(self) -> list[str]:
        if not self.available:
            return []
        _, data = self._request({"cmd": "status"}, "status", timeout=10.0)
        if isinstance(data, dict):
            return list(data.get("plugins", []))
        return []

    def dispatch_command(self, line: str) -> bool:
        if not self.available:
            return False
        event, data = self._request({"cmd": "dispatch", "line": line}, "dispatched", timeout=10.0)
        if event is None or not isinstance(data, dict):
            return False
        return bool(data.get("ok", False))

    def broadcast(self, message: str) -> None:
        if self.available:
            self._send({"cmd": "broadcast", "message": message})

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            self._send({"cmd": "shutdown"})
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except Exception:
                pass

    # ---------
    # ------------------------------------------------------------
    # Comm protocol helpers
    # ------------------------------------------------------------
    def _send(self, payload: dict) -> bool:
        if not self.available or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            return True
        except Exception:
            return False

    def _read_loop(self) -> None:
        assert self._proc is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            event = msg.get("event", "unknown")
            data = msg.get("data")
            if event == "broadcast" and self.on_broadcast is not None and isinstance(data, str):
                try:
                    self.on_broadcast(data)
                except Exception as e:
                    logger.debug(f"Java broadcast handler failed: {e}")
            elif event == "console" and isinstance(data, str):
                logger.info(f"[JavaPlugin] {data}")
            with self._event_cv:
                self._events.append((event, data))
                self._event_cv.notify_all()
        if self._proc and self._proc.stderr:
            stderr = self._proc.stderr.read()
            if stderr and stderr.strip():
                logger.debug("Java bridge stderr: %s", stderr.strip()[-4000:])

    def _request(self, payload: dict, expected_event: str, timeout: float = 10.0):
        self._clear_event(expected_event)
        if not self._send(payload):
            return None, None
        return self._wait_event(expected_event, timeout)

    def _clear_event(self, event: str) -> None:
        with self._event_cv:
            self._events = [item for item in self._events if item[0] != event]

    def _wait_event(self, event: str, timeout: float):
        deadline = time.monotonic() + timeout
        with self._event_cv:
            while True:
                for idx, item in enumerate(self._events):
                    if item[0] == event:
                        del self._events[idx]
                        return item
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, None
                self._event_cv.wait(remaining)

    def __del__(self):
        self.stop()
