# ============================================================
# PyMC - /schedule Command
# Delayed and repeated command execution
# ============================================================

import asyncio
import logging
import time

from commands.framework import Command, CommandContext, SUCCESS, FAILURE

logger = logging.getLogger("PyMC.调度")


# Active scheduled tasks
_scheduled_tasks: dict[str, asyncio.Task] = {}
_task_counter = 0


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
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

            # Parse time
            try:
                from commands.arguments import parse_time_value
                delay_ticks = parse_time_value(time_str)
            except ValueError:
                await ctx.reply(f"[PyMC] 无效时间: {time_str}")
                return FAILURE

            delay_seconds = delay_ticks / 20.0  # Convert ticks to seconds

            # Schedule the execution
            _task_counter += 1
            task_id = f"schedule_{_task_counter}"

            async def _run_scheduled():
                await asyncio.sleep(delay_seconds)
                try:
                    # Check if it's a function name or a direct command
                    if "." not in target and " " not in target:
                        # Assume function
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
            target = args[1]
            # Cancel matching tasks
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

    cmd = Command(
        name="schedule",
        description="延迟或重复执行命令",
        usage="schedule function <命令> <时间> | schedule clear <ID>",
        permission="command.schedule",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
