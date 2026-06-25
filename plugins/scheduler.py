"""Tick-based task scheduler for PYMC plugins and mods.

The server game loop runs at 20 TPS (50ms per tick). The scheduler's
`tick()` method is called once per game tick by the server.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class _TaskKind(Enum):
    REPEAT = auto()
    DELAYED = auto()
    ASYNC = auto()


@dataclass
class _ScheduledTask:
    task_id: int
    kind: _TaskKind
    callback: Any  # Callable or Coroutine
    plugin_id: str
    ticks_remaining: int
    interval: int = 0  # only used by REPEAT tasks


class PluginScheduler:
    """Schedules sync, delayed, and async tasks on the server tick loop.

    Usage::

        scheduler = PluginScheduler(server)
        # every 40 ticks (2 seconds)
        tid = scheduler.run_every(40, my_callback, plugin_id="my_plugin")
        # once after 100 ticks
        scheduler.run_delayed(100, lambda: print("hello"), plugin_id="my_plugin")
        # async task
        scheduler.run_async(my_coroutine(), plugin_id="my_plugin")
        # next tick convenience
        scheduler.run_next_tick(some_fn, plugin_id="my_plugin")

        # called by server each tick
        scheduler.tick()
    """

    def __init__(self, server: Any):
        self._server = server
        self._tasks: Dict[int, _ScheduledTask] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def run_every(self, interval_ticks: int, callback: Callable, plugin_id: str = "") -> int:
        """Register a repeating task that fires every *interval_ticks*.

        Returns the task ID which can be used to cancel the task later.
        """
        if interval_ticks < 1:
            raise ValueError("interval_ticks must be >= 1")
        tid = self._allocate_id()
        self._tasks[tid] = _ScheduledTask(
            task_id=tid,
            kind=_TaskKind.REPEAT,
            callback=callback,
            plugin_id=plugin_id,
            ticks_remaining=interval_ticks,
            interval=interval_ticks,
        )
        logger.debug("Scheduled repeating task %d every %d ticks for %r", tid, interval_ticks, plugin_id)
        return tid

    def run_delayed(self, delay_ticks: int, callback: Callable, plugin_id: str = "") -> int:
        """Register a one-shot task that fires once after *delay_ticks*.

        Returns the task ID.
        """
        if delay_ticks < 1:
            raise ValueError("delay_ticks must be >= 1")
        tid = self._allocate_id()
        self._tasks[tid] = _ScheduledTask(
            task_id=tid,
            kind=_TaskKind.DELAYED,
            callback=callback,
            plugin_id=plugin_id,
            ticks_remaining=delay_ticks,
        )
        logger.debug("Scheduled delayed task %d in %d ticks for %r", tid, delay_ticks, plugin_id)
        return tid

    def run_next_tick(self, callback: Callable, plugin_id: str = "") -> int:
        """Convenience: schedule *callback* to run on the very next tick."""
        return self.run_delayed(1, callback, plugin_id=plugin_id)

    def run_async(self, coroutine, plugin_id: str = "") -> int:
        """Register an async task. It is launched via ``asyncio.ensure_future``
        on the next tick.

        Returns the task ID.
        """
        tid = self._allocate_id()
        self._tasks[tid] = _ScheduledTask(
            task_id=tid,
            kind=_TaskKind.ASYNC,
            callback=coroutine,
            plugin_id=plugin_id,
            ticks_remaining=1,  # fire on next tick
        )
        logger.debug("Scheduled async task %d for %r", tid, plugin_id)
        return tid

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel(self, task_id: int) -> bool:
        """Cancel a scheduled task. Returns ``True`` if the task existed."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.debug("Cancelled task %d", task_id)
            return True
        return False

    def cancel_all_for_plugin(self, plugin_id: str) -> None:
        """Cancel every task belonging to *plugin_id*."""
        to_remove = [tid for tid, t in self._tasks.items() if t.plugin_id == plugin_id]
        for tid in to_remove:
            del self._tasks[tid]
        logger.debug("Cancelled %d tasks for plugin %r", len(to_remove), plugin_id)

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Called once per server tick. Decrements counters and executes due tasks."""
        due: list[_ScheduledTask] = []
        for task in self._tasks.values():
            task.ticks_remaining -= 1
            if task.ticks_remaining <= 0:
                due.append(task)

        for task in due:
            # Task may have been cancelled during an earlier execution this tick
            if task.task_id not in self._tasks:
                continue

            if task.kind == _TaskKind.REPEAT:
                self._execute_sync(task)
                # Re-schedule: only if not cancelled during execution
                if task.task_id in self._tasks:
                    task.ticks_remaining = task.interval

            elif task.kind == _TaskKind.DELAYED:
                self._execute_sync(task)
                # One-shot: remove after execution
                self._tasks.pop(task.task_id, None)

            elif task.kind == _TaskKind.ASYNC:
                self._execute_async(task)
                self._tasks.pop(task.task_id, None)

    def _execute_sync(self, task: _ScheduledTask) -> None:
        """Run a synchronous callback with error handling."""
        try:
            task.callback()
        except Exception:
            logger.exception(
                "Error in scheduled task %d (plugin=%r)",
                task.task_id,
                task.plugin_id,
            )

    def _execute_async(self, task: _ScheduledTask) -> None:
        """Launch an async coroutine via the event loop with error handling."""
        try:
            future = asyncio.ensure_future(task.callback)
            future.add_done_callback(self._make_async_error_handler(task))
        except Exception:
            logger.exception(
                "Failed to schedule async task %d (plugin=%r)",
                task.task_id,
                task.plugin_id,
            )

    @staticmethod
    def _make_async_error_handler(task: _ScheduledTask) -> Callable:
        def _handler(fut: asyncio.Future) -> None:
            try:
                fut.result()
            except Exception:
                logger.exception(
                    "Error in async task %d (plugin=%r)",
                    task.task_id,
                    task.plugin_id,
                )
        return _handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Cancel all scheduled tasks. Call during server shutdown."""
        count = len(self._tasks)
        self._tasks.clear()
        logger.info("Scheduler shutdown: cancelled %d tasks", count)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _allocate_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Number of currently scheduled tasks."""
        return len(self._tasks)
