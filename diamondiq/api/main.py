from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import settings
from ..auth import bootstrap_admin, prepare_setup, require_access
from ..db import SessionLocal, init_db
from .routers import auth, games, players, projections, reference, scouting, stats, tracking, video


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as session:
        bootstrap_admin(session)
        prepare_setup(session)
    yield


app = FastAPI(
    title="DiamondIQ",
    version=__version__,
    description="Player evaluation, biomechanics, scouting, tracking and projection for every level of baseball, high school through MLB.",
    lifespan=lifespan,
)
# reference is registered before projections so /projections/outcome-tiers is not captured by /projections/{run_id}.
for r in (players.router, players.watchlists, scouting.router, stats.router, games.router, tracking.router, video.router,
          reference.router, projections.router):
    # Every data endpoint requires a signed-in user; viewers are read-only.
    app.include_router(r, dependencies=[Depends(require_access)])
app.include_router(auth.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/app"):
        # The app only loads its own scripts; inline style attributes are used for layout.
        h.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                     "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if settings.secure_cookies:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# Mobile web app (players, scouting, mechanics, projections, live pitch charting).
app.mount("/app", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="app")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")


@app.get("/health", tags=["reference"])
def health():
    return {"status": "ok", "version": __version__}
