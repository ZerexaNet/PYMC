# ============================================================
# PyMC - C++ Acceleration Layer Python Interface
#
# Provides unified access to the C++ acceleration layer:
#   - Shared memory IPC mode (fastest, separate process)
#   - Direct in-process mode (via ctypes shared library)
#   - Fallback to subprocess mode (existing terrain_gen/mob_ai)
#
# Architecture:
#   NativeCore
#     ├── NativeRedstoneEngine  - Redstone simulation
#     ├── NativeLightEngine     - Light propagation
#     └── NativePhysicsEngine   - AABB collision + physics
# ============================================================

import ctypes
import logging
import os
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pymc.native")

# ===========================================================
# Constants
# ===========================================================

# Command types (must match pymc_native_server.cpp)
CMD_TICK = 0x01
CMD_ADD_REDSTONE = 0x02
CMD_REMOVE_REDSTONE = 0x03
CMD_SET_POWER = 0x04
CMD_CALC_LIGHT = 0x05
CMD_UPDATE_LIGHT = 0x06
CMD_SET_ENTITY = 0x07
CMD_REMOVE_ENTITY = 0x08
CMD_SET_BLOCKS = 0x09
CMD_TICK_FLUIDS = 0x0A
CMD_PING = 0x0B
CMD_SHUTDOWN = 0xFF

# Response status
STATUS_OK = 0
STATUS_ERROR = 1
STATUS_UNKNOWN_CMD = 2

# Engine constants
SECTION_SIZE = 16
CHUNK_SECTIONS = 24
LIGHT_SECTIONS = 26
MIN_Y = -64

# Component types
COMPONENT_WIRE = 0
COMPONENT_TORCH = 1
COMPONENT_REPEATER = 2
COMPONENT_COMPARATOR = 3
COMPONENT_PISTON = 4
COMPONENT_STICKY_PISTON = 5
COMPONENT_OBSERVER = 6
COMPONENT_LEVER = 7
COMPONENT_BUTTON = 8
COMPONENT_PRESSURE_PLATE = 9
COMPONENT_WEIGHTED_PRESSURE_PLATE = 10

# Facing directions
FACING_DOWN = 0
FACING_UP = 1
FACING_NORTH = 2
FACING_SOUTH = 3
FACING_WEST = 4
FACING_EAST = 5


# ===========================================================
# Binary protocol helpers
# ===========================================================

def _pack_u8(val: int) -> bytes:
    return struct.pack('<B', val & 0xFF)

def _pack_u16(val: int) -> bytes:
    return struct.pack('<H', val & 0xFFFF)

def _pack_i32(val: int) -> bytes:
    return struct.pack('<i', val)

def _pack_u32(val: int) -> bytes:
    return struct.pack('<I', val)

def _pack_f64(val: float) -> bytes:
    return struct.pack('<d', val)

