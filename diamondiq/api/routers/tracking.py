from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import models as m
from ...integrations import ADAPTERS
from ...services import import_tracking, tracking_summary
from ..deps import SessionDep, get_player_or_404

router = APIRouter(tags=["integrations & tracking"])


@router.get("/integrations")
def list_integrations():
    return [{"name": name, "description": cls.description, "signature_columns": list(cls.signature)} for name, cls in ADAPTERS.items()]


@router.post("/integrations/import")
async def import_file(file: UploadFile = File(...), source: str | None = Form(None, description="omit to auto-detect"),
                      player_id: int | None = Form(None), level: str | None = Form(None), session_label: str | None = Form(None),
                      options: str | None = Form(None, description="JSON, e.g. a column_map for the generic adapter"),
                      session: Session = SessionDep):
    opts = json.loads(options) if options else {}
    if session_label:
        opts["session_label"] = session_label
    try:
        batch = import_tracking(session, await file.read(), source=source, filename=file.filename, player_id=player_id, level=level, options=opts)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    return {"batch_id": batch.id, "source": batch.source, "events": batch.row_count, "matched": batch.matched_count, "unmatched_names": batch.unmatched_names}


@router.post("/integrations/batches/{batch_id}/assign")
def assign_unmatched(batch_id: int, name: str, player_id: int, session: Session = SessionDep):
    """Link events from an unmatched name in an import to a player (and remember the mapping is by name)."""
    events = list(session.scalars(select(m.TrackingEvent).where(m.TrackingEvent.batch_id == batch_id, m.TrackingEvent.player_id.is_(None),
                                                                 m.TrackingEvent.player_name_raw == name)))
    for e in events:
        e.player_id = player_id
    session.commit()
    return {"assigned": len(events)}


@router.get("/players/{player_id}/tracking")
def player_tracking(player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    return tracking_summary(session, player.id)


@router.get("/players/{player_id}/tracking/events")
def player_tracking_events(event_type: str | None = None, source: str | None = None, limit: int = 500,
                           player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    q = select(m.TrackingEvent).where(m.TrackingEvent.player_id == player.id)
    if event_type:
        q = q.where(m.TrackingEvent.event_type == event_type)
    if source:
        q = q.where(m.TrackingEvent.source == source)
    cols = [c.name for c in m.TrackingEvent.__table__.columns if c.name != "raw"]
    return [{c: getattr(e, c) for c in cols} for e in session.scalars(q.order_by(m.TrackingEvent.occurred_at.desc()).limit(limit))]
