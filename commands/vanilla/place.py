# ============================================================
# PyMC - /place Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: place <structure|feature|jigsaw|template> <名称> [x] [y] [z]")
            return FAILURE

        place_type = args[0].lower()

        if place_type == "structure":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place structure <结构名> [x] [y] [z]")
                return FAILURE
            struct_name = args[1]

            bx, by, bz = 0.0, 100.0, 0.0
            if ctx.sender and hasattr(ctx.sender, 'x'):
                bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

            x, y, z = bx, by, bz
            if len(args) >= 5:
                try:
                    x = resolve_coordinate(parse_coordinate(args[2]), bx)
                    y = resolve_coordinate(parse_coordinate(args[3]), by)
                    z = resolve_coordinate(parse_coordinate(args[4]), bz)
                except ValueError:
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE

            await ctx.reply(f"[PyMC] 已在 ({x:.0f}, {y:.0f}, {z:.0f}) 放置结构 {struct_name} (结构放置暂未完全实现)")
            return SUCCESS

        if place_type == "feature":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place feature <特性名> [x] [y] [z]")
                return FAILURE
            feature_name = args[1]
            await ctx.reply(f"[PyMC] 已放置特性 {feature_name} (特性放置暂未完全实现)")
            return SUCCESS

        if place_type == "jigsaw":
            if len(args) < 5:
                await ctx.reply("[PyMC] 用法: place jigsaw <池> <目标> <最大深度> [x] [y] [z]")
                return FAILURE
            await ctx.reply("[PyMC] jigsaw 放置暂未完全实现")
            return SUCCESS

        if place_type == "template":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place template <模板名> [x] [y] [z] [旋转] [镜像]")
                return FAILURE
            await ctx.reply("[PyMC] 模板放置暂未完全实现")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知放置类型: {place_type}")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["structure", "feature", "jigsaw", "template"]
        return []

    cmd = Command(
        name="place",
        description="放置结构、特性或模板",
        usage="place <structure|feature|jigsaw|template> <名称> [位置]",
        permission="command.place",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
