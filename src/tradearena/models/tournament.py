"""Tournament Pydantic models for API request/response validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TournamentCreate(BaseModel):
    """Request body for POST /tournament."""

    name: str = Field(..., min_length=3, max_length=128)
    format: str = Field("single_elimination", pattern="^(single_elimination|round_robin)$")
    max_participants: int = Field(8, ge=2, le=64)


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


class TournamentResponse(BaseModel):
    """Full tournament state."""

    id: str
    name: str
    format: str
    status: str
    max_participants: int
    current_round: int
    created_at: datetime
    entries: list[TournamentEntryResponse]

    model_config = ConfigDict(from_attributes=True)


class TournamentListResponse(BaseModel):
    """List of tournaments."""

    total: int
    tournaments: list[TournamentResponse]
