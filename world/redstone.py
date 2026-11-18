"""
Redstone entry point. The engine is the vanilla-accurate port in world.rs;
the previous approximate engine is kept in world.redstone_legacy for reference.
"""

from .chunk_io import BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE, STATE_ID_TO_BLOCK
from .rs import RedstoneEngine, is_redstone_block  # noqa: F401


def _get_block_name(block_state_id: int) -> str:
    return STATE_ID_TO_BLOCK.get(block_state_id, ("minecraft:air", {}))[0]


def _get_block_props(block_state_id: int) -> dict:
    return STATE_ID_TO_BLOCK.get(block_state_id, ("minecraft:air", {}))[1]


def resolve_state_id(block_name: str, **properties) -> int:
    from .rs.core import with_props
    state = BLOCK_NAME_TO_DEFAULT_STATE.get(block_name, 0)
    return with_props(state, **properties) if properties else state
