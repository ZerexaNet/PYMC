# ============================================================
# PyMC - /tag Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


# Tag storage: entity_id -> set of tags
_entity_tags: dict[int, set[str]] = {}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 3:
            await ctx.reply("[PyMC] 用法: tag <目标> <add|remove|list> <标签名>")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[0])
        if not targets:
            await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
            return FAILURE

        action = args[1].lower()
        tag_name = args[2] if len(args) >= 3 else None

        if action == "add":
            if not tag_name:
                await ctx.reply("[PyMC] 用法: tag <目标> add <标签名>")
                return FAILURE
            for target in targets:
                eid = getattr(target, 'entity_id', id(target))
                if eid not in _entity_tags:
                    _entity_tags[eid] = set()
                    # Also attach _tags attribute to the entity
                _entity_tags[eid].add(tag_name)
                if hasattr(target, '_tags'):
                    target._tags.add(tag_name)
                else:
                    target._tags = {tag_name}
            await ctx.reply(f"[PyMC] 已添加标签 '{tag_name}' 到 {len(targets)} 个实体")
            return SUCCESS

        if action == "remove":
            if not tag_name:
                await ctx.reply("[PyMC] 用法: tag <目标> remove <标签名>")
                return FAILURE
            for target in targets:
                eid = getattr(target, 'entity_id', id(target))
                if eid in _entity_tags:
                    _entity_tags[eid].discard(tag_name)
                if hasattr(target, '_tags'):
                    target._tags.discard(tag_name)
            await ctx.reply(f"[PyMC] 已移除标签 '{tag_name}' 从 {len(targets)} 个实体")
            return SUCCESS

        if action == "list":
            for target in targets:
                eid = getattr(target, 'entity_id', id(target))
                tags = _entity_tags.get(eid, set())
                if hasattr(target, '_tags'):
                    tags = tags | target._tags
                name = getattr(target, 'username', f"实体#{eid}")
                tag_list = ", ".join(sorted(tags)) if tags else "无"
                await ctx.reply(f"[PyMC] {name} 的标签: {tag_list}")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd = Command(
        name="tag",
        description="管理实体标签",
        usage="tag <目标> <add|remove|list> <标签名>",
        permission="command.tag",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
