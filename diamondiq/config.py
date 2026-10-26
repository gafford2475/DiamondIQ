from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DIAMONDIQ_DATABASE_URL", "sqlite:///./diamondiq.db")
    media_dir: Path = Path(os.getenv("DIAMONDIQ_MEDIA_DIR", "./media"))
    # MediaPipe Pose Landmarker model (.task). Download with `python -m diamondiq.biomechanics.pose --download`.
    pose_model_path: Path = Path(os.getenv("DIAMONDIQ_POSE_MODEL", "./models/pose_landmarker_heavy.task"))
    projection_simulations: int = int(os.getenv("DIAMONDIQ_PROJECTION_SIMS", "2000"))


settings = Settings()
