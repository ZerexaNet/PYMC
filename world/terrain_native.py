# ============================================================
# PyMC - C++ 原生地形生成器桥接
# 通过子进程与 terrain_gen 可执行文件进行二进制协议通信
# 原生进程不可用时由 MinecraftServer 上层回退到 Python 实现
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
  响应: 4 + 200192 字节
    [0:4]        uint32  数据长度 (固定 200192)
    [4:196612]   uint16  方块数据 98304 个 (y*256+z*16+x 顺序)
    [196612:197124] int16 高度图 256 个 (z*16+x 顺序)
    [197124:200196] uint16 生物群系 1536 个 (section*64 + y*16 + z*4 + x)
"""

import os
import sys
import struct
import array
import logging
import subprocess
import time
from pathlib import Path

from ._native_binary import is_runnable_native_binary

logger = logging.getLogger("pymc.terrain_native")

# 常量
WORLD_HEIGHT = 384
BLOCKS_COUNT = WORLD_HEIGHT * 16 * 16  # 98304
BLOCKS_BYTES = BLOCKS_COUNT * 2        # 196608
HEIGHTMAP_COUNT = 256
HEIGHTMAP_BYTES = HEIGHTMAP_COUNT * 2  # 512
BIOME_COUNT = 24 * 64
BIOME_BYTES = BIOME_COUNT * 2
LEGACY_PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES  # 197120
PAYLOAD_SIZE = BLOCKS_BYTES + HEIGHTMAP_BYTES + BIOME_BYTES

SINGLE_COMMAND = b'C'
BATCH_COMMAND = b'B'
SINGLE_REQUEST_FORMAT = '<iiq'
BATCH_HEADER_FORMAT = '<qI'
CHUNK_COORD_FORMAT = '<ii'
SINGLE_RESPONSE_HEADER_FORMAT = '<I'
BATCH_RESPONSE_HEADER_FORMAT = '<I'


def _find_native_binary() -> str | None:
    """查找跨平台 terrain_gen 可执行文件路径。"""
    # Pick binary name based on current OS
    if os.name == "nt":
        binary_names = ["terrain_gen.exe", "terrain_gen"]
    else:
        binary_names = ["terrain_gen", "terrain_gen.exe"]
    compiled = globals().get("__compiled__")
    base_roots = [
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent,
        Path.cwd(),
        Path(sys.argv[0]).resolve().parent,
        Path(compiled.containing_dir).resolve()
        if compiled is not None and hasattr(compiled, "containing_dir")
        else None,
        Path(sys.executable).resolve().parent,
    ]

    search_roots: list[Path] = []
    for root in base_roots:
        if root is None:
            continue
        current = root
        for _ in range(4):
            if current not in search_roots:
                search_roots.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent

    seen: set[Path] = set()
    candidates: list[Path] = []

    for root in search_roots:
        # Prefer source-tree artifacts first, then CMake install/build trees.
        for relative in (
            "native",
            "build/stage/native",
            "build/stage",
            "build",
            ".",
        ):
            base = root / relative
            for name in binary_names:
                candidate = (base / name).resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)

        # 兼容 standalone / onefile 等不同打包布局，在根目录附近再做一次浅层扫描。
        for name in binary_names:
            direct = root / name
            if direct not in seen:
                seen.add(direct)
                candidates.append(direct)
        try:
            for pattern in ("terrain_gen*", "native/terrain_gen*"):
                for candidate in root.glob(pattern):
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(resolved)
                for candidate in root.glob(f"*/{pattern}"):
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(resolved)
                for candidate in root.glob(f"*/*/{pattern}"):
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(resolved)
        except Exception:
            pass

    for path in candidates:
        if is_runnable_native_binary(path):
            return str(path)
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


def _decode_binary_biomes(data: bytes) -> list[list[int]] | None:
    """将 C++ 返回的 24 个 section biome palette ids 解码为 [[64], ...]。"""
    if not data:
        return None
    flat = array.array('H')
    flat.frombytes(data)
    if len(flat) < BIOME_COUNT:
        return None
    sections = []
    offset = 0
    for _ in range(24):
        sections.append(list(flat[offset:offset + 64]))
        offset += 64
    return sections


class NativeTerrainGenerator:
    """
    使用 C++ 子进程的高性能地形生成器。

    自动管理子进程生命周期，支持多次调用。
    如果子进程崩溃会自动重启。
    """

    def __init__(self, seed: int, binary_path: str | None = None, worker_count: int | None = None):
        self.seed = seed
        self._process: subprocess.Popen | None = None
        self._binary_path = binary_path or _find_native_binary()
        self.worker_count = max(1, int(worker_count or (os.cpu_count() or 1)))

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
                [self._binary_path, "--threads", str(self.worker_count)],
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

    def _harvest_stderr(self) -> str:
        """读取子进程 stderr 中累积的数据。

        安全策略：仅当子进程已退出 (poll() 返回非 None) 时才读 stderr。
        否则返回空字符串，因为 read() 在活着的管道上会阻塞。
        """
        if not self._process or self._process.stderr is None:
            return ""
        if self._process.poll() is None:
            # 进程还活着，不要读 (会阻塞)
            return ""
        try:
            data = self._process.stderr.read() or b""
            return data.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def _diagnose_crash(self, context: str) -> str:
        """子进程崩溃时，输出诊断信息。"""
        if not self._process:
            return f"{context} (子进程已退出)"
        exit_code = self._process.poll()
        stderr_text = self._harvest_stderr()
        parts = [context]
        if exit_code is not None:
            parts.append(f"退出码={exit_code}")
        if stderr_text:
            parts.append(f"stderr: {stderr_text}")
        hint = ""
        # 常见崩溃模式的人性化提示
        if exit_code is not None and not stderr_text:
            hint = ("无 stderr 输出 — 可能是 DLL 缺失或运行时初始化失败 "
                    "(Windows MinGW 静态链接问题)")
        elif stderr_text and ("dll" in stderr_text.lower() or
                              "0xC0000135" in stderr_text or
                              "0xc0000135" in stderr_text):
            hint = "DLL 缺失或运行时错误"
        if hint:
            parts.append(f"提示: {hint}")
        return " | ".join(parts)

    def _read_exact(self, n: int) -> bytes:
        """从子进程 stdout 精确读取 n 字节。"""
        data = b''
        while len(data) < n:
            chunk = self._process.stdout.read(n - len(data))
            if not chunk:
                raise RuntimeError("子进程无响应 (可能已退出)")
            data += chunk
        return data

    def _send_single_request(self, chunk_x: int, chunk_z: int):
        """发送单区块二进制请求到子进程。"""
        request = bytearray()
        request.extend(SINGLE_COMMAND)
        request.extend(struct.pack(SINGLE_REQUEST_FORMAT, chunk_x, chunk_z, self.seed))
        self._process.stdin.write(request)
        self._process.stdin.flush()

    def _send_batch_request(self, chunk_coords: list[tuple[int, int]]):
        """发送批量区块请求到子进程。"""
        request = bytearray()
        request.extend(BATCH_COMMAND)
        request.extend(struct.pack(BATCH_HEADER_FORMAT, self.seed, len(chunk_coords)))
        for chunk_x, chunk_z in chunk_coords:
            request.extend(struct.pack(CHUNK_COORD_FORMAT, chunk_x, chunk_z))
        self._process.stdin.write(request)
        self._process.stdin.flush()

    def _recv_single_response(self) -> tuple[bytes, bytes, bytes | None]:
        """
        接收单区块二进制响应。
        返回 (方块数据 bytes, 高度图数据 bytes)。
        """
        header = self._read_exact(4)
        payload_size = struct.unpack(SINGLE_RESPONSE_HEADER_FORMAT, header)[0]

        if payload_size not in (PAYLOAD_SIZE, LEGACY_PAYLOAD_SIZE):
            raise RuntimeError(
                f"响应数据长度异常: 期望 {PAYLOAD_SIZE} 或 {LEGACY_PAYLOAD_SIZE}, 收到 {payload_size}"
            )

        # 读取完整数据
        payload = self._read_exact(payload_size)

        blocks_data = payload[:BLOCKS_BYTES]
        heightmap_data = payload[BLOCKS_BYTES:BLOCKS_BYTES + HEIGHTMAP_BYTES]
        biome_data = payload[BLOCKS_BYTES + HEIGHTMAP_BYTES:] or None

        return blocks_data, heightmap_data, biome_data

    def _recv_batch_response(self, expected_count: int) -> list[tuple[bytes, bytes, bytes | None]]:
        """接收批量区块响应。"""
        header = self._read_exact(4)
        chunk_count = struct.unpack(BATCH_RESPONSE_HEADER_FORMAT, header)[0]
        if chunk_count != expected_count:
            raise RuntimeError(f"批量响应数量异常: 期望 {expected_count}, 收到 {chunk_count}")

        payload_size_per_chunk = PAYLOAD_SIZE
        payload = self._read_exact(chunk_count * payload_size_per_chunk)
        chunks: list[tuple[bytes, bytes, bytes | None]] = []
        offset = 0
        for _ in range(chunk_count):
            chunk_payload = payload[offset:offset + payload_size_per_chunk]
            offset += payload_size_per_chunk
            chunks.append((
                chunk_payload[:BLOCKS_BYTES],
                chunk_payload[BLOCKS_BYTES:BLOCKS_BYTES + HEIGHTMAP_BYTES],
                chunk_payload[BLOCKS_BYTES + HEIGHTMAP_BYTES:] or None,
            ))
        return chunks

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
            self._send_single_request(chunk_x, chunk_z)
            blocks_data, _, _ = self._recv_single_response()
            return _decode_binary_blocks(blocks_data)

        except Exception as e:
            diag = self._diagnose_crash(f"原生区块生成失败 ({chunk_x}, {chunk_z}): {e}")
            logger.error(diag)
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
            self._send_single_request(chunk_x, chunk_z)
            blocks_data, heightmap_data, _ = self._recv_single_response()

            blocks = _decode_binary_blocks(blocks_data)
            height_map = _decode_binary_heightmap(heightmap_data)

            return blocks, height_map

        except Exception as e:
            diag = self._diagnose_crash(f"原生区块生成失败 ({chunk_x}, {chunk_z}): {e}")
            logger.error(diag)
            self.shutdown()
            self._start_process()
            raise

    def generate_chunk_with_metadata(self, chunk_x: int, chunk_z: int):
        """生成区块、地形高度图和原生 biome section ids。"""
        if not self.available:
            self._start_process()
            if not self.available:
                raise RuntimeError("原生地形生成器不可用")

        try:
            self._send_single_request(chunk_x, chunk_z)
            blocks_data, heightmap_data, biome_data = self._recv_single_response()
            return (
                _decode_binary_blocks(blocks_data),
                _decode_binary_heightmap(heightmap_data),
                _decode_binary_biomes(biome_data),
            )
        except Exception as e:
            diag = self._diagnose_crash(f"原生区块生成失败 ({chunk_x}, {chunk_z}): {e}")
            logger.error(diag)
            self.shutdown()
            self._start_process()
            raise

    def generate_chunks_with_heightmaps(self, chunk_coords: list[tuple[int, int]]):
        """
        批量生成多个区块数据和高度图。

        返回:
            [(blocks, height_map), ...]，顺序与 chunk_coords 一致
        """
        if not chunk_coords:
            return []

        if not self.available:
            self._start_process()
            if not self.available:
                raise RuntimeError("原生地形生成器不可用")

        try:
            self._send_batch_request(chunk_coords)
            raw_chunks = self._recv_batch_response(len(chunk_coords))
            return [
                (_decode_binary_blocks(blocks_data), _decode_binary_heightmap(heightmap_data))
                for blocks_data, heightmap_data, _ in raw_chunks
            ]
        except Exception as e:
            diag = self._diagnose_crash(f"原生批量区块生成失败 ({len(chunk_coords)} 个): {e}")
            logger.error(diag)
            self.shutdown()
            self._start_process()
            raise

    def generate_chunks_with_metadata(self, chunk_coords: list[tuple[int, int]]):
        """批量生成区块、地形高度图和 biome section ids。"""
        if not chunk_coords:
            return []

        if not self.available:
            self._start_process()
            if not self.available:
                raise RuntimeError("原生地形生成器不可用")

        try:
            self._send_batch_request(chunk_coords)
            raw_chunks = self._recv_batch_response(len(chunk_coords))
            return [
                (
                    _decode_binary_blocks(blocks_data),
                    _decode_binary_heightmap(heightmap_data),
                    _decode_binary_biomes(biome_data),
                )
                for blocks_data, heightmap_data, biome_data in raw_chunks
            ]
        except Exception as e:
            diag = self._diagnose_crash(f"原生批量区块生成失败 ({len(chunk_coords)} 个): {e}")
            logger.error(diag)
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
        if getattr(self, "_process", None):
            process = self._process
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            finally:
                for pipe in (process.stdout, process.stderr):
                    try:
                        if pipe:
                            pipe.close()
                    except Exception:
                        pass
            self._process = None
            logger.info("原生地形生成器子进程已关闭")

    def __del__(self):
        self.shutdown()
