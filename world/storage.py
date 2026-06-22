# ============================================================
# PyMC - 世界存储系统
# 支持 Linear V2 (.linear) 格式读写
# 支持从 Anvil (.mca) 格式自动转换
# 支持 Linear V2 → Anvil (.mca) 导出
# 支持 LRU 区域文件缓存和安全出生点
# 支持 xxhash 数据校验 (可选)
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
    [17]     uint8   zstd 压缩级别 (0-22, 现在是 uint8)
    [18:20]  uint16  区块数量 (unsigned)
    [20:24]  uint32  压缩数据长度
    [24:32]  uint64  xxhash 校验和 (0 = 无校验)
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
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from io import BytesIO
from .chunk_io import serialize_chunk, deserialize_chunk, deserialize_chunk_with_biomes
from .blocks import AIR, GRASS_BLOCK, WATER, STONE, LAVA, CACTUS, FIRE, SAND, DIRT

logger = logging.getLogger("pymc.storage")

# 尝试导入 zstandard (Linear 格式需要)
try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    logger.warning("zstandard 未安装，Linear 格式将不可用")

# 尝试导入 xxhash (可选校验和)
try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False
    logger.debug("xxhash 未安装，Linear 文件校验和将不可用")


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

# LRU 缓存默认配置
DEFAULT_MAX_REGIONS = 64          # 最多缓存 64 个区域文件
DEFAULT_MAX_MEMORY_MB = 256       # 最大内存 256MB

# 安全出生点配置
SAFE_SPAWN_RADIUS = 16            # 检查半径 (区块)

# 世界维度常量
MIN_Y = -64
WORLD_HEIGHT = 384
SEA_LEVEL = 63

# 危险方块集合 (出生点应避免)
DANGEROUS_BLOCKS = frozenset({
    WATER, LAVA, FIRE, CACTUS,
    # 额外的危险方块 (如果 blocks.py 中定义)
    # MAGMA, CAMPFIRE, SOUL_FIRE, SOUL_CAMPFIRE,
    # SWEET_BERRY_BUSH, WITHER_ROSE, POINTED_DRIPSTONE,
    # POWDER_SNOW,
})


# ============================================================
# Anvil 读取器 (增强错误处理)
# ============================================================

class AnvilReader:
    """Anvil (.mca) 区域文件读取器。增强版支持损坏文件处理。"""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.chunks: list[bytes | None] = [None] * 1024
        self.timestamps: list[int] = [0] * 1024
        self.skipped_chunks: int = 0  # 跳过的损坏区块数
        self._read()

    def _read(self):
        """读取 Anvil 文件，解析所有区块。"""
        try:
            with open(self.filepath, 'rb') as f:
                data = f.read()
        except OSError as e:
            logger.warning(f"Cannot read Anvil file {self.filepath}: {e}")
            return

        if len(data) < SECTOR_SIZE * 2:
            logger.warning(f"Anvil file too small: {self.filepath} ({len(data)} bytes)")
            return

        # 解析位置表 (前 4096 字节)
        for i in range(1024):
            try:
                offset_bytes = data[i * 4:i * 4 + 4]
                if len(offset_bytes) < 4:
                    continue
                # 3 字节偏移 (扇区数) + 1 字节扇区计数
                sector_offset = (offset_bytes[0] << 16 | offset_bytes[1] << 8 |
                                 offset_bytes[2])
                sector_count = offset_bytes[3]

                if sector_offset == 0 and sector_count == 0:
                    continue

                # 解析时间戳
                ts_offset = SECTOR_SIZE + i * 4
                if ts_offset + 4 <= len(data):
                    self.timestamps[i] = struct.unpack_from('>I', data, ts_offset)[0]

                # 读取区块数据
                chunk_start = sector_offset * SECTOR_SIZE
                if chunk_start + 5 > len(data):
                    logger.debug(f"Chunk {i} offset out of range, skipping")
                    self.skipped_chunks += 1
                    continue

                # 区块头: 4 字节长度 + 1 字节压缩类型
                chunk_length = struct.unpack_from('>I', data, chunk_start)[0]
                compression_type = data[chunk_start + 4]

                # 验证区块长度合理性
                if chunk_length < 1 or chunk_length > 10 * 1024 * 1024:
                    logger.debug(f"Chunk {i} length abnormal ({chunk_length}), skipping")
                    self.skipped_chunks += 1
                    continue

                compressed_data = data[chunk_start + 5:chunk_start + 4 + chunk_length]

                # 解压
                try:
                    if compression_type == 1:
                        raw_nbt = gzip.decompress(compressed_data)
                    elif compression_type == 2:
                        raw_nbt = zlib.decompress(compressed_data)
                    elif compression_type == 3:
                        raw_nbt = compressed_data
                    else:
                        logger.debug(f"Unknown compression type {compression_type}, skipping chunk {i}")
                        self.skipped_chunks += 1
                        continue

                    self.chunks[i] = raw_nbt
                except Exception as e:
                    logger.debug(f"Decompression failed for chunk {i}: {e}")
                    self.skipped_chunks += 1

            except Exception as e:
                logger.debug(f"Error parsing chunk {i}: {e}")
                self.skipped_chunks += 1

        if self.skipped_chunks > 0:
            logger.warning(f"Anvil file {os.path.basename(self.filepath)}: "
                          f"skipped {self.skipped_chunks} corrupted chunks")

    @property
    def chunk_count(self) -> int:
        """有效区块数量。"""
        return sum(1 for c in self.chunks if c is not None)


