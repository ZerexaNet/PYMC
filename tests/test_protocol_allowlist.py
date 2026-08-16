import unittest

from protocol.versions import filter_supported_versions


class ProtocolAllowlistTests(unittest.TestCase):
    def test_all_respects_minimum_and_maximum(self):
        self.assertEqual(filter_supported_versions("all", 767, 770), [767, 770])

    def test_comma_separated_allowlist_is_parsed_and_filtered(self):
        self.assertEqual(
            filter_supported_versions("47, 340, 767, 999, invalid", 47, 770),
            [47, 340, 767],
        )

    def test_empty_or_invalid_allowlist_enables_nothing(self):
        self.assertEqual(filter_supported_versions("", 47, 770), [])
        self.assertEqual(filter_supported_versions("invalid", 47, 770), [])


if __name__ == "__main__":
    unittest.main()