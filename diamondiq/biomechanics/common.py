"""Shared helpers for pitching and hitting analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .keypoints import PoseSequence
from .kinematics import UP, derivative, horizontal, unit


@dataclass
class MotionResult:
    motion_type: str
    phases: dict[str, int]
    phase_times_s: dict[str, float]
    metrics: dict[str, float | bool | str | None]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "motion_type": self.motion_type,
            "phases": self.phases,
            "phase_times_s": self.phase_times_s,
            "metrics": self.metrics,
            "warnings": self.warnings,
        }


def other(side: str) -> str:
    return "left" if side == "right" else "right"


def rnd(x, n=1):
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    x = float(x)
    return None if np.isnan(x) else round(x, n)


def scale_factor(seq: PoseSequence, height_m: float | None) -> tuple[float, float]:
    """(estimated height in sequence units, multiplier to convert sequence units to meters)."""
    h_est = seq.body_height()
    if height_m and h_est and not np.isnan(h_est):
        return h_est, height_m / h_est
    return h_est, 1.0


def ground_height(y: np.ndarray, start: int) -> float:
    return float(np.nanmin(y[start:])) if y[start:].size else float(np.nanmin(y))


def landing_frame(ankle: np.ndarray, fps: float, after: int, before: int, height: float) -> int:
    """First frame after ``after`` where the ankle is down and nearly stopped."""
    y = ankle[:, 1]
    ground = ground_height(y, after)
    hspeed = np.linalg.norm(horizontal(derivative(ankle, fps)), axis=-1)
    window = range(after + 1, max(after + 2, before))
    max_h = np.nanmax(hspeed[after:before]) if before > after else np.nanmax(hspeed)
    down = [i for i in window if y[i] <= ground + 0.04 * height]
    for i in down:
        if hspeed[i] <= 0.25 * max_h:
            return i
    return down[0] if down else max(after + 1, before - 1)


def fps_warnings(fps: float) -> list[str]:
    if fps < 60:
        return [f"Video is {fps:.0f} fps. Phase timing and segment speeds are unreliable below 60 fps; 120-240 fps is recommended."]
    if fps < 120:
        return [f"Video is {fps:.0f} fps. Peak angular velocities will be underestimated; 120+ fps recommended for sequencing."]
    return []


def forward_direction(back_ankle: np.ndarray, front_ankle: np.ndarray, frame: int) -> np.ndarray:
    d = unit(horizontal(front_ankle[frame] - back_ankle[frame]))
    return d


def lateral_axis(forward: np.ndarray, toward_point: np.ndarray, from_point: np.ndarray) -> np.ndarray:
    """Horizontal unit vector perpendicular to ``forward`` pointing from ``from_point`` toward ``toward_point``."""
    v = horizontal(toward_point - from_point)
    v = v - (v @ forward) * forward
    if np.linalg.norm(v) < 1e-6:
        v = np.cross(forward, UP)
    return unit(v)
