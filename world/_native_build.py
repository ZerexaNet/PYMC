# ============================================================
# PyMC - Build the native terrain generator from source
# ============================================================

"""
Compile ``native/terrain_gen.cpp`` with the local C++ compiler.

Used when no up-to-date terrain_gen binary is present (fresh checkout,
outdated release binary). The result is cached in ``build/native``; it is
rebuilt automatically whenever a generator source file is newer.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("pymc.native_build")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "native" / "terrain_gen.cpp"


def build_cache_dir() -> Path:
    return ROOT / "build" / "native"


def _sources() -> list[Path]:
    files = [SOURCE]
    worldgen = ROOT / "native" / "worldgen"
    if worldgen.is_dir():
        files.extend(sorted(worldgen.glob("*.h")))
    return files


def _compilers() -> list[list[str]]:
    if os.name == "nt":
        found = []
        if shutil.which("cl"):
            found.append(["cl"])
        for cxx in ("g++", "clang++"):
            if shutil.which(cxx):
                found.append([cxx])
        return found
    names = [os.environ.get("CXX", ""), "c++", "g++", "clang++"]
    return [[n] for n in names if n and shutil.which(n)]


def build_native_generator(force: bool = False) -> str | None:
    """Compile terrain_gen; returns the binary path or None."""
    if not SOURCE.exists():
        return None
    out_dir = build_cache_dir()
    binary = out_dir / ("terrain_gen.exe" if os.name == "nt" else "terrain_gen")
    newest_source = max(p.stat().st_mtime for p in _sources())
    if binary.exists() and not force and binary.stat().st_mtime >= newest_source:
        return str(binary)

    compilers = _compilers()
    if not compilers:
        logger.info("No C++ compiler found; cannot build the native terrain generator")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    for compiler in compilers:
        if compiler[0] == "cl":
            cmd = ["cl", "/nologo", "/O2", "/EHsc", "/std:c++17", "/fp:precise", "/DNOMINMAX",
                   f"/Fe:{binary}", str(SOURCE)]
        else:
            cmd = compiler + ["-O2", "-std=c++17", "-ffp-contract=off", "-pthread", "-o", str(binary), str(SOURCE)]
            if sys.platform == "win32":
                cmd.insert(-2, "-static")
        logger.info("Building the native terrain generator (one-time, ~10-30 s)...")
        try:
            result = subprocess.run(cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"{compiler[0]} failed: {e}")
            continue
        if result.returncode == 0 and binary.exists():
            logger.info(f"Native terrain generator built: {binary}")
            return str(binary)
        logger.warning(f"Building terrain_gen with {compiler[0]} failed:\n"
                       + result.stdout.decode("utf-8", errors="replace")[-2000:])
    return None
