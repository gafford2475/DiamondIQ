"""Rapsodo Pitching 2.0 / Hitting 2.0 CSV exports (per-player exports with a header preamble)."""

from __future__ import annotations

from .base import Adapter, NormalizedEvent, Row, clock_to_degrees, normalize_pitch_type, parse_datetime


def _inches_to_feet(v):
    return round(v / 12, 3) if v is not None else None


class RapsodoPitchingAdapter(Adapter):
    name = "rapsodo_pitching"
    description = "Rapsodo Pitching export (velocity, spin, break, release, strike-zone location)"
    header_hints = ("Pitch Type", "Velocity", "Total Spin")
    signature = ("Pitch Type", "Velocity", "Total Spin", "Spin Efficiency (release)", "HB (trajectory)")

    def parse_row(self, row: Row, **options):
        if row.num("Velocity", "Speed") is None:
            return []
        # Prefer induced (spin-based) vertical break when the export has it.
        ivb = row.num("Induced Vertical Break", "VB (spin)", "IVB", "VB (trajectory)")
        hb = row.num("HB (spin)", "HB (trajectory)", "Horizontal Break")
        return [
            NormalizedEvent(
                source=self.name, event_type="pitch", role="pitcher",
                player_name=row.get("Player Name") or options.get("player_name"), player_external_id=row.get("Player ID"),
                occurred_at=parse_datetime(row.get("Date")), session_label=options.get("session_label") or row.get("Session"),
                pitch_type=normalize_pitch_type(row.get("Pitch Type")), velocity=row.num("Velocity", "Speed"),
                spin_rate=row.num("Total Spin", "Spin"), spin_efficiency=row.num("Spin Efficiency (release)", "Spin Efficiency"),
                spin_axis=clock_to_degrees(row.get("Spin Direction", "Spin Axis")), ivb=ivb, hb=hb,
                release_height=row.num("Release Height"), release_side=row.num("Release Side"),
                extension=row.num("Release Extension (ft)", "Release Extension", "Extension"),
                plate_x=_inches_to_feet(row.num("Strike Zone Side")), plate_z=_inches_to_feet(row.num("Strike Zone Height")),
                pitch_result="called_strike" if str(row.get("Is Strike") or "").upper() in ("YES", "Y", "TRUE", "1") else None,
                raw=row.data,
            )
        ]


class RapsodoHittingAdapter(Adapter):
    name = "rapsodo_hitting"
    description = "Rapsodo Hitting export (exit velocity, launch angle, direction, distance)"
    header_hints = ("Exit Velocity", "ExitVelocity", "Launch Angle")
    signature = ("Exit Velocity", "Launch Angle", "Exit Direction", "Distance", "Spin Rate")

    def parse_row(self, row: Row, **options):
        ev = row.num("Exit Velocity", "ExitVelocity", "EV")
        if ev is None:
            return []
        return [
            NormalizedEvent(
                source=self.name, event_type="batted_ball", role="hitter",
                player_name=row.get("Player Name") or options.get("player_name"), player_external_id=row.get("Player ID"),
                occurred_at=parse_datetime(row.get("Date")), session_label=options.get("session_label"),
                velocity=row.num("Pitch Velocity"), exit_velocity=ev, launch_angle=row.num("Launch Angle", "LaunchAngle", "LA"),
                spray_angle=row.num("Exit Direction", "Direction"), distance=row.num("Distance"), raw=row.data,
            )
        ]
