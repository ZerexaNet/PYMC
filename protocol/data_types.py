# ============================================================
# PyMC - 协议基础数据类型
# 实现 Minecraft 协议所需的所有基础数据类型的编解码
# ============================================================

import struct
import uuid as _uuid


# --------------------------------------------------
# VarInt / VarLong 编解码
# --------------------------------------------------

def write_varint(value: int) -> bytes:
    """将整数编码为 VarInt 格式 (最多 5 字节)。"""
    # 处理负数: 转为无符号 32 位
    if value < 0:
        value = value + (1 << 32)
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        result.append(byte)
        if value == 0:
            break
    return bytes(result)


def read_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """
    从字节流中读取 VarInt。
    返回 (值, 新偏移量)。
    """
    result = 0
    num_read = 0
    while True:
        if offset >= len(data):
            raise ValueError("VarInt 数据不足，无法继续读取")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt 超过最大长度 (5 字节)")
        if (byte & 0x80) == 0:
            break
    # 转为有符号 32 位
    if result >= (1 << 31):
        result -= (1 << 32)
    return result, offset


async def read_varint_async(reader) -> int:
    """从 asyncio.StreamReader 中异步读取 VarInt。"""
    result = 0
    num_read = 0
    while True:
        data = await reader.readexactly(1)
        byte = data[0]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt 超过最大长度 (5 字节)")
        if (byte & 0x80) == 0:
            break
    if result >= (1 << 31):
        result -= (1 << 32)
    return result


def write_varlong(value: int) -> bytes:
    """将整数编码为 VarLong 格式 (最多 10 字节)。"""
    if value < 0:
        value = value + (1 << 64)
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        result.append(byte)
        if value == 0:
            break
    return bytes(result)


def read_varlong(data: bytes, offset: int = 0) -> tuple[int, int]:
    """从字节流中读取 VarLong。返回 (值, 新偏移量)。"""
    result = 0
    num_read = 0
    while True:
        if offset >= len(data):
            raise ValueError("VarLong 数据不足")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 10:
            raise ValueError("VarLong 超过最大长度 (10 字节)")
        if (byte & 0x80) == 0:
            break
    if result >= (1 << 63):
        result -= (1 << 64)
    return result, offset


# --------------------------------------------------
# 基础类型编码 (大端序)
# --------------------------------------------------

def write_boolean(value: bool) -> bytes:
    """编码布尔值。"""
    return b'\x01' if value else b'\x00'


def read_boolean(data: bytes, offset: int = 0) -> tuple[bool, int]:
    """读取布尔值。"""
    return data[offset] != 0, offset + 1


def write_byte(value: int) -> bytes:
    """编码有符号字节 (-128 ~ 127)。"""
    return struct.pack('>b', value)


