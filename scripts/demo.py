"""Seed a demo database through the API and print what the system produces.

    python scripts/demo.py            # uses ./diamondiq-demo.db
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DIAMONDIQ_DATABASE_URL", f"sqlite:///{ROOT / 'diamondiq-demo.db'}")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from diamondiq import models as m  # noqa: E402
from diamondiq.api.main import app  # noqa: E402
from diamondiq.auth import create_user  # noqa: E402
from diamondiq.db import SessionLocal  # noqa: E402
from diamondiq.biomechanics.synthetic import synthetic_pitch, synthetic_swing  # noqa: E402

SAMPLES = ROOT / "samples"


def main():
    with TestClient(app) as c:
        with SessionLocal() as session:
            if not session.query(m.User).filter_by(email="demo@example.com").first():
                create_user(session, "demo@example.com", "Demo Admin", "demo password", role="admin")
        c.post("/auth/login", json={"email": "demo@example.com", "password": "demo password"})
        print("Demo sign-in: demo@example.com / demo password (local demo database only)")
        rhp = c.post("/players", json={"first_name": "Marco", "last_name": "Reyes", "birth_date": "2005-03-02", "throws": "R", "bats": "R",
                                       "height_in": 74, "weight_lb": 195, "player_type": "pitcher", "primary_position": "P",
                                       "current_level": "NCAA_D1", "current_team": "State U", "external_ids": {"trackman": "1001"}}).json()
        ss = c.post("/players", json={"first_name": "Jordan", "last_name": "Cole", "birth_date": "2009-05-01", "throws": "R", "bats": "R",
                                      "height_in": 73, "player_type": "hitter", "primary_position": "SS", "current_level": "HS",
                                      "current_team": "Central HS", "grad_year": 2027, "commitment": "State U"}).json()

        c.post(f"/players/{rhp['id']}/stats", json={"season": 2026, "level": "NCAA_D1", "team": "State U", "kind": "pitching",
                                                     "stats": {"ip": "72.1", "bf": 300, "h": 60, "er": 28, "bb": 25, "so": 88, "hr": 6}})
        c.post(f"/players/{ss['id']}/stats", json={"season": 2026, "level": "HS", "team": "Central HS", "kind": "hitting",
                                                    "stats": {"pa": 112, "ab": 94, "h": 39, "2b": 10, "3b": 2, "hr": 6, "bb": 14, "so": 11, "hbp": 2, "sf": 2, "sb": 18, "cs": 3}})
        c.post(f"/players/{rhp['id']}/scouting-reports", json={
            "scout_name": "J. Smith", "report_date": "2026-04-12", "report_type": "pitcher", "level_seen": "NCAA_D1",
            "tool_grades": {"fastball": {"present": 50, "future": 55}, "slider": {"present": 50, "future": 60},
                            "changeup": {"present": 40, "future": 50}, "control": {"present": 40, "future": 50}},
            "makeup": 60, "role_projection": "No. 4 starter / high-leverage reliever", "risk": "medium"})
        c.post(f"/players/{ss['id']}/scouting-reports", json={
            "scout_name": "A. Lee", "report_date": "2026-06-20", "report_type": "hitter", "level_seen": "SHOWCASE",
            "tool_grades": {"hit": {"present": 30, "future": 55}, "game_power": {"present": 25, "future": 50}, "raw_power": {"present": 35, "future": 55},
                            "run": {"present": 60, "future": 55}, "field": {"present": 45, "future": 55}, "arm": {"present": 50, "future": 55}},
            "projectability": 60, "makeup": 55, "measurables": {"sixty_time": 6.65, "inf_velo": 88}})

        for f, kw in (("trackman_game.csv", {}), ("rapsodo_pitching.csv", {"player_id": str(rhp["id"])}),
                      ("hittrax_session.csv", {}), ("blast_swings.csv", {"player_id": str(ss["id"])})):
            with open(SAMPLES / f, "rb") as fh:
                r = c.post("/integrations/import", files={"file": (f, fh)}, data=kw).json()
            print(f"import {f:24s} -> {r['source']:16s} events={r['events']} matched={r['matched']}")

        for pid, motion, seq in ((rhp["id"], "pitching", synthetic_pitch(stride_pct=0.76, separation_deg=25)), (ss["id"], "hitting", synthetic_swing())):
            a = c.post(f"/players/{pid}/keypoints", files={"file": ("kp.json", json.dumps(seq.to_json()))}, data={"motion_type": motion}).json()
            print(f"\n{motion} mechanics score {a['scores']['mechanics_score']}  priorities: {a['scores']['top_priorities']}")
            if "arm_stress" in a["scores"]:
                print(f"  arm stress screen: {a['scores']['arm_stress']}")
            for item in [i for i in a["feedback"] if i["status"] != "optimal"][:3]:
                print(f"  [{item['status']}] {item['label']}: {item['value']} (target {item['optimal']}) -> {item['message']}")

        for p in (rhp, ss):
            proj = c.post(f"/players/{p['id']}/projections", json={"years": 6}).json()
            print(f"\n=== {p['first_name']} {p['last_name']} ===\n{proj['summary']}")
            y3 = proj["years"][3]
            print(f"  In 3 years (age {y3['age']}): most likely {y3['most_likely_level']}; overall talent {y3['overall_talent']}")
            key = "woba" if proj["player_type"] == "hitter" else "era_fip_est"
            row = {lv: line[key]["median"] for lv, line in y3["projected_by_level"].items()}
            print(f"  Projected {key} by level in 3 years: {row}")

        print("\nAPI docs: run `uvicorn diamondiq.api.main:app --reload` and open http://127.0.0.1:8000/docs")


if __name__ == "__main__":
    main()
