# ============================================================
# PyMC - Python Minecraft 1.21.1 服务端
# 主入口文件
# ============================================================

"""
PyMC: Python 实现的 Minecraft Java 版服务端，关键路径使用 C++ 原生组件加速。

启动方式与原版服务端一致:

    python main.py [--nogui] [--port 25565] [--world world]

工作目录下会生成原版风格的文件:
  server.properties, ops.json, whitelist.json, banned-players.json,
  banned-ips.json, usercache.json, logs/latest.log, <level-name>/level.dat ...
"""

import argparse
import asyncio
import concurrent.futures
import logging
import os
import signal
import sys

# 确保模块搜索路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from serverlog import setup_logging
from network.server import MinecraftServer, MINECRAFT_VERSION
from handlers.play import execute_server_command
from commands import CommandManager, register_all_vanilla_commands
from watchdog import WatchdogManager
from plugins.bridge import init_plugin_system


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pymc", description=f"PyMC - Minecraft {MINECRAFT_VERSION} server")
    parser.add_argument("--nogui", action="store_true",
                        help="accepted for compatibility with vanilla start scripts")
    parser.add_argument("--port", type=int, default=None, help="override server-port")
    parser.add_argument("--world", "--level-name", dest="world", default=None,
                        help="override level-name")
    parser.add_argument("--universe", default=None,
                        help="directory that contains the world folder")
    parser.add_argument("--config", default="server.properties",
                        help="path to server.properties")
    args, _unknown = parser.parse_known_args(argv)
    return args


async def main(argv=None) -> int:
    """主入口函数。"""
    args = parse_args(argv)

    config_path = args.config
    first_run = not os.path.exists(config_path)
    # 先用 INFO 级别初始化日志, 读到配置后再按 debug 开关调整
    setup_logging(debug=False)
    logger = logging.getLogger("minecraft.server")

    logger.info(f"Starting minecraft server version {MINECRAFT_VERSION}")
    logger.info("Loading properties")
    if first_run:
        logger.warning(f"{config_path} does not exist")
        logger.info(f"Generating new properties file")
    config = load_config(config_path)
    if args.port is not None:
        config["server-port"] = args.port
    if args.world is not None:
        config["level-name"] = args.world
    if args.universe is not None:
        config["universe"] = args.universe
    if config.get("debug", False):
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(
        max_workers=max(4, (os.cpu_count() or 2) + 2), thread_name_prefix="Worker-Main"))

    # 创建服务器实例
    try:
        server = MinecraftServer(config, config_path=config_path)
    except Exception as e:
        logger.error(f"Failed to start the minecraft server: {e}")
        return 1

    # 初始化命令框架
    server.command_manager = CommandManager(server)
    register_all_vanilla_commands(server.command_manager)

    # 初始化插件系统 (自动发现、加载、启用并注册命令)
    plugins_dir = config.get("plugins-directory", "plugins")
    init_plugin_system(server, plugins_dir)

    # 初始化 Watchdog (如果配置启用)
    server.watchdog_manager = None
    if config.get("watchdog-enabled", False):
        server.watchdog_manager = WatchdogManager(server)
        await server.watchdog_manager.start()

    # 注册信号处理 (优雅关闭): Ctrl+C / SIGTERM 等同于控制台输入 stop
    def handle_shutdown():
        if server.running:
            server.request_stop()

    if sys.platform == 'win32':
        signal.signal(signal.SIGINT, lambda s, f: loop.call_soon_threadsafe(handle_shutdown))
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_shutdown)

    console_task = asyncio.create_task(console_input_loop(server))
    exit_code = 0
    try:
        await server.start()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Failed to start the minecraft server: {e}", exc_info=True)
        exit_code = 1
    finally:
        console_task.cancel()
        await server.stop()
    return exit_code


async def console_input_loop(server: MinecraftServer):
    """
    后台读取服务端控制台命令 (带不带前导 "/" 均可, 与原版控制台一致)。
    标准输入关闭 (nohup / systemd / Docker 无 TTY) 时静默退出, 服务器继续运行。
    """
    logger = logging.getLogger("minecraft.console")
    loop = asyncio.get_running_loop()
    reader = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="Console")

    while True:
        try:
            line = await loop.run_in_executor(reader, sys.stdin.readline)
        except (asyncio.CancelledError, RuntimeError):
            reader.shutdown(wait=False, cancel_futures=True)
            raise
        except Exception as e:
            logger.debug(f"Console input unavailable: {e}")
            return

        if line == "":
            # EOF: 没有可用的控制台
            reader.shutdown(wait=False)
            return

        command = line.strip()
        if command.startswith("/"):
            command = command[1:]
        if not command:
            continue
        # 启动完成前输入的命令排队等待 (与原版控制台一致)
        await server.wait_until_ready()
        if not server.running:
            return

        try:
            await execute_server_command(server, command)
        except Exception as e:
            logger.error(f"Unexpected exception while executing '{command}': {e}", exc_info=True)


def run() -> None:
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 0
    # 控制台读取线程可能仍阻塞在 stdin 上; 不等待它, 直接退出
    logging.shutdown()
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    run()
