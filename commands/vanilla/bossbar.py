# ============================================================
# PyMC - /bossbar Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


# Boss bar storage
_boss_bars: dict[str, dict] = {}  # id -> {players, name, color, style, value, max, visible}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            # List boss bars
            if not _boss_bars:
                await ctx.reply("[PyMC] 没有自定义 Boss 栏")
            else:
                for bid, bar in _boss_bars.items():
                    await ctx.reply(f"[PyMC] {bid}: {bar['name']} ({bar['value']}/{bar['max']})")
            return SUCCESS

        action = args[0].lower()

        if action == "add":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: bossbar add <ID> <名称>")
                return FAILURE
            bar_id = args[1]
            name = ' '.join(args[2:])
            if bar_id in _boss_bars:
                await ctx.reply(f"[PyMC] Boss 栏 {bar_id} 已存在")
                return FAILURE
            _boss_bars[bar_id] = {
                "name": name,
                "color": "white",
                "style": "progress",
                "value": 0,
                "max": 100,
                "visible": True,
                "players": [],
            }
            await ctx.reply(f"[PyMC] 已创建 Boss 栏: {bar_id}")
            return SUCCESS

        if action == "remove":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: bossbar remove <ID>")
                return FAILURE
            bar_id = args[1]
            if bar_id not in _boss_bars:
                await ctx.reply(f"[PyMC] Boss 栏 {bar_id} 不存在")
                return FAILURE
            del _boss_bars[bar_id]
            await ctx.reply(f"[PyMC] 已移除 Boss 栏: {bar_id}")
            return SUCCESS

        if action == "get":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: bossbar get <ID> <max|players|value|visible|color|name|style>")
                return FAILURE
            bar_id = args[1]
            prop = args[2].lower()
            if bar_id not in _boss_bars:
                await ctx.reply(f"[PyMC] Boss 栏 {bar_id} 不存在")
                return FAILURE
            bar = _boss_bars[bar_id]
            if prop in bar:
                await ctx.reply(f"[PyMC] {bar_id}.{prop} = {bar[prop]}")
            else:
                await ctx.reply(f"[PyMC] 未知属性: {prop}")
            return SUCCESS

        if action == "set":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: bossbar set <ID> <属性> <值>")
                return FAILURE
            bar_id = args[1]
            if bar_id not in _boss_bars:
                await ctx.reply(f"[PyMC] Boss 栏 {bar_id} 不存在")
                return FAILURE
            bar = _boss_bars[bar_id]
            prop = args[2].lower()
            if len(args) < 4:
                await ctx.reply("[PyMC] 缺少值")
                return FAILURE
            value = args[3]

            if prop == "name":
                bar["name"] = ' '.join(args[3:])
            elif prop == "color":
                bar["color"] = value.lower()
            elif prop == "style":
                bar["style"] = value.lower()
            elif prop == "value":
                try:
                    bar["value"] = int(value)
                except ValueError:
                    await ctx.reply("[PyMC] 值格式无效")
                    return FAILURE
            elif prop == "max":
                try:
                    bar["max"] = int(value)
                except ValueError:
                    await ctx.reply("[PyMC] 最大值格式无效")
                    return FAILURE
            elif prop == "visible":
                bar["visible"] = value.lower() in ("true", "1")
            elif prop == "players":
                bar["players"] = [value]
            else:
                await ctx.reply(f"[PyMC] 未知属性: {prop}")
                return FAILURE

            await ctx.reply(f"[PyMC] 已设置 Boss 栏 {bar_id} 的 {prop}")
            return SUCCESS

        if action == "list":
            if not _boss_bars:
                await ctx.reply("[PyMC] 没有自定义 Boss 栏")
            else:
                for bid, bar in _boss_bars.items():
                    await ctx.reply(f"[PyMC] {bid}: {bar['name']}")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: bossbar <add|remove|get|set|list> ...")
        return FAILURE

    cmd = Command(
        name="bossbar",
        description="管理自定义 Boss 栏",
        usage="bossbar <add|remove|get|set|list> ...",
        permission="command.bossbar",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
