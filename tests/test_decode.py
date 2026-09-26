import unittest

from elan0c82 import decode_size, normalize_image


class DecodeTests(unittest.TestCase):
    def test_size_and_pixels(self):
        self.assertEqual(decode_size(bytes([51, 0, 149, 0])), (52, 150))
        self.assertEqual(normalize_image(bytes([0, 0, 255, 0]), 2, 1), bytes([0, 255]))

    def test_rejects_truncated_or_flat_image(self):
        with self.assertRaises(ValueError):
            normalize_image(b"\x00\x00", 2, 1)
        with self.assertRaises(ValueError):
            normalize_image(b"\x01\x00\x01\x00", 2, 1)


if __name__ == "__main__":
    unittest.main()
