"""Common pieces for tracking-device adapters.

Each adapter turns a vendor export (CSV/JSON rows) into ``NormalizedEvent``s
in shared units: mph, rpm, inches of movement, feet for release and plate
location, degrees for angles, seconds for time.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

PITCH_TYPE_ALIASES = {
    "FF": "FF", "FA": "FF", "FASTBALL": "FF", "4SEAM": "FF", "FOURSEAM": "FF", "FOUR_SEAM": "FF", "4_SEAM_FASTBALL": "FF", "FOUR-SEAM_FASTBALL": "FF",
    "SI": "SI", "SINKER": "SI", "2SEAM": "SI", "TWOSEAM": "SI", "TWO_SEAM": "SI", "FT": "SI", "2_SEAM_FASTBALL": "SI",
    "FC": "FC", "CUTTER": "FC", "CUT_FASTBALL": "FC",
    "SL": "SL", "SLIDER": "SL", "GYRO": "SL",
    "ST": "ST", "SWEEPER": "ST", "SW": "ST",
    "SV": "SV", "SLURVE": "SV",
    "CU": "CU", "CURVEBALL": "CU", "CB": "CU", "KC": "KC", "KNUCKLE_CURVE": "KC",
    "CH": "CH", "CHANGEUP": "CH", "CHANGE_UP": "CH", "CHANGE": "CH",
    "FS": "FS", "SPLITTER": "FS", "SPLIT": "FS", "SPLIT_FINGER": "FS", "FO": "FO", "FORKBALL": "FO",
    "KN": "KN", "KNUCKLEBALL": "KN", "EP": "EP", "EEPHUS": "EP",
}

PITCH_RESULT_ALIASES = {
    "BALLCALLED": "ball", "BALL": "ball", "BLOCKED_BALL": "ball", "BALLINDIRT": "ball", "PITCHOUT": "ball", "BALLINTENTIONAL": "ball",
    "STRIKECALLED": "called_strike", "CALLED_STRIKE": "called_strike",
    "STRIKESWINGING": "swinging_strike", "SWINGING_STRIKE": "swinging_strike", "SWINGING_STRIKE_BLOCKED": "swinging_strike", "MISSED_BUNT": "swinging_strike",
    "FOULBALL": "foul", "FOUL": "foul", "FOULBALLNOTFIELDABLE": "foul", "FOULBALLFIELDABLE": "foul", "FOUL_BUNT": "foul",
    "FOUL_TIP": "foul_tip", "FOULTIP": "foul_tip",
    "INPLAY": "in_play", "HIT_INTO_PLAY": "in_play", "HIT_INTO_PLAY_SCORE": "in_play", "HIT_INTO_PLAY_NO_OUT": "in_play",
    "HITBYPITCH": "hit_by_pitch", "HIT_BY_PITCH": "hit_by_pitch",
}


def norm_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.strip().upper()).strip("_")


def normalize_pitch_type(value: Any) -> str | None:
    if value in (None, "", "Undefined", "Other"):
        return None
    key = norm_key(str(value))
    return PITCH_TYPE_ALIASES.get(key, PITCH_TYPE_ALIASES.get(key.replace("_", ""), key[:4]))


def normalize_pitch_result(value: Any) -> str | None:
    if value in (None, ""):
        return None
    key = norm_key(str(value))
    return PITCH_RESULT_ALIASES.get(key, PITCH_RESULT_ALIASES.get(key.replace("_", ""), key.lower()))


def num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "--", "NA", "N/A", "null", "None", "nan"):
        return None
    s = re.sub(r"[^0-9.\-eE]", "", s)  # strip units like "mph" or "%"
    try:
        return float(s)
    except ValueError:
        return None


def clock_to_degrees(value: Any) -> float | None:
    """Spin direction '1:30' (clock face) to degrees (12:00 = 180, Trackman/Statcast convention)."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return num(s)
    hours = int(m.group(1)) % 12 + int(m.group(2)) / 60
    return round((hours * 30 + 180) % 360, 1)


def parse_datetime(*values: Any) -> dt.datetime | None:
    text = " ".join(str(v).strip() for v in values if v not in (None, ""))
    if not text:
        return None
    fmts = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %H:%M", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d")
    for f in fmts:
        try:
            return dt.datetime.strptime(text, f).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def flip_name(name: Any) -> str | None:
    """'Last, First' -> 'First Last'."""
    if not name:
        return None
    s = str(name).strip()
    if "," in s:
        last, first = (p.strip() for p in s.split(",", 1))
        return f"{first} {last}".strip()
    return s


@dataclass
class NormalizedEvent:
    source: str
    event_type: str  # pitch | batted_ball | swing
    role: str  # pitcher | hitter
    player_name: str | None = None
    player_external_id: str | None = None
    opponent_name: str | None = None
    occurred_at: dt.datetime | None = None
    session_label: str | None = None
    pitch_type: str | None = None
    velocity: float | None = None
    spin_rate: float | None = None
    spin_axis: float | None = None
    spin_efficiency: float | None = None
    ivb: float | None = None
    hb: float | None = None
    release_height: float | None = None
    release_side: float | None = None
    extension: float | None = None
    plate_x: float | None = None
    plate_z: float | None = None
    pitch_result: str | None = None
    exit_velocity: float | None = None
    launch_angle: float | None = None
    spray_angle: float | None = None
    distance: float | None = None
    bat_speed: float | None = None
    attack_angle: float | None = None
    time_to_contact: float | None = None
    rotational_acceleration: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.occurred_at:
            d["occurred_at"] = self.occurred_at.isoformat()
        return d


class Row:
    """Case/spacing-insensitive access to a vendor row."""

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self._idx = {norm_key(k): v for k, v in data.items() if k is not None}

    def get(self, *names: str) -> Any:
        for n in names:
            v = self._idx.get(norm_key(n))
            if v not in (None, ""):
                return v
        return None

    def num(self, *names: str) -> float | None:
        return num(self.get(*names))

    def has(self, *names: str) -> bool:
        return any(norm_key(n) in self._idx for n in names)


def read_rows(content: bytes | str, header_hints: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Read CSV or JSON into a list of dict rows.

    For CSVs with a preamble (Rapsodo, Blast), the header row is the first
    line that contains any of ``header_hints``.
    """
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content.lstrip("﻿")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        return [r for r in data if isinstance(r, dict)]
    lines = text.splitlines()
    start = 0
    if header_hints:
        hints = [norm_key(h) for h in header_hints]
        for i, line in enumerate(lines[:50]):
            if any(h in norm_key(line) for h in hints):
                start = i
                break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [r for r in reader if any(v not in (None, "") for v in r.values())]


class Adapter:
    name: ClassVar[str]
    description: ClassVar[str]
    header_hints: ClassVar[tuple[str, ...]] = ()
    # Columns that, if present, identify this vendor's format.
    signature: ClassVar[tuple[str, ...]] = ()

    def parse(self, content: bytes | str, **options: Any) -> list[NormalizedEvent]:
        rows = read_rows(content, self.header_hints)
        events: list[NormalizedEvent] = []
        for raw in rows:
            events.extend(self.parse_row(Row(raw), **options))
        return events

    def parse_row(self, row: Row, **options: Any) -> list[NormalizedEvent]:  # pragma: no cover - abstract
        raise NotImplementedError

    @classmethod
    def matches(cls, columns: list[str]) -> float:
        keys = {norm_key(c) for c in columns if c}
        if not cls.signature:
            return 0.0
        return sum(norm_key(c) in keys for c in cls.signature) / len(cls.signature)
