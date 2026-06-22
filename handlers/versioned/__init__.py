# ============================================================
# PyMC - 版本化协议处理器
# 为不同 Minecraft 版本提供协议差异处理
# ============================================================

"""
Version-specific protocol handlers.

Each handler knows how to:
- Build Join Game packets for its version
- Build Chunk Data packets for its version
- Provide correct packet ID mappings
- Handle version-specific login/config flow differences
"""

from handlers.versioned.base import VersionHandler
from handlers.versioned.v1_8 import VersionHandlerV1_8
from handlers.versioned.v1_12 import VersionHandlerV1_12
from handlers.versioned.v1_13 import VersionHandlerV1_13
from handlers.versioned.v1_14 import VersionHandlerV1_14
from handlers.versioned.v1_16 import VersionHandlerV1_16
from handlers.versioned.v1_17 import VersionHandlerV1_17
from handlers.versioned.v1_19 import VersionHandlerV1_19
from handlers.versioned.v1_20 import VersionHandlerV1_20
from handlers.versioned.v1_21 import VersionHandlerV1_21

# Map from handler version string -> handler class
HANDLER_MAP = {
    "v1_8": VersionHandlerV1_8,
    "v1_12": VersionHandlerV1_12,
    "v1_13": VersionHandlerV1_13,
    "v1_14": VersionHandlerV1_14,
    "v1_16": VersionHandlerV1_16,
    "v1_17": VersionHandlerV1_17,
    "v1_19": VersionHandlerV1_19,
    "v1_20": VersionHandlerV1_20,
    "v1_21": VersionHandlerV1_21,
}


def get_version_handler(protocol_version: int):
    """
    Get the appropriate version handler for a protocol version.

    Args:
        protocol_version: The client's protocol version

    Returns:
        An instance of the appropriate VersionHandler subclass
    """
    from protocol.versions import get_handler_version
    handler_key = get_handler_version(protocol_version)
    handler_class = HANDLER_MAP.get(handler_key, VersionHandlerV1_21)
    return handler_class()
