"""Monte Carlo career projection across levels.

For each simulated career we draw the player's current component talents
from their estimated distribution, then age them year by year with the
development curve, the player-specific growth multiplier, shared and
component-specific randomness, and (for pitchers) injury shocks. Each year
we record where the player would most likely be playing and what their stat
line would look like at every level.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ..levels import PRO_LADDER, all_levels, assign_level, get_level, stat_sd
from .development import annual_delta, annual_noise, growth_multiplier
from .talent import HITTER_COMPONENTS, PITCHER_COMPONENTS, estimate_talent, non_bat_value, overall

MODEL_VERSION = "0.1.0"

OUTCOME_TIERS = [
    (60, "All-Star caliber"),
    (55, "Above-average MLB regular"),
    (50, "Average MLB regular"),
    (47, "MLB role player (platoon / bench / middle relief)"),
    (44, "Up-and-down / Quad-A"),
    (40, "Upper minors (AA/AAA)"),
    (35, "Lower minors / independent pro"),
    (31, "NCAA D1 / top summer league"),
    (25, "Small-college (D2 / D3 / NAIA / JUCO)"),
    (-1e9, "High school / club"),
]

DEFAULT_DISPLAY_LEVELS = ["HS", "JUCO", "NAIA", "NCAA_D3", "NCAA_D2", "NCAA_D1", "CAPE", "ROOKIE", "A", "A_PLUS", "AA", "AAA", "MLB"]


@dataclass
class ProjectionInput:
    player_type: str  # hitter | pitcher
    age: float
    current_level: str
    seasons: list[dict[str, Any]] = field(default_factory=list)  # {season, level, age, pa|bf, rates{...}}
    scouting: dict[str, Any] | None = None  # scouting.consensus() output
    tracking: dict[str, Any] | None = None  # aggregates: fb_velo_avg, ev_90th, bat_speed_avg ...
    mechanics_score: float | None = None
    arm_stress: str | None = None  # low | moderate | elevated
    position: str | None = None
    pathway: str = "auto"  # auto | college | juco | pro
    years: int = 6
    sims: int = 2000
    seed: int | None = 7
    display_levels: list[str] | None = None


def tier_for(talent: float) -> str:
    for cutoff, label in OUTCOME_TIERS:
        if talent >= cutoff:
            return label
    return OUTCOME_TIERS[-1][1]


def _soft(z: np.ndarray, cap: float = 2.5) -> np.ndarray:
    """Compress extreme z-scores: a player far above a level dominates it, but rates saturate instead of going linear forever."""
    return cap * np.tanh(z / cap)


def translate_hitter(c: dict[str, np.ndarray], level_code: str) -> dict[str, np.ndarray]:
    lvl = get_level(level_code)
    b, m, sd = lvl.hitting, lvl.talent_mean, lvl.talent_sd
    zc, zp, zd = _soft((c["contact"] - m) / sd), _soft((c["power"] - m) / sd), _soft((c["discipline"] - m) / sd)
    zo = _soft((overall(c, "hitter") - m) / sd)
    k = np.clip(b.k_pct - zc * stat_sd(lvl, "k_pct"), 0.03, 0.6)
    bb = np.clip(b.bb_pct + zd * stat_sd(lvl, "bb_pct"), 0.01, 0.3)
    iso = np.clip(b.iso + zp * stat_sd(lvl, "iso"), 0.0, 0.45)
    avg = np.clip(b.avg + (0.6 * zc + 0.25 * zp) * stat_sd(lvl, "avg"), 0.1, 0.45)
    obp = np.clip(avg + bb * (1 - avg) * 0.95, 0.15, 0.6)
    woba = np.clip(b.woba + zo * stat_sd(lvl, "woba"), 0.18, 0.55)
    return {"avg": avg, "obp": obp, "slg": avg + iso, "iso": iso, "k_pct": k, "bb_pct": bb, "woba": woba}


def translate_pitcher(c: dict[str, np.ndarray], level_code: str) -> dict[str, np.ndarray]:
    lvl = get_level(level_code)
    b, m, sd = lvl.pitching, lvl.talent_mean, lvl.talent_sd
    zs, zc, zm = _soft((c["stuff"] - m) / sd), _soft((c["control"] - m) / sd), _soft((c["contact_mgmt"] - m) / sd)
    k = np.clip(b.k_pct + zs * stat_sd(lvl, "k_pct"), 0.05, 0.5)
    bb = np.clip(b.bb_pct - zc * stat_sd(lvl, "bb_pct"), 0.02, 0.25)
    hr = np.clip(b.hr_pct - zm * stat_sd(lvl, "hr_pct"), 0.0, 0.08)
    era = np.clip(b.era + 4.3 * (13 * (hr - b.hr_pct) + 3 * (bb - b.bb_pct) - 2 * (k - b.k_pct)), 0.5, 12.0)
    return {"k_pct": k, "bb_pct": bb, "k_minus_bb_pct": k - bb, "hr_pct": hr, "era_fip_est": era}


# Highest affiliated level a newly signed player starts at, by age.
def _entry_cap(age: float) -> int:
    return PRO_LADDER.index("A") if age < 20 else PRO_LADDER.index("A_PLUS") if age < 23 else PRO_LADDER.index("AA")


def paced_level(prev: str | None, talent: float, age: float, pathway: str) -> str:
    """Assign a level with realistic promotion pace.

    Within the affiliated ladder a player climbs one rung a year, or two when
    already well above the next level; first pro assignments are capped by age.
    """
    target = assign_level(talent, age, pathway)
    code = target.code if target else "OUT"
    if code not in PRO_LADDER:
        return code
    t_idx = PRO_LADDER.index(code)
    if prev in PRO_LADDER:
        p_idx = PRO_LADDER.index(prev)
        step = 1
        if p_idx + 2 < len(PRO_LADDER):
            two_up = get_level(PRO_LADDER[p_idx + 2])
            if talent >= two_up.hold_own_threshold + 0.5 * two_up.talent_sd:
                step = 2
        return PRO_LADDER[max(min(t_idx, p_idx + step), p_idx - 1)]
    return PRO_LADDER[min(t_idx, _entry_cap(age))]


def _pcts(x: np.ndarray, digits: int = 3) -> dict[str, float]:
    p10, p50, p90 = np.percentile(x, [10, 50, 90])
    return {"p10": round(float(p10), digits), "median": round(float(p50), digits), "p90": round(float(p90), digits)}


def project(inp: ProjectionInput) -> dict[str, Any]:
    rng = np.random.default_rng(inp.seed)
    ptype = "hitter" if inp.player_type in ("hitter", "two_way") else "pitcher"
    comps = HITTER_COMPONENTS if ptype == "hitter" else PITCHER_COMPONENTS
    est = estimate_talent(ptype, inp.current_level, inp.age, inp.seasons, inp.scouting, inp.tracking)
    extra = non_bat_value(inp.scouting, inp.position) if ptype == "hitter" else 0.0
    display = inp.display_levels or DEFAULT_DISPLAY_LEVELS
    N, Y = inp.sims, inp.years

    # Player-specific growth multipliers (per component when scouts graded present+future).
    tools = (inp.scouting or {}).get("tools") or {}
    tool_for = {"contact": "hit", "power": "game_power", "discipline": "approach", "stuff": "fastball", "control": "control", "contact_mgmt": "command"}
    mults, reasons = {}, {}
    for c in comps:
        t = tools.get(tool_for[c], {})
        present = t.get("present", {}).get("mean") if t.get("present") else None
        future = t.get("future", {}).get("mean") if t.get("future") else None
        mults[c], reasons[c] = growth_multiplier(
            inp.age, ptype, present=present, future=future,
            projectability=(inp.scouting or {}).get("projectability"), makeup=(inp.scouting or {}).get("makeup"),
            mechanics_score=inp.mechanics_score,
        )

    talent = {c: rng.normal(est.means[c], np.sqrt(est.variances[c]), N) for c in comps}
    injury_p = {"low": 0.05, "moderate": 0.08, "elevated": 0.12}.get(inp.arm_stress or "low", 0.05) if ptype == "pitcher" else 0.02

    years_out = []
    overall_path = np.zeros((Y + 1, N))
    level_path: list[list[str | None]] = []
    for y in range(Y + 1):
        age = inp.age + y
        if y > 0:
            base = annual_delta(age - 1, ptype)
            noise = annual_noise(age - 1)
            shared = rng.normal(0, noise * 0.75, N)
            for c in comps:
                growth = base * mults[c] if base > 0 else base
                talent[c] = talent[c] + growth + shared + rng.normal(0, noise * 0.5, N)
            hurt = rng.random(N) < injury_p * (1.3 if age > 30 else 1.0)
            if hurt.any():
                hit_comp = "stuff" if ptype == "pitcher" else "power"
                talent[hit_comp][hurt] -= rng.uniform(2, 6, hurt.sum())
        ovr = overall(talent, ptype, extra)
        overall_path[y] = ovr
        prev_codes = level_path[-1] if level_path else [get_level(inp.current_level).code] * N
        if y == 0:
            codes = prev_codes
        else:
            codes = [paced_level(prev_codes[i], float(ovr[i]), age, inp.pathway) for i in range(N)]
        level_path.append(codes)
        uniq, counts = np.unique(codes, return_counts=True)
        dist = sorted(({"level": str(u), "probability": round(float(n) / N, 3)} for u, n in zip(uniq, counts, strict=True)), key=lambda d: -d["probability"])
        translate = translate_hitter if ptype == "hitter" else translate_pitcher
        by_level = {}
        for code in display:
            lines = translate(talent, code)
            by_level[code] = {k: _pcts(v) for k, v in lines.items()}
        years_out.append({
            "year_offset": y,
            "age": round(age, 1),
            "overall_talent": _pcts(ovr, 1),
            "components": {c: _pcts(talent[c], 1) for c in comps},
            "most_likely_level": dist[0]["level"],
            "level_distribution": dist[:6],
            "projected_by_level": by_level,
        })

    peak = overall_path.max(axis=0)
    tier_counts: dict[str, int] = {}
    for p in peak:
        tier_counts[tier_for(p)] = tier_counts.get(tier_for(p), 0) + 1
    tiers = [{"tier": label, "probability": round(tier_counts.get(label, 0) / N, 3)} for _, label in OUTCOME_TIERS if tier_counts.get(label)]

    reach = {}
    for code in [lv.code for lv in all_levels() if lv.primary]:
        hit = np.zeros(N, dtype=bool)
        for y in range(Y + 1):
            hit |= np.array([lp == code for lp in level_path[y]])
        reach[code] = round(float(hit.mean()), 3)
    ladder_reach = {code: 0.0 for code in PRO_LADDER}
    order = {code: i for i, code in enumerate(PRO_LADDER)}
    highest = np.full(N, -1)
    for y in range(Y + 1):
        for i, code in enumerate(level_path[y]):
            if code in order:
                highest[i] = max(highest[i], order[code])
    for code, i in order.items():
        ladder_reach[code] = round(float((highest >= i).mean()), 3)

    current = est.summary()
    result = {
        "model_version": MODEL_VERSION,
        "player_type": ptype,
        "start_age": inp.age,
        "current_level": get_level(inp.current_level).code,
        "current_talent": {"overall": round(float(overall(est.means, ptype, extra)), 1), "components": current, "non_bat_adjustment": round(extra, 1)},
        "growth_multipliers": {c: {"multiplier": round(mults[c], 2), "reasons": reasons[c]} for c in comps},
        "years": years_out,
        "outcomes": {
            "peak_talent": _pcts(peak, 1),
            "most_likely_tier": tier_for(float(np.median(peak))),
            "ceiling_tier": tier_for(float(np.percentile(peak, 90))),
            "floor_tier": tier_for(float(np.percentile(peak, 10))),
            "tier_probabilities": tiers,
            "probability_reach_level": reach,
            "probability_reach_pro_level": ladder_reach,
            "risk": _risk_label(float(np.percentile(peak, 90) - np.percentile(peak, 10))),
        },
        "assumptions": {
            "pathway": inp.pathway,
            "simulations": N,
            "injury_rate_per_year": injury_p,
            "note": "Talent scale aligns with the 20-80 scouting scale (50 = average MLB regular). Level baselines and aging curves are priors until calibrated on historical data.",
        },
    }
    result["summary"] = narrative(result)
    return result


def _risk_label(spread: float) -> str:
    if spread < 8:
        return "low"
    if spread < 13:
        return "medium"
    if spread < 18:
        return "high"
    return "extreme"


def narrative(r: dict[str, Any]) -> str:
    o = r["outcomes"]
    yrs = r["years"]
    path = []
    last = None
    for y in yrs:
        if y["most_likely_level"] != last:
            path.append(f"{y['most_likely_level']} (age {y['age']:.1f})")
            last = y["most_likely_level"]
    mlb = o["probability_reach_pro_level"].get("MLB", 0)
    top_tiers = ", ".join(f"{t['tier']} {t['probability']:.0%}" for t in sorted(o["tier_probabilities"], key=lambda t: -t["probability"])[:3])
    return (
        f"Current overall talent {r['current_talent']['overall']:.0f} on the 20-80 scale. "
        f"Most likely outcome: {o['most_likely_tier']} (ceiling: {o['ceiling_tier']}; floor: {o['floor_tier']}; risk {o['risk']}). "
        f"Most likely path: {' -> '.join(path)}. "
        f"Chance to reach MLB within {len(yrs) - 1} years: {mlb:.0%}. "
        f"Outcome mix: {top_tiers}."
    )


def to_jsonable(inp: ProjectionInput) -> dict[str, Any]:
    return asdict(inp)
