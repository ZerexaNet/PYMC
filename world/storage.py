# ============================================================
# PyMC - 世界存储系统
# 支持 Linear V2 (.linear) 格式读写
# 支持从 Anvil (.mca) 格式自动转换
# ============================================================

"""
世界存储模块。

使用 Linear V2 区域文件格式存储区块数据。
遇到 Anvil (.mca) 文件时自动转换为 Linear 格式。

区域文件: 每个文件存储 32x32 = 1024 个区块。
文件名: r.{rx}.{rz}.linear (或 .mca)
区块在区域内的索引: (cx & 31) + (cz & 31) * 32

Linear V2 格式 (大端序):
  头部 32 字节:
    [0:8]    uint64  签名 (0xc3ff13183cca9d9a)
    [8]      uint8   版本 (1 或 2)
    [9:17]   uint64  最新区块时间戳
    [17]     int8    zstd 压缩级别
    [18:20]  uint16  区块数量 (原格式是 int16，但实际是无符号)
    [20:24]  uint32  压缩数据长度
    [24:32]  uint64  保留 (hash, 始终为 0)
  压缩数据 (zstd):
    区块表 8192 字节 (1024 * 8):
      每条 8 字节: uint32 大小 + uint32 时间戳
    区块数据: 紧密排列
  尾部 8 字节:
    uint64  签名 (0xc3ff13183cca9d9a)

Anvil 格式 (.mca, 大端序):
  位置表 4096 字节 (1024 * 4):
    每条 4 字节: 3字节扇区偏移 + 1字节扇区数
  时间戳表 4096 字节 (1024 * 4):
    每条 4 字节: uint32 时间戳
  数据扇区 (4096 字节对齐):
    每个区块: 4字节长度 + 1字节压缩类型 + 压缩数据
    压缩类型: 1=GZip, 2=Zlib, 3=无压缩
"""

import os
import struct
import zlib
import gzip
import time
import logging
import json
from pathlib import Path
from io import BytesIO
from .chunk_io import serialize_chunk, deserialize_chunk

logger = logging.getLogger("pymc.storage")

# 尝试导入 zstandard (Linear 格式需要)
try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    logger.warning("zstandard 未安装，Linear 格式将不可用")


# ============================================================
# 常量
# ============================================================
LINEAR_SIGNATURE = 0xc3ff13183cca9d9a
LINEAR_VERSION = 2
LINEAR_HEADER_SIZE = 32
LINEAR_FOOTER_SIZE = 8
LINEAR_CHUNK_TABLE_SIZE = 1024 * 8  # 8192 字节
REGION_DIM = 32
SECTOR_SIZE = 4096


# ============================================================
# Anvil 读取器
# ============================================================

class AnvilReader:
    """Anvil (.mca) 区域文件读取器。"""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.chunks: list[bytes | None] = [None] * 1024
        self.timestamps: list[int] = [0] * 1024
        self._read()

    def _read(self):
        """读取 Anvil 文件，解析所有区块。"""
        with open(self.filepath, 'rb') as f:
            data = f.read()

        if len(data) < SECTOR_SIZE * 2:
            logger.warning(f"Anvil 文件过小: {self.filepath}")
            return

        # 解析位置表 (前 4096 字节)
        for i in range(1024):
            offset_bytes = data[i * 4:i * 4 + 4]
            # 3 字节偏移 (扇区数) + 1 字节扇区计数
            sector_offset = (offset_bytes[0] << 16 | offset_bytes[1] << 8 |
                             offset_bytes[2])
            sector_count = offset_bytes[3]

            if sector_offset == 0 and sector_count == 0:
                continue

            # 解析时间戳
            ts_offset = SECTOR_SIZE + i * 4
            self.timestamps[i] = struct.unpack_from('>I', data, ts_offset)[0]

            # 读取区块数据
            chunk_start = sector_offset * SECTOR_SIZE
            if chunk_start + 5 > len(data):
                continue

            # 区块头: 4 字节长度 + 1 字节压缩类型
            chunk_length = struct.unpack_from('>I', data, chunk_start)[0]
            compression_type = data[chunk_start + 4]

            compressed_data = data[chunk_start + 5:chunk_start + 4 + chunk_length]

            # 解压
            try:
                if compression_type == 1:
                    # GZip
                    raw_nbt = gzip.decompress(compressed_data)
                elif compression_type == 2:
                    # Zlib
                    raw_nbt = zlib.decompress(compressed_data)
                elif compression_type == 3:
                    # 无压缩
                    raw_nbt = compressed_data
                else:
                    logger.warning(f"未知压缩类型 {compression_type}，跳过区块 {i}")
                    continue

                self.chunks[i] = raw_nbt
            except Exception as e:
                logger.warning(f"解压区块 {i} 失败: {e}")

    @property
    def chunk_count(self) -> int:
        """有效区块数量。"""
        return sum(1 for c in self.chunks if c is not None)


