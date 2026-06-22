# ============================================================
# PyMC - /help Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        cmd_name = ctx.arguments.get("command")
        if cmd_name:
            cmd = manager.get_command(cmd_name)
            if cmd:
                await ctx.reply(f"[PyMC] /{cmd.name}: {cmd.description}")
                if cmd.usage:
                    await ctx.reply(f"[PyMC] 用法: {cmd.usage}")
                return SUCCESS
            await ctx.reply(f"[PyMC] 未知命令: /{cmd_name}")
            return SUCCESS

        # Show available commands
        available = manager.get_commands_for_sender(ctx.sender)
        if ctx.sender is not None:
            level = ctx.server.permissions.get_permission_level(ctx.sender.username)
            await ctx.reply(f"[PyMC] 你的权限组: {level}")

        cmd_list = ", ".join(f"/{cmd.name}" for cmd in sorted(available, key=lambda c: c.name))
        await ctx.reply(f"[PyMC] 可用命令: {cmd_list}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        return [f"/{cmd.name}" for cmd in manager.get_commands_for_sender(ctx.sender)]

    cmd = Command(
        name="help",
        description="显示可用命令列表",
        usage="help [命令名]",
        aliases=["?"],
        permission="command.help",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
