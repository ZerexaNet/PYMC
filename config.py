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
    "spawn-protection": 0,
    "enable-command-block": True,
    "web-admin-enabled": True,
    "web-admin-host": "0.0.0.0",
    "web-admin-port": 25568,
    "permissions-file": "permissions.json",
    "chunk-generation-multithreading": False,
}

# 类型映射 (用于自动转换配置值)
TYPE_MAP = {
    "server-port": int,
    "max-players": int,
    "online-mode": lambda v: v.lower() in ("true", "1", "yes"),
    "view-distance": int,
    "network-compression-threshold": int,
    "spawn-protection": int,
    "enable-command-block": lambda v: v.lower() in ("true", "1", "yes"),
    "web-admin-enabled": lambda v: v.lower() in ("true", "1", "yes"),
    "web-admin-port": int,
    "chunk-generation-multithreading": lambda v: v.lower() in ("true", "1", "yes"),
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