# ============================================================
# Linear V2 读写器
# ============================================================

class LinearRegion:
    """Linear V2 (.linear) 区域文件读写器。"""

    def __init__(self):
        self.chunks: list[bytes | None] = [None] * 1024
        self.timestamps: list[int] = [0] * 1024

    @staticmethod
    def read(filepath: str) -> 'LinearRegion':
        """读取 Linear V2 文件。"""
        if not HAS_ZSTD:
            raise RuntimeError("zstandard 未安装，无法读取 Linear 文件")

        region = LinearRegion()

        with open(filepath, 'rb') as f:
            data = f.read()

        if len(data) < LINEAR_HEADER_SIZE + LINEAR_FOOTER_SIZE:
            raise ValueError(f"Linear 文件过小: {filepath}")

        # 解析头部 (大端序)
        (signature, version, newest_ts, comp_level, chunk_count,
         region_length, reserved) = struct.unpack_from('>QBQbhIQ', data, 0)

        if signature != LINEAR_SIGNATURE:
            raise ValueError(f"无效的 Linear 签名: {hex(signature)}")

        if version not in (1, 2):
            raise ValueError(f"不支持的 Linear 版本: {version}")

        # 检查尾部签名
        footer_sig = struct.unpack_from('>Q', data, len(data) - 8)[0]
        if footer_sig != LINEAR_SIGNATURE:
            raise ValueError("Linear 尾部签名无效")

        # 解压数据
        compressed = data[LINEAR_HEADER_SIZE:len(data) - LINEAR_FOOTER_SIZE]
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(compressed, max_output_size=256 * 1024 * 1024)

        # 解析区块表
        offset = 0
        sizes = []
        for i in range(1024):
            size, timestamp = struct.unpack_from('>II', decompressed, offset)
            sizes.append(size)
            region.timestamps[i] = timestamp
            offset += 8

        # 读取区块数据
        data_offset = LINEAR_CHUNK_TABLE_SIZE
        for i in range(1024):
            if sizes[i] > 0:
                region.chunks[i] = decompressed[data_offset:data_offset + sizes[i]]
                data_offset += sizes[i]

        return region

    def write(self, filepath: str, compression_level: int = 1):
        """写入 Linear V2 文件。"""
        if not HAS_ZSTD:
            raise RuntimeError("zstandard 未安装，无法写入 Linear 文件")

        # 构建区块表和数据
        table_parts = []
        data_parts = []
        chunk_count = 0
        newest_ts = 0

        for i in range(1024):
            if self.chunks[i] is not None:
                size = len(self.chunks[i])
                table_parts.append(struct.pack('>II', size, self.timestamps[i]))
                data_parts.append(self.chunks[i])
                chunk_count += 1
                newest_ts = max(newest_ts, self.timestamps[i])
            else:
                table_parts.append(b'\x00' * 8)

        # 组合并压缩
        raw_data = b''.join(table_parts) + b''.join(data_parts)
        cctx = zstd.ZstdCompressor(level=compression_level)
        compressed = cctx.compress(raw_data)

        # 构建文件
        header = struct.pack('>QBQbhIQ',
                             LINEAR_SIGNATURE,
                             LINEAR_VERSION,
                             newest_ts,
                             compression_level,
                             chunk_count,
                             len(compressed),
                             0)  # 保留字段
        footer = struct.pack('>Q', LINEAR_SIGNATURE)

        # 原子写入 (先写临时文件再重命名)
        tmp_path = filepath + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(header)
            f.write(compressed)
            f.write(footer)
            f.flush()
            os.fsync(f.fileno())

        # Windows 上 rename 需要先删除目标
        if os.path.exists(filepath):
            os.replace(tmp_path, filepath)
        else:
            os.rename(tmp_path, filepath)

    @property
    def chunk_count(self) -> int:
        """有效区块数量。"""
        return sum(1 for c in self.chunks if c is not None)

    def get_chunk(self, index: int) -> bytes | None:
        """获取指定索引的区块原始 NBT 数据。"""
        return self.chunks[index]

    def set_chunk(self, index: int, data: bytes, timestamp: int | None = None):
        """设置指定索引的区块数据。"""
        self.chunks[index] = data
        self.timestamps[index] = timestamp or int(time.time())


