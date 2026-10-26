from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _database_url() -> str:
    url = os.getenv("DIAMONDIQ_DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///./diamondiq.db"
    # Hosts (Render, Heroku, Railway) hand out postgres:// URLs; SQLAlchemy needs the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str = _database_url()
    media_dir: Path = Path(os.getenv("DIAMONDIQ_MEDIA_DIR", "./media"))
    # MediaPipe Pose Landmarker model (.task). Download with `python -m diamondiq.biomechanics.pose --download`.
    pose_model_path: Path = Path(os.getenv("DIAMONDIQ_POSE_MODEL", "./models/pose_landmarker_heavy.task"))
    projection_simulations: int = int(os.getenv("DIAMONDIQ_PROJECTION_SIMS", "2000"))
    # Auth. Set secure cookies whenever the site is served over HTTPS (any real deployment).
    secure_cookies: bool = _flag("DIAMONDIQ_SECURE_COOKIES")
    session_days: int = int(os.getenv("DIAMONDIQ_SESSION_DAYS", "30"))
    # First admin, created at startup only if the database has no users yet.
    admin_email: str | None = os.getenv("DIAMONDIQ_ADMIN_EMAIL")
    admin_password: str | None = os.getenv("DIAMONDIQ_ADMIN_PASSWORD")


settings = Settings()
