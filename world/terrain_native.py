# ============================================================
# PyMC - C++ 原生地形生成器桥接
# 通过子进程与 terrain_gen 可执行文件进行二进制协议通信
# 自动回退到纯 Python 实现
# ============================================================

"""
原生地形生成器桥接模块。

启动 terrain_gen 可执行文件作为长驻子进程，通过 stdin/stdout 传递二进制数据
进行区块生成。

二进制通信协议 (全部小端序):
  请求: 16 字节
    [0:4]   int32  chunk_x
    [4:8]   int32  chunk_z
    [8:16]  int64  seed
  响应: 4 + 197120 字节
    [0:4]        uint32  数据长度 (固定 197120)
    [4:196612]   uint16  方块数据 98304 个 (y*256+z*16+x 顺序)
    [196612:197124] int16 高度图 256 个 (z*16+x 顺序)
"""

import os
import sys
import struct
import array
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("pymc.terrain_native")

# 常量
WORLD_HEIGHT = 384
BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16  # 98304
BLOCKS_BYTES = BLOCKS_COUNT * 2        # 196608
HEIGHTMAP_COUNT = 256
HEIGHTMAP_BYTES = HEIGHTMAP_COUNT * 2  # 512
PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES  # 197120

# 请求格式: int32 + int32 + int64 = 16 字节
REQUEST_FORMAT = '<iiq'
REQUEST_SIZE = struct.calcsize(REQUEST_FORMAT)  # 16


def _find_native_binary() -> str | None:
    """查找跨平台 terrain_gen 可执行文件路径。"""
    binary_names = ["terrain_gen.exe", "terrain_gen"]
    compiled = globals().get("__compiled__")
    search_roots = [
        Path(compiled.containing_dir).resolve()
        if compiled is not None and hasattr(compiled, "containing_dir")
        else None,
        Path(sys.executable).resolve().parent,
        Path(sys.argv[0]).resolve().parent,
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]

    seen: set[Path] = set()
    candidates: list[Path] = []

    for root in search_roots:
        if root is None:
            continue
        for relative in ("native", "."):
            base = root / relative
            for name in binary_names:
                candidate = (base / name).resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)

    for path in candidates:
        if path.exists() and path.is_file():
            if os.name == "nt" or os.access(path, os.X_OK):
                return str(path)
    logger.warning(
        "未在以下路径找到原生地形生成器: %s",
        ", ".join(str(path) for path in candidates),
    )
    return None


def _decode_binary_blocks(data: bytes) -> list[list[list[int]]]:
    """
    将二进制方块数据解码为 3D 数组 [y][z][x]。
    data: 196608 字节的 uint16 小端序数据，顺序为 y*256+z*16+x
    """
    # 使用 array 模块高效解包
    flat = array.array('H')  # unsigned short (uint16)
    flat.frombytes(data)

    # 用切片批量转换为 3D 数组 [y][z][x]，避免逐元素循环
    blocks = []
    offset = 0
    for y in range(WORLD_HEIGHT):
        layer = []
        for z in range(16):
            layer.append(list(flat[offset:offset + 16]))
            offset += 16
        blocks.append(layer)

    return blocks


def _decode_binary_heightmap(data: bytes) -> list[list[int]]:
    """
    将二进制高度图数据解码为 2D 数组 [z][x]。
    data: 512 字节的 int16 小端序数据，顺序为 z*16+x
    """
    flat = array.array('h')  # signed short (int16)
    flat.frombytes(data)

    height_map = []
    for z in range(16):
        height_map.append(list(flat[z * 16:(z + 1) * 16]))

    return height_map


