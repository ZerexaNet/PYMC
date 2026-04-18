# ============================================================
# PyMC - 客户端连接管理
# 每个连接的客户端对应一个 Connection 实例
# ============================================================

import asyncio
import logging
import uuid
from enum import IntEnum
from protocol.packet import pack_packet, read_packet_async

logger = logging.getLogger("PyMC.连接")


class ConnectionState(IntEnum):
    """连接协议状态。"""
    HANDSHAKE = 0       # 握手阶段
    STATUS = 1          # 状态查询 (服务器列表)
    LOGIN = 2           # 登录阶段
    CONFIGURATION = 3   # 配置阶段 (1.20.2+)
    PLAY = 4            # 游戏阶段


class Connection:
    """
    表示一个客户端连接。
    管理连接状态、数据包收发和压缩。
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 server):
        self.reader = reader
        self.writer = writer
        self.server = server

        # 连接信息
        addr = writer.get_extra_info('peername')
        self.address = f"{addr[0]}:{addr[1]}" if addr else "未知"
        self.state = ConnectionState.HANDSHAKE
        self.compression_threshold = -1  # -1 表示未启用压缩

        # 玩家信息 (登录后设置)
        self.username: str = ""
        self.uuid: uuid.UUID = uuid.UUID(int=0)
        self.entity_id: int = 0

        # 玩家位置
        self.x: float = 0.0
        self.y: float = 100.0  # 出生点高度
        self.z: float = 0.0
        self.yaw: float = 0.0
        self.pitch: float = 0.0
        self.on_ground: bool = True

        # 连接状态
        self.alive = True
        self.keepalive_id: int = 0

        logger.info(f"新连接来自 {self.address}")

    async def send_packet(self, packet_id: int, payload: bytes = b''):
        """发送数据包给客户端。"""
        if not self.alive:
            return
        try:
            frame = pack_packet(packet_id, payload, self.compression_threshold)
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, OSError) as e:
            logger.warning(f"发送数据包失败 [{self.address}]: {e}")
            self.alive = False

    async def read_packet(self) -> tuple[int, bytes]:
        """读取一个数据包。返回 (数据包ID, 负载)。"""
        return await read_packet_async(self.reader, self.compression_threshold)

    async def disconnect(self, reason: str = ""):
        """断开连接。"""
        if not self.alive:
            return
        self.alive = False
        logger.info(f"断开连接 [{self.address}] {self.username or ''}: {reason}")
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    def generate_offline_uuid(self) -> uuid.UUID:
        """根据用户名生成离线模式 UUID。"""
        # 与 Java 版一致: UUID.nameUUIDFromBytes("OfflinePlayer:" + name)
        return uuid.uuid3(uuid.UUID("00000000-0000-0000-0000-000000000000"),
                          f"OfflinePlayer:{self.username}")

    def __repr__(self):
        return f"<Connection {self.address} state={self.state.name} user={self.username or '未登录'}>"
