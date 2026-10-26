"""End-to-end: video or keypoints -> metrics -> feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .feedback import build_feedback
from .hitting import analyze_hitting
from .keypoints import PoseSequence
from .pitching import analyze_pitching
from .pose import MediaPipeExtractor, PoseExtractor


def analyze_sequence(seq: PoseSequence, motion_type: str, handedness: str = "R", height_in: float | None = None,
                     level_code: str | None = None) -> dict[str, Any]:
    height_m = height_in * 0.0254 if height_in else None
    if motion_type == "pitching":
        result = analyze_pitching(seq, throws=handedness, height_m=height_m)
    elif motion_type == "hitting":
        result = analyze_hitting(seq, bats=handedness, height_m=height_m)
    else:
        raise ValueError("motion_type must be 'pitching' or 'hitting'")
    fb = build_feedback(motion_type, result.metrics, level_code=level_code, fps=seq.fps)
    return {**result.to_dict(), "fps": seq.fps, "feedback": fb}


def analyze_video(video_path: str | Path, motion_type: str, handedness: str = "R", height_in: float | None = None,
                  level_code: str | None = None, extractor: PoseExtractor | None = None) -> dict[str, Any]:
    seq = (extractor or MediaPipeExtractor()).extract(video_path)
    if seq.n_frames < 10:
        raise ValueError("Video too short or no athlete detected.")
    return analyze_sequence(seq, motion_type, handedness, height_in, level_code)
