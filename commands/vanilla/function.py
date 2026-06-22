# ============================================================
# PyMC - /function Command
# Simple .mcfunction file support
# ============================================================

import os
import logging

from commands.framework import Command, CommandContext, SUCCESS, FAILURE

logger = logging.getLogger("PyMC.函数")


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: function <函数名>")
            return FAILURE

        function_name = args[0].replace(":", "/")

        # Look for .mcfunction files
        # Standard datapack structure: world/datapacks/<pack>/data/<namespace>/functions/<name>.mcfunction
        search_paths = [
            os.path.join("world", "datapacks"),
            os.path.join("datapacks"),
            "functions",
        ]

        function_path = None
        for base in search_paths:
            # Try direct path
            candidate = os.path.join(base, f"{function_name}.mcfunction")
            if os.path.isfile(candidate):
                function_path = candidate
                break

            # Try within data directory
            candidate = os.path.join(base, "data", f"{function_name}.mcfunction")
            if os.path.isfile(candidate):
                function_path = candidate
                break

            # Search recursively
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

        # Read and execute each line
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

            # Remove leading /
            if line.startswith("/"):
                line = line[1:]

            try:
                result = await ctx.server.command_manager.execute(ctx.sender, line)
                executed += 1
            except Exception as e:
                logger.debug(f"Function {args[0]} line {line_num} error: {e}")

        await ctx.reply(f"[PyMC] 已执行函数 {args[0]} ({executed} 条命令)")
        return SUCCESS

    cmd = Command(
        name="function",
        description="执行 .mcfunction 函数文件",
        usage="function <函数名>",
        permission="command.function",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
