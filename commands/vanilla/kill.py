# ============================================================
# PyMC - /kill Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.entities import broadcast_entity_remove
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            if ctx.sender is None:
                await ctx.reply("[PyMC] 用法: kill <实体>")
                return FAILURE
            # Kill self
            ctx.sender.health = 0.0
            from handlers.play.join import _send_update_health
            await _send_update_health(ctx.sender)
            await ctx.reply("[PyMC] 你已经死了")
            return SUCCESS

        target_spec = args[0]

        # Use selector system
        targets = resolve_selector(ctx.server, ctx.sender, target_spec)
        if not targets:
            # Maybe it's an entity ID
            try:
                entity_id = int(target_spec)
                entity = ctx.server.entity_manager.remove_entity(entity_id)
                if entity is not None:
                    await broadcast_entity_remove(ctx.server, [entity_id])
                    await ctx.reply(f"[PyMC] 已移除实体 #{entity_id} ({entity.kind})")
                    return SUCCESS
                await ctx.reply(f"[PyMC] 未找到实体: {entity_id}")
                return FAILURE
            except ValueError:
                await ctx.reply(f"[PyMC] 未找到目标: {target_spec}")
                return FAILURE

        # Kill all matched targets
        killed_count = 0
        entity_ids = []
        for target in targets:
            if isinstance(target, Connection):
                target.health = 0.0
                from handlers.play.join import _send_update_health
                await _send_update_health(target)
                killed_count += 1
            else:
                entity_ids.append(target.entity_id)
                ctx.server.entity_manager.remove_entity(target.entity_id)
                killed_count += 1

        if entity_ids:
            await broadcast_entity_remove(ctx.server, entity_ids)

        await ctx.reply(f"[PyMC] 已击杀 {killed_count} 个目标")
        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        return ["@a", "@p", "@e", "@s", "@r"]

    cmd = Command(
        name="kill",
        description="击杀实体",
        usage="kill <目标>",
        permission="command.kill",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