# ============================================================
# Linear V2 读写器 (修复版 + xxhash 校验)
# ============================================================

class LinearRegion:
    """
    Linear V2 (.linear) 区域文件读写器。

    增强功能:
      - chunk_count 使用 uint16 (兼容其他工具)
      - 读写时验证头部和尾部签名
      - 可选 xxhash 校验和用于数据完整性验证
    """

    def __init__(self):
        self.chunks: list[bytes | None] = [None] * 1024
        self.timestamps: list[int] = [0] * 1024
        self.compression_level: int = 1
        self.checksum: int = 0  # xxhash checksum (0 = no checksum)

    @staticmethod
    def read(filepath: str, verify_checksum: bool = True) -> 'LinearRegion':
        """
        读取 Linear V2 文件。

        Args:
            filepath: 文件路径
            verify_checksum: 是否验证 xxhash 校验和

        验证步骤:
          1. 头部签名验证
          2. 尾部签名验证
          3. 可选: xxhash 校验和验证
        """
        if not HAS_ZSTD:
            raise RuntimeError("zstandard not installed, cannot read Linear files")

        region = LinearRegion()

        with open(filepath, 'rb') as f:
            data = f.read()

        if len(data) < LINEAR_HEADER_SIZE + LINEAR_FOOTER_SIZE:
            raise ValueError(f"Linear file too small: {filepath}")

        # 解析头部 (大端序)
        # chunk_count 使用 uint16 (B) 而非 int16 (b) - 兼容性修复
        # compression_level 使用 uint8 (B) 而非 int8 (b)
        (signature, version, newest_ts, comp_level, chunk_count,
         region_length, stored_checksum) = struct.unpack_from('>QBQBHIQ', data, 0)

        # 验证头部签名
        if signature != LINEAR_SIGNATURE:
            raise ValueError(f"Invalid Linear header signature: {hex(signature)}")

        if version not in (1, 2):
            raise ValueError(f"Unsupported Linear version: {version}")

        # 验证尾部签名
        footer_sig = struct.unpack_from('>Q', data, len(data) - 8)[0]
        if footer_sig != LINEAR_SIGNATURE:
            raise ValueError("Invalid Linear footer signature")

        region.compression_level = comp_level
        region.checksum = stored_checksum

        # 解压数据
        compressed = data[LINEAR_HEADER_SIZE:len(data) - LINEAR_FOOTER_SIZE]

        # 可选: 验证 xxhash 校验和
        if verify_checksum and stored_checksum != 0 and HAS_XXHASH:
            computed = xxhash.xxh64(compressed).intdigest()
            if computed != stored_checksum:
                logger.warning(f"Linear file {filepath}: xxhash checksum mismatch "
                              f"(stored={hex(stored_checksum)}, "
                              f"computed={hex(computed)}). Data may be corrupted.")

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

    def write(self, filepath: str, compression_level: int | None = None,
              enable_checksum: bool = True):
        """
        写入 Linear V2 文件。

        Args:
            filepath: 输出文件路径
            compression_level: zstd 压缩级别 (None = 使用默认)
            enable_checksum: 是否写入 xxhash 校验和
        """
        if not HAS_ZSTD:
            raise RuntimeError("zstandard not installed, cannot write Linear files")

        if compression_level is None:
            compression_level = self.compression_level

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

        # 计算 xxhash 校验和 (可选)
        checksum = 0
        if enable_checksum and HAS_XXHASH:
            checksum = xxhash.xxh64(compressed).intdigest()

        # 构建文件头
        # chunk_count 使用 uint16 (H)，compression_level 使用 uint8 (B)
        # 保留字段 [24:32] 现在存储 xxhash 校验和
        header = struct.pack('>QBQBHIQ',
                             LINEAR_SIGNATURE,
                             LINEAR_VERSION,
                             newest_ts,
                             compression_level,
                             chunk_count,
                             len(compressed),
                             checksum)
        footer = struct.pack('>Q', LINEAR_SIGNATURE)

        # 原子写入 (先写临时文件再重命名)
        tmp_path = filepath + '.tmp'
        try:
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
        except Exception:
            # 清理临时文件
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            raise

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

    def estimated_size(self) -> int:
        """估算该区域在内存中的大小。"""
        total = 1024 * 8  # timestamps
        for chunk in self.chunks:
            if chunk is not None:
                total += len(chunk)
        return total


