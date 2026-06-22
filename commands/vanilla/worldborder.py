# ============================================================
# PyMC - /worldborder Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


# Global world border state
_world_border = {
    "center_x": 0.0,
    "center_z": 0.0,
    "size": 60000000.0,
    "target_size": 60000000.0,
    "speed": 0.0,
    "damage_per_block": 0.2,
    "damage_safe_zone": 5.0,
    "warning_blocks": 5,
    "warning_time": 15,
}


def get_world_border() -> dict:
    return _world_border


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 世界边界大小: {_world_border['size']:.0f}")
            return SUCCESS

        action = args[0].lower()

        if action == "set":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder set <大小> [时间(秒)]")
                return FAILURE
            try:
                size = float(args[1])
            except ValueError:
                await ctx.reply("[PyMC] 大小格式无效")
                return FAILURE
            _world_border["size"] = size
            _world_border["target_size"] = size
            await ctx.reply(f"[PyMC] 世界边界已设置为 {size}")
            return SUCCESS

        if action == "center":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: worldborder center <x> <z>")
                return FAILURE
            try:
                _world_border["center_x"] = float(args[1])
                _world_border["center_z"] = float(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
            await ctx.reply(f"[PyMC] 世界边界中心已设置为 ({_world_border['center_x']}, {_world_border['center_z']})")
            return SUCCESS

        if action == "damage":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder damage <amount|buffer> <值>")
                return FAILURE
            sub = args[1].lower()
            if sub == "amount" and len(args) >= 3:
                try:
                    _world_border["damage_per_block"] = float(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 伤害值格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 边界伤害已设置为 {_world_border['damage_per_block']}")
            elif sub == "buffer" and len(args) >= 3:
                try:
                    _world_border["damage_safe_zone"] = float(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 缓冲区大小格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 伤害缓冲区已设置为 {_world_border['damage_safe_zone']}")
            else:
                await ctx.reply("[PyMC] 用法: worldborder damage <amount|buffer> <值>")
                return FAILURE
            return SUCCESS

        if action == "warning":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder warning <time|distance> <值>")
                return FAILURE
            sub = args[1].lower()
            if sub == "time" and len(args) >= 3:
                try:
                    _world_border["warning_time"] = int(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 时间格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 警告时间已设置为 {_world_border['warning_time']} 秒")
            elif sub == "distance" and len(args) >= 3:
                try:
                    _world_border["warning_blocks"] = int(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 距离格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 警告距离已设置为 {_world_border['warning_blocks']} 方块")
            else:
                await ctx.reply("[PyMC] 用法: worldborder warning <time|distance> <值>")
                return FAILURE
            return SUCCESS

        if action == "get":
            await ctx.reply(f"[PyMC] 世界边界: 大小={_world_border['size']}, 中心=({_world_border['center_x']}, {_world_border['center_z']})")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: worldborder <set|center|damage|warning|get> ...")
        return FAILURE

    cmd = Command(
        name="worldborder",
        description="管理世界边界",
        usage="worldborder <set|center|damage|warning|get> ...",
        permission="command.worldborder",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
