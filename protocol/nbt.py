# ============================================================
# PyMC - 简化版 NBT (Named Binary Tag) 编码器
# 用于构建 Registry Codec、文本组件等所需的 NBT 数据
# ============================================================

"""
NBT 标签类型常量及编码工具。
在 Minecraft 1.20.2+ 中，网络协议中的 NBT 不再有根标签名称，
但仍然需要标签类型前缀字节。
"""

import struct
from typing import Any

# NBT 标签类型 ID
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


def _encode_string(s: str) -> bytes:
    """编码 NBT 字符串 (无符号 Short 长度前缀 + Modified UTF-8)。"""
    encoded = s.encode('utf-8')
    return struct.pack('>H', len(encoded)) + encoded


def encode_nbt(tag: Any, with_type: bool = True, root_name: str = None) -> bytes:
    """
    将 Python 对象编码为 NBT 二进制格式。

    支持的类型映射:
        - dict -> TAG_COMPOUND
        - list -> TAG_LIST
        - str -> TAG_STRING
        - int -> TAG_INT
        - float -> TAG_FLOAT
        - bool -> TAG_BYTE (0/1)
        - bytes -> TAG_BYTE_ARRAY
        - NbtByte/NbtShort/NbtLong/NbtDouble 等 -> 对应类型

    参数:
        tag: 要编码的数据
        with_type: 是否在最外层包含类型前缀 (网络协议中需要)
        root_name: 根标签名称 (1.20.2+ 网络协议中通常为 None 或空)
    """
    result = bytearray()

    if with_type:
        tag_type = _get_tag_type(tag)
        result.append(tag_type)
        # 网络协议中的根复合标签没有名称
        if root_name is not None:
            result.extend(_encode_string(root_name))

    result.extend(_encode_tag_payload(tag))
    return bytes(result)


def _get_tag_type(value: Any) -> int:
    """推断 Python 值对应的 NBT 标签类型。"""
    if isinstance(value, NbtByte):
        return TAG_BYTE
    if isinstance(value, NbtShort):
        return TAG_SHORT
    if isinstance(value, NbtLong):
        return TAG_LONG
    if isinstance(value, NbtDouble):
        return TAG_DOUBLE
    if isinstance(value, NbtFloat):
        return TAG_FLOAT
    if isinstance(value, NbtIntArray):
        return TAG_INT_ARRAY
    if isinstance(value, NbtLongArray):
        return TAG_LONG_ARRAY
    if isinstance(value, bool):
        return TAG_BYTE
    if isinstance(value, int):
        return TAG_INT
    if isinstance(value, float):
        return TAG_FLOAT
    if isinstance(value, str):
        return TAG_STRING
    if isinstance(value, bytes):
        return TAG_BYTE_ARRAY
    if isinstance(value, list):
        return TAG_LIST
    if isinstance(value, dict):
        return TAG_COMPOUND
    raise TypeError(f"无法将类型 {type(value).__name__} 转换为 NBT 标签")


def _encode_tag_payload(value: Any) -> bytes:
    """编码标签的负载部分 (不含类型和名称)。"""
    if isinstance(value, NbtByte):
        return struct.pack('>b', value.value)
    if isinstance(value, NbtShort):
        return struct.pack('>h', value.value)
    if isinstance(value, NbtLong):
        return struct.pack('>q', value.value)
    if isinstance(value, NbtDouble):
        return struct.pack('>d', value.value)
    if isinstance(value, NbtFloat):
        return struct.pack('>f', value.value)
    if isinstance(value, NbtIntArray):
        result = struct.pack('>i', len(value.values))
        for v in value.values:
            result += struct.pack('>i', v)
        return result
    if isinstance(value, NbtLongArray):
        result = struct.pack('>i', len(value.values))
        for v in value.values:
            result += struct.pack('>q', v)
        return result
    if isinstance(value, bool):
        return struct.pack('>b', 1 if value else 0)
    if isinstance(value, int):
        return struct.pack('>i', value)
    if isinstance(value, float):
        return struct.pack('>f', value)
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, bytes):
        return struct.pack('>i', len(value)) + value
    if isinstance(value, list):
        return _encode_list(value)
    if isinstance(value, dict):
        return _encode_compound(value)
    raise TypeError(f"无法编码类型 {type(value).__name__}")


def _encode_list(items: list) -> bytes:
    """编码 TAG_LIST。"""
    if len(items) == 0:
        # 空列表: 类型为 TAG_END, 长度为 0
        return struct.pack('>bi', TAG_END, 0)

    # 推断列表元素类型 (所有元素必须相同类型)
    element_type = _get_tag_type(items[0])
    result = bytearray()
    result.append(element_type)
    result.extend(struct.pack('>i', len(items)))
    for item in items:
        result.extend(_encode_tag_payload(item))
    return bytes(result)


