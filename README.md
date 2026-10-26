# DiamondIQ

Player evaluation, biomechanics, scouting, tracking and projection for every level of baseball, from high school JV through MLB (JUCO, NAIA, NCAA D3/D2/D1, summer leagues, the affiliated minors, independent and international pro).

## What it does

| Area | Capabilities |
|---|---|
| **One talent scale for every level** | Every level (24 of them) sits on a single scale aligned with the 20-80 scouting scale (50 = average MLB regular). A player's stats at any level, scouting grades and tracking data all convert to that scale, so you can compare a D2 pitcher with a High-A pitcher, or a HS hitter with a JUCO hitter. |
| **Video biomechanics** | Upload pitching or hitting video. MediaPipe pose estimation extracts 3D keypoints. The system detects phases (leg lift, foot plant, release / load, foot down, contact), computes ~25 metrics per motion (stride, hip-shoulder separation, lead-leg block, trunk tilt, arm slot, kinematic sequence, head movement…), and gives prioritized feedback with cues and drills against level-appropriate targets. Pitchers also get an arm-stress screen. You can compare two analyses to see before/after changes. Pose data from other systems (lab markerless capture etc.) can be imported directly. |
| **Scouting** | 20-80 present/future tool grades for hitters and pitchers, measurables, OFP (suggested if not given), risk, role, projectability, makeup and narrative fields. Multiple reports combine into a recency-weighted consensus that shows where scouts disagree. |
| **Stats** | Counting stats by season, level and split, with derived rates (AVG/OBP/SLG/ISO/K%/BB%/wOBA/BABIP, ERA/WHIP/FIP/K-BB%). CSV bulk import. |
| **Game & pitch tracking** | Chart games live: every pitch with type, velo, location, count and result, plus PA outcomes, time to plate and scout notes. You get per-game and season-to-date pitcher lines (mix, velo by inning, strike %, first-pitch strike %, CSW, whiff by pitch) and batter lines (swing / whiff / chase). Watchlists keep targets organized. |
| **Integrations** | TrackMan (and TrackMan-format exports such as Yakkertech/FlightScope), Rapsodo pitching & hitting, HitTrax, Hawk-Eye / Statcast (Savant CSV or JSON), Blast Motion / bat sensors, and a **generic column-mapping adapter** with unit conversion for anything else (Pocket Radar, Stalker, PitchLogic, in-house tools). Formats are auto-detected. Rows are matched to players by external ID, then by name, and unmatched names are reported so you can assign them. |
| **Projection** | A Monte Carlo career model (2,000 sims by default) combines all of the above. Each year it gives: talent percentiles, the most likely level and the full level distribution, and projected stat lines (p10/median/p90) **at every level**. It also gives outcome-tier probabilities (from "small college" up to "All-Star"), the chance of reaching each level, ceiling, floor and risk, and a plain-English summary. Every estimate shows which evidence drove it and how much. A what-if endpoint projects hypothetical players. |

## Mobile app

Open **http://<server>:8000/app/** on a phone (or `/`, which redirects there). It's a mobile-first web app served by the API itself, with nothing to install. "Add to Home Screen" makes it open full-screen like a native app.

- **Players:** search and filter by level, type and watchlist. Each player has tabs:
  - **Overview:** bio and a snapshot
  - **Scouting:** consensus grades and a 20-80 report form
  - **Stats:** season lines
  - **Tracking:** device data and file import
  - **Mechanics:** record or upload a video, read prioritized feedback with drills, compare two analyses
  - **Projection:** talent-by-age chart with range band, chance to reach each level, outcome mix, projected stat lines at every level by year, and where the estimate comes from
