import json

import pytest
from conftest import SAMPLES
from fastapi.testclient import TestClient

from diamondiq import models as m
from diamondiq.api.main import app
from diamondiq.auth import create_user
from diamondiq.db import SessionLocal
from diamondiq.biomechanics.synthetic import synthetic_pitch


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        with SessionLocal() as session:
            if not session.query(m.User).filter_by(email="scout@example.com").first():
                create_user(session, "scout@example.com", "Test Scout", "correct horse battery", role="scout")
        assert c.post("/auth/login", json={"email": "scout@example.com", "password": "correct horse battery"}).status_code == 200
        yield c


def _player(client, **kw):
    body = {"first_name": "Marco", "last_name": "Reyes", "birth_date": "2005-03-02", "throws": "R", "bats": "R", "height_in": 74,
            "player_type": "pitcher", "primary_position": "P", "current_level": "D1", "current_team": "State U",
            "external_ids": {"trackman": "1001"}}
    body.update(kw)
    r = client.post("/players", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_pitcher_workflow(client):
    p = _player(client)
    pid = p["id"]
    assert p["current_level"] == "NCAA_D1"

    # stats
    r = client.post(f"/players/{pid}/stats", json={"season": 2026, "level": "NCAA_D1", "team": "State U", "kind": "pitching",
                                                     "stats": {"ip": "72.1", "bf": 300, "h": 60, "er": 28, "bb": 25, "so": 88, "hr": 6}})
    assert r.status_code == 201 and r.json()["rates"]["k_pct"] == pytest.approx(88 / 300, abs=1e-3)

    # scouting
    r = client.post(f"/players/{pid}/scouting-reports", json={
        "scout_name": "J. Smith", "report_date": "2026-04-12", "report_type": "pitcher", "level_seen": "D1",
        "tool_grades": {"fastball": {"present": 45, "future": 55}, "slider": {"present": 50, "future": 60}, "control": {"present": 40, "future": 50}},
        "measurables": {"fb_velo_low": 90, "fb_velo_high": 94}, "makeup": 60, "summary": "Athletic RHP with a hard slider."})
    assert r.status_code == 201 and r.json()["ofp"] is not None
    assert client.post(f"/players/{pid}/scouting-reports", json={"scout_name": "x", "report_date": "2026-04-12", "report_type": "pitcher",
                                                                "tool_grades": {"fastball": 95}}).status_code == 422

    # tracking import (auto-detect, matched by external id)
    with open(SAMPLES / "trackman_game.csv", "rb") as fh:
        r = client.post("/integrations/import", files={"file": ("tm.csv", fh, "text/csv")})
    imp = r.json()
    assert imp["source"] == "trackman" and imp["matched"] >= 6
    assert "Jordan Cole" in imp["unmatched_names"]
    with open(SAMPLES / "rapsodo_pitching.csv", "rb") as fh:
        r = client.post("/integrations/import", files={"file": ("r.csv", fh, "text/csv")}, data={"player_id": str(pid)})
    assert r.json()["matched"] == 3
    t = client.get(f"/players/{pid}/tracking").json()
    assert t["pitching"]["fb_velo_avg"] > 90 and "SL" in t["pitching"]["arsenal"]

    # biomechanics from keypoints (video uploads take the same path after pose extraction)
    kp = json.dumps(synthetic_pitch().to_json()).encode()
    r = client.post(f"/players/{pid}/keypoints", files={"file": ("kp.json", kp, "application/json")}, data={"motion_type": "pitching"})
    assert r.status_code == 201, r.text
    a1 = r.json()
    assert a1["status"] == "done" and a1["scores"]["mechanics_score"] > 0 and "arm_stress" in a1["scores"]
    kp2 = json.dumps(synthetic_pitch(stride_pct=0.7, knee_brace_deg=-10).to_json()).encode()
    a2 = client.post(f"/players/{pid}/keypoints", files={"file": ("kp.json", kp2, "application/json")}, data={"motion_type": "pitching"}).json()
    cmp = client.get(f"/analyses/{a2['id']}/compare/{a1['id']}").json()
    assert cmp["metrics"]["stride_length_pct_height"]["change"] > 10

    # live game charting
    g = client.post("/games", json={"game_date": "2026-04-18", "home_team": "State U", "away_team": "Tech", "level": "D1", "scout_name": "J. Smith"}).json()
    seq = [("FF", 93, "called_strike", 0, 0, None), ("SL", 84, "swinging_strike", 0, 1, None), ("FF", 94, "foul", 0, 2, None),
           ("SL", 85, "swinging_strike", 0, 2, "strikeout"), ("FF", 92, "ball", 0, 0, None), ("CH", 85, "in_play", 1, 0, "single")]
    for pt, v, res, b, s_, out in seq:
        r = client.post(f"/games/{g['id']}/pitches", json={"pitcher_id": pid, "batter_name": "Opp Hitter", "inning": 1, "balls": b, "strikes": s_,
                                                              "pitch_type": pt, "velocity": v, "result": res, "pa_outcome": out})
        assert r.status_code == 201, r.text
    client.post(f"/games/{g['id']}/notes", json={"player_id": pid, "inning": 1, "category": "delivery", "text": "Quick to the plate."})
    summ = client.get(f"/games/{g['id']}/summary").json()
    line = summ["pitchers"]["Marco Reyes"]
    assert line["pitches"] == 6 and line["strikeouts"] == 1 and line["pitch_mix"]["SL"]["whiff_pct"] == 1.0
    assert line["first_pitch_strike_pct"] == 0.5
    client.delete(f"/games/{g['id']}/pitches/last")
    assert len(client.get(f"/games/{g['id']}/pitches").json()) == 5
    assert client.get(f"/players/{pid}/charted-pitching").json()["overall"]["pitches"] == 5

    # projection uses everything above
    r = client.post(f"/players/{pid}/projections", json={"years": 5, "sims": 400})
    assert r.status_code == 201, r.text
    proj = r.json()
    srcs = {s["source"] for s in proj["current_talent"]["components"]["stuff"]["sources"]}
    assert {"stats", "scouting", "tracking"} <= srcs
    assert len(proj["years"]) == 6 and "MLB" in proj["years"][0]["projected_by_level"]
    assert client.get(f"/players/{pid}/projections").json()[0]["id"] == proj["id"]

    prof = client.get(f"/players/{pid}/profile").json()
    assert prof["scouting"]["pitcher"]["report_count"] == 1
    assert prof["latest_projection"]["summary"].startswith("Current overall talent")
    assert prof["mechanics"]


def test_watchlists_search_and_reference(client):
    p = _player(client, first_name="Jordan", last_name="Cole", player_type="hitter", primary_position="SS", current_level="HS", grad_year=2027,
                birth_date="2009-05-01", external_ids={})
    wl = client.post("/watchlists", json={"name": "2027 SS targets"}).json()
    assert client.put(f"/watchlists/{wl['id']}/players/{p['id']}").status_code == 204
    assert client.get(f"/watchlists/{wl['id']}").json()["players"][0]["last_name"] == "Cole"
    assert [x["id"] for x in client.get("/players", params={"grad_year": 2027, "position": "SS"}).json()] == [p["id"]]
    with open(SAMPLES / "hittrax_session.csv", "rb") as fh:
        assert client.post("/integrations/import", files={"file": ("h.csv", fh)}).json()["matched"] == 4
    assert client.get(f"/players/{p['id']}/tracking").json()["hitting"]["ev_max"] == 101.4
    assert len(client.get("/levels").json()) > 20
    assert client.get("/projections/outcome-tiers").status_code == 200
    assert "pitching" in client.get("/biomechanics/references").json()


def test_stats_csv_import_and_what_if(client):
    csv = "first_name,last_name,season,level,team,PA,AB,H,2B,3B,HR,BB,SO,HBP,SF\nJordan,Cole,2026,HS,Central,110,92,38,9,1,6,15,12,2,1\nNo,Body,2026,HS,X,10,10,1,0,0,0,0,5,0,0\n"
    r = client.post("/stats/import", files={"file": ("s.csv", csv)}, data={"kind": "hitting"}).json()
    assert r == {"created": 1, "unmatched": ["No Body"]}
    r = client.post("/projections/what-if", json={"player_type": "pitcher", "age": 18, "current_level": "HS", "tracking": {"fb_velo_avg": 91}, "years": 4, "sims": 300})
    assert r.status_code == 200 and len(r.json()["years"]) == 5


def test_mobile_app_is_served(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/app/"
    page = client.get("/app/")
    assert page.status_code == 200 and "app.js" in page.text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/sw.js").status_code == 200
