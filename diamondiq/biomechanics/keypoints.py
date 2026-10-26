"""Pose sequences: 3D body keypoints over time.

Internal convention (meters): x = horizontal in the image plane, y = up,
z = depth. The ground plane is x-z. Any pose source (MediaPipe, a markerless
lab system such as KinaTrax, or hand-labelled data) is converted into a
``PoseSequence`` before analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# MediaPipe Pose 33-landmark topology.
LANDMARKS = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_pinky", "right_pinky", "left_index", "right_index",
    "left_thumb", "right_thumb", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
]
INDEX = {name: i for i, name in enumerate(LANDMARKS)}


@dataclass
class PoseSequence:
    points: np.ndarray  # (T, 33, 3) meters, NaN where missing
    fps: float
    visibility: np.ndarray | None = None  # (T, 33) in [0, 1]
    source: str = "unknown"

    def __post_init__(self):
        self.points = np.asarray(self.points, dtype=float)
        if self.points.ndim != 3 or self.points.shape[1:] != (len(LANDMARKS), 3):
            raise ValueError(f"expected (T, {len(LANDMARKS)}, 3) array, got {self.points.shape}")
        if self.visibility is None:
            self.visibility = np.where(np.isnan(self.points[..., 0]), 0.0, 1.0)

    @property
    def n_frames(self) -> int:
        return self.points.shape[0]

    @property
    def dt(self) -> float:
        return 1.0 / self.fps

    def joint(self, name: str) -> np.ndarray:
        return self.points[:, INDEX[name], :]

    def mid(self, a: str, b: str) -> np.ndarray:
        return (self.joint(a) + self.joint(b)) / 2

    def side(self, side: str, part: str) -> np.ndarray:
        """side: 'left' | 'right'; part: 'shoulder', 'hip', ..."""
        return self.joint(f"{side}_{part}")

    def body_height(self) -> float:
        """Estimate standing height (m) from the tallest early-motion frames."""
        head = self.joint("nose")
        feet = self.mid("left_ankle", "right_ankle")
        n = max(5, self.n_frames // 5)
        h = head[:n, 1] - feet[:n, 1]
        h = h[~np.isnan(h)]
        # Nose sits roughly 0.93 of standing height; ankles ~0.04 above floor.
        return float(np.nanmax(h) / 0.89) if h.size else float("nan")

    def cleaned(self, min_visibility: float = 0.3, window: int = 5) -> PoseSequence:
        """Mask low-confidence points, interpolate gaps, and smooth each coordinate."""
        pts = self.points.copy()
        pts[self.visibility < min_visibility] = np.nan
        t = np.arange(self.n_frames)
        for j in range(pts.shape[1]):
            for c in range(3):
                y = pts[:, j, c]
                ok = ~np.isnan(y)
                if ok.sum() >= 2:
                    pts[:, j, c] = np.interp(t, t[ok], y[ok])
        pts = smooth(pts, window)
        return PoseSequence(pts, self.fps, np.ones(pts.shape[:2]), self.source)

    def to_json(self) -> dict[str, Any]:
        return {"fps": self.fps, "source": self.source, "landmarks": LANDMARKS, "points": np.round(self.points, 4).tolist()}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PoseSequence:
        """Accept either a dense (T, 33, 3|4) list or per-frame dicts of named joints.

        Named-joint form: {"fps": 240, "frames": [{"left_hip": [x, y, z], ...}, ...], "y_up": true}
        """
        fps = float(data.get("fps", 30))
        if "points" in data:
            arr = np.asarray(data["points"], dtype=float)
            vis = arr[..., 3] if arr.shape[-1] == 4 else None
            pts = arr[..., :3]
        else:
            frames = data["frames"]
            pts = np.full((len(frames), len(LANDMARKS), 3), np.nan)
            for i, frame in enumerate(frames):
                for name, xyz in frame.items():
                    if name in INDEX and xyz is not None:
                        pts[i, INDEX[name]] = xyz[:3]
            vis = None
        if not data.get("y_up", True):
            pts = pts.copy()
            pts[..., 1] *= -1
        return cls(pts, fps, vis, data.get("source", "import"))


def smooth(arr: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average along axis 0 with edge padding."""
    if window <= 1 or arr.shape[0] < window:
        return arr
    pad = window // 2
    padded = np.pad(arr, [(pad, pad)] + [(0, 0)] * (arr.ndim - 1), mode="edge")
    kernel = np.ones(window) / window
    return np.apply_along_axis(lambda v: np.convolve(v, kernel, mode="valid"), 0, padded)