# ============================================================
# Anvil 写入器 (用于 Linear → MCA 导出)
# ============================================================

class AnvilWriter:
    """
    Anvil (.mca) 区域文件写入器。

    支持完整的扇区对齐写入:
      - 4096 字节扇区对齐
      - zlib 压缩
      - 时间戳保留
      - 扇区填充
    """

    def __init__(self):
        self.chunks: list[bytes | None] = [None] * 1024
        self.timestamps: list[int] = [0] * 1024

    def set_chunk(self, index: int, data: bytes, timestamp: int | None = None):
        """设置区块数据 (原始未压缩 NBT)。"""
        self.chunks[index] = data
        self.timestamps[index] = timestamp or int(time.time())

    def write(self, filepath: str, compression_type: int = 2):
        """
        写入 Anvil (.mca) 文件。

        完整的扇区对齐写入:
          1. 位置表 (4096 字节)
          2. 时间戳表 (4096 字节)
          3. 数据扇区 (4096 字节对齐)

        Args:
            filepath: 输出文件路径
            compression_type: 压缩类型 (1=GZip, 2=Zlib)
        """
        if compression_type not in (1, 2):
            compression_type = 2

        # 构建区块数据
        chunk_entries: list[tuple[int, bytes, int]] = []  # (index, sector_data, timestamp)
        for i in range(1024):
            if self.chunks[i] is not None:
                raw_nbt = self.chunks[i]
                if compression_type == 1:
                    compressed = gzip.compress(raw_nbt)
                else:
                    compressed = zlib.compress(raw_nbt, level=6)

                # 构建完整的区块数据: 长度(4) + 压缩类型(1) + 压缩数据
                chunk_length = 1 + len(compressed)
                chunk_data = struct.pack('>I', chunk_length)
                chunk_data += struct.pack('B', compression_type)
                chunk_data += compressed

                # 对齐到 4096 字节扇区
                padding = (SECTOR_SIZE - (len(chunk_data) % SECTOR_SIZE)) % SECTOR_SIZE
                chunk_data += b'\x00' * padding

                chunk_entries.append((i, chunk_data, self.timestamps[i]))

        if not chunk_entries:
            return

        # 构建位置表和时间戳表
        location_table = bytearray(SECTOR_SIZE)
        timestamp_table = bytearray(SECTOR_SIZE)

        # 第一个可用扇区 (位置表和时间戳表之后)
        current_sector = 2
        sector_data = bytearray()

        for index, chunk_data, timestamp in chunk_entries:
            sector_count = len(chunk_data) // SECTOR_SIZE

            # 写入位置表: 3字节扇区偏移 + 1字节扇区数
            location_table[index * 4] = (current_sector >> 16) & 0xFF
            location_table[index * 4 + 1] = (current_sector >> 8) & 0xFF
            location_table[index * 4 + 2] = current_sector & 0xFF
            location_table[index * 4 + 3] = sector_count

            # 写入时间戳表
            ts_bytes = struct.pack('>I', timestamp)
            timestamp_table[index * 4:index * 4 + 4] = ts_bytes

            sector_data.extend(chunk_data)
            current_sector += sector_count

        # 原子写入
        tmp_path = filepath + '.tmp'
        try:
            with open(tmp_path, 'wb') as f:
                f.write(location_table)
                f.write(timestamp_table)
                f.write(sector_data)
                f.flush()
                os.fsync(f.fileno())

            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            raise


# ============================================================
# Anvil -> Linear 转换器 (增强版 + 并发支持)
# ============================================================

