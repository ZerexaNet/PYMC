# ============================================================
# PyMC - /tp Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.join import _send_synchronize_position

        tokens = ctx.arguments.get("_raw_tokens", [])
        # Remove command name
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: /tp <目标> 或 /tp <x> <y> <z> 或 /tp <玩家> <x> <y> <z> 或 /tp <玩家> <目标玩家>")
            return FAILURE

        sender = ctx.sender

        # Determine the target and destination
        target = sender  # Who to teleport
        dest = None      # Where to teleport to

        # Try to parse as: /tp <x> <y> <z> (self teleport)
        if len(args) >= 3:
            # Check if first arg is a coordinate or selector
            first = args[0]
            is_coord = first.startswith("~") or first.startswith("^") or _is_number(first)

            if is_coord and sender is not None:
                # /tp <x> <y> <z>
                try:
                    from commands.arguments import parse_coordinate, resolve_coordinate
                    bx, by, bz = sender.x, sender.y, sender.z
                    x = resolve_coordinate(parse_coordinate(args[0]), bx)
                    y = resolve_coordinate(parse_coordinate(args[1]), by)
                    z = resolve_coordinate(parse_coordinate(args[2]), bz)
                except (ValueError, IndexError):
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE

                # Check for rotation
                yaw = sender.yaw
                pitch = sender.pitch
                if len(args) >= 5:
                    try:
                        yaw = float(args[3])
                        pitch = float(args[4])
                    except ValueError:
                        pass

                target.x, target.y, target.z = x, y, z
                target.yaw, target.pitch = yaw, pitch
                await _send_synchronize_position(target)
                await ctx.reply(f"[PyMC] 已传送到 ({x:.1f}, {y:.1f}, {z:.1f})")
                return SUCCESS

            # Not a coordinate - first arg is a player/selector
            targets = resolve_selector(ctx.server, sender, first)
            if not targets:
                await ctx.reply(f"[PyMC] 未找到目标: {first}")
                return FAILURE
            target = targets[0]

            # Check if remaining args are a destination player or coordinates
            if len(args) >= 4:
                # Could be /tp <player> <x> <y> <z> or /tp <player> <player2>
                second = args[1]
                if _is_selector_or_player(second) and len(args) < 5:
                    # /tp <player> <target_player>
                    dest_targets = resolve_selector(ctx.server, sender, second)
                    if not dest_targets:
                        await ctx.reply(f"[PyMC] 未找到目标: {second}")
                        return FAILURE
                    dest = dest_targets[0]
                    target.x, target.y, target.z = dest.x, dest.y, dest.z
                    target.yaw, target.pitch = dest.yaw, dest.pitch
                else:
                    # /tp <player> <x> <y> <z>
                    try:
                        from commands.arguments import parse_coordinate, resolve_coordinate
                        bx, by, bz = target.x, target.y, target.z
                        x = resolve_coordinate(parse_coordinate(args[1]), bx)
                        y = resolve_coordinate(parse_coordinate(args[2]), by)
                        z = resolve_coordinate(parse_coordinate(args[3]), bz)
                    except (ValueError, IndexError):
                        await ctx.reply("[PyMC] 坐标格式无效")
                        return FAILURE
                    target.x, target.y, target.z = x, y, z

                    yaw = target.yaw
                    pitch = target.pitch
                    if len(args) >= 6:
                        try:
                            yaw = float(args[4])
                            pitch = float(args[5])
                        except ValueError:
                            pass
                    target.yaw, target.pitch = yaw, pitch

                await _send_synchronize_position(target)
                from network.connection import Connection
                target_name = target.username if isinstance(target, Connection) else f"实体#{getattr(target, 'entity_id', '?')}"
                await ctx.reply(f"[PyMC] 已将 {target_name} 传送到 ({target.x:.1f}, {target.y:.1f}, {target.z:.1f})")
                return SUCCESS

        elif len(args) == 1:
            # /tp <target> - teleport self to target
            if sender is None:
                await ctx.reply("[PyMC] 控制台用法: tp <玩家> <x> <y> <z>")
                return FAILURE
            targets = resolve_selector(ctx.server, sender, args[0])
            if not targets:
                await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
                return FAILURE
            dest = targets[0]
            sender.x, sender.y, sender.z = dest.x, dest.y, dest.z
            sender.yaw, sender.pitch = dest.yaw, dest.pitch
            await _send_synchronize_position(sender)
            from network.connection import Connection
            dest_name = dest.username if isinstance(dest, Connection) else f"实体#{getattr(dest, 'entity_id', '?')}"
            await ctx.reply(f"[PyMC] 已传送到 {dest_name}")
            return SUCCESS

        elif len(args) == 2:
            # /tp <entity> <destination>
            src_targets = resolve_selector(ctx.server, sender, args[0])
            if not src_targets:
                await ctx.reply(f"[PyMC] 未找到源目标: {args[0]}")
                return FAILURE
            dest_targets = resolve_selector(ctx.server, sender, args[1])
            if not dest_targets:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE
            target = src_targets[0]
            dest = dest_targets[0]
            target.x, target.y, target.z = dest.x, dest.y, dest.z
            target.yaw, target.pitch = dest.yaw, dest.pitch
            await _send_synchronize_position(target)
            await ctx.reply(f"[PyMC] 已传送实体到目标位置")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: /tp <目标> 或 /tp <x> <y> <z>")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        from network.connection import Connection
        players = ctx.server.get_online_players()
        names = [p.username for p in players]
        return names + ["@a", "@p", "@s", "@r"]

    cmd = Command(
        name="tp",
        description="传送实体到指定位置或目标",
        usage="tp <x> <y> <z> | tp <目标> | tp <实体> <目标>",
        aliases=["teleport"],
        permission="command.tp",
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


def _is_selector_or_player(s: str) -> bool:
    return s.startswith("@") or not _is_number(s)
