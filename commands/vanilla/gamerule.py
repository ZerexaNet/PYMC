# ============================================================
# PyMC - /gamerule Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        rules = getattr(ctx.server, "gamerules", {})

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            # List all gamerules
            summary = ", ".join(
                f"{name}={str(value).lower()}"
                for name, value in sorted(rules.items())
            )
            await ctx.reply(f"[PyMC] 游戏规则: {summary}")
            return SUCCESS

        rule_name = args[0]
        if rule_name not in rules:
            known = ", ".join(sorted(rules.keys()))
            await ctx.reply(f"[PyMC] 未知游戏规则: {rule_name}，当前支持: {known}")
            return FAILURE

        if len(args) == 1:
            await ctx.reply(f"[PyMC] {rule_name} = {str(rules[rule_name]).lower()}")
            return SUCCESS

        raw_value = args[1].lower()
        if raw_value not in {"true", "false"}:
            await ctx.reply("[PyMC] 当前 gamerule 仅支持 true/false 值")
            return FAILURE
        rules[rule_name] = raw_value == "true"
        await ctx.reply(f"[PyMC] 游戏规则 {rule_name} 已设置为 {raw_value}")
        return SUCCESS

    cmd = Command(
        name="gamerule",
        description="设置或查询游戏规则",
        usage="gamerule [规则名] [值]",
        permission="command.gamerule",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
