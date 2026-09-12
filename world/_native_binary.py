# ============================================================
# PyMC - Cross-platform native executable detection helper
# ============================================================

"""跨平台原生可执行文件识别。

Git 仓库中同时提交了 Linux ELF 与 Windows PE 产物。如果只看
文件名，macOS (或 ARM Linux) 会选中错误格式/架构的二进制，
启动时触发 ``[Errno 8] Exec format error``。这里根据当前平台
校验文件 magic 和 CPU 架构。
"""

from __future__ import annotations

import os
import platform
import struct
import sys
from pathlib import Path

# Mach-O fat/universal binary magics.
_MACHO_FAT_MAGICS = {
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM
    b"\xca\xfe\xba\xbf",  # FAT_MAGIC_64
    b"\xbf\xba\xfe\xca",  # FAT_CIGAM_64
}

# Mach-O thin binary magics.
_MACHO_THIN_MAGICS = {
    b"\xfe\xed\xfa\xce",  # MH_MAGIC
    b"\xce\xfa\xed\xfe",  # MH_CIGAM
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64
    b"\xcf\xfa\xed\xfe",  # MH_CIGAM_64
}

# Mach-O cpu_type_t values used by the architectures we care about.
_MACHO_CPU = {
    "x86": {0x00000007},
    "x86_64": {0x01000007},
    "arm": {0x0000000C},
    "arm64": {0x0100000C},
}

# ELF e_machine values.
_ELF_MACHINE = {
    "x86": {3},        # EM_386
    "x86_64": {62},    # EM_X86_64
    "arm": {40},       # EM_ARM
    "arm64": {183},    # EM_AARCH64
    "riscv64": {243},  # EM_RISCV
    "ppc64": {21},     # EM_PPC64
    "ppc64le": {21},
    "s390x": {22},     # EM_S390
    "loongarch64": {258},  # EM_LOONGARCH
}


def _normalized_machine() -> str:
    """Normalize ``platform.machine()`` to a small architecture key."""
    machine = (platform.machine() or "").strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "x32": "x86",
        "aarch64": "arm64",
        "arm64e": "arm64",
        "armv6l": "arm",
        "armv7l": "arm",
        "powerpc": "ppc64",
        "powerpc64": "ppc64",
        "powerpc64le": "ppc64le",
        "riscv64gc": "riscv64",
    }
    return aliases.get(machine, machine)


def _is_compatible_macho(path: Path) -> bool:
    """Return True when *path* is a Mach-O executable for this Mac."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        return False

    magic = header[:4]
    if magic in _MACHO_FAT_MAGICS:
        # Universal binaries contain multiple slices. The OS loader can
        # select a compatible one, so accept them without further parsing.
        return True
    if magic not in _MACHO_THIN_MAGICS:
        return False

    if magic == b"\xfe\xed\xfa\xcf":  # MH_MAGIC_64 (big endian)
        endian = ">"
    elif magic == b"\xcf\xfa\xed\xfe":  # MH_CIGAM_64 (little endian)
        endian = "<"
    elif magic == b"\xfe\xed\xfa\xce":  # MH_MAGIC (big endian)
        endian = ">"
    else:  # MH_CIGAM (little endian)
        endian = "<"

    try:
        cpu_type = struct.unpack_from(endian + "I", header, 4)[0]
    except struct.error:
        return False

    expected = _MACHO_CPU.get(_normalized_machine())
    if expected is None:
        return True
    return cpu_type in expected


def _is_compatible_elf(path: Path) -> bool:
    """Return True when *path* is an ELF executable for this Unix host."""
    try:
        with open(path, "rb") as f:
            header = f.read(20)
    except OSError:
        return False

    if len(header) < 20 or header[:4] != b"\x7fELF":
        return False

    expected = _ELF_MACHINE.get(_normalized_machine())
    if expected is None:
        return True

    data_encoding = header[5]
    if data_encoding == 1:
        endian = "<"
    elif data_encoding == 2:
        endian = ">"
    else:
        return True

    try:
        machine = struct.unpack_from(endian + "H", header, 18)[0]
    except struct.error:
        return True
    return machine in expected


def is_runnable_native_binary(path: str | Path) -> bool:
    """Check that *path* is an executable native binary for the current OS.

    Windows requires a PE (``MZ``) file. macOS accepts compatible Mach-O
    slices, and Linux/Unix-like systems accept a compatible ELF. This
    prevents the Python bridge from selecting a committed Linux binary on
    macOS or a Windows binary on Linux.
    """
    candidate = Path(path)
    try:
        if not candidate.exists() or not candidate.is_file():
            return False
    except OSError:
        return False

    if os.name == "nt":
        try:
            with open(candidate, "rb") as f:
                return f.read(2) == b"MZ"
        except OSError:
            return False

    try:
        if not os.access(candidate, os.X_OK):
            return False
    except OSError:
        return False

    if sys.platform == "darwin":
        return _is_compatible_macho(candidate)
    return _is_compatible_elf(candidate)
