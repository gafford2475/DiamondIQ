"""Database-facing operations shared by the API and scripts."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .integrations import detect_source, get_adapter
from .levels import get_level
from .projection import ProjectionInput, project
from .projection.simulate import MODEL_VERSION
from .scouting import consensus
from .stats import rates

FASTBALL_TYPES = {"FF", "SI"}
SWING_RESULTS = {"swinging_strike", "foul", "foul_tip", "in_play"}
STRIKE_RESULTS = {"called_strike", "swinging_strike", "foul", "foul_tip", "in_play"}


def in_zone(px: float | None, pz: float | None) -> bool | None:
    if px is None or pz is None:
        return None
    return abs(px) <= 0.83 and 1.5 <= pz <= 3.5


# --------------------------------------------------------------------------- players

def find_player(session: Session, name: str | None = None, source: str | None = None, external_id: str | None = None) -> m.Player | None:
    if external_id and source:
        for p in session.scalars(select(m.Player).where(m.Player.external_ids.is_not(None))):
            ids = p.external_ids or {}
            if str(ids.get(source)) == str(external_id) or str(ids.get(source.split("_")[0])) == str(external_id):
                return p
    if name:
        parts = name.replace(",", " ").split()
        if len(parts) >= 2:
            first, last = parts[0], " ".join(parts[1:])
            q = select(m.Player).where(func.lower(m.Player.first_name) == first.lower(), func.lower(m.Player.last_name) == last.lower())
            hit = session.scalars(q).first()
            if hit:
                return hit
    return None


# --------------------------------------------------------------------------- tracking imports

def import_tracking(session: Session, content: bytes, source: str | None = None, filename: str | None = None,
                    player_id: int | None = None, level: str | None = None, options: dict[str, Any] | None = None) -> m.ImportBatch:
    """Parse a device export and store normalized events.

    ``player_id`` forces every row to one player (per-athlete exports such as
    Rapsodo or Blast). Otherwise rows are matched by external id, then name.
    """
    source = source or detect_source(content)
    if not source:
        raise ValueError("Could not detect the file format; pass source explicitly (see /integrations).")
    adapter = get_adapter(source)
    events = adapter.parse(content, **(options or {}))
    batch = m.ImportBatch(source=adapter.name, filename=filename, row_count=len(events))
    session.add(batch)
    session.flush()
    forced = session.get(m.Player, player_id) if player_id else None
    cache: dict[tuple, m.Player | None] = {}
    unmatched: set[str] = set()
    matched = 0
    for ev in events:
        player = forced
        if player is None:
            key = (ev.player_external_id, ev.player_name)
            if key not in cache:
                cache[key] = find_player(session, ev.player_name, adapter.name, ev.player_external_id)
            player = cache[key]
        if player is None:
            if ev.player_name:
                unmatched.add(ev.player_name)
        else:
            matched += 1
        d = ev.to_dict()
        d.pop("player_external_id")
        name, opp = d.pop("player_name"), d.pop("opponent_name")
        d["occurred_at"] = ev.occurred_at
        session.add(m.TrackingEvent(**d, player_id=player.id if player else None, batch_id=batch.id, level=level,
                                    player_name_raw=name, opponent_name_raw=opp))
    batch.matched_count = matched
    batch.unmatched_names = sorted(unmatched)
    session.commit()
    return batch


def _arr(vals):
    a = np.array([v for v in vals if v is not None], dtype=float)
    return a


def tracking_summary(session: Session, player_id: int, since: dt.datetime | None = None) -> dict[str, Any]:
    q = select(m.TrackingEvent).where(m.TrackingEvent.player_id == player_id)
    if since:
        q = q.where(m.TrackingEvent.occurred_at >= since)
    events = list(session.scalars(q))
    pitches = [e for e in events if e.event_type == "pitch" and e.role == "pitcher"]
    batted = [e for e in events if e.event_type == "batted_ball"]
    swings = [e for e in events if e.event_type == "swing" or e.bat_speed is not None]
    out: dict[str, Any] = {"event_counts": {"pitches": len(pitches), "batted_balls": len(batted), "swings": len(swings)}, "sources": sorted({e.source for e in events})}

    if pitches:
        arsenal = {}
        by_type = defaultdict(list)
        for p in pitches:
            by_type[p.pitch_type or "UN"].append(p)
        for pt, ps in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            velo, spin, ivb, hb = _arr(p.velocity for p in ps), _arr(p.spin_rate for p in ps), _arr(p.ivb for p in ps), _arr(p.hb for p in ps)
            sw = [p for p in ps if p.pitch_result in SWING_RESULTS]
            wh = [p for p in sw if p.pitch_result == "swinging_strike"]
            arsenal[pt] = {
                "count": len(ps), "usage": round(len(ps) / len(pitches), 3),
                "velo_avg": _r(velo.mean()) if velo.size else None, "velo_max": _r(velo.max()) if velo.size else None,
                "spin_avg": _r(spin.mean(), 0) if spin.size else None,
                "ivb_avg": _r(ivb.mean()) if ivb.size else None, "hb_avg": _r(hb.mean()) if hb.size else None,
                "whiff_pct": _r(len(wh) / len(sw), 3) if sw else None,
            }
        fb = [p for p in pitches if p.pitch_type in FASTBALL_TYPES] or [p for p in pitches if p.pitch_type is None]
        fbv, fbivb = _arr(p.velocity for p in fb), _arr(p.ivb for p in fb if p.pitch_type == "FF")
        zones = [in_zone(p.plate_x, p.plate_z) for p in pitches]
        zones = [z for z in zones if z is not None]
        ext, rel_h = _arr(p.extension for p in pitches), _arr(p.release_height for p in pitches)
        out["pitching"] = {
            "arsenal": arsenal,
            "fb_velo_avg": _r(fbv.mean()) if fbv.size else None,
            "fb_velo_max": _r(fbv.max()) if fbv.size else None,
            "fb_ivb_avg": _r(fbivb.mean()) if fbivb.size else None,
            "zone_pct": _r(sum(zones) / len(zones), 3) if zones else None,
            "extension_avg": _r(ext.mean(), 2) if ext.size else None,
            "release_height_avg": _r(rel_h.mean(), 2) if rel_h.size else None,
        }
    if batted or swings:
        ev = _arr(b.exit_velocity for b in batted)
        la = _arr(b.launch_angle for b in batted if b.exit_velocity is not None)
        bs = _arr(s.bat_speed for s in swings)
        pairs = [(b.exit_velocity, b.launch_angle) for b in batted if b.exit_velocity is not None and b.launch_angle is not None]
        barrels = sum(1 for e, a in pairs if _is_barrel(e, a))
        out["hitting"] = {
            "ev_avg": _r(ev.mean()) if ev.size else None,
            "ev_90th": _r(np.percentile(ev, 90)) if ev.size >= 10 else None,
            "ev_max": _r(ev.max()) if ev.size else None,
            "hard_hit_pct": _r((ev >= 95).mean(), 3) if ev.size else None,
            "la_avg": _r(la.mean()) if la.size else None,
            "sweet_spot_pct": _r(((la >= 8) & (la <= 32)).mean(), 3) if la.size else None,
            "barrel_pct": _r(barrels / len(pairs), 3) if pairs else None,
            "bat_speed_avg": _r(bs.mean()) if bs.size else None,
            "bat_speed_max": _r(bs.max()) if bs.size else None,
            "attack_angle_avg": _r(_arr(s.attack_angle for s in swings).mean()) if any(s.attack_angle is not None for s in swings) else None,
        }
    return out


def _is_barrel(ev: float, la: float) -> bool:
    """Statcast-style barrel: 98+ mph with a launch-angle window that widens with EV."""
    if ev < 98:
        return False
    extra = ev - 98
    return max(8.0, 26 - extra) <= la <= min(50.0, 30 + 1.2 * extra)


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# --------------------------------------------------------------------------- games

def game_summary(game: m.Game) -> dict[str, Any]:
    pitchers: dict[str, list[m.GamePitch]] = defaultdict(list)
    batters: dict[str, list[m.GamePitch]] = defaultdict(list)
    for p in game.pitches:
        pitchers[p.pitcher_name or f"player:{p.pitcher_id}"].append(p)
        batters[p.batter_name or f"player:{p.batter_id}"].append(p)
    return {
        "game_id": game.id,
        "date": game.game_date.isoformat(),
        "matchup": f"{game.away_team} @ {game.home_team}",
        "total_pitches": len(game.pitches),
        "pitchers": {name: pitcher_line(ps) for name, ps in pitchers.items()},
        "batters": {name: batter_line(ps) for name, ps in batters.items()},
    }


def pitcher_line(ps: list[m.GamePitch]) -> dict[str, Any]:
    n = len(ps)
    strikes = sum(p.result in STRIKE_RESULTS for p in ps)
    swings = [p for p in ps if p.result in SWING_RESULTS]
    whiffs = sum(p.result == "swinging_strike" for p in ps)
    csw = sum(p.result in ("called_strike", "swinging_strike") for p in ps)
    first = [p for p in ps if p.balls == 0 and p.strikes == 0]
    outcomes = [p.pa_outcome for p in ps if p.pa_outcome]
    by_type: dict[str, list[m.GamePitch]] = defaultdict(list)
    for p in ps:
        by_type[p.pitch_type or "UN"].append(p)
    mix = {}
    for pt, group in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        v = _arr(p.velocity for p in group)
        sw = [p for p in group if p.result in SWING_RESULTS]
        mix[pt] = {
            "count": len(group), "usage": round(len(group) / n, 3),
            "velo_avg": _r(v.mean()) if v.size else None, "velo_min": _r(v.min()) if v.size else None, "velo_max": _r(v.max()) if v.size else None,
            "strike_pct": round(sum(p.result in STRIKE_RESULTS for p in group) / len(group), 3),
            "whiff_pct": round(sum(p.result == "swinging_strike" for p in sw) / len(sw), 3) if sw else None,
        }
    velo_by_inning = {}
    for inning in sorted({p.inning for p in ps}):
        v = _arr(p.velocity for p in ps if p.inning == inning and p.pitch_type in FASTBALL_TYPES)
        if v.size:
            velo_by_inning[inning] = {"avg": _r(v.mean()), "max": _r(v.max())}
    ttp = _arr(p.time_to_plate for p in ps)
    return {
        "pitches": n,
        "batters_faced": len(outcomes),
        "strike_pct": round(strikes / n, 3) if n else None,
        "first_pitch_strike_pct": round(sum(p.result in STRIKE_RESULTS for p in first) / len(first), 3) if first else None,
        "csw_pct": round(csw / n, 3) if n else None,
        "whiff_pct": round(whiffs / len(swings), 3) if swings else None,
        "strikeouts": outcomes.count("strikeout"),
        "walks": outcomes.count("walk"),
        "hits": sum(o in ("single", "double", "triple", "home_run") for o in outcomes),
        "pitch_mix": mix,
        "fb_velo_by_inning": velo_by_inning,
        "time_to_plate_avg": _r(ttp.mean(), 2) if ttp.size else None,
    }


def batter_line(ps: list[m.GamePitch]) -> dict[str, Any]:
    swings = [p for p in ps if p.result in SWING_RESULTS]
    chase_opps = [p for p in ps if (p.zone or 0) >= 11 or in_zone(p.plate_x, p.plate_z) is False]
    chases = [p for p in chase_opps if p.result in SWING_RESULTS]
    ev = _arr(p.exit_velocity for p in ps)
    outcomes = [p.pa_outcome for p in ps if p.pa_outcome]
    return {
        "pitches_seen": len(ps),
        "plate_appearances": len(outcomes),
        "swing_pct": round(len(swings) / len(ps), 3) if ps else None,
        "whiff_pct": round(sum(p.result == "swinging_strike" for p in swings) / len(swings), 3) if swings else None,
        "chase_pct": round(len(chases) / len(chase_opps), 3) if chase_opps else None,
        "ev_avg": _r(ev.mean()) if ev.size else None,
        "ev_max": _r(ev.max()) if ev.size else None,
        "outcomes": outcomes,
    }


def charted_plate_discipline(session: Session, player_id: int) -> dict[str, float | None]:
    """Whiff/chase from scout-charted games, as a hitter tracking input."""
    ps = list(session.scalars(select(m.GamePitch).where(m.GamePitch.batter_id == player_id)))
    if len(ps) < 50:
        return {}
    line = batter_line(ps)
    return {"whiff_pct": line["whiff_pct"], "chase_pct": line["chase_pct"]}


# --------------------------------------------------------------------------- projection

def player_seasons(player: m.Player, kind: str) -> list[dict[str, Any]]:
    out = []
    for s in player.stat_lines:
        if s.kind != kind or s.split != "overall":
            continue
        r = rates(kind, s.stats)
        age = player.age_on(dt.date(s.season, 6, 30)) if player.birth_date else None
        out.append({"season": s.season, "level": s.level, "age": age, "pa" if kind == "hitting" else "bf": r["pa" if kind == "hitting" else "bf"], "rates": r, "team": s.team})
    return sorted(out, key=lambda d: d["season"])


def build_projection_input(session: Session, player: m.Player, *, as_type: str | None = None, years: int = 6,
                           pathway: str = "auto", sims: int = 2000, display_levels: list[str] | None = None) -> ProjectionInput:
    ptype = as_type or ("pitcher" if player.player_type == "pitcher" else "hitter")
    age = player.age_on() or (get_level(player.current_level or "HS").typical_age)
    kind = "pitching" if ptype == "pitcher" else "hitting"
    reports = [r for r in player.scouting_reports if r.report_type == ptype]
    cons = consensus(reports) if reports else None
    track = tracking_summary(session, player.id)
    t_in: dict[str, Any] = {}
    if ptype == "pitcher" and "pitching" in track:
        t_in = {k: track["pitching"].get(k) for k in ("fb_velo_avg", "fb_ivb_avg", "zone_pct")}
    elif ptype == "hitter":
        t_in = {k: track.get("hitting", {}).get(k) for k in ("ev_90th", "ev_max", "bat_speed_avg")}
        t_in.update(charted_plate_discipline(session, player.id))
    motion = "pitching" if ptype == "pitcher" else "hitting"
    analyses = sorted((a for a in player.video_analyses if a.motion_type == motion and a.status == "done"), key=lambda a: a.created_at)
    mech = analyses[-1].scores.get("mechanics_score") if analyses else None
    stress = analyses[-1].scores.get("arm_stress") if analyses and ptype == "pitcher" else None
    return ProjectionInput(
        player_type=ptype, age=age, current_level=player.current_level or "HS",
        seasons=player_seasons(player, kind), scouting=cons,
        tracking={k: v for k, v in t_in.items() if v is not None}, mechanics_score=mech, arm_stress=stress,
        position=player.primary_position, pathway=pathway, years=years, sims=sims, display_levels=display_levels,
    )


def run_projection(session: Session, player: m.Player, **kwargs) -> m.ProjectionRun:
    inp = build_projection_input(session, player, **kwargs)
    result = project(inp)
    run = m.ProjectionRun(player_id=player.id, model_version=MODEL_VERSION, inputs=_jsonable(inp.__dict__), result=_jsonable(result))
    session.add(run)
    session.commit()
    return run


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, (dt.date, dt.datetime)):
        return x.isoformat()
    return x
