"""Geometry and kinematics primitives on (T, 3) joint trajectories."""

from __future__ import annotations

import numpy as np

UP = np.array([0.0, 1.0, 0.0])


def joint_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Interior angle ABC in degrees for each frame."""
    v1, v2 = a - b, c - b
    cos = np.sum(v1 * v2, axis=-1) / (np.linalg.norm(v1, axis=-1) * np.linalg.norm(v2, axis=-1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def flexion(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Flexion = 180 - interior angle (0 = straight limb)."""
    return 180.0 - joint_angle(a, b, c)


def horizontal(v: np.ndarray) -> np.ndarray:
    out = np.array(v, dtype=float, copy=True)
    out[..., 1] = 0.0
    return out


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def yaw(v: np.ndarray) -> np.ndarray:
    """Heading (deg) of a vector projected on the ground plane, unwrapped over time."""
    ang = np.arctan2(v[..., 2], v[..., 0])
    return np.degrees(np.unwrap(ang)) if ang.ndim else np.degrees(ang)


def wrap180(a):
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


def derivative(x: np.ndarray, fps: float) -> np.ndarray:
    return np.gradient(x, 1.0 / fps, axis=0)


def speed(p: np.ndarray, fps: float) -> np.ndarray:
    return np.linalg.norm(derivative(p, fps), axis=-1)


def tilt_components(bottom: np.ndarray, top: np.ndarray, forward: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Forward and lateral tilt (deg) of the segment bottom->top relative to vertical.

    ``forward`` is the horizontal unit direction of the throw/pitch. Positive
    forward tilt leans toward the target; lateral tilt is signed with the
    right-hand side of ``forward`` (callers flip sign by handedness).
    """
    seg = top - bottom
    right = np.cross(forward, UP)
    fwd_c = seg @ forward
    lat_c = seg @ right
    up_c = seg @ UP
    return np.degrees(np.arctan2(fwd_c, up_c)), np.degrees(np.arctan2(lat_c, up_c))


def peak_index(x: np.ndarray, start: int = 0, end: int | None = None, mode: str = "max") -> int:
    seg = x[start:end]
    if seg.size == 0 or np.all(np.isnan(seg)):
        return start
    return start + int(np.nanargmax(seg) if mode == "max" else np.nanargmin(seg))


def segment_rotation(back: np.ndarray, front: np.ndarray, forward: np.ndarray, rising_between: tuple[int, int]) -> np.ndarray:
    """Rotation (deg) of a body segment line (back joint -> front joint) about vertical.

    0 means the line points at the target (fully closed); values grow as the
    segment opens toward the target. The sign is chosen so the angle increases
    between the two frames in ``rising_between`` (e.g. setup -> release),
    which makes it independent of handedness and camera side.
    """
    v = unit(horizontal(front - back))
    dot = v @ forward
    cross_y = np.cross(forward, v)[:, 1]
    ang = np.degrees(np.unwrap(np.arctan2(cross_y, dot)))
    a, b = rising_between
    if ang[b] < ang[a]:
        ang = -ang
    return ang - ang[a] + np.degrees(np.arctan2(abs(cross_y[a]), dot[a]))
