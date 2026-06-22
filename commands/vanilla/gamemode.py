# ============================================================
# PyMC - /gamemode Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_gamemode, GAMEMODE_NAMES


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.join import _send_game_event
        from handlers.play.chat import send_system_message

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            if ctx.sender is not None:
                await ctx.reply(f"[PyMC] 当前游戏模式: {ctx.sender.gamemode}")
            else:
                await ctx.reply("[PyMC] 用法: gamemode <模式> [玩家]")
            return SUCCESS

        mode_name = args[0].lower()
        target = ctx.sender

        try:
            mode, normalized = parse_gamemode(mode_name)
        except ValueError:
            await ctx.reply("[PyMC] 无效模式，可用值: survival, creative, adventure, spectator (或 s, c, a, sp)")
            return FAILURE

        # Check for target player
        if len(args) >= 2:
            target = ctx.server.find_player(args[1])
            if target is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE
        elif ctx.sender is None:
            await ctx.reply("[PyMC] 用法: gamemode <模式> <玩家>")
            return FAILURE

        mode_names_cn = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
        target.gamemode = normalized
        await _send_game_event(target, 3, float(mode))
        await send_system_message(target, f"[PyMC] 游戏模式已切换为 {mode_names_cn.get(mode, '未知')}")
        if ctx.sender is not target:
            await ctx.reply(f"[PyMC] 已将 {target.username} 的游戏模式切换为 {mode_names_cn.get(mode, '未知')}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        return ["survival", "creative", "adventure", "spectator"]

    cmd = Command(
        name="gamemode",
        description="切换游戏模式",
        usage="gamemode <survival|creative|adventure|spectator> [玩家]",
        aliases=["gm"],
        permission="command.gamemode",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
