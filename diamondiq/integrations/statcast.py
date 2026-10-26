"""Hawk-Eye / Statcast (Baseball Savant CSV or JSON records using Statcast field names)."""

from __future__ import annotations

import math

from .base import Adapter, NormalizedEvent, Row, flip_name, normalize_pitch_result, normalize_pitch_type, parse_datetime


def _spray_from_hc(hc_x, hc_y):
    """Savant hit coordinates -> spray angle in degrees (negative = pull side for RHH, 0 = center)."""
    if hc_x is None or hc_y is None:
        return None
    return round(math.degrees(math.atan2(hc_x - 125.42, 198.27 - hc_y)), 1)


class StatcastAdapter(Adapter):
    name = "hawkeye"
    description = "Hawk-Eye / Statcast pitch-level data (Baseball Savant CSV or JSON with Statcast field names)"
    signature = ("release_speed", "release_spin_rate", "pfx_x", "pfx_z", "plate_x", "plate_z", "launch_speed")

    def parse_row(self, row: Row, **options):
        when = parse_datetime(row.get("game_date"))
        session = str(row.get("game_pk") or "") or options.get("session_label")
        result = normalize_pitch_result(row.get("description"))
        pitch_type = normalize_pitch_type(row.get("pitch_type"))
        pfx_x, pfx_z = row.num("pfx_x"), row.num("pfx_z")
        # Savant's player_name is the pitcher; batter is an MLBAM id only.
        events = [
            NormalizedEvent(
                source=self.name, event_type="pitch", role="pitcher",
                player_name=flip_name(row.get("player_name", "pitcher_name")), player_external_id=str(row.get("pitcher") or "") or None,
                occurred_at=when, session_label=session, pitch_type=pitch_type,
                velocity=row.num("release_speed"), spin_rate=row.num("release_spin_rate"), spin_axis=row.num("spin_axis"),
                ivb=round(pfx_z * 12, 2) if pfx_z is not None else None, hb=round(pfx_x * 12, 2) if pfx_x is not None else None,
                release_height=row.num("release_pos_z"), release_side=row.num("release_pos_x"), extension=row.num("release_extension"),
                plate_x=row.num("plate_x"), plate_z=row.num("plate_z"), pitch_result=result, raw=row.data,
            )
        ]
        if row.num("launch_speed") is not None or row.num("bat_speed") is not None:
            events.append(
                NormalizedEvent(
                    source=self.name, event_type="batted_ball" if row.num("launch_speed") is not None else "swing", role="hitter",
                    player_name=flip_name(row.get("batter_name")), player_external_id=str(row.get("batter") or "") or None,
                    occurred_at=when, session_label=session, pitch_type=pitch_type, velocity=row.num("release_speed"),
                    plate_x=row.num("plate_x"), plate_z=row.num("plate_z"), pitch_result=result,
                    exit_velocity=row.num("launch_speed"), launch_angle=row.num("launch_angle"),
                    spray_angle=_spray_from_hc(row.num("hc_x"), row.num("hc_y")), distance=row.num("hit_distance_sc"),
                    bat_speed=row.num("bat_speed"), raw=row.data,
                )
            )
        return events
