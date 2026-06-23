# ============================================================
# PyMC - 服务器指标监控
# TPS、区块生成吞吐、内存使用、网络 I/O 统计
# ============================================================

"""
ServerMetrics - 服务器性能指标收集与报告。

包括:
  - TPS 计量 (实际每秒 tick 数)
  - 区块生成吞吐量 (chunks/s)
  - 内存使用追踪
  - 网络 I/O 统计 (发送/接收字节数)
"""

import time
import os
import logging
from typing import Optional

logger = logging.getLogger("PyMC.指标")


class TPSMeter:
    """
    TPS (Ticks Per Second) 计量器。
    
    通过滑动窗口采样计算实际 TPS。
    """

    def __init__(self, window_size: int = 100):
        self._window_size = window_size
        self._tick_times: list[float] = []
        self._last_tick_time: float = time.time()
        self._current_tps: float = 20.0

    def tick(self):
        """每 tick 调用一次，记录时间戳。"""
        now = time.time()
        self._tick_times.append(now)

        # 保持窗口大小
        if len(self._tick_times) > self._window_size:
            self._tick_times = self._tick_times[-self._window_size:]

        # 计算 TPS
        if len(self._tick_times) >= 2:
            elapsed = self._tick_times[-1] - self._tick_times[0]
            if elapsed > 0:
                self._current_tps = min(20.0, (len(self._tick_times) - 1) / elapsed)

        self._last_tick_time = now

    @property
    def tps(self) -> float:
        """当前 TPS。"""
        return self._current_tps

    @property
    def mspt(self) -> float:
        """每 tick 平均耗时 (毫秒)。"""
        if self._current_tps <= 0:
            return 50.0
        return 1000.0 / self._current_tps


class ChunkThroughputCounter:
    """
    区块生成吞吐量计数器。
    """

    def __init__(self, window_seconds: float = 60.0):
        self._window_seconds = window_seconds
        self._records: list[tuple[float, int]] = []  # (timestamp, count)
        self._total_generated: int = 0
        self._total_loaded: int = 0

    def record_generation(self, count: int, loaded: int):
        """记录一次区块生成。"""
        now = time.time()
        self._records.append((now, count))
        self._total_generated += count - loaded
        self._total_loaded += loaded

        # 清理过期记录
        cutoff = now - self._window_seconds
        self._records = [(t, c) for t, c in self._records if t > cutoff]

    @property
    def chunks_per_second(self) -> float:
        """最近窗口内的平均每秒区块生成数。"""
        if not self._records:
            return 0.0
        now = time.time()
        cutoff = now - self._window_seconds
        recent = [(t, c) for t, c in self._records if t > cutoff]
        if len(recent) < 2:
            return 0.0
        total = sum(c for _, c in recent)
        elapsed = recent[-1][0] - recent[0][0]
        if elapsed <= 0:
            return 0.0
        return total / elapsed

    @property
    def total_generated(self) -> int:
        """总生成区块数。"""
        return self._total_generated

    @property
    def total_loaded(self) -> int:
        """总加载区块数。"""
        return self._total_loaded


class MemoryTracker:
    """
    内存使用追踪器。
    """

    def __init__(self):
        self._peak_rss: int = 0
        self._samples: list[tuple[float, int]] = []

    def sample(self):
        """采样当前内存使用。"""
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux: ru_maxrss 单位是 KB; macOS: 字节
            if rss > 0 and rss < 100 * 1024 * 1024:  # 看起来是 KB
                rss *= 1024  # 转换为字节
        except ImportError:
            rss = 0

        # 使用 /proc/self/status 作为备选
        if rss == 0:
            try:
                with open("/proc/self/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss = int(line.split()[1]) * 1024  # KB -> bytes
                            break
            except (FileNotFoundError, ValueError):
                rss = 0

        now = time.time()
        self._samples.append((now, rss))
        if len(self._samples) > 60:
            self._samples = self._samples[-60:]

        if rss > self._peak_rss:
            self._peak_rss = rss

    @property
    def current_rss(self) -> int:
        """当前 RSS 内存使用 (字节)。"""
        if self._samples:
            return self._samples[-1][1]
        return 0

    @property
    def peak_rss(self) -> int:
        """峰值 RSS 内存使用 (字节)。"""
        return self._peak_rss

    @property
    def current_rss_mb(self) -> float:
        """当前 RSS 内存使用 (MB)。"""
        return self.current_rss / (1024 * 1024)

    @property
    def peak_rss_mb(self) -> float:
        """峰值 RSS 内存使用 (MB)。"""
        return self._peak_rss / (1024 * 1024)


class NetworkIOTracker:
    """
    网络 I/O 统计追踪器。
    """

    def __init__(self):
        self._bytes_sent: int = 0
        self._bytes_received: int = 0
        self._packets_sent: int = 0
        self._packets_received: int = 0
        self._start_time: float = time.time()

    def record_send(self, byte_count: int, packet_count: int = 1):
        """记录发送数据。"""
        self._bytes_sent += byte_count
        self._packets_sent += packet_count

    def record_receive(self, byte_count: int, packet_count: int = 1):
        """记录接收数据。"""
        self._bytes_received += byte_count
        self._packets_received += packet_count

    @property
    def bytes_sent(self) -> int:
        return self._bytes_sent

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    @property
    def packets_sent(self) -> int:
        return self._packets_sent

    @property
    def packets_received(self) -> int:
        return self._packets_received

    @property
    def send_rate_kbps(self) -> float:
        """平均发送速率 (KB/s)。"""
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        return (self._bytes_sent / 1024) / elapsed

    @property
    def receive_rate_kbps(self) -> float:
        """平均接收速率 (KB/s)。"""
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        return (self._bytes_received / 1024) / elapsed

    def reset(self):
        """重置所有统计。"""
        self._bytes_sent = 0
        self._bytes_received = 0
        self._packets_sent = 0
        self._packets_received = 0
        self._start_time = time.time()


class ServerMetrics:
    """
    服务器指标集合。
    
    整合所有指标追踪器，提供统一的采样和报告接口。
    """

    def __init__(self):
        self.tps = TPSMeter()
        self.chunk_throughput = ChunkThroughputCounter()
        self.memory = MemoryTracker()
        self.network = NetworkIOTracker()
        self._last_report_time: float = time.time()
        self._report_interval: float = 60.0  # 每 60 秒输出一次报告

    def tick(self):
        """每 tick 调用，更新指标。"""
        self.tps.tick()

    def should_report(self) -> bool:
        """判断是否应该输出报告。"""
        return time.time() - self._last_report_time >= self._report_interval

    def report(self) -> str:
        """生成指标报告字符串。"""
        self.memory.sample()
        self._last_report_time = time.time()

        lines = [
            f"--- 服务器指标 ---",
            f"TPS: {self.tps.tps:.1f} (MSPT: {self.tps.mspt:.1f}ms)",
            f"内存: {self.memory.current_rss_mb:.1f}MB / 峰值 {self.memory.peak_rss_mb:.1f}MB",
            f"区块吞吐: {self.chunk_throughput.chunks_per_second:.1f} chunks/s "
            f"(生成: {self.chunk_throughput.total_generated}, 加载: {self.chunk_throughput.total_loaded})",
            f"网络: 发送 {self.network.send_rate_kbps:.1f}KB/s, "
            f"接收 {self.network.receive_rate_kbps:.1f}KB/s "
            f"({self.network.packets_sent} 包发, {self.network.packets_received} 包收)",
        ]
        return "\n".join(lines)