class NativeTerrainGenerator:
    """
    使用 C++ 子进程的高性能地形生成器。

    自动管理子进程生命周期，支持多次调用。
    如果子进程崩溃会自动重启。
    """

    def __init__(self, seed: int):
        self.seed = seed
        self._process: subprocess.Popen | None = None
        self._binary_path = _find_native_binary()

        if self._binary_path:
            logger.info(f"找到原生地形生成器: {self._binary_path}")
            self._start_process()
        else:
            logger.warning("未找到 terrain_gen 原生生成器，将使用纯 Python 回退")

    @property
    def available(self) -> bool:
        """原生生成器是否可用。"""
        return self._process is not None and self._process.poll() is None

    def _start_process(self):
        """启动子进程。"""
        if not self._binary_path:
            return

        try:
            self._process = subprocess.Popen(
                [self._binary_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # 无缓冲
            )
            time.sleep(0.1)
            exit_code = self._process.poll()
            if exit_code is not None:
                stderr_data = b""
                if self._process.stderr is not None:
                    try:
                        stderr_data = self._process.stderr.read() or b""
                    except Exception:
                        stderr_data = b""
                logger.error(
                    "原生地形生成器启动后立即退出 (code=%s): %s",
                    exit_code,
                    stderr_data.decode("utf-8", errors="replace").strip() or "无错误输出",
                )
                self._process = None
                return
            logger.info(f"原生地形生成器子进程已启动 (PID: {self._process.pid})")
        except Exception as e:
            logger.error(f"启动原生地形生成器失败: {e}")
            self._process = None

    def _read_exact(self, n: int) -> bytes:
        """从子进程 stdout 精确读取 n 字节。"""
        data = b''
        while len(data) < n:
            chunk = self._process.stdout.read(n - len(data))
            if not chunk:
                raise RuntimeError("子进程无响应 (可能已退出)")
            data += chunk
        return data

    def _send_request(self, chunk_x: int, chunk_z: int):
        """发送二进制请求到子进程。"""
        request = struct.pack(REQUEST_FORMAT, chunk_x, chunk_z, self.seed)
        self._process.stdin.write(request)
        self._process.stdin.flush()

    def _recv_response(self) -> tuple[bytes, bytes]:
        """
        接收二进制响应。
        返回 (方块数据 bytes, 高度图数据 bytes)。
        """
        # 读取 4 字节长度头
        header = self._read_exact(4)
        payload_size = struct.unpack('<I', header)[0]

        if payload_size != PAYLOAD_SIZE:
            raise RuntimeError(f"响应数据长度异常: 期望 {PAYLOAD_SIZE}, 收到 {payload_size}")

        # 读取完整数据
        payload = self._read_exact(payload_size)

        blocks_data = payload[:BLOCKS_BYTES]
        heightmap_data = payload[BLOCKS_BYTES:]

        return blocks_data, heightmap_data

    def generate_chunk(self, chunk_x: int, chunk_z: int) -> list[list[list[int]]]:
        """
        通过 C++ 子进程生成区块数据。

        参数:
            chunk_x, chunk_z: 区块坐标

        返回:
            3D 方块数组 [y][z][x]，尺寸 384 x 16 x 16
        """
        if not self.available:
            # 尝试重启
            self._start_process()
            if not self.available:
                raise RuntimeError("原生地形生成器不可用")

        try:
            self._send_request(chunk_x, chunk_z)
            blocks_data, _ = self._recv_response()
            return _decode_binary_blocks(blocks_data)

        except Exception as e:
            logger.error(f"原生区块生成失败 ({chunk_x}, {chunk_z}): {e}")
            # 子进程可能已崩溃，尝试重启
            self.shutdown()
            self._start_process()
            raise

    def generate_chunk_with_heightmap(self, chunk_x: int, chunk_z: int):
        """
        生成区块数据和高度图。

        返回:
            (blocks, height_map)
            blocks: 3D 方块数组 [y][z][x]
            height_map: 2D 高度图 [z][x]
        """
        if not self.available:
            self._start_process()
            if not self.available:
                raise RuntimeError("原生地形生成器不可用")

        try:
            self._send_request(chunk_x, chunk_z)
            blocks_data, heightmap_data = self._recv_response()

            blocks = _decode_binary_blocks(blocks_data)
            height_map = _decode_binary_heightmap(heightmap_data)

            return blocks, height_map

        except Exception as e:
            logger.error(f"原生区块生成失败 ({chunk_x}, {chunk_z}): {e}")
            self.shutdown()
            self._start_process()
            raise

    def get_terrain_height(self, world_x: int, world_z: int) -> int:
        """
        获取单个坐标的地形高度。
        通过生成该坐标所在区块来获取。
        """
        chunk_x = world_x >> 4
        chunk_z = world_z >> 4
        local_x = world_x & 15
        local_z = world_z & 15

        _, height_map = self.generate_chunk_with_heightmap(chunk_x, chunk_z)
        return height_map[local_z][local_x]

    def shutdown(self):
        """关闭子进程。"""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            logger.info("原生地形生成器子进程已关闭")

    def __del__(self):
        self.shutdown()
