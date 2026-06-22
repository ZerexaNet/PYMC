# ============================================================
# PyMC - /time Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_time_value, TIME_PRESETS


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前时间: {ctx.server.world_time}")
            return SUCCESS

        action = args[0].lower()

        if action == "set" and len(args) >= 2:
            try:
                value = parse_time_value(args[1])
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间值: {args[1]}")
                return FAILURE
            ctx.server.world_time = value
            await ctx.reply(f"[PyMC] 世界时间已设置为 {value}")
            return SUCCESS

        if action == "add" and len(args) >= 2:
            try:
                value = parse_time_value(args[1])
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间值: {args[1]}")
                return FAILURE
            ctx.server.world_time += value
            await ctx.reply(f"[PyMC] 世界时间已变更为 {ctx.server.world_time}")
            return SUCCESS

        if action == "query":
            if len(args) >= 2 and args[1].lower() == "daytime":
                await ctx.reply(f"[PyMC] 白天时间: {ctx.server.world_time % 24000}")
            elif len(args) >= 2 and args[1].lower() == "day":
                await ctx.reply(f"[PyMC] 天数: {ctx.server.world_time // 24000}")
            else:
                await ctx.reply(f"[PyMC] 世界时间: {ctx.server.world_time}")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: time <set|add|query> <值>")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["set", "add", "query"]
        if len(tokens) == 3 and tokens[1] == "set":
            return list(TIME_PRESETS.keys())
        if len(tokens) == 3 and tokens[1] == "query":
            return ["daytime", "day", "gametime"]
        return []

    cmd = Command(
        name="time",
        description="设置或查询世界时间",
        usage="time <set|add|query> <值>",
        permission="command.time",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