# ============================================================
# Anvil -> Linear 转换器
# ============================================================

def convert_anvil_to_linear(mca_path: str, linear_path: str,
                            compression_level: int = 1) -> int:
    """
    将单个 Anvil (.mca) 文件转换为 Linear V2 (.linear) 文件。

    返回: 转换的区块数量
    """
    anvil = AnvilReader(mca_path)

    if anvil.chunk_count == 0:
        return 0

    region = LinearRegion()
    for i in range(1024):
        if anvil.chunks[i] is not None:
            region.chunks[i] = anvil.chunks[i]
            region.timestamps[i] = anvil.timestamps[i]

    region.write(linear_path, compression_level)
    return anvil.chunk_count


def convert_world_anvil_to_linear(world_dir: str) -> int:
    """
    将世界目录中所有 Anvil 文件转换为 Linear 格式。

    扫描 world_dir/region/ 目录下的 .mca 文件，
    转换为 .linear 文件后删除原始 .mca 文件。

    返回: 转换的文件数量
    """
    region_dir = Path(world_dir) / "region"
    if not region_dir.exists():
        return 0

    mca_files = list(region_dir.glob("*.mca"))
    if not mca_files:
        return 0

    logger.info(f"检测到 {len(mca_files)} 个 Anvil 区域文件，开始转换为 Linear 格式...")

    converted = 0
    total_chunks = 0

    for mca_file in mca_files:
        # r.0.0.mca -> r.0.0.linear
        linear_file = mca_file.with_suffix('.linear')

        try:
            chunks = convert_anvil_to_linear(str(mca_file), str(linear_file))
            if chunks > 0:
                total_chunks += chunks
                converted += 1
                logger.info(f"  已转换: {mca_file.name} -> {linear_file.name} "
                            f"({chunks} 个区块)")

                # 删除原始 .mca 文件
                mca_file.unlink()
            else:
                logger.info(f"  跳过空文件: {mca_file.name}")
        except Exception as e:
            logger.error(f"  转换失败: {mca_file.name}: {e}")

    logger.info(f"Anvil -> Linear 转换完成: {converted} 个文件, "
                f"共 {total_chunks} 个区块")

    return converted


# ============================================================
# 世界存储管理器
# ============================================================

