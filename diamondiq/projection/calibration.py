"""Fit the model's priors from the system's own historical data.

Both functions use the delta method: compare the same player in consecutive
seasons, so selection on talent cancels out. Weighting by the harmonic mean
of playing time keeps small samples from dominating.

Feed the outputs back into ``levels.py`` (talent_mean gaps) and
``development.py`` (annual deltas) as data accumulates.
"""

from __future__ import annotations

import pandas as pd

from ..levels import get_level


def _pairs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["player_id", "season"])
    nxt = df.groupby("player_id").shift(-1)
    pairs = df.assign(**{f"next_{c}": nxt[c] for c in ("season", "level", "age", "n", "talent_z")})
    pairs = pairs[pairs["next_season"] == pairs["season"] + 1].copy()
    pairs["w"] = 2 / (1 / pairs["n"] + 1 / pairs["next_n"])
    return pairs


def _with_z(df: pd.DataFrame, stat: str, higher_is_better: bool = True) -> pd.DataFrame:
    """Standardize a rate stat within its level: z = (stat - level mean) / level sd."""
    g = df.groupby("level")[stat]
    z = (df[stat] - g.transform("mean")) / g.transform("std")
    return df.assign(talent_z=z if higher_is_better else -z)


def fit_level_gaps(df: pd.DataFrame, stat: str = "woba", min_pairs: int = 30, higher_is_better: bool = True) -> pd.DataFrame:
    """Estimate how much harder level B is than level A, in talent points.

    df columns: player_id, season, level, age, n (PA or BF), and ``stat``.
    Returns one row per (from_level, to_level) with the implied gap between
    the levels' talent means after removing expected one-year development.
    """
    from .development import annual_delta

    df = _with_z(df.rename(columns={stat: "_stat"}).rename(columns={"_stat": stat}), stat, higher_is_better)
    pairs = _pairs(df)
    pairs = pairs[pairs["level"] != pairs["next_level"]]
    rows = []
    for (a, b), grp in pairs.groupby(["level", "next_level"]):
        if len(grp) < min_pairs:
            continue
        la, lb = get_level(a), get_level(b)
        growth = grp["age"].map(annual_delta).mean()
        # talent_then + growth = talent_now  =>  mean_b + z_b*sd_b = mean_a + z_a*sd_a + growth
        za = (grp["talent_z"] * grp["w"]).sum() / grp["w"].sum()
        zb = (grp["next_talent_z"] * grp["w"]).sum() / grp["w"].sum()
        implied_gap = za * la.talent_sd + growth - zb * lb.talent_sd
        rows.append({
            "from_level": a, "to_level": b, "pairs": len(grp),
            "implied_gap": round(implied_gap, 2), "prior_gap": round(lb.talent_mean - la.talent_mean, 2),
        })
    return pd.DataFrame(rows)


def fit_aging_curve(df: pd.DataFrame, stat: str = "woba", higher_is_better: bool = True, min_pairs: int = 30) -> pd.DataFrame:
    """Same-level consecutive seasons -> average change in talent points by age."""
    df = _with_z(df, stat, higher_is_better)
    pairs = _pairs(df)
    pairs = pairs[pairs["level"] == pairs["next_level"]]
    pairs["sd"] = pairs["level"].map(lambda c: get_level(c).talent_sd)
    pairs["delta"] = (pairs["next_talent_z"] - pairs["talent_z"]) * pairs["sd"]
    pairs["age_bin"] = pairs["age"].round()
    out = pairs.groupby("age_bin").apply(
        lambda g: pd.Series({"pairs": len(g), "delta": (g["delta"] * g["w"]).sum() / g["w"].sum()}), include_groups=False
    ).reset_index()
    return out[out["pairs"] >= min_pairs]
