import unittest

from network.server import parse_vanilla_seed


def java_hash(text: str) -> int:
    value = 0
    for ch in text:
        value = (31 * value + ord(ch)) & 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


class SeedParsingTests(unittest.TestCase):
    def test_numeric_seed_uses_signed_long_range(self):
        self.assertEqual(parse_vanilla_seed("0"), 0)
        self.assertEqual(parse_vanilla_seed("-1"), -1)
        self.assertEqual(parse_vanilla_seed("9223372036854775807"), 9223372036854775807)
        self.assertEqual(parse_vanilla_seed("-9223372036854775808"), -9223372036854775808)

    def test_non_numeric_or_out_of_range_seed_uses_java_hash(self):
        self.assertEqual(parse_vanilla_seed("Glacier"), java_hash("Glacier"))
        self.assertEqual(parse_vanilla_seed("9223372036854775808"), java_hash("9223372036854775808"))
        self.assertEqual(parse_vanilla_seed("-9223372036854775809"), java_hash("-9223372036854775809"))
        self.assertEqual(parse_vanilla_seed(""), 0)


if __name__ == "__main__":
    unittest.main()
