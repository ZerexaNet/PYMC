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


# ------------------------------------------------------------------
# In-process engine library (redstone / block updates, hoppers, explosions)
# ------------------------------------------------------------------

VANILLA_DIR = ROOT / "native" / "vanilla"
VANILLA_SOURCE = VANILLA_DIR / "api.cpp"


def vanilla_library_name() -> str:
    if os.name == "nt":
        return "pymc_vanilla.dll"
    if sys.platform == "darwin":
        return "libpymc_vanilla.dylib"
    return "libpymc_vanilla.so"


def _vanilla_sources() -> list[Path]:
    files = sorted(VANILLA_DIR.glob("*.h")) + [VANILLA_SOURCE, ROOT / "native" / "worldgen" / "json.h"]
    return [p for p in files if p.exists()]


def build_vanilla_library(force: bool = False) -> str | None:
    """Compile native/vanilla/api.cpp into a shared library; returns its path or None."""
    if not VANILLA_SOURCE.exists():
        return None
    out_dir = build_cache_dir()
    library = out_dir / vanilla_library_name()
    newest_source = max(p.stat().st_mtime for p in _vanilla_sources())
    if library.exists() and not force and library.stat().st_mtime >= newest_source:
        return str(library)
    compilers = _compilers()
    if not compilers:
        logger.info("No C++ compiler found; the Python redstone engine will be used")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    # build to a temporary name: a loaded library must not be overwritten in place
    tmp = out_dir / ("tmp_" + str(os.getpid()) + "_" + library.name)
    for compiler in compilers:
        if compiler[0] == "cl":
            cmd = ["cl", "/nologo", "/O2", "/EHsc", "/std:c++17", "/LD", "/MT", "/DNOMINMAX",
                   f"/Fe:{tmp}", str(VANILLA_SOURCE)]
        else:
            cmd = compiler + ["-O2", "-std=c++17", "-shared", "-fPIC", "-fvisibility=hidden", "-o", str(tmp),
                              str(VANILLA_SOURCE)]
            if sys.platform == "win32":
                cmd[1:1] = ["-static-libgcc", "-static-libstdc++", "-static"]
        logger.info("Building the native redstone/hopper/explosion engine (one-time, ~10 s)...")
        try:
            result = subprocess.run(cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"{compiler[0]} failed: {e}")
            continue
        if result.returncode == 0 and tmp.exists():
            try:
                os.replace(tmp, library)
            except OSError:
                return str(tmp)      # the old library is in use (Windows): use the new one under its temp name
            logger.info(f"Native engine built: {library}")
            return str(library)
        logger.warning(f"Building the native engine with {compiler[0]} failed:\n"
                       + result.stdout.decode("utf-8", errors="replace")[-2000:])
    return None
