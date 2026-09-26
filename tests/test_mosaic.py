import unittest

import cv2
import numpy as np

from fingerprint_mosaic import Mosaic


def synthetic_ridges():
    random = np.random.default_rng(7)
    y, x = np.mgrid[:160, :160]
    phase = x * 0.6 + 0.15 * np.sin(y / 17) * x / 5 + 0.22 * np.sin(x / 23) * y / 5
    noise = cv2.GaussianBlur(random.normal(size=(160, 160)).astype("float32"), (0, 0), 1.2)
    return np.uint8(np.clip(125 + 70 * np.sin(phase) + 22 * noise, 0, 255))


class MosaicTests(unittest.TestCase):
    def test_translated_tiles_expand_observed_area(self):
        image = synthetic_ridges()
        first = image[20:100, 20:100]
        second = image[35:115, 28:108]
        mosaic = Mosaic()
        mosaic.add(first, mosaic.propose(first))
        match = mosaic.propose(second)
        self.assertIsNotNone(match)
        self.assertGreater(match.inliers, 7)
        self.assertGreater(match.correlation, 0.9)
        self.assertAlmostEqual(match.pose[0, 2], 288, delta=1)
        self.assertAlmostEqual(match.pose[1, 2], 295, delta=1)
        mosaic.add(second, match)
        rgba, _ = mosaic.render()
        self.assertGreater(rgba.shape[0], 80)
        self.assertGreater(rgba.shape[1], 80)
        self.assertEqual(rgba.shape[2], 4)

    def test_blank_patch_cannot_be_registered(self):
        image = synthetic_ridges()
        mosaic = Mosaic()
        first = image[20:100, 20:100]
        mosaic.add(first, mosaic.propose(first))
        self.assertIsNone(mosaic.propose(np.zeros((80, 80), np.uint8)))


if __name__ == "__main__":
    unittest.main()
