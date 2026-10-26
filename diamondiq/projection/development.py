"""Aging / development curves on the talent scale.

Expected one-year talent change by age for players who keep playing. Values
are priors shaped like published delta-method aging curves (steep growth
through the early 20s, plateau around 26-28, decline after 30; pitchers peak
a little earlier and decline a little faster). ``calibration.fit_aging_curve``
re-estimates these from the system's own longitudinal data.
"""

from __future__ import annotations

import numpy as np

_AGES = np.array([14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 40])
_HITTER = np.array([3.2, 3.1, 3.0, 2.8, 2.6, 2.4, 2.2, 1.9, 1.5, 1.1, 0.7, 0.4, 0.2, 0.0, -0.2, -0.4, -0.7, -1.0, -1.3, -1.7, -2.1, -2.5, -2.9, -3.6, -4.2])
_PITCHER = np.array([3.2, 3.1, 3.0, 2.8, 2.6, 2.4, 2.1, 1.8, 1.4, 1.0, 0.6, 0.3, 0.0, -0.2, -0.4, -0.7, -1.0, -1.3, -1.6, -2.0, -2.4, -2.8, -3.2, -3.9, -4.5])
# Year-to-year randomness in development (sd, talent points) by age.
_NOISE = np.array([3.0, 3.0, 3.0, 2.9, 2.8, 2.7, 2.6, 2.4, 2.2, 2.0, 1.8, 1.7, 1.6, 1.5, 1.5, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.4, 2.6])

PEAK_AGE = {"hitter": 27, "pitcher": 26}


def annual_delta(age: float, player_type: str = "hitter") -> float:
    curve = _HITTER if player_type == "hitter" else _PITCHER
    return float(np.interp(age, _AGES, curve))


def annual_noise(age: float) -> float:
    return float(np.interp(age, _AGES, _NOISE))


def expected_growth(from_age: float, to_age: float, player_type: str = "hitter") -> float:
    """Expected cumulative talent change between two ages (negative if to_age < from_age)."""
    if from_age is None or to_age is None or abs(to_age - from_age) < 1e-6:
        return 0.0
    sign = 1.0 if to_age > from_age else -1.0
    lo, hi = sorted((from_age, to_age))
    grid = np.linspace(lo, hi, max(2, int((hi - lo) * 12) + 1))
    deltas = np.array([annual_delta(a, player_type) for a in grid])
    return sign * float(np.trapezoid(deltas, grid))


def growth_multiplier(age: float, player_type: str, *, present: float | None = None, future: float | None = None,
                      projectability: float | None = None, makeup: float | None = None,
                      mechanics_score: float | None = None, scout_weight: float = 0.5) -> tuple[float, list[str]]:
    """Scale the generic curve's *growth* for this player and say why.

    - Scout future vs present grade: blends the scout's implied growth with the curve's.
    - Projectability (physical projection remaining) matters most before ~23.
    - Makeup / work ethic and movement efficiency (biomechanics) nudge growth.
    Only positive (pre-peak) growth is scaled; decline is left to the curve.
    """
    reasons = []
    mult = 1.0
    model_growth = expected_growth(age, max(age, PEAK_AGE[player_type]), player_type)
    if present is not None and future is not None and model_growth > 0.5:
        scout_growth = max(0.0, future - present)
        m = (scout_weight * scout_growth + (1 - scout_weight) * model_growth) / model_growth
        mult *= m
        reasons.append(f"scouts project +{scout_growth:.0f} grade points vs +{model_growth:.0f} typical (x{m:.2f})")
    # A future grade already bakes in physical projection, so only use projectability without one.
    if projectability is not None and age < 23 and future is None:
        m = 1 + 0.2 * (projectability - 50) / 20 * (23 - age) / 6
        mult *= m
        reasons.append(f"projectability {projectability:.0f} (x{m:.2f})")
    if makeup is not None:
        m = 1 + 0.1 * (makeup - 50) / 20
        mult *= m
        reasons.append(f"makeup {makeup:.0f} (x{m:.2f})")
    if mechanics_score is not None:
        m = 1 + 0.12 * (mechanics_score - 70) / 30
        mult *= m
        reasons.append(f"mechanics score {mechanics_score:.0f} (x{m:.2f})")
    return float(np.clip(mult, 0.3, 2.0)), reasons
