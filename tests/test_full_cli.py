import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from elan0c82 import run_full


class FullCliTests(unittest.TestCase):
    def test_two_overlapping_passes_expand_both_axes(self):
        random = np.random.default_rng(7)
        y, x = np.mgrid[:200, :200]
        phase = x * 0.6 + 0.15 * np.sin(y / 17) * x / 5 + 0.22 * np.sin(x / 23) * y / 5
        noise = cv2.GaussianBlur(random.normal(size=(200, 200)).astype("float32"), (0, 0), 1.2)
        image = np.uint8(np.clip(125 + 70 * np.sin(phase) + 22 * noise, 0, 255))
        frames = [image[sy:sy + 80, sx:sx + 80].tobytes()
                  for sx in (20, 35) for sy in (20, 35, 50, 65)]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mosaic.png"
            with patch("builtins.input", side_effect=("", "")), \
                    patch("elan0c82.read_frame", side_effect=frames):
                self.assertEqual(run_full(None, 80, 80, output, 100, 4, 2, None), 0)
            with Image.open(output) as result:
                self.assertEqual(result.mode, "RGBA")
                self.assertGreater(result.width, 80)
                self.assertGreater(result.height, 80)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
