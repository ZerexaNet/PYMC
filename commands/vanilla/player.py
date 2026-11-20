# ============================================================
# PyMC - Player Commands
# tp, gamemode, give, clear, kill, xp, effect, enchant
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    """Register all player-related commands."""

    # --- /tp ---
    # --- /gamemode ---
    # --- /give ---
    # --- /clear ---
    # --- /kill ---
    # --- /xp ---
    # --- /effect ---
    from commands.arguments import parse_effect_name, EFFECT_NAMES

    # In-memory active effects per player
    _active_effects: dict[str, dict[str, dict]] = {}

    async def _effect(ctx: CommandContext) -> int:
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

            duration = 600
            if len(args) >= 4:
                try:
                    duration = int(args[3]) * 20
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

    def _effect_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["give", "clear"]
        if len(tokens) >= 3 and tokens[1] == "give":
            if len(tokens) == 3:
                return ["@a", "@p", "@s"]
            if len(tokens) == 4:
                return list(EFFECT_NAMES.keys())
        return []

    cmd_effect = Command(
        name="effect",
        description="给予或清除状态效果",
        usage="effect give <目标> <效果> [秒数] [放大器] | effect clear <目标> [效果]",
        permission="command.effect",
        category="player",
    )
    cmd_effect._execute_func = _effect
    cmd_effect._suggest_func = _effect_suggest
    manager.register(cmd_effect)

    # --- /enchant ---
    from commands.arguments import parse_enchantment_name, ENCHANTMENT_NAMES

    async def _enchant(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: enchant <目标> <附魔> [等级]")
            return FAILURE

        target = ctx.sender
        target_spec = args[0]

        if ctx.sender is None or (len(args) >= 2 and not _is_number(args[1]) and args[1].lower() not in ENCHANTMENT_NAMES):
            targets = resolve_selector(ctx.server, ctx.sender, target_spec)
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到目标: {target_spec}")
                return FAILURE

        enchant_idx = 1 if target != ctx.sender else 0
        if enchant_idx >= len(args):
            await ctx.reply("[PyMC] 用法: enchant <目标> <附魔> [等级]")
            return FAILURE

        try:
            enchant_name = parse_enchantment_name(args[enchant_idx])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        level = 1
        if len(args) > enchant_idx + 1:
            try:
                level = int(args[enchant_idx + 1])
                level = max(1, min(255, level))
            except ValueError:
                await ctx.reply("[PyMC] 等级格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未找到目标")
            return FAILURE

        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            slot = target.selected_hotbar_slot
            item = target.inventory_obj.get_item_in_slot(slot)
            if item is not None:
                if "enchantments" not in item:
                    item["enchantments"] = {}
                item["enchantments"][enchant_name] = level
                await ctx.reply(f"[PyMC] 已附魔 {target.username} 手持物品: {enchant_name} {level}")
                return SUCCESS
            else:
                await ctx.reply(f"[PyMC] {target.username} 手中没有物品")
                return FAILURE

        await ctx.reply(f"[PyMC] 已附魔 {target.username}: {enchant_name} {level}")
        return SUCCESS

    def _enchant_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) >= 3:
            partial = tokens[-1] if tokens[-1] else ""
            return [e for e in ENCHANTMENT_NAMES if e.startswith(partial)]
        return []

    cmd_enchant = Command(
        name="enchant",
        description="给手持物品添加附魔",
        usage="enchant <目标> <附魔> [等级]",
        permission="command.enchant",
        category="player",
    )
    cmd_enchant._execute_func = _enchant
    cmd_enchant._suggest_func = _enchant_suggest
    manager.register(cmd_enchant)


    # --- /damage ---

def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