def read_byte(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取有符号字节。"""
    return struct.unpack_from('>b', data, offset)[0], offset + 1


def write_ubyte(value: int) -> bytes:
    """编码无符号字节 (0 ~ 255)。"""
    return struct.pack('>B', value)


def read_ubyte(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取无符号字节。"""
    return struct.unpack_from('>B', data, offset)[0], offset + 1


def write_short(value: int) -> bytes:
    """编码有符号 Short (16位)。"""
    return struct.pack('>h', value)


def read_short(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取有符号 Short。"""
    return struct.unpack_from('>h', data, offset)[0], offset + 2


def write_ushort(value: int) -> bytes:
    """编码无符号 Short (16位)。"""
    return struct.pack('>H', value)


def read_ushort(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取无符号 Short。"""
    return struct.unpack_from('>H', data, offset)[0], offset + 2


def write_int(value: int) -> bytes:
    """编码有符号 Int (32位)。"""
    return struct.pack('>i', value)


def read_int(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取有符号 Int。"""
    return struct.unpack_from('>i', data, offset)[0], offset + 4


def write_long(value: int) -> bytes:
    """编码有符号 Long (64位)。"""
    return struct.pack('>q', value)


def read_long(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取有符号 Long。"""
    return struct.unpack_from('>q', data, offset)[0], offset + 8


def write_ulong(value: int) -> bytes:
    """编码无符号 Long (64位)。"""
    return struct.pack('>Q', value)


def read_ulong(data: bytes, offset: int = 0) -> tuple[int, int]:
    """读取无符号 Long。"""
    return struct.unpack_from('>Q', data, offset)[0], offset + 8


def write_float(value: float) -> bytes:
    """编码 Float (32位浮点)。"""
    return struct.pack('>f', value)


def read_float(data: bytes, offset: int = 0) -> tuple[float, int]:
    """读取 Float。"""
    return struct.unpack_from('>f', data, offset)[0], offset + 4


def write_double(value: float) -> bytes:
    """编码 Double (64位浮点)。"""
    return struct.pack('>d', value)


def read_double(data: bytes, offset: int = 0) -> tuple[float, int]:
    """读取 Double。"""
    return struct.unpack_from('>d', data, offset)[0], offset + 8


# --------------------------------------------------
# 字符串编解码 (UTF-8 + VarInt 长度前缀)
# --------------------------------------------------

def write_string(value: str) -> bytes:
    """编码 Minecraft 协议字符串 (UTF-8 + VarInt 长度前缀)。"""
    encoded = value.encode('utf-8')
    return write_varint(len(encoded)) + encoded


def read_string(data: bytes, offset: int = 0) -> tuple[str, int]:
    """读取 Minecraft 协议字符串。"""
    length, offset = read_varint(data, offset)
    if length < 0:
        raise ValueError(f"字符串长度不能为负数: {length}")
    end = offset + length
    if end > len(data):
        raise ValueError("字符串数据不足")
    return data[offset:end].decode('utf-8'), end


# --------------------------------------------------
# UUID 编解码
# --------------------------------------------------

def write_uuid(value: _uuid.UUID) -> bytes:
    """编码 UUID (128位，大端序)。"""
    return value.bytes


def read_uuid(data: bytes, offset: int = 0) -> tuple[_uuid.UUID, int]:
    """读取 UUID。"""
    return _uuid.UUID(bytes=data[offset:offset + 16]), offset + 16


# --------------------------------------------------
# 位置编码 (Position: X/Y/Z 打包为 Long)
# --------------------------------------------------

def write_position(x: int, y: int, z: int) -> bytes:
    """
    将方块坐标编码为 Position 格式。
    X: 26位, Z: 26位, Y: 12位 (有符号)
    """
    # 处理有符号数
    if x < 0:
        x = x + (1 << 26)
    if z < 0:
        z = z + (1 << 26)
    if y < 0:
        y = y + (1 << 12)
    val = ((x & 0x3FFFFFF) << 38) | ((z & 0x3FFFFFF) << 12) | (y & 0xFFF)
    return struct.pack('>Q', val)


def read_position(data: bytes, offset: int = 0) -> tuple[tuple[int, int, int], int]:
    """读取 Position，返回 ((x, y, z), 新偏移量)。"""
    val = struct.unpack_from('>Q', data, offset)[0]
    x = val >> 38
    z = (val >> 12) & 0x3FFFFFF
    y = val & 0xFFF
    # 转为有符号
    if x >= (1 << 25):
        x -= (1 << 26)
    if z >= (1 << 25):
        z -= (1 << 26)
    if y >= (1 << 11):
        y -= (1 << 12)
    return (x, y, z), offset + 8


# --------------------------------------------------
# Angle 编解码 (1/256 圈)
# --------------------------------------------------

def write_angle(degrees: float) -> bytes:
    """将角度 (0-360) 编码为协议 Angle (0-255)。"""
    return struct.pack('>B', int((degrees / 360.0) * 256) & 0xFF)


def read_angle(data: bytes, offset: int = 0) -> tuple[float, int]:
    """读取 Angle，返回角度值。"""
    raw = data[offset]
    return (raw / 256.0) * 360.0, offset + 1


# --------------------------------------------------
# 字节数组
# --------------------------------------------------

def write_byte_array(data_bytes: bytes) -> bytes:
    """编码字节数组 (VarInt 长度前缀 + 数据)。"""
    return write_varint(len(data_bytes)) + data_bytes


def read_byte_array(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    """读取字节数组。"""
    length, offset = read_varint(data, offset)
    end = offset + length
    return data[offset:end], end


# --------------------------------------------------
# 标识符 (Identifier / Namespace:Path)
# --------------------------------------------------

def write_identifier(namespace: str, path: str = None) -> bytes:
    """
    编码标识符。
    如果只传入一个参数且包含冒号，则直接作为完整标识符。
    """
    if path is None:
        return write_string(namespace)
    return write_string(f"{namespace}:{path}")


def read_identifier(data: bytes, offset: int = 0) -> tuple[str, int]:
    """读取标识符。"""
    return read_string(data, offset)