def convert_anvil_to_linear(mca_path: str, linear_path: str,
                            compression_level: int = 1,
                            enable_checksum: bool = True) -> int:
    """
    将单个 Anvil (.mca) 文件转换为 Linear V2 (.linear) 文件。

    增强功能:
      - 优雅处理损坏的 Anvil 文件
      - 保留区块时间戳
      - 跳过坏区块并记录警告
      - 可选 xxhash 校验和

    返回: 转换的区块数量
    """
    try:
        anvil = AnvilReader(mca_path)
    except Exception as e:
        logger.error(f"Cannot read Anvil file {mca_path}: {e}")
        return 0

    if anvil.chunk_count == 0:
        return 0

    region = LinearRegion()
    for i in range(1024):
        if anvil.chunks[i] is not None:
            region.chunks[i] = anvil.chunks[i]
            region.timestamps[i] = anvil.timestamps[i]

    try:
        region.write(linear_path, compression_level, enable_checksum=enable_checksum)
    except Exception as e:
        logger.error(f"Failed to write Linear file {linear_path}: {e}")
        return 0

    if anvil.skipped_chunks > 0:
        logger.warning(f"Converting {os.path.basename(mca_path)}: "
                      f"skipped {anvil.skipped_chunks} corrupted chunks")

    return anvil.chunk_count


def convert_world_anvil_to_linear(world_dir: str,
                                  max_workers: int = 1) -> int:
    """
    将世界目录中所有 Anvil 文件转换为 Linear 格式。

    增强功能:
      - 进度报告 (每 100 个区块)
      - 损坏文件跳过 (不中断整个转换)
      - 原始 .mca 文件重命名为 .mca.bak 而非删除
      - 支持并发转换 (当 max_workers > 1 时使用 ThreadPoolExecutor)

    返回: 转换的文件数量
    """
    region_dir = Path(world_dir) / "region"
    if not region_dir.exists():
        return 0

    mca_files = list(region_dir.glob("*.mca"))
    if not mca_files:
        return 0

    logger.info(f"Found {len(mca_files)} Anvil region files, converting to Linear format...")

    converted = 0
    total_chunks = 0
    failed = 0
    chunks_since_report = 0

    def convert_one(mca_file: Path) -> tuple[int, int, bool]:
        """转换单个文件，返回 (chunks, failed_count, success)。"""
        linear_file = mca_file.with_suffix('.linear')
        try:
            chunks = convert_anvil_to_linear(str(mca_file), str(linear_file))
            return chunks, 0, chunks > 0
        except Exception as e:
            logger.error(f"  Conversion failed: {mca_file.name}: {e}")
            return 0, 1, False

    if max_workers > 1 and len(mca_files) > 1:
        # 并发转换
        actual_workers = min(max_workers, len(mca_files))
        logger.info(f"Using {actual_workers} workers for concurrent conversion")

        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_file = {
                executor.submit(convert_one, mca_file): mca_file
                for mca_file in mca_files
            }

            for future in as_completed(future_to_file):
                mca_file = future_to_file[future]
                try:
                    chunks, fail, success = future.result()
                except Exception as e:
                    logger.error(f"  Conversion failed: {mca_file.name}: {e}")
                    failed += 1
                    continue

                if success:
                    total_chunks += chunks
                    converted += 1
                    chunks_since_report += chunks

                    # 进度报告 (每 100 个区块)
                    if chunks_since_report >= 100:
                        logger.info(f"  Progress: {total_chunks} chunks converted "
                                    f"({converted}/{len(mca_files)} files)")
                        chunks_since_report = 0

                    # 重命名原始 .mca 文件为 .mca.bak (而非删除)
                    try:
                        bak_path = str(mca_file) + '.bak'
                        mca_file.rename(bak_path)
                    except Exception as e:
                        logger.warning(f"  Rename backup failed: {mca_file.name}: {e}")
                elif fail > 0:
                    failed += fail

    else:
        # 串行转换
        for idx, mca_file in enumerate(mca_files):
            chunks, fail, success = convert_one(mca_file)

            # 进度报告
            progress = (idx + 1) / len(mca_files) * 100
            if success:
                total_chunks += chunks
                converted += 1
                chunks_since_report += chunks

                # 每 100 个区块报告一次
                if chunks_since_report >= 100:
                    logger.info(f"  Progress: {total_chunks} chunks converted "
                                f"({converted}/{len(mca_files)} files)")
                    chunks_since_report = 0

                # 完整进度信息
                logger.info(f"  [{progress:.0f}%] Converted: {mca_file.name} "
                            f"({chunks} chunks)")

                # 重命名原始 .mca 文件为 .mca.bak (而非删除)
                try:
                    bak_path = str(mca_file) + '.bak'
                    mca_file.rename(bak_path)
                except Exception as e:
                    logger.warning(f"  Rename backup failed: {mca_file.name}: {e}")
            elif fail > 0:
                failed += fail
            else:
                logger.info(f"  [{progress:.0f}%] Skipped empty file: {mca_file.name}")

    logger.info(f"Anvil -> Linear conversion complete: {converted} files, "
                f"total {total_chunks} chunks"
                f"{f', {failed} failed' if failed else ''}")

    return converted


