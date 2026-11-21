# ============================================================
# PyMC - Default Server Commands
# kick, ban, op, whitelist, stop, say, msg, me, etc.
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


def register(manager):
    # --- /say ---
    # --- /me ---
    # --- /msg ---
    # --- /kick ---
    # --- /ban ---
    # --- /pardon ---
    # --- /ban-ip ---
    # --- /pardon-ip ---
    # --- /banlist ---
    # --- /op ---
    # --- /deop ---
    # --- /whitelist ---
    # --- /stop ---
    # --- /reload ---
    async def _reload(ctx: CommandContext) -> int:
        ctx.server.permissions.load()
        await ctx.reply("[PyMC] 已重载权限与白名单配置")
        return SUCCESS

    cmd_reload = Command(name="reload", description="重载配置", usage="reload", permission="command.op")
    cmd_reload._execute_func = _reload
    manager.register(cmd_reload)

    # --- /save-all ---
    # --- /save-on / save-off ---
    # --- /defaultgamemode ---
    # --- /setworldspawn ---
    # --- /spawnpoint ---
    # --- /entities ---
    async def _entities(ctx: CommandContext) -> int:
        counts = ctx.server.entity_manager.count_by_kind()
        if not counts:
            await ctx.reply("[PyMC] 当前没有非玩家实体")
            return SUCCESS
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        await ctx.reply(f"[PyMC] 当前实体统计: {summary}")
        return SUCCESS

    cmd_ent = Command(name="entities", description="显示实体统计", usage="entities", permission="command.list")
    cmd_ent._execute_func = _entities
    manager.register(cmd_ent)

    # --- /group ---
    async def _group(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) == 1:
            groups = ", ".join(sorted(ctx.server.permissions.list_groups().keys()))
            await ctx.reply(f"[PyMC] 权限组: {groups}")
            return SUCCESS
        if len(tokens) >= 3:
            ctx.server.permissions.set_user_group(tokens[1], tokens[2])
            await ctx.reply(f"[PyMC] 已将 {tokens[1]} 设置为权限组 {tokens[2]}")
            return SUCCESS
        await ctx.reply("[PyMC] 用法: group <玩家> <组名>")
        return FAILURE

    cmd_group = Command(name="group", description="管理权限组", usage="group <玩家> <组名>", permission="command.op")
    cmd_group._execute_func = _group
    manager.register(cmd_group)

    # --- /perm ---
    async def _perm(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: perm <玩家>")
            return FAILURE
        level = ctx.server.permissions.get_permission_level(tokens[1])
        await ctx.reply(f"[PyMC] {tokens[1]} 的权限组: {level}")
        return SUCCESS

    cmd_perm = Command(name="perm", description="查看权限等级", usage="perm <玩家>", permission="command.op")
    cmd_perm._execute_func = _perm
    manager.register(cmd_perm)

    # --- /save-status ---
    async def _save_status(ctx: CommandContext) -> int:
        await ctx.reply(f"[PyMC] 自动保存状态: {'开启' if ctx.server.autosave_enabled else '关闭'}")
        return SUCCESS

    cmd_ss = Command(name="save-status", description="查看保存状态", usage="save-status", permission="command.list")
    cmd_ss._execute_func = _save_status
    manager.register(cmd_ss)
