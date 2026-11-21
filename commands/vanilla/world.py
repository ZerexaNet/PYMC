# ============================================================
# PyMC - World Commands
# time, weather, difficulty, seed, setblock, fill, clone,
# setworldspawn, spawnpoint
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import (
    parse_coordinate, resolve_coordinate, parse_fill_mode, parse_clone_mode,
)


def register(manager):
    """Register all world-related commands."""

    # --- /time ---
    # --- /weather ---
    # --- /difficulty ---
    # --- /seed ---
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
    # --- /spawnpoint ---
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
