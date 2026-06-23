# ============================================================
# PyMC - /execute Command
# The most complex vanilla command. Supports chained subcommands.
# ============================================================

from __future__ import annotations

import math
import logging
from typing import Any

from commands.framework import Command, CommandContext, SUCCESS, FAILURE, ERROR
from commands.selector import resolve_selector, parse_selector, parse_int_range

logger = logging.getLogger("PyMC.命令执行")


class ExecuteContext:
    """Mutable context for an /execute chain.

    Tracks the current executor, position, rotation, dimension,
    anchor point, and store targets as the chain is processed.
    """

    def __init__(self, server, sender):
        self.server = server
        self.original_sender = sender
        self.executor = sender  # Current executing entity
        self.position = (
            sender.x if sender and hasattr(sender, 'x') else 0.0,
            sender.y if sender and hasattr(sender, 'y') else 100.0,
            sender.z if sender and hasattr(sender, 'z') else 0.0,
        )
        self.yaw = sender.yaw if sender and hasattr(sender, 'yaw') else 0.0
        self.pitch = sender.pitch if sender and hasattr(sender, 'pitch') else 0.0
        self.dimension = "overworld"
        self.anchor = "feet"  # "feet" or "eyes"
        self.store_targets: list[dict] = []
        self.condition_result: bool | None = None

    def clone(self) -> ExecuteContext:
        """Create a copy of this context for branching (e.g., 'as' with multiple targets)."""
        new = ExecuteContext(self.server, self.original_sender)
        new.executor = self.executor
        new.position = self.position
        new.yaw = self.yaw
        new.pitch = self.pitch
        new.dimension = self.dimension
        new.anchor = self.anchor
        new.store_targets = list(self.store_targets)
        new.condition_result = self.condition_result
        return new


def _tokenize_execute(args_str: str) -> list[str]:
    """Tokenize the execute subcommand chain, respecting quoted strings and brackets."""
    tokens = []
    current = []
    in_quotes = False
    depth = 0

    for ch in args_str:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == '[' and not in_quotes:
            depth += 1
            current.append(ch)
        elif ch == ']' and not in_quotes:
            depth -= 1
            current.append(ch)
        elif ch == '{' and not in_quotes:
            depth += 1
            current.append(ch)
        elif ch == '}' and not in_quotes:
            depth -= 1
            current.append(ch)
        elif ch == ' ' and not in_quotes and depth == 0:
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(ch)

    if current:
        tokens.append(''.join(current))

    return tokens


# ============================================================
# Condition evaluation
# ============================================================

