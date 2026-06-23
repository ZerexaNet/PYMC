# ============================================================
# PyMC - 数据包帧处理
# 实现数据包的读取、写入、压缩和解压缩
# ============================================================

import zlib
from .data_types import write_varint, read_varint, read_varint_async


class PacketBuffer:
    """
    数据包缓冲区，用于方便地构建和读取数据包内容。
    """

    def __init__(self, data: bytes = b''):
        self._data = bytearray(data)
        self._offset = 0

    @property
    def data(self) -> bytes:
        """获取缓冲区中的所有数据。"""
        return bytes(self._data)

    @property
    def remaining(self) -> int:
        """剩余可读字节数。"""
        return len(self._data) - self._offset

    def write(self, data: bytes):
        """向缓冲区写入原始字节。"""
        self._data.extend(data)

    def read(self, length: int) -> bytes:
        """从缓冲区读取指定长度的字节。"""
        if self._offset + length > len(self._data):
            raise ValueError(f"缓冲区数据不足: 需要 {length} 字节, 剩余 {self.remaining} 字节")
        result = bytes(self._data[self._offset:self._offset + length])
        self._offset += length
        return result

    def read_all(self) -> bytes:
        """读取剩余所有字节。"""
        result = bytes(self._data[self._offset:])
        self._offset = len(self._data)
        return result

    def reset(self):
        """重置读取位置到开头。"""
        self._offset = 0


def pack_packet(packet_id: int, payload: bytes, compression_threshold: int = -1) -> bytes:
    """
    将数据包 ID 和负载打包为可发送的帧。

    参数:
        packet_id: 数据包 ID
        payload: 数据包负载
        compression_threshold: 压缩阈值 (-1 表示不压缩)

    返回:
        完整的数据包帧字节
    """
    # 数据包 ID + 负载
    packet_id_bytes = write_varint(packet_id)
    uncompressed_data = packet_id_bytes + payload

    if compression_threshold < 0:
        # 未启用压缩: 长度 + 数据包ID + 负载
        return write_varint(len(uncompressed_data)) + uncompressed_data
    else:
        # 启用压缩
        data_length = len(uncompressed_data)
        if data_length >= compression_threshold:
            # 需要压缩
            compressed = zlib.compress(uncompressed_data)
            data_length_bytes = write_varint(data_length)
            packet_length = len(data_length_bytes) + len(compressed)
            return write_varint(packet_length) + data_length_bytes + compressed
        else:
            # 不需要压缩 (数据长度字段为 0)
            data_length_bytes = write_varint(0)
            packet_length = len(data_length_bytes) + len(uncompressed_data)
            return write_varint(packet_length) + data_length_bytes + uncompressed_data


async def read_packet_async(reader, compression_threshold: int = -1) -> tuple[int, bytes]:
    """
    从异步流中读取一个完整的数据包。

    返回:
        (数据包ID, 负载字节)

    异常:
        asyncio.IncompleteReadError: 连接断开
        ValueError: 数据格式错误
    """
    # 读取数据包长度
    packet_length = await read_varint_async(reader)
    if packet_length <= 0:
        raise ValueError(f"无效的数据包长度: {packet_length}")

    # 限制最大数据包大小 (2MB)
    if packet_length > 2 * 1024 * 1024:
        raise ValueError(f"数据包过大: {packet_length} 字节")

    # 读取完整数据包内容
    raw_data = await reader.readexactly(packet_length)

    if compression_threshold < 0:
        # 未启用压缩
        packet_id, offset = read_varint(raw_data, 0)
        payload = raw_data[offset:]
        return packet_id, payload
    else:
        # 启用压缩
        data_length, offset = read_varint(raw_data, 0)
        remaining = raw_data[offset:]

        if data_length == 0:
            # 未压缩
            packet_id, poffset = read_varint(remaining, 0)
            payload = remaining[poffset:]
            return packet_id, payload
        else:
            # 解压缩
            decompressed = zlib.decompress(remaining)
            if len(decompressed) != data_length:
                raise ValueError(
                    f"解压后数据长度不匹配: 期望 {data_length}, 实际 {len(decompressed)}"
                )
            packet_id, poffset = read_varint(decompressed, 0)
            payload = decompressed[poffset:]
            return packet_id, payload
