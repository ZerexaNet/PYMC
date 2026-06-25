# ============================================================
# PyMC - C++ native mob AI bridge
# ============================================================

import logging
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("pymc.ai_native")

TICK_COMMAND = b"T"
REQUEST_HEADER_FORMAT = "<8i11dI"
PLAYER_FORMAT = "<3dB"
RESPONSE_HEADER_FORMAT = "<I"
RESPONSE_FORMAT = "<i4d4i3di"
RESPONSE_SIZE = struct.calcsize(RESPONSE_FORMAT)

MOB_TYPE_IDS = {
    "pig": 0,
    "cow": 1,
    "sheep": 2,
    "zombie": 3,
    "skeleton": 4,
    "creeper": 5,
    "spider": 6,
}


def _find_native_binary() -> str | None:
    # Pick binary name based on current OS
    if os.name == "nt":
        binary_names = ["mob_ai.exe", "mob_ai"]
    else:
        binary_names = ["mob_ai", "mob_ai.exe"]
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
        for relative in ("native", "."):
            base = root / relative
            for name in binary_names:
                candidate = (base / name).resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
        try:
            for pattern in ("mob_ai*", "native/mob_ai*"):
                for candidate in root.glob(pattern):
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(resolved)
        except Exception:
            pass

    for path in candidates:
        if path.exists() and path.is_file():
            if os.name == "nt" or os.access(path, os.X_OK):
                # Validate file format to avoid running wrong-arch binary
                try:
                    with open(path, 'rb') as f:
                        magic = f.read(4)
                    if os.name == "nt" and magic[:2] != b'MZ':
                        continue  # Not a valid PE executable
                    elif os.name != "nt" and magic != b'\x7fELF':
                        continue  # Not a valid ELF executable
                except Exception:
                    continue
                return str(path)
    return None


class NativeMobAiEngine:
    """Long-lived subprocess wrapper for native mob goal decisions."""

    def __init__(self, binary_path: str | None = None):
        self._binary_path = binary_path or _find_native_binary()
        self._process: subprocess.Popen | None = None
        self._disabled = False
        if self._binary_path:
            self._start_process()
        else:
            logger.info("未找到 mob_ai 原生 AI，将使用 Python AI 回退")

    @property
    def available(self) -> bool:
        return (
            not self._disabled
            and self._process is not None
            and self._process.poll() is None
        )

    def _start_process(self):
        if not self._binary_path or self._disabled:
            return
        try:
            self._process = subprocess.Popen(
                [self._binary_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            time.sleep(0.03)
            exit_code = self._process.poll()
            if exit_code is not None:
                stderr_data = b""
                if self._process.stderr is not None:
                    try:
                        stderr_data = self._process.stderr.read() or b""
                    except Exception:
                        stderr_data = b""
                logger.warning(
                    "原生 AI 启动后退出 (code=%s): %s",
                    exit_code,
                    stderr_data.decode("utf-8", errors="replace").strip() or "无错误输出",
                )
                self._process = None
                self._disabled = True
                return
            logger.info("原生 AI 子进程已启动 (PID: %s)", self._process.pid)
        except Exception as e:
            logger.warning("启动原生 AI 失败: %s", e)
            self._process = None
            self._disabled = True

    def _read_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._process.stdout.read(n - len(data))
            if not chunk:
                raise RuntimeError("原生 AI 子进程无响应")
            data += chunk
        return data

    def _online_players(self, server):
        players = server.get_online_players()
        payload = bytearray()
        for player in players:
            attackable = 0 if player.gamemode in {"creative", "spectator"} else 1
            payload.extend(struct.pack(PLAYER_FORMAT, player.x, player.y, player.z, attackable))
        return players, payload

    def tick_mob(self, mob, server) -> bool:
        if mob.mob_type not in MOB_TYPE_IDS:
            return False
        if not self.available:
            self._start_process()
            if not self.available:
                return False

        players, players_payload = self._online_players(server)
        has_target = int(mob.target_x is not None and mob.target_z is not None)
        target_x = float(mob.target_x) if mob.target_x is not None else 0.0
        target_y = float(mob.target_y) if mob.target_y is not None else 0.0
        target_z = float(mob.target_z) if mob.target_z is not None else 0.0

        request = bytearray(TICK_COMMAND)
        request.extend(struct.pack(
            REQUEST_HEADER_FORMAT,
            MOB_TYPE_IDS[mob.mob_type],
            int(mob.entity_id),
            int(mob.age_ticks),
            int(mob.wander_cooldown),
            int(mob.attack_cooldown),
            int(mob.aggressive_ticks),
            int(mob.look_time),
            has_target,
            float(mob.x),
            float(mob.y),
            float(mob.z),
            float(mob.yaw),
            float(mob.pitch),
            float(mob.vx),
            float(mob.vy),
            float(mob.vz),
            target_x,
            target_y,
            target_z,
            len(players),
        ))
        request.extend(players_payload)

        try:
            self._process.stdin.write(request)
            self._process.stdin.flush()

            header = self._read_exact(4)
            payload_size = struct.unpack(RESPONSE_HEADER_FORMAT, header)[0]
            if payload_size != RESPONSE_SIZE:
                raise RuntimeError(f"原生 AI 响应长度异常: {payload_size}")
            payload = self._read_exact(payload_size)
            (
                ok,
                vx,
                vz,
                yaw,
                pitch,
                wander_cooldown,
                aggressive_ticks,
                look_time,
                out_has_target,
                out_target_x,
                out_target_y,
                out_target_z,
                target_player_index,
            ) = struct.unpack(RESPONSE_FORMAT, payload)
            if not ok:
                return False

            mob.vx = vx
            mob.vz = vz
            mob.yaw = yaw
            mob.pitch = pitch
            mob.wander_cooldown = max(0, int(wander_cooldown))
            mob.aggressive_ticks = max(0, int(aggressive_ticks))
            mob.look_time = max(0, int(look_time))
            if out_has_target:
                mob.target_x = out_target_x
                mob.target_y = out_target_y
                mob.target_z = out_target_z
            else:
                mob.target_x = mob.target_y = mob.target_z = None
            if 0 <= target_player_index < len(players):
                mob.target_username = players[target_player_index].username
            elif mob.profile.get("category") == "hostile":
                mob.target_username = None
            return True

        except Exception as e:
            logger.warning("原生 AI tick 失败，回退到 Python AI: %s", e)
            self.shutdown()
            self._disabled = True
            return False

    def shutdown(self):
        if getattr(self, "_process", None):
            process = self._process
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=2)
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

    def __del__(self):
        self.shutdown()
