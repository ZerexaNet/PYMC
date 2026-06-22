# ============================================================
# PyMC - /ride Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
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

            # Store mount relationship in metadata
            if hasattr(rider, 'metadata'):
                rider.metadata["riding"] = mount.entity_id if hasattr(mount, 'entity_id') else id(mount)
            if hasattr(mount, 'metadata'):
                riders = mount.metadata.get("riders", [])
                rider_id = rider.entity_id if hasattr(rider, 'entity_id') else id(rider)
                if rider_id not in riders:
                    riders.append(rider_id)
                    mount.metadata["riders"] = riders

            # Position rider on top of mount
            if hasattr(rider, 'x') and hasattr(mount, 'x'):
                rider.x = mount.x
                rider.y = mount.y + 1.0
                rider.z = mount.z

                from network.connection import Connection
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

    cmd = Command(
        name="ride",
        description="让实体骑乘或下骑",
        usage="ride <骑乘者> <mount|dismount> [坐骑]",
        permission="command.ride",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
