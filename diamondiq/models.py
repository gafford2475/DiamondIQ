"""Relational data model.

Level codes are stored as strings that resolve through ``levels.get_level`` so
the same tables serve high school, college, pro and international players.
Flexible, source-specific payloads (scouting tool grades, raw device rows,
biomechanics metrics) live in JSON columns so new tools and devices do not
require migrations.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


watchlist_players = Table(
    "watchlist_players",
    Base.metadata,
    Column("watchlist_id", ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True),
    Column("player_id", ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    birth_date: Mapped[dt.date | None] = mapped_column(Date)
    bats: Mapped[str | None] = mapped_column(String(1))  # L / R / S
    throws: Mapped[str | None] = mapped_column(String(1))  # L / R
    height_in: Mapped[float | None] = mapped_column(Float)
    weight_lb: Mapped[float | None] = mapped_column(Float)
    primary_position: Mapped[str | None] = mapped_column(String(4))  # P, C, 1B, SS, CF, ...
    player_type: Mapped[str] = mapped_column(String(10), default="hitter")  # hitter | pitcher | two_way
    current_level: Mapped[str | None] = mapped_column(String(20))
    current_team: Mapped[str | None] = mapped_column(String(120))
    grad_year: Mapped[int | None] = mapped_column(Integer)
    hometown: Mapped[str | None] = mapped_column(String(120))
    commitment: Mapped[str | None] = mapped_column(String(120))
    # IDs in outside systems, e.g. {"trackman": "1234", "mlbam": "660271", "rapsodo": "abc"}
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scouting_reports: Mapped[list[ScoutingReport]] = relationship(back_populates="player", cascade="all, delete-orphan")
    stat_lines: Mapped[list[StatLine]] = relationship(back_populates="player", cascade="all, delete-orphan")
    tracking_events: Mapped[list[TrackingEvent]] = relationship(back_populates="player", cascade="all, delete-orphan")
    video_analyses: Mapped[list[VideoAnalysis]] = relationship(back_populates="player", cascade="all, delete-orphan")
    measurements: Mapped[list[PhysicalMeasurement]] = relationship(back_populates="player", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def age_on(self, when: dt.date | None = None) -> float | None:
        if not self.birth_date:
            return None
        when = when or dt.date.today()
        return round((when - self.birth_date).days / 365.25, 2)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    players: Mapped[list[Player]] = relationship(secondary=watchlist_players)


class ScoutingReport(Base):
    """A scout's evaluation. Grades use the 20-80 scale (present and future)."""

    __tablename__ = "scouting_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    scout_name: Mapped[str] = mapped_column(String(120))
    report_date: Mapped[dt.date] = mapped_column(Date)
    level_seen: Mapped[str | None] = mapped_column(String(20))
    event: Mapped[str | None] = mapped_column(String(200))  # game, showcase, workout, video
    report_type: Mapped[str] = mapped_column(String(10))  # hitter | pitcher
    # {"hit": {"present": 40, "future": 55}, "raw_power": {...}, "fastball": {...}, ...}
    tool_grades: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Objective numbers observed by the scout, e.g. {"sixty_time": 6.7, "fb_velo_low": 90, "fb_velo_high": 93, "pop_time": 1.95}
    measurables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ofp: Mapped[float | None] = mapped_column(Float)  # overall future potential
    risk: Mapped[str | None] = mapped_column(String(20))  # low | medium | high | extreme
    role_projection: Mapped[str | None] = mapped_column(String(120))
    projectability: Mapped[int | None] = mapped_column(Integer)  # 20-80: physical projection remaining
    makeup: Mapped[int | None] = mapped_column(Integer)  # 20-80
    physical_description: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    player: Mapped[Player] = relationship(back_populates="scouting_reports")


class StatLine(Base):
    """Season (or split) counting stats at one level. Rates are derived on read."""

    __tablename__ = "stat_lines"
    __table_args__ = (UniqueConstraint("player_id", "season", "level", "team", "kind", "split", name="uq_statline"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(20))
    team: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))  # hitting | pitching
    split: Mapped[str] = mapped_column(String(30), default="overall")
    source: Mapped[str | None] = mapped_column(String(60))  # manual, maxpreps, d1baseball, fangraphs, mlb_stats_api...
    # Counting stats; keys documented in stats.py (pa, ab, h, 2b, 3b, hr, bb, so, hbp, sf, sb, cs / bf, outs, h, er, bb, so, hr, hbp ...)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    player: Mapped[Player] = relationship(back_populates="stat_lines")


class PhysicalMeasurement(Base):
    __tablename__ = "physical_measurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    measured_on: Mapped[dt.date] = mapped_column(Date)
    height_in: Mapped[float | None] = mapped_column(Float)
    weight_lb: Mapped[float | None] = mapped_column(Float)
    wingspan_in: Mapped[float | None] = mapped_column(Float)
    # sixty_time, home_to_first, pop_time, exit_velo_max, inf_velo, of_velo, broad_jump, vertical, grip ...
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    player: Mapped[Player] = relationship(back_populates="measurements")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_date: Mapped[dt.date] = mapped_column(Date, index=True)
    level: Mapped[str | None] = mapped_column(String(20))
    home_team: Mapped[str] = mapped_column(String(120))
    away_team: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(200))
    scout_name: Mapped[str | None] = mapped_column(String(120))
    weather: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    pitches: Mapped[list[GamePitch]] = relationship(back_populates="game", cascade="all, delete-orphan", order_by="GamePitch.sequence")
    notes_log: Mapped[list[GameNote]] = relationship(back_populates="game", cascade="all, delete-orphan")


