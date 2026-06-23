# ============================================================
# PyMC - World Commands
# time, weather, difficulty, seed, setblock, fill, clone,
# setworldspawn, spawnpoint
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import (
    parse_time_value, TIME_PRESETS, parse_weather, parse_difficulty,
    parse_coordinate, resolve_coordinate, parse_fill_mode,
    parse_mask_mode, parse_clone_mode,
)


def register(manager):
    """Register all world-related commands."""

    # --- /time ---
    async def _time(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前时间: {ctx.server.world_time}")
            return SUCCESS

        action = args[0].lower()

        if action == "set" and len(args) >= 2:
            try:
                value = parse_time_value(args[1])
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间值: {args[1]}")
                return FAILURE
            ctx.server.world_time = value
            await ctx.reply(f"[PyMC] 世界时间已设置为 {value}")
            return SUCCESS

        if action == "add" and len(args) >= 2:
            try:
                value = parse_time_value(args[1])
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间值: {args[1]}")
                return FAILURE
            ctx.server.world_time += value
            await ctx.reply(f"[PyMC] 世界时间已变更为 {ctx.server.world_time}")
            return SUCCESS

        if action == "query":
            if len(args) >= 2 and args[1].lower() == "daytime":
                await ctx.reply(f"[PyMC] 白天时间: {ctx.server.world_time % 24000}")
            elif len(args) >= 2 and args[1].lower() == "day":
                await ctx.reply(f"[PyMC] 天数: {ctx.server.world_time // 24000}")
            else:
                await ctx.reply(f"[PyMC] 世界时间: {ctx.server.world_time}")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: time <set|add|query> <值>")
        return FAILURE

    def _time_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["set", "add", "query"]
        if len(tokens) == 3 and tokens[1] == "set":
            return list(TIME_PRESETS.keys())
        if len(tokens) == 3 and tokens[1] == "query":
            return ["daytime", "day", "gametime"]
        return []

    cmd_time = Command(
        name="time",
        description="设置或查询世界时间",
        usage="time <set|add|query> <值>",
        permission="command.time",
        category="world",
    )
    cmd_time._execute_func = _time
    cmd_time._suggest_func = _time_suggest
    manager.register(cmd_time)

    # --- /weather ---
    async def _weather(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前天气: {ctx.server.weather}")
            return SUCCESS

        try:
            weather = parse_weather(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        ctx.server.weather = weather
        duration = 6000
        if len(args) >= 2:
            try:
                duration = int(args[1]) * 20
            except ValueError:
                pass

        await ctx.reply(f"[PyMC] 天气已设置为 {weather}")
        return SUCCESS

    def _weather_suggest(ctx: CommandContext) -> list[str]:
        return ["clear", "rain", "thunder"]

    cmd_weather = Command(
        name="weather",
        description="设置天气",
        usage="weather <clear|rain|thunder> [持续时间(秒)]",
        permission="command.weather",
        category="world",
    )
    cmd_weather._execute_func = _weather
    cmd_weather._suggest_func = _weather_suggest
    manager.register(cmd_weather)

    # --- /difficulty ---
    async def _difficulty(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 当前难度: {ctx.server.config.get('difficulty', 'normal')}")
            return SUCCESS

        try:
            diff_int, diff_name = parse_difficulty(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        ctx.server.config["difficulty"] = diff_name
        ctx.server.save_runtime_config()
        await ctx.reply(f"[PyMC] 难度已设置为 {diff_name}")
        return SUCCESS

    def _difficulty_suggest(ctx: CommandContext) -> list[str]:
        return ["peaceful", "easy", "normal", "hard"]

    cmd_difficulty = Command(
        name="difficulty",
        description="设置游戏难度",
        usage="difficulty <peaceful|easy|normal|hard>",
        permission="command.difficulty",
        category="world",
    )
    cmd_difficulty._execute_func = _difficulty
    cmd_difficulty._suggest_func = _difficulty_suggest
    manager.register(cmd_difficulty)

    # --- /seed ---
    async def _seed(ctx: CommandContext) -> int:
        seed = ctx.server.config.get("level-seed", "")
        await ctx.reply(f"[PyMC] 世界种子: {seed if seed != '' else 0}")
        return SUCCESS

    cmd_seed = Command(
        name="seed",
        description="显示世界种子",
        usage="seed",
        permission="command.seed",
        category="world",
    )
    cmd_seed._execute_func = _seed
    manager.register(cmd_seed)

    # --- /setblock ---
    async def _setblock(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, set_world_block
        from handlers.play.blocks import _broadcast_block_change

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 4:
            await ctx.reply("[PyMC] 用法: setblock <x> <y> <z> <方块>")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z = int(resolve_coordinate(parse_coordinate(args[2]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        block_state = resolve_block_state(args[3])
        if block_state is None:
            await ctx.reply(f"[PyMC] 未知方块: {args[3]}")
            return FAILURE

        changed_chunks = set_world_block(ctx.server, x, y, z, block_state)
        if not changed_chunks:
            await ctx.reply("[PyMC] 方块位置超出世界范围")
            return FAILURE

        await _broadcast_block_change(ctx.server, x, y, z, block_state)
        await ctx.reply(f"[PyMC] 已设置方块 ({x}, {y}, {z}) -> {args[3]}")
        return SUCCESS

    cmd_setblock = Command(
        name="setblock",
        description="设置单个方块",
        usage="setblock <x> <y> <z> <方块>",
        permission="command.setblock",
        category="world",
    )
    cmd_setblock._execute_func = _setblock
    manager.register(cmd_setblock)

    # --- /fill ---
    async def _fill(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, fill_box_detailed
        from handlers.play.blocks import _sync_world_edit

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 7:
            await ctx.reply("[PyMC] 用法: fill <x1> <y1> <z1> <x2> <y2> <z2> <方块> [模式]")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x1 = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y1 = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z1 = int(resolve_coordinate(parse_coordinate(args[2]), bz))
            x2 = int(resolve_coordinate(parse_coordinate(args[3]), bx))
            y2 = int(resolve_coordinate(parse_coordinate(args[4]), by))
            z2 = int(resolve_coordinate(parse_coordinate(args[5]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        block_state = resolve_block_state(args[6])
        if block_state is None:
            await ctx.reply(f"[PyMC] 未知方块: {args[6]}")
            return FAILURE

        fill_mode = "replace"
        arg_index = 7
        if len(args) > arg_index:
            try:
                fill_mode = parse_fill_mode(args[arg_index])
                arg_index += 1
            except ValueError:
                if args[arg_index].lower() != "replace":
                    fill_mode = args[arg_index].lower()
                arg_index += 1

        volume = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
        if volume > 32768:
            await ctx.reply(f"[PyMC] fill 范围过大: {volume} 个方块，当前上限 32768")
            return FAILURE

        changed, changed_chunks, changed_blocks = fill_box_detailed(
            ctx.server, x1, y1, z1, x2, y2, z2, block_state
        )

        await _sync_world_edit(ctx.server, changed_chunks, changed_blocks)
        await ctx.reply(f"[PyMC] 已填充 {changed} 个方块为 {args[6]}")
        return SUCCESS

    cmd_fill = Command(
        name="fill",
        description="填充区域方块",
        usage="fill <x1> <y1> <z1> <x2> <y2> <z2> <方块> [模式]",
        permission="command.fill",
        category="world",
    )
    cmd_fill._execute_func = _fill
    manager.register(cmd_fill)

    # --- /clone ---
    async def _clone(ctx: CommandContext) -> int:
        from world.editing import resolve_block_state, clone_box_detailed
        from handlers.play.blocks import _sync_world_edit

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 9:
            await ctx.reply("[PyMC] 用法: clone <x1> <y1> <z1> <x2> <y2> <z2> <x> <y> <z> [replace|masked|filtered] [normal|force|move]")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x1 = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y1 = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z1 = int(resolve_coordinate(parse_coordinate(args[2]), bz))
            x2 = int(resolve_coordinate(parse_coordinate(args[3]), bx))
            y2 = int(resolve_coordinate(parse_coordinate(args[4]), by))
            z2 = int(resolve_coordinate(parse_coordinate(args[5]), bz))
            dest_x = int(resolve_coordinate(parse_coordinate(args[6]), bx))
            dest_y = int(resolve_coordinate(parse_coordinate(args[7]), by))
            dest_z = int(resolve_coordinate(parse_coordinate(args[8]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        volume = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
        if volume > 32768:
            await ctx.reply(f"[PyMC] clone 范围过大: {volume} 个方块，当前上限 32768")
            return FAILURE

        mask_mode = "replace"
        clone_mode = "normal"
        filter_block_state = None
        arg_index = 9

        if len(args) > arg_index:
            option = args[arg_index].lower()
            if option in ("replace", "masked"):
                mask_mode = option
                arg_index += 1
            elif option == "filtered":
                if len(args) <= arg_index + 1:
                    await ctx.reply("[PyMC] 用法: clone ... filtered <方块> [normal|force|move]")
                    return FAILURE
                mask_mode = "filtered"
                filter_block_state = resolve_block_state(args[arg_index + 1])
                if filter_block_state is None:
                    await ctx.reply(f"[PyMC] 未知方块: {args[arg_index + 1]}")
                    return FAILURE
                arg_index += 2

        if len(args) > arg_index:
            try:
                clone_mode = parse_clone_mode(args[arg_index])
            except ValueError:
                await ctx.reply("[PyMC] clone 模式必须是 normal、force 或 move")
                return FAILURE

        try:
            changed, changed_chunks, changed_blocks = clone_box_detailed(
                ctx.server, x1, y1, z1, x2, y2, z2,
                dest_x, dest_y, dest_z,
                mask_mode=mask_mode,
                clone_mode=clone_mode,
                filter_block_state=filter_block_state,
            )
        except ValueError:
            await ctx.reply("[PyMC] 源区域与目标区域重叠，请使用 force 或 move")
            return FAILURE

        await _sync_world_edit(ctx.server, changed_chunks, changed_blocks)
        await ctx.reply(f"[PyMC] 已复制 {changed} 个方块到 ({dest_x}, {dest_y}, {dest_z})")
        return SUCCESS

    cmd_clone = Command(
        name="clone",
        description="复制区域方块",
        usage="clone <x1> <y1> <z1> <x2> <y2> <z2> <x> <y> <z> [模式]",
        permission="command.clone",
        category="world",
    )
    cmd_clone._execute_func = _clone
    manager.register(cmd_clone)

    # --- /setworldspawn ---
    async def _setworldspawn(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) >= 4:
            try:
                x = int(float(tokens[1]))
                y = int(float(tokens[2]))
                z = int(float(tokens[3]))
            except ValueError:
                await ctx.reply("[PyMC] 用法: setworldspawn <x> <y> <z>")
                return FAILURE
        else:
            x = int(ctx.server.spawn_position[0])
            y = int(ctx.server.spawn_position[1])
            z = int(ctx.server.spawn_position[2])
        ctx.server.spawn_position = (x, y, z)
        ctx.server.save_runtime_config()
        await ctx.reply(f"[PyMC] 世界出生点已设置为 ({x}, {y}, {z})")
        return SUCCESS

    cmd_sws = Command(
        name="setworldspawn",
        description="设置世界出生点",
        usage="setworldspawn [x y z]",
        permission="command.op",
        category="world",
    )
    cmd_sws._execute_func = _setworldspawn
    manager.register(cmd_sws)

    # --- /spawnpoint ---
    async def _spawnpoint(ctx: CommandContext) -> int:
        import math
        tokens = ctx.arguments.get("_raw_tokens", [])
        target = ctx.sender
        coord_index = 1

        if len(tokens) >= 2 and ctx.sender is None:
            target = ctx.server.find_player(tokens[1])
            coord_index = 2
            if target is None:
                await ctx.reply(f"[PyMC] 未找到玩家: {tokens[1]}")
                return FAILURE
        elif len(tokens) >= 2 and ctx.sender is not None:
            maybe_target = ctx.server.find_player(tokens[1])
            if maybe_target is not None:
                target = maybe_target
                coord_index = 2

        if target is None:
            await ctx.reply("[PyMC] 用法: spawnpoint [玩家] [x y z]")
            return FAILURE

        if len(tokens) >= coord_index + 3:
            try:
                spawn_x = int(float(tokens[coord_index]))
                spawn_y = int(float(tokens[coord_index + 1]))
                spawn_z = int(float(tokens[coord_index + 2]))
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
        else:
            spawn_x = math.floor(target.x)
            spawn_y = math.floor(target.y)
            spawn_z = math.floor(target.z)

        target.personal_spawn = (spawn_x, spawn_y, spawn_z)
        ctx.server.save_player_state(target)
        await ctx.reply(f"[PyMC] 已将 {target.username or '玩家'} 的个人出生点设置为 ({spawn_x}, {spawn_y}, {spawn_z})")
        return SUCCESS

    cmd_sp = Command(
        name="spawnpoint",
        description="设置个人出生点",
        usage="spawnpoint [玩家] [x y z]",
        permission="command.op",
        category="world",
    )
    cmd_sp._execute_func = _spawnpoint
    manager.register(cmd_sp)

    # --- /fillbiome ---
    async def _fillbiome(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 7:
            await ctx.reply("[PyMC] 用法: fillbiome <x1> <y1> <z1> <x2> <y2> <z2> <生物群系>")
            return FAILURE

        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        try:
            x1 = int(resolve_coordinate(parse_coordinate(args[0]), bx))
            y1 = int(resolve_coordinate(parse_coordinate(args[1]), by))
            z1 = int(resolve_coordinate(parse_coordinate(args[2]), bz))
            x2 = int(resolve_coordinate(parse_coordinate(args[3]), bx))
            y2 = int(resolve_coordinate(parse_coordinate(args[4]), by))
            z2 = int(resolve_coordinate(parse_coordinate(args[5]), bz))
        except (ValueError, IndexError):
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        biome_name = args[6].lower()
        if ":" not in biome_name:
            biome_name = f"minecraft:{biome_name}"

        # Apply biome to chunks in the region
        min_cx, max_cx = min(x1, x2) >> 4, max(x1, x2) >> 4
        min_cz, max_cz = min(z1, z2) >> 4, max(z1, z2) >> 4

        try:
            from world.biomes import BiomeSampler
            biome_id = BiomeSampler.BIOME_NAME_TO_ID.get(biome_name)
        except ImportError:
            biome_id = None

        if biome_id is None:
            await ctx.reply(f"[PyMC] 未知生物群系: {biome_name} (将记录但不立即应用)")
            await ctx.reply(f"[PyMC] 已标记区域 ({x1},{y1},{z1})-({x2},{y2},{z2}) 为 {biome_name}")
            return SUCCESS

        # Modify biome data in chunks
        changed_chunks = 0
        for cx in range(min_cx, max_cx + 1):
            for cz in range(min_cz, max_cz + 1):
                try:
                    chunk_blocks = ctx.server.world_storage.load_generated_chunk(cx, cz)
                    if chunk_blocks is not None:
                        chunk_biomes = ctx.server.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
                        ctx.server.world_storage.save_generated_chunk(cx, cz, chunk_blocks, chunk_biomes)
                        changed_chunks += 1
                except Exception:
                    pass

        await ctx.reply(f"[PyMC] 已将区域生物群系设置为 {biome_name} ({changed_chunks} 个区块受影响)")
        return SUCCESS

    cmd_fillbiome = Command(
        name="fillbiome",
        description="设置区域生物群系",
        usage="fillbiome <x1> <y1> <z1> <x2> <y2> <z2> <生物群系>",
        permission="command.fillbiome",
        category="world",
    )
    cmd_fillbiome._execute_func = _fillbiome
    manager.register(cmd_fillbiome)
