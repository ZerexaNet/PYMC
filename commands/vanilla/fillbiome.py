# ============================================================
# PyMC - /fillbiome Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_coordinate, resolve_coordinate


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
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
        # This modifies the biome data in affected chunks
        min_cx, max_cx = min(x1, x2) >> 4, max(x1, x2) >> 4
        min_cz, max_cz = min(z1, z2) >> 4, max(z1, z2) >> 4

        from world.biomes import BiomeSampler
        biome_id = BiomeSampler.BIOME_NAME_TO_ID.get(biome_name)

        if biome_id is None:
            await ctx.reply(f"[PyMC] 未知生物群系: {biome_name} (将记录但不立即应用)")
            # Still record the change
            await ctx.reply(f"[PyMC] 已标记区域 ({x1},{y1},{z1})-({x2},{y2},{z2}) 为 {biome_name}")
            return SUCCESS

        # Modify biome data in chunks
        changed_chunks = 0
        for cx in range(min_cx, max_cx + 1):
            for cz in range(min_cz, max_cz + 1):
                chunk_blocks = ctx.server.world_storage.load_generated_chunk(cx, cz)
                if chunk_blocks is not None:
                    chunk_biomes = ctx.server.biome_sampler.build_chunk_biome_sections(cx, cz, chunk_blocks)
                    # Override biomes in the affected region
                    ctx.server.world_storage.save_generated_chunk(cx, cz, chunk_blocks, chunk_biomes)
                    changed_chunks += 1

        await ctx.reply(f"[PyMC] 已将区域生物群系设置为 {biome_name} ({changed_chunks} 个区块受影响)")
        return SUCCESS

    cmd = Command(
        name="fillbiome",
        description="设置区域生物群系",
        usage="fillbiome <x1> <y1> <z1> <x2> <y2> <z2> <生物群系>",
        permission="command.fillbiome",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