# ============================================================
# Linear -> Anvil 转换器
# ============================================================

def convert_linear_to_anvil(linear_path: str, mca_path: str,
                            compression_type: int = 2) -> int:
    """
    将单个 Linear V2 (.linear) 文件转换为 Anvil (.mca) 文件。

    用于导出为原版兼容格式。

    完整的扇区对齐写入:
      - 4096 字节扇区对齐
      - zlib 压缩 (compression_type=2)
      - 扇区填充
      - 时间戳保留

    Args:
        linear_path: 输入 Linear 文件路径
        mca_path: 输出 Anvil 文件路径
        compression_type: 压缩类型 (1=GZip, 2=Zlib)

    返回: 转换的区块数量
    """
    try:
        region = LinearRegion.read(linear_path, verify_checksum=True)
    except Exception as e:
        logger.error(f"Cannot read Linear file {linear_path}: {e}")
        return 0

    if region.chunk_count == 0:
        return 0

    writer = AnvilWriter()
    for i in range(1024):
        if region.chunks[i] is not None:
            writer.set_chunk(i, region.chunks[i], region.timestamps[i])

    try:
        writer.write(mca_path, compression_type)
    except Exception as e:
        logger.error(f"Failed to write Anvil file {mca_path}: {e}")
        return 0

    return region.chunk_count


def convert_world_linear_to_anvil(world_dir: str,
                                  compression_type: int = 2) -> int:
    """
    将世界目录中所有 Linear 文件转换为 Anvil 格式。

    用于导出为原版兼容格式。

    返回: 转换的文件数量
    """
    region_dir = Path(world_dir) / "region"
    if not region_dir.exists():
        return 0

    linear_files = list(region_dir.glob("*.linear"))
    if not linear_files:
        return 0

    logger.info(f"Found {len(linear_files)} Linear region files, converting to Anvil format...")

    converted = 0
    total_chunks = 0

    for linear_file in linear_files:
        mca_file = linear_file.with_suffix('.mca')
        try:
            chunks = convert_linear_to_anvil(str(linear_file), str(mca_file), compression_type)
            if chunks > 0:
                total_chunks += chunks
                converted += 1
                logger.info(f"  Exported: {linear_file.name} -> {mca_file.name} "
                            f"({chunks} chunks)")
        except Exception as e:
            logger.error(f"  Export failed: {linear_file.name}: {e}")

    logger.info(f"Linear -> Anvil export complete: {converted} files, "
                f"total {total_chunks} chunks")

    return converted


# ============================================================
# LRU 区域文件缓存
# ============================================================

