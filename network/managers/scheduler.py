# ============================================================
# PyMC - 延迟任务调度器
# 支持延迟执行和周期执行的异步任务调度
# ============================================================

"""
TickScheduler - 基于 tick 的延迟任务调度器。

在游戏循环中，某些操作需要延迟执行或周期性执行，
例如延迟伤害、重生倒计时、药水效果倒计时等。
这个调度器提供了基于 tick 数而非真实时间的调度机制。
"""

import asyncio
import logging
from typing import Callable, Any

logger = logging.getLogger("PyMC.调度器")


class ScheduledTask:
    """一个计划中的任务。"""

    __slots__ = ('_callback', '_delay', '_period', '_elapsed', '_cancelled', '_async')

    def __init__(self, callback: Callable, delay: int, period: int = 0, async_: bool = False):
        self._callback = callback
        self._delay = delay  # 首次执行延迟 (ticks)
        self._period = period  # 周期 (0 = 不重复)
        self._elapsed = 0
        self._cancelled = False
        self._async = async_

    def cancel(self):
        """取消任务。"""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class TickScheduler:
    """
    基于 tick 的任务调度器。
    
    用法:
        scheduler = TickScheduler()
        task_id = scheduler.schedule(lambda: print("hello"), delay=100)
        scheduler.schedule_periodic(callback, delay=20, period=40)
        
        # 在游戏循环中每 tick 调用:
        scheduler.tick()
    """

    def __init__(self):
        self._tasks: list[ScheduledTask] = []
        self._next_id: int = 0
        self._task_map: dict[int, ScheduledTask] = {}

    def schedule(self, callback: Callable, delay: int = 0, async_: bool = False) -> int:
        """
        调度一个延迟执行的任务。
        
        参数:
            callback: 回调函数
            delay: 延迟的 tick 数
            async_: 回调是否为 async 函数
        
        返回:
            任务 ID (可用于取消)
        """
        task = ScheduledTask(callback, delay=delay, async_=async_)
        task_id = self._next_id
        self._next_id += 1
        self._tasks.append(task)
        self._task_map[task_id] = task
        return task_id

    def schedule_periodic(self, callback: Callable, delay: int = 0, period: int = 1,
                          async_: bool = False) -> int:
        """
        调度一个周期执行的任务。
        
        参数:
            callback: 回调函数
            delay: 首次执行的延迟 tick 数
            period: 两次执行之间的间隔 tick 数
            async_: 回调是否为 async 函数
        
        返回:
            任务 ID (可用于取消)
        """
        task = ScheduledTask(callback, delay=delay, period=period, async_=async_)
        task_id = self._next_id
        self._next_id += 1
        self._tasks.append(task)
        self._task_map[task_id] = task
        return task_id

    def cancel(self, task_id: int) -> bool:
        """
        取消一个调度任务。
        
        返回:
            True 表示成功取消，False 表示任务不存在或已完成
        """
        task = self._task_map.pop(task_id, None)
        if task is not None:
            task.cancel()
            return True
        return False

    async def tick(self):
        """
        每游戏 tick 调用一次。
        检查所有任务是否到期并执行。
        """
        remaining = []
        for task in self._tasks:
            if task.cancelled:
                continue

            task._elapsed += 1

            if task._elapsed >= task._delay:
                try:
                    if task._async:
                        await task._callback()
                    else:
                        task._callback()
                except Exception as e:
                    logger.error(f"调度任务执行异常: {e}")

                if task._period > 0:
                    # 周期任务: 重置计时
                    task._elapsed = 0
                    task._delay = task._period
                    remaining.append(task)
                else:
                    # 一次性任务: 从映射中移除
                    for tid, t in list(self._task_map.items()):
                        if t is task:
                            del self._task_map[tid]
                            break
            else:
                remaining.append(task)

        self._tasks = remaining

    @property
    def pending_count(self) -> int:
        """待执行任务数量。"""
        return len(self._tasks)

    def clear(self):
        """清除所有任务。"""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._task_map.clear()