class GamePitch(Base):
    """A pitch charted live (or from video) by a scout."""

    __tablename__ = "game_pitches"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    pitcher_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    batter_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    pitcher_name: Mapped[str | None] = mapped_column(String(160))
    batter_name: Mapped[str | None] = mapped_column(String(160))
    batter_side: Mapped[str | None] = mapped_column(String(1))
    inning: Mapped[int] = mapped_column(Integer)
    top_bottom: Mapped[str | None] = mapped_column(String(1))  # T / B
    outs: Mapped[int | None] = mapped_column(Integer)
    balls: Mapped[int] = mapped_column(Integer, default=0)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    pitch_type: Mapped[str | None] = mapped_column(String(4))  # FF, SI, FC, SL, SW, CU, CH, FS, KN ...
    velocity: Mapped[float | None] = mapped_column(Float)
    zone: Mapped[int | None] = mapped_column(Integer)  # 1-9 strike zone, 11-14 chase quadrants (Statcast convention)
    plate_x: Mapped[float | None] = mapped_column(Float)  # feet, catcher's view
    plate_z: Mapped[float | None] = mapped_column(Float)
    # ball, called_strike, swinging_strike, foul, foul_tip, in_play, hit_by_pitch
    result: Mapped[str] = mapped_column(String(20))
    batted_ball_type: Mapped[str | None] = mapped_column(String(12))  # ground_ball, line_drive, fly_ball, popup
    pa_outcome: Mapped[str | None] = mapped_column(String(20))  # single, double, triple, home_run, out, strikeout, walk, hbp ...
    exit_velocity: Mapped[float | None] = mapped_column(Float)
    time_to_plate: Mapped[float | None] = mapped_column(Float)  # delivery time with runners on
    notes: Mapped[str | None] = mapped_column(Text)

    game: Mapped[Game] = relationship(back_populates="pitches")


class GameNote(Base):
    __tablename__ = "game_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    inning: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(40))  # defense, baserunning, makeup, swing, delivery ...
    text: Mapped[str] = mapped_column(Text)

    game: Mapped[Game] = relationship(back_populates="notes_log")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str | None] = mapped_column(String(255))
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_names: Mapped[list[str]] = mapped_column(JSON, default=list)


class TrackingEvent(Base):
    """One normalized event from a tracking device (pitch, batted ball, or swing).

    Every source is mapped into the same units: mph, rpm, inches of break,
    feet for release/plate location, degrees for angles.
    """

    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(40), index=True)  # trackman, rapsodo, hittrax, hawkeye, blast, ...
    event_type: Mapped[str] = mapped_column(String(12))  # pitch | batted_ball | swing
    role: Mapped[str] = mapped_column(String(8))  # pitcher | hitter
    occurred_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    session_label: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str | None] = mapped_column(String(20))
    player_name_raw: Mapped[str | None] = mapped_column(String(160))
    opponent_name_raw: Mapped[str | None] = mapped_column(String(160))
    # pitch
    pitch_type: Mapped[str | None] = mapped_column(String(4))
    velocity: Mapped[float | None] = mapped_column(Float)
    spin_rate: Mapped[float | None] = mapped_column(Float)
    spin_axis: Mapped[float | None] = mapped_column(Float)
    spin_efficiency: Mapped[float | None] = mapped_column(Float)
    ivb: Mapped[float | None] = mapped_column(Float)
    hb: Mapped[float | None] = mapped_column(Float)
    release_height: Mapped[float | None] = mapped_column(Float)
    release_side: Mapped[float | None] = mapped_column(Float)
    extension: Mapped[float | None] = mapped_column(Float)
    plate_x: Mapped[float | None] = mapped_column(Float)
    plate_z: Mapped[float | None] = mapped_column(Float)
    pitch_result: Mapped[str | None] = mapped_column(String(20))
    # batted ball
    exit_velocity: Mapped[float | None] = mapped_column(Float)
    launch_angle: Mapped[float | None] = mapped_column(Float)
    spray_angle: Mapped[float | None] = mapped_column(Float)
    distance: Mapped[float | None] = mapped_column(Float)
    # swing (bat sensors)
    bat_speed: Mapped[float | None] = mapped_column(Float)
    attack_angle: Mapped[float | None] = mapped_column(Float)
    time_to_contact: Mapped[float | None] = mapped_column(Float)
    rotational_acceleration: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    player: Mapped[Player | None] = relationship(back_populates="tracking_events")


class VideoAnalysis(Base):
    __tablename__ = "video_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    motion_type: Mapped[str] = mapped_column(String(10))  # pitching | hitting
    camera_view: Mapped[str | None] = mapped_column(String(20))  # open_side, closed_side, behind, front
    video_path: Mapped[str | None] = mapped_column(String(500))
    recorded_on: Mapped[dt.date | None] = mapped_column(Date)
    fps: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | processing | done | failed
    error: Mapped[str | None] = mapped_column(Text)
    phases: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # event -> frame index
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feedback: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    player: Mapped[Player] = relationship(back_populates="video_analyses")


class ProjectionRun(Base):
    __tablename__ = "projection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    model_version: Mapped[str] = mapped_column(String(20))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class User(Base):
    """A person who can sign in. Roles: admin (everything + manage users), scout (read/write), viewer (read-only)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10), default="scout")
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """A signed-in browser or API client. Only a hash of the token is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()