class WorldStorage:
    """
    世界存储管理器。

    管理区域文件的加载和保存，提供按区块坐标的访问接口。
    使用 Linear V2 格式存储，自动转换 Anvil 格式。
    """

    def __init__(self, world_dir: str):
        self.world_dir = Path(world_dir)
        self.region_dir = self.world_dir / "region"
        self.playerdata_dir = self.world_dir / "playerdata"
        # 缓存已加载的区域文件 (rx, rz) -> LinearRegion
        self._regions: dict[tuple[int, int], LinearRegion] = {}
        # 标记已修改的区域 (需要保存)
        self._dirty: set[tuple[int, int]] = set()

        # 确保目录存在
        self.region_dir.mkdir(parents=True, exist_ok=True)
        self.playerdata_dir.mkdir(parents=True, exist_ok=True)

    def initialize(self):
        """初始化存储，执行必要的格式转换。"""
        convert_world_anvil_to_linear(str(self.world_dir))

    @staticmethod
    def _chunk_to_region(cx: int, cz: int) -> tuple[int, int, int]:
        """
        计算区块坐标对应的区域坐标和区域内索引。

        返回: (区域x, 区域z, 区域内索引)
        """
        rx = cx >> 5  # cx // 32 (算术右移处理负数)
        rz = cz >> 5
        index = (cx & 31) + (cz & 31) * 32
        return rx, rz, index

    def _get_region_path(self, rx: int, rz: int) -> Path:
        """获取区域文件路径。"""
        return self.region_dir / f"r.{rx}.{rz}.linear"

    def _load_region(self, rx: int, rz: int) -> LinearRegion | None:
        """加载区域文件 (带缓存)。"""
        key = (rx, rz)
        if key in self._regions:
            return self._regions[key]

        path = self._get_region_path(rx, rz)
        if not path.exists():
            return None

        try:
            region = LinearRegion.read(str(path))
            self._regions[key] = region
            return region
        except Exception as e:
            logger.error(f"加载区域文件失败 ({rx}, {rz}): {e}")
            return None

    def _get_or_create_region(self, rx: int, rz: int) -> LinearRegion:
        """获取区域，不存在则创建空的。"""
        key = (rx, rz)
        region = self._load_region(rx, rz)
        if region is None:
            region = LinearRegion()
            self._regions[key] = region
        return region

    def load_chunk(self, cx: int, cz: int) -> bytes | None:
        """
        加载区块的原始 NBT 数据。

        参数:
            cx, cz: 区块坐标

        返回:
            区块 NBT 数据，或 None (区块不存在)
        """
        rx, rz, index = self._chunk_to_region(cx, cz)
        region = self._load_region(rx, rz)
        if region is None:
            return None
        return region.get_chunk(index)

    def load_generated_chunk(self, cx: int, cz: int):
        """
        加载区块方块数组。

        返回:
            [y][z][x] 方块数组，或 None（不存在 / 无法解析）
        """
        raw = self.load_chunk(cx, cz)
        if raw is None:
            return None
        return deserialize_chunk(raw)

    def save_chunk(self, cx: int, cz: int, nbt_data: bytes):
        """
        保存区块数据。

        参数:
            cx, cz: 区块坐标
            nbt_data: 区块 NBT 数据 (原始未压缩)
        """
        rx, rz, index = self._chunk_to_region(cx, cz)
        region = self._get_or_create_region(rx, rz)
        region.set_chunk(index, nbt_data)
        self._dirty.add((rx, rz))

    def save_generated_chunk(self, cx: int, cz: int, chunk_blocks, chunk_biomes=None):
        """保存区块方块数组到 Linear V2 区域文件（内容为原版 Chunk NBT）。"""
        self.save_chunk(
            cx,
            cz,
            serialize_chunk(chunk_blocks, chunk_x=cx, chunk_z=cz, chunk_biomes=chunk_biomes)
        )

    def flush(self):
        """将所有修改过的区域写入磁盘。"""
        for key in list(self._dirty):
            rx, rz = key
            region = self._regions.get(key)
            if region is None:
                continue

            path = self._get_region_path(rx, rz)
            try:
                region.write(str(path))
                self._dirty.discard(key)
            except Exception as e:
                logger.error(f"保存区域文件失败 ({rx}, {rz}): {e}")

    def flush_region(self, rx: int, rz: int):
        """保存单个区域文件。"""
        key = (rx, rz)
        if key not in self._dirty:
            return
        region = self._regions.get(key)
        if region is None:
            return
        path = self._get_region_path(rx, rz)
        try:
            region.write(str(path))
            self._dirty.discard(key)
        except Exception as e:
            logger.error(f"保存区域文件失败 ({rx}, {rz}): {e}")

    def has_dirty_regions(self) -> bool:
        """是否存在尚未落盘的区域修改。"""
        return bool(self._dirty)

    def unload_region(self, rx: int, rz: int):
        """卸载区域文件 (先保存再释放内存)。"""
        key = (rx, rz)
        if key in self._dirty:
            self.flush_region(rx, rz)
        self._regions.pop(key, None)

    def close(self):
        """关闭存储，保存所有未写入的数据。"""
        self.flush()
        self._regions.clear()
        self._dirty.clear()

    def _get_playerdata_path(self, player_uuid: str) -> Path:
        """获取玩家存档路径。"""
        return self.playerdata_dir / f"{player_uuid}.json"

    def load_player_data(self, player_uuid: str) -> dict | None:
        """加载玩家存档。"""
        path = self._get_playerdata_path(player_uuid)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.error(f"加载玩家存档失败 ({player_uuid}): {e}")
        return None

    def save_player_data(self, player_uuid: str, data: dict):
        """保存玩家存档。"""
        path = self._get_playerdata_path(player_uuid)
        tmp_path = path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"保存玩家存档失败 ({player_uuid}): {e}")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