def _unpack_u8(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<B', data, offset)[0]

def _unpack_u16(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<H', data, offset)[0]

def _unpack_i32(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<i', data, offset)[0]

def _unpack_u32(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<I', data, offset)[0]

def _unpack_f64(data: bytes, offset: int = 0) -> float:
    return struct.unpack_from('<d', data, offset)[0]


# ===========================================================
# Native library finder
# ===========================================================

def _find_native_lib() -> Optional[str]:
    """Find the pymc_native shared library."""
    lib_names = ["libpymc_native.so", "pymc_native.dll", "pymc_native.dylib"]
    compiled = globals().get("__compiled__")

    search_roots = [
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
        Path(sys.argv[0]).resolve().parent,
        Path(sys.executable).resolve().parent,
    ]

    if compiled is not None and hasattr(compiled, "containing_dir"):
        search_roots.append(Path(compiled.containing_dir).resolve())

    seen: set = set()
    for root in search_roots:
        if root is None:
            continue
        for name in lib_names:
            for subdir in [".", "native", "build", "lib"]:
                candidate = (root / subdir / name).resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    if candidate.exists() and candidate.is_file():
                        return str(candidate)
    return None


def _find_native_server() -> Optional[str]:
    """Find the pymc_native_server executable."""
    exe_names = ["pymc_native_server", "pymc_native_server.exe"]
    search_roots = [
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]

    for root in search_roots:
        for name in exe_names:
            candidate = (root / name).resolve()
            if candidate.exists() and candidate.is_file():
                return str(candidate)
            candidate = (root / "native" / name).resolve()
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    return None


# ===========================================================
# IPC-based Native Core (separate process, shared memory)
# ===========================================================

class NativeIPCConnection:
    """
    Communicates with the native C++ server process via shared memory.

    This is the FASTEST mode - zero-copy ring buffer IPC with
    no serialization overhead. The C++ process runs continuously
    and Python sends commands/responses through shared memory.
    """

    def __init__(self, shm_name: str = "/pymc_native",
                 cmd_size: int = 16 * 1024 * 1024,
                 resp_size: int = 16 * 1024 * 1024):
        self._shm_name = shm_name
        self._cmd_size = cmd_size
        self._resp_size = resp_size
        self._lib: Optional[ctypes.CDLL] = None
        self._channel: Optional[int] = None
        self._process: Optional[subprocess.Popen] = None
        self._initialized = False

    def _ensure_lib(self) -> bool:
        """Load the pymc_native shared library for IPC functions."""
        if self._lib is not None:
            return True

        lib_path = _find_native_lib()
        if lib_path is None:
            logger.warning("pymc_native shared library not found")
            return False

        try:
            self._lib = ctypes.CDLL(lib_path)
            # Set up function signatures
            self._lib.pymc_ipc_channel_create.restype = ctypes.c_void_p
            self._lib.pymc_ipc_channel_create.argtypes = [
                ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int
            ]
            self._lib.pymc_ipc_channel_destroy.restype = None
            self._lib.pymc_ipc_channel_destroy.argtypes = [ctypes.c_void_p]
            self._lib.pymc_ipc_send_command.restype = ctypes.c_int
            self._lib.pymc_ipc_send_command.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
            ]
            self._lib.pymc_ipc_recv_response.restype = ctypes.c_uint32
            self._lib.pymc_ipc_recv_response.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
            ]
            self._lib.pymc_ipc_wait_for_response.restype = ctypes.c_int
            self._lib.pymc_ipc_wait_for_response.argtypes = [
                ctypes.c_void_p, ctypes.c_int
            ]
            self._lib.pymc_ipc_is_valid.restype = ctypes.c_int
            self._lib.pymc_ipc_is_valid.argtypes = [ctypes.c_void_p]
            return True
        except Exception as e:
            logger.warning(f"Failed to load pymc_native library: {e}")
            self._lib = None
            return False

    def start(self) -> bool:
        """Start the native server process and establish IPC."""
        server_path = _find_native_server()
        if server_path is None:
            logger.warning("pymc_native_server not found")
            return False

        if not self._ensure_lib():
            return False

        try:
            # Create the IPC channel (Python is the creator)
            self._channel = self._lib.pymc_ipc_channel_create(
                self._shm_name.encode('utf-8'),
                self._cmd_size,
                self._resp_size,
                1  # create=True
            )
            if not self._channel:
                logger.error("Failed to create IPC channel")
                return False

            # Start the native server process
            self._process = subprocess.Popen(
                [server_path,
                 "--name", self._shm_name,
                 "--cmd-size", str(self._cmd_size),
                 "--resp-size", str(self._resp_size)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            time.sleep(0.1)
            if self._process.poll() is not None:
                stderr = b""
                if self._process.stderr:
                    try:
                        stderr = self._process.stderr.read() or b""
                    except Exception:
                        pass
                logger.error(
                    f"Native server exited immediately (code={self._process.returncode}): "
                    f"{stderr.decode('utf-8', errors='replace').strip()}"
                )
                self._channel = None
                return False

            # Verify with ping
            if self.ping():
                self._initialized = True
                logger.info(f"Native IPC connection established (PID: {self._process.pid})")
                return True
            else:
                logger.warning("Native server ping failed")
                self.shutdown()
                return False

        except Exception as e:
            logger.error(f"Failed to start native server: {e}")
            self.shutdown()
            return False

    def ping(self) -> bool:
        """Send a ping command and wait for response."""
        if not self._channel:
            return False
        try:
            cmd = _pack_u8(CMD_PING)
            result = self._lib.pymc_ipc_send_command(
                self._channel, cmd, len(cmd)
            )
            if not result:
                return False

            buf = ctypes.create_string_buffer(64)
            self._lib.pymc_ipc_wait_for_response(self._channel, 2000)
            n = self._lib.pymc_ipc_recv_response(self._channel, buf, 64)
            if n < 4:
                return False

            status = _unpack_u32(buf.raw[:4])
            return status == STATUS_OK
        except Exception:
            return False

    def send_command(self, data: bytes) -> Optional[bytes]:
        """Send a command and wait for the response."""
        if not self._channel:
            return None
        try:
            result = self._lib.pymc_ipc_send_command(
                self._channel, data, len(data)
            )
            if not result:
                logger.warning("IPC send_command: buffer full")
                return None

            buf = ctypes.create_string_buffer(self._resp_size)
            self._lib.pymc_ipc_wait_for_response(self._channel, 5000)
            n = self._lib.pymc_ipc_recv_response(
                self._channel, buf, self._resp_size
            )
            if n < 4:
                return None
            return buf.raw[:n]
        except Exception as e:
            logger.warning(f"IPC send_command failed: {e}")
            return None

    @property
    def available(self) -> bool:
        return (
            self._initialized
            and self._channel is not None
            and self._process is not None
            and self._process.poll() is None
        )

    def shutdown(self):
        """Shut down the native server process."""
        if self._channel:
            try:
                cmd = _pack_u8(CMD_SHUTDOWN)
                self._lib.pymc_ipc_send_command(
                    self._channel, cmd, len(cmd)
                )
                # Wait briefly for response
                buf = ctypes.create_string_buffer(64)
                self._lib.pymc_ipc_wait_for_response(self._channel, 500)
                self._lib.pymc_ipc_recv_response(self._channel, buf, 64)
            except Exception:
                pass

        if self._process:
            try:
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._channel and self._lib:
            try:
                self._lib.pymc_ipc_channel_destroy(self._channel)
            except Exception:
                pass
            self._channel = None

        self._initialized = False


# ===========================================================
# Direct in-process engine access (via ctypes)
# ===========================================================

class NativeRedstoneEngine:
    """Direct in-process redstone engine via ctypes."""

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib
        self._engine = lib.pymc_redstone_create()
        if not self._engine:
            raise RuntimeError("Failed to create redstone engine")

    def add_component(self, x: int, y: int, z: int,
                      comp_type: int, facing: int):
        self._lib.pymc_redstone_add_component(
            self._engine, x, y, z, comp_type, facing
        )

    def remove_component(self, x: int, y: int, z: int):
        self._lib.pymc_redstone_remove_component(self._engine, x, y, z)

    def set_power_level(self, x: int, y: int, z: int, level: int):
        self._lib.pymc_redstone_set_power(self._engine, x, y, z, level)

    def get_power_level(self, x: int, y: int, z: int) -> int:
        return self._lib.pymc_redstone_get_power(self._engine, x, y, z)

    def tick(self) -> list:
        """Process one tick. Returns list of (x, y, z, new_state, flags)."""
        max_updates = 4096
        buf = (ctypes.c_int32 * (max_updates * 5))()
        count = self._lib.pymc_redstone_tick(self._engine, buf, max_updates)

        updates = []
        for i in range(count):
            updates.append((
                buf[i * 5], buf[i * 5 + 1], buf[i * 5 + 2],
                buf[i * 5 + 3], buf[i * 5 + 4]
            ))
        return updates

    def clear(self):
        self._lib.pymc_redstone_clear(self._engine)

    def destroy(self):
        if self._engine:
            self._lib.pymc_redstone_destroy(self._engine)
            self._engine = None

    def __del__(self):
        self.destroy()


class NativeLightEngine:
    """Direct in-process light engine via ctypes."""

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib
        self._engine = lib.pymc_light_create()
        if not self._engine:
            raise RuntimeError("Failed to create light engine")

    def calculate_chunk_lighting(self, blocks: list) -> tuple:
        """
        Calculate lighting for a chunk.

        Args:
            blocks: flat list of 98304 uint16 block state IDs

        Returns:
            (sky_light, block_light) as bytes arrays
        """
        blocks_array = (ctypes.c_uint16 * len(blocks))(*blocks)

        sky_size = LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE
        block_size = sky_size

        sky_light = (ctypes.c_uint8 * sky_size)()
        block_light = (ctypes.c_uint8 * block_size)()

        self._lib.pymc_light_calculate_chunk(
            self._engine, blocks_array, sky_light, block_light
        )

        return bytes(sky_light), bytes(block_light)

    def update_block_light(self, x: int, y: int, z: int,
                           old_block: int, new_block: int) -> list:
        """Incremental light update."""
        max_updates = 256
        buf = (ctypes.c_int32 * (max_updates * 5))()
        count = self._lib.pymc_light_update_block(
            self._engine, x, y, z, old_block, new_block, buf, max_updates
        )

        updates = []
        for i in range(count):
            updates.append({
                'x': buf[i * 5],
                'y': buf[i * 5 + 1],
                'z': buf[i * 5 + 2],
                'sky_light': buf[i * 5 + 3],
                'block_light': buf[i * 5 + 4],
            })
        return updates

    def set_block_info(self, block_state: int, sky_type: int,
                       block_type: int, emitted_light: int, filter_level: int):
        self._lib.pymc_light_set_block_info(
            self._engine, block_state, sky_type, block_type,
            emitted_light, filter_level
        )

    def destroy(self):
        if self._engine:
            self._lib.pymc_light_destroy(self._engine)
            self._engine = None

    def __del__(self):
        self.destroy()


class NativePhysicsEngine:
    """Direct in-process physics engine via ctypes."""

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib
        self._engine = lib.pymc_physics_create()
        if not self._engine:
            raise RuntimeError("Failed to create physics engine")

    def set_entity(self, entity_id: int, x: float, y: float, z: float,
                   vx: float = 0.0, vy: float = 0.0, vz: float = 0.0,
                   bb_min: tuple = (-0.3, 0.0, -0.3),
                   bb_max: tuple = (0.3, 1.8, 0.3),
                   on_ground: bool = False, has_gravity: bool = True,
                   is_item: bool = False, is_falling_block: bool = False,
                   block_state: int = 0):
        entity = (
            _pack_i32(entity_id) +
            _pack_f64(x) + _pack_f64(y) + _pack_f64(z) +
            _pack_f64(vx) + _pack_f64(vy) + _pack_f64(vz) +
            _pack_f64(bb_min[0]) + _pack_f64(bb_min[1]) + _pack_f64(bb_min[2]) +
            _pack_f64(bb_max[0]) + _pack_f64(bb_max[1]) + _pack_f64(bb_max[2]) +
            _pack_u8(int(on_ground)) + _pack_u8(int(has_gravity)) +
            _pack_u8(int(is_item)) + _pack_u8(int(is_falling_block)) +
            _pack_u16(block_state)
        )

        class PhysicsEntity(ctypes.Structure):
            _fields_ = [
                ("entity_id", ctypes.c_int32),
                ("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double),
                ("vx", ctypes.c_double), ("vy", ctypes.c_double), ("vz", ctypes.c_double),
                ("bb_min_x", ctypes.c_double), ("bb_min_y", ctypes.c_double), ("bb_min_z", ctypes.c_double),
                ("bb_max_x", ctypes.c_double), ("bb_max_y", ctypes.c_double), ("bb_max_z", ctypes.c_double),
                ("on_ground", ctypes.c_uint8),
                ("has_gravity", ctypes.c_uint8),
                ("is_item", ctypes.c_uint8),
                ("is_falling_block", ctypes.c_uint8),
                ("block_state", ctypes.c_uint16),
            ]

        e = PhysicsEntity()
        e.entity_id = entity_id
        e.x, e.y, e.z = x, y, z
        e.vx, e.vy, e.vz = vx, vy, vz
        e.bb_min_x, e.bb_min_y, e.bb_min_z = bb_min
        e.bb_max_x, e.bb_max_y, e.bb_max_z = bb_max
        e.on_ground = int(on_ground)
        e.has_gravity = int(has_gravity)
        e.is_item = int(is_item)
        e.is_falling_block = int(is_falling_block)
        e.block_state = block_state

        self._lib.pymc_physics_set_entity(self._engine, ctypes.byref(e))

    def remove_entity(self, entity_id: int):
        self._lib.pymc_physics_remove_entity(self._engine, entity_id)

    def set_blocks(self, blocks: list):
        """
        Set block data for collision.

        Args:
            blocks: list of (x, y, z, block_state) tuples
        """
        if not blocks:
            return

        count = len(blocks)
        xyz_data = (ctypes.c_int32 * (count * 3))()
        block_states = (ctypes.c_uint16 * count)()

        for i, (x, y, z, bs) in enumerate(blocks):
            xyz_data[i * 3] = x
            xyz_data[i * 3 + 1] = y
            xyz_data[i * 3 + 2] = z
            block_states[i] = bs

        self._lib.pymc_physics_set_blocks(
            self._engine, xyz_data, block_states, count
        )

    def tick(self) -> list:
        """Process one physics tick. Returns list of update dicts."""
        max_updates = 1024

        class PhysicsUpdate(ctypes.Structure):
            _fields_ = [
                ("entity_id", ctypes.c_int32),
                ("new_x", ctypes.c_double), ("new_y", ctypes.c_double), ("new_z", ctypes.c_double),
                ("new_vx", ctypes.c_double), ("new_vy", ctypes.c_double), ("new_vz", ctypes.c_double),
                ("on_ground", ctypes.c_uint8),
                ("landed", ctypes.c_uint8),
                ("landed_block_state", ctypes.c_uint16),
                ("landed_x", ctypes.c_int32), ("landed_y", ctypes.c_int32), ("landed_z", ctypes.c_int32),
            ]

        buf = (PhysicsUpdate * max_updates)()
        count = self._lib.pymc_physics_tick(self._engine, buf, max_updates)

        updates = []
        for i in range(count):
            u = buf[i]
            updates.append({
                'entity_id': u.entity_id,
                'new_x': u.new_x, 'new_y': u.new_y, 'new_z': u.new_z,
                'new_vx': u.new_vx, 'new_vy': u.new_vy, 'new_vz': u.new_vz,
                'on_ground': bool(u.on_ground),
                'landed': bool(u.landed),
                'landed_block_state': u.landed_block_state,
                'landed_x': u.landed_x, 'landed_y': u.landed_y, 'landed_z': u.landed_z,
            })
        return updates

    def clear_blocks(self):
        self._lib.pymc_physics_clear_blocks(self._engine)

    def destroy(self):
        if self._engine:
            self._lib.pymc_physics_destroy(self._engine)
            self._engine = None

    def __del__(self):
        self.destroy()


# ===========================================================
# IPC-based engine wrappers (communicate with server process)
# ===========================================================

class IPCRedstoneEngine:
    """Redstone engine via IPC to the native server process."""

    def __init__(self, ipc: NativeIPCConnection):
        self._ipc = ipc

    def add_component(self, x: int, y: int, z: int,
                      comp_type: int, facing: int):
        cmd = (_pack_u8(CMD_ADD_REDSTONE) +
               _pack_i32(x) + _pack_i32(y) + _pack_i32(z) +
               _pack_u8(comp_type) + _pack_u8(facing))
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def remove_component(self, x: int, y: int, z: int):
        cmd = (_pack_u8(CMD_REMOVE_REDSTONE) +
               _pack_i32(x) + _pack_i32(y) + _pack_i32(z))
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def set_power_level(self, x: int, y: int, z: int, level: int):
        cmd = (_pack_u8(CMD_SET_POWER) +
               _pack_i32(x) + _pack_i32(y) + _pack_i32(z) +
               _pack_i32(level))
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def tick(self) -> list:
        """Process one tick. Returns list of update dicts."""
        cmd = _pack_u8(CMD_TICK)
        resp = self._ipc.send_command(cmd)
        if not resp or _unpack_u32(resp) != STATUS_OK:
            return []

        offset = 4
        # Read redstone updates
        rs_count = _unpack_u32(resp, offset)
        offset += 4

        updates = []
        for _ in range(rs_count):
            x = _unpack_i32(resp, offset); offset += 4
            y = _unpack_i32(resp, offset); offset += 4
            z = _unpack_i32(resp, offset); offset += 4
            new_state = _unpack_i32(resp, offset); offset += 4
            flags = _unpack_i32(resp, offset); offset += 4
            updates.append({
                'type': 'redstone',
                'x': x, 'y': y, 'z': z,
                'new_block_state': new_state,
                'flags': flags,
            })

        # Read physics updates
        phys_count = _unpack_u32(resp, offset)
        offset += 4

        for _ in range(phys_count):
            entity_id = _unpack_i32(resp, offset); offset += 4
            new_x = _unpack_f64(resp, offset); offset += 8
            new_y = _unpack_f64(resp, offset); offset += 8
            new_z = _unpack_f64(resp, offset); offset += 8
            new_vx = _unpack_f64(resp, offset); offset += 8
            new_vy = _unpack_f64(resp, offset); offset += 8
            new_vz = _unpack_f64(resp, offset); offset += 8
            on_ground = _unpack_u8(resp, offset); offset += 1
            landed = _unpack_u8(resp, offset); offset += 1
            landed_bs = 0
            landed_x = landed_y = landed_z = 0
            if landed:
                landed_bs = _unpack_u16(resp, offset); offset += 2
                landed_x = _unpack_i32(resp, offset); offset += 4
                landed_y = _unpack_i32(resp, offset); offset += 4
                landed_z = _unpack_i32(resp, offset); offset += 4

            updates.append({
                'type': 'physics',
                'entity_id': entity_id,
                'new_x': new_x, 'new_y': new_y, 'new_z': new_z,
                'new_vx': new_vx, 'new_vy': new_vy, 'new_vz': new_vz,
                'on_ground': bool(on_ground),
                'landed': bool(landed),
                'landed_block_state': landed_bs,
                'landed_x': landed_x, 'landed_y': landed_y, 'landed_z': landed_z,
            })

        return updates


class IPCLightEngine:
    """Light engine via IPC to the native server process."""

    def __init__(self, ipc: NativeIPCConnection):
        self._ipc = ipc

    def calculate_chunk_lighting(self, blocks: list) -> tuple:
        """
        Calculate lighting for a chunk.

        Args:
            blocks: flat list of 98304 uint16 block state IDs

        Returns:
            (sky_light, block_light) as bytes
        """
        # Pack blocks as little-endian uint16
        blocks_data = b''.join(_pack_u16(b) for b in blocks)
        cmd = _pack_u8(CMD_CALC_LIGHT) + blocks_data
        resp = self._ipc.send_command(cmd)

        if not resp or _unpack_u32(resp) != STATUS_OK:
            return b'', b''

        offset = 4
        light_size = LIGHT_SECTIONS * SECTION_SIZE * SECTION_SIZE * SECTION_SIZE
        sky_light = resp[offset:offset + light_size]
        offset += light_size
        block_light = resp[offset:offset + light_size]
        return sky_light, block_light

    def update_block_light(self, x: int, y: int, z: int,
                           old_block: int, new_block: int) -> list:
        cmd = (_pack_u8(CMD_UPDATE_LIGHT) +
               _pack_i32(x) + _pack_i32(y) + _pack_i32(z) +
               _pack_u16(old_block) + _pack_u16(new_block))
        resp = self._ipc.send_command(cmd)
        if not resp or _unpack_u32(resp) != STATUS_OK:
            return []

        offset = 4
        count = _unpack_u32(resp, offset)
        offset += 4
        updates = []
        for _ in range(count):
            ux = _unpack_i32(resp, offset); offset += 4
            uy = _unpack_i32(resp, offset); offset += 4
            uz = _unpack_i32(resp, offset); offset += 4
            usl = _unpack_u8(resp, offset); offset += 1
            ubl = _unpack_u8(resp, offset); offset += 1
            updates.append({
                'x': ux, 'y': uy, 'z': uz,
                'sky_light': usl, 'block_light': ubl,
            })
        return updates


class IPCPhysicsEngine:
    """Physics engine via IPC to the native server process."""

    def __init__(self, ipc: NativeIPCConnection):
        self._ipc = ipc

    def set_entity(self, entity_id: int, x: float, y: float, z: float,
                   vx: float = 0.0, vy: float = 0.0, vz: float = 0.0,
                   bb_min: tuple = (-0.3, 0.0, -0.3),
                   bb_max: tuple = (0.3, 1.8, 0.3),
                   on_ground: bool = False, has_gravity: bool = True,
                   is_item: bool = False, is_falling_block: bool = False,
                   block_state: int = 0):
        cmd = (_pack_u8(CMD_SET_ENTITY) +
               _pack_i32(entity_id) +
               _pack_f64(x) + _pack_f64(y) + _pack_f64(z) +
               _pack_f64(vx) + _pack_f64(vy) + _pack_f64(vz) +
               _pack_f64(bb_min[0]) + _pack_f64(bb_min[1]) + _pack_f64(bb_min[2]) +
               _pack_f64(bb_max[0]) + _pack_f64(bb_max[1]) + _pack_f64(bb_max[2]) +
               _pack_u8(int(on_ground)) + _pack_u8(int(has_gravity)) +
               _pack_u8(int(is_item)) + _pack_u8(int(is_falling_block)) +
               _pack_u16(block_state))
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def remove_entity(self, entity_id: int):
        cmd = _pack_u8(CMD_REMOVE_ENTITY) + _pack_i32(entity_id)
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def set_blocks(self, blocks: list):
        """Set block data. blocks: list of (x, y, z, block_state) tuples."""
        payload = _pack_u32(len(blocks))
        for x, y, z, bs in blocks:
            payload += _pack_i32(x) + _pack_i32(y) + _pack_i32(z) + _pack_u16(bs)
        cmd = _pack_u8(CMD_SET_BLOCKS) + payload
        resp = self._ipc.send_command(cmd)
        return resp is not None and _unpack_u32(resp) == STATUS_OK

    def tick_fluids(self) -> list:
        cmd = _pack_u8(CMD_TICK_FLUIDS)
        resp = self._ipc.send_command(cmd)
        if not resp or _unpack_u32(resp) != STATUS_OK:
            return []

        offset = 4
        count = _unpack_u32(resp, offset)
        offset += 4
        updates = []
        for _ in range(count):
            fx = _unpack_i32(resp, offset); offset += 4
            fy = _unpack_i32(resp, offset); offset += 4
            fz = _unpack_i32(resp, offset); offset += 4
            fbs = _unpack_u16(resp, offset); offset += 2
            flv = struct.unpack_from('<b', resp, offset)[0]; offset += 1
            updates.append({
                'x': fx, 'y': fy, 'z': fz,
                'new_block_state': fbs,
                'new_fluid_level': flv,
            })
        return updates


# ===========================================================
# Main entry point: NativeCore
# ===========================================================

class NativeCore:
    """
    Python interface to the C++ acceleration layer.

    Automatically selects the best available mode:
      1. IPC mode (separate process, shared memory ring buffer) - FASTEST
      2. Direct mode (in-process shared library via ctypes)
      3. Subprocess mode (fallback to existing terrain_gen/mob_ai)

    Usage:
        core = NativeCore()
        if core.available:
            core.redstone.add_component(0, 64, 0, COMPONENT_LEVER, FACING_UP)
            updates = core.redstone.tick()
    """

    def __init__(self, prefer_ipc: bool = True):
        self._mode = "none"
        self._ipc: Optional[NativeIPCConnection] = None
        self._lib: Optional[ctypes.CDLL] = None

        self.redstone = None
        self.lighting = None
        self.physics = None

        # Try IPC mode first (fastest)
        if prefer_ipc:
            try:
                self._init_ipc_mode()
                if self._mode != "none":
                    return
            except Exception as e:
                logger.debug(f"IPC mode unavailable: {e}")

        # Try direct in-process mode
        try:
            self._init_direct_mode()
            if self._mode != "none":
                return
        except Exception as e:
            logger.debug(f"Direct mode unavailable: {e}")

        logger.info("Native acceleration layer not available, using Python fallback")

    def _init_ipc_mode(self):
        """Initialize IPC mode (separate process + shared memory)."""
        ipc = NativeIPCConnection()
        if ipc.start():
            self._ipc = ipc
            self._mode = "ipc"
            self.redstone = IPCRedstoneEngine(ipc)
            self.lighting = IPCLightEngine(ipc)
            self.physics = IPCPhysicsEngine(ipc)
            logger.info("Native acceleration layer: IPC mode (shared memory)")

    def _init_direct_mode(self):
        """Initialize direct in-process mode via ctypes."""
        lib_path = _find_native_lib()
        if lib_path is None:
            return

        lib = ctypes.CDLL(lib_path)

        # Set up function signatures
        lib.pymc_redstone_create.restype = ctypes.c_void_p
        lib.pymc_redstone_create.argtypes = []
        lib.pymc_redstone_destroy.restype = None
        lib.pymc_redstone_destroy.argtypes = [ctypes.c_void_p]
        lib.pymc_redstone_add_component.restype = None
        lib.pymc_redstone_add_component.argtypes = [
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
            ctypes.c_uint8, ctypes.c_uint8
        ]
        lib.pymc_redstone_remove_component.restype = None
        lib.pymc_redstone_remove_component.argtypes = [
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32
        ]
        lib.pymc_redstone_set_power.restype = None
        lib.pymc_redstone_set_power.argtypes = [
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32
        ]
        lib.pymc_redstone_get_power.restype = ctypes.c_int32
        lib.pymc_redstone_get_power.argtypes = [
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32
        ]
        lib.pymc_redstone_tick.restype = ctypes.c_uint32
        lib.pymc_redstone_tick.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint32]
        lib.pymc_redstone_clear.restype = None
        lib.pymc_redstone_clear.argtypes = [ctypes.c_void_p]

        lib.pymc_light_create.restype = ctypes.c_void_p
        lib.pymc_light_create.argtypes = []
        lib.pymc_light_destroy.restype = None
        lib.pymc_light_destroy.argtypes = [ctypes.c_void_p]
        lib.pymc_light_calculate_chunk.restype = None
        lib.pymc_light_calculate_chunk.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8)
        ]
        lib.pymc_light_update_block.restype = ctypes.c_uint32
        lib.pymc_light_update_block.argtypes = [
            ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
            ctypes.c_uint16, ctypes.c_uint16,
            ctypes.POINTER(ctypes.c_int32), ctypes.c_uint32
        ]
        lib.pymc_light_set_block_info.restype = None
        lib.pymc_light_set_block_info.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint8,
            ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8
        ]

        lib.pymc_physics_create.restype = ctypes.c_void_p
        lib.pymc_physics_create.argtypes = []
        lib.pymc_physics_destroy.restype = None
        lib.pymc_physics_destroy.argtypes = [ctypes.c_void_p]
        lib.pymc_physics_set_entity.restype = None
        lib.pymc_physics_set_entity.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.pymc_physics_remove_entity.restype = None
        lib.pymc_physics_remove_entity.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        lib.pymc_physics_set_blocks.restype = None
        lib.pymc_physics_set_blocks.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_uint16), ctypes.c_uint32
        ]
        lib.pymc_physics_tick.restype = ctypes.c_uint32
        lib.pymc_physics_tick.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        lib.pymc_physics_clear_blocks.restype = None
        lib.pymc_physics_clear_blocks.argtypes = [ctypes.c_void_p]

        self._lib = lib
        self._mode = "direct"
        self.redstone = NativeRedstoneEngine(lib)
        self.lighting = NativeLightEngine(lib)
        self.physics = NativePhysicsEngine(lib)
        logger.info("Native acceleration layer: Direct mode (in-process ctypes)")

    @property
    def available(self) -> bool:
        """Check if native acceleration is available."""
        return self._mode != "none"

    @property
    def mode(self) -> str:
        """Get the current mode: 'ipc', 'direct', or 'none'."""
        return self._mode

    def tick(self):
        """Process one native tick (redstone + physics)."""
        if self.redstone is not None:
            return self.redstone.tick()
        return []

    def shutdown(self):
        """Shut down the native acceleration layer."""
        if self._ipc:
            self._ipc.shutdown()
            self._ipc = None

        # Direct mode engines clean up in their __del__
        if self.redstone and hasattr(self.redstone, 'destroy'):
            self.redstone.destroy()
        if self.lighting and hasattr(self.lighting, 'destroy'):
            self.lighting.destroy()
        if self.physics and hasattr(self.physics, 'destroy'):
            self.physics.destroy()

        self._mode = "none"
        self.redstone = None
        self.lighting = None
        self.physics = None

    def __del__(self):
        self.shutdown()
