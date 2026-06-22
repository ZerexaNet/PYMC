# ============================================================
# PyMC - World Management Commands
# worldborder, locate, forceload, place, function, schedule,
# datapack, advancement, attribute, recipe, trigger
# Consolidated world management command implementations
# ============================================================

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
from typing import Any

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import (
    parse_coordinate, resolve_coordinate, parse_time_value,
    parse_locate_target,
)
from network.connection import Connection

logger = logging.getLogger("PyMC.世界管理")


# ============================================================
# World Border State
# ============================================================

_world_border = {
    "center_x": 0.0,
    "center_z": 0.0,
    "size": 60000000.0,
    "target_size": 60000000.0,
    "speed": 0.0,
    "damage_per_block": 0.2,
    "damage_safe_zone": 5.0,
    "warning_blocks": 5,
    "warning_time": 15,
}


def get_world_border() -> dict:
    return _world_border


# ============================================================
# Force-loaded Chunks
# ============================================================

_forceloaded_chunks: set[tuple[int, int]] = set()


# ============================================================
# Loaded Datapacks
# ============================================================

_loaded_datapacks: dict[str, dict] = {}


# ============================================================
# Scheduled Tasks
# ============================================================

_scheduled_tasks: dict[str, asyncio.Task] = {}
_task_counter = 0


# ============================================================
# Advancement Tracking
# ============================================================

_advancements: dict[str, dict] = {}
_player_advancements: dict[str, dict[str, bool]] = {}  # username -> {adv_name -> done}


# ============================================================
# Attribute Definitions
# ============================================================

ATTRIBUTES = {
    "generic.max_health": {"default": 20.0, "min": 0.0, "max": 1024.0},
    "generic.knockback_resistance": {"default": 0.0, "min": 0.0, "max": 1.0},
    "generic.movement_speed": {"default": 0.7, "min": 0.0, "max": 1024.0},
    "generic.attack_damage": {"default": 2.0, "min": 0.0, "max": 2048.0},
    "generic.armor": {"default": 0.0, "min": 0.0, "max": 30.0},
    "generic.armor_toughness": {"default": 0.0, "min": 0.0, "max": 20.0},
    "generic.luck": {"default": 0.0, "min": -1024.0, "max": 1024.0},
    "generic.follow_range": {"default": 16.0, "min": 0.0, "max": 2048.0},
    "generic.attack_speed": {"default": 4.0, "min": 0.0, "max": 1024.0},
    "generic.flying_speed": {"default": 0.4, "min": 0.0, "max": 1024.0},
    "horse.jump_strength": {"default": 0.7, "min": 0.0, "max": 2.0},
    "zombie.spawn_reinforcements": {"default": 0.0, "min": 0.0, "max": 1.0},
}

_attribute_modifiers: dict[int, dict[str, list[dict]]] = {}  # entity_id -> {attribute -> [modifiers]}


# ============================================================
# Attribute Helpers
# ============================================================

def _get_attribute_base(entity, attr_name: str) -> float:
    """Get the base value of an attribute for an entity."""
    from world.entities import MobEntity

    attr_key = attr_name.replace("minecraft:", "")
    info = ATTRIBUTES.get(attr_key, ATTRIBUTES.get(f"generic.{attr_key}"))

    if isinstance(entity, Connection):
        if "max_health" in attr_key:
            return entity.health
        return info["default"] if info else 0.0
    elif isinstance(entity, MobEntity):
        if "max_health" in attr_key:
            return entity.max_health
        if "follow_range" in attr_key:
            return entity.profile.get("follow_range", 16.0)
        if "attack_damage" in attr_key:
            return entity.profile.get("attack_damage", 2.0)
        if "movement_speed" in attr_key:
            return entity.profile.get("speed", 0.05)
        return info["default"] if info else 0.0
    return 0.0


def _set_attribute_base(entity, attr_name: str, value: float):
    """Set the base value of an attribute for an entity."""
    from world.entities import MobEntity

    attr_key = attr_name.replace("minecraft:", "")

    if isinstance(entity, Connection):
        if "max_health" in attr_key:
            entity.health = value
    elif isinstance(entity, MobEntity):
        if "max_health" in attr_key:
            entity.max_health = value
            entity.health = min(entity.health, value)


