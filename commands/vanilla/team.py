# ============================================================
# PyMC - /team Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.vanilla.scoreboard import get_scoreboard_manager


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        # Delegate to scoreboard teams
        sb = get_scoreboard_manager()

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            # List teams
            if not sb.teams:
                await ctx.reply("[PyMC] 没有队伍")
            else:
                for name, team in sb.teams.items():
                    members = ", ".join(team["members"]) or "无"
                    await ctx.reply(f"[PyMC] {name} ({team['display_name']}): {members}")
            return SUCCESS

        action = args[0].lower()

        if action == "add":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: team add <名称> [显示名]")
                return FAILURE
            team_name = args[1]
            display_name = " ".join(args[2:]) if len(args) >= 3 else team_name
            try:
                sb.create_team(team_name, display_name)
                await ctx.reply(f"[PyMC] 已创建队伍: {team_name}")
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE
            return SUCCESS

        if action == "remove":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: team remove <名称>")
                return FAILURE
            try:
                sb.remove_team(args[1])
                await ctx.reply(f"[PyMC] 已移除队伍: {args[1]}")
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE
            return SUCCESS

        if action == "join":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: team join <队伍> <成员>")
                return FAILURE
            try:
                sb.join_team(args[1], args[2])
                await ctx.reply(f"[PyMC] 已将 {args[2]} 加入队伍 {args[1]}")
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE
            return SUCCESS

        if action == "leave":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: team leave <队伍> <成员>")
                return FAILURE
            try:
                sb.leave_team(args[1], args[2])
                await ctx.reply(f"[PyMC] 已将 {args[2]} 移出队伍 {args[1]}")
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE
            return SUCCESS

        if action == "list":
            if len(args) >= 2:
                team_name = args[1]
                if team_name not in sb.teams:
                    await ctx.reply(f"[PyMC] 队伍不存在: {team_name}")
                    return FAILURE
                members = ", ".join(sb.teams[team_name]["members"]) or "无"
                await ctx.reply(f"[PyMC] 队伍 {team_name} 成员: {members}")
            else:
                for name, team in sb.teams.items():
                    members = ", ".join(team["members"]) or "无"
                    await ctx.reply(f"[PyMC] {name}: {members}")
            return SUCCESS

        if action == "modify":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: team modify <队伍> <属性> <值>")
                return FAILURE
            team_name = args[1]
            if team_name not in sb.teams:
                await ctx.reply(f"[PyMC] 队伍不存在: {team_name}")
                return FAILURE
            prop = args[2].lower()
            value = args[3]
            if prop == "color":
                sb.teams[team_name]["color"] = value.lower()
            elif prop == "displayname":
                sb.teams[team_name]["display_name"] = value
            elif prop == "prefix":
                sb.teams[team_name]["prefix"] = value
            elif prop == "suffix":
                sb.teams[team_name]["suffix"] = value
            elif prop == "friendlyfire":
                sb.teams[team_name]["friendly_fire"] = value.lower() in ("true", "1")
            elif prop == "seeFriendlyInvisibles":
                sb.teams[team_name]["see_friendly_invisibles"] = value.lower() in ("true", "1")
            else:
                await ctx.reply(f"[PyMC] 未知属性: {prop}")
                return FAILURE
            await ctx.reply(f"[PyMC] 已修改队伍 {team_name} 的 {prop}")
            return SUCCESS

        if action == "empty":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: team empty <队伍>")
                return FAILURE
            if args[1] not in sb.teams:
                await ctx.reply(f"[PyMC] 队伍不存在: {args[1]}")
                return FAILURE
            count = len(sb.teams[args[1]]["members"])
            sb.teams[args[1]]["members"] = set()
            await ctx.reply(f"[PyMC] 已清空队伍 {args[1]} ({count} 个成员)")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd = Command(
        name="team",
        description="管理队伍",
        usage="team <add|remove|join|leave|list|modify|empty> ...",
        permission="command.team",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
