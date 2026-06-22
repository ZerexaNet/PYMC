# ============================================================
# PyMC - 协议层优化
# 数据包缓存、批量发送、速率限制
# ============================================================

"""
协议层优化工具。

包括:
  - PacketCache: 频繁使用的数据包编码缓存
  - PacketBatcher: 批量数据包合并发送
  - MovementRateLimiter: 移动更新速率限制
"""

import time
import logging
from collections import deque
from typing import Optional

from protocol.packet import pack_packet

logger = logging.getLogger("PyMC.协议优化")


class PacketCache:
    """
    数据包编码缓存。
    
    对于频繁发送且内容不变的数据包 (如 KeepAlive、时间更新等)，
    缓存其编码结果以避免重复序列化。
    
    注意: 仅缓存压缩阈值不变时的结果。
    """

    def __init__(self, max_size: int = 256):
        self._cache: dict[tuple[int, bytes, int], bytes] = {}
        self._max_size = max_size
        self._hits: int = 0
        self._misses: int = 0

    def get_or_encode(self, packet_id: int, payload: bytes,
                      compression_threshold: int) -> bytes:
        """
        获取缓存的数据包帧，或编码并缓存。
        """
        key = (packet_id, payload, compression_threshold)
        cached = self._cache.get(key)
        if cached is not None:
            self._hits += 1
            return cached

        # 编码并缓存
        frame = pack_packet(packet_id, payload, compression_threshold)
        self._misses += 1

        # 如果缓存已满，清除最旧的条目
        if len(self._cache) >= self._max_size:
            # 简单策略: 清除一半
            keys = list(self._cache.keys())
            for k in keys[:len(keys) // 2]:
                del self._cache[k]

        self._cache[key] = frame
        return frame

    def invalidate(self, packet_id: int | None = None):
        """
        使缓存失效。
        如果指定 packet_id，只清除该 ID 的缓存；否则清除全部。
        """
        if packet_id is None:
            self._cache.clear()
        else:
            keys_to_remove = [k for k in self._cache if k[0] == packet_id]
            for k in keys_to_remove:
                del self._cache[k]

    @property
    def hit_rate(self) -> float:
        """缓存命中率。"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    @property
    def size(self) -> int:
        """缓存条目数。"""
        return len(self._cache)


class PacketBatcher:
    """
    数据包批量发送器。
    
    将多个小数据包合并为一次 TCP 写入，减少系统调用次数。
    对于同一 tick 内需要发送多个数据包的场景特别有效。
    """

    def __init__(self, max_batch_size: int = 64 * 1024):
        self._buffer: bytearray = bytearray()
        self._max_batch_size: int = max_batch_size
        self._pending_count: int = 0

    def add(self, frame: bytes):
        """
        添加一个已编码的数据包帧到批处理缓冲区。
        """
        self._buffer.extend(frame)
        self._pending_count += 1

    @property
    def pending_count(self) -> int:
        """待发送数据包数量。"""
        return self._pending_count

    @property
    def pending_bytes(self) -> int:
        """待发送字节数。"""
        return len(self._buffer)

    @property
    def should_flush(self) -> bool:
        """判断是否应该刷新缓冲区。"""
        return len(self._buffer) >= self._max_batch_size or self._pending_count > 0

    def flush(self) -> bytes:
        """
        获取并清空缓冲区。
        返回所有待发送数据的字节串。
        """
        if not self._buffer:
            return b''
        data = bytes(self._buffer)
        self._buffer.clear()
        self._pending_count = 0
        return data


class MovementRateLimiter:
    """
    移动更新速率限制器。
    
    Minecraft 客户端每 tick 可以发送多个移动数据包，
    但服务器不需要对每一个都做完整处理。
    此限制器过滤掉过于频繁的移动更新。
    """

    def __init__(self, min_interval_ticks: int = 1, max_packets_per_window: int = 4,
                 window_ticks: int = 20):
        """
        参数:
            min_interval_ticks: 两次处理之间的最小 tick 间隔
            max_packets_per_window: 窗口内最大处理包数
            window_ticks: 统计窗口的 tick 数
        """
        self._min_interval = min_interval_ticks
        self._max_per_window = max_packets_per_window
        self._window_ticks = window_ticks
        self._last_processed: float = 0.0
        self._window_start: float = 0.0
        self._window_count: int = 0
        self._total_processed: int = 0
        self._total_dropped: int = 0

    def should_process(self, current_tick: float) -> bool:
        """
        判断当前移动数据包是否应该处理。
        
        参数:
            current_tick: 当前 tick 时间戳
        
        返回:
            True 表示应该处理，False 表示应该跳过
        """
        # 检查窗口重置
        if current_tick - self._window_start >= self._window_ticks:
            self._window_start = current_tick
            self._window_count = 0

        # 检查最小间隔
        if current_tick - self._last_processed < self._min_interval:
            self._total_dropped += 1
            return False

        # 检查窗口内最大数量
        if self._window_count >= self._max_per_window:
            self._total_dropped += 1
            return False

        self._last_processed = current_tick
        self._window_count += 1
        self._total_processed += 1
        return True

    @property
    def drop_rate(self) -> float:
        """丢弃率。"""
        total = self._total_processed + self._total_dropped
        if total == 0:
            return 0.0
        return self._total_dropped / total

    @property
    def total_processed(self) -> int:
        return self._total_processed

    @property
    def total_dropped(self) -> int:
        return self._total_dropped
