# ============================================================
# PyMC - Player Commands
# tp, gamemode, give, clear, kill, xp, effect, enchant
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector


def register(manager):
    """Register all player-related commands."""

    # --- /tp ---
    async def _tp(ctx: CommandContext) -> int:
        from handlers.play.join import _send_synchronize_position

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: /tp <目标> 或 /tp <x> <y> <z> 或 /tp <玩家> <x> <y> <z> 或 /tp <玩家> <目标玩家>")
            return FAILURE

        sender = ctx.sender
        target = sender
        dest = None

        # Try to parse as: /tp <x> <y> <z> (self teleport)
        if len(args) >= 3:
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
                second = args[1]
                if _is_selector_or_player(second) and len(args) < 5:
                    dest_targets = resolve_selector(ctx.server, sender, second)
                    if not dest_targets:
                        await ctx.reply(f"[PyMC] 未找到目标: {second}")
                        return FAILURE
                    dest = dest_targets[0]
                    target.x, target.y, target.z = dest.x, dest.y, dest.z
                    target.yaw, target.pitch = dest.yaw, dest.pitch
                else:
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

    def _tp_suggest(ctx: CommandContext) -> list[str]:
        from network.connection import Connection
        players = ctx.server.get_online_players()
        names = [p.username for p in players]
        return names + ["@a", "@p", "@s", "@r"]

    cmd_tp = Command(
        name="tp",
        description="传送实体到指定位置或目标",
        usage="tp <x> <y> <z> | tp <目标> | tp <实体> <目标>",
        aliases=["teleport"],
        permission="command.tp",
        category="player",
    )
    cmd_tp._execute_func = _tp
    cmd_tp._suggest_func = _tp_suggest
    manager.register(cmd_tp)

    # --- /gamemode ---
    async def _gamemode(ctx: CommandContext) -> int:
        from handlers.play.join import _send_game_event
        from handlers.play.chat import send_system_message

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            if ctx.sender is not None:
                await ctx.reply(f"[PyMC] 当前游戏模式: {ctx.sender.gamemode}")
            else:
                await ctx.reply("[PyMC] 用法: gamemode <模式> [玩家]")
            return SUCCESS

        mode_name = args[0].lower()
        target = ctx.sender

        try:
            from commands.arguments import parse_gamemode
            mode, normalized = parse_gamemode(mode_name)
        except ValueError:
            await ctx.reply("[PyMC] 无效模式，可用值: survival, creative, adventure, spectator (或 s, c, a, sp)")
            return FAILURE

        if len(args) >= 2:
            target = ctx.server.find_player(args[1])
            if target is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE
        elif ctx.sender is None:
            await ctx.reply("[PyMC] 用法: gamemode <模式> <玩家>")
            return FAILURE

        mode_names_cn = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
        target.gamemode = normalized
        await _send_game_event(target, 3, float(mode))
        await send_system_message(target, f"[PyMC] 游戏模式已切换为 {mode_names_cn.get(mode, '未知')}")
        if ctx.sender is not target:
            await ctx.reply(f"[PyMC] 已将 {target.username} 的游戏模式切换为 {mode_names_cn.get(mode, '未知')}")
        return SUCCESS

    def _gamemode_suggest(ctx: CommandContext) -> list[str]:
        return ["survival", "creative", "adventure", "spectator"]

    cmd_gamemode = Command(
        name="gamemode",
        description="切换游戏模式",
        usage="gamemode <survival|creative|adventure|spectator> [玩家]",
        aliases=[],
        permission="command.gamemode",
        category="player",
    )
    cmd_gamemode._execute_func = _gamemode
    cmd_gamemode._suggest_func = _gamemode_suggest
    manager.register(cmd_gamemode)

    # --- /give ---
    async def _give(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: give <玩家> <物品> [数量]")
            return FAILURE

        target = ctx.sender
        target_spec = args[0]
        if ctx.sender is None or target_spec != ctx.sender.username:
            targets = resolve_selector(ctx.server, ctx.sender, target_spec)
            if targets:
                for t in targets:
                    if isinstance(t, Connection):
                        target = t
                        break
                if target is None and ctx.sender is None:
                    await ctx.reply(f"[PyMC] 未找到玩家: {target_spec}")
                    return FAILURE

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: give <玩家> <物品> [数量]")
            return FAILURE

        item_name = args[1].lower()
        if ":" not in item_name:
            item_name = f"minecraft:{item_name}"

        count = 1
        if len(args) >= 3:
            try:
                count = int(args[2])
                count = max(1, min(64, count))
            except ValueError:
                await ctx.reply("[PyMC] 数量格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未找到目标玩家")
            return FAILURE

        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            try:
                slot = target.inventory_obj.add_item(item_name, count)
                target.inventory_state_id += 1
                if slot is not None:
                    await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count}")
                    return SUCCESS
            except Exception:
                await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count} (物品栏暂未完全同步)")
                return SUCCESS

        await ctx.reply(f"[PyMC] 已给予 {target.username} {item_name} x{count}")
        return SUCCESS

    def _give_suggest(ctx: CommandContext) -> list[str]:
        from commands.vanilla.give import KNOWN_ITEMS
        tokens = ctx.input_string.split()
        if len(tokens) <= 2:
            partial = tokens[1] if len(tokens) > 1 else ""
            return [i for i in KNOWN_ITEMS if i.startswith(partial)]
        return []

    cmd_give = Command(
        name="give",
        description="给予玩家物品",
        usage="give <玩家> <物品> [数量]",
        permission="command.give",
        category="player",
    )
    cmd_give._execute_func = _give
    cmd_give._suggest_func = _give_suggest
    manager.register(cmd_give)

    # --- /clear ---
    async def _clear(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        target = ctx.sender
        item_filter = None
        max_count = -1

        if args:
            targets = resolve_selector(ctx.server, ctx.sender, args[0])
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[0]}")
                return FAILURE

        if len(args) >= 2:
            item_filter = args[1].lower()
            if ":" not in item_filter:
                item_filter = f"minecraft:{item_filter}"

        if len(args) >= 3:
            try:
                max_count = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 数量格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未指定目标玩家")
            return FAILURE

        cleared = 0
        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            cleared = target.inventory_obj.clear_items(item_filter=item_filter, max_count=max_count)
            target.inventory_state_id += 1

        if item_filter:
            await ctx.reply(f"[PyMC] 已清除 {target.username} 的 {item_filter} x{cleared}")
        else:
            await ctx.reply(f"[PyMC] 已清除 {target.username} 的物品栏 (共 {cleared} 个物品)")
        return SUCCESS

    cmd_clear = Command(
        name="clear",
        description="清除玩家物品栏",
        usage="clear [玩家] [物品] [最大数量]",
        permission="command.clear",
        category="player",
    )
    cmd_clear._execute_func = _clear
    manager.register(cmd_clear)

    # --- /kill ---
    async def _kill(ctx: CommandContext) -> int:
        from handlers.play.entities import broadcast_entity_remove
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            if ctx.sender is None:
                await ctx.reply("[PyMC] 用法: kill <实体>")
                return FAILURE
            ctx.sender.health = 0.0
            from handlers.play.join import _send_update_health
            await _send_update_health(ctx.sender)
            await ctx.reply("[PyMC] 你已经死了")
            return SUCCESS

        target_spec = args[0]
        targets = resolve_selector(ctx.server, ctx.sender, target_spec)
        if not targets:
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

    def _kill_suggest(ctx: CommandContext) -> list[str]:
        return ["@a", "@p", "@e", "@s", "@r"]

    cmd_kill = Command(
        name="kill",
        description="击杀实体",
        usage="kill <目标>",
        permission="command.kill",
        category="player",
    )
    cmd_kill._execute_func = _kill
    cmd_kill._suggest_func = _kill_suggest
    manager.register(cmd_kill)

    # --- /xp ---
    async def _xp(ctx: CommandContext) -> int:
        from handlers.play.join import _add_player_experience
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: xp <数量> [玩家] 或 xp set <玩家> <数量> [levels|points]")
            return FAILURE

        sub = args[0].lower()

        if sub in ("set", "add"):
            if len(args) < 3:
                await ctx.reply(f"[PyMC] 用法: xp {sub} <玩家> <数量> [levels|points]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE

            try:
                amount = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 经验数量格式无效")
                return FAILURE

            unit = "points"
            if len(args) >= 4:
                unit = args[3].lower()

            for player in players:
                if unit == "levels":
                    if sub == "set":
                        player.experience_level = max(0, amount)
                        player.experience_progress = 0.0
                    else:
                        player.experience_level = max(0, player.experience_level + amount)
                else:
                    if sub == "add":
                        await _add_player_experience(player, amount)
                    elif sub == "set":
                        player.experience_total = max(0, amount)

            names = ", ".join(p.username for p in players)
            action = "设置为" if sub == "set" else "添加了"
            unit_cn = "级" if unit == "levels" else "点"
            await ctx.reply(f"[PyMC] 已{action} {names} {abs(amount)} {unit_cn}经验")
            return SUCCESS

        try:
            amount = int(args[0])
        except ValueError:
            await ctx.reply("[PyMC] 经验数量格式无效")
            return FAILURE

        target = ctx.sender
        if len(args) >= 2:
            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {args[1]}")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未指定目标")
            return FAILURE

        if amount < 0:
            await ctx.reply("[PyMC] 暂不支持扣除经验")
            return FAILURE

        await _add_player_experience(target, amount)
        await ctx.reply(f"[PyMC] 获得 {amount} 点经验")
        return SUCCESS

    cmd_xp = Command(
        name="xp",
        description="设置或添加经验",
        usage="xp <数量> [玩家] | xp <set|add> <玩家> <数量> [levels|points]",
        aliases=["experience"],
        permission="command.xp",
        category="player",
    )
    cmd_xp._execute_func = _xp
    manager.register(cmd_xp)

    # --- /effect ---
    from commands.arguments import parse_effect_name, EFFECT_NAMES

    # In-memory active effects per player
    _active_effects: dict[str, dict[str, dict]] = {}

    async def _effect(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: effect give <目标> <效果> [秒数] [放大器] [是否环境] | effect clear <目标> [效果]")
            return FAILURE

        sub = args[0].lower()

        if sub == "give":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: effect give <目标> <效果> [秒数] [放大器]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE

            try:
                effect_name = parse_effect_name(args[2])
            except ValueError as e:
                await ctx.reply(f"[PyMC] {e}")
                return FAILURE

            duration = 600
            if len(args) >= 4:
                try:
                    duration = int(args[3]) * 20
                    if duration == 0:
                        duration = 600
                except ValueError:
                    await ctx.reply("[PyMC] 持续时间格式无效")
                    return FAILURE

            amplifier = 0
            if len(args) >= 5:
                try:
                    amplifier = int(args[4])
                    amplifier = max(0, min(255, amplifier))
                except ValueError:
                    await ctx.reply("[PyMC] 放大器格式无效")
                    return FAILURE

            ambient = False
            if len(args) >= 6:
                ambient = args[5].lower() in ("true", "1", "yes")

            for player in players:
                if player.username not in _active_effects:
                    _active_effects[player.username] = {}
                _active_effects[player.username][effect_name] = {
                    "amplifier": amplifier,
                    "duration": duration,
                    "ambient": ambient,
                    "effect_id": EFFECT_NAMES.get(effect_name, 0),
                }

            names = ", ".join(p.username for p in players)
            await ctx.reply(f"[PyMC] 已给予 {names} {effect_name} 效果 (等级 {amplifier + 1}, {duration // 20}秒)")
            return SUCCESS

        elif sub == "clear":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: effect clear <目标> [效果]")
                return FAILURE

            targets = resolve_selector(ctx.server, ctx.sender, args[1])
            players = [t for t in targets if isinstance(t, Connection)]
            if not players:
                await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
                return FAILURE

            effect_to_clear = None
            if len(args) >= 3:
                try:
                    effect_to_clear = parse_effect_name(args[2])
                except ValueError:
                    await ctx.reply(f"[PyMC] 未知效果: {args[2]}")
                    return FAILURE

            total_cleared = 0
            for player in players:
                if player.username in _active_effects:
                    if effect_to_clear:
                        if effect_to_clear in _active_effects[player.username]:
                            del _active_effects[player.username][effect_to_clear]
                            total_cleared += 1
                    else:
                        total_cleared += len(_active_effects[player.username])
                        _active_effects[player.username] = {}

            names = ", ".join(p.username for p in players)
            if effect_to_clear:
                await ctx.reply(f"[PyMC] 已清除 {names} 的 {effect_to_clear} 效果")
            else:
                await ctx.reply(f"[PyMC] 已清除 {names} 的所有效果 (共 {total_cleared} 个)")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: effect <give|clear> ...")
        return FAILURE

    def _effect_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["give", "clear"]
        if len(tokens) >= 3 and tokens[1] == "give":
            if len(tokens) == 3:
                return ["@a", "@p", "@s"]
            if len(tokens) == 4:
                return list(EFFECT_NAMES.keys())
        return []

    cmd_effect = Command(
        name="effect",
        description="给予或清除状态效果",
        usage="effect give <目标> <效果> [秒数] [放大器] | effect clear <目标> [效果]",
        permission="command.effect",
        category="player",
    )
    cmd_effect._execute_func = _effect
    cmd_effect._suggest_func = _effect_suggest
    manager.register(cmd_effect)

    # --- /enchant ---
    from commands.arguments import parse_enchantment_name, ENCHANTMENT_NAMES

    async def _enchant(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: enchant <目标> <附魔> [等级]")
            return FAILURE

        target = ctx.sender
        target_spec = args[0]

        if ctx.sender is None or (len(args) >= 2 and not _is_number(args[1]) and args[1].lower() not in ENCHANTMENT_NAMES):
            targets = resolve_selector(ctx.server, ctx.sender, target_spec)
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]
            elif ctx.sender is None:
                await ctx.reply(f"[PyMC] 未找到目标: {target_spec}")
                return FAILURE

        enchant_idx = 1 if target != ctx.sender else 0
        if enchant_idx >= len(args):
            await ctx.reply("[PyMC] 用法: enchant <目标> <附魔> [等级]")
            return FAILURE

        try:
            enchant_name = parse_enchantment_name(args[enchant_idx])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        level = 1
        if len(args) > enchant_idx + 1:
            try:
                level = int(args[enchant_idx + 1])
                level = max(1, min(255, level))
            except ValueError:
                await ctx.reply("[PyMC] 等级格式无效")
                return FAILURE

        if target is None:
            await ctx.reply("[PyMC] 未找到目标")
            return FAILURE

        if hasattr(target, 'inventory_obj') and target.inventory_obj is not None:
            slot = target.selected_hotbar_slot
            item = target.inventory_obj.get_item_in_slot(slot)
            if item is not None:
                if "enchantments" not in item:
                    item["enchantments"] = {}
                item["enchantments"][enchant_name] = level
                await ctx.reply(f"[PyMC] 已附魔 {target.username} 手持物品: {enchant_name} {level}")
                return SUCCESS
            else:
                await ctx.reply(f"[PyMC] {target.username} 手中没有物品")
                return FAILURE

        await ctx.reply(f"[PyMC] 已附魔 {target.username}: {enchant_name} {level}")
        return SUCCESS

    def _enchant_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) >= 3:
            partial = tokens[-1] if tokens[-1] else ""
            return [e for e in ENCHANTMENT_NAMES if e.startswith(partial)]
        return []

    cmd_enchant = Command(
        name="enchant",
        description="给手持物品添加附魔",
        usage="enchant <目标> <附魔> [等级]",
        permission="command.enchant",
        category="player",
    )
    cmd_enchant._execute_func = _enchant
    cmd_enchant._suggest_func = _enchant_suggest
    manager.register(cmd_enchant)


    # --- /damage ---
    from commands.arguments import parse_damage_type

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
        category="player",
    )
    cmd_damage._execute_func = _damage
    manager.register(cmd_damage)


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_selector_or_player(s: str) -> bool:
    return s.startswith("@") or not _is_number(s)
