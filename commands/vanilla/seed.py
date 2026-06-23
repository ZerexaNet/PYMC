# ============================================================
# PyMC - /seed Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        seed = ctx.server.config.get("level-seed", "")
        text = f"[PyMC] 世界种子: {seed if seed != '' else 0}"
        await ctx.reply(text)
        return SUCCESS

    cmd = Command(
        name="seed",
        description="显示世界种子",
        usage="seed",
        permission="command.seed",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
