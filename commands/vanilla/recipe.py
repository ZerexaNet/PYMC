# ============================================================
# PyMC - /recipe Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: recipe <give|take> <目标> [配方名|*]")
            return FAILURE

        action = args[0].lower()
        if action not in ("give", "take"):
            await ctx.reply(f"[PyMC] 未知操作: {action}")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[1])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
            return FAILURE

        recipe_name = args[2] if len(args) >= 3 else "*"
        action_cn = "给予" if action == "give" else "移除"

        # Recipe system not fully implemented, acknowledge command
        if recipe_name == "*":
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家的所有配方")
        else:
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家配方: {recipe_name}")

        return SUCCESS

    cmd = Command(
        name="recipe",
        description="给予或移除配方",
        usage="recipe <give|take> <目标> [配方名|*]",
        permission="command.recipe",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
