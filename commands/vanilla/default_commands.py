# ============================================================
# PyMC - Default Server Commands
# kick, ban, op, whitelist, stop, say, msg, me, etc.
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
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

    cmd_say = Command(name="say", description="广播服务器消息", usage="say <消息>", permission="command.say")
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

    cmd_me = Command(name="me", description="发送动作消息", usage="me <动作>", permission="command.me")
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
        name="msg", description="发送私聊消息",
        usage="msg <玩家> <消息>",
        aliases=["tell", "w"],
        permission="command.msg",
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

    cmd_kick = Command(name="kick", description="踢出玩家", usage="kick <玩家> [原因]", permission="command.kick")
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

    cmd_ban = Command(name="ban", description="封禁玩家", usage="ban <玩家> [原因]", permission="command.ban")
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

    cmd_pardon = Command(name="pardon", description="解除封禁", usage="pardon <玩家>", permission="command.ban")
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

    cmd_banip = Command(name="ban-ip", description="封禁 IP", usage="ban-ip <IP> [原因]", permission="command.ban")
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

    cmd_pardonip = Command(name="pardon-ip", description="解除 IP 封禁", usage="pardon-ip <IP>", permission="command.ban")
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

    cmd_banlist = Command(name="banlist", description="查看封禁列表", usage="banlist", permission="command.ban")
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

    cmd_op = Command(name="op", description="授予 OP 权限", usage="op <玩家>", permission="command.op")
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

    cmd_deop = Command(name="deop", description="移除 OP 权限", usage="deop <玩家>", permission="command.op")
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

    cmd_whitelist = Command(name="whitelist", description="管理白名单", usage="whitelist <on|off|list|add|remove|reload>", permission="command.whitelist")
    cmd_whitelist._execute_func = _whitelist
    manager.register(cmd_whitelist)

    # --- /stop ---
    async def _stop(ctx: CommandContext) -> int:
        if ctx.sender is not None:
            from handlers.play.chat import send_system_message
            await send_system_message(ctx.sender, "[PyMC] 正在关闭服务器...")
        ctx.server.broadcast_system_message("[PyMC] 服务器正在关闭...")
        import asyncio
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(ctx.server.stop()))
        return SUCCESS

    cmd_stop = Command(name="stop", description="停止服务器", usage="stop", permission="command.stop")
    cmd_stop._execute_func = _stop
    manager.register(cmd_stop)

    # --- /reload ---
    async def _reload(ctx: CommandContext) -> int:
        ctx.server.permissions.load()
        await ctx.reply("[PyMC] 已重载权限与白名单配置")
        return SUCCESS

    cmd_reload = Command(name="reload", description="重载配置", usage="reload", permission="command.op")
    cmd_reload._execute_func = _reload
    manager.register(cmd_reload)

    # --- /save-all ---
    async def _save_all(ctx: CommandContext) -> int:
        ctx.server.save_all_player_states()
        ctx.server.world_storage.flush()
        await ctx.reply("[PyMC] 世界与玩家数据已保存")
        return SUCCESS

    cmd_saveall = Command(name="save-all", description="保存所有数据", usage="save-all", permission="command.op")
    cmd_saveall._execute_func = _save_all
    manager.register(cmd_saveall)

    # --- /save-on / save-off ---
    async def _save_toggle(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        cmd_name = tokens[0].lower()
        ctx.server.autosave_enabled = (cmd_name == "save-on")
        await ctx.reply(f"[PyMC] 自动保存已{'开启' if ctx.server.autosave_enabled else '关闭'}")
        return SUCCESS

    cmd_saveon = Command(name="save-on", description="开启自动保存", usage="save-on", permission="command.op")
    cmd_saveon._execute_func = _save_toggle
    manager.register(cmd_saveon)

    cmd_saveoff = Command(name="save-off", description="关闭自动保存", usage="save-off", permission="command.op")
    cmd_saveoff._execute_func = _save_toggle
    manager.register(cmd_saveoff)

    # --- /defaultgamemode ---
    async def _defaultgamemode(ctx: CommandContext) -> int:
        from commands.arguments import parse_gamemode
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: defaultgamemode <survival|creative|adventure|spectator>")
            return FAILURE
        try:
            _, normalized = parse_gamemode(tokens[1])
        except ValueError:
            await ctx.reply("[PyMC] 无效模式")
            return FAILURE
        ctx.server.config["gamemode"] = normalized
        ctx.server.save_runtime_config()
        await ctx.reply(f"[PyMC] 默认游戏模式已设置为 {normalized}")
        return SUCCESS

    cmd_dgm = Command(name="defaultgamemode", description="设置默认游戏模式", usage="defaultgamemode <模式>", permission="command.gamemode")
    cmd_dgm._execute_func = _defaultgamemode
    manager.register(cmd_dgm)

    # --- /setworldspawn ---
    async def _setworldspawn(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) >= 4:
            try:
                x = int(float(tokens[1]))
                y = int(float(tokens[2]))
                z = int(float(tokens[3]))
            except ValueError:
                await ctx.reply("[PyMC] 用法: setworldspawn <x> <y> <z>")
                return FAILURE
        else:
            x = int(ctx.server.spawn_position[0])
            y = int(ctx.server.spawn_position[1])
            z = int(ctx.server.spawn_position[2])
        ctx.server.spawn_position = (x, y, z)
        ctx.server.save_runtime_config()
        await ctx.reply(f"[PyMC] 世界出生点已设置为 ({x}, {y}, {z})")
        return SUCCESS

    cmd_sws = Command(name="setworldspawn", description="设置世界出生点", usage="setworldspawn [x y z]", permission="command.op")
    cmd_sws._execute_func = _setworldspawn
    manager.register(cmd_sws)

    # --- /spawnpoint ---
    async def _spawnpoint(ctx: CommandContext) -> int:
        import math
        tokens = ctx.arguments.get("_raw_tokens", [])
        target = ctx.sender
        coord_index = 1

        if len(tokens) >= 2 and ctx.sender is None:
            target = ctx.server.find_player(tokens[1])
            coord_index = 2
            if target is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {tokens[1]}")
                return FAILURE
        elif len(tokens) >= 2 and ctx.sender is not None:
            maybe_target = ctx.server.find_player(tokens[1])
            if maybe_target is not None:
                target = maybe_target
                coord_index = 2

        if target is None:
            await ctx.reply("[PyMC] 用法: spawnpoint [玩家] [x y z]")
            return FAILURE

        if len(tokens) >= coord_index + 3:
            try:
                spawn_x = int(float(tokens[coord_index]))
                spawn_y = int(float(tokens[coord_index + 1]))
                spawn_z = int(float(tokens[coord_index + 2]))
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
        else:
            spawn_x = math.floor(target.x)
            spawn_y = math.floor(target.y)
            spawn_z = math.floor(target.z)

        target.personal_spawn = (spawn_x, spawn_y, spawn_z)
        ctx.server.save_player_state(target)
        await ctx.reply(f"[PyMC] 已将 {target.username or '玩家'} 的个人出生点设置为 ({spawn_x}, {spawn_y}, {spawn_z})")
        return SUCCESS

    cmd_sp = Command(name="spawnpoint", description="设置个人出生点", usage="spawnpoint [玩家] [x y z]", permission="command.op")
    cmd_sp._execute_func = _spawnpoint
    manager.register(cmd_sp)

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
