import unittest
from types import SimpleNamespace

from admin.web import WebAdminServer


class WebAdminSecurityTests(unittest.TestCase):
    def test_loopback_hosts_are_allowed_by_default(self):
        self.assertTrue(WebAdminServer._is_loopback_host("127.0.0.1"))
        self.assertTrue(WebAdminServer._is_loopback_host("::1"))
        self.assertTrue(WebAdminServer._is_loopback_host("localhost"))

    def test_wildcard_and_remote_hosts_are_rejected(self):
        self.assertFalse(WebAdminServer._is_loopback_host("0.0.0.0"))
        self.assertFalse(WebAdminServer._is_loopback_host("::"))
        self.assertFalse(WebAdminServer._is_loopback_host("192.168.1.20"))
        self.assertFalse(WebAdminServer._is_loopback_host("admin.example.com"))

    def test_public_bind_requires_explicit_opt_in(self):
        admin = WebAdminServer(SimpleNamespace(), "0.0.0.0", 0)
        with self.assertRaisesRegex(ValueError, "web-admin-allow-remote"):
            admin.start()


if __name__ == "__main__":
    unittest.main()