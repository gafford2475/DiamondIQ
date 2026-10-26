"""HitTrax session CSV export."""

from __future__ import annotations

from .base import Adapter, NormalizedEvent, Row, parse_datetime


class HitTraxAdapter(Adapter):
    name = "hittrax"
    description = "HitTrax session export (Velo, LA, Dist, Horiz. Angle, result)"
    signature = ("Velo", "LA", "Dist", "Res", "Type", "Horiz. Angle")

    def parse_row(self, row: Row, **options):
        ev = row.num("Velo", "Exit Velo")
        if ev is None:
            return []
        return [
            NormalizedEvent(
                source=self.name, event_type="batted_ball", role="hitter",
                player_name=row.get("Batter", "User", "Player") or options.get("player_name"),
                occurred_at=parse_datetime(row.get("Date")), session_label=options.get("session_label") or row.get("Session"),
                velocity=row.num("Pitch"), exit_velocity=ev, launch_angle=row.num("LA"),
                spray_angle=row.num("Horiz. Angle", "Horiz Angle", "HorizAngle"), distance=row.num("Dist"),
                pitch_result="in_play", raw=row.data,
            )
        ]
