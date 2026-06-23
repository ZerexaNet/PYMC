# ============================================================
# PyMC - 游戏规则管理器
# 管理 gamerule 的读取、设置和持久化
# ============================================================

"""
GameruleManager - 游戏规则管理。

将原先直接在 MinecraftServer 中使用的 gamerules 字典
封装为独立的管理器类，提供类型安全的接口和持久化支持。
"""

import logging
from typing import Any

logger = logging.getLogger("PyMC.游戏规则")

# --- 默认游戏规则 ---
DEFAULT_GAMERULES: dict[str, bool] = {
    "doDaylightCycle": True,
    "doMobSpawning": True,
    "naturalRegeneration": True,
    "keepInventory": False,
    "doImmediateRespawn": False,
    "doWeatherCycle": True,
    "doEntityDrops": True,
    "doTileDrops": True,
    "doMobLoot": True,
    "doInsomnia": True,
    "doPatrolSpawning": True,
    "doTraderSpawning": True,
    "doWardenSpawning": True,
    "fallDamage": True,
    "fireDamage": True,
    "freezeDamage": True,
    "drowningDamage": True,
    "forgiveDeadPlayers": True,
    "universalAnger": False,
    "announceAdvancements": True,
    "commandBlockOutput": True,
    "disableElytraMovementCheck": False,
    "disablePlayerMovementCheck": False,
    "doLimitedCrafting": False,
    "logAdminCommands": True,
    "maxCommandChainLength": 65536,
    "maxEntityCramming": 24,
    "mobGriefing": True,
    "playersSleepingPercentage": 100,
    "randomTickSpeed": 3,
    "reducedDebugInfo": False,
    "sendCommandFeedback": True,
    "showDeathMessages": True,
    "spawnRadius": 10,
    "spectatorsGenerateChunks": True,
}


class GameruleManager:
    """
    游戏规则管理器。
    
    支持 bool 和 int 两种类型的规则。
    提供获取/设置/序列化/反序列化接口。
    """

    def __init__(self, initial_rules: dict[str, Any] | None = None):
        self._rules: dict[str, Any] = dict(DEFAULT_GAMERULES)
        if initial_rules:
            for key, value in initial_rules.items():
                if key in self._rules:
                    self._rules[key] = self._coerce(key, value)

    def _coerce(self, key: str, value: Any) -> Any:
        """将配置值强制转换为正确的类型。"""
        default = self._rules.get(key)
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        if isinstance(default, int):
            return int(value)
        return value

    def get(self, name: str, default: Any = None) -> Any:
        """获取游戏规则值。"""
        return self._rules.get(name, default)

    def set(self, name: str, value: Any) -> bool:
        """
        设置游戏规则值。
        返回 True 表示设置成功，False 表示规则不存在。
        """
        if name not in self._rules:
            return False
        self._rules[name] = self._coerce(name, value)
        logger.info(f"游戏规则 {name} 已设置为 {self._rules[name]}")
        return True

    def has(self, name: str) -> bool:
        """判断游戏规则是否存在。"""
        return name in self._rules

    def all_rules(self) -> dict[str, Any]:
        """获取所有游戏规则的副本。"""
        return dict(self._rules)

    def known_rules(self) -> list[str]:
        """获取所有已知规则名称列表。"""
        return sorted(self._rules.keys())

    def serialize(self) -> dict[str, Any]:
        """序列化为可保存的字典。"""
        return dict(self._rules)

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> 'GameruleManager':
        """从字典反序列化。"""
        return cls(initial_rules=data)

    def __contains__(self, name: str) -> bool:
        return name in self._rules

    def __getitem__(self, name: str) -> Any:
        return self._rules[name]

    def __setitem__(self, name: str, value: Any):
        """支持字典式赋值 (向后兼容)。"""
        self._rules[name] = self._coerce(name, value)

    def __iter__(self):
        return iter(self._rules)

    def keys(self):
        """支持 dict.keys() 接口。"""
        return self._rules.keys()

    def values(self):
        """支持 dict.values() 接口。"""
        return self._rules.values()

    def items(self):
        """支持 dict.items() 接口。"""
        return self._rules.items()

    def __repr__(self) -> str:
        return f"<GameruleManager rules={len(self._rules)}>"
