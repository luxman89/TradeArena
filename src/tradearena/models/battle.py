"""Battle Pydantic models for API request/response validation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BattleCreate(BaseModel):
    """Request body for POST /battle/create.

    Create a head-to-head battle between two creators. Both creators must
    exist and cannot already have an active battle between them.
    """

    creator1_id: str = Field(..., min_length=1, description="First creator's ID")
    creator2_id: str = Field(..., min_length=1, description="Second creator's ID")
    window_days: int = Field(7, ge=1, le=30, description="Battle duration in days (1-30)")
    battle_type: str = Field("MANUAL", description="Battle type: MANUAL or AUTO")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "creator1_id": "alice-quantsworth-a1b2",
                    "creator2_id": "bob-trader-c3d4",
                    "window_days": 7,
                }
            ]
        },
    )


class ScoreBreakdown(BaseModel):
    """Four-dimension score snapshot."""

    win_rate: float
    risk_adjusted_return: float
    consistency: float
    confidence_calibration: float
    composite: float


class BattleResponse(BaseModel):
    """Full battle state returned by the API."""

    battle_id: str
    creator1_id: str
    creator2_id: str
    status: str
    window_days: int
    created_at: datetime
    resolved_at: datetime | None = None
    creator1_score: float | None = None
    creator2_score: float | None = None
    creator1_details: ScoreBreakdown | None = None
    creator2_details: ScoreBreakdown | None = None
    winner_id: str | None = None
    margin: float | None = None
    battle_type: str = "MANUAL"

    model_config = ConfigDict(from_attributes=True)


class BattleActiveListResponse(BaseModel):
    """Active battles list (non-paginated)."""

    total: int
    battles: list[BattleResponse]


class BattleListResponse(BaseModel):
    """Paginated list of battles."""

    total: int
    offset: int
    limit: int
    battles: list[BattleResponse]