def _encode_compound(data: dict) -> bytes:
    """编码 TAG_COMPOUND。"""
    result = bytearray()
    for key, value in data.items():
        tag_type = _get_tag_type(value)
        result.append(tag_type)
        result.extend(_encode_string(key))
        result.extend(_encode_tag_payload(value))
    # TAG_END 结束符
    result.append(TAG_END)
    return bytes(result)


# --------------------------------------------------
# NBT 类型包装器 (用于显式指定 NBT 类型)
# --------------------------------------------------

class NbtByte:
    """表示一个 NBT Byte 值。"""
    def __init__(self, value: int):
        self.value = value & 0xFF
        if value < 0:
            self.value = value


class NbtShort:
    """表示一个 NBT Short 值。"""
    def __init__(self, value: int):
        self.value = value


class NbtLong:
    """表示一个 NBT Long 值。"""
    def __init__(self, value: int):
        self.value = value


class NbtFloat:
    """表示一个 NBT Float 值。"""
    def __init__(self, value: float):
        self.value = value


class NbtDouble:
    """表示一个 NBT Double 值。"""
    def __init__(self, value: float):
        self.value = value


class NbtIntArray:
    """表示一个 NBT Int Array。"""
    def __init__(self, values: list[int]):
        self.values = values


class NbtLongArray:
    """表示一个 NBT Long Array。"""
    def __init__(self, values: list[int]):
        self.values = values


# ============================================================
# NBT 解码器
# ============================================================

def decode_nbt(data: bytes, offset: int = 0, with_type: bool = True,
               with_name: bool = True) -> tuple[Any, int]:
    """
    从二进制数据解码 NBT 标签。

    参数:
        data: 原始字节数据
        offset: 起始偏移量
        with_type: 是否包含类型前缀字节
        with_name: 是否包含根标签名称 (Anvil 文件有名称，网络协议通常无)

    返回:
        (解码后的 Python 对象, 新的偏移量)
    """
    if with_type:
        tag_type = data[offset]
        offset += 1
        if tag_type == TAG_END:
            return None, offset
        if with_name:
            name_len = struct.unpack_from('>H', data, offset)[0]
            offset += 2 + name_len
    else:
        tag_type = TAG_COMPOUND  # 默认为复合标签

    value, offset = _decode_tag_payload(data, offset, tag_type)
    return value, offset


def _decode_string(data: bytes, offset: int) -> tuple[str, int]:
    """解码 NBT 字符串。"""
    length = struct.unpack_from('>H', data, offset)[0]
    offset += 2
    s = data[offset:offset + length].decode('utf-8', errors='replace')
    return s, offset + length


def _decode_tag_payload(data: bytes, offset: int, tag_type: int) -> tuple[Any, int]:
    """解码指定类型的标签负载。"""
    if tag_type == TAG_BYTE:
        value = struct.unpack_from('>b', data, offset)[0]
        return NbtByte(value), offset + 1

    elif tag_type == TAG_SHORT:
        value = struct.unpack_from('>h', data, offset)[0]
        return NbtShort(value), offset + 2

    elif tag_type == TAG_INT:
        value = struct.unpack_from('>i', data, offset)[0]
        return value, offset + 4

    elif tag_type == TAG_LONG:
        value = struct.unpack_from('>q', data, offset)[0]
        return NbtLong(value), offset + 8

    elif tag_type == TAG_FLOAT:
        value = struct.unpack_from('>f', data, offset)[0]
        return NbtFloat(value), offset + 4

    elif tag_type == TAG_DOUBLE:
        value = struct.unpack_from('>d', data, offset)[0]
        return NbtDouble(value), offset + 8

    elif tag_type == TAG_BYTE_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        offset += 4
        value = data[offset:offset + length]
        return value, offset + length

    elif tag_type == TAG_STRING:
        return _decode_string(data, offset)

    elif tag_type == TAG_LIST:
        elem_type = data[offset]
        offset += 1
        length = struct.unpack_from('>i', data, offset)[0]
        offset += 4
        items = []
        for _ in range(length):
            item, offset = _decode_tag_payload(data, offset, elem_type)
            items.append(item)
        return items, offset

    elif tag_type == TAG_COMPOUND:
        result = {}
        while True:
            child_type = data[offset]
            offset += 1
            if child_type == TAG_END:
                break
            # 读取名称
            name, offset = _decode_string(data, offset)
            value, offset = _decode_tag_payload(data, offset, child_type)
            result[name] = value
        return result, offset

    elif tag_type == TAG_INT_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        offset += 4
        values = list(struct.unpack_from(f'>{length}i', data, offset))
        return NbtIntArray(values), offset + length * 4

    elif tag_type == TAG_LONG_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        offset += 4
        values = list(struct.unpack_from(f'>{length}q', data, offset))
        return NbtLongArray(values), offset + length * 8

    else:
        raise ValueError(f"未知的 NBT 标签类型: {tag_type}")
