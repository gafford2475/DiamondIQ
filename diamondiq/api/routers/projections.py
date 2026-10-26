from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import models as m
from ... import schemas as s
from ...projection import ProjectionInput, project
from ...services import run_projection
from ..deps import SessionDep, get_player_or_404

router = APIRouter(tags=["projections"])


@router.post("/players/{player_id}/projections", status_code=201)
def create_projection(body: s.ProjectionRequest, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    """Project growth/regression year by year, most likely levels, outcome tiers, and stat lines at every level."""
    if not player.current_level:
        raise HTTPException(422, "set the player's current_level first")
    run = run_projection(session, player, **body.model_dump())
    return {"id": run.id, "created_at": run.created_at, **run.result}


@router.get("/players/{player_id}/projections")
def projection_history(player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    runs = session.scalars(select(m.ProjectionRun).where(m.ProjectionRun.player_id == player.id).order_by(m.ProjectionRun.created_at))
    return [{"id": r.id, "created_at": r.created_at, "model_version": r.model_version,
             "current_overall": r.result["current_talent"]["overall"], "peak_median": r.result["outcomes"]["peak_talent"]["median"],
             "most_likely_tier": r.result["outcomes"]["most_likely_tier"],
             "p_mlb": r.result["outcomes"]["probability_reach_pro_level"].get("MLB")} for r in runs]


@router.get("/projections/{run_id}")
def get_projection(run_id: int, session: Session = SessionDep):
    run = session.get(m.ProjectionRun, run_id)
    if not run:
        raise HTTPException(404, "projection not found")
    return {"id": run.id, "player_id": run.player_id, "created_at": run.created_at, "inputs": run.inputs, **run.result}


@router.post("/projections/what-if")
def what_if(body: s.WhatIfProjectionRequest):
    """Project from raw inputs without saving (hypothetical players, 'what if he adds 3 mph', etc.)."""
    return project(ProjectionInput(**body.model_dump()))