- **Games & live charting:** big tap targets for pitch type, velocity, location (catcher's-view zone grid) and result.
  - The count, outs and innings advance automatically; strikeouts, walks and HBP are recorded for you.
  - A ball in play opens a result sheet.
  - Undo, scouting notes, and a running pitcher line (pitch count, strike %, velo by pitch type) are on the same screen.
- **Works with bad ballpark signal:** pitches are queued on the phone and sync automatically when the connection returns. The badge in the header shows anything still waiting. The app shell is cached so the charting screen opens offline.

## Quick start

```bash
pip install -e ".[video,dev]"
python -m diamondiq.biomechanics.pose --download     # MediaPipe pose model (~30 MB)
uvicorn diamondiq.api.main:app --reload              # interactive docs at http://127.0.0.1:8000/docs
python scripts/demo.py                               # seeds a demo DB and prints analyses + projections
pytest                                               # 29 tests
```

On a headless Linux server, MediaPipe also needs `libegl1 libgles2 libgl1` (apt).

Configuration (environment variables): `DIAMONDIQ_DATABASE_URL` (default SQLite; any SQLAlchemy URL such as `postgresql+psycopg://…` works), `DIAMONDIQ_MEDIA_DIR`, `DIAMONDIQ_POSE_MODEL`, `DIAMONDIQ_PROJECTION_SIMS`.

## Typical workflow

```text
POST /players                                   create player (level codes or aliases: "D1", "JUCO", "High-A", "MLB")
POST /players/{id}/stats                        season line at any level
POST /players/{id}/scouting-reports             20-80 tool grades
POST /integrations/import                       TrackMan / Rapsodo / HitTrax / Hawk-Eye / Blast / generic file
POST /players/{id}/videos                       pitching or hitting video, analyzed in background -> GET /analyses/{id}
POST /games, POST /games/{id}/pitches           live charting -> GET /games/{id}/summary
POST /players/{id}/projections                  career projection across levels
GET  /players/{id}/profile                      everything in one place
```

## Layout

```
diamondiq/
  levels.py              level catalog: talent mean/sd, typical ages, league baselines, eligibility & assignment
  models.py, db.py       SQLAlchemy data model (JSON columns for flexible grades/metrics/raw device rows)
  stats.py, scouting.py  rate stats; 20-80 scale, OFP, multi-scout consensus
  services.py            imports & player matching, tracking aggregates, game summaries, projection inputs
  integrations/          one adapter per vendor + generic mapper, normalized to shared units
  biomechanics/          pose extraction, kinematics, pitching & hitting analysis, feedback, synthetic motions
  projection/            talent estimation, development curves, Monte Carlo simulation, calibration
  api/                   FastAPI app and routers
samples/                 example vendor exports used by tests and the demo
```

## How the projection works

1. **Estimate current talent per component.** For hitters these are contact, power and discipline; for pitchers, stuff, control and contact management. Each piece of evidence becomes a noisy measurement on the talent scale:
   - each season's rates, converted from their level and weighted by sample size against stabilization points
   - scouts' present grades
   - tracking (FB velo/IVB, 90th-percentile EV, bat speed, zone%, whiff/chase from charted games)

   These are combined by precision weighting on top of a prior for the player's level. Older seasons are rolled forward with expected development and down-weighted.
2. **Develop** year by year with an aging curve. Growth before the peak is scaled by scouts' present→future gap, makeup, projectability (only when no future grade exists) and mechanics score. Randomness is both shared and per component. Pitchers also take injury shocks, with higher rates when the arm-stress screen is elevated.
3. **Assign levels** with realistic pacing (age eligibility, pathway (college / JUCO / pro / auto), entry caps for draftees, at most 1-2 rungs a year).
4. **Translate** talent into stat lines at any level, using that level's baselines and spreads. Extreme gaps saturate.

**Important:** level gaps, stat baselines, aging curves and biomechanics targets are informed *priors*, not values fitted to data. `projection/calibration.py` re-estimates level gaps and aging curves (delta method) from your own longitudinal data. Run it once you have a few hundred player-season pairs, and update `levels.py` / `development.py`. Treat projections as structured, explainable estimates until then.

## Biomechanics notes and limits

- Best capture: 120-240 fps, full body in frame, camera roughly perpendicular to the throw/swing direction, one athlete in view. Below 120 fps, speed and sequencing metrics are marked lower-confidence and never raised as flags.
- Single-camera pose cannot measure shoulder external rotation, joint torques or bat path directly. For those, import lab or sensor data (keypoints endpoint, Blast, etc.).
- The arm-stress output is a screen based on mechanical patterns linked to elevated load in research. It is not a medical assessment.
- Accuracy against real video hasn't been benchmarked yet. Validate against a lab system or hand-labelled clips before relying on absolute values.

## Integration notes

Sample files in `samples/` follow each vendor's common export layout, but export columns vary by product version and settings. If one of your files isn't detected, pass `source` explicitly or use the `generic` adapter with a `column_map`. If it's a recurring format, add a small adapter in `integrations/` (≈40 lines). Live API pulls (TrackMan/Rapsodo cloud, MLB Stats API, Synergy, etc.) need vendor credentials and contracts. Adding them means a new adapter that feeds the same `NormalizedEvent` pipeline.

## Roadmap

- Web/mobile front end (scout game-charting UI optimized for a phone, player pages, projection charts)
- Auth, organizations and roles (scouts, coaches, front office), with per-org data separation
- Background job queue (e.g. Celery/RQ) and GPU workers for video at scale; overlay video rendering of keypoints and phases
- Live vendor API connectors and scheduled syncs; stat scrapers/feeds by level
- Fit priors on historical data; add a learned model (e.g. gradient boosting on career outcomes) alongside the transparent simulation and compare calibration
- Pitch-level models (Stuff+/location+), defensive metrics, workload/fatigue tracking
