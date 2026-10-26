from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

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


@app.get("/health", tags=["reference"])
def health():
    return {"status": "ok", "version": __version__}
