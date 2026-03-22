"""Tournament Pydantic models for API request/response validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TournamentCreate(BaseModel):
    """Request body for POST /tournament.

    Create a bracket-style tournament. Supports single elimination
    (losers are eliminated each round) or round robin (everyone plays
    everyone, points awarded per win).
    """

    name: str = Field(..., min_length=3, max_length=128, description="Tournament name")
    format: str = Field(
        "single_elimination",
        pattern="^(single_elimination|round_robin)$",
        description="single_elimination or round_robin",
    )
    max_participants: int = Field(8, ge=2, le=64, description="Max creators allowed (2-64)")
    start_time: datetime | None = Field(None, description="Scheduled start time (optional)")
    created_by: str | None = Field(None, description="Creator ID of the tournament organizer")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "March Madness Trading Cup",
                    "format": "single_elimination",
                    "max_participants": 16,
                    "start_time": "2026-04-01T18:00:00Z",
                }
            ]
        },
    )


class TournamentJoinRequest(BaseModel):
    """Request body for POST /tournament/{id}/join."""

    creator_id: str = Field(..., min_length=1)


class TournamentEntryResponse(BaseModel):
    """A single tournament participant."""

    creator_id: str
    seed: int | None = None
    eliminated_at: str | None = None
    points: int = 0

    model_config = ConfigDict(from_attributes=True)


class TournamentMatchResponse(BaseModel):
    """A single match within a tournament round."""

    round: int
    match_order: int
    battle_id: str | None = None
    winner_bot_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TournamentResponse(BaseModel):
    """Full tournament state."""

    id: str
    name: str
    format: str
    status: str
    max_participants: int
    current_round: int
    start_time: datetime | None = None
    created_by: str | None = None
    created_at: datetime
    entries: list[TournamentEntryResponse]
    matches: list[TournamentMatchResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TournamentListResponse(BaseModel):
    """List of tournaments."""

    total: int
    tournaments: list[TournamentResponse]
