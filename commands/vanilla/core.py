# ============================================================
# PyMC - Core Commands
# help, list, stop, reload, save-all, save-on, save-off
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


def register(manager):
    """Register all core server commands."""

    # --- /help ---
    async def _help(ctx: CommandContext) -> int:
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

        # Show available commands, grouped by category
        available = manager.get_commands_for_sender(ctx.sender)
        if ctx.sender is not None:
            level = ctx.server.permissions.get_permission_level(ctx.sender.username)
            await ctx.reply(f"[PyMC] 你的权限组: {level}")

        # Group by category
        categories: dict[str, list] = {}
        for cmd in sorted(available, key=lambda c: c.name):
            cat = getattr(cmd, 'category', 'general')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cmd)

        for cat_name, cmds in sorted(categories.items()):
            cmd_list = ", ".join(f"/{cmd.name}" for cmd in cmds)
            await ctx.reply(f"[PyMC] [{cat_name}] {cmd_list}")

        return SUCCESS

    def _help_suggest(ctx: CommandContext) -> list[str]:
        return [f"/{cmd.name}" for cmd in manager.get_commands_for_sender(ctx.sender)]

    cmd_help = Command(
        name="help",
        description="显示可用命令列表",
        usage="help [命令名]",
        aliases=["?"],
        permission="command.help",
        category="core",
    )
    cmd_help._execute_func = _help
    cmd_help._suggest_func = _help_suggest
    manager.register(cmd_help)

    # --- /list ---
    async def _list(ctx: CommandContext) -> int:
        players = ctx.server.get_online_players()
        names = ", ".join(p.username for p in players) if players else "无"
        await ctx.reply(f"[PyMC] 在线玩家 ({len(players)}/{ctx.server.max_players}): {names}")
        return SUCCESS

    cmd_list = Command(
        name="list",
        description="显示在线玩家列表",
        usage="list",
        permission="command.list",
        category="core",
    )
    cmd_list._execute_func = _list
    manager.register(cmd_list)

    # --- /stop ---
    async def _stop(ctx: CommandContext) -> int:
        if ctx.sender is not None:
            from handlers.play.chat import send_system_message
            await send_system_message(ctx.sender, "[PyMC] 正在关闭服务器...")
        ctx.server.broadcast_system_message("[PyMC] 服务器正在关闭...")
        import asyncio
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(ctx.server.stop()))
        return SUCCESS

    cmd_stop = Command(
        name="stop",
        description="停止服务器",
        usage="stop",
        permission="command.stop",
        category="core",
    )
    cmd_stop._execute_func = _stop
    manager.register(cmd_stop)

    # --- /reload ---
    async def _reload(ctx: CommandContext) -> int:
        ctx.server.permissions.load()
        await ctx.reply("[PyMC] 已重载权限与白名单配置")
        return SUCCESS

    cmd_reload = Command(
        name="reload",
        description="重载配置",
        usage="reload",
        permission="command.op",
        category="core",
    )
    cmd_reload._execute_func = _reload
    manager.register(cmd_reload)

    # --- /save-all ---
    async def _save_all(ctx: CommandContext) -> int:
        ctx.server.save_all_player_states()
        ctx.server.world_storage.flush()
        await ctx.reply("[PyMC] 世界与玩家数据已保存")
        return SUCCESS

    cmd_saveall = Command(
        name="save-all",
        description="保存所有数据",
        usage="save-all",
        permission="command.op",
        category="core",
    )
    cmd_saveall._execute_func = _save_all
    manager.register(cmd_saveall)

    # --- /save-on / save-off ---
    async def _save_toggle(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        cmd_name = tokens[0].lower()
        ctx.server.autosave_enabled = (cmd_name == "save-on")
        await ctx.reply(f"[PyMC] 自动保存已{'开启' if ctx.server.autosave_enabled else '关闭'}")
        return SUCCESS

    cmd_saveon = Command(
        name="save-on",
        description="开启自动保存",
        usage="save-on",
        permission="command.op",
        category="core",
    )
    cmd_saveon._execute_func = _save_toggle
    manager.register(cmd_saveon)

    cmd_saveoff = Command(
        name="save-off",
        description="关闭自动保存",
        usage="save-off",
        permission="command.op",
        category="core",
    )
    cmd_saveoff._execute_func = _save_toggle
    manager.register(cmd_saveoff)

    # --- /save-status ---
    async def _save_status(ctx: CommandContext) -> int:
        autosave = getattr(ctx.server, 'autosave_enabled', True)
        status = "开启" if autosave else "关闭"
        await ctx.reply(f"[PyMC] 自动保存状态: {status}")
        return SUCCESS

    cmd_savestatus = Command(
        name="save-status",
        description="查看保存状态",
        usage="save-status",
        permission="command.list",
        category="core",
    )
    cmd_savestatus._execute_func = _save_status
    manager.register(cmd_savestatus)
