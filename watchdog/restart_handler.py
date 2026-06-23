# ============================================================
# PyMC - Restart Handler
# Graceful restart logic for the watchdog system
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger("PyMC.重启处理")


class RestartHandler:
    """Handles graceful server restart."""

    def __init__(self, server):
        self.server = server
        self._restart_pending = False
        self._restart_reason = ""

    async def request_restart(self, reason: str = "管理员请求"):
        """Request a graceful server restart."""
        if self._restart_pending:
            logger.warning("重启已在进行中")
            return

        self._restart_pending = True
        self._restart_reason = reason

        logger.info(f"正在准备重启: {reason}")

        # 1. Notify all players
        self.server.broadcast_system_message(f"[PyMC] 服务器即将重启: {reason}")

        # 2. Save all data
        await self._save_all()

        # 3. Wait for pending operations
        await asyncio.sleep(3)

        # 4. Disconnect players gracefully
        for player in self.server.get_online_players():
            try:
                await player.disconnect("服务器重启中...")
            except Exception:
                pass

        # 5. Start new process
        self._start_new_process()

        # 6. Stop current process
        await self.server.stop()

    async def _save_all(self):
        """Save all world and player data."""
        logger.info("正在保存所有数据...")
        try:
            self.server.save_all_player_states()
            self.server.world_storage.flush()
            logger.info("所有数据已保存")
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def _start_new_process(self):
        """Start a new server process."""
        try:
            main_path = os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', 'main.py'
            ))

            cmd = [sys.executable, main_path]

            env = os.environ.copy()
            # Preserve watchdog configuration
            if hasattr(self.server, 'command_manager'):
                env['PYMC_RESTARTED'] = '1'

            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )

            logger.info(f"已启动新服务器进程 PID={process.pid}")

            # Notify watchdog about new partner PID
            if hasattr(self.server, '_watchdog') and self.server._watchdog:
                self.server._watchdog.partner_pid = process.pid

        except Exception as e:
            logger.error(f"启动新进程失败: {e}")

    async def emergency_restart(self, reason: str = "紧急重启"):
        """Emergency restart without graceful shutdown."""
        logger.critical(f"紧急重启: {reason}")

        try:
            # Quick save
            self.server.save_all_player_states()
        except Exception:
            pass

        # Start new process immediately
        self._start_new_process()

        # Force stop
        os._exit(1)


class GracefulShutdown:
    """Handles graceful shutdown with timeout."""

    def __init__(self, server, timeout: float = 30.0):
        self.server = server
        self.timeout = timeout
        self._shutdown_started = False

    async def shutdown(self, reason: str = "正常关闭"):
        """Perform graceful shutdown."""
        if self._shutdown_started:
            return
        self._shutdown_started = True

        logger.info(f"正在关闭服务器: {reason}")

        # Notify players
        self.server.broadcast_system_message(f"[PyMC] 服务器正在关闭: {reason}")

        # Save data
        try:
            self.server.save_all_player_states()
            self.server.world_storage.flush()
        except Exception as e:
            logger.error(f"关闭时保存数据失败: {e}")

        # Disconnect players
        for player in list(self.server.get_online_players()):
            try:
                await player.disconnect("服务器关闭")
            except Exception:
                pass

        # Stop watchdog
        if hasattr(self.server, '_watchdog') and self.server._watchdog:
            try:
                await self.server._watchdog.graceful_shutdown()
            except Exception:
                pass

        # Stop server
        try:
            await asyncio.wait_for(self.server.stop(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning("关闭超时，强制退出")
            os._exit(0)
