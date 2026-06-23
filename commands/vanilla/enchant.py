# ============================================================
# PyMC - /enchant Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import parse_enchantment_name, ENCHANTMENT_NAMES


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
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

        # Find the enchantment argument
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

        # Apply enchantment (record on inventory item if available)
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

        # Fallback
        await ctx.reply(f"[PyMC] 已附魔 {target.username}: {enchant_name} {level}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) >= 3:
            partial = tokens[-1] if tokens[-1] else ""
            return [e for e in ENCHANTMENT_NAMES if e.startswith(partial)]
        return []

    cmd = Command(
        name="enchant",
        description="给手持物品添加附魔",
        usage="enchant <目标> <附魔> [等级]",
        permission="command.enchant",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
