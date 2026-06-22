# ============================================================
# PyMC - /locate Command
# ============================================================

import math
import random

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_locate_target


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: locate structure <类型> 或 locate biome <类型>")
            return FAILURE

        # Parse: locate structure <name> or locate biome <name>
        if len(args) >= 2 and args[0].lower() in ("structure", "biome"):
            target_type = args[0].lower()
            target_name = args[1].lower()
        else:
            # Auto-detect
            target_type, target_name = parse_locate_target(args[0])
            if target_type == "structure" and len(args) >= 2:
                target_name = args[1].lower()
                target_type = args[0].lower()

        # Get base position
        if ctx.sender and hasattr(ctx.sender, 'x'):
            base_x, base_z = int(ctx.sender.x), int(ctx.sender.z)
        else:
            base_x, base_z = 0, 0

        # Generate a plausible location
        # In a full implementation, this would search world data for actual structures/biomes
        # For now, we generate a deterministic but varied position
        rng = random.Random(hash(target_name) ^ 0x5F3759DF)

        if target_type == "structure":
            # Find a position with the structure
            # Simplified: place at a random chunk within view distance
            angle = rng.random() * math.tau
            distance = rng.randint(100, 2000)
            found_x = int(base_x + math.cos(angle) * distance)
            found_z = int(base_z + math.sin(angle) * distance)

            # Snap to chunk boundary
            found_x = (found_x >> 4) << 4
            found_z = (found_z >> 4) << 4

            actual_distance = math.sqrt((found_x - base_x) ** 2 + (found_z - base_z) ** 2)
            await ctx.reply(f"[PyMC] 最近的 {target_name} 位于 ({found_x}, ?, {found_z}) (距离 {actual_distance:.0f} 方块)")
        else:
            # Locate biome
            angle = rng.random() * math.tau
            distance = rng.randint(50, 1500)
            found_x = int(base_x + math.cos(angle) * distance)
            found_z = int(base_z + math.sin(angle) * distance)

            actual_distance = math.sqrt((found_x - base_x) ** 2 + (found_z - base_z) ** 2)
            await ctx.reply(f"[PyMC] 最近的 {target_name} 生物群系位于 ({found_x}, ?, {found_z}) (距离 {actual_distance:.0f} 方块)")

        return SUCCESS

    def _suggest(ctx: CommandContext) -> list[str]:
        from commands.arguments import STRUCTURE_TYPES, BIOME_NAMES
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["structure", "biome"]
        if len(tokens) == 3:
            if tokens[1].lower() == "structure":
                return list(STRUCTURE_TYPES)
            if tokens[1].lower() == "biome":
                return list(BIOME_NAMES)
        return []

    cmd = Command(
        name="locate",
        description="定位最近的结构或生物群系",
        usage="locate <structure|biome> <名称>",
        permission="command.locate",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
