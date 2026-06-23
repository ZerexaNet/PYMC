# ============================================================
# PyMC - /clone Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate, parse_mask_mode, parse_clone_mode


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, clone_box_detailed
        from handlers.play.blocks import _sync_world_edit

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 9:
            await ctx.reply("[PyMC] 用法: clone <x1> <y1> <z1> <x2> <y2> <z2> <x> <y> <z> [replace|masked|filtered] [normal|force|move]")
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
            dest_x = int(resolve_coordinate(parse_coordinate(args[6]), bx))
            dest_y = int(resolve_coordinate(parse_coordinate(args[7]), by))
            dest_z = int(resolve_coordinate(parse_coordinate(args[8]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        volume = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
        if volume > 32768:
            await ctx.reply(f"[PyMC] clone 范围过大: {volume} 个方块，当前上限 32768")
            return FAILURE

        mask_mode = "replace"
        clone_mode = "normal"
        filter_block_state = None
        arg_index = 9

        if len(args) > arg_index:
            option = args[arg_index].lower()
            if option in ("replace", "masked"):
                mask_mode = option
                arg_index += 1
            elif option == "filtered":
                if len(args) <= arg_index + 1:
                    await ctx.reply("[PyMC] 用法: clone ... filtered <方块> [normal|force|move]")
                    return FAILURE
                mask_mode = "filtered"
                filter_block_state = resolve_block_state(args[arg_index + 1])
                if filter_block_state is None:
                    await ctx.reply(f"[PyMC] 未知方块: {args[arg_index + 1]}")
                    return FAILURE
                arg_index += 2

        if len(args) > arg_index:
            try:
                clone_mode = parse_clone_mode(args[arg_index])
            except ValueError:
                await ctx.reply("[PyMC] clone 模式必须是 normal、force 或 move")
                return FAILURE

        try:
            changed, changed_chunks, changed_blocks = clone_box_detailed(
                ctx.server, x1, y1, z1, x2, y2, z2,
                dest_x, dest_y, dest_z,
                mask_mode=mask_mode,
                clone_mode=clone_mode,
                filter_block_state=filter_block_state,
            )
        except ValueError:
            await ctx.reply("[PyMC] 源区域与目标区域重叠，请使用 force 或 move")
            return FAILURE

        await _sync_world_edit(ctx.server, changed_chunks, changed_blocks)
        await ctx.reply(f"[PyMC] 已复制 {changed} 个方块到 ({dest_x}, {dest_y}, {dest_z})")
        return SUCCESS

    cmd = Command(
        name="clone",
        description="复制区域方块",
        usage="clone <x1> <y1> <z1> <x2> <y2> <z2> <x> <y> <z> [模式]",
        permission="command.clone",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
