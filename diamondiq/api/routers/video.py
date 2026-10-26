from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ... import models as m
from ...biomechanics.keypoints import PoseSequence
from ...biomechanics.pipeline import analyze_sequence, analyze_video
from ...config import settings
from ...db import SessionLocal
from ..deps import SessionDep, get_player_or_404

router = APIRouter(tags=["video & biomechanics"])


def _handedness(player: m.Player, motion_type: str) -> str:
    if motion_type == "pitching":
        return player.throws or "R"
    return "L" if player.bats == "L" else "R"


def _store(analysis: m.VideoAnalysis, result: dict) -> None:
    fb = result["feedback"]
    analysis.status = "done"
    analysis.fps = result["fps"]
    analysis.phases = result["phases"]
    analysis.metrics = result["metrics"]
    analysis.feedback = fb["items"]
    analysis.scores = {
        "mechanics_score": fb["mechanics_score"],
        "level_band": fb["level_band"],
        "top_priorities": [i["label"] for i in fb["top_priorities"]],
        "strengths": fb["strengths"],
        "warnings": result["warnings"],
        **({"arm_stress": fb["arm_stress"]["level"], "arm_stress_detail": fb["arm_stress"]} if "arm_stress" in fb else {}),
    }


def _run_video_job(analysis_id: int, handedness: str, height_in: float | None, level: str | None) -> None:
    session = SessionLocal()
    try:
        a = session.get(m.VideoAnalysis, analysis_id)
        a.status = "processing"
        session.commit()
        try:
            _store(a, analyze_video(a.video_path, a.motion_type, handedness, height_in, level))
        except Exception as e:  # report failures on the record instead of losing them in a worker
            a.status, a.error = "failed", f"{type(e).__name__}: {e}"
        session.commit()
    finally:
        session.close()


@router.post("/players/{player_id}/videos", status_code=202)
async def upload_video(background: BackgroundTasks, file: UploadFile = File(...), motion_type: str = Form(...),
                       camera_view: str | None = Form(None), recorded_on: dt.date | None = Form(None),
                       player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    """Upload a pitching or hitting video. Analysis runs in the background; poll GET /analyses/{id}.

    Best results: 120-240 fps, full body in frame, camera perpendicular to the
    throwing/hitting direction (open-side view), one athlete in frame.
    """
    if motion_type not in ("pitching", "hitting"):
        raise HTTPException(422, "motion_type must be pitching or hitting")
    dest_dir = settings.media_dir / "videos" / str(player.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    a = m.VideoAnalysis(player_id=player.id, motion_type=motion_type, camera_view=camera_view, video_path=str(dest), recorded_on=recorded_on)
    session.add(a)
    session.commit()
    background.add_task(_run_video_job, a.id, _handedness(player, motion_type), player.height_in, player.current_level)
    return {"analysis_id": a.id, "status": a.status}


@router.post("/players/{player_id}/keypoints", status_code=201)
async def upload_keypoints(file: UploadFile = File(...), motion_type: str = Form(...), recorded_on: dt.date | None = Form(None),
                           player: m.Player = Depends(get_player_or_404), session: Session = SessionDep):
    """Analyze pose data from another system (lab markerless capture, KinaTrax-style exports, etc.). See PoseSequence.from_json."""
    try:
        seq = PoseSequence.from_json(json.loads(await file.read()))
        result = analyze_sequence(seq, motion_type, _handedness(player, motion_type), player.height_in, player.current_level)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, f"invalid keypoint data: {e}") from e
    a = m.VideoAnalysis(player_id=player.id, motion_type=motion_type, recorded_on=recorded_on, camera_view="keypoints")
    _store(a, result)
    session.add(a)
    session.commit()
    return _analysis_out(a)


def _analysis_out(a: m.VideoAnalysis) -> dict:
    return {
        "id": a.id, "player_id": a.player_id, "motion_type": a.motion_type, "status": a.status, "error": a.error,
        "recorded_on": a.recorded_on, "fps": a.fps, "phases": a.phases, "metrics": a.metrics, "scores": a.scores, "feedback": a.feedback,
    }


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: int, session: Session = SessionDep):
    a = session.get(m.VideoAnalysis, analysis_id)
    if not a:
        raise HTTPException(404, "analysis not found")
    return _analysis_out(a)


@router.get("/players/{player_id}/analyses")
def list_analyses(motion_type: str | None = None, player: m.Player = Depends(get_player_or_404)):
    rows = [a for a in player.video_analyses if motion_type is None or a.motion_type == motion_type]
    return [{"id": a.id, "motion_type": a.motion_type, "status": a.status, "recorded_on": a.recorded_on, "scores": a.scores}
            for a in sorted(rows, key=lambda a: a.created_at, reverse=True)]


@router.get("/analyses/{analysis_id}/compare/{other_id}")
def compare(analysis_id: int, other_id: int, session: Session = SessionDep):
    """Metric-by-metric change between two analyses (e.g. before/after a training block)."""
    a, b = session.get(m.VideoAnalysis, analysis_id), session.get(m.VideoAnalysis, other_id)
    if not a or not b:
        raise HTTPException(404, "analysis not found")
    if a.motion_type != b.motion_type:
        raise HTTPException(422, "analyses are different motion types")
    status_a = {i["metric"]: i["status"] for i in a.feedback or []}
    status_b = {i["metric"]: i["status"] for i in b.feedback or []}
    changes = {}
    for k, va in (a.metrics or {}).items():
        vb = (b.metrics or {}).get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
            changes[k] = {"before": va, "after": vb, "change": round(vb - va, 2), "status_before": status_a.get(k), "status_after": status_b.get(k)}
    return {
        "mechanics_score": {"before": a.scores.get("mechanics_score"), "after": b.scores.get("mechanics_score")},
        "metrics": changes,
        "improved": [k for k, c in changes.items() if c["status_before"] in ("watch", "flag") and c["status_after"] == "optimal"],
        "regressed": [k for k, c in changes.items() if c["status_before"] == "optimal" and c["status_after"] in ("watch", "flag")],
    }