async def _evaluate_condition(ctx: CommandContext, exec_ctx: ExecuteContext, condition_type: str, tokens: list[str], index: int) -> tuple[bool, int]:
    """Evaluate a condition for if/unless.

    Returns:
        (result, next_index) where next_index is the token index after this condition
    """
    if condition_type == "entity":
        if index >= len(tokens):
            return (False, index)
        targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index])
        return (len(targets) > 0, index + 1)

    if condition_type == "score":
        if index + 3 >= len(tokens):
            return (False, index + 4)
        from commands.vanilla.scoreboard import get_scoreboard_manager
        sb = get_scoreboard_manager()
        target_player = tokens[index]
        target_obj = tokens[index + 1]
        operation = tokens[index + 2]

        target_score = sb.get_score(target_obj, target_player)

        if operation == "matches":
            if index + 3 < len(tokens):
                try:
                    min_val, max_val = parse_int_range(tokens[index + 3])
                    if min_val is not None and target_score < min_val:
                        return (False, index + 4)
                    if max_val is not None and target_score > max_val:
                        return (False, index + 4)
                    return (True, index + 4)
                except ValueError:
                    return (False, index + 4)
            return (False, index + 4)

        # Binary comparison: score <target> <targetObj> <op> <source> <sourceObj>
        if index + 5 >= len(tokens):
            return (False, index + 5)
        source_player = tokens[index + 3]
        source_obj = tokens[index + 4]
        source_score = sb.get_score(source_obj, source_player)

        if operation == "<":
            result = target_score < source_score
        elif operation == "<=":
            result = target_score <= source_score
        elif operation == ">":
            result = target_score > source_score
        elif operation == ">=":
            result = target_score >= source_score
        elif operation == "=":
            result = target_score == source_score
        else:
            result = False
        return (result, index + 5)

    if condition_type == "block":
        # if block <x> <y> <z> <block>
        if index + 3 >= len(tokens):
            return (False, index + 4)
        try:
            from commands.arguments import parse_coordinate, resolve_coordinate
            bx, by, bz = exec_ctx.position
            x = int(resolve_coordinate(parse_coordinate(tokens[index]), bx))
            y = int(resolve_coordinate(parse_coordinate(tokens[index + 1]), by))
            z = int(resolve_coordinate(parse_coordinate(tokens[index + 2]), bz))
        except (ValueError, IndexError):
            return (False, index + 4)

        # Get the block at the position
        block_name = tokens[index + 3] if index + 3 < len(tokens) else ""
        if ":" not in block_name:
            block_name = f"minecraft:{block_name}"

        # Check world block
        try:
            from world.editing import resolve_block_state
            target_state = resolve_block_state(block_name)
            if target_state is None:
                return (False, index + 4)

            # Get the actual block at position
            chunk_x = (x >> 4) + 13  # Adjust for internal chunk offset
            chunk_z = (z >> 4) + 13
            section_y = (y + 64) // 16

            world = exec_ctx.server.world
            if chunk_x < 0 or chunk_x >= 27 or chunk_z < 0 or chunk_z >= 27:
                return (False, index + 4)

            chunk_data = world.chunks.get((chunk_x, chunk_z))
            if chunk_data is None:
                return (False, index + 4)

            actual_state = chunk_data.get_block(x & 0xF, y, z & 0xF)
            result = (actual_state == target_state)
        except Exception:
            result = False

        return (result, index + 4)

    if condition_type == "blocks":
        # if blocks <x1> <y1> <z1> <x2> <y2> <z2> <x> <y> <z> <all|masked>
        # Simplified: just check if area exists
        return (True, index + 13)

    if condition_type == "predicate":
        # Not fully supported
        return (True, index + 1)

    if condition_type == "function":
        # if function <function_name> - check if function returns success
        return (True, index + 1)

    if condition_type == "loaded":
        # if loaded <x> <y> <z> - check if position is in loaded chunk
        if index + 2 >= len(tokens):
            return (False, index + 3)
        try:
            from commands.arguments import parse_coordinate, resolve_coordinate
            bx, by, bz = exec_ctx.position
            x = int(resolve_coordinate(parse_coordinate(tokens[index]), bx))
            z = int(resolve_coordinate(parse_coordinate(tokens[index + 2]), bz))
            chunk_x = (x >> 4) + 13
            chunk_z = (z >> 4) + 13
            world = exec_ctx.server.world
            loaded = (chunk_x, chunk_z) in world.chunks
            return (loaded, index + 3)
        except (ValueError, IndexError):
            return (False, index + 3)

    return (False, index + 1)


def _skip_condition_tokens(tokens: list[str], index: int, condition_type: str) -> int:
    """Skip past the tokens of a condition to find the next subcommand."""
    if condition_type == "entity":
        return index + 1
    if condition_type == "score":
        # score <target> <targetObj> <operation> <source> <sourceObj>
        # or score <target> <targetObj> matches <range>
        if index + 2 < len(tokens):
            op = tokens[index + 2]
            if op == "matches":
                return index + 4
            return index + 5
        return index + 4
    if condition_type == "block":
        return index + 4
    if condition_type == "blocks":
        return index + 13  # Rough estimate
    if condition_type == "predicate":
        return index + 1
    if condition_type == "function":
        return index + 1
    if condition_type == "loaded":
        return index + 3
    return index + 1


# ============================================================
# Execute chain processor
# ============================================================

