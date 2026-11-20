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
import random

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

    与原版 level.dat 的字段对应:
      - ``age``            Time: 世界总刻数, 始终递增
      - ``day_time_total`` DayTime: 昼夜时间, 受 doDaylightCycle 控制, 不取模
      - ``time``           DayTime % 24000 (向后兼容的一天内时间)
      - 天气: raining / thundering + rainTime / thunderTime / clearWeatherTime
        倒计时, doWeatherCycle 开启时按原版的随机区间自然切换。
    """

    RAIN_DURATION = (12000, 24000)
    RAIN_DELAY = (12000, 180000)
    THUNDER_DURATION = (3600, 15600)
    THUNDER_DELAY = (12000, 180000)

    def __init__(self, initial_time: int = 1000, do_daylight_cycle: bool = True):
        self._day_time: int = int(initial_time)
        self._age: int = 0
        self._do_daylight_cycle = do_daylight_cycle
        self._do_weather_cycle: bool = True
        self._weather: str = "clear"
        self._weather_duration: int = 0  # 当前天气剩余 tick (0 = 由自然循环决定)
        self._thunder_duration: int = 0
        self._natural_delay: int = random.randint(*self.RAIN_DELAY)

    @property
    def time(self) -> int:
        """一天内的时间 (0-23999 ticks)。"""
        return self._day_time % MAX_TIME

    @time.setter
    def time(self, value: int):
        self._day_time = int(value) % MAX_TIME

    @property
    def day_time_total(self) -> int:
        """level.dat 的 DayTime (不取模, 含天数)。"""
        return self._day_time

    @day_time_total.setter
    def day_time_total(self, value: int):
        self._day_time = max(0, int(value))

    @property
    def age(self) -> int:
        """世界总刻数 (level.dat 的 Time)。"""
        return self._age

    @age.setter
    def age(self, value: int):
        self._age = max(0, int(value))

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
        self._age += 1
        if self._do_daylight_cycle:
            self._day_time += 1

        # 天气持续计时 (doWeatherCycle=false 时天气保持不变)
        if not self._do_weather_cycle:
            return
        if self._thunder_duration > 0:
            self._thunder_duration -= 1
            if self._thunder_duration == 0 and self._weather == "thunder":
                self._weather = "rain"
        if self._weather_duration > 0:
            self._weather_duration -= 1
            if self._weather_duration == 0:
                if self._weather == "clear":
                    self._start_natural_weather()
                else:
                    self._weather = "clear"
                    self._thunder_duration = 0
                    self._natural_delay = random.randint(*self.RAIN_DELAY)
            return
        if self._weather == "clear":
            # 自然天气循环: 倒计时结束后开始下雨 (小概率雷暴)
            self._natural_delay -= 1
            if self._natural_delay <= 0:
                self._start_natural_weather()

    def _start_natural_weather(self):
        self._weather = "rain"
        self._weather_duration = random.randint(*self.RAIN_DURATION)
        if random.random() < 0.25:
            self._weather = "thunder"
            self._thunder_duration = min(
                self._weather_duration, random.randint(*self.THUNDER_DURATION))

    def set_time(self, value) -> int:
        """
        设置世界时间。
        支持预设名称和数字值。
        """
        if isinstance(value, str):
            preset = TIME_PRESETS.get(value.lower())
            if preset is None:
                try:
                    preset = int(value)
                except ValueError:
                    logger.warning(f"无效的时间值: {value}")
                    return self.time
            value = preset
        self._day_time = max(0, int(value))
        return self.time

    def add_time(self, ticks: int) -> int:
        """增加世界时间。"""
        self._day_time = max(0, self._day_time + int(ticks))
        return self.time

    def get_day_count(self) -> int:
        """获取当前是第几天。"""
        return self._day_time // MAX_TIME

    def set_weather(self, weather: str, duration: int = 0):
        """
        设置天气。
        duration: 天气持续的 tick 数 (0 = 无限, 直到手动变更)。
        """
        if weather not in ("clear", "rain", "thunder"):
            return
        self._weather = weather
        self._weather_duration = max(0, int(duration))
        self._thunder_duration = self._weather_duration if weather == "thunder" else 0
        if weather == "clear" and self._weather_duration == 0:
            self._natural_delay = random.randint(*self.RAIN_DELAY)

    def serialize(self) -> dict:
        """序列化时间状态。"""
        return {
            "time": self.time,
            "day_time": self._day_time,
            "age": self._age,
            "weather": self._weather,
            "weather_duration": self._weather_duration,
            "thunder_duration": self._thunder_duration,
            "do_daylight_cycle": self._do_daylight_cycle,
            "do_weather_cycle": self._do_weather_cycle,
        }

    @classmethod
    def deserialize(cls, data: dict) -> 'TimeManager':
        """从字典反序列化。"""
        mgr = cls(
            initial_time=data.get("day_time", data.get("time", 1000)),
            do_daylight_cycle=data.get("do_daylight_cycle", True),
        )
        mgr._age = int(data.get("age", 0))
        mgr._weather = data.get("weather", "clear")
        mgr._weather_duration = data.get("weather_duration", 0)
        mgr._thunder_duration = data.get("thunder_duration", 0)
        mgr._do_weather_cycle = data.get("do_weather_cycle", True)
        return mgr

    # ---- level.dat 互转 ----

    def apply_level_data(self, level) -> None:
        self._age = int(level.game_time)
        self._day_time = int(level.day_time)
        if level.raining and level.thundering:
            self._weather = "thunder"
        elif level.raining:
            self._weather = "rain"
        else:
            self._weather = "clear"
        if self._weather == "clear":
            self._weather_duration = 0
            if level.rain_time > 0:
                self._natural_delay = int(level.rain_time)
        else:
            self._weather_duration = int(level.rain_time)
            self._thunder_duration = int(level.thunder_time) if level.thundering else 0

    def write_level_data(self, level) -> None:
        level.game_time = self._age
        level.day_time = self._day_time
        level.raining = self._weather in ("rain", "thunder")
        level.thundering = self._weather == "thunder"
        level.rain_time = (self._weather_duration if level.raining
                           else max(0, self._natural_delay))
        level.thunder_time = self._thunder_duration
        level.clear_weather_time = 0
