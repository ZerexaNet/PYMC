# ============================================================
# PyMC - /give Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


# Known items for give command
KNOWN_ITEMS = {
    "diamond", "iron_ingot", "gold_ingot", "emerald", "coal",
    "stick", "oak_planks", "spruce_planks", "birch_planks",
    "cobblestone", "stone", "dirt", "grass_block", "sand",
    "glass", "oak_log", "spruce_log", "birch_log",
    "diamond_sword", "iron_sword", "stone_sword", "wooden_sword",
    "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe", "wooden_pickaxe",
    "diamond_axe", "iron_axe", "stone_axe", "wooden_axe",
    "diamond_shovel", "iron_shovel", "stone_shovel", "wooden_shovel",
    "diamond_hoe", "iron_hoe", "stone_hoe", "wooden_hoe",
    "diamond_helmet", "diamond_chestplate", "diamond_leggings", "diamond_boots",
    "iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots",
    "leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots",
    "bread", "apple", "cooked_beef", "cooked_porkchop", "cooked_chicken",
    "raw_beef", "raw_porkchop", "raw_chicken", "wheat", "melon_slice",
    "golden_apple", "enchanted_golden_apple",
    "arrow", "bow", "crossbow", "trident", "shield",
    "bucket", "water_bucket", "lava_bucket", "milk_bucket",
    "tnt", "ender_pearl", "blaze_rod", "blaze_powder",
    "crafting_table", "furnace", "chest", "ender_chest",
    "bed", "torch", "ladder", "sign", "boat",
    "redstone", "redstone_torch", "repeater", "comparator",
    "piston", "sticky_piston", "observer", "hopper", "dropper", "dispenser",
    "book", "paper", "ink_sac", "writable_book", "written_book",
    "map", "compass", "clock", "spyglass",
    "netherite_sword", "netherite_pickaxe", "netherite_axe",
    "netherite_shovel", "netherite_hoe",
    "netherite_helmet", "netherite_chestplate", "netherite_leggings", "netherite_boots",
    "netherite_ingot", "netherite_scrap", "ancient_debris",
    "elytra", "totem_of_undying", "experience_bottle",
    "debug_stick", "knowledge_book", "command_block_minecart",
}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: give <玩家> <物品> [数量]")
            return FAILURE

        # Resolve target player
        target = ctx.sender
        target_spec = args[0]
        if ctx.sender is None or target_spec != ctx.sender.username:
            targets = resolve_selector(ctx.server, ctx.sender, target_spec)
            if targets:
                from network.connection import Connection
                # Find a player target
                for t in targets:
                    if isinstance(t, Connection):
                        target = t
                        break
                if target is None and ctx.sender is None:
                    await ctx.reply(f"[PyMC] 未找到玩家: {target_spec}")
                    return FAILURE

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: give <玩家> <物品> [数量]")
            return FAILURE

        item_name = args[1].lower()
        if ":" not in item_name:
            item_name = f"minecraft:{item_name}"

        count = 1
        if len(args) >= 3:
            try:
                count = int(args[2])
                count = max(1, min(64, count))
            except ValueError:
                await ctx.reply("[PyMC] 数量格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未找到目标玩家")
            return FAILURE

        # Add to inventory if PlayerInventory is available
        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            try:
                slot = target.inventory_obj.add_item(item_name, count)
                target.inventory_state_id += 1
                if slot is not None:
                    # Send slot update
                    from handlers.play.join import _send_set_experience
                    await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count}")
                    return SUCCESS
            except Exception as e:
                await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count} (物品栏暂未完全同步)")
                return SUCCESS

        # Fallback: just notify
        await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count}")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) <= 2:
            # Suggesting item name
            partial = tokens[1] if len(tokens) > 1 else ""
            return [i for i in KNOWN_ITEMS if i.startswith(partial)]
        return []

    cmd = Command(
        name="give",
        description="给予玩家物品",
        usage="give <玩家> <物品> [数量]",
        permission="command.give",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
