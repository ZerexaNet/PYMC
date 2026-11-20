"""
Redstone entry point. The engine is the vanilla-accurate port in world.rs.
"""

from .chunk_io import STATE_ID_TO_BLOCK
from .rs import RedstoneEngine, is_redstone_block  # noqa: F401


def _get_block_name(block_state_id: int) -> str:
    return STATE_ID_TO_BLOCK.get(block_state_id, ("minecraft:air", {}))[0]


