# ============================================================
# PyMC - /scoreboard Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_display_slot, parse_criteria


class ScoreboardManager:
    """Manages scoreboard objectives and scores."""

    def __init__(self):
        self.objectives: dict[str, dict] = {}  # name -> {criteria, display_name, display_slot}
        self.scores: dict[str, dict[str, int]] = {}  # objective_name -> {player_name -> score}
        self.teams: dict[str, dict] = {}  # team_name -> {display_name, color, prefix, suffix, friendly_fire, see_friendly, members}
        self.display_slots: dict[str, str | None] = {}  # slot -> objective_name

    def create_objective(self, name: str, criteria: str = "dummy", display_name: str = ""):
        if name in self.objectives:
            raise ValueError(f"Objective '{name}' already exists")
        self.objectives[name] = {
            "criteria": criteria,
            "display_name": display_name or name,
        }
        self.scores[name] = {}

    def remove_objective(self, name: str):
        if name not in self.objectives:
            raise ValueError(f"Objective '{name}' does not exist")
        del self.objectives[name]
        self.scores.pop(name, None)
        # Remove from display slots
        for slot, obj in list(self.display_slots.items()):
            if obj == name:
                self.display_slots[slot] = None

    def set_score(self, objective: str, player: str, score: int):
        if objective not in self.objectives:
            raise ValueError(f"Objective '{objective}' does not exist")
        self.scores[objective][player] = score

    def get_score(self, objective: str, player: str) -> int:
        if objective not in self.objectives:
            return 0
        return self.scores.get(objective, {}).get(player, 0)

    def add_score(self, objective: str, player: str, amount: int) -> int:
        current = self.get_score(objective, player)
        new_score = current + amount
        self.set_score(objective, player, new_score)
        return new_score

    def remove_score(self, objective: str, player: str) -> bool:
        if objective not in self.scores:
            return False
        return self.scores[objective].pop(player, None) is not None

    def set_display(self, slot: str, objective: str | None):
        if objective is not None and objective not in self.objectives:
            raise ValueError(f"Objective '{objective}' does not exist")
        self.display_slots[slot] = objective

    def list_objectives(self) -> list[tuple[str, str, str]]:
        return [(name, obj["criteria"], obj["display_name"]) for name, obj in self.objectives.items()]

    def create_team(self, name: str, display_name: str = ""):
        if name in self.teams:
            raise ValueError(f"Team '{name}' already exists")
        self.teams[name] = {
            "display_name": display_name or name,
            "color": "white",
            "prefix": "",
            "suffix": "",
            "friendly_fire": True,
            "see_friendly_invisibles": False,
            "members": set(),
        }

    def remove_team(self, name: str):
        if name not in self.teams:
            raise ValueError(f"Team '{name}' does not exist")
        del self.teams[name]

    def join_team(self, team_name: str, member: str):
        if team_name not in self.teams:
            raise ValueError(f"Team '{team_name}' does not exist")
        self.teams[team_name]["members"].add(member)

    def leave_team(self, team_name: str, member: str):
        if team_name not in self.teams:
            raise ValueError(f"Team '{team_name}' does not exist")
        self.teams[team_name]["members"].discard(member)


# Global scoreboard instance
_scoreboard_manager = ScoreboardManager()


