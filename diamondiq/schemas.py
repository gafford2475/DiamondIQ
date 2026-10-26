from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .levels import get_level
from .scouting import normalize_tool_grades


def _check_level(v: str | None) -> str | None:
    return get_level(v).code if v else v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PlayerIn(BaseModel):
    first_name: str
    last_name: str
    birth_date: dt.date | None = None
    bats: Literal["L", "R", "S"] | None = None
    throws: Literal["L", "R"] | None = None
    height_in: float | None = None
    weight_lb: float | None = None
    primary_position: str | None = None
    player_type: Literal["hitter", "pitcher", "two_way"] = "hitter"
    current_level: str | None = None
    current_team: str | None = None
    grad_year: int | None = None
    hometown: str | None = None
    commitment: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    _lvl = field_validator("current_level")(_check_level)


class PlayerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    birth_date: dt.date | None = None
    bats: Literal["L", "R", "S"] | None = None
    throws: Literal["L", "R"] | None = None
    height_in: float | None = None
    weight_lb: float | None = None
    primary_position: str | None = None
    player_type: Literal["hitter", "pitcher", "two_way"] | None = None
    current_level: str | None = None
    current_team: str | None = None
    grad_year: int | None = None
    commitment: str | None = None
    external_ids: dict[str, Any] | None = None
    notes: str | None = None

    _lvl = field_validator("current_level")(_check_level)


class PlayerOut(ORM, PlayerIn):
    id: int
    created_at: dt.datetime


class ScoutingReportIn(BaseModel):
    scout_name: str
    report_date: dt.date
    report_type: Literal["hitter", "pitcher"]
    level_seen: str | None = None
    event: str | None = None
    tool_grades: dict[str, Any] = Field(default_factory=dict, description='{"hit": {"present": 40, "future": 55}} or {"hit": 55}')
    measurables: dict[str, Any] = Field(default_factory=dict)
    ofp: float | None = Field(None, ge=20, le=80)
    risk: Literal["low", "medium", "high", "extreme"] | None = None
    role_projection: str | None = None
    projectability: int | None = Field(None, ge=20, le=80)
    makeup: int | None = Field(None, ge=20, le=80)
    physical_description: str | None = None
    strengths: str | None = None
    weaknesses: str | None = None
    summary: str | None = None

    _lvl = field_validator("level_seen")(_check_level)

    @field_validator("tool_grades")
    @classmethod
    def _grades(cls, v):
        return normalize_tool_grades(v)


class ScoutingReportOut(ORM, ScoutingReportIn):
    id: int
    player_id: int


class StatLineIn(BaseModel):
    season: int
    level: str
    team: str | None = None
    kind: Literal["hitting", "pitching"]
    split: str = "overall"
    source: str | None = "manual"
    stats: dict[str, Any]

    _lvl = field_validator("level")(_check_level)


class StatLineOut(ORM, StatLineIn):
    id: int
    player_id: int
    rates: dict[str, Any] | None = None


class MeasurementIn(BaseModel):
    measured_on: dt.date
    height_in: float | None = None
    weight_lb: float | None = None
    wingspan_in: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class GameIn(BaseModel):
    game_date: dt.date
    home_team: str
    away_team: str
    level: str | None = None
    location: str | None = None
    scout_name: str | None = None
    weather: str | None = None
    notes: str | None = None

    _lvl = field_validator("level")(_check_level)


class GameOut(ORM, GameIn):
    id: int


PitchResult = Literal["ball", "called_strike", "swinging_strike", "foul", "foul_tip", "in_play", "hit_by_pitch"]


class GamePitchIn(BaseModel):
    pitcher_id: int | None = None
    batter_id: int | None = None
    pitcher_name: str | None = None
    batter_name: str | None = None
    batter_side: Literal["L", "R"] | None = None
    inning: int = Field(ge=1)
    top_bottom: Literal["T", "B"] | None = None
    outs: int | None = Field(None, ge=0, le=2)
    balls: int = Field(0, ge=0, le=3)
    strikes: int = Field(0, ge=0, le=2)
    pitch_type: str | None = None
    velocity: float | None = None
    zone: int | None = Field(None, ge=1, le=14)
    plate_x: float | None = None
    plate_z: float | None = None
    result: PitchResult
    batted_ball_type: Literal["ground_ball", "line_drive", "fly_ball", "popup", "bunt"] | None = None
    pa_outcome: str | None = None
    exit_velocity: float | None = None
    time_to_plate: float | None = None
    notes: str | None = None


class GamePitchOut(ORM, GamePitchIn):
    id: int
    game_id: int
    sequence: int


class GameNoteIn(BaseModel):
    player_id: int | None = None
    inning: int | None = None
    category: str | None = None
    text: str


class WatchlistIn(BaseModel):
    name: str
    description: str | None = None


class ProjectionRequest(BaseModel):
    as_type: Literal["hitter", "pitcher"] | None = None
    years: int = Field(6, ge=1, le=15)
    pathway: Literal["auto", "college", "juco", "pro"] = "auto"
    sims: int = Field(2000, ge=200, le=20000)
    display_levels: list[str] | None = None

    @field_validator("display_levels")
    @classmethod
    def _levels(cls, v):
        return [get_level(x).code for x in v] if v else v


class WhatIfProjectionRequest(BaseModel):
    """Project a hypothetical or not-yet-saved player directly from inputs."""

    player_type: Literal["hitter", "pitcher"]
    age: float = Field(ge=13, le=45)
    current_level: str
    seasons: list[dict[str, Any]] = Field(default_factory=list)
    scouting: dict[str, Any] | None = None
    tracking: dict[str, Any] | None = None
    mechanics_score: float | None = None
    arm_stress: Literal["low", "moderate", "elevated"] | None = None
    position: str | None = None
    pathway: Literal["auto", "college", "juco", "pro"] = "auto"
    years: int = Field(6, ge=1, le=15)
    sims: int = Field(2000, ge=200, le=20000)
    display_levels: list[str] | None = None

    _lvl = field_validator("current_level")(_check_level)
