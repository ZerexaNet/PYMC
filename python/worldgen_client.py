import struct
import subprocess
from dataclasses import dataclass


MAGIC = 0x4E475752
VERSION = 1

REQ_INIT = 1
REQ_COLUMN = 2
REQ_REGION = 3
REQ_PING = 4
REQ_SHUTDOWN = 5

RESP_ERROR = 0xFFFF
RESP_FLAG = 0x8000


@dataclass
class ColumnSample:
    x: int
    z: int
    height: int
    biome_id: int
    temperature: float
    humidity: float
    continentalness: float
    erosion: float
    weirdness: float
    peaks_valleys: float


class WorldgenClient:
    def __init__(self, exe_path: str):
        self.proc = subprocess.Popen(
            [exe_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def close(self):
        try:
            self.shutdown()
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()

    def _read_exact(self, n: int) -> bytes:
        data = self.proc.stdout.read(n)
        if data is None or len(data) != n:
            raise RuntimeError(f"unexpected EOF while reading {n} bytes")
        return data

    def _send(self, req_type: int, payload: bytes) -> tuple[int, bytes]:
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("process pipes are not available")
        header = struct.pack("<IHHI", MAGIC, VERSION, req_type, len(payload))
        self.proc.stdin.write(header)
        if payload:
            self.proc.stdin.write(payload)
        self.proc.stdin.flush()

        resp_header = self._read_exact(12)
        magic, version, resp_type, length = struct.unpack("<IHHI", resp_header)
        if magic != MAGIC:
            raise RuntimeError(f"bad response magic: {magic:#x}")
        if version != VERSION:
            raise RuntimeError(f"bad response version: {version}")
        body = self._read_exact(length) if length else b""

        if resp_type == RESP_ERROR:
            if len(body) < 8:
                raise RuntimeError("malformed error response")
            code, msg_len = struct.unpack("<iI", body[:8])
            msg = body[8 : 8 + msg_len].decode("utf-8", errors="replace")
            raise RuntimeError(f"server error {code}: {msg}")
        return resp_type, body

    def init(self, seed: int):
        resp_type, body = self._send(REQ_INIT, struct.pack("<q", seed))
        expected = RESP_FLAG | REQ_INIT
        if resp_type != expected:
            raise RuntimeError(f"unexpected response type {resp_type:#x}")
        status, ret_seed = struct.unpack("<iq", body)
        if status != 0:
            raise RuntimeError(f"init failed with status {status}")
        return ret_seed

    def ping(self, token: bytes = b"ping") -> bytes:
        resp_type, body = self._send(REQ_PING, token)
        expected = RESP_FLAG | REQ_PING
        if resp_type != expected:
            raise RuntimeError(f"unexpected response type {resp_type:#x}")
        return body

    def sample_column(self, x: int, z: int) -> ColumnSample:
        resp_type, body = self._send(REQ_COLUMN, struct.pack("<ii", x, z))
        expected = RESP_FLAG | REQ_COLUMN
        if resp_type != expected:
            raise RuntimeError(f"unexpected response type {resp_type:#x}")
        if len(body) != 40:
            raise RuntimeError(f"unexpected column payload length: {len(body)}")
        vals = struct.unpack("<iiiHHffffff", body)
        return ColumnSample(
            x=vals[0],
            z=vals[1],
            height=vals[2],
            biome_id=vals[3],
            temperature=vals[5],
            humidity=vals[6],
            continentalness=vals[7],
            erosion=vals[8],
            weirdness=vals[9],
            peaks_valleys=vals[10],
        )

    def sample_region(self, x0: int, z0: int, width: int, depth: int):
        payload = struct.pack("<iiii", x0, z0, width, depth)
        resp_type, body = self._send(REQ_REGION, payload)
        expected = RESP_FLAG | REQ_REGION
        if resp_type != expected:
            raise RuntimeError(f"unexpected response type {resp_type:#x}")
        if len(body) < 16:
            raise RuntimeError("region payload too short")
        rx, rz, rw, rd = struct.unpack("<iiii", body[:16])
        expected_cells = rw * rd
        expected_len = 16 + expected_cells * 4
        if len(body) != expected_len:
            raise RuntimeError(
                f"region payload length mismatch: got {len(body)}, expected {expected_len}"
            )
        rows = []
        offset = 16
        for dz in range(rd):
            row = []
            for dx in range(rw):
                biome_id, height = struct.unpack("<HH", body[offset : offset + 4])
                row.append((biome_id, height))
                offset += 4
            rows.append(row)
        return rx, rz, rows

    def shutdown(self):
        if self.proc.poll() is not None:
            return
        self._send(REQ_SHUTDOWN, b"")


if __name__ == "__main__":
    # Example:
    #   python worldgen_client.py ..\\build\\rootree_worldgen.exe
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("exe")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--z", type=int, default=0)
    args = parser.parse_args()

    cli = WorldgenClient(args.exe)
    try:
        print("init seed:", cli.init(args.seed))
        print("ping:", cli.ping(b"hello"))
        col = cli.sample_column(args.x, args.z)
        print("column:", col)
        rx, rz, rows = cli.sample_region(args.x, args.z, 4, 4)
        print("region origin:", rx, rz)
        print("first row:", rows[0])
        cli.shutdown()
    finally:
        cli.close()
