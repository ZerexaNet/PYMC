# ============================================================
# PyMC - /item Command
# Advanced item manipulation
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: item <replace|modify> <目标> <槽位> ...")
            return FAILURE

        action = args[0].lower()

        if action == "replace":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: item replace <目标> <槽位> with <物品> [数量]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE

            slot = args[2].lower()

            if args[3].lower() == "with":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: item replace <目标> <槽位> with <物品> [数量]")
                    return FAILURE

                item_name = args[4].lower()
                if ":" not in item_name:
                    item_name = f"minecraft:{item_name}"
                count = int(args[5]) if len(args) >= 6 else 1

                for player in players:
                    if hasattr(player, 'inventory_obj') and player.inventory_obj is not None:
                        slot_idx = _parse_slot(slot, player)
                        if slot_idx is not None:
                            player.inventory_obj.set_item_in_slot(slot_idx, {
                                "item": item_name,
                                "count": count,
                            })
                            player.inventory_state_id += 1

                names = ", ".join(p.username for p in players)
                await ctx.reply(f"[PyMC] 已替换 {names} 的 {slot} 为 {item_name} x{count}")
                return SUCCESS

            # from another source
            await ctx.reply("[PyMC] item replace from 暂未实现")
            return FAILURE

        if action == "modify":
            await ctx.reply("[PyMC] item modify 暂未完全实现")
            return FAILURE

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd = Command(
        name="item",
        description="高级物品操作",
        usage="item replace <目标> <槽位> with <物品> [数量]",
        permission="command.item",
    )
    cmd._execute_func = _execute
    manager.register(cmd)


def _parse_slot(slot_str: str, player: Connection) -> int | None:
    """Parse a slot string to a slot index."""
    slot_str = slot_str.lower()
    # Hotbar: hotbar.0-8 or 0-8
    if slot_str.startswith("hotbar."):
        idx = int(slot_str.split(".")[1])
        return idx if 0 <= idx <= 8 else None
    if slot_str.startswith("weapon.") or slot_str == "weapon.mainhand":
        return player.selected_hotbar_slot
    if slot_str == "weapon.offhand":
        return 40  # Offhand slot
    if slot_str.startswith("armor."):
        armor_slots = {"head": 39, "chest": 38, "legs": 37, "feet": 36}
        part = slot_str.split(".")[1] if "." in slot_str else slot_str
        return armor_slots.get(part)
    if slot_str.startswith("container."):
        idx = int(slot_str.split(".")[1])
        return idx if 0 <= idx <= 53 else None
    try:
        idx = int(slot_str)
        if 0 <= idx <= 41:
            return idx
    except ValueError:
        pass
    return None
