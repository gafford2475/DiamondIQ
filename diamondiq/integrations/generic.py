"""Configurable adapter for any other device (Pocket Radar, FlightScope, Stalker, PitchLogic, in-house tools...).

Pass a ``column_map`` of normalized field -> vendor column, plus optional unit
conversions, e.g.::

    {"event_type": "pitch", "role": "pitcher",
     "column_map": {"player_name": "Athlete", "velocity": "Speed (km/h)", "spin_rate": "RPM"},
     "units": {"velocity": "kph"}}
"""

from __future__ import annotations

from dataclasses import fields

from .base import Adapter, NormalizedEvent, Row, normalize_pitch_result, normalize_pitch_type, parse_datetime

UNIT_FACTORS = {"kph": 0.621371, "m_s": 2.23694, "cm": 1 / 2.54, "m": 3.28084, "in_to_ft": 1 / 12, "ft_to_in": 12.0}
_NUMERIC = {f.name for f in fields(NormalizedEvent)} - {
    "source", "event_type", "role", "player_name", "player_external_id", "opponent_name", "occurred_at",
    "session_label", "pitch_type", "pitch_result", "raw",
}


class GenericAdapter(Adapter):
    name = "generic"
    description = "Any CSV/JSON export, mapped with a column_map (and optional unit conversions)"

    def parse_row(self, row: Row, column_map: dict[str, str] | None = None, units: dict[str, str] | None = None,
                  event_type: str = "pitch", role: str | None = None, **options):
        if not column_map:
            raise ValueError("generic adapter requires a column_map")
        units = units or {}
        values = {}
        for target, col in column_map.items():
            if target in _NUMERIC:
                v = row.num(col)
                if v is not None and target in units:
                    v = v * UNIT_FACTORS[units[target]]
                values[target] = v
            else:
                values[target] = row.get(col)
        if not any(values.get(k) is not None for k in _NUMERIC):
            return []
        values["occurred_at"] = parse_datetime(values.get("occurred_at")) if values.get("occurred_at") else None
        values["pitch_type"] = normalize_pitch_type(values.get("pitch_type"))
        values["pitch_result"] = normalize_pitch_result(values.get("pitch_result"))
        values.setdefault("player_name", options.get("player_name"))
        values.setdefault("session_label", options.get("session_label"))
        return [
            NormalizedEvent(
                source=options.get("source_name", self.name), event_type=event_type,
                role=role or ("pitcher" if event_type == "pitch" else "hitter"), raw=row.data, **values,
            )
        ]
