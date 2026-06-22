# ============================================================
# PyMC - 配置文件管理
# 读取和解析 server.properties 配置文件
# ============================================================

import os
import logging

logger = logging.getLogger("PyMC.配置")

# 默认配置
DEFAULT_CONFIG = {
    "server-ip": "0.0.0.0",
    "server-port": 25565,
    "motd": "PyMC - Python Minecraft 1.21.1 服务器",
    "max-players": 20,
    "online-mode": False,
    "view-distance": 10,
    "network-compression-threshold": 256,
    "gamemode": "creative",
    "difficulty": "normal",
    "level-name": "world",
    "level-type": "default",
    "level-seed": "",
    "level-spawn-x": 0,
    "level-spawn-y": 100,
    "level-spawn-z": 0,
    "spawn-protection": 0,
    "enable-command-block": True,
    "web-admin-enabled": True,
    "web-admin-host": "0.0.0.0",
    "web-admin-port": 25568,
    "permissions-file": "permissions.json",
    "chunk-generation-multithreading": False,
    "chunk-generation-workers": 0,
    "join-immediate-radius": 2,
    # Multi-version protocol support
    "support-protocol-versions": "all",  # "all" or comma-separated list (e.g. "47,340,767")
    "min-protocol-version": 47,            # Minimum allowed protocol version
    "max-protocol-version": 770,           # Maximum allowed protocol version

    # Watchdog dual-process mutual protection
    "watchdog-enabled": False,             # Enable watchdog dual-process protection
    "watchdog-health-port": 25569,         # UDP port for health check heartbeats
    "watchdog-partner-pid": 0,             # PID of partner process (0 = auto-detect)
    "watchdog-max-missed-heartbeats": 5,   # Missed heartbeats before restart

    # Network optimization
    "network-packet-batching": True,        # Enable packet batching for reduced TCP writes
    "network-movement-rate-hz": 20.0,      # Max position updates per second per player

    # Vanilla terrain generation
    "vanilla-terrain": True,                # Use the 1:1 vanilla terrain generator

    # Redstone
    "redstone-enabled": True,               # Enable redstone simulation

    # Fluids
    "fluid-flow-enabled": True,             # Enable water/lava flow simulation

    # Mod and plugin directories
    "mods-directory": "mods",               # Directory to scan for Fabric/Forge mods
    "plugins-directory": "plugins",          # Directory to scan for Paper/Bukkit plugins
}

# 类型映射 (用于自动转换配置值)
TYPE_MAP = {
    "server-port": int,
    "max-players": int,
    "online-mode": lambda v: v.lower() in ("true", "1", "yes"),
    "view-distance": int,
    "network-compression-threshold": int,
    "level-spawn-x": int,
    "level-spawn-y": int,
    "level-spawn-z": int,
    "spawn-protection": int,
    "enable-command-block": lambda v: v.lower() in ("true", "1", "yes"),
    "web-admin-enabled": lambda v: v.lower() in ("true", "1", "yes"),
    "web-admin-port": int,
    "chunk-generation-multithreading": lambda v: v.lower() in ("true", "1", "yes"),
    "chunk-generation-workers": int,
    "join-immediate-radius": int,
    "min-protocol-version": int,
    "max-protocol-version": int,

    # Watchdog
    "watchdog-enabled": lambda v: v.lower() in ("true", "1", "yes"),
    "watchdog-health-port": int,
    "watchdog-partner-pid": int,
    "watchdog-max-missed-heartbeats": int,

    # Network optimization
    "network-packet-batching": lambda v: v.lower() in ("true", "1", "yes"),
    "network-movement-rate-hz": float,

    # Vanilla terrain / Redstone / Fluids
    "vanilla-terrain": lambda v: v.lower() in ("true", "1", "yes"),
    "redstone-enabled": lambda v: v.lower() in ("true", "1", "yes"),
    "fluid-flow-enabled": lambda v: v.lower() in ("true", "1", "yes"),

    # Mod and plugin directories (string, no conversion needed)
}


def load_config(filepath: str = "server.properties") -> dict:
    """
    加载服务器配置文件。
    如果文件不存在则创建默认配置。
    
    返回:
        配置字典
    """
    config = dict(DEFAULT_CONFIG)

    if os.path.exists(filepath):
        logger.info(f"正在加载配置文件: {filepath}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # 类型转换
                        if key in TYPE_MAP:
                            try:
                                value = TYPE_MAP[key](value)
                            except (ValueError, TypeError):
                                logger.warning(f"配置项 '{key}' 的值无效: '{value}'，使用默认值")
                                continue

                        config[key] = value
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}，使用默认配置")
    else:
        logger.info(f"配置文件不存在，正在创建默认配置: {filepath}")
        save_config(config, filepath)

    return config


def save_config(config: dict, filepath: str = "server.properties"):
    """保存配置到文件。"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# ============================================================\n")
            f.write("# PyMC 服务器配置文件\n")
            f.write("# Minecraft 1.21.1 服务端\n")
            f.write("# ============================================================\n\n")

            for key, value in config.items():
                if isinstance(value, bool):
                    value = "true" if value else "false"
                f.write(f"{key}={value}\n")

        logger.info(f"配置文件已保存: {filepath}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
