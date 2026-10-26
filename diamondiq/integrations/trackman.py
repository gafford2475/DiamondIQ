"""TrackMan Baseball (V3 CSV) adapter. Also reads Yakkertech/FlightScope exports that use TrackMan column names."""

from __future__ import annotations

from .base import Adapter, NormalizedEvent, Row, flip_name, normalize_pitch_result, normalize_pitch_type, parse_datetime


class TrackmanAdapter(Adapter):
    name = "trackman"
    description = "TrackMan Baseball game/practice CSV (also Yakkertech & TrackMan-compatible exports)"
    signature = ("Pitcher", "Batter", "RelSpeed", "SpinRate", "InducedVertBreak", "PitchCall", "TaggedPitchType")

    def parse_row(self, row: Row, **options):
        when = parse_datetime(row.get("Date"), row.get("Time"))
        pitcher, batter = flip_name(row.get("Pitcher")), flip_name(row.get("Batter"))
        session = row.get("GameID", "GameUID") or options.get("session_label")
        pitch_type = normalize_pitch_type(row.get("TaggedPitchType") or row.get("AutoPitchType"))
        result = normalize_pitch_result(row.get("PitchCall"))
        events = []
        if row.has("RelSpeed"):
            events.append(
                NormalizedEvent(
                    source=self.name, event_type="pitch", role="pitcher",
                    player_name=pitcher, player_external_id=row.get("PitcherId"), opponent_name=batter,
                    occurred_at=when, session_label=session, pitch_type=pitch_type,
                    velocity=row.num("RelSpeed"), spin_rate=row.num("SpinRate"), spin_axis=row.num("SpinAxis"),
                    ivb=row.num("InducedVertBreak"), hb=row.num("HorzBreak"),
                    release_height=row.num("RelHeight"), release_side=row.num("RelSide"), extension=row.num("Extension"),
                    plate_x=row.num("PlateLocSide"), plate_z=row.num("PlateLocHeight"), pitch_result=result,
                    raw=row.data,
                )
            )
        if row.num("ExitSpeed") is not None:
            events.append(
                NormalizedEvent(
                    source=self.name, event_type="batted_ball", role="hitter",
                    player_name=batter, player_external_id=row.get("BatterId"), opponent_name=pitcher,
                    occurred_at=when, session_label=session, pitch_type=pitch_type, velocity=row.num("RelSpeed"),
                    plate_x=row.num("PlateLocSide"), plate_z=row.num("PlateLocHeight"), pitch_result=result,
                    exit_velocity=row.num("ExitSpeed"), launch_angle=row.num("Angle"),
                    spray_angle=row.num("Direction"), distance=row.num("Distance"), raw=row.data,
                )
            )
        return events
