# ============================================================
# PyMC - 世界时间管理器
# 管理世界时间、昼夜循环和天气
# ============================================================

"""
TimeManager - 世界时间与天气管理。

将原先在 MinecraftServer 中的 world_time / weather 管理
封装为独立的管理器类。
"""

import logging

logger = logging.getLogger("PyMC.时间")

# --- 时间预设 ---
TIME_PRESETS = {
    "day": 1000,
    "noon": 6000,
    "night": 13000,
    "midnight": 18000,
    "sunrise": 23000,
    "sunset": 12000,
}

MAX_TIME = 24000


class TimeManager:
    """
    世界时间管理器。
    
    管理游戏内时间 (0-23999 ticks)、昼夜循环和天气状态。
    """

    def __init__(self, initial_time: int = 1000, do_daylight_cycle: bool = True):
        self._time: int = initial_time % MAX_TIME
        self._do_daylight_cycle = do_daylight_cycle
        self._do_weather_cycle: bool = True
        self._weather: str = "clear"
        self._weather_duration: int = 0  # ticks remaining
        self._thunder_duration: int = 0

    @property
    def time(self) -> int:
        """当前世界时间 (ticks)。"""
        return self._time

    @time.setter
    def time(self, value: int):
        self._time = value % MAX_TIME

    @property
    def weather(self) -> str:
        """当前天气状态。"""
        return self._weather

    @weather.setter
    def weather(self, value: str):
        if value not in ("clear", "rain", "thunder"):
            logger.warning(f"无效天气: {value}")
            return
        self._weather = value

    @property
    def do_daylight_cycle(self) -> bool:
        """是否启用昼夜循环。"""
        return self._do_daylight_cycle

    @do_daylight_cycle.setter
    def do_daylight_cycle(self, value: bool):
        self._do_daylight_cycle = value

    @property
    def do_weather_cycle(self) -> bool:
        """是否启用天气循环 (gamerule doWeatherCycle)。"""
        return self._do_weather_cycle

    @do_weather_cycle.setter
    def do_weather_cycle(self, value: bool):
        self._do_weather_cycle = value

    def tick(self):
        """
        每游戏 tick 调用。
        推进时间并更新天气。
        """
        if self._do_daylight_cycle:
            self._time = (self._time + 1) % MAX_TIME

        # 天气持续计时 (doWeatherCycle=false 时天气保持不变)
        if not self._do_weather_cycle:
            return
        if self._weather_duration > 0:
            self._weather_duration -= 1
            if self._weather_duration == 0:
                self._weather = "clear"
        if self._thunder_duration > 0:
            self._thunder_duration -= 1
            if self._thunder_duration == 0 and self._weather == "thunder":
                self._weather = "rain"

    def set_time(self, value) -> int:
        """
        设置世界时间。
        支持预设名称和数字值。
        """
        if isinstance(value, str):
            value = TIME_PRESETS.get(value.lower())
            if value is None:
                try:
                    value = int(value)
                except ValueError:
                    logger.warning(f"无效的时间值: {value}")
                    return self._time
        self._time = int(value) % MAX_TIME
        return self._time

    def add_time(self, ticks: int) -> int:
        """增加世界时间。"""
        self._time = (self._time + ticks) % MAX_TIME
        return self._time

    def get_day_time(self) -> float:
        """获取以小时表示的游戏时间。"""
        return (self._time / MAX_TIME) * 24.0

    def get_day_count(self) -> int:
        """获取当前是第几天 (基于总时间)。"""
        return self._time // MAX_TIME

    def is_daytime(self) -> bool:
        """判断是否为白天。"""
        return 0 <= self._time < 12000 or self._time >= 23000

    def is_nighttime(self) -> bool:
        """判断是否为夜晚。"""
        return 12000 <= self._time < 23000

    def set_weather(self, weather: str, duration: int = 0):
        """
        设置天气。
        duration: 天气持续的 tick 数 (0 = 无限)。
        """
        if weather not in ("clear", "rain", "thunder"):
            return
        self._weather = weather
        self._weather_duration = duration
        if weather == "thunder":
            self._thunder_duration = duration

    def serialize(self) -> dict:
        """序列化时间状态。"""
        return {
            "time": self._time,
            "weather": self._weather,
            "weather_duration": self._weather_duration,
            "do_daylight_cycle": self._do_daylight_cycle,
            "do_weather_cycle": self._do_weather_cycle,
        }

    @classmethod
    def deserialize(cls, data: dict) -> 'TimeManager':
        """从字典反序列化。"""
        mgr = cls(
            initial_time=data.get("time", 1000),
            do_daylight_cycle=data.get("do_daylight_cycle", True),
        )
        mgr._weather = data.get("weather", "clear")
        mgr._weather_duration = data.get("weather_duration", 0)
        mgr._do_weather_cycle = data.get("do_weather_cycle", True)
        return mgr
