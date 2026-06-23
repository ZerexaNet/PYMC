# ============================================================
# PyMC - /datapack Command
# ============================================================

import os
import json
import logging

from commands.framework import Command, CommandContext, SUCCESS, FAILURE

logger = logging.getLogger("PyMC.数据包")


# Loaded datapacks
_loaded_datapacks: dict[str, dict] = {}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            # List datapacks
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
                # Scan datapack directory
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

    cmd = Command(
        name="datapack",
        description="管理数据包",
        usage="datapack <list|enable|disable> <名称>",
        permission="command.datapack",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
