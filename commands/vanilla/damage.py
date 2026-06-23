# ============================================================
# PyMC - /damage Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import parse_damage_type
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.join import _damage_player

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: damage <目标> <伤害值> [伤害类型]")
            return FAILURE

        # Parse target
        targets = resolve_selector(ctx.server, ctx.sender, args[0])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            if ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
                return FAILURE
            players = [ctx.sender] if isinstance(ctx.sender, Connection) else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: damage <目标> <伤害值> [伤害类型]")
            return FAILURE

        try:
            amount = float(args[1])
        except ValueError:
            await ctx.reply("[PyMC] 伤害值格式无效")
            return FAILURE

        damage_type = "generic"
        if len(args) >= 3:
            try:
                damage_type = parse_damage_type(args[2])
            except ValueError:
                damage_type = args[2]

        for player in players:
            await _damage_player(player, max(0.0, amount), damage_type, ctx.server)

        names = ", ".join(p.username for p in players)
        await ctx.reply(f"[PyMC] 已对 {names} 造成 {amount:.1f} 点{damage_type}伤害")
        return SUCCESS

    cmd = Command(
        name="damage",
        description="对实体造成伤害",
        usage="damage <目标> <伤害值> [伤害类型]",
        permission="command.damage",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