def get_scoreboard_manager() -> ScoreboardManager:
    return _scoreboard_manager


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: scoreboard <objectives|players|teams> ...")
            return FAILURE

        sb = _scoreboard_manager
        category = args[0].lower()

        # === OBJECTIVES ===
        if category == "objectives":
            if len(args) < 2:
                # List objectives
                objs = sb.list_objectives()
                if not objs:
                    await ctx.reply("[PyMC] 没有记分板目标")
                else:
                    for name, criteria, display in objs:
                        scores = sb.scores.get(name, {})
                        await ctx.reply(f"[PyMC] {name}: {criteria} (显示名: {display}, {len(scores)} 个分数)")
                return SUCCESS

            action = args[1].lower()

            if action == "add":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard objectives add <名称> <条件> [显示名]")
                    return FAILURE
                obj_name = args[2]
                criteria = args[3].lower() if len(args) >= 4 else "dummy"
                display_name = " ".join(args[4:]) if len(args) >= 5 else obj_name
                try:
                    criteria = parse_criteria(criteria)
                    sb.create_objective(obj_name, criteria, display_name)
                    await ctx.reply(f"[PyMC] 已创建新记分板目标: {obj_name}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "remove":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard objectives remove <名称>")
                    return FAILURE
                try:
                    sb.remove_objective(args[2])
                    await ctx.reply(f"[PyMC] 已移除记分板目标: {args[2]}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "setdisplay":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard objectives setdisplay <位置> [目标]")
                    return FAILURE
                try:
                    slot = parse_display_slot(args[2])
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                obj_name = args[3] if len(args) >= 4 else None
                try:
                    sb.set_display(slot, obj_name)
                    if obj_name:
                        await ctx.reply(f"[PyMC] 已将目标 {obj_name} 显示在 {slot}")
                    else:
                        await ctx.reply(f"[PyMC] 已清除 {slot} 的显示目标")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "list":
                objs = sb.list_objectives()
                if not objs:
                    await ctx.reply("[PyMC] 没有记分板目标")
                else:
                    for name, criteria, display in objs:
                        await ctx.reply(f"[PyMC] - {name}: {criteria} ({display})")
                return SUCCESS

        # === PLAYERS ===
        elif category == "players":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: scoreboard players <set|add|remove|get|reset|list|enable|operation> ...")
                return FAILURE

            action = args[1].lower()

            if action == "set":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: scoreboard players set <目标> <目标名> <分数>")
                    return FAILURE
                player = args[2]
                obj_name = args[3]
                try:
                    score = int(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 分数格式无效")
                    return FAILURE
                try:
                    sb.set_score(obj_name, player, score)
                    await ctx.reply(f"[PyMC] 已将 {player} 的 {obj_name} 分数设置为 {score}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "add":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: scoreboard players add <目标> <目标名> <分数>")
                    return FAILURE
                player = args[2]
                obj_name = args[3]
                try:
                    amount = int(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 分数格式无效")
                    return FAILURE
                try:
                    new_score = sb.add_score(obj_name, player, amount)
                    await ctx.reply(f"[PyMC] {player} 的 {obj_name} 分数现在是 {new_score}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "remove":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: scoreboard players remove <目标> <目标名> <分数>")
                    return FAILURE
                player = args[2]
                obj_name = args[3]
                try:
                    amount = int(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 分数格式无效")
                    return FAILURE
                try:
                    new_score = sb.add_score(obj_name, player, -amount)
                    await ctx.reply(f"[PyMC] {player} 的 {obj_name} 分数现在是 {new_score}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "get":
                if len(args) < 4:
                    await ctx.reply("[PyMC] 用法: scoreboard players get <目标> <目标名>")
                    return FAILURE
                player = args[2]
                obj_name = args[3]
                score = sb.get_score(obj_name, player)
                await ctx.reply(f"[PyMC] {player} 的 {obj_name} 分数: {score}")
                return SUCCESS

            if action == "reset":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard players reset <目标> [目标名]")
                    return FAILURE
                player = args[2]
                if len(args) >= 4:
                    obj_name = args[3]
                    sb.remove_score(obj_name, player)
                    await ctx.reply(f"[PyMC] 已重置 {player} 的 {obj_name} 分数")
                else:
                    for obj_name in list(sb.scores.keys()):
                        sb.remove_score(obj_name, player)
                    await ctx.reply(f"[PyMC] 已重置 {player} 的所有分数")
                return SUCCESS

            if action == "list":
                player = args[2] if len(args) >= 3 else None
                if player:
                    found = []
                    for obj_name, scores in sb.scores.items():
                        if player in scores:
                            found.append(f"{obj_name}={scores[player]}")
                    if found:
                        await ctx.reply(f"[PyMC] {player} 的分数: {', '.join(found)}")
                    else:
                        await ctx.reply(f"[PyMC] {player} 没有任何分数")
                else:
                    all_players = set()
                    for scores in sb.scores.values():
                        all_players.update(scores.keys())
                    if all_players:
                        await ctx.reply(f"[PyMC] 跟踪的实体: {', '.join(sorted(all_players))}")
                    else:
                        await ctx.reply("[PyMC] 没有被跟踪的实体")
                return SUCCESS

            if action == "operation":
                if len(args) < 6:
                    await ctx.reply("[PyMC] 用法: scoreboard players operation <目标> <目标名> <操作> <源> <源目标名>")
                    return FAILURE
                target_player = args[2]
                target_obj = args[3]
                op = args[4]
                source_player = args[5]
                source_obj = args[6] if len(args) >= 7 else target_obj

                source_val = sb.get_score(source_obj, source_player)
                target_val = sb.get_score(target_obj, target_player)

                if op == "+=":
                    result = target_val + source_val
                elif op == "-=":
                    result = target_val - source_val
                elif op == "*=":
                    result = target_val * source_val
                elif op == "/=":
                    result = target_val // source_val if source_val != 0 else 0
                elif op == "%=":
                    result = target_val % source_val if source_val != 0 else 0
                elif op == "=":
                    result = source_val
                elif op == "<":
                    result = min(target_val, source_val)
                elif op == ">":
                    result = max(target_val, source_val)
                elif op == "><":
                    # Swap
                    sb.set_score(target_obj, target_player, source_val)
                    sb.set_score(source_obj, source_player, target_val)
                    await ctx.reply(f"[PyMC] 已交换分数")
                    return SUCCESS
                else:
                    await ctx.reply(f"[PyMC] 未知操作: {op}")
                    return FAILURE

                sb.set_score(target_obj, target_player, result)
                await ctx.reply(f"[PyMC] {target_player} 的 {target_obj} = {result}")
                return SUCCESS

            await ctx.reply(f"[PyMC] 未知子命令: scoreboard players {action}")
            return FAILURE

        # === TEAMS ===
        elif category == "teams":
            if len(args) < 2:
                # List teams
                if not sb.teams:
                    await ctx.reply("[PyMC] 没有队伍")
                else:
                    for name, team in sb.teams.items():
                        members = ", ".join(team["members"]) or "无"
                        await ctx.reply(f"[PyMC] {name} ({team['display_name']}): {members}")
                return SUCCESS

            action = args[1].lower()

            if action == "add":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard teams add <名称> [显示名]")
                    return FAILURE
                team_name = args[2]
                display_name = " ".join(args[3:]) if len(args) >= 4 else team_name
                try:
                    sb.create_team(team_name, display_name)
                    await ctx.reply(f"[PyMC] 已创建队伍: {team_name}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "remove":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: scoreboard teams remove <名称>")
                    return FAILURE
                try:
                    sb.remove_team(args[2])
                    await ctx.reply(f"[PyMC] 已移除队伍: {args[2]}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "join":
                if len(args) < 4:
                    await ctx.reply("[PyMC] 用法: scoreboard teams join <队伍> <成员>")
                    return FAILURE
                try:
                    sb.join_team(args[2], args[3])
                    await ctx.reply(f"[PyMC] 已将 {args[3]} 加入队伍 {args[2]}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "leave":
                if len(args) < 4:
                    await ctx.reply("[PyMC] 用法: scoreboard teams leave <队伍> <成员>")
                    return FAILURE
                try:
                    sb.leave_team(args[2], args[3])
                    await ctx.reply(f"[PyMC] 已将 {args[3]} 移出队伍 {args[2]}")
                except ValueError as e:
                    await ctx.reply(f"[PyMC] {e}")
                    return FAILURE
                return SUCCESS

            if action == "list":
                if len(args) >= 3:
                    team_name = args[2]
                    if team_name not in sb.teams:
                        await ctx.reply(f"[PyMC] 队伍不存在: {team_name}")
                        return FAILURE
                    members = ", ".join(sb.teams[team_name]["members"]) or "无"
                    await ctx.reply(f"[PyMC] 队伍 {team_name} 成员: {members}")
                else:
                    for name, team in sb.teams.items():
                        members = ", ".join(team["members"]) or "无"
                        await ctx.reply(f"[PyMC] {name} ({team['display_name']}): {members}")
                return SUCCESS

            if action == "modify":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: scoreboard teams modify <队伍> <属性> <值>")
                    return FAILURE
                team_name = args[2]
                if team_name not in sb.teams:
                    await ctx.reply(f"[PyMC] 队伍不存在: {team_name}")
                    return FAILURE
                prop = args[3].lower()
                value = args[4]
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
                else:
                    await ctx.reply(f"[PyMC] 未知队伍属性: {prop}")
                    return FAILURE
                await ctx.reply(f"[PyMC] 已修改队伍 {team_name} 的 {prop}")
                return SUCCESS

            await ctx.reply(f"[PyMC] 未知子命令: scoreboard teams {action}")
            return FAILURE

        await ctx.reply(f"[PyMC] 用法: scoreboard <objectives|players|teams> ...")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["objectives", "players", "teams"]
        if len(tokens) == 3:
            category = tokens[1].lower()
            if category == "objectives":
                return ["add", "remove", "setdisplay", "list"]
            if category == "players":
                return ["set", "add", "remove", "get", "reset", "list", "operation"]
            if category == "teams":
                return ["add", "remove", "join", "leave", "list", "modify"]
        return []

    cmd = Command(
        name="scoreboard",
        description="管理记分板",
        usage="scoreboard <objectives|players|teams> ...",
        permission="command.scoreboard",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
