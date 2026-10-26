from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models as m
from ... import schemas as s
from ...scouting import GRADE_LABELS, HITTER_TOOLS, PITCHER_TOOLS, consensus, suggested_ofp
from ..deps import SessionDep, get_player_or_404

router = APIRouter(tags=["scouting"])


@router.get("/scouting/scale")
def scouting_scale():
    return {"grades": [{"grade": g, "label": label} for g, label in GRADE_LABELS], "hitter_tools": HITTER_TOOLS, "pitcher_tools": PITCHER_TOOLS}


@router.post("/players/{player_id}/scouting-reports", response_model=s.ScoutingReportOut, status_code=201)
def create_report(body: s.ScoutingReportIn, player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    data = body.model_dump()
    if data.get("ofp") is None:
        data["ofp"] = suggested_ofp(body.report_type, body.tool_grades)
    report = m.ScoutingReport(player_id=player.id, **data)
    session.add(report)
    session.commit()
    return report


@router.get("/players/{player_id}/scouting-reports", response_model=list[s.ScoutingReportOut])
def list_reports(player: m.Player = Depends(get_player_or_404)):
    return sorted(player.scouting_reports, key=lambda r: r.report_date, reverse=True)


@router.get("/players/{player_id}/scouting-consensus")
def report_consensus(report_type: str | None = None, player: m.Player = Depends(get_player_or_404)):
    reports = [r for r in player.scouting_reports if report_type is None or r.report_type == report_type]
    if not reports:
        raise HTTPException(404, "no scouting reports")
    return consensus(reports)


@router.delete("/scouting-reports/{report_id}", status_code=204)
def delete_report(report_id: int, session: Session = SessionDep):
    r = session.get(m.ScoutingReport, report_id)
    if not r:
        raise HTTPException(404, "report not found")
    session.delete(r)
    session.commit()
