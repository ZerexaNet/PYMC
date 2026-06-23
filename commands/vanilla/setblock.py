# ============================================================
# PyMC - /setblock Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, set_world_block
        from handlers.play.blocks import _broadcast_block_change

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 4:
            await ctx.reply("[PyMC] 用法: setblock <x> <y> <z> <方块>")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z = int(resolve_coordinate(parse_coordinate(args[2]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        block_state = resolve_block_state(args[3])
        if block_state is None:
            await ctx.reply(f"[PyMC] 未知方块: {args[3]}")
            return FAILURE

        changed_chunks = set_world_block(ctx.server, x, y, z, block_state)
        if not changed_chunks:
            await ctx.reply("[PyMC] 方块位置超出世界范围")
            return FAILURE

        await _broadcast_block_change(ctx.server, x, y, z, block_state)
        await ctx.reply(f"[PyMC] 已设置方块 ({x}, {y}, {z}) -> {args[3]}")
        return SUCCESS

    cmd = Command(
        name="setblock",
        description="设置单个方块",
        usage="setblock <x> <y> <z> <方块>",
        permission="command.setblock",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
