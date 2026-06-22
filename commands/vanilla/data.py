# ============================================================
# PyMC - /data Command
# Read/modify NBT data of blocks, entities, and storage
# ============================================================

import json
import logging

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector

logger = logging.getLogger("PyMC.数据")


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: data <get|merge|modify|remove> <block|entity|storage> <目标> [路径] [缩放]")
            return FAILURE

        action = args[0].lower()
        if action not in ("get", "merge", "modify", "remove"):
            await ctx.reply(f"[PyMC] 未知操作: {action}")
            return FAILURE

        if len(args) < 2:
            await ctx.reply(f"[PyMC] 用法: data {action} <block|entity|storage> <目标>")
            return FAILURE

        target_type = args[1].lower()

        # === data get ===
        if action == "get":
            if target_type == "entity":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: data get entity <选择器> [路径]")
                    return FAILURE
                targets = resolve_selector(ctx.server, ctx.sender, args[2])
                if not targets:
                    await ctx.reply(f"[PyMC] 未找到实体: {args[2]}")
                    return FAILURE
                target = targets[0]
                path = args[3] if len(args) >= 4 else None

                # Build data from entity attributes
                data = _get_entity_data(target)
                if path:
                    data = _traverse_path(data, path)

                result = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, dict) else str(data)
                await ctx.reply(f"[PyMC] 数据: {result}")
                return SUCCESS

            elif target_type == "block":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: data get block <x> <y> <z> [路径]")
                    return FAILURE
                try:
                    from commands.arguments import parse_coordinate, resolve_coordinate
                    bx, by, bz = 0.0, 100.0, 0.0
                    if ctx.sender and hasattr(ctx.sender, 'x'):
                        bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z
                    x = int(resolve_coordinate(parse_coordinate(args[2]), bx))
                    y = int(resolve_coordinate(parse_coordinate(args[3]), by))
                    z = int(resolve_coordinate(parse_coordinate(args[4]), bz))
                except (ValueError, IndexError):
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE

                block_id = ctx.server.get_block_at(x, y, z)
                if block_id is None:
                    await ctx.reply(f"[PyMC] 位置 ({x}, {y}, {z}) 无方块数据")
                    return FAILURE

                from world.chunk_io import STATE_ID_TO_BLOCK_NAME
                block_name = STATE_ID_TO_BLOCK_NAME.get(block_id, f"unknown({block_id})")
                data = {"block": block_name, "state_id": block_id, "x": x, "y": y, "z": z}

                path = args[5] if len(args) >= 6 else None
                if path:
                    data = _traverse_path(data, path)

                result = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, dict) else str(data)
                await ctx.reply(f"[PyMC] 方块数据: {result}")
                return SUCCESS

            elif target_type == "storage":
                if len(args) < 3:
                    await ctx.reply("[PyMC] 用法: data get storage <名称> [路径]")
                    return FAILURE
                # Storage is not fully implemented, return empty
                await ctx.reply(f"[PyMC] 存储 {args[2]} 无数据 (存储系统暂未实现)")
                return SUCCESS

        # === data merge ===
        if action == "merge":
            if target_type == "entity":
                if len(args) < 4:
                    await ctx.reply("[PyMC] 用法: data merge entity <选择器> <NBT>")
                    return FAILURE
                targets = resolve_selector(ctx.server, ctx.sender, args[2])
                if not targets:
                    await ctx.reply(f"[PyMC] 未找到实体: {args[2]}")
                    return FAILURE
                nbt_str = args[3]
                try:
                    nbt_data = json.loads(nbt_str)
                except json.JSONDecodeError:
                    await ctx.reply("[PyMC] NBT 格式无效")
                    return FAILURE

                # Merge NBT into entity metadata
                for target in targets:
                    if hasattr(target, 'metadata') and isinstance(target.metadata, dict):
                        _deep_merge(target.metadata, nbt_data)

                await ctx.reply(f"[PyMC] 已合并数据到 {len(targets)} 个实体")
                return SUCCESS
            else:
                await ctx.reply(f"[PyMC] data merge {target_type} 暂未完全实现")
                return FAILURE

        # === data modify ===
        if action == "modify":
            await ctx.reply("[PyMC] data modify 暂未完全实现")
            return FAILURE

        # === data remove ===
        if action == "remove":
            if target_type == "entity":
                if len(args) < 4:
                    await ctx.reply("[PyMC] 用法: data remove entity <选择器> <路径>")
                    return FAILURE
                targets = resolve_selector(ctx.server, ctx.sender, args[2])
                path = args[3]
                for target in targets:
                    if hasattr(target, 'metadata') and isinstance(target.metadata, dict):
                        _remove_path(target.metadata, path)
                await ctx.reply(f"[PyMC] 已从 {len(targets)} 个实体移除路径 {path}")
                return SUCCESS
            else:
                await ctx.reply(f"[PyMC] data remove {target_type} 暂未完全实现")
                return FAILURE

        await ctx.reply(f"[PyMC] 用法: data <get|merge|modify|remove> ...")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["get", "merge", "modify", "remove"]
        if len(tokens) == 3:
            return ["block", "entity", "storage"]
        return []

    cmd = Command(
        name="data",
        description="读取或修改 NBT 数据",
        usage="data <get|merge|modify|remove> <block|entity|storage> <目标> [路径]",
        permission="command.data",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)


def _get_entity_data(entity) -> dict:
    """Get serializable data from an entity."""
    from network.connection import Connection
    if isinstance(entity, Connection):
        data = {
            "type": "minecraft:player",
            "username": entity.username,
            "uuid": str(entity.uuid),
            "position": [entity.x, entity.y, entity.z],
            "rotation": [entity.yaw, entity.pitch],
            "gamemode": entity.gamemode,
            "health": entity.health,
            "food": entity.food,
            "experience_level": entity.experience_level,
            "experience_total": entity.experience_total,
            "on_ground": entity.on_ground,
        }
        if entity.inventory_obj is not None:
            data["inventory"] = entity.inventory_obj.serialize()
        return data
    else:
        data = {
            "entity_id": getattr(entity, 'entity_id', -1),
            "type": f"minecraft:{getattr(entity, 'kind', 'unknown')}",
            "position": [getattr(entity, 'x', 0), getattr(entity, 'y', 0), getattr(entity, 'z', 0)],
            "rotation": [getattr(entity, 'yaw', 0), getattr(entity, 'pitch', 0)],
            "alive": getattr(entity, 'alive', False),
        }
        if hasattr(entity, 'mob_type'):
            data["mob_type"] = entity.mob_type
        if hasattr(entity, 'metadata'):
            data["metadata"] = dict(entity.metadata)
        return data


def _traverse_path(data: dict, path: str):
    """Traverse a dot-separated path into a data dict."""
    parts = path.replace(".", " ").replace("[", " ").replace("]", " ").split()
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part, None)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _deep_merge(target: dict, source: dict):
    """Deep merge source into target dict."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _remove_path(data: dict, path: str):
    """Remove a path from a dict."""
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
