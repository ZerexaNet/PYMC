# ============================================================
# PyMC - Server Administration Commands
# kick, ban, ban-ip, pardon, pardon-ip, op, deop, whitelist,
# say, me, msg
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    """Register all server administration commands."""

    # --- /say ---
    async def _say(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: say <消息>")
            return FAILURE
        message = ' '.join(tokens[1:])
        full_text = f"[Server] {message}"
        ctx.server.broadcast_system_message(full_text)
        return SUCCESS

    cmd_say = Command(
        name="say",
        description="广播服务器消息",
        usage="say <消息>",
        permission="command.say",
        category="server",
    )
    cmd_say._execute_func = _say
    manager.register(cmd_say)

    # --- /me ---
    async def _me(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: /me <动作>")
            return FAILURE
        action = ' '.join(tokens[1:])
        ctx.server.broadcast_system_message(f"* {ctx.source_name} {action}")
        return SUCCESS

    cmd_me = Command(
        name="me",
        description="发送动作消息",
        usage="me <动作>",
        permission="command.me",
        category="server",
    )
    cmd_me._execute_func = _me
    manager.register(cmd_me)

    # --- /msg ---
    async def _msg(ctx: CommandContext) -> int:
        from handlers.play.chat import send_system_message

        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 3:
            await ctx.reply("[PyMC] 用法: /msg <玩家> <消息>")
            return FAILURE

        target = ctx.server.find_player(tokens[1])
        if target is None:
            await ctx.reply(f"[PyMC] 未找到玩家: {tokens[1]}")
            return FAILURE

        message = ' '.join(tokens[2:])
        await send_system_message(target, f"[私聊] {ctx.source_name}: {message}")
        if ctx.sender is not None and target != ctx.sender:
            await send_system_message(ctx.sender, f"[私聊 -> {target.username}] {message}")
        return SUCCESS

    cmd_msg = Command(
        name="msg",
        description="发送私聊消息",
        usage="msg <玩家> <消息>",
        aliases=["tell", "w"],
        permission="command.msg",
        category="server",
    )
    cmd_msg._execute_func = _msg
    manager.register(cmd_msg)

    # --- /kick ---
    async def _kick(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: kick <玩家> [原因]")
            return FAILURE

        target = ctx.server.find_player(tokens[1])
        if target is None:
            await ctx.reply(f"[PyMC] 未找到玩家: {tokens[1]}")
            return FAILURE

        reason = ' '.join(tokens[2:]) if len(tokens) >= 3 else "已被管理员移出服务器"
        await target.disconnect(reason)
        await ctx.reply(f"[PyMC] 已踢出 {target.username}: {reason}")
        return SUCCESS

    cmd_kick = Command(
        name="kick",
        description="踢出玩家",
        usage="kick <玩家> [原因]",
        permission="command.kick",
        category="server",
    )
    cmd_kick._execute_func = _kick
    manager.register(cmd_kick)

    # --- /ban ---
    async def _ban(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: ban <玩家> [原因]")
            return FAILURE

        reason = ' '.join(tokens[2:]) if len(tokens) >= 3 else ""
        ctx.server.permissions.ban_player(tokens[1], reason)
        target = ctx.server.find_player(tokens[1])
        if target is not None:
            await target.disconnect(reason or "你已被封禁")
        await ctx.reply(f"[PyMC] 已封禁玩家: {tokens[1]}")
        return SUCCESS

    cmd_ban = Command(
        name="ban",
        description="封禁玩家",
        usage="ban <玩家> [原因]",
        permission="command.ban",
        category="server",
    )
    cmd_ban._execute_func = _ban
    manager.register(cmd_ban)

    # --- /pardon ---
    async def _pardon(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: pardon <玩家>")
            return FAILURE
        ctx.server.permissions.pardon_player(tokens[1])
        await ctx.reply(f"[PyMC] 已解除封禁: {tokens[1]}")
        return SUCCESS

    cmd_pardon = Command(
        name="pardon",
        description="解除封禁",
        usage="pardon <玩家>",
        permission="command.ban",
        category="server",
    )
    cmd_pardon._execute_func = _pardon
    manager.register(cmd_pardon)

    # --- /ban-ip ---
    async def _ban_ip(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: ban-ip <IP> [原因]")
            return FAILURE

        reason = ' '.join(tokens[2:]) if len(tokens) >= 3 else ""
        ctx.server.permissions.ban_ip(tokens[1], reason)
        for player in ctx.server.get_online_players():
            address = player.address.split(":")[0]
            if address == tokens[1]:
                await player.disconnect(reason or "你的 IP 已被封禁")
        await ctx.reply(f"[PyMC] 已封禁 IP: {tokens[1]}")
        return SUCCESS

    cmd_banip = Command(
        name="ban-ip",
        description="封禁 IP",
        usage="ban-ip <IP> [原因]",
        permission="command.ban",
        category="server",
    )
    cmd_banip._execute_func = _ban_ip
    manager.register(cmd_banip)

    # --- /pardon-ip ---
    async def _pardon_ip(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: pardon-ip <IP>")
            return FAILURE
        ctx.server.permissions.pardon_ip(tokens[1])
        await ctx.reply(f"[PyMC] 已解除 IP 封禁: {tokens[1]}")
        return SUCCESS

    cmd_pardonip = Command(
        name="pardon-ip",
        description="解除 IP 封禁",
        usage="pardon-ip <IP>",
        permission="command.ban",
        category="server",
    )
    cmd_pardonip._execute_func = _pardon_ip
    manager.register(cmd_pardonip)

    # --- /banlist ---
    async def _banlist(ctx: CommandContext) -> int:
        banlist = ctx.server.permissions.get_banlist()
        players = ", ".join(sorted(entry["name"] for entry in banlist["players"].values())) or "无"
        ips = ", ".join(sorted(banlist["ips"].keys())) or "无"
        await ctx.reply(f"[PyMC] 玩家封禁: {players}")
        await ctx.reply(f"[PyMC] IP 封禁: {ips}")
        return SUCCESS

    cmd_banlist = Command(
        name="banlist",
        description="查看封禁列表",
        usage="banlist",
        permission="command.ban",
        category="server",
    )
    cmd_banlist._execute_func = _banlist
    manager.register(cmd_banlist)

    # --- /op ---
    async def _op(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: op <玩家>")
            return FAILURE
        ctx.server.permissions.op(tokens[1])
        ctx.server.permissions.set_user_group(tokens[1], "admin")
        await ctx.reply(f"[PyMC] 已授予 OP: {tokens[1]}")
        return SUCCESS

    cmd_op = Command(
        name="op",
        description="授予 OP 权限",
        usage="op <玩家>",
        permission="command.op",
        category="server",
    )
    cmd_op._execute_func = _op
    manager.register(cmd_op)

    # --- /deop ---
    async def _deop(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: deop <玩家>")
            return FAILURE
        ctx.server.permissions.deop(tokens[1])
        ctx.server.permissions.set_user_group(tokens[1], "default")
        await ctx.reply(f"[PyMC] 已移除 OP: {tokens[1]}")
        return SUCCESS

    cmd_deop = Command(
        name="deop",
        description="移除 OP 权限",
        usage="deop <玩家>",
        permission="command.op",
        category="server",
    )
    cmd_deop._execute_func = _deop
    manager.register(cmd_deop)

    # --- /whitelist ---
    async def _whitelist(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            whitelist = ctx.server.permissions.get_whitelist()
            status = "开启" if whitelist["enabled"] else "关闭"
            players = ", ".join(whitelist["players"]) or "无"
            await ctx.reply(f"[PyMC] 白名单状态: {status}")
            await ctx.reply(f"[PyMC] 白名单玩家: {players}")
            return SUCCESS

        action = tokens[1].lower()
        if action == "on":
            ctx.server.permissions.set_whitelist_enabled(True)
            await ctx.reply("[PyMC] 白名单已开启")
        elif action == "off":
            ctx.server.permissions.set_whitelist_enabled(False)
            await ctx.reply("[PyMC] 白名单已关闭")
        elif action == "list":
            whitelist = ctx.server.permissions.get_whitelist()
            players = ", ".join(whitelist["players"]) or "无"
            await ctx.reply(f"[PyMC] 白名单玩家: {players}")
        elif action == "add" and len(tokens) >= 3:
            ctx.server.permissions.add_whitelist(tokens[2])
            await ctx.reply(f"[PyMC] 已加入白名单: {tokens[2]}")
        elif action == "remove" and len(tokens) >= 3:
            ctx.server.permissions.remove_whitelist(tokens[2])
            await ctx.reply(f"[PyMC] 已移除白名单: {tokens[2]}")
        elif action == "reload":
            ctx.server.permissions.load()
            await ctx.reply("[PyMC] 白名单与权限文件已重载")
        else:
            await ctx.reply("[PyMC] 用法: whitelist <on|off|list|add|remove|reload>")
            return FAILURE
        return SUCCESS

    cmd_whitelist = Command(
        name="whitelist",
        description="管理白名单",
        usage="whitelist <on|off|list|add|remove|reload>",
        permission="command.whitelist",
        category="server",
    )
    cmd_whitelist._execute_func = _whitelist
    manager.register(cmd_whitelist)
