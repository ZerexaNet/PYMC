import asyncio
import json
import socket
import unittest
from types import SimpleNamespace

from watchdog.process_manager import WatchdogManager


def make_watchdog():
    """真实 UDP 健康服务器, 端口由 OS 分配。"""
    server = SimpleNamespace(
        config={"watchdog-health-port": 0, "watchdog-max-missed-heartbeats": 5},
        get_online_players=lambda: [],
    )
    return WatchdogManager(server)


class WatchdogEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_pong_over_real_udp(self):
        """端到端: 真实 UDP  socket 发送 PYMC_PING, 收到 PYMC_HEALTH。"""
        wd = make_watchdog()
        await wd._start_health_server()
        self.assertIsNotNone(wd._health_server)
        port = wd._health_server.get_extra_info("sockname")[1]
        self.assertGreater(port, 0)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(b"PYMC_PING", ("127.0.0.1", port))
            data, _ = await asyncio.to_thread(sock.recvfrom, 4096)
            sock.close()

            text = data.decode("utf-8")
            self.assertTrue(text.startswith("PYMC_HEALTH|"))
            payload = json.loads(text.split("|", 1)[1])
            self.assertIn("pid", payload)
            self.assertIn("tps", payload)
            self.assertIn("uptime_seconds", payload)
        finally:
            wd._health_server.close()

    async def test_heartbeat_updates_partner_state(self):
        """端到端: 收到 PYMC_HB 心跳后更新伙伴进程状态。"""
        wd = make_watchdog()
        await wd._start_health_server()
        port = wd._health_server.get_extra_info("sockname")[1]

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(b"PYMC_HB|4242|19.5|3|512.0|1700000000",
                        ("127.0.0.1", port))
            sock.close()
            # handle_heartbeat 通过 ensure_future 调度, 让事件循环执行
            await asyncio.sleep(0.2)

            self.assertEqual(wd.partner_pid, 4242)
            self.assertAlmostEqual(wd._partner_tps, 19.5)
            self.assertEqual(wd._partner_players, 3)
            self.assertGreater(wd._partner_last_seen, 0)
        finally:
            wd._health_server.close()


if __name__ == "__main__":
    unittest.main()
