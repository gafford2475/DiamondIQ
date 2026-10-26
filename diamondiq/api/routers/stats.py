from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import models as m
from ... import schemas as s
from ...levels import get_level
from ...services import find_player
from ...stats import rates
from ..deps import SessionDep, get_player_or_404

router = APIRouter(tags=["stats"])

HITTING_KEYS = ("pa", "ab", "h", "2b", "3b", "hr", "bb", "ibb", "so", "hbp", "sf", "sh", "sb", "cs", "r", "rbi", "g")
PITCHING_KEYS = ("g", "gs", "ip", "outs", "bf", "h", "r", "er", "bb", "so", "hr", "hbp", "w", "l", "sv", "gb", "fb")


def _out(line: m.StatLine) -> dict:
    d = s.StatLineOut.model_validate(line).model_dump()
    d["rates"] = rates(line.kind, line.stats)
    return d


@router.post("/players/{player_id}/stats", status_code=201)
def upsert_stat_line(body: s.StatLineIn, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    existing = session.scalars(select(m.StatLine).where(
        m.StatLine.player_id == player.id, m.StatLine.season == body.season, m.StatLine.level == body.level,
        m.StatLine.team == body.team, m.StatLine.kind == body.kind, m.StatLine.split == body.split)).first()
    if existing:
        existing.stats, existing.source = body.stats, body.source
        line = existing
    else:
        line = m.StatLine(player_id=player.id, **body.model_dump())
        session.add(line)
    session.commit()
    return _out(line)


@router.get("/players/{player_id}/stats")
def list_stats(kind: str | None = None, player: m.Player = Depends(get_player_or_404)):
    lines = [x for x in player.stat_lines if kind is None or x.kind == kind]
    return [_out(x) for x in sorted(lines, key=lambda x: (x.season, get_level(x.level).talent_mean))]


@router.post("/stats/import")
async def import_stats_csv(file: UploadFile = File(...), kind: str = Form(...), default_level: str | None = Form(None),
                           default_season: int | None = Form(None), source: str = Form("csv"), session: Session = SessionDep):
    """Bulk import season lines. Columns: player_id or first_name+last_name, season, level, team, and stat columns
    (hitting: PA AB H 2B 3B HR BB SO HBP SF SB CS / pitching: IP BF H ER BB SO HR HBP)."""
    if kind not in ("hitting", "pitching"):
        raise HTTPException(422, "kind must be hitting or pitching")
    text = (await file.read()).decode("utf-8-sig")
    keys = HITTING_KEYS if kind == "hitting" else PITCHING_KEYS
    created, unmatched = 0, []
    for row in csv.DictReader(io.StringIO(text)):
        r = {k.strip().lower(): v for k, v in row.items() if k}
        r["so"] = r.get("so") or r.get("k")
        player = session.get(m.Player, int(r["player_id"])) if r.get("player_id") else find_player(session, f"{r.get('first_name', '')} {r.get('last_name', '')}".strip() or r.get("name"))
        if not player:
            unmatched.append(r.get("name") or f"{r.get('first_name')} {r.get('last_name')}")
            continue
        stats = {k: float(r[k]) if k != "ip" else r[k] for k in keys if r.get(k) not in (None, "")}
        session.add(m.StatLine(player_id=player.id, season=int(r.get("season") or default_season), level=get_level(r.get("level") or default_level).code,
                               team=r.get("team"), kind=kind, split=r.get("split") or "overall", source=source, stats=stats))
        created += 1
    session.commit()
    return {"created": created, "unmatched": unmatched}