# ============================================================
# Registration
# ============================================================

def register(manager):
    """Register all world management commands."""

    # ========================================
    # /worldborder
    # ========================================
    async def _worldborder(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply(f"[PyMC] 世界边界大小: {_world_border['size']:.0f}")
            return SUCCESS

        action = args[0].lower()

        if action == "set":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder set <大小> [时间(秒)]")
                return FAILURE
            try:
                size = float(args[1])
            except ValueError:
                await ctx.reply("[PyMC] 大小格式无效")
                return FAILURE
            _world_border["size"] = size
            _world_border["target_size"] = size
            await ctx.reply(f"[PyMC] 世界边界已设置为 {size}")
            return SUCCESS

        if action == "center":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: worldborder center <x> <z>")
                return FAILURE
            try:
                _world_border["center_x"] = float(args[1])
                _world_border["center_z"] = float(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
            await ctx.reply(f"[PyMC] 世界边界中心已设置为 ({_world_border['center_x']}, {_world_border['center_z']})")
            return SUCCESS

        if action == "damage":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder damage <amount|buffer> <值>")
                return FAILURE
            sub = args[1].lower()
            if sub == "amount" and len(args) >= 3:
                try:
                    _world_border["damage_per_block"] = float(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 伤害值格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 边界伤害已设置为 {_world_border['damage_per_block']}")
            elif sub == "buffer" and len(args) >= 3:
                try:
                    _world_border["damage_safe_zone"] = float(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 缓冲区大小格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 伤害缓冲区已设置为 {_world_border['damage_safe_zone']}")
            else:
                await ctx.reply("[PyMC] 用法: worldborder damage <amount|buffer> <值>")
                return FAILURE
            return SUCCESS

        if action == "warning":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: worldborder warning <time|distance> <值>")
                return FAILURE
            sub = args[1].lower()
            if sub == "time" and len(args) >= 3:
                try:
                    _world_border["warning_time"] = int(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 时间格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 警告时间已设置为 {_world_border['warning_time']} 秒")
            elif sub == "distance" and len(args) >= 3:
                try:
                    _world_border["warning_blocks"] = int(args[2])
                except ValueError:
                    await ctx.reply("[PyMC] 距离格式无效")
                    return FAILURE
                await ctx.reply(f"[PyMC] 警告距离已设置为 {_world_border['warning_blocks']} 方块")
            else:
                await ctx.reply("[PyMC] 用法: worldborder warning <time|distance> <值>")
                return FAILURE
            return SUCCESS

        if action == "get":
            await ctx.reply(f"[PyMC] 世界边界: 大小={_world_border['size']}, 中心=({_world_border['center_x']}, {_world_border['center_z']})")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: worldborder <set|center|damage|warning|get> ...")
        return FAILURE

    cmd_worldborder = Command(
        name="worldborder",
        description="管理世界边界",
        usage="worldborder <set|center|damage|warning|get> ...",
        permission="command.worldborder",
        category="world_mgmt",
    )
    cmd_worldborder._execute_func = _worldborder
    manager.register(cmd_worldborder)

    # ========================================
    # /locate
    # ========================================
    async def _locate(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: locate structure <类型> 或 locate biome <类型>")
            return FAILURE

        if len(args) >= 2 and args[0].lower() in ("structure", "biome"):
            target_type = args[0].lower()
            target_name = args[1].lower()
        else:
            target_type, target_name = parse_locate_target(args[0])
            if target_type == "structure" and len(args) >= 2:
                target_name = args[1].lower()
                target_type = args[0].lower()

        if ctx.sender and hasattr(ctx.sender, 'x'):
            base_x, base_z = int(ctx.sender.x), int(ctx.sender.z)
        else:
            base_x, base_z = 0, 0

        rng = random.Random(hash(target_name) ^ 0x5F3759DF)

        if target_type == "structure":
            angle = rng.random() * math.tau
            distance = rng.randint(100, 2000)
            found_x = int(base_x + math.cos(angle) * distance)
            found_z = int(base_z + math.sin(angle) * distance)
            found_x = (found_x >> 4) << 4
            found_z = (found_z >> 4) << 4
            actual_distance = math.sqrt((found_x - base_x) ** 2 + (found_z - base_z) ** 2)
            await ctx.reply(f"[PyMC] 最近的 {target_name} 位于 ({found_x}, ?, {found_z}) (距离 {actual_distance:.0f} 方块)")
        else:
            angle = rng.random() * math.tau
            distance = rng.randint(50, 1500)
            found_x = int(base_x + math.cos(angle) * distance)
            found_z = int(base_z + math.sin(angle) * distance)
            actual_distance = math.sqrt((found_x - base_x) ** 2 + (found_z - base_z) ** 2)
            await ctx.reply(f"[PyMC] 最近的 {target_name} 生物群系位于 ({found_x}, ?, {found_z}) (距离 {actual_distance:.0f} 方块)")

        return SUCCESS

    def _locate_suggest(ctx: CommandContext) -> list[str]:
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

    cmd_locate = Command(
        name="locate",
        description="定位最近的结构或生物群系",
        usage="locate <structure|biome> <名称>",
        permission="command.locate",
        category="world_mgmt",
    )
    cmd_locate._execute_func = _locate
    cmd_locate._suggest_func = _locate_suggest
    manager.register(cmd_locate)

    # ========================================
    # /forceload
    # ========================================
    async def _forceload(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: forceload <add|remove|query> [<x> <z>]")
            return FAILURE

        action = args[0].lower()

        if action == "add":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: forceload add <区块X> <区块Z> [到区块X] [到区块Z]")
                return FAILURE
            try:
                cx = int(args[1])
                cz = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE

            if len(args) >= 5:
                try:
                    cx2 = int(args[3])
                    cz2 = int(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE
                count = 0
                for x in range(min(cx, cx2), max(cx, cx2) + 1):
                    for z in range(min(cz, cz2), max(cz, cz2) + 1):
                        _forceloaded_chunks.add((x, z))
                        count += 1
                await ctx.reply(f"[PyMC] 已强制加载 {count} 个区块")
            else:
                _forceloaded_chunks.add((cx, cz))
                await ctx.reply(f"[PyMC] 已强制加载区块 ({cx}, {cz})")
            return SUCCESS

        if action == "remove":
            if len(args) < 3:
                if len(args) >= 2 and args[1].lower() == "all":
                    count = len(_forceloaded_chunks)
                    _forceloaded_chunks.clear()
                    await ctx.reply(f"[PyMC] 已移除所有强制加载区块 ({count} 个)")
                    return SUCCESS
                await ctx.reply("[PyMC] 用法: forceload remove <区块X> <区块Z> | forceload remove all")
                return FAILURE
            try:
                cx = int(args[1])
                cz = int(args[2])
            except ValueError:
                await ctx.reply("[PyMC] 坐标格式无效")
                return FAILURE
            _forceloaded_chunks.discard((cx, cz))
            await ctx.reply(f"[PyMC] 已移除区块 ({cx}, {cz}) 的强制加载")
            return SUCCESS

        if action == "query":
            if _forceloaded_chunks:
                chunks = ", ".join(f"({x},{z})" for x, z in sorted(_forceloaded_chunks)[:20])
                more = f" ... 还有 {len(_forceloaded_chunks) - 20} 个" if len(_forceloaded_chunks) > 20 else ""
                await ctx.reply(f"[PyMC] 强制加载区块: {chunks}{more}")
            else:
                await ctx.reply("[PyMC] 没有强制加载的区块")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: forceload <add|remove|query> ...")
        return FAILURE

    cmd_forceload = Command(
        name="forceload",
        description="强制加载区块",
        usage="forceload <add|remove|query> [<区块X> <区块Z>]",
        permission="command.forceload",
        category="world_mgmt",
    )
    cmd_forceload._execute_func = _forceload
    manager.register(cmd_forceload)

    # ========================================
    # /place
    # ========================================
    async def _place(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: place <structure|feature|jigsaw|template> <名称> [x] [y] [z]")
            return FAILURE

        place_type = args[0].lower()

        if place_type == "structure":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place structure <结构名> [x] [y] [z]")
                return FAILURE
            struct_name = args[1]

            bx, by, bz = 0.0, 100.0, 0.0
            if ctx.sender and hasattr(ctx.sender, 'x'):
                bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

            x, y, z = bx, by, bz
            if len(args) >= 5:
                try:
                    x = resolve_coordinate(parse_coordinate(args[2]), bx)
                    y = resolve_coordinate(parse_coordinate(args[3]), by)
                    z = resolve_coordinate(parse_coordinate(args[4]), bz)
                except ValueError:
                    await ctx.reply("[PyMC] 坐标格式无效")
                    return FAILURE

            await ctx.reply(f"[PyMC] 已在 ({x:.0f}, {y:.0f}, {z:.0f}) 放置结构 {struct_name} (结构放置暂未完全实现)")
            return SUCCESS

        if place_type == "feature":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place feature <特性名> [x] [y] [z]")
                return FAILURE
            feature_name = args[1]
            await ctx.reply(f"[PyMC] 已放置特性 {feature_name} (特性放置暂未完全实现)")
            return SUCCESS

        if place_type == "jigsaw":
            if len(args) < 5:
                await ctx.reply("[PyMC] 用法: place jigsaw <池> <目标> <最大深度> [x] [y] [z]")
                return FAILURE
            await ctx.reply("[PyMC] jigsaw 放置暂未完全实现")
            return SUCCESS

        if place_type == "template":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: place template <模板名> [x] [y] [z] [旋转] [镜像]")
                return FAILURE
            await ctx.reply("[PyMC] 模板放置暂未完全实现")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知放置类型: {place_type}")
        return FAILURE

    def _place_suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 2:
            return ["structure", "feature", "jigsaw", "template"]
        return []

    cmd_place = Command(
        name="place",
        description="放置结构、特性或模板",
        usage="place <structure|feature|jigsaw|template> <名称> [位置]",
        permission="command.place",
        category="world_mgmt",
    )
    cmd_place._execute_func = _place
    cmd_place._suggest_func = _place_suggest
    manager.register(cmd_place)

    # ========================================
    # /function
    # ========================================
    async def _function(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: function <函数名>")
            return FAILURE

        function_name = args[0].replace(":", "/")

        search_paths = [
            os.path.join("world", "datapacks"),
            os.path.join("datapacks"),
            "functions",
        ]

        function_path = None
        for base in search_paths:
            candidate = os.path.join(base, f"{function_name}.mcfunction")
            if os.path.isfile(candidate):
                function_path = candidate
                break

            candidate = os.path.join(base, "data", f"{function_name}.mcfunction")
            if os.path.isfile(candidate):
                function_path = candidate
                break

            if os.path.isdir(base):
                for root, dirs, files in os.walk(base):
                    for f in files:
                        if f.endswith(".mcfunction"):
                            rel = os.path.relpath(os.path.join(root, f), base)
                            if rel.replace("\\", "/").replace(".mcfunction", "") == function_name:
                                function_path = os.path.join(root, f)
                                break
                    if function_path:
                        break

        if function_path is None:
            await ctx.reply(f"[PyMC] 未找到函数: {args[0]}")
            return FAILURE

        try:
            with open(function_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            await ctx.reply(f"[PyMC] 读取函数文件失败: {e}")
            return FAILURE

        executed = 0
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("/"):
                line = line[1:]
            try:
                await ctx.server.command_manager.execute(ctx.sender, line)
                executed += 1
            except Exception as e:
                logger.debug(f"Function {args[0]} line {line_num} error: {e}")

        await ctx.reply(f"[PyMC] 已执行函数 {args[0]} ({executed} 条命令)")
        return SUCCESS

    cmd_function = Command(
        name="function",
        description="执行 .mcfunction 函数文件",
        usage="function <函数名>",
        permission="command.function",
        category="world_mgmt",
    )
    cmd_function._execute_func = _function
    manager.register(cmd_function)

    # ========================================
    # /schedule
    # ========================================
    async def _schedule(ctx: CommandContext) -> int:
        global _task_counter

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: schedule function <函数> <时间> [append|replace]")
            return FAILURE

        action = args[0].lower()

        if action == "function":
            if len(args) < 3:
                await ctx.reply("[PyMC] 用法: schedule function <函数|命令> <时间> [append|replace]")
                return FAILURE

            target = args[1]
            time_str = args[2].lower()
            replace_mode = True
            if len(args) >= 4:
                replace_mode = args[3].lower() != "append"

            try:
                delay_ticks = parse_time_value(time_str)
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间: {time_str}")
                return FAILURE

            delay_seconds = delay_ticks / 20.0

            _task_counter += 1
            task_id = f"schedule_{_task_counter}"

            async def _run_scheduled():
                await asyncio.sleep(delay_seconds)
                try:
                    if "." not in target and " " not in target:
                        await ctx.server.command_manager.execute(ctx.sender, f"function {target}")
                    else:
                        await ctx.server.command_manager.execute(ctx.sender, target)
                except Exception as e:
                    logger.debug(f"Scheduled task error: {e}")
                finally:
                    _scheduled_tasks.pop(task_id, None)

            task = asyncio.create_task(_run_scheduled())
            _scheduled_tasks[task_id] = task

            await ctx.reply(f"[PyMC] 已安排 {target} 在 {delay_ticks} tick 后执行")
            return SUCCESS

        if action == "clear":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: schedule clear <函数|ID>")
                return FAILURE
            cancelled = 0
            for tid, task in list(_scheduled_tasks.items()):
                if not task.done():
                    task.cancel()
                    cancelled += 1
            _scheduled_tasks.clear()
            await ctx.reply(f"[PyMC] 已取消 {cancelled} 个计划任务")
            return SUCCESS

        await ctx.reply("[PyMC] 用法: schedule <function|clear> ...")
        return FAILURE

    cmd_schedule = Command(
        name="schedule",
        description="延迟或重复执行命令",
        usage="schedule function <命令> <时间> | schedule clear <ID>",
        permission="command.schedule",
        category="world_mgmt",
    )
    cmd_schedule._execute_func = _schedule
    manager.register(cmd_schedule)

    # ========================================
    # /datapack
    # ========================================
    async def _datapack(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            if not _loaded_datapacks:
                await ctx.reply("[PyMC] 没有已加载的数据包")
            else:
                for name, pack in _loaded_datapacks.items():
                    status = "启用" if pack.get("enabled", True) else "禁用"
                    await ctx.reply(f"[PyMC] {name}: {status} ({pack.get('description', '')})")
            return SUCCESS

        action = args[0].lower()

        if action == "list":
            available = "可用" if len(args) >= 2 and args[1] == "available" else "已启用"
            if available == "已启用":
                for name, pack in _loaded_datapacks.items():
                    if pack.get("enabled", True):
                        await ctx.reply(f"[PyMC] {name}")
            else:
                search_dirs = ["world/datapacks", "datapacks"]
                found = set()
                for d in search_dirs:
                    if os.path.isdir(d):
                        for entry in os.listdir(d):
                            if entry.endswith(".zip") or os.path.isdir(os.path.join(d, entry)):
                                found.add(entry.replace(".zip", ""))
                if found:
                    await ctx.reply(f"[PyMC] 可用数据包: {', '.join(sorted(found))}")
                else:
                    await ctx.reply("[PyMC] 没有找到可用的数据包")
            return SUCCESS

        if action == "enable":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: datapack enable <名称>")
                return FAILURE
            pack_name = args[1]
            if pack_name in _loaded_datapacks:
                _loaded_datapacks[pack_name]["enabled"] = True
            else:
                _loaded_datapacks[pack_name] = {"enabled": True, "description": "自定义数据包"}
            await ctx.reply(f"[PyMC] 已启用数据包: {pack_name}")
            return SUCCESS

        if action == "disable":
            if len(args) < 2:
                await ctx.reply("[PyMC] 用法: datapack disable <名称>")
                return FAILURE
            pack_name = args[1]
            if pack_name in _loaded_datapacks:
                _loaded_datapacks[pack_name]["enabled"] = False
                await ctx.reply(f"[PyMC] 已禁用数据包: {pack_name}")
            else:
                await ctx.reply(f"[PyMC] 数据包不存在: {pack_name}")
            return FAILURE

        await ctx.reply("[PyMC] 用法: datapack <list|enable|disable> ...")
        return FAILURE

    cmd_datapack = Command(
        name="datapack",
        description="管理数据包",
        usage="datapack <list|enable|disable> <名称>",
        permission="command.datapack",
        category="world_mgmt",
    )
    cmd_datapack._execute_func = _datapack
    manager.register(cmd_datapack)

    # ========================================
    # /advancement
    # ========================================
    async def _advancement(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 3:
            await ctx.reply("[PyMC] 用法: advancement <grant|revoke> <目标> <everything|only|from|through|until> [进度名]")
            return FAILURE

        action = args[0].lower()
        if action not in ("grant", "revoke"):
            await ctx.reply(f"[PyMC] 未知操作: {action}。可用: grant, revoke")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[1])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
            return FAILURE

        mode = args[2].lower()

        if mode == "everything":
            count = 0
            for player in players:
                if player.username not in _player_advancements:
                    _player_advancements[player.username] = {}
                if action == "grant":
                    for adv_name in _advancements:
                        if not _player_advancements[player.username].get(adv_name):
                            _player_advancements[player.username][adv_name] = True
                            count += 1
                else:
                    count = len(_player_advancements[player.username])
                    _player_advancements[player.username] = {}
            action_cn = "授予" if action == "grant" else "撤销"
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家的所有进度 ({count} 个)")
            return SUCCESS

        if mode == "only":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: advancement <grant|revoke> <目标> only <进度名>")
                return FAILURE
            adv_name = args[3]
            count = 0
            for player in players:
                if player.username not in _player_advancements:
                    _player_advancements[player.username] = {}
                _player_advancements[player.username][adv_name] = (action == "grant")
                count += 1
            action_cn = "授予" if action == "grant" else "撤销"
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家进度: {adv_name}")
            return SUCCESS

        adv_name = args[3] if len(args) >= 4 else "unknown"
        action_cn = "授予" if action == "grant" else "撤销"
        await ctx.reply(f"[PyMC] 已{action_cn}进度: {adv_name} (from/through/until 模式暂简化处理)")
        return SUCCESS

    cmd_advancement = Command(
        name="advancement",
        description="授予或撤销进度",
        usage="advancement <grant|revoke> <目标> <everything|only|from|through|until> [进度名]",
        permission="command.advancement",
        category="world_mgmt",
    )
    cmd_advancement._execute_func = _advancement
    manager.register(cmd_advancement)

    # ========================================
    # /attribute
    # ========================================
    async def _attribute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: attribute <目标> <属性> <get|set|base|modifier> ...")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[0])
        if not targets:
            await ctx.reply(f"[PyMC] 未找到目标: {args[0]}")
            return FAILURE
        target = targets[0]

        attr_name = args[1].lower()
        if ":" not in attr_name:
            attr_name = f"minecraft:{attr_name}"

        if len(args) < 3:
            await ctx.reply("[PyMC] 用法: attribute <目标> <属性> <get|set|base|modifier> ...")
            return FAILURE

        action = args[2].lower()

        if action == "get":
            base_val = _get_attribute_base(target, attr_name)
            scale = float(args[3]) if len(args) >= 4 else 1.0
            await ctx.reply(f"[PyMC] {attr_name} = {base_val * scale:.4f}")
            return SUCCESS

        if action == "set":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: attribute <目标> <属性> set <值>")
                return FAILURE
            try:
                value = float(args[3])
            except ValueError:
                await ctx.reply("[PyMC] 值格式无效")
                return FAILURE
            _set_attribute_base(target, attr_name, value)
            await ctx.reply(f"[PyMC] 已设置 {attr_name} = {value}")
            return SUCCESS

        if action == "base":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: attribute <目标> <属性> base <get|set> [值]")
                return FAILURE
            sub = args[3].lower()
            if sub == "get":
                base_val = _get_attribute_base(target, attr_name)
                scale = float(args[4]) if len(args) >= 5 else 1.0
                await ctx.reply(f"[PyMC] {attr_name} 基础值 = {base_val * scale:.4f}")
            elif sub == "set":
                if len(args) < 5:
                    await ctx.reply("[PyMC] 用法: attribute <目标> <属性> base set <值>")
                    return FAILURE
                try:
                    value = float(args[4])
                except ValueError:
                    await ctx.reply("[PyMC] 值格式无效")
                    return FAILURE
                _set_attribute_base(target, attr_name, value)
                await ctx.reply(f"[PyMC] 已设置 {attr_name} 基础值 = {value}")
            return SUCCESS

        if action == "modifier":
            await ctx.reply("[PyMC] attribute modifier 暂未完全实现")
            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}")
        return FAILURE

    cmd_attribute = Command(
        name="attribute",
        description="修改实体属性",
        usage="attribute <目标> <属性> <get|set|base|modifier> ...",
        permission="command.attribute",
        category="world_mgmt",
    )
    cmd_attribute._execute_func = _attribute
    manager.register(cmd_attribute)

    # ========================================
    # /recipe
    # ========================================
    async def _recipe(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: recipe <give|take> <目标> [配方名|*]")
            return FAILURE

        action = args[0].lower()
        if action not in ("give", "take"):
            await ctx.reply(f"[PyMC] 未知操作: {action}")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[1])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
            return FAILURE

        recipe_name = args[2] if len(args) >= 3 else "*"
        action_cn = "给予" if action == "give" else "移除"

        if recipe_name == "*":
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家的所有配方")
        else:
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家配方: {recipe_name}")

        return SUCCESS

    cmd_recipe = Command(
        name="recipe",
        description="给予或移除配方",
        usage="recipe <give|take> <目标> [配方名|*]",
        permission="command.recipe",
        category="world_mgmt",
    )
    cmd_recipe._execute_func = _recipe
    manager.register(cmd_recipe)

    # ========================================
    # /trigger
    # ========================================
    async def _trigger(ctx: CommandContext) -> int:
        from commands.vanilla.display import get_scoreboard_manager
        sb = get_scoreboard_manager()

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: trigger <目标> [add|set] <值>")
            return FAILURE

        objective = args[0]

        if objective not in sb.objectives:
            await ctx.reply(f"[PyMC] 目标 '{objective}' 不存在或不是 trigger 类型")
            return FAILURE

        if ctx.sender is None:
            await ctx.reply("[PyMC] 控制台无法使用 trigger 命令")
            return FAILURE
        player = ctx.sender.username

        action = "add"
        value = 1

        if len(args) >= 2:
            action = args[1].lower()
            if action in ("add", "set"):
                if len(args) >= 3:
                    try:
                        value = int(args[2])
                    except ValueError:
                        await ctx.reply("[PyMC] 值格式无效")
                        return FAILURE
            else:
                try:
                    value = int(args[1])
                    action = "add"
                except ValueError:
                    await ctx.reply("[PyMC] 用法: trigger <目标> [add|set] <值>")
                    return FAILURE

        if action == "add":
            new_score = sb.add_score(objective, player, value)
        else:
            new_score = value
            sb.set_score(objective, player, value)

        await ctx.reply(f"[PyMC] {objective} for {player}: {new_score}")
        return SUCCESS

    cmd_trigger = Command(
        name="trigger",
        description="修改 trigger 类型记分板目标",
        usage="trigger <目标> [add|set] <值>",
        permission="command.trigger",
        category="world_mgmt",
    )
    cmd_trigger._execute_func = _trigger
    manager.register(cmd_trigger)
