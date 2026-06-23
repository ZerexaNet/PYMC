# ============================================================
# PyMC - /effect Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import parse_effect_name, EFFECT_NAMES


# In-memory active effects per player
_active_effects: dict[str, dict[str, dict]] = {}  # username -> {effect_name -> {amplifier, duration, ambient}}


def get_active_effects(username: str) -> dict[str, dict]:
    """Get active effects for a player."""
    return _active_effects.get(username, {})


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: effect give <目标> <效果> [秒数] [放大器] [是否环境] | effect clear <目标> [效果]")
            return FAILURE

        sub = args[0].lower()

        if sub == "give":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: effect give <目标> <效果> [秒数] [放大器]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE

            try:
                effect_name = parse_effect_name(args[2])
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE

            duration = 600  # 30 seconds default
            if len(args) >= 4:
                try:
                    duration = int(args[3]) * 20  # seconds to ticks
                    if duration == 0:
                        duration = 600
                except ValueError:
                    await ctx.reply("[PyMC] 持续时间格式无效")
                    return FAILURE

            amplifier = 0
            if len(args) >= 5:
                try:
                    amplifier = int(args[4])
                    amplifier = max(0, min(255, amplifier))
                except ValueError:
                    await ctx.reply("[PyMC] 放大器格式无效")
                    return FAILURE

            ambient = False
            if len(args) >= 6:
                ambient = args[5].lower() in ("true", "1", "yes")

            # Store the effect
            for player in players:
                if player.username not in _active_effects:
                    _active_effects[player.username] = {}
                _active_effects[player.username][effect_name] = {
                    "amplifier": amplifier,
                    "duration": duration,
                    "ambient": ambient,
                    "effect_id": EFFECT_NAMES.get(effect_name, 0),
                }

            names = ", ".join(p.username for p in players)
            await ctx.reply(f"[PyMC] 已给予 {names} {effect_name} 效果 (等级 {amplifier + 1}, {duration // 20}秒)")
            return SUCCESS

        elif sub == "clear":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: effect clear <目标> [效果]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE

            effect_to_clear = None
            if len(args) >= 3:
                try:
                    effect_to_clear = parse_effect_name(args[2])
                except ValueError:
                    await ctx.reply(f"[PyMC] 未知效果: {args[2]}")
                    return FAILURE

            total_cleared = 0
            for player in players:
                if player.username in _active_effects:
                    if effect_to_clear:
                        if effect_to_clear in _active_effects[player.username]:
                            del _active_effects[player.username][effect_to_clear]
                            total_cleared += 1
                    else:
                        total_cleared += len(_active_effects[player.username])
                        _active_effects[player.username] = {}

            names = ", ".join(p.username for p in players)
            if effect_to_clear:
                await ctx.reply(f"[PyMC] 已清除 {names} 的 {effect_to_clear} 效果")
            else:
                await ctx.reply(f"[PyMC] 已清除 {names} 的所有效果 (共 {total_cleared} 个)")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: effect <give|clear> ...")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["give", "clear"]
        if len(tokens) >= 3 and tokens[1] == "give":
            if len(tokens) == 3:
                return ["@a", "@p", "@s"]
            if len(tokens) == 4:
                return list(EFFECT_NAMES.keys())
        return []

    cmd = Command(
        name="effect",
        description="给予或清除状态效果",
        usage="effect give <目标> <效果> [秒数] [放大器] | effect clear <目标> [效果]",
        permission="command.effect",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
