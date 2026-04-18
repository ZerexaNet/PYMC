# ============================================================
# PyMC - Python Minecraft 1.21.1 服务端
# 主入口文件
# ============================================================

"""
PyMC: 使用纯 Python 实现的 Minecraft Java 版服务端。

支持版本: 1.21.1 (协议版本 767)
功能:
  - 离线模式登录
  - 平坦世界生成
  - 玩家移动同步
  - 聊天消息
  - 基础命令 (/help, /list, /tp, /gamemode, /stop)
  - 数据包压缩
  - KeepAlive 心跳
"""

import asyncio
import logging
import signal
import sys
import os

# 确保模块搜索路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from network.server import MinecraftServer
from handlers.play import execute_server_command


def setup_logging():
    """配置日志系统。"""
    # 创建根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # 日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s/%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器 (可选)
    try:
        file_handler = logging.FileHandler('pymc.log', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception:
        pass  # 如果无法创建日志文件则跳过


def print_banner():
    """打印启动横幅。"""
    banner = r"""
  ____        __  __  ____
 |  _ \ _   _|  \/  |/ ___|
 | |_) | | | | |\/| | |
 |  __/| |_| | |  | | |___
 |_|    \__, |_|  |_|\____|
        |___/
    """
    print(banner)
    print("  Python Minecraft 服务端 - 版本 1.21.1")
    print("  协议版本: 767")
    print("=" * 50)
    print()


async def main():
    """主入口函数。"""
    print_banner()
    setup_logging()

    logger = logging.getLogger("PyMC")
    logger.info("正在启动 PyMC 服务器...")

    # 加载配置
    config_path = "server.properties"
    config = load_config(config_path)
    logger.info(f"服务器地址: {config['server-ip']}:{config['server-port']}")

    # 创建服务器实例
    server = MinecraftServer(config, config_path=config_path)
    console_task = None

    # 注册信号处理 (优雅关闭)
    loop = asyncio.get_event_loop()

    def handle_shutdown():
        logger.info("收到关闭信号，正在停止服务器...")
        asyncio.ensure_future(server.stop())

    # Windows 下信号处理
    if sys.platform == 'win32':
        # Windows 不支持 SIGTERM 信号
        signal.signal(signal.SIGINT, lambda s, f: handle_shutdown())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_shutdown)

    # 启动服务器
    try:
        console_task = asyncio.create_task(console_input_loop(server))
        await server.start()
    except KeyboardInterrupt:
        logger.info("检测到键盘中断...")
    except Exception as e:
        logger.error(f"服务器异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if console_task:
            console_task.cancel()
        await server.stop()


async def console_input_loop(server: MinecraftServer):
    """后台读取服务端控制台命令。"""
    logger = logging.getLogger("PyMC.控制台")
    await asyncio.sleep(0)
    logger.info("控制台已就绪，可输入 help 查看命令")

    while True:
        try:
            line = await asyncio.to_thread(sys.stdin.readline)
        except (asyncio.CancelledError, RuntimeError):
            raise
        except Exception as e:
            logger.warning(f"读取控制台输入失败: {e}")
            return

        if line == "":
            await asyncio.sleep(0.1)
            if not server.running:
                return
            continue

        command = line.strip()
        if not command:
            continue

        await execute_server_command(server, command)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务器已停止。")
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
