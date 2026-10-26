"""OpenCV image-motion validation, independent of pose inference.

Track patches at six pose locations forward and backward between raw frames.
Poor optical flow is unknown evidence, not proof that the person stopped moving.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class MotionCheck:
    status: str = 'unavailable'  # unavailable, consistent, inconsistent
    tracked: int = 0
    displacement_px: float = 0.0
    disagreement_px: float = 0.0


class LandmarkMotion:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None

    def update(self, frame, metrics, now, side):
        """Consume unannotated BGR pixels and pixel-space Metrics; never alter them."""
        if metrics is None:
            self.reset()
            return MotionCheck()
        points = np.asarray(metrics.points, dtype=np.float32)
        if points.shape != (6, 2) or not np.isfinite(points).all():
            self.reset()
            return MotionCheck()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        previous = self.previous
        # Re-seed from measured landmarks every frame: no accumulated LK drift.
        self.previous = (gray, points.copy(), now, side, metrics.scale)
        if previous is None:
            return MotionCheck()
        old_gray, old_points, old_time, old_side, old_scale = previous
        if (gray.shape != old_gray.shape or side != old_side
                or not 0 < now-old_time <= .25):
            return MotionCheck()
        params = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01),
                      minEigThreshold=1e-4)
        starts = old_points.reshape(-1, 1, 2)
        try:
            forward, status, error = cv2.calcOpticalFlowPyrLK(old_gray, gray, starts, None, **params)
            if forward is None or status is None or error is None:
                return MotionCheck()
            finite = np.isfinite(forward).all(axis=(1, 2))
            # Never feed NaN/Inf from a failed forward track into the reverse pass.
            reverse_starts = forward.copy()
            reverse_starts[~finite] = starts[~finite]
            backward, reverse_status, _ = cv2.calcOpticalFlowPyrLK(
                gray, old_gray, reverse_starts, None, **params)
            if backward is None or reverse_status is None:
                return MotionCheck()
        except cv2.error:
            # Unsupported/failed frame pair must not take down the camera app.
            return MotionCheck()
        predicted = forward.reshape(-1, 2)
        returned = backward.reshape(-1, 2)
        height, width = gray.shape
        valid = ((status.ravel() == 1) & (reverse_status.ravel() == 1) & finite
                 & np.isfinite(returned).all(axis=1) & np.isfinite(error.ravel())
                 & (error.ravel() <= 20)
                 & (np.linalg.norm(returned-old_points, axis=1) <= 1.5)
                 & (predicted[:, 0] >= 0) & (predicted[:, 0] < width)
                 & (predicted[:, 1] >= 0) & (predicted[:, 1] < height))
        count = int(valid.sum())
        # Require several locations AND a hip/knee track; feet alone cannot
        # validate the body motion driving squat state transitions.
        if count < 3 or not (valid[1] or valid[2]):
            return MotionCheck(tracked=count)
        residual = np.linalg.norm(predicted-points, axis=1)
        tolerance = max(8.0, .12*old_scale)
        disagrees = valid & (residual > tolerance)
        # Two noisy patches must not veto four agreeing ones. Require a strict
        # majority of reliable tracks, still including hip/knee and at least two.
        inconsistent = int(disagrees.sum()) > count/2 and (disagrees[1] or disagrees[2])
        result = MotionCheck('inconsistent' if inconsistent else 'consistent', count,
                             float(np.median(np.linalg.norm(predicted-old_points, axis=1)[valid])),
                             float(np.median(residual[valid])))
        if inconsistent:
            self.reset()
        return result
