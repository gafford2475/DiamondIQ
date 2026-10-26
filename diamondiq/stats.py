"""Derive rate stats from counting stats.

Hitting keys: pa, ab, h, 2b, 3b, hr, bb, ibb, so, hbp, sf, sh, sb, cs
Pitching keys: bf, outs (or ip as 6.1 notation), h, er, r, bb, so, hr, hbp, gb, fb
"""

from __future__ import annotations

from typing import Any

# Linear weights for an approximate, level-neutral wOBA.
WOBA_WEIGHTS = {"bb": 0.69, "hbp": 0.72, "1b": 0.88, "2b": 1.25, "3b": 1.58, "hr": 2.03}
FIP_CONSTANT = 3.15


def _n(d: dict[str, Any], k: str) -> float:
    v = d.get(k)
    return float(v) if v not in (None, "") else 0.0


def _div(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def ip_to_outs(ip: float | str) -> int:
    """Baseball IP notation (6.2 = 6 and 2/3 innings) to outs."""
    whole, _, frac = str(ip).partition(".")
    return int(whole or 0) * 3 + (int(frac[0]) if frac else 0)


def hitting_rates(s: dict[str, Any]) -> dict[str, float | None]:
    ab, h, d, t, hr = _n(s, "ab"), _n(s, "h"), _n(s, "2b"), _n(s, "3b"), _n(s, "hr")
    bb, ibb, hbp, sf, sh, so = _n(s, "bb"), _n(s, "ibb"), _n(s, "hbp"), _n(s, "sf"), _n(s, "sh"), _n(s, "so")
    pa = _n(s, "pa") or (ab + bb + hbp + sf + sh)
    singles = h - d - t - hr
    tb = singles + 2 * d + 3 * t + 4 * hr
    avg = _div(h, ab)
    obp = _div(h + bb + hbp, ab + bb + hbp + sf)
    slg = _div(tb, ab)
    woba_den = ab + bb - ibb + sf + hbp
    woba_num = (
        WOBA_WEIGHTS["bb"] * (bb - ibb)
        + WOBA_WEIGHTS["hbp"] * hbp
        + WOBA_WEIGHTS["1b"] * singles
        + WOBA_WEIGHTS["2b"] * d
        + WOBA_WEIGHTS["3b"] * t
        + WOBA_WEIGHTS["hr"] * hr
    )
    babip_den = ab - so - hr + sf
    return {
        "pa": pa,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": round(obp + slg, 4) if obp is not None and slg is not None else None,
        "iso": round(slg - avg, 4) if slg is not None and avg is not None else None,
        "k_pct": _div(so, pa),
        "bb_pct": _div(bb, pa),
        "hr_pct": _div(hr, pa),
        "babip": _div(h - hr, babip_den),
        "woba": _div(woba_num, woba_den),
        "sb_success": _div(_n(s, "sb"), _n(s, "sb") + _n(s, "cs")),
    }


def pitching_rates(s: dict[str, Any]) -> dict[str, float | None]:
    outs = _n(s, "outs") or (ip_to_outs(s["ip"]) if s.get("ip") not in (None, "") else 0)
    ip = outs / 3
    h, er, bb, so, hr, hbp = _n(s, "h"), _n(s, "er"), _n(s, "bb"), _n(s, "so"), _n(s, "hr"), _n(s, "hbp")
    bf = _n(s, "bf") or (outs + h + bb + hbp)
    gb, fb = _n(s, "gb"), _n(s, "fb")
    return {
        "ip": round(ip, 2),
        "bf": bf,
        "era": _div(er * 9, ip),
        "whip": _div(h + bb, ip),
        "k_pct": _div(so, bf),
        "bb_pct": _div(bb, bf),
        "k_minus_bb_pct": _div(so - bb, bf),
        "hr_pct": _div(hr, bf),
        "k_per_9": _div(so * 9, ip),
        "bb_per_9": _div(bb * 9, ip),
        "fip": round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT, 3) if ip else None,
        "gb_pct": _div(gb, gb + fb) if gb + fb else None,
    }


def rates(kind: str, s: dict[str, Any]) -> dict[str, float | None]:
    return hitting_rates(s) if kind == "hitting" else pitching_rates(s)
