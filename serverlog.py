# ============================================================
# PyMC - 日志系统 (原版服务端格式)
# ============================================================

"""
Console and file logging in the vanilla dedicated-server layout:

    [12:34:56] [Server thread/INFO]: Done (3.142s)! For help, type "help"

  * console: stdout, INFO and above (DEBUG when ``debug=true``)
  * file:    ``logs/latest.log``; on startup the previous ``latest.log`` is
             archived as ``logs/YYYY-MM-DD-N.log.gz`` exactly like vanilla.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

LOG_DIR = "logs"
LATEST_LOG = "latest.log"

_LEVEL_NAMES = {"WARNING": "WARN", "CRITICAL": "FATAL"}


class VanillaFormatter(logging.Formatter):
    """``[HH:MM:SS] [thread/LEVEL]: message``"""

    def format(self, record: logging.LogRecord) -> str:
        level = _LEVEL_NAMES.get(record.levelname, record.levelname)
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return f"[{stamp}] [{record.threadName}/{level}]: {message}"


def archive_latest_log(log_dir: str | os.PathLike = LOG_DIR) -> Path | None:
    """Compress an existing latest.log to ``<date>-<n>.log.gz``; returns the archive."""
    log_dir = Path(log_dir)
    latest = log_dir / LATEST_LOG
    if not latest.exists() or latest.stat().st_size == 0:
        return None
    date = time.strftime("%Y-%m-%d", time.localtime(latest.stat().st_mtime))
    index = 1
    while (log_dir / f"{date}-{index}.log.gz").exists():
        index += 1
    archive = log_dir / f"{date}-{index}.log.gz"
    try:
        with latest.open("rb") as src, gzip.open(archive, "wb") as dst:
            shutil.copyfileobj(src, dst)
        latest.unlink()
    except OSError:
        return None
    return archive


def setup_logging(debug: bool = False, log_dir: str | os.PathLike = LOG_DIR) -> None:
    """Install vanilla-style console + ``logs/latest.log`` handlers."""
    threading.main_thread().name = "Server thread"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    formatter = VanillaFormatter()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        archive_latest_log(log_dir)
        file_handler = logging.FileHandler(Path(log_dir) / LATEST_LOG, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        root.warning(f"Could not open {log_dir}/{LATEST_LOG} for writing: {e}")

    # asyncio 的调试噪声不属于服务端日志
    logging.getLogger("asyncio").setLevel(logging.WARNING)
