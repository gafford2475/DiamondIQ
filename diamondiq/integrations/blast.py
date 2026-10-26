"""Blast Motion (and similar bat-sensor) swing exports. Diamond Kinetics exports map the same way."""

from __future__ import annotations

from .base import Adapter, NormalizedEvent, Row, parse_datetime


class BlastAdapter(Adapter):
    name = "blast"
    description = "Blast Motion / bat-sensor swing export (bat speed, attack angle, time to contact)"
    header_hints = ("Bat Speed",)
    signature = ("Bat Speed (mph)", "Attack Angle (deg)", "Time to Contact (sec)", "Rotational Acceleration (g)", "On Plane Efficiency (%)")

    def parse_row(self, row: Row, **options):
        bs = row.num("Bat Speed (mph)", "Bat Speed", "Swing Speed")
        if bs is None:
            return []
        return [
            NormalizedEvent(
                source=self.name, event_type="swing", role="hitter",
                player_name=row.get("Player", "Name") or options.get("player_name"),
                occurred_at=parse_datetime(row.get("Date")), session_label=options.get("session_label"),
                bat_speed=bs, attack_angle=row.num("Attack Angle (deg)", "Attack Angle"),
                time_to_contact=row.num("Time to Contact (sec)", "Time to Contact"),
                rotational_acceleration=row.num("Rotational Acceleration (g)", "Rotational Acceleration"),
                raw=row.data,
            )
        ]
