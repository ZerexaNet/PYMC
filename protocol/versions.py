# ============================================================
# PyMC - 多版本协议支持
# 协议版本号到 Minecraft 版本的映射
# ============================================================

"""
Protocol version mapping for multi-version support.
Maps protocol version numbers to human-readable Minecraft version info.
"""

# Map of protocol version -> version info
PROTOCOL_VERSIONS = {
    47:  {"name": "1.8.9",   "major": "1.8"},
    340: {"name": "1.12.2",  "major": "1.12"},
    404: {"name": "1.13.2",  "major": "1.13"},
    498: {"name": "1.14.4",  "major": "1.14"},
    578: {"name": "1.15.2",  "major": "1.15"},
    736: {"name": "1.16.1",  "major": "1.16"},
    754: {"name": "1.16.2",  "major": "1.16"},
    757: {"name": "1.17.1",  "major": "1.17"},
    758: {"name": "1.18.2",  "major": "1.18"},
    761: {"name": "1.19.2",  "major": "1.19"},
    764: {"name": "1.19.3",  "major": "1.19"},
    765: {"name": "1.19.4",  "major": "1.19"},
    766: {"name": "1.20.1",  "major": "1.20"},
    767: {"name": "1.21.1",  "major": "1.21"},
    770: {"name": "1.21.4",  "major": "1.21"},
}

# All supported protocol versions (in order)
SUPPORTED_VERSIONS = [47, 340, 404, 498, 578, 736, 754, 757, 758, 761, 764, 765, 766, 767, 770]

# Default / native protocol version
NATIVE_PROTOCOL_VERSION = 767
NATIVE_VERSION_NAME = "1.21.1"

# Version capability flags
HAS_CONFIGURATION_PHASE = set()      # 1.20.2+ (protocol 764+)
HAS_CHAT_SIGNING = set()             # 1.19+ (protocol 759+)
HAS_WORLD_HEIGHT_384 = set()         # 1.17+ (protocol 755+)
HAS_FLATTENING = set()               # 1.13+ (protocol 393+)
HAS_DIMENSION_REGISTRY = set()       # 1.16+ (protocol 701+)

for pv in SUPPORTED_VERSIONS:
    if pv >= 764:
        HAS_CONFIGURATION_PHASE.add(pv)
    if pv >= 757:
        HAS_CHAT_SIGNING.add(pv)
    if pv >= 757:
        HAS_WORLD_HEIGHT_384.add(pv)
    if pv >= 404:
        HAS_FLATTENING.add(pv)
    if pv >= 736:
        HAS_DIMENSION_REGISTRY.add(pv)


def get_version_info(protocol_version: int) -> dict | None:
    """Get version info for a protocol version, or None if not supported."""
    return PROTOCOL_VERSIONS.get(protocol_version)


def is_supported(protocol_version: int) -> bool:
    """Check if a protocol version is supported."""
    return protocol_version in PROTOCOL_VERSIONS


def get_version_name(protocol_version: int) -> str:
    """Get human-readable version name for a protocol version."""
    info = PROTOCOL_VERSIONS.get(protocol_version)
    if info:
        return info["name"]
    return f"Unknown ({protocol_version})"


def get_major_version(protocol_version: int) -> str:
    """Get major version string (e.g. '1.21') for a protocol version."""
    info = PROTOCOL_VERSIONS.get(protocol_version)
    if info:
        return info["major"]
    return "unknown"


def has_configuration_phase(protocol_version: int) -> bool:
    """Check if this protocol version uses the configuration phase (1.20.2+)."""
    return protocol_version in HAS_CONFIGURATION_PHASE


def has_world_height_384(protocol_version: int) -> bool:
    """Check if this protocol version supports 384-height world (1.17+)."""
    return protocol_version in HAS_WORLD_HEIGHT_384


def has_flattening(protocol_version: int) -> bool:
    """Check if this protocol version uses the flattened block state IDs (1.13+)."""
    return protocol_version in HAS_FLATTENING


def get_closest_supported_version(protocol_version: int) -> int | None:
    """
    Find the closest supported protocol version for an unsupported version.
    Returns the nearest supported version, or None if completely out of range.
    """
    if protocol_version in PROTOCOL_VERSIONS:
        return protocol_version

    # Find the closest lower supported version
    best = None
    for pv in SUPPORTED_VERSIONS:
        if pv <= protocol_version:
            best = pv
        else:
            break
    return best


def get_handler_version(protocol_version: int) -> str:
    """
    Get the version handler identifier for a given protocol version.
    Returns a string like 'v1_8', 'v1_13', 'v1_17', 'v1_19', 'v1_20', 'v1_21'.
    """
    if protocol_version >= 767:
        return "v1_21"
    elif protocol_version >= 764:
        return "v1_20"
    elif protocol_version >= 757:
        return "v1_17"
    elif protocol_version >= 736:
        return "v1_16"
    elif protocol_version >= 498:
        return "v1_14"
    elif protocol_version >= 404:
        return "v1_13"
    elif protocol_version >= 340:
        return "v1_12"
    else:
        return "v1_8"


def filter_supported_versions(version_list: list[int] | str,
                              min_version: int = 0,
                              max_version: int = 999) -> list[int]:
    """
    Filter and return supported protocol versions within a range.

    Args:
        version_list: List of protocol versions, or "all"
        min_version: Minimum allowed protocol version (inclusive)
        max_version: Maximum allowed protocol version (inclusive)
    """
    if version_list == "all":
        return [pv for pv in SUPPORTED_VERSIONS
                if min_version <= pv <= max_version]

    result = []
    for pv in version_list:
        if isinstance(pv, int) and pv in PROTOCOL_VERSIONS:
            if min_version <= pv <= max_version:
                result.append(pv)
    return sorted(set(result))
