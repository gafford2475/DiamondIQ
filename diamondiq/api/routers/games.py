from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ... import models as m
from ... import schemas as s
from ...services import game_summary, pitcher_line
from ..deps import SessionDep, get_game_or_404, get_player_or_404

router = APIRouter(tags=["games & pitch charting"])


@router.post("/games", response_model=s.GameOut, status_code=201)
def create_game(body: s.GameIn, session: Session = SessionDep):
    game = m.Game(**body.model_dump())
    session.add(game)
    session.commit()
    return game


@router.get("/games", response_model=list[s.GameOut])
def list_games(start: dt.date | None = None, end: dt.date | None = None, team: str | None = None, scout: str | None = None,
               session: Session = SessionDep):
    q = select(m.Game)
    if start:
        q = q.where(m.Game.game_date >= start)
    if end:
        q = q.where(m.Game.game_date <= end)
    if team:
        q = q.where(or_(m.Game.home_team.ilike(f"%{team}%"), m.Game.away_team.ilike(f"%{team}%")))
    if scout:
        q = q.where(m.Game.scout_name == scout)
    return list(session.scalars(q.order_by(m.Game.game_date.desc())))


@router.post("/games/{game_id}/pitches", response_model=s.GamePitchOut, status_code=201)
def log_pitch(body: s.GamePitchIn, game: m.Game = Depends(get_game_or_404), session: Session = SessionDep):
    data = body.model_dump()
    for role in ("pitcher", "batter"):
        pid = data.get(f"{role}_id")
        if pid and not data.get(f"{role}_name"):
            p = session.get(m.Player, pid)
            if not p:
                raise HTTPException(404, f"{role} {pid} not found")
            data[f"{role}_name"] = p.full_name
    if data.get("pitch_type"):
        from ...integrations.base import normalize_pitch_type

        data["pitch_type"] = normalize_pitch_type(data["pitch_type"])
    pitch = m.GamePitch(game_id=game.id, sequence=len(game.pitches) + 1, **data)
    session.add(pitch)
    session.commit()
    return pitch


@router.delete("/games/{game_id}/pitches/last", status_code=204)
def undo_last_pitch(game: m.Game = Depends(get_game_or_404), session: Session = SessionDep):
    if game.pitches:
        session.delete(game.pitches[-1])
        session.commit()


@router.get("/games/{game_id}/pitches", response_model=list[s.GamePitchOut])
def list_pitches(game: m.Game = Depends(get_game_or_404)):
    return game.pitches


@router.post("/games/{game_id}/notes", status_code=201)
def add_note(body: s.GameNoteIn, game: m.Game = Depends(get_game_or_404), session: Session = SessionDep):
    note = m.GameNote(game_id=game.id, **body.model_dump())
    session.add(note)
    session.commit()
    return {"id": note.id}


@router.get("/games/{game_id}/summary")
def summary(game: m.Game = Depends(get_game_or_404)):
    out = game_summary(game)
    out["notes"] = [{"inning": n.inning, "player_id": n.player_id, "category": n.category, "text": n.text} for n in game.notes_log]
    return out


@router.get("/players/{player_id}/charted-pitching")
def charted_pitching(player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    """Per-game and season-to-date lines from every game a scout charted this pitcher."""
    pitches = list(session.scalars(select(m.GamePitch).where(m.GamePitch.pitcher_id == player.id)))
    by_game: dict[int, list[m.GamePitch]] = {}
    for p in pitches:
        by_game.setdefault(p.game_id, []).append(p)
    games = {g.id: g for g in session.scalars(select(m.Game).where(m.Game.id.in_(by_game)))}
    return {
        "overall": pitcher_line(pitches) if pitches else None,
        "games": [{"game_id": gid, "date": games[gid].game_date, "matchup": f"{games[gid].away_team} @ {games[gid].home_team}", **pitcher_line(ps)}
                  for gid, ps in sorted(by_game.items(), key=lambda kv: games[kv[0]].game_date)],
    }
