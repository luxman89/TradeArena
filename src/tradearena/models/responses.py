"""Shared API response models for OpenAPI documentation."""

from __future__ import annotations

from typing import Any  # noqa: F401

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry(BaseModel):
    creator_id: str
    display_name: str
    division: str
    composite_score: float
    win_rate: float
    risk_adjusted_return: float
    consistency: float
    confidence_calibration: float
    total_signals: int


class LeaderboardResponse(BaseModel):
    total: int
    offset: int
    limit: int
    entries: list[LeaderboardEntry]


class LeaderboardDivisionResponse(LeaderboardResponse):
    division: str


# ---------------------------------------------------------------------------
# Creator
# ---------------------------------------------------------------------------


class CreatorScores(BaseModel):
    composite: float
    win_rate: float
    risk_adjusted_return: float
    consistency: float
    confidence_calibration: float
    total_signals: int
    updated_at: str | None = None


class CreatorProfileResponse(BaseModel):
    creator_id: str
    display_name: str
    division: str
    created_at: str
    scores: CreatorScores


class CreatorRegisterResponse(BaseModel):
    creator_id: str
    api_key: str
    display_name: str
    division: str
    created_at: str


class SignalDetail(BaseModel):
    signal_id: str
    asset: str
    action: str
    confidence: float
    reasoning: str
    supporting_data: dict[str, Any]
    target_price: float | None = None
    stop_loss: float | None = None
    timeframe: str | None = None
    commitment_hash: str
    committed_at: str
    outcome: str | None = None
    outcome_price: float | None = None
    outcome_at: str | None = None


class CreatorSignalsResponse(BaseModel):
    creator_id: str
    total: int
    offset: int
    limit: int
    signals: list[SignalDetail]


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------


class OracleResolveResponse(BaseModel):
    resolved: int
    skipped: int
    errors: int


class OracleStatusResponse(BaseModel):
    pending_total: int
    eligible_now: int
    next_eligible: list[str]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class AuthRegisterResponse(BaseModel):
    creator_id: str
    api_key: str
    token: str
    display_name: str
    division: str
    avatar_index: int
    level: int
    xp: int
    created_at: str


class AuthLoginResponse(BaseModel):
    token: str
    creator_id: str
    display_name: str
    division: str
    avatar_index: int
    level: int
    xp: int
    title: str


class AuthMeScores(BaseModel):
    composite: float
    win_rate: float
    total_signals: int


class AuthMeResponse(BaseModel):
    creator_id: str
    display_name: str
    division: str
    avatar_index: int
    level: int
    xp: int
    xp_progress: int
    xp_needed: int
    xp_to_next: int
    title: str
    glow: str | None = None
    unlocked_avatars: list[int]
    scores: AuthMeScores


class AvatarUpdateResponse(BaseModel):
    avatar_index: int
    message: str


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class TimeseriesPoint(BaseModel):
    timestamp: str
    value: float


class CalibrationPoint(BaseModel):
    predicted_confidence: float
    actual_win_rate: float
    sample_count: int


class StreaksData(BaseModel):
    current_win_streak: int
    current_loss_streak: int
    max_win_streak: int
    max_loss_streak: int


class AnalyticsResponse(BaseModel):
    range: str
    total_signals: int
    resolved_signals: int
    equity_curve: list[TimeseriesPoint]
    drawdown_series: list[TimeseriesPoint]
    streaks: StreaksData
    action_distribution: dict[str, int]
    confidence_calibration_curve: list[CalibrationPoint]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
