# ============================================================
# PyMC - /attribute Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


# Known attributes
ATTRIBUTES = {
    "generic.max_health": {"default": 20.0, "min": 0.0, "max": 1024.0},
    "generic.knockback_resistance": {"default": 0.0, "min": 0.0, "max": 1.0},
    "generic.movement_speed": {"default": 0.7, "min": 0.0, "max": 1024.0},
    "generic.attack_damage": {"default": 2.0, "min": 0.0, "max": 2048.0},
    "generic.armor": {"default": 0.0, "min": 0.0, "max": 30.0},
    "generic.armor_toughness": {"default": 0.0, "min": 0.0, "max": 20.0},
    "generic.luck": {"default": 0.0, "min": -1024.0, "max": 1024.0},
    "generic.follow_range": {"default": 16.0, "min": 0.0, "max": 2048.0},
    "generic.attack_speed": {"default": 4.0, "min": 0.0, "max": 1024.0},
    "generic.flying_speed": {"default": 0.4, "min": 0.0, "max": 1024.0},
    "horse.jump_strength": {"default": 0.7, "min": 0.0, "max": 2.0},
    "zombie.spawn_reinforcements": {"default": 0.0, "min": 0.0, "max": 1.0},
}

# In-memory attribute modifiers
_attribute_modifiers: dict[int, dict[str, list[dict]]] = {}  # entity_id -> {attribute -> [modifiers]}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: attribute <目标> <属性> <get|set|base|modifier> ...")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[0])
        if not targets:
            await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
            return FAILURE
        target = targets[0]

        attr_name = args[1].lower()
        if ":" not in attr_name:
            attr_name = f"minecraft:{attr_name}"

        if attr_name.replace("minecraft:", "") not in {a.replace("generic.", "") for a in ATTRIBUTES} and attr_name not in ATTRIBUTES:
            # Allow custom attributes
            pass

        if len(args) < 3:
            await ctx.reply("[PyMC] 用法: attribute <目标> <属性> <get|set|base|modifier> ...")
            return FAILURE

        action = args[2].lower()

        if action == "get":
            # Get base value
            base_val = _get_attribute_base(target, attr_name)
            scale = float(args[3]) if len(args) >= 4 else 1.0
            await ctx.reply(f"[PyMC] {attr_name} = {base_val * scale:.4f}")
            return SUCCESS

        if action == "set":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: attribute <目标> <属性> set <值>")
                return FAILURE
            try:
                value = float(args[3])
            except ValueError:
                await ctx.reply("[PyMC] 值格式无效")
                return FAILURE
            _set_attribute_base(target, attr_name, value)
            await ctx.reply(f"[PyMC] 已设置 {attr_name} = {value}")
            return SUCCESS

        if action == "base":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: attribute <目标> <属性> base <get|set> [值]")
                return FAILURE
            sub = args[3].lower()
            if sub == "get":
                base_val = _get_attribute_base(target, attr_name)
                scale = float(args[4]) if len(args) >= 5 else 1.0
                await ctx.reply(f"[PyMC] {attr_name} 基础值 = {base_val * scale:.4f}")
            elif sub == "set":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: attribute <目标> <属性> base set <值>")
                    return FAILURE
                try:
                    value = float(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 值格式无效")
                    return FAILURE
                _set_attribute_base(target, attr_name, value)
                await ctx.reply(f"[PyMC] 已设置 {attr_name} 基础值 = {value}")
            return SUCCESS

        if action == "modifier":
            await ctx.reply("[PyMC] attribute modifier 暂未完全实现")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd = Command(
        name="attribute",
        description="修改实体属性",
        usage="attribute <目标> <属性> <get|set|base|modifier> ...",
        permission="command.attribute",
    )
    cmd._execute_func = _execute
    manager.register(cmd)


def _get_attribute_base(entity, attr_name: str) -> float:
    """Get the base value of an attribute for an entity."""
    from network.connection import Connection
    from world.entities import MobEntity

    attr_key = attr_name.replace("minecraft:", "")
    info = ATTRIBUTES.get(attr_key, ATTRIBUTES.get(f"generic.{attr_key}"))

    if isinstance(entity, Connection):
        if "max_health" in attr_key:
            return entity.health
        return info["default"] if info else 0.0
    elif isinstance(entity, MobEntity):
        if "max_health" in attr_key:
            return entity.max_health
        if "follow_range" in attr_key:
            return entity.profile.get("follow_range", 16.0)
        if "attack_damage" in attr_key:
            return entity.profile.get("attack_damage", 2.0)
        if "movement_speed" in attr_key:
            return entity.profile.get("speed", 0.05)
        return info["default"] if info else 0.0
    return 0.0


def _set_attribute_base(entity, attr_name: str, value: float):
    """Set the base value of an attribute for an entity."""
    from network.connection import Connection
    from world.entities import MobEntity

    attr_key = attr_name.replace("minecraft:", "")

    if isinstance(entity, Connection):
        if "max_health" in attr_key:
            entity.health = value
    elif isinstance(entity, MobEntity):
        if "max_health" in attr_key:
            entity.max_health = value
            entity.health = min(entity.health, value)
