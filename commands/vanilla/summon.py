# ============================================================
# PyMC - /summon Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.entities import broadcast_entity_spawn
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: summon <实体类型> [x] [y] [z] [NBT]")
            return FAILURE

        entity_type = args[0].lower()
        if ":" in entity_type:
            entity_type = entity_type.split(":", 1)[1]

        # Parse coordinates
        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        if len(args) >= 4:
            try:
                x = resolve_coordinate(parse_coordinate(args[1]), bx)
                y = resolve_coordinate(parse_coordinate(args[2]), by)
                z = resolve_coordinate(parse_coordinate(args[3]), bz)
            except (ValueError, IndexError):
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
        else:
            x, y, z = bx, by, bz

        # Create entity based on type
        entity = None
        if entity_type == "experience_orb" or entity_type == "orb":
            count = 1
            if len(args) >= 5:
                try:
                    count = max(1, int(args[4]))
                except ValueError:
                    pass
            entity = ctx.server.entity_manager.create_experience_orb(x, y, z, count=count)
            await broadcast_entity_spawn(ctx.server, entity)
            await ctx.reply(f"[PyMC] 已生成经验球实体 #{entity.entity_id} x{count}")
        elif entity_type == "item":
            item_name = "minecraft:stone"
            count = 1
            if len(args) >= 5:
                item_name = args[4]
                if ":" not in item_name:
                    item_name = f"minecraft:{item_name}"
            if len(args) >= 6:
                try:
                    count = max(1, int(args[5]))
                except ValueError:
                    pass
            entity = ctx.server.entity_manager.create_item(x, y, z, item_name=item_name, count=count)
            await ctx.reply(f"[PyMC] 已生成 item 实体 #{entity.entity_id}: {item_name} x{count}")
        elif entity_type in ("pig", "cow", "sheep", "zombie", "skeleton", "creeper", "spider"):
            entity = ctx.server.entity_manager.create_mob(x, y, z, mob_type=entity_type)
            await broadcast_entity_spawn(ctx.server, entity)
            await ctx.reply(f"[PyMC] 已生成 {entity_type} 实体 #{entity.entity_id}")
        else:
            # Try to create a generic mob
            entity = ctx.server.entity_manager.create_mob(x, y, z, mob_type=entity_type)
            await broadcast_entity_spawn(ctx.server, entity)
            await ctx.reply(f"[PyMC] 已生成 {entity_type} 实体 #{entity.entity_id}")

        return SUCCESS

    cmd = Command(
        name="summon",
        description="生成实体",
        usage="summon <实体类型> [x] [y] [z] [NBT]",
        permission="command.summon",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