class LRUCache:
    """
    Least-recently-used cache for region files.

    Features:
      - Memory limit (max_memory_mb)
      - Count limit (max_regions)
      - Dirty page tracking and flush
      - Thread-safe with locking
    """

    def __init__(self, max_regions: int = DEFAULT_MAX_REGIONS,
                 max_memory_mb: int = DEFAULT_MAX_MEMORY_MB):
        self._max_regions = max_regions
        self._max_memory = max_memory_mb * 1024 * 1024
        self.current_memory: int = 0
        self.access_order: OrderedDict = OrderedDict()
        self._dirty: set[tuple[int, int]] = set()
        self._lock = threading.Lock()
        self._flush_callback = None  # 由 WorldStorage 设置

    @property
    def dirty(self) -> set[tuple[int, int]]:
        return self._dirty

    def set_flush_callback(self, callback):
        """设置脏页刷写回调函数 callback(rx, rz, region)。"""
        self._flush_callback = callback

    def get(self, key: tuple[int, int]) -> LinearRegion | None:
        """
        Get a region from cache.

        If found, moves it to the end (most recently used).
        Returns None if not in cache.
        """
        with self._lock:
            if key in self.access_order:
                self.access_order.move_to_end(key)
                return self.access_order[key]
        return None

    def put(self, key: tuple[int, int], region: LinearRegion,
            size: int | None = None, is_dirty: bool = False):
        """
        Put a region into cache.

        If the key already exists, moves it to the end.
        If cache exceeds limits, evicts least-recently-used entries.

        Args:
            key: Region coordinates (rx, rz)
            region: The LinearRegion object
            size: Estimated size in bytes (None = auto-calculate)
            is_dirty: Whether this region has unsaved changes
        """
        with self._lock:
            if key in self.access_order:
                # Update existing entry
                old_region = self.access_order[key]
                self.current_memory -= old_region.estimated_size()
                self.access_order.move_to_end(key)
                self.access_order[key] = region
                self.current_memory += region.estimated_size()
                if is_dirty:
                    self._dirty.add(key)
                return

            # Add new entry (add first, then evict so _evict sees accurate count)
            region_size = size if size is not None else region.estimated_size()
            self.access_order[key] = region
            self.current_memory += region_size
            if is_dirty:
                self._dirty.add(key)

            # Evict if needed
            self._evict()

    def mark_dirty(self, key: tuple[int, int]):
        """标记区域为脏页。"""
        with self._lock:
            self._dirty.add(key)

    def is_dirty(self, key: tuple[int, int]) -> bool:
        return key in self._dirty

    def remove(self, key: tuple[int, int]):
        """移除区域 (应先刷写)。"""
        with self._lock:
            region = self.access_order.pop(key, None)
            if region is not None:
                self.current_memory -= region.estimated_size()
            self._dirty.discard(key)

    def clear(self):
        """清空所有缓存。"""
        with self._lock:
            self.access_order.clear()
            self._dirty.clear()
            self.current_memory = 0

    def _evict(self):
        """
        Remove LRU entries until under limit.

        Evicts the least recently used entries (first in OrderedDict)
        until both memory and count limits are satisfied.
        Dirty entries are flushed before eviction.
        """
        while self.access_order:
            # Check count limit
            if len(self.access_order) <= self._max_regions:
                # Check memory limit
                if self.current_memory <= self._max_memory:
                    break

            # 驱逐最久未使用的 (有序字典的第一个)
            oldest_key, oldest_region = next(iter(self.access_order.items()))

            # 如果是脏页，先刷写
            if oldest_key in self._dirty and self._flush_callback:
                try:
                    rx, rz = oldest_key
                    self._flush_callback(rx, rz, oldest_region)
                except Exception as e:
                    logger.error(f"Failed to flush dirty region ({oldest_key}): {e}")
                self._dirty.discard(oldest_key)

            # Remove from cache
            self.current_memory -= oldest_region.estimated_size()
            del self.access_order[oldest_key]

    @property
    def size(self) -> int:
        return len(self.access_order)

    def estimated_memory(self) -> int:
        """估算当前缓存使用的内存。"""
        return self.current_memory


# ============================================================
# 世界存储管理器 (增强版)
# ============================================================

