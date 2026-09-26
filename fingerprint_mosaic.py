"""Register overlapping fingerprint tiles and render observed pixels only."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Tile:
    image: np.ndarray
    pose: np.ndarray  # 2x3 affine transform from tile pixels to canvas pixels


@dataclass
class Match:
    pose: np.ndarray
    reference: int
    inliers: int
    correlation: float
    new_fraction: float
    method: str = "initial"


class Mosaic:
    def __init__(self, size: int = 640):
        self.size = size
        self.tiles: list[Tile] = []
        self._sum = np.zeros((size, size), np.float32)
        self._weight = np.zeros((size, size), np.float32)
        self._sift = cv2.SIFT_create(nfeatures=500, contrastThreshold=0.015)
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)

    @property
    def covered(self) -> np.ndarray:
        return self._weight > 0.05

    def _feather(self, shape: tuple[int, int]) -> np.ndarray:
        height, width = shape
        yy, xx = np.indices(shape)
        edge = np.minimum.reduce((xx + 1, yy + 1, width - xx, height - yy))
        return np.minimum(edge / 10.0, 1.0).astype(np.float32)

    def _warp(self, tile: np.ndarray, pose: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        extent = (self.size, self.size)
        pixels = cv2.warpAffine(tile.astype(np.float32), pose, extent)
        weight = cv2.warpAffine(self._feather(tile.shape), pose, extent)
        return pixels, weight

    def _measure(self, tile: np.ndarray, pose: np.ndarray) -> tuple[float, float]:
        pixels, weight = self._warp(tile, pose)
        visible = weight > 0.05
        if visible.sum() < tile.size * 0.8:
            return -1.0, 0.0  # the proposed tile is outside the canvas
        overlap = visible & self.covered
        overlap_count = int(overlap.sum())
        if overlap_count < tile.size * 0.2:
            return -1.0, 0.0
        previous = self._sum[overlap] / self._weight[overlap]
        current = pixels[overlap]
        previous -= previous.mean()
        current -= current.mean()
        denom = float(np.linalg.norm(previous) * np.linalg.norm(current))
        correlation = float(previous @ current / denom) if denom > 0 else -1.0
        new_fraction = float((visible & ~self.covered).sum() / visible.sum())
        return correlation, new_fraction

    def _relative_pose(self, image: np.ndarray, reference: Tile) -> tuple[np.ndarray, int] | None:
        key_new, desc_new = self._sift.detectAndCompute(image, None)
        key_ref, desc_ref = self._sift.detectAndCompute(reference.image, None)
        if desc_new is None or desc_ref is None or len(desc_new) < 8 or len(desc_ref) < 8:
            return None
        pairs = self._matcher.knnMatch(desc_new, desc_ref, k=2)
        good = [a for a, b in pairs if a.distance < 0.75 * b.distance]
        if len(good) < 8:
            return None
        src = np.float32([key_new[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([key_ref[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        affine, inlier_mask = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.5,
            maxIters=3000, confidence=0.995,
        )
        if affine is None or inlier_mask is None:
            return None
        inliers = int(inlier_mask.sum())
        if inliers < 7 or inliers / len(good) < 0.35:
            return None
        scale = float(np.hypot(affine[0, 0], affine[1, 0]))
        angle = float(np.degrees(np.arctan2(affine[1, 0], affine[0, 0])))
        if not (0.90 <= scale <= 1.10 and abs(angle) <= 15):
            return None
        ref_pose = np.vstack((reference.pose, [0, 0, 1]))
        relative = np.vstack((affine, [0, 0, 1]))
        return (ref_pose @ relative)[:2], inliers

    def _translation_pose(self, image: np.ndarray, reference: Tile) -> np.ndarray | None:
        height, width = image.shape
        if reference.image.shape != image.shape:
            return None
        best_score = -1.0
        best_shift = None
        for dy in range(-24, 25):
            for dx in range(-24, 25):
                left_ref, left_new = max(dx, 0), max(-dx, 0)
                top_ref, top_new = max(dy, 0), max(-dy, 0)
                overlap_width, overlap_height = width - abs(dx), height - abs(dy)
                if overlap_width * overlap_height < image.size * 0.5:
                    continue
                a = reference.image[top_ref:top_ref + overlap_height,
                                    left_ref:left_ref + overlap_width]
                b = image[top_new:top_new + overlap_height,
                          left_new:left_new + overlap_width]
                score = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
                score -= 0.0005 * (abs(dx) + abs(dy))
                if score > best_score:
                    best_score, best_shift = score, (dx, dy)
        if best_shift is None or best_score < 0.45:
            return None
        relative = np.array([[1.0, 0.0, best_shift[0]],
                             [0.0, 1.0, best_shift[1]],
                             [0.0, 0.0, 1.0]])
        return (np.vstack((reference.pose, [0, 0, 1])) @ relative)[:2]

    def propose(self, image: np.ndarray) -> Match | None:
        if image.ndim != 2 or image.dtype != np.uint8:
            raise ValueError("tile must be an 8-bit grayscale image")
        if not self.tiles:
            pose = np.array([[1.0, 0.0, self.size / 2 - image.shape[1] / 2],
                             [0.0, 1.0, self.size / 2 - image.shape[0] / 2]])
            return Match(pose, -1, 0, 1.0, 1.0)

        candidates: list[Match] = []
        for index, reference in enumerate(self.tiles):
            result = self._relative_pose(image, reference)
            if result is not None:
                pose, inliers = result
                correlation, new_fraction = self._measure(image, pose)
                if ((inliers >= 12 and correlation >= 0.5) or
                        (inliers >= 8 and correlation >= 0.75)):
                    candidates.append(Match(pose, index, inliers, correlation, new_fraction, "SIFT"))
        if any(item.inliers >= 12 and item.correlation >= 0.5 for item in candidates):
            return max(candidates, key=lambda item: (item.correlation, item.inliers))
        for index in range(max(0, len(self.tiles) - 2), len(self.tiles)):
            pose = self._translation_pose(image, self.tiles[index])
            if pose is not None:
                correlation, new_fraction = self._measure(image, pose)
                if correlation >= 0.80:
                    candidates.append(Match(pose, index, 0, correlation, new_fraction, "translation"))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.correlation, item.inliers))

    def add(self, image: np.ndarray, match: Match) -> None:
        pixels, weight = self._warp(image, match.pose)
        self._sum += pixels * weight
        self._weight += weight
        self.tiles.append(Tile(image.copy(), match.pose.copy()))

    def render(self) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        covered = self.covered
        ys, xs = np.nonzero(covered)
        if not len(xs):
            raise ValueError("no tiles have been added")
        left, top, right, bottom = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        gray = np.zeros((self.size, self.size), np.uint8)
        gray[covered] = np.clip(
            np.rint(self._sum[covered] / self._weight[covered]), 0, 255
        ).astype(np.uint8)
        rgba = np.dstack((gray, gray, gray, covered.astype(np.uint8) * 255))
        return rgba[top:bottom, left:right], (left, top, right, bottom)

    def rebuild_without_last(self) -> None:
        if len(self.tiles) <= 1:
            return
        kept = self.tiles[:-1]
        self.tiles = []
        self._sum.fill(0)
        self._weight.fill(0)
        for tile in kept:
            self.add(tile.image, Match(tile.pose, -1, 0, 0, 0))
