# ============================================================
# PyMC - /list Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        players = ctx.server.get_online_players()
        names = ", ".join(p.username for p in players) if players else "无"
        await ctx.reply(f"[PyMC] 在线玩家 ({len(players)}/{ctx.server.max_players}): {names}")
        return SUCCESS

    cmd = Command(
        name="list",
        description="显示在线玩家列表",
        usage="list",
        permission="command.list",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
