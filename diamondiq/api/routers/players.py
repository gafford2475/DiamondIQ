from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ... import models as m
from ... import schemas as s
from ...scouting import consensus
from ...services import player_seasons, tracking_summary
from ..deps import SessionDep, get_player_or_404

router = APIRouter(prefix="/players", tags=["players"])


@router.post("", response_model=s.PlayerOut, status_code=201)
def create_player(body: s.PlayerIn, session: Session = SessionDep):
    player = m.Player(**body.model_dump())
    session.add(player)
    session.commit()
    return player


@router.get("", response_model=list[s.PlayerOut])
def list_players(q: str | None = None, level: str | None = None, player_type: str | None = None, grad_year: int | None = None,
                 position: str | None = None, limit: int = 100, offset: int = 0, session: Session = SessionDep):
    stmt = select(m.Player)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(m.Player.first_name.ilike(like), m.Player.last_name.ilike(like), m.Player.current_team.ilike(like)))
    if level:
        from ...levels import get_level

        stmt = stmt.where(m.Player.current_level == get_level(level).code)
    if player_type:
        stmt = stmt.where(m.Player.player_type == player_type)
    if grad_year:
        stmt = stmt.where(m.Player.grad_year == grad_year)
    if position:
        stmt = stmt.where(m.Player.primary_position == position.upper())
    return list(session.scalars(stmt.order_by(m.Player.last_name).offset(offset).limit(limit)))


@router.get("/{player_id}", response_model=s.PlayerOut)
def get_player(player: m.Player = Depends(get_player_or_404)):
    return player


@router.patch("/{player_id}", response_model=s.PlayerOut)
def update_player(body: s.PlayerUpdate, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(player, k, v)
    session.commit()
    return player


@router.delete("/{player_id}", status_code=204)
def delete_player(player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    session.delete(player)
    session.commit()


@router.get("/{player_id}/profile")
def player_profile(player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    """Everything known about a player in one call: bio, stats, scouting consensus, tracking, mechanics, projection."""
    hitter_reports = [r for r in player.scouting_reports if r.report_type == "hitter"]
    pitcher_reports = [r for r in player.scouting_reports if r.report_type == "pitcher"]
    analyses = sorted(player.video_analyses, key=lambda a: a.created_at, reverse=True)
    latest_proj = session.scalars(
        select(m.ProjectionRun).where(m.ProjectionRun.player_id == player.id).order_by(m.ProjectionRun.created_at.desc())
    ).first()
    return {
        "player": s.PlayerOut.model_validate(player).model_dump(),
        "age": player.age_on(),
        "stats": {"hitting": player_seasons(player, "hitting"), "pitching": player_seasons(player, "pitching")},
        "scouting": {
            "hitter": consensus(hitter_reports) if hitter_reports else None,
            "pitcher": consensus(pitcher_reports) if pitcher_reports else None,
        },
        "tracking": tracking_summary(session, player.id),
        "mechanics": [
            {"id": a.id, "motion_type": a.motion_type, "recorded_on": a.recorded_on, "status": a.status, "scores": a.scores,
             "top_priorities": [i["label"] for i in (a.feedback or []) if i.get("status") == "flag"][:3]}
            for a in analyses[:10]
        ],
        "measurements": [
            {"measured_on": x.measured_on, "height_in": x.height_in, "weight_lb": x.weight_lb, "metrics": x.metrics}
            for x in sorted(player.measurements, key=lambda x: x.measured_on)
        ],
        "latest_projection": {"id": latest_proj.id, "created_at": latest_proj.created_at, "summary": latest_proj.result.get("summary"),
                              "outcomes": latest_proj.result.get("outcomes")} if latest_proj else None,
    }


@router.post("/{player_id}/measurements", status_code=201)
def add_measurement(body: s.MeasurementIn, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    meas = m.PhysicalMeasurement(player_id=player.id, **body.model_dump())
    session.add(meas)
    if body.height_in:
        player.height_in = body.height_in
    if body.weight_lb:
        player.weight_lb = body.weight_lb
    session.commit()
    return {"id": meas.id}


# ---- watchlists -------------------------------------------------------------

watchlists = APIRouter(prefix="/watchlists", tags=["watchlists"])


@watchlists.post("", status_code=201)
def create_watchlist(body: s.WatchlistIn, session: Session = SessionDep):
    wl = m.Watchlist(**body.model_dump())
    session.add(wl)
    session.commit()
    return {"id": wl.id, "name": wl.name}


@watchlists.get("")
def list_watchlists(session: Session = SessionDep):
    return [{"id": w.id, "name": w.name, "description": w.description, "player_count": len(w.players)} for w in session.scalars(select(m.Watchlist))]


@watchlists.get("/{watchlist_id}")
def get_watchlist(watchlist_id: int, session: Session = SessionDep):
    wl = session.get(m.Watchlist, watchlist_id)
    if not wl:
        raise HTTPException(404, "watchlist not found")
    return {"id": wl.id, "name": wl.name, "description": wl.description,
            "players": [s.PlayerOut.model_validate(p).model_dump() for p in wl.players]}


@watchlists.put("/{watchlist_id}/players/{player_id}", status_code=204)
def add_to_watchlist(watchlist_id: int, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    wl = session.get(m.Watchlist, watchlist_id)
    if not wl:
        raise HTTPException(404, "watchlist not found")
    if player not in wl.players:
        wl.players.append(player)
    session.commit()


@watchlists.delete("/{watchlist_id}/players/{player_id}", status_code=204)
def remove_from_watchlist(watchlist_id: int, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    wl = session.get(m.Watchlist, watchlist_id)
    if wl and player in wl.players:
        wl.players.remove(player)
        session.commit()
