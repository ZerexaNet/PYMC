# ============================================================
# PyMC - /spreadplayers Command
# ============================================================

import math
import random

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 4:
            await ctx.reply("[PyMC] 用法: spreadplayers <x> <z> <最大距离> <是否尊重团队> <目标>")
            return FAILURE

        try:
            center_x = float(args[0])
            center_z = float(args[1])
            max_distance = float(args[2])
            respect_teams = args[3].lower() in ("true", "1", "yes")
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 参数格式无效")
            return FAILURE

        if len(args) < 5:
            await ctx.reply("[PyMC] 用法: spreadplayers <x> <z> <最大距离> <是否尊重团队> <目标>")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[4])
        players = [t for t in targets if isinstance(t, Connection)]

        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {args[4]}")
            return FAILURE

        from handlers.play.join import _send_synchronize_position

        spread_count = 0
        for player in players:
            angle = random.random() * math.tau
            radius = random.random() * max_distance
            new_x = center_x + math.cos(angle) * radius
            new_z = center_z + math.sin(angle) * radius

            # Find safe Y
            terrain = getattr(ctx.server, 'terrain_generator', None)
            if terrain:
                try:
                    new_y = terrain.get_terrain_height(int(new_x), int(new_z)) + 2
                except Exception:
                    new_y = 100
            else:
                new_y = 100

            player.x, player.y, player.z = new_x, float(new_y), new_z
            await _send_synchronize_position(player)
            spread_count += 1

        await ctx.reply(f"[PyMC] 已将 {spread_count} 个玩家分散在 ({center_x}, {center_z}) 附近")
        return SUCCESS

    cmd = Command(
        name="spreadplayers",
        description="将玩家分散到区域中",
        usage="spreadplayers <x> <z> <最大距离> <尊重团队> <目标>",
        permission="command.spreadplayers",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
