# ============================================================
# PyMC - /weather Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_weather


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前天气: {ctx.server.weather}")
            return SUCCESS

        try:
            weather = parse_weather(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        ctx.server.weather = weather
        duration = 6000
        if len(args) >= 2:
            try:
                duration = int(args[1]) * 20  # Convert seconds to ticks
            except ValueError:
                pass

        await ctx.reply(f"[PyMC] 天气已设置为 {weather}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        return ["clear", "rain", "thunder"]

    cmd = Command(
        name="weather",
        description="设置天气",
        usage="weather <clear|rain|thunder> [持续时间(秒)]",
        permission="command.weather",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
