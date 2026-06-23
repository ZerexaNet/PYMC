# ============================================================
# PyMC - /forceload Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


# Force-loaded chunks
_forceloaded_chunks: set[tuple[int, int]] = {}  # Will be set reference per-world


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: forceload <add|remove|query> [<x> <z>]")
            return FAILURE

        action = args[0].lower()

        if action == "add":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: forceload add <区块X> <区块Z> [到区块X] [到区块Z]")
                return FAILURE
            try:
                cx = int(args[1])
                cz = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE

            if len(args) >= 5:
                try:
                    cx2 = int(args[3])
                    cz2 = int(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE
                # Add range
                count = 0
                for x in range(min(cx, cx2), max(cx, cx2) + 1):
                    for z in range(min(cz, cz2), max(cz, cz2) + 1):
                        _forceloaded_chunks.add((x, z))
                        count += 1
                await ctx.reply(f"[PyMC] 已强制加载 {count} 个区块")
            else:
                _forceloaded_chunks.add((cx, cz))
                await ctx.reply(f"[PyMC] 已强制加载区块 ({cx}, {cz})")
            return SUCCESS

        if action == "remove":
            if len(args) < 3:
                if len(args) >= 2 and args[1].lower() == "all":
                    count = len(_forceloaded_chunks)
                    _forceloaded_chunks.clear()
                    await ctx.reply(f"[PyMC] 已移除所有强制加载区块 ({count} 个)")
                    return SUCCESS
                await ctx.reply("[PyMC] 用法: forceload remove <区块X> <区块Z> | forceload remove all")
                return FAILURE
            try:
                cx = int(args[1])
                cz = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
            _forceloaded_chunks.discard((cx, cz))
            await ctx.reply(f"[PyMC] 已移除区块 ({cx}, {cz}) 的强制加载")
            return SUCCESS

        if action == "query":
            if _forceloaded_chunks:
                chunks = ", ".join(f"({x},{z})" for x, z in sorted(_forceloaded_chunks)[:20])
                more = f" ... 还有 {len(_forceloaded_chunks) - 20} 个" if len(_forceloaded_chunks) > 20 else ""
                await ctx.reply(f"[PyMC] 强制加载区块: {chunks}{more}")
            else:
                await ctx.reply("[PyMC] 没有强制加载的区块")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: forceload <add|remove|query> ...")
        return FAILURE

    cmd = Command(
        name="forceload",
        description="强制加载区块",
        usage="forceload <add|remove|query> [<区块X> <区块Z>]",
        permission="command.forceload",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
