from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..db import init_db
from .routers import games, players, projections, reference, scouting, stats, tracking, video


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
    app.include_router(r)


# Mobile web app (players, scouting, mechanics, projections, live pitch charting).
app.mount("/app", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="app")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")


@app.get("/health", tags=["reference"])
def health():
    return {"status": "ok", "version": __version__}
