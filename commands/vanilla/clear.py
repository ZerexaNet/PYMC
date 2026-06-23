# ============================================================
# PyMC - /clear Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        target = ctx.sender
        item_filter = None
        max_count = -1

        # Parse target
        if args:
            from network.connection import Connection
            targets = resolve_selector(ctx.server, ctx.sender, args[0])
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[0]}")
                return FAILURE

        # Parse item filter
        if len(args) >= 2:
            item_filter = args[1].lower()
            if ":" not in item_filter:
                item_filter = f"minecraft:{item_filter}"

        # Parse max count
        if len(args) >= 3:
            try:
                max_count = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 数量格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未指定目标玩家")
            return FAILURE

        # Clear inventory
        cleared = 0
        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            cleared = target.inventory_obj.clear_items(item_filter=item_filter, max_count=max_count)
            target.inventory_state_id += 1
        else:
            cleared = 0

        if item_filter:
            await ctx.reply(f"[PyMC] 已清除 {target.username} 的 {item_filter} x{cleared}")
        else:
            await ctx.reply(f"[PyMC] 已清除 {target.username} 的物品栏 (共 {cleared} 个物品)")
        return SUCCESS

    cmd = Command(
        name="clear",
        description="清除玩家物品栏",
        usage="clear [玩家] [物品] [最大数量]",
        permission="command.clear",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
