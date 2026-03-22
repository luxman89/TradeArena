"""Rating & matchmaking Pydantic models for API request/response validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BotRatingResponse(BaseModel):
    """Current ELO rating for a bot/creator."""

    bot_id: str
    elo: float
    matches_played: int
    wins: int
    losses: int
    draws: int
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RatingHistoryEntry(BaseModel):
    """Single ELO history point for charting."""

    elo: float
    match_id: str
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class RatingHistoryResponse(BaseModel):
    """ELO history for a bot/creator."""

    bot_id: str
    history: list[RatingHistoryEntry]


class MatchmakingQueueResponse(BaseModel):
    """Response after joining/leaving the matchmaking queue."""

    bot_id: str
    queued: bool
    message: str


class LeaderboardEloEntry(BaseModel):
    """Single entry in the ELO leaderboard."""

    bot_id: str
    display_name: str
    elo: float
    matches_played: int
    wins: int
    losses: int
    draws: int


class LeaderboardEloResponse(BaseModel):
    """ELO-ranked leaderboard."""

    total: int
    entries: list[LeaderboardEloEntry]
