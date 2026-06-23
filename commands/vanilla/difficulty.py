# ============================================================
# PyMC - /difficulty Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_difficulty


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前难度: {ctx.server.config.get('difficulty', 'normal')}")
            return SUCCESS

        try:
            diff_int, diff_name = parse_difficulty(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        ctx.server.config["difficulty"] = diff_name
        ctx.server.save_runtime_config()
        await ctx.reply(f"[PyMC] 难度已设置为 {diff_name}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        return ["peaceful", "easy", "normal", "hard"]

    cmd = Command(
        name="difficulty",
        description="设置游戏难度",
        usage="difficulty <peaceful|easy|normal|hard>",
        permission="command.difficulty",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
