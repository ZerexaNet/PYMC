# ============================================================
# PyMC - 配置文件管理
# 读取和解析 server.properties 配置文件
# ============================================================

import os
import logging

logger = logging.getLogger("PyMC.配置")

# 默认配置。
#
# 键名、默认值与原版 1.21.1 的 server.properties 保持一致；PyMC 自己的
# 扩展项排在后面。保存时与原版一样按键名排序写出。
DEFAULT_CONFIG = {
    # ---- 原版 (vanilla) ----
    "allow-flight": False,
    "broadcast-console-to-ops": True,
    "broadcast-rcon-to-ops": True,
    "difficulty": "easy",
    "enable-command-block": False,
    "enable-rcon": False,
    "enable-status": True,
    "enforce-whitelist": False,
    "force-gamemode": False,
    "gamemode": "survival",
    "hardcore": False,
    "hide-online-players": False,
    "level-name": "world",
    "level-seed": "",
    "level-type": "minecraft:normal",
    "log-ips": True,
    "max-players": 20,
    "motd": "A Minecraft Server",
    "network-compression-threshold": 256,
    "online-mode": False,
    "op-permission-level": 4,
    "player-idle-timeout": 0,
    "pvp": True,
    "rcon.password": "",
    "rcon.port": 25575,
    "server-ip": "",
    "server-port": 25565,
    "simulation-distance": 10,
    "spawn-animals": True,
    "spawn-monsters": True,
    "spawn-protection": 16,
    "view-distance": 10,
    "white-list": False,

    # ---- PyMC 扩展 ----
    "debug": False,                         # 输出 DEBUG 级别日志
    "anvil-too-expensive-limit": True,      # 铁砧费用达到 40 级时不能取 (原版); 关闭后不限制费用
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

    # World storage: "anvil" (.mca, vanilla) or "linear" (.linear, needs zstandard)
    "region-file-format": "anvil",

    # Vanilla terrain generation
    "vanilla-terrain": True,                # Python fallback generator when terrain_gen is missing

    # Redstone
    "redstone-enabled": True,               # Enable redstone simulation

    # Fluids
    "fluid-flow-enabled": True,             # Enable water/lava flow simulation

    # Mod and plugin directories
    "mods-directory": "mods",               # Directory for PYMC native Python mods
    "plugins-directory": "plugins",          # Directory for PYMC native Python plugins

    # Tab list header/footer (empty = none, like vanilla)
    "tab-list-header": "",
    "tab-list-footer": "",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


# 类型映射 (用于自动转换配置值): 由默认值的类型推导
TYPE_MAP = {}
for _key, _default in DEFAULT_CONFIG.items():
    if isinstance(_default, bool):
        TYPE_MAP[_key] = _parse_bool
    elif isinstance(_default, int):
        TYPE_MAP[_key] = int
    elif isinstance(_default, float):
        TYPE_MAP[_key] = float
# 旧版本 PyMC 写入的出生点键 (现在保存在 level.dat 中, 仅作首次迁移用)
for _key in ("level-spawn-x", "level-spawn-y", "level-spawn-z"):
    TYPE_MAP[_key] = int

# 不再写回 server.properties 的旧键
LEGACY_KEYS = {"level-spawn-x", "level-spawn-y", "level-spawn-z"}


def _unescape(value: str) -> str:
    """解析 Java .properties 转义 (\\: \\= \\n \\uXXXX)。"""
    if "\\" not in value:
        return value
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == "u" and i + 5 < len(value) + 1:
                try:
                    out.append(chr(int(value[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _escape(value: str) -> str:
    """按 Java Properties.store 的规则转义值。"""
    out = []
    for i, ch in enumerate(value):
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch in ":=#!":
            out.append("\\" + ch)
        elif ch == " " and i == 0:
            out.append("\\ ")
        else:
            out.append(ch)
    return "".join(out)


def load_config(filepath: str = "server.properties") -> dict:
    """
    加载服务器配置文件。
    如果文件不存在则创建默认配置；缺失的键会用默认值补齐并写回。

    返回:
        配置字典
    """
    config = dict(DEFAULT_CONFIG)
    seen: set[str] = set()

    if os.path.exists(filepath):
        logger.debug(f"正在加载配置文件: {filepath}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if not line or line.startswith('#') or line.startswith('!'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = _unescape(value.strip())

                        # 类型转换
                        if key in TYPE_MAP:
                            try:
                                value = TYPE_MAP[key](value)
                            except (ValueError, TypeError):
                                logger.warning(f"配置项 '{key}' 的值无效: '{value}'，使用默认值")
                                continue

                        config[key] = value
                        seen.add(key)
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}，使用默认配置")
        if any(key not in seen for key in DEFAULT_CONFIG):
            save_config(config, filepath)
    else:
        save_config(config, filepath)

    return config


def save_config(config: dict, filepath: str = "server.properties"):
    """保存配置到文件 (原版格式: 两行注释头 + 按键名排序)。"""
    import time
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("#Minecraft server properties\n")
            f.write(time.strftime("#%a %b %d %H:%M:%S %Z %Y\n"))

            for key in sorted(config):
                if key in LEGACY_KEYS:
                    continue
                value = config[key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                elif isinstance(value, float) and value.is_integer():
                    value = int(value)
                f.write(f"{key}={_escape(str(value))}\n")

        logger.debug(f"配置文件已保存: {filepath}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