class WorldStorage:
    """
    世界存储管理器。

    管理区域文件的加载和保存，提供按区块坐标的访问接口。
    使用 Linear V2 格式存储，自动转换 Anvil 格式。
    支持 LRU 缓存、xxhash 校验和安全出生点。
    """

    def __init__(self, world_dir: str,
                 max_cached_regions: int = DEFAULT_MAX_REGIONS,
                 max_memory_mb: int = DEFAULT_MAX_MEMORY_MB):
        self.world_dir = Path(world_dir)
        self.region_dir = self.world_dir / "region"
        self.playerdata_dir = self.world_dir / "playerdata"

        # LRU 缓存
        self._cache = LRUCache(max_cached_regions, max_memory_mb)
        self._cache.set_flush_callback(self._flush_region_impl)

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

    def _flush_region_impl(self, rx: int, rz: int, region: LinearRegion):
        """将区域写入磁盘 (由缓存回调调用)。"""
        path = self._get_region_path(rx, rz)
        region.write(str(path))

    def _load_region(self, rx: int, rz: int) -> LinearRegion | None:
        """加载区域文件 (带 LRU 缓存)。"""
        key = (rx, rz)

        # 检查缓存
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        # 从磁盘加载
        path = self._get_region_path(rx, rz)
        if not path.exists():
            return None

        try:
            region = LinearRegion.read(str(path), verify_checksum=True)
            self._cache.put(key, region)
            return region
        except Exception as e:
            logger.error(f"Failed to load region ({rx}, {rz}): {e}")
            return None

    def _get_or_create_region(self, rx: int, rz: int) -> LinearRegion:
        """获取区域，不存在则创建空的。"""
        key = (rx, rz)
        region = self._load_region(rx, rz)
        if region is None:
            region = LinearRegion()
            self._cache.put(key, region)
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

    def load_generated_chunk_with_biomes(self, cx: int, cz: int):
        """
        加载区块方块数组和 biome section ids。

        返回:
            (blocks, biomes) 或 None
        """
        raw = self.load_chunk(cx, cz)
        if raw is None:
            return None
        return deserialize_chunk_with_biomes(raw)

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
        self._cache.mark_dirty((rx, rz))

    def save_generated_chunk(self, cx: int, cz: int, chunk_blocks, chunk_biomes=None):
        """保存区块方块数组到 Linear V2 区域文件（内容为原版 Chunk NBT）。"""
        self.save_chunk(
            cx,
            cz,
            serialize_chunk(chunk_blocks, chunk_x=cx, chunk_z=cz, chunk_biomes=chunk_biomes)
        )

    def flush(self):
        """将所有修改过的区域写入磁盘。"""
        for key in list(self._cache.dirty):
            rx, rz = key
            region = self._cache.get(key)
            if region is None:
                continue

            path = self._get_region_path(rx, rz)
            try:
                region.write(str(path))
                self._cache.dirty.discard(key)
            except Exception as e:
                logger.error(f"Failed to save region ({rx}, {rz}): {e}")

    def flush_region(self, rx: int, rz: int):
        """保存单个区域文件。"""
        key = (rx, rz)
        if not self._cache.is_dirty(key):
            return
        region = self._cache.get(key)
        if region is None:
            return
        path = self._get_region_path(rx, rz)
        try:
            region.write(str(path))
            self._cache.dirty.discard(key)
        except Exception as e:
            logger.error(f"Failed to save region ({rx}, {rz}): {e}")

    def has_dirty_regions(self) -> bool:
        """是否存在尚未落盘的区域修改。"""
        return bool(self._cache.dirty)

    def unload_region(self, rx: int, rz: int):
        """卸载区域文件 (先保存再释放内存)。"""
        key = (rx, rz)
        if self._cache.is_dirty(key):
            self.flush_region(rx, rz)
        self._cache.remove(key)

    def close(self):
        """关闭存储，保存所有未写入的数据。"""
        self.flush()
        self._cache.clear()

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
            logger.error(f"Failed to load player data ({player_uuid}): {e}")
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
            logger.error(f"Failed to save player data ({player_uuid}): {e}")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    # ============================================================
    # 安全出生点系统 (增强版)
    # ============================================================

    def _is_dangerous_block(self, block_id: int) -> bool:
        """
        Check if a block is dangerous for spawning.

        Dangerous blocks include: water, lava, fire, cactus,
        and other blocks that would harm or trap a player.
        """
        return block_id in DANGEROUS_BLOCKS

    def _is_safe_spawn_location(self, chunk_blocks, local_x: int,
                                 surface_y: int, local_z: int) -> bool:
        """
        Check if a specific location is safe for spawning.

        A location is safe if:
        - The block below (feet) is solid and not dangerous
        - The block at feet level is air
        - The block at head level is air
        - No dangerous blocks adjacent or below

        Args:
            chunk_blocks: The chunk block array [y][z][x]
            local_x: Local X coordinate within chunk (0-15)
            surface_y: Surface Y coordinate
            local_z: Local Z coordinate within chunk (0-15)

        Returns:
            True if the location is safe for spawning
        """
        below_yi = (surface_y - 1) - MIN_Y
        at_yi = surface_y - MIN_Y
        above_yi = (surface_y + 1) - MIN_Y

        # Bounds check
        if below_yi < 0 or above_yi >= WORLD_HEIGHT:
            return False

        below_block = chunk_blocks[below_yi][local_z][local_x]
        at_block = chunk_blocks[at_yi][local_z][local_x]
        above_block = chunk_blocks[above_yi][local_z][local_x]

        # Feet must be on solid ground (not air, not dangerous)
        if below_block == AIR or self._is_dangerous_block(below_block):
            return False

        # Body and head must be air
        if at_block != AIR or above_block != AIR:
            return False

        # Check for dangerous blocks around the spawn point
        # Check adjacent blocks at feet level
        for dx, dz in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, nz = local_x + dx, local_z + dz
            if 0 <= nx < 16 and 0 <= nz < 16:
                adj_block = chunk_blocks[at_yi][nz][nx]
                if self._is_dangerous_block(adj_block):
                    return False

        # Check block below for lava/water (in case standing on edge)
        if self._is_dangerous_block(below_block):
            return False

        return True

    def find_safe_spawn_point(self, terrain_generator=None,
                              preferred_x: int = 0,
                              preferred_z: int = 0) -> tuple[int, int, int]:
        """
        查找安全的出生点。

        增强功能:
          - 检查更宽的半径 (16 个区块)
          - 避免水、熔岩、仙人掌、火焰
          - 优先选择 y=63-80 处的草方块
          - 在世界生成后验证出生点

        Args:
            terrain_generator: 地形生成器 (用于生成未加载的区块)
            preferred_x, preferred_z: 首选的世界坐标

        Returns:
            (x, y, z) 安全出生点坐标
        """
        # 转换为区块坐标
        center_cx = preferred_x >> 4
        center_cz = preferred_z >> 4

        best_pos = None
        best_score = -1

        # 螺旋搜索 - 16 个区块半径
        for dist in range(SAFE_SPAWN_RADIUS + 1):
            for dx in range(-dist, dist + 1):
                for dz in range(-dist, dist + 1):
                    if abs(dx) != dist and abs(dz) != dist:
                        continue  # 只搜索外圈

                    cx = center_cx + dx
                    cz = center_cz + dz

                    # 尝试加载或生成区块
                    chunk_blocks = self.load_generated_chunk(cx, cz)
                    if chunk_blocks is None and terrain_generator is not None:
                        try:
                            chunk_blocks = terrain_generator.generate_chunk(cx, cz)
                        except Exception:
                            continue

                    if chunk_blocks is None:
                        continue

                    # 在区块中心寻找出生点
                    wx = cx * 16 + 8
                    wz = cz * 16 + 8
                    local_x = 8
                    local_z = 8

                    # 寻找地表
                    surface_y = MIN_Y
                    for yi in range(WORLD_HEIGHT - 1, -1, -1):
                        block = chunk_blocks[yi][local_z][local_x]
                        if block != AIR and block != WATER:
                            surface_y = MIN_Y + yi
                            break

                    # 评分系统
                    score = 0

                    # 优先 y=63-80 (海平面附近, 草地高度)
                    if 63 <= surface_y <= 80:
                        score += 15
                    elif 60 <= surface_y <= 90:
                        score += 10
                    elif 50 <= surface_y <= 100:
                        score += 5

                    # 优先草方块
                    surface_yi = surface_y - MIN_Y
                    if 0 <= surface_yi < WORLD_HEIGHT:
                        surface_block = chunk_blocks[surface_yi][local_z][local_x]
                        if surface_block == GRASS_BLOCK:
                            score += 20
                        elif surface_block == DIRT:
                            score += 10
                        elif surface_block == SAND:
                            score += 5

                    # 避免危险方块
                    if 0 <= surface_yi < WORLD_HEIGHT:
                        # 检查脚下方块是否危险
                        foot_block = chunk_blocks[surface_yi][local_z][local_x]
                        if self._is_dangerous_block(foot_block):
                            score -= 100  # 强烈避免

                        # 检查附近是否有危险方块
                        for check_yi in range(max(0, surface_yi - 1),
                                              min(WORLD_HEIGHT, surface_yi + 3)):
                            for check_dx in range(-2, 3):
                                for check_dz in range(-2, 3):
                                    nx, nz = local_x + check_dx, local_z + check_dz
                                    if 0 <= nx < 16 and 0 <= nz < 16:
                                        check_block = chunk_blocks[check_yi][nz][nx]
                                        if check_block in DANGEROUS_BLOCKS:
                                            if check_block == LAVA:
                                                score -= 50
                                            elif check_block == WATER:
                                                score -= 20
                                            elif check_block in (FIRE, CACTUS):
                                                score -= 30

                    # 避免水下
                    if surface_y <= SEA_LEVEL:
                        score -= 50

                    # 避免高海拔
                    if surface_y > 120:
                        score -= 20

                    # 距离偏好 (越近越好)
                    score -= dist * 2

                    # 验证出生点安全性
                    if score > 0 and self._is_safe_spawn_location(
                            chunk_blocks, local_x, surface_y + 1, local_z):
                        if score > best_score:
                            best_score = score
                            best_pos = (wx, surface_y + 1, wz)

        if best_pos is None:
            # 回退: 使用首选坐标 (海平面 + 1)
            return (preferred_x, SEA_LEVEL + 1, preferred_z)

        return best_pos

    def validate_spawn_point(self, spawn_x: int, spawn_y: int,
                             spawn_z: int) -> tuple[int, int, int]:
        """
        验证出生点是否安全，不安全则寻找附近的替代点。

        增强功能:
          - 检查脚下和头部方块
          - 避免水、熔岩、仙人掌、火焰
          - 验证失败时搜索更宽区域

        Args:
            spawn_x, spawn_y, spawn_z: 待验证的出生点

        Returns:
            验证后的安全出生点
        """
        cx = spawn_x >> 4
        cz = spawn_z >> 4
        local_x = spawn_x & 15
        local_z = spawn_z & 15

        chunk_blocks = self.load_generated_chunk(cx, cz)
        if chunk_blocks is None:
            return (spawn_x, spawn_y, spawn_z)

        # 检查出生点安全性
        if self._is_safe_spawn_location(chunk_blocks, local_x, spawn_y, local_z):
            return (spawn_x, spawn_y, spawn_z)

        # 寻找安全的替代点
        return self.find_safe_spawn_point(
            preferred_x=spawn_x,
            preferred_z=spawn_z,
        )
