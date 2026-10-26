"""Estimate a player's current component talents on the 20-80-aligned talent scale.

Each source of evidence (stats at any level, scouting grades, tracking data)
becomes a noisy measurement of the same underlying talent, and they are
combined by precision weighting on top of a prior centred on the player's
current level. Every contribution is recorded so the projection can explain
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..levels import get_level, stat_sd
from .development import expected_growth

HITTER_COMPONENTS = ("contact", "power", "discipline")
PITCHER_COMPONENTS = ("stuff", "control", "contact_mgmt")

# PA (or BF) at which half of an observed rate is signal. Roughly follows
# published stabilization points for MLB.
STABILIZATION = {"k_pct": 60, "bb_pct": 120, "iso": 160, "p_k_pct": 70, "p_bb_pct": 170, "p_hr_pct": 1000}
PAST_SEASON_VAR_PER_YEAR = 1.5**2
POSITION_ADJ = {"C": 2.0, "SS": 2.0, "CF": 1.5, "2B": 0.5, "3B": 0.5, "LF": -0.5, "RF": -0.5, "OF": 0.0, "IF": 0.5, "1B": -2.0, "DH": -3.0}


@dataclass
class Evidence:
    component: str
    source: str
    estimate: float
    variance: float
    detail: str = ""


@dataclass
class TalentEstimate:
    means: dict[str, float]
    variances: dict[str, float]
    evidence: list[Evidence] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for comp, mean in self.means.items():
            ev = [e for e in self.evidence if e.component == comp]
            total_prec = sum(1 / e.variance for e in ev)
            out[comp] = {
                "talent": round(mean, 1),
                "sd": round(self.variances[comp] ** 0.5, 1),
                "sources": [
                    {"source": e.source, "estimate": round(e.estimate, 1), "weight": round((1 / e.variance) / total_prec, 2), "detail": e.detail}
                    for e in ev
                ],
            }
        return out


def _combine(evidence: list[Evidence], comp: str) -> tuple[float, float]:
    ev = [e for e in evidence if e.component == comp]
    prec = sum(1 / e.variance for e in ev)
    mean = sum(e.estimate / e.variance for e in ev) / prec
    return mean, 1 / prec


def _season_evidence(season: dict[str, Any], player_type: str, current_age: float) -> list[Evidence]:
    lvl = get_level(season["level"])
    rates = season.get("rates") or {}
    n = season.get("pa") or season.get("bf") or 0
    if n < 10:
        return []
    age_then = season.get("age")
    roll = expected_growth(age_then, current_age, player_type) if age_then is not None else 0.0
    years_ago = max(0.0, current_age - age_then) if age_then is not None else 0.0
    label = f"{season.get('season', '')} {lvl.code} ({int(n)} {'PA' if player_type == 'hitter' else 'BF'})"
    out = []

    def add(comp, z, stab_key, stat):
        var = lvl.talent_sd**2 * STABILIZATION[stab_key] / n + PAST_SEASON_VAR_PER_YEAR * years_ago
        out.append(Evidence(comp, "stats", lvl.talent_mean + z * lvl.talent_sd + roll, var, f"{label}: {stat}"))

    if player_type == "hitter":
        b = lvl.hitting
        if rates.get("k_pct") is not None:
            add("contact", (b.k_pct - rates["k_pct"]) / stat_sd(lvl, "k_pct"), "k_pct", f"K% {rates['k_pct']:.1%}")
        if rates.get("bb_pct") is not None:
            add("discipline", (rates["bb_pct"] - b.bb_pct) / stat_sd(lvl, "bb_pct"), "bb_pct", f"BB% {rates['bb_pct']:.1%}")
        if rates.get("iso") is not None:
            add("power", (rates["iso"] - b.iso) / stat_sd(lvl, "iso"), "iso", f"ISO {rates['iso']:.3f}")
    else:
        b = lvl.pitching
        if rates.get("k_pct") is not None:
            add("stuff", (rates["k_pct"] - b.k_pct) / stat_sd(lvl, "k_pct"), "p_k_pct", f"K% {rates['k_pct']:.1%}")
        if rates.get("bb_pct") is not None:
            add("control", (b.bb_pct - rates["bb_pct"]) / stat_sd(lvl, "bb_pct"), "p_bb_pct", f"BB% {rates['bb_pct']:.1%}")
        if rates.get("hr_pct") is not None:
            add("contact_mgmt", (b.hr_pct - rates["hr_pct"]) / stat_sd(lvl, "hr_pct"), "p_hr_pct", f"HR% {rates['hr_pct']:.1%}")
    return out


def _scouting_evidence(consensus: dict[str, Any], player_type: str) -> list[Evidence]:
    tools = (consensus or {}).get("tools") or {}
    n_reports = max(1, consensus.get("report_count", 1)) if consensus else 1

    def present(*names):
        for name in names:
            t = tools.get(name, {}).get("present")
            if t:
                return t["mean"], t.get("spread", 0.0)
        return None

    out = []

    def add(comp, found, extra_var=0.0, detail=""):
        if found:
            mean, spread = found
            out.append(Evidence(comp, "scouting", mean, 5.0**2 / n_reports + spread**2 + extra_var, detail))

    if player_type == "hitter":
        add("contact", present("hit"), detail="present hit grade")
        pw = present("game_power")
        add("power", pw or (present("raw_power") and (present("raw_power")[0] - 5, present("raw_power")[1])), detail="present game/raw power")
        add("discipline", present("approach"), detail="present approach grade")
        if not present("approach"):
            add("discipline", present("hit"), extra_var=8.0**2, detail="hit grade (approach not graded)")
    else:
        fb = present("fastball", "sinker")
        secondaries = [present(t) for t in ("slider", "sweeper", "curveball", "changeup", "splitter", "cutter")]
        best2 = max((s for s in secondaries if s), default=None, key=lambda s: s[0])
        if fb and best2:
            add("stuff", ((fb[0] + best2[0]) / 2, max(fb[1], best2[1])), detail="present FB + best secondary")
        else:
            add("stuff", fb or best2, extra_var=3.0**2, detail="present pitch grades")
        add("control", present("control", "command"), detail="present control/command")
        add("contact_mgmt", present("command", "control"), extra_var=6.0**2, detail="command as contact-quality proxy")
    return out


def _tracking_evidence(tracking: dict[str, Any], player_type: str) -> list[Evidence]:
    t = tracking or {}
    out = []
    if player_type == "pitcher":
        if t.get("fb_velo_avg"):
            g = 50 + (t["fb_velo_avg"] - 93.0) * 3.75
            if t.get("fb_ivb_avg") is not None:
                g += max(-4.0, min(4.0, (t["fb_ivb_avg"] - 16.0) * 0.5))
            out.append(Evidence("stuff", "tracking", g, 6.0**2, f"FB {t['fb_velo_avg']:.1f} mph" + (f", {t['fb_ivb_avg']:.1f}\" IVB" if t.get("fb_ivb_avg") is not None else "")))
        if t.get("zone_pct") is not None:
            out.append(Evidence("control", "tracking", 50 + (t["zone_pct"] - 0.49) * 120, 7.0**2, f"zone% {t['zone_pct']:.1%}"))
    else:
        if t.get("ev_90th"):
            out.append(Evidence("power", "tracking", 50 + (t["ev_90th"] - 103.5) * 2.2, 5.0**2, f"90th pct EV {t['ev_90th']:.1f} mph"))
        elif t.get("ev_max"):
            out.append(Evidence("power", "tracking", 50 + (t["ev_max"] - 109.0) * 2.0, 7.0**2, f"max EV {t['ev_max']:.1f} mph"))
        if t.get("bat_speed_avg"):
            out.append(Evidence("power", "tracking", 50 + (t["bat_speed_avg"] - 72.0) * 2.5, 7.0**2, f"bat speed {t['bat_speed_avg']:.1f} mph"))
        if t.get("whiff_pct") is not None:
            out.append(Evidence("contact", "tracking", 50 - (t["whiff_pct"] - 0.25) * 90, 7.0**2, f"whiff% {t['whiff_pct']:.1%}"))
        if t.get("chase_pct") is not None:
            out.append(Evidence("discipline", "tracking", 50 - (t["chase_pct"] - 0.28) * 90, 7.0**2, f"chase% {t['chase_pct']:.1%}"))
    return out


def estimate_talent(player_type: str, current_level: str, age: float, seasons: list[dict[str, Any]],
                    scouting: dict[str, Any] | None, tracking: dict[str, Any] | None) -> TalentEstimate:
    lvl = get_level(current_level)
    comps = HITTER_COMPONENTS if player_type == "hitter" else PITCHER_COMPONENTS
    evidence = [Evidence(c, "level prior", lvl.talent_mean, lvl.talent_sd**2, f"typical {lvl.name} player") for c in comps]
    for s in seasons:
        evidence += _season_evidence(s, player_type, age)
    evidence += _scouting_evidence(scouting or {}, player_type)
    evidence += _tracking_evidence(tracking or {}, player_type)
    means, variances = {}, {}
    for c in comps:
        means[c], variances[c] = _combine(evidence, c)
    return TalentEstimate(means, variances, evidence)


def non_bat_value(scouting: dict[str, Any] | None, position: str | None) -> float:
    """Defense, arm, speed and positional value added to a hitter's overall talent."""
    tools = (scouting or {}).get("tools") or {}

    def fut(name):
        t = tools.get(name, {})
        g = t.get("future") or t.get("present")
        return g["mean"] if g else None

    adj = POSITION_ADJ.get((position or "").upper(), 0.0)
    field_g, arm_g, run_g = fut("field") or fut("glove"), fut("arm"), fut("run")
    if field_g:
        adj += (field_g - 50) * 0.15
    if arm_g:
        adj += (arm_g - 50) * 0.04
    if run_g:
        adj += (run_g - 50) * 0.06
    return adj


def overall(components: dict[str, Any], player_type: str, extra: float = 0.0):
    if player_type == "hitter":
        return 0.35 * components["contact"] + 0.40 * components["power"] + 0.25 * components["discipline"] + extra
    return 0.50 * components["stuff"] + 0.30 * components["control"] + 0.20 * components["contact_mgmt"] + extra