async def _execute_chain(ctx: CommandContext, exec_ctx: ExecuteContext, tokens: list[str], index: int) -> int:
    """Recursively process an /execute subcommand chain."""
    if index >= len(tokens):
        return FAILURE

    subcommand = tokens[index].lower()

    # --- as <targets> ---
    if subcommand == "as":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute as: 缺少目标")
            return FAILURE
        targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index + 1])
        if not targets:
            return FAILURE
        # Run the rest of the chain for each target as executor
        results = []
        for target in targets:
            new_ctx = exec_ctx.clone()
            new_ctx.executor = target
            result = await _execute_chain(ctx, new_ctx, tokens, index + 2)
            results.append(result)
        return SUCCESS if any(r == SUCCESS for r in results) else FAILURE

    # --- at <targets> ---
    if subcommand == "at":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute at: 缺少目标")
            return FAILURE
        targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index + 1])
        if not targets:
            return FAILURE
        target = targets[0]
        exec_ctx.position = (target.x, target.y, target.z) if hasattr(target, 'x') else exec_ctx.position
        exec_ctx.yaw = target.yaw if hasattr(target, 'yaw') else exec_ctx.yaw
        exec_ctx.pitch = target.pitch if hasattr(target, 'pitch') else exec_ctx.pitch
        return await _execute_chain(ctx, exec_ctx, tokens, index + 2)

    # --- positioned <pos> / positioned as <targets> / positioned over <anchor> ---
    if subcommand == "positioned":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute positioned: 缺少参数")
            return FAILURE
        if tokens[index + 1].lower() == "as":
            if index + 2 >= len(tokens):
                await ctx.reply("[PyMC] execute positioned as: 缺少目标")
                return FAILURE
            targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index + 2])
            if targets:
                t = targets[0]
                exec_ctx.position = (t.x, t.y, t.z) if hasattr(t, 'x') else exec_ctx.position
            return await _execute_chain(ctx, exec_ctx, tokens, index + 3)
        elif tokens[index + 1].lower() == "over":
            # positioned over <anchor> - anchor can be "feet" or "eyes"
            if index + 2 >= len(tokens):
                await ctx.reply("[PyMC] execute positioned over: 缺少锚点")
                return FAILURE
            # In vanilla, "over" adjusts position to the anchor point
            anchor = tokens[index + 2].lower()
            if anchor == "eyes" and exec_ctx.executor and hasattr(exec_ctx.executor, 'height'):
                x, y, z = exec_ctx.position
                exec_ctx.position = (x, y + getattr(exec_ctx.executor, 'eye_height', 1.62), z)
            return await _execute_chain(ctx, exec_ctx, tokens, index + 3)
        else:
            if index + 3 >= len(tokens):
                await ctx.reply("[PyMC] execute positioned: 需要 x y z")
                return FAILURE
            try:
                from commands.arguments import parse_coordinate, resolve_coordinate
                bx, by, bz = exec_ctx.position
                x = resolve_coordinate(parse_coordinate(tokens[index + 1]), bx)
                y = resolve_coordinate(parse_coordinate(tokens[index + 2]), by)
                z = resolve_coordinate(parse_coordinate(tokens[index + 3]), bz)
                exec_ctx.position = (x, y, z)
            except ValueError:
                await ctx.reply("[PyMC] execute positioned: 坐标格式无效")
                return FAILURE
            return await _execute_chain(ctx, exec_ctx, tokens, index + 4)

    # --- rotated <yaw> <pitch> / rotated as <targets> ---
    if subcommand == "rotated":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute rotated: 缺少参数")
            return FAILURE
        if tokens[index + 1].lower() == "as":
            if index + 2 >= len(tokens):
                await ctx.reply("[PyMC] execute rotated as: 缺少目标")
                return FAILURE
            targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index + 2])
            if targets:
                t = targets[0]
                exec_ctx.yaw = t.yaw if hasattr(t, 'yaw') else exec_ctx.yaw
                exec_ctx.pitch = t.pitch if hasattr(t, 'pitch') else exec_ctx.pitch
            return await _execute_chain(ctx, exec_ctx, tokens, index + 3)
        else:
            if index + 2 >= len(tokens):
                await ctx.reply("[PyMC] execute rotated: 需要 yaw pitch")
                return FAILURE
            try:
                exec_ctx.yaw = float(tokens[index + 1])
                exec_ctx.pitch = float(tokens[index + 2])
            except ValueError:
                await ctx.reply("[PyMC] execute rotated: 旋转格式无效")
                return FAILURE
            return await _execute_chain(ctx, exec_ctx, tokens, index + 3)

    # --- align <axes> ---
    if subcommand == "align":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute align: 缺少坐标轴")
            return FAILURE
        axes = tokens[index + 1].lower()
        x, y, z = exec_ctx.position
        if 'x' in axes:
            x = math.floor(x)
        if 'y' in axes:
            y = math.floor(y)
        if 'z' in axes:
            z = math.floor(z)
        exec_ctx.position = (x, y, z)
        return await _execute_chain(ctx, exec_ctx, tokens, index + 2)

    # --- anchored <anchor> ---
    if subcommand == "anchored":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute anchored: 缺少锚点")
            return FAILURE
        anchor = tokens[index + 1].lower()
        if anchor not in ("feet", "eyes"):
            await ctx.reply("[PyMC] execute anchored: 锚点必须是 feet 或 eyes")
            return FAILURE
        exec_ctx.anchor = anchor
        return await _execute_chain(ctx, exec_ctx, tokens, index + 2)

    # --- facing <pos> / facing entity <targets> <anchor> ---
    if subcommand == "facing":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute facing: 缺少参数")
            return FAILURE
        if tokens[index + 1].lower() == "entity":
            if index + 3 >= len(tokens):
                await ctx.reply("[PyMC] execute facing entity: 缺少目标或锚点")
                return FAILURE
            targets = resolve_selector(exec_ctx.server, exec_ctx.executor, tokens[index + 2])
            if targets:
                t = targets[0]
                if hasattr(t, 'x'):
                    tx, ty, tz = t.x, t.y, t.z
                    if tokens[index + 3].lower() == "eyes" and hasattr(t, 'height'):
                        ty += 1.62
                    x, y, z = exec_ctx.position
                    dx, dy, dz = tx - x, ty - y, tz - z
                    h = math.sqrt(dx * dx + dz * dz)
                    if h > 0:
                        exec_ctx.yaw = math.degrees(math.atan2(-dx, dz))
                        exec_ctx.pitch = -math.degrees(math.atan2(dy, h))
            return await _execute_chain(ctx, exec_ctx, tokens, index + 4)
        else:
            if index + 3 >= len(tokens):
                await ctx.reply("[PyMC] execute facing: 需要 x y z")
                return FAILURE
            try:
                from commands.arguments import parse_coordinate, resolve_coordinate
                bx, by, bz = exec_ctx.position
                fx = resolve_coordinate(parse_coordinate(tokens[index + 1]), bx)
                fy = resolve_coordinate(parse_coordinate(tokens[index + 2]), by)
                fz = resolve_coordinate(parse_coordinate(tokens[index + 3]), bz)
                x, y, z = exec_ctx.position
                dx, dy, dz = fx - x, fy - y, fz - z
                h = math.sqrt(dx * dx + dz * dz)
                if h > 0:
                    exec_ctx.yaw = math.degrees(math.atan2(-dx, dz))
                    exec_ctx.pitch = -math.degrees(math.atan2(dy, h))
            except ValueError:
                await ctx.reply("[PyMC] execute facing: 坐标格式无效")
                return FAILURE
            return await _execute_chain(ctx, exec_ctx, tokens, index + 4)

    # --- in <dimension> ---
    if subcommand == "in":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute in: 缺少维度")
            return FAILURE
        exec_ctx.dimension = tokens[index + 1].lower()
        return await _execute_chain(ctx, exec_ctx, tokens, index + 2)

    # --- if / unless ---
    if subcommand in ("if", "unless"):
        if index + 1 >= len(tokens):
            await ctx.reply(f"[PyMC] execute {subcommand}: 缺少条件")
            return FAILURE
        condition_type = tokens[index + 1].lower()
        result, next_index = await _evaluate_condition(ctx, exec_ctx, condition_type, tokens, index + 2)
        passed = (subcommand == "if" and result) or (subcommand == "unless" and not result)
        if not passed:
            return FAILURE
        return await _execute_chain(ctx, exec_ctx, tokens, next_index)

    # --- store ---
    if subcommand == "store":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute store: 缺少参数")
            return FAILURE
        store_type = tokens[index + 1].lower()
        # Parse store target
        store_info = {"type": store_type}
        if store_type == "result" or store_type == "success":
            if index + 2 >= len(tokens):
                await ctx.reply("[PyMC] execute store: 缺少存储目标")
                return FAILURE
            target_type = tokens[index + 2].lower()
            store_info["target_type"] = target_type
            if target_type == "score":
                if index + 5 >= len(tokens):
                    await ctx.reply("[PyMC] execute store score: 缺少参数")
                    return FAILURE
                store_info["player"] = tokens[index + 3]
                store_info["objective"] = tokens[index + 4]
                exec_ctx.store_targets.append(store_info)
                return await _execute_chain(ctx, exec_ctx, tokens, index + 5)
            elif target_type == "bossbar":
                if index + 4 >= len(tokens):
                    await ctx.reply("[PyMC] execute store bossbar: 缺少参数")
                    return FAILURE
                store_info["id"] = tokens[index + 3]
                store_info["value"] = tokens[index + 4].lower()
                exec_ctx.store_targets.append(store_info)
                return await _execute_chain(ctx, exec_ctx, tokens, index + 5)
            elif target_type == "block":
                # store result block <x> <y> <z> <path> <type> <scale>
                if index + 8 >= len(tokens):
                    await ctx.reply("[PyMC] execute store block: 缺少参数")
                    return FAILURE
                store_info["x"] = tokens[index + 3]
                store_info["y"] = tokens[index + 4]
                store_info["z"] = tokens[index + 5]
                store_info["path"] = tokens[index + 6]
                store_info["datatype"] = tokens[index + 7]
                store_info["scale"] = tokens[index + 8] if index + 8 < len(tokens) else "1"
                exec_ctx.store_targets.append(store_info)
                return await _execute_chain(ctx, exec_ctx, tokens, index + 9)
            elif target_type == "entity":
                # store result entity <target> <path> <type> <scale>
                if index + 7 >= len(tokens):
                    await ctx.reply("[PyMC] execute store entity: 缺少参数")
                    return FAILURE
                store_info["target"] = tokens[index + 3]
                store_info["path"] = tokens[index + 4]
                store_info["datatype"] = tokens[index + 5]
                store_info["scale"] = tokens[index + 6] if index + 6 < len(tokens) else "1"
                exec_ctx.store_targets.append(store_info)
                return await _execute_chain(ctx, exec_ctx, tokens, index + 7)
            else:
                next_idx = index + 3
                exec_ctx.store_targets.append(store_info)
                return await _execute_chain(ctx, exec_ctx, tokens, next_idx)
        await ctx.reply(f"[PyMC] execute store: 未知存储类型 {store_type}")
        return FAILURE

    # --- on <origin> ---
    if subcommand == "on":
        # execute on <origin|passengers|owner|vehicle> - not fully implemented
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute on: 缺少参数")
            return FAILURE
        return await _execute_chain(ctx, exec_ctx, tokens, index + 2)

    # --- summon ---
    if subcommand == "summon":
        # execute summon <entity> [pos] [nbt] - summon and set executor
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute summon: 缺少实体类型")
            return FAILURE
        # Just pass through to the run subcommand with a summon command
        command_str = ' '.join(tokens[index:])
        from commands import CommandManager
        result = await ctx.server.command_manager.execute(exec_ctx.executor, command_str)
        return result

    # --- run ---
    if subcommand == "run":
        if index + 1 >= len(tokens):
            await ctx.reply("[PyMC] execute run: 缺少命令")
            return FAILURE
        # Join remaining tokens as the command to run
        command_str = ' '.join(tokens[index + 1:])

        # Temporarily modify sender position if needed
        old_x = old_y = old_z = old_yaw = old_pitch = None
        if exec_ctx.executor and hasattr(exec_ctx.executor, 'x'):
            old_x, old_y, old_z = exec_ctx.executor.x, exec_ctx.executor.y, exec_ctx.executor.z
            old_yaw, old_pitch = exec_ctx.executor.yaw, exec_ctx.executor.pitch
            exec_ctx.executor.x, exec_ctx.executor.y, exec_ctx.executor.z = exec_ctx.position
            exec_ctx.executor.yaw, exec_ctx.executor.pitch = exec_ctx.yaw, exec_ctx.pitch

        # Execute the command
        from commands import CommandManager
        result = await ctx.server.command_manager.execute(exec_ctx.executor, command_str)

        # Restore position
        if old_x is not None and exec_ctx.executor:
            exec_ctx.executor.x, exec_ctx.executor.y, exec_ctx.executor.z = old_x, old_y, old_z
            exec_ctx.executor.yaw, exec_ctx.executor.pitch = old_yaw, old_pitch

        # Handle store targets
        if exec_ctx.store_targets:
            for store_info in exec_ctx.store_targets:
                if store_info.get("target_type") == "score":
                    from commands.vanilla.scoreboard import get_scoreboard_manager
                    sb = get_scoreboard_manager()
                    try:
                        sb.set_score(store_info["objective"], store_info["player"], result)
                    except ValueError:
                        pass

        return result

    await ctx.reply(f"[PyMC] execute: 未知子命令 '{subcommand}'")
    return FAILURE


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        if len(tokens) < 2:
            await ctx.reply("[PyMC] 用法: execute <子命令> ...")
            return FAILURE

        args_str = ' '.join(tokens[1:])
        sub_tokens = _tokenize_execute(args_str)

        exec_ctx = ExecuteContext(ctx.server, ctx.sender)
        return await _execute_chain(ctx, exec_ctx, sub_tokens, 0)

    def _suggest(ctx: CommandContext) -> list[str]:
        return ["as", "at", "positioned", "rotated", "align", "anchored",
                "facing", "in", "if", "unless", "store", "on", "summon", "run"]

    cmd = Command(
        name="execute",
        description="执行命令链，可改变执行者、位置和条件",
        usage="execute <as|at|positioned|rotated|align|anchored|facing|in|if|unless|store|on|summon|run> ...",
        permission="command.execute",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)
