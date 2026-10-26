"""Video -> PoseSequence using MediaPipe Pose Landmarker.

The extractor is behind a small interface so a different backend (a lab
markerless system, a higher-accuracy model, or a cloud service) can be
swapped in by implementing ``PoseExtractor.extract``.

Download the model once:  python -m diamondiq.biomechanics.pose --download
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path
from typing import Protocol

import numpy as np

from ..config import settings
from .keypoints import LANDMARKS, PoseSequence

MODEL_URLS = {
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
}


class PoseExtractor(Protocol):
    def extract(self, video_path: str | Path) -> PoseSequence: ...


def download_model(variant: str = "heavy", dest: Path | None = None) -> Path:
    dest = dest or settings.pose_model_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MODEL_URLS[variant], dest)
    return dest


class MediaPipeExtractor:
    """Runs MediaPipe Pose Landmarker frame by frame (VIDEO mode, temporal tracking).

    MediaPipe world landmarks are 3D in meters but centered on the hips every
    frame, which hides whole-body travel (stride, head drift). We restore it by
    adding the hip-center translation measured in the image, scaled to meters
    with the body's apparent size.
    """

    def __init__(self, model_path: str | Path | None = None, min_confidence: float = 0.5):
        self.model_path = Path(model_path or settings.pose_model_path)
        self.min_confidence = min_confidence

    def extract(self, video_path: str | Path) -> PoseSequence:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        if not self.model_path.exists():
            raise FileNotFoundError(f"Pose model not found at {self.model_path}. Run: python -m diamondiq.biomechanics.pose --download")

        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=self.min_confidence,
            min_tracking_confidence=self.min_confidence,
        )
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
        world, image, vis = [], [], []
        n = len(LANDMARKS)
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(i * 1000 / fps))
                if result.pose_world_landmarks:
                    w = result.pose_world_landmarks[0]
                    im = result.pose_landmarks[0]
                    world.append([[p.x, -p.y, p.z] for p in w])
                    image.append([[p.x * width, -p.y * height] for p in im])
                    vis.append([p.visibility for p in w])
                else:
                    world.append([[np.nan] * 3] * n)
                    image.append([[np.nan] * 2] * n)
                    vis.append([0.0] * n)
                i += 1
        cap.release()
        world_a, image_a = np.array(world, dtype=float), np.array(image, dtype=float)
        detected = ~np.isnan(world_a[:, 0, 0]) if len(world_a) else np.array([], dtype=bool)
        if detected.sum() < max(10, 0.3 * len(world_a)):
            raise ValueError(
                f"Athlete detected in only {int(detected.sum())} of {len(world_a)} frames. Use a clip with the full body in frame, "
                "good lighting, and one athlete in view."
            )
        return PoseSequence(_restore_translation(world_a, image_a), float(fps), np.array(vis, dtype=float), source="mediapipe")


def _restore_translation(world: np.ndarray, image: np.ndarray) -> np.ndarray:
    """Add per-frame hip-center travel (from image pixels) to hip-centered world landmarks."""
    lh, rh, ls, rs = (LANDMARKS.index(n) for n in ("left_hip", "right_hip", "left_shoulder", "right_shoulder"))
    torso_world = np.linalg.norm((world[:, ls] + world[:, rs]) / 2 - (world[:, lh] + world[:, rh]) / 2, axis=-1)
    torso_img = np.linalg.norm((image[:, ls] + image[:, rs]) / 2 - (image[:, lh] + image[:, rh]) / 2, axis=-1)
    m_per_px = np.nanmedian(torso_world / torso_img)
    hip_img = (image[:, lh] + image[:, rh]) / 2
    shift = (hip_img - np.nanmedian(hip_img[: max(3, len(hip_img) // 10)], axis=0)) * m_per_px
    out = world.copy()
    out[..., 0] += shift[:, None, 0]
    out[..., 1] += shift[:, None, 1]
    # Put the lowest foot near y = 0 so heights are measured from the ground.
    feet = [LANDMARKS.index(n) for n in ("left_ankle", "right_ankle", "left_heel", "right_heel")]
    out[..., 1] -= np.nanmin(out[:, feet, 1])
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MediaPipe pose model utilities")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--variant", default="heavy", choices=sorted(MODEL_URLS))
    args = parser.parse_args()
    if args.download:
        print(f"Saved model to {download_model(args.variant)}")
