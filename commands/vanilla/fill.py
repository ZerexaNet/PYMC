# ============================================================
# PyMC - /fill Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate, parse_fill_mode, parse_mask_mode


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, fill_box_detailed
        from handlers.play.blocks import _sync_world_edit

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 7:
            await ctx.reply("[PyMC] 用法: fill <x1> <y1> <z1> <x2> <y2> <z2> <方块> [模式]")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x1 = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y1 = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z1 = int(resolve_coordinate(parse_coordinate(args[2]), bz))
            x2 = int(resolve_coordinate(parse_coordinate(args[3]), bx))
            y2 = int(resolve_coordinate(parse_coordinate(args[4]), by))
            z2 = int(resolve_coordinate(parse_coordinate(args[5]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        block_state = resolve_block_state(args[6])
        if block_state is None:
            await ctx.reply(f"[PyMC] 未知方块: {args[6]}")
            return FAILURE

        # Check for fill mode and mask mode
        fill_mode = "replace"
        arg_index = 7
        if len(args) > arg_index:
            try:
                fill_mode = parse_fill_mode(args[arg_index])
                arg_index += 1
            except ValueError:
                # Might be a mask block for "replace" mode
                if args[arg_index].lower() != "replace":
                    fill_mode = args[arg_index].lower()
                arg_index += 1

        volume = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
        if volume > 32768:
            await ctx.reply(f"[PyMC] fill 范围过大: {volume} 个方块，当前上限 32768")
            return FAILURE

        changed, changed_chunks, changed_blocks = fill_box_detailed(
            ctx.server, x1, y1, z1, x2, y2, z2, block_state
        )

        await _sync_world_edit(ctx.server, changed_chunks, changed_blocks)
        await ctx.reply(f"[PyMC] 已填充 {changed} 个方块为 {args[6]}")
        return SUCCESS

    cmd = Command(
        name="fill",
        description="填充区域方块",
        usage="fill <x1> <y1> <z1> <x2> <y2> <z2> <方块> [模式]",
        permission="command.fill",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
