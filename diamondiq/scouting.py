"""20-80 scouting scale helpers and report aggregation."""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any

HITTER_TOOLS = ("hit", "raw_power", "game_power", "approach", "run", "arm", "field", "glove", "range", "hands", "pop_time_grade")
PITCHER_TOOLS = (
    "fastball", "sinker", "cutter", "slider", "sweeper", "curveball", "changeup", "splitter", "knuckleball",
    "control", "command", "deception", "delivery", "athleticism", "pitchability",
)
FASTBALLS = ("fastball", "sinker")
SECONDARIES = ("cutter", "slider", "sweeper", "curveball", "changeup", "splitter", "knuckleball")

GRADE_LABELS = [
    (80, "Elite / top of the scale"),
    (70, "Plus-plus"),
    (65, "Plus / well above average"),
    (60, "Plus"),
    (55, "Above average"),
    (50, "Average (MLB)"),
    (45, "Fringe average"),
    (40, "Below average"),
    (30, "Well below average"),
    (20, "Poor"),
]


def grade_label(grade: float) -> str:
    for threshold, label in GRADE_LABELS:
        if grade >= threshold:
            return label
    return "Poor"


def validate_grade(value: Any) -> int:
    g = int(round(float(value)))
    if not 20 <= g <= 80:
        raise ValueError(f"grade {value} outside the 20-80 scale")
    return g


def normalize_tool_grades(tool_grades: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Accept {"hit": 55} or {"hit": {"present": 40, "future": 55}} and normalize."""
    out: dict[str, dict[str, int]] = {}
    for tool, val in (tool_grades or {}).items():
        key = tool.strip().lower().replace(" ", "_")
        if isinstance(val, dict):
            entry = {k: validate_grade(v) for k, v in val.items() if k in ("present", "future") and v is not None}
        else:
            entry = {"future": validate_grade(val)}
        if entry:
            out[key] = entry
    return out


def future_grade(tool_grades: dict[str, Any], tool: str) -> float | None:
    entry = tool_grades.get(tool)
    if not entry:
        return None
    return entry.get("future", entry.get("present"))


def present_grade(tool_grades: dict[str, Any], tool: str) -> float | None:
    entry = tool_grades.get(tool)
    if not entry:
        return None
    return entry.get("present")


def suggested_ofp(report_type: str, tool_grades: dict[str, Any]) -> float | None:
    """Rough OFP from future tool grades when the scout did not supply one."""
    g = normalize_tool_grades(tool_grades)
    if report_type == "pitcher":
        fb = max((future_grade(g, t) or 0 for t in FASTBALLS), default=0)
        secondaries = sorted((future_grade(g, t) for t in SECONDARIES if future_grade(g, t)), reverse=True)
        cmd = future_grade(g, "command") or future_grade(g, "control")
        parts = [(fb, 0.35)] if fb else []
        parts += list(zip(secondaries[:2], (0.25, 0.15), strict=False))
        if cmd:
            parts.append((cmd, 0.25))
    else:
        weights = {"hit": 0.30, "game_power": 0.25, "raw_power": 0.05, "run": 0.10, "field": 0.20, "arm": 0.10}
        parts = [(future_grade(g, t), w) for t, w in weights.items() if future_grade(g, t)]
    if not parts:
        return None
    total_w = sum(w for _, w in parts)
    return round(sum(v * w for v, w in parts) / total_w, 1)


def consensus(reports: Iterable[Any]) -> dict[str, Any]:
    """Aggregate multiple scouts' reports: per-tool mean/min/max and spread.

    Recent reports count more (weights 1.0, 0.8, 0.64 ... by recency).
    """
    reports = sorted(reports, key=lambda r: r.report_date, reverse=True)
    tools: dict[str, dict[str, list[tuple[float, float]]]] = {}
    ofps, projs, makeups = [], [], []
    for i, r in enumerate(reports):
        w = 0.8**i
        for tool, entry in normalize_tool_grades(r.tool_grades).items():
            for kind, val in entry.items():
                tools.setdefault(tool, {}).setdefault(kind, []).append((val, w))
        ofp = r.ofp or suggested_ofp(r.report_type, r.tool_grades)
        if ofp:
            ofps.append((ofp, w))
        if r.projectability:
            projs.append((r.projectability, w))
        if r.makeup:
            makeups.append((r.makeup, w))

    def wmean(pairs):
        return round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 1) if pairs else None

    tool_summary = {}
    for tool, kinds in tools.items():
        tool_summary[tool] = {}
        for kind, pairs in kinds.items():
            vals = [v for v, _ in pairs]
            tool_summary[tool][kind] = {
                "mean": wmean(pairs),
                "min": min(vals),
                "max": max(vals),
                "spread": round(statistics.pstdev(vals), 1) if len(vals) > 1 else 0.0,
                "n": len(vals),
            }
    return {
        "report_count": len(reports),
        "scouts": sorted({r.scout_name for r in reports}),
        "tools": tool_summary,
        "ofp": wmean(ofps),
        "projectability": wmean(projs),
        "makeup": wmean(makeups),
    }
