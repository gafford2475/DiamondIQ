"""Catalog of baseball competition levels.

Every level is placed on a single *talent scale* that lines up with the
20-80 scouting scale: 50 is an average MLB regular. Amateur and minor league
levels sit lower on the same scale, so a player's talent can be compared,
translated, and projected across any level from high school to MLB.

The numbers here are informed priors, not fitted values. They are meant to be
recalibrated once the system has historical data (see
``projection/calibration.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LevelCategory(str, Enum):
    HIGH_SCHOOL = "high_school"
    TRAVEL = "travel_showcase"
    JUCO = "junior_college"
    COLLEGE = "four_year_college"
    SUMMER = "summer_collegiate"
    MINORS = "affiliated_minors"
    MLB = "mlb"
    INDEPENDENT = "independent"
    INTERNATIONAL = "international_pro"


@dataclass(frozen=True)
class HitterBaseline:
    """League-average rate stats for full-time hitters at a level."""

    k_pct: float
    bb_pct: float
    iso: float
    avg: float
    woba: float


@dataclass(frozen=True)
class PitcherBaseline:
    """League-average rate stats for pitchers at a level (per batter faced)."""

    k_pct: float
    bb_pct: float
    hr_pct: float
    era: float


@dataclass(frozen=True)
class Level:
    code: str
    name: str
    category: LevelCategory
    talent_mean: float
    talent_sd: float
    typical_age: float
    min_age: int
    max_age: int | None
    hitting: HitterBaseline
    pitching: PitcherBaseline
    # Whether a player can be "assigned" to this level as a primary level in
    # projections (summer leagues and showcases are supplemental).
    primary: bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def hold_own_threshold(self) -> float:
        """Talent needed to be a playable (slightly below-average) regular."""
        return self.talent_mean - 0.5 * self.talent_sd

    @property
    def is_amateur(self) -> bool:
        return self.category in {
            LevelCategory.HIGH_SCHOOL,
            LevelCategory.TRAVEL,
            LevelCategory.JUCO,
            LevelCategory.COLLEGE,
            LevelCategory.SUMMER,
        }


# Spread of rate stats among regulars. Amateur environments are noisier.
STAT_SD = {"k_pct": 0.060, "bb_pct": 0.030, "iso": 0.060, "avg": 0.035, "woba": 0.038, "hr_pct": 0.010}
AMATEUR_SD_MULT = 1.25


def _lvl(code, name, cat, mean, sd, age, min_age, max_age, hit, pit, primary=True, aliases=()):
    return Level(
        code=code,
        name=name,
        category=cat,
        talent_mean=mean,
        talent_sd=sd,
        typical_age=age,
        min_age=min_age,
        max_age=max_age,
        hitting=HitterBaseline(*hit),
        pitching=PitcherBaseline(*pit),
        primary=primary,
        aliases=tuple(aliases),
    )


C = LevelCategory
_LEVELS: list[Level] = [
    #    code        name                         category        mean  sd   age  min max   hitting (K, BB, ISO, AVG, wOBA)       pitching (K, BB, HR, ERA)
    _lvl("HS_JV", "High School JV", C.HIGH_SCHOOL, 14, 7, 15.0, 13, 18, (0.17, 0.12, 0.080, 0.290, 0.360), (0.17, 0.13, 0.008, 4.80)),
    _lvl("HS", "High School Varsity", C.HIGH_SCHOOL, 20, 7, 16.5, 14, 19, (0.16, 0.12, 0.120, 0.315, 0.385), (0.20, 0.11, 0.010, 3.90), aliases=("HIGH_SCHOOL", "VARSITY")),
    _lvl("SHOWCASE", "Travel / Showcase (elite HS)", C.TRAVEL, 28, 6, 17.0, 14, 19, (0.21, 0.10, 0.110, 0.270, 0.340), (0.24, 0.11, 0.010, 3.60), primary=False, aliases=("TRAVEL", "PG")),
    _lvl("JUCO_D3", "NJCAA Division III", C.JUCO, 23, 7, 19.5, 17, 23, (0.17, 0.11, 0.120, 0.295, 0.370), (0.18, 0.12, 0.016, 5.60)),
    _lvl("JUCO_D2", "NJCAA Division II", C.JUCO, 25, 7, 19.5, 17, 23, (0.17, 0.11, 0.130, 0.300, 0.375), (0.19, 0.12, 0.017, 5.40)),
    _lvl("JUCO", "NJCAA Division I / CCCAA", C.JUCO, 28, 7, 19.5, 17, 23, (0.17, 0.11, 0.135, 0.300, 0.375), (0.20, 0.12, 0.018, 5.20), aliases=("JUCO_D1", "NJCAA", "CCCAA")),
    _lvl("NCAA_D3", "NCAA Division III", C.COLLEGE, 25, 7, 20.5, 17, 24, (0.17, 0.11, 0.120, 0.290, 0.365), (0.18, 0.11, 0.015, 5.30), aliases=("D3",)),
    _lvl("NAIA", "NAIA", C.COLLEGE, 27, 7, 20.5, 17, 24, (0.17, 0.11, 0.140, 0.295, 0.375), (0.19, 0.12, 0.018, 5.50)),
    _lvl("NCAA_D2", "NCAA Division II", C.COLLEGE, 29, 7, 20.5, 17, 24, (0.17, 0.11, 0.140, 0.290, 0.370), (0.20, 0.11, 0.018, 5.30), aliases=("D2",)),
    _lvl("NCAA_D1", "NCAA Division I", C.COLLEGE, 33, 7, 20.5, 17, 24, (0.19, 0.11, 0.150, 0.280, 0.365), (0.22, 0.11, 0.020, 5.40), aliases=("D1",)),
    _lvl("NCAA_D1_P4", "NCAA Division I (Power conference)", C.COLLEGE, 36, 6, 20.5, 17, 24, (0.20, 0.11, 0.165, 0.280, 0.370), (0.24, 0.11, 0.022, 5.20), aliases=("SEC", "ACC", "BIG12", "BIG10")),
    _lvl("CAPE", "Cape Cod League", C.SUMMER, 37, 6, 20.5, 17, 24, (0.23, 0.11, 0.100, 0.240, 0.310), (0.25, 0.11, 0.012, 3.40), primary=False, aliases=("CCBL",)),
    _lvl("SUMMER", "Summer Collegiate (non-Cape)", C.SUMMER, 30, 7, 20.0, 17, 24, (0.20, 0.11, 0.120, 0.265, 0.345), (0.22, 0.12, 0.014, 4.30), primary=False, aliases=("NWL", "PROSPECT_LEAGUE", "MLB_DRAFT_LEAGUE")),
    _lvl("ROOKIE", "Rookie / Complex (ACL, FCL, DSL)", C.MINORS, 34, 6, 19.5, 16, 26, (0.24, 0.12, 0.120, 0.245, 0.325), (0.24, 0.12, 0.015, 4.70), aliases=("ACL", "FCL", "DSL", "CPX")),
    _lvl("A", "Single-A", C.MINORS, 37, 6, 21.0, 17, 27, (0.24, 0.115, 0.125, 0.240, 0.320), (0.25, 0.115, 0.018, 4.40), aliases=("LOW_A",)),
    _lvl("A_PLUS", "High-A", C.MINORS, 40, 6, 22.5, 18, 28, (0.24, 0.105, 0.140, 0.240, 0.320), (0.25, 0.105, 0.022, 4.20), aliases=("HIGH_A", "A+")),
    _lvl("AA", "Double-A", C.MINORS, 43, 6, 24.0, 19, 30, (0.23, 0.100, 0.150, 0.245, 0.320), (0.24, 0.100, 0.025, 4.30)),
    _lvl("AAA", "Triple-A", C.MINORS, 46, 6, 26.0, 19, 36, (0.22, 0.105, 0.170, 0.255, 0.335), (0.23, 0.105, 0.030, 4.90)),
    _lvl("MLB", "Major League Baseball", C.MLB, 50, 6, 28.0, 19, None, (0.225, 0.083, 0.160, 0.245, 0.315), (0.225, 0.083, 0.030, 4.20)),
    _lvl("INDY_TOP", "Independent (Atlantic League)", C.INDEPENDENT, 41, 6, 27.0, 20, None, (0.21, 0.095, 0.150, 0.265, 0.335), (0.21, 0.095, 0.028, 4.90), aliases=("ATLANTIC",)),
    _lvl("INDY", "Independent (Frontier / American Assoc.)", C.INDEPENDENT, 36, 6, 25.5, 20, None, (0.21, 0.100, 0.145, 0.265, 0.340), (0.21, 0.100, 0.026, 4.80), aliases=("FRONTIER", "AMERICAN_ASSOCIATION", "PIONEER")),
    _lvl("NPB", "Nippon Professional Baseball", C.INTERNATIONAL, 46, 6, 28.0, 18, None, (0.20, 0.085, 0.120, 0.250, 0.310), (0.20, 0.085, 0.022, 3.30), primary=False),
    _lvl("KBO", "Korea Baseball Organization", C.INTERNATIONAL, 42, 6, 28.0, 18, None, (0.18, 0.095, 0.140, 0.275, 0.345), (0.18, 0.095, 0.025, 4.60), primary=False),
    _lvl("LMB", "Liga Mexicana de Béisbol", C.INTERNATIONAL, 40, 6, 29.0, 18, None, (0.18, 0.095, 0.160, 0.290, 0.360), (0.18, 0.095, 0.030, 5.50), primary=False),
]

LEVELS: dict[str, Level] = {lvl.code: lvl for lvl in _LEVELS}
_ALIASES: dict[str, str] = {}
for _l in _LEVELS:
    _ALIASES[_l.code] = _l.code
    for _a in _l.aliases:
        _ALIASES[_a] = _l.code

# The affiliated pro ladder, lowest to highest.
PRO_LADDER = ["ROOKIE", "A", "A_PLUS", "AA", "AAA", "MLB"]


def get_level(code: str) -> Level:
    key = code.strip().upper().replace(" ", "_").replace("-", "_")
    if key not in _ALIASES:
        raise KeyError(f"Unknown level '{code}'. Known: {sorted(LEVELS)}")
    return LEVELS[_ALIASES[key]]


def stat_sd(level: Level, stat: str) -> float:
    sd = STAT_SD[stat]
    return sd * AMATEUR_SD_MULT if level.is_amateur else sd


def eligible_primary_levels(age: float, pathway: str = "auto") -> list[Level]:
    """Primary levels a player of ``age`` could realistically be assigned to.

    pathway: "auto" | "college" | "juco" | "pro" | "high_school"
    """
    out = []
    for lvl in _LEVELS:
        if not lvl.primary or lvl.category == LevelCategory.INTERNATIONAL:
            continue
        if age < lvl.min_age or (lvl.max_age is not None and age > lvl.max_age):
            continue
        cat = lvl.category
        if age < 18:
            if cat != LevelCategory.HIGH_SCHOOL:
                continue
        elif cat == LevelCategory.HIGH_SCHOOL:
            continue
        if pathway == "college" and cat == LevelCategory.JUCO:
            continue
        if pathway == "juco" and cat == LevelCategory.COLLEGE and age < 20:
            continue
        if pathway in ("college", "juco") and age < 21 and cat in (LevelCategory.MINORS, LevelCategory.MLB, LevelCategory.INDEPENDENT):
            continue  # draft-eligibility: four-year players are eligible after junior year / age 21
        if pathway == "pro" and cat in (LevelCategory.COLLEGE, LevelCategory.JUCO) and age >= 18:
            continue
        if cat == LevelCategory.INDEPENDENT and age < 22:
            continue
        out.append(lvl)
    return out


def assign_level(talent: float, age: float, pathway: str = "auto") -> Level | None:
    """Highest primary level where the player can hold their own.

    Returns ``None`` when the player falls out of organized baseball.
    """
    candidates = eligible_primary_levels(age, pathway)
    fits = [lvl for lvl in candidates if talent >= lvl.hold_own_threshold]
    if fits:
        return max(fits, key=lambda lvl: lvl.talent_mean)
    # Under-18s always have a high school level to play at.
    if age < 18 and candidates:
        return min(candidates, key=lambda lvl: lvl.talent_mean)
    return None


def all_levels() -> list[Level]:
    return list(_LEVELS)
