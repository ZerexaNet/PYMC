# ============================================================
# PyMC - /xp Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.join import _add_player_experience
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: xp <数量> [玩家] 或 xp set <玩家> <数量> [levels|points]")
            return FAILURE

        # Simple mode: /xp <amount> [player]
        # Or: /xp set <player> <amount> [levels|points]
        # Or: /xp add <player> <amount> [levels|points]

        sub = args[0].lower()

        if sub in ("set", "add"):
            if len(args) < 3:
                await ctx.reply(f"[PyMC] 用法: xp {sub} <玩家> <数量> [levels|points]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE

            try:
                amount = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 经验数量格式无效")
                return FAILURE

            unit = "points"
            if len(args) >= 4:
                unit = args[3].lower()

            for player in players:
                if unit == "levels":
                    if sub == "set":
                        player.experience_level = max(0, amount)
                        player.experience_progress = 0.0
                    else:
                        player.experience_level = max(0, player.experience_level + amount)
                else:  # points
                    if sub == "add":
                        await _add_player_experience(player, amount)
                    elif sub == "set":
                        player.experience_total = max(0, amount)

            names = ", ".join(p.username for p in players)
            action = "设置为" if sub == "set" else "添加了"
            unit_cn = "级" if unit == "levels" else "点"
            await ctx.reply(f"[PyMC] 已{action} {names} {abs(amount)} {unit_cn}经验")
            return SUCCESS

        # Simple mode: /xp <amount> [player]
        try:
            amount = int(args[0])
        except ValueError:
            await ctx.reply("[PyMC] 经验数量格式无效")
            return FAILURE

        target = ctx.sender
        if len(args) >= 2:
            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未指定目标")
            return FAILURE

        if amount < 0:
            await ctx.reply("[PyMC] 暂不支持扣除经验")
            return FAILURE

        await _add_player_experience(target, amount)
        await ctx.reply(f"[PyMC] 获得 {amount} 点经验")
        return SUCCESS

    cmd = Command(
        name="xp",
        description="设置或添加经验",
        usage="xp <数量> [玩家] | xp <set|add> <玩家> <数量> [levels|points]",
        aliases=["experience"],
        permission="command.xp",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
