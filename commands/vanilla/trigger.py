# ============================================================
# PyMC - /trigger Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.vanilla.scoreboard import get_scoreboard_manager


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        sb = get_scoreboard_manager()

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: trigger <目标> [add|set] <值>")
            return FAILURE

        objective = args[0]

        if objective not in sb.objectives:
            await ctx.reply(f"[PyMC] 目标 '{objective}' 不存在或不是 trigger 类型")
            return FAILURE

        # Get player name
        if ctx.sender is None:
            await ctx.reply("[PyMC] 控制台无法使用 trigger 命令")
            return FAILURE
        player = ctx.sender.username

        action = "add"
        value = 1

        if len(args) >= 2:
            action = args[1].lower()
            if action in ("add", "set"):
                if len(args) >= 3:
                    try:
                        value = int(args[2])
                    except ValueError:
                        await ctx.reply("[PyMC] 值格式无效")
                        return FAILURE
            else:
                # First arg after objective is the value (implicit add)
                try:
                    value = int(args[1])
                    action = "add"
                except ValueError:
                    await ctx.reply("[PyMC] 用法: trigger <目标> [add|set] <值>")
                    return FAILURE

        if action == "add":
            new_score = sb.add_score(objective, player, value)
        else:
            new_score = value
            sb.set_score(objective, player, value)

        await ctx.reply(f"[PyMC] {objective} for {player}: {new_score}")
        return SUCCESS

    cmd = Command(
        name="trigger",
        description="修改 trigger 类型记分板目标",
        usage="trigger <目标> [add|set] <值>",
        permission="command.trigger",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
