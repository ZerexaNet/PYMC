# ============================================================
# PyMC - Entity Commands
# summon, damage, ride, spreadplayers
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import parse_coordinate, resolve_coordinate, parse_damage_type
from network.connection import Connection


def register(manager):
    """Register all entity-related commands."""

    # --- /summon ---
    async def _summon(ctx: CommandContext) -> int:
        from handlers.play.entities import broadcast_entity_spawn

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: summon <实体类型> [x] [y] [z] [NBT]")
            return FAILURE

        entity_type = args[0].lower()
        if ":" in entity_type:
            entity_type = entity_type.split(":", 1)[1]

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
            entity = ctx.server.entity_manager.create_mob(x, y, z, mob_type=entity_type)
            await broadcast_entity_spawn(ctx.server, entity)
            await ctx.reply(f"[PyMC] 已生成 {entity_type} 实体 #{entity.entity_id}")

        return SUCCESS

    cmd_summon = Command(
        name="summon",
        description="生成实体",
        usage="summon <实体类型> [x] [y] [z] [NBT]",
        permission="command.summon",
        category="entity",
    )
    cmd_summon._execute_func = _summon
    manager.register(cmd_summon)

    # --- /damage ---
    async def _damage(ctx: CommandContext) -> int:
        from handlers.play.join import _damage_player

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: damage <目标> <伤害值> [伤害类型]")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[0])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            if ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
                return FAILURE
            players = [ctx.sender] if isinstance(ctx.sender, Connection) else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: damage <目标> <伤害值> [伤害类型]")
            return FAILURE

        try:
            amount = float(args[1])
        except ValueError:
            await ctx.reply("[PyMC] 伤害值格式无效")
            return FAILURE

        damage_type = "generic"
        if len(args) >= 3:
            try:
                damage_type = parse_damage_type(args[2])
            except ValueError:
                damage_type = args[2]

        for player in players:
            await _damage_player(player, max(0.0, amount), damage_type, ctx.server)

        names = ", ".join(p.username for p in players)
        await ctx.reply(f"[PyMC] 已对 {names} 造成 {amount:.1f} 点{damage_type}伤害")
        return SUCCESS

    cmd_damage = Command(
        name="damage",
        description="对实体造成伤害",
        usage="damage <目标> <伤害值> [伤害类型]",
        permission="command.damage",
        category="entity",
    )
    cmd_damage._execute_func = _damage
    manager.register(cmd_damage)

    # --- /ride ---
    async def _ride(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: ride <骑乘者> <mount|dismount> [坐骑]")
            return FAILURE

        rider_targets = resolve_selector(ctx.server, ctx.sender, args[0])
        if not rider_targets:
            await ctx.reply(f"[PyMC] 未找到骑乘者: {args[0]}")
            return FAILURE
        rider = rider_targets[0]

        action = args[1].lower()

        if action == "mount":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: ride <骑乘者> mount <坐骑>")
                return FAILURE
            mount_targets = resolve_selector(ctx.server, ctx.sender, args[2])
            if not mount_targets:
                await ctx.reply(f"[PyMC] 未找到坐骑: {args[2]}")
                return FAILURE
            mount = mount_targets[0]

            if hasattr(rider, 'metadata'):
                rider.metadata["riding"] = mount.entity_id if hasattr(mount, 'entity_id') else id(mount)
            if hasattr(mount, 'metadata'):
                riders = mount.metadata.get("riders", [])
                rider_id = rider.entity_id if hasattr(rider, 'entity_id') else id(rider)
                if rider_id not in riders:
                    riders.append(rider_id)
                    mount.metadata["riders"] = riders

            if hasattr(rider, 'x') and hasattr(mount, 'x'):
                rider.x = mount.x
                rider.y = mount.y + 1.0
                rider.z = mount.z

                from handlers.play.join import _send_synchronize_position
                if isinstance(rider, Connection):
                    await _send_synchronize_position(rider)

            await ctx.reply("[PyMC] 已将实体骑乘到目标上")
            return SUCCESS

        if action == "dismount":
            if hasattr(rider, 'metadata'):
                rider.metadata.pop("riding", None)
            await ctx.reply("[PyMC] 已让实体下骑")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd_ride = Command(
        name="ride",
        description="让实体骑乘或下骑",
        usage="ride <骑乘者> <mount|dismount> [坐骑]",
        permission="command.ride",
        category="entity",
    )
    cmd_ride._execute_func = _ride
    manager.register(cmd_ride)

    # --- /spreadplayers ---
    async def _spreadplayers(ctx: CommandContext) -> int:
        import math
        import random

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

    cmd_spreadplayers = Command(
        name="spreadplayers",
        description="将玩家分散到区域中",
        usage="spreadplayers <x> <z> <最大距离> <尊重团队> <目标>",
        permission="command.spreadplayers",
        category="entity",
    )
    cmd_spreadplayers._execute_func = _spreadplayers
    manager.register(cmd_spreadplayers)
