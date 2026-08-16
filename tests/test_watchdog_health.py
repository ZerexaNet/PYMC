import json
import unittest
from types import SimpleNamespace

from watchdog.process_manager import WatchdogManager


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


class WatchdogHealthTests(unittest.TestCase):
    def test_ping_returns_health_payload(self):
        watchdog = SimpleNamespace()
        watchdog._health_server = FakeTransport()
        watchdog.get_health_status = lambda: {"pid": 42, "tps": 20.0}

        WatchdogManager._handle_incoming_message(
            watchdog, "PYMC_PING", ("127.0.0.1", 9999)
        )

        data, addr = watchdog._health_server.sent[0]
        prefix, payload = data.decode().split("|", 1)
        self.assertEqual(prefix, "PYMC_HEALTH")
        self.assertEqual(json.loads(payload)["pid"], 42)
        self.assertEqual(addr, ("127.0.0.1", 9999))


if __name__ == "__main__":
    unittest.main()
