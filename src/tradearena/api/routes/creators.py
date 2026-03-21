"""Creator endpoints: registration and profile/signals retrieval."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from tradearena.core.analytics import TIME_RANGES, compute_analytics
from tradearena.db.database import CreatorORM, SignalORM, get_db
from tradearena.models.responses import (
    AnalyticsResponse,
    CreatorProfileResponse,
    CreatorRegisterResponse,
    CreatorSignalsResponse,
)

router = APIRouter()

_VALID_DIVISIONS = {"crypto", "polymarket", "multi"}


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text


class CreatorRegisterRequest(BaseModel):
    display_name: str
    division: str
    strategy_description: str
    email: str

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        if not (3 <= len(v) <= 50):
            raise ValueError("display_name must be 3-50 characters")
        return v

    @field_validator("division")
    @classmethod
    def validate_division(cls, v: str) -> str:
        if v not in _VALID_DIVISIONS:
            raise ValueError(f"division must be one of: {', '.join(sorted(_VALID_DIVISIONS))}")
        return v

    @field_validator("strategy_description")
    @classmethod
    def validate_strategy_description(cls, v: str) -> str:
        if not (20 <= len(v) <= 500):
            raise ValueError("strategy_description must be 20-500 characters")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v.lower()


@router.post(
    "/creator/register",
    status_code=201,
    response_model=CreatorRegisterResponse,
    summary="Register a new creator (API-key flow)",
    responses={
        409: {"description": "Email already registered"},
    },
)
async def register_creator(
    body: CreatorRegisterRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Register a new creator. Public endpoint — no authentication required."""
    # 409 if email already registered
    if db.query(CreatorORM).filter(CreatorORM.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Generate creator_id: slug + "-" + 4 random hex chars; retry once on collision
    slug = _slugify(body.display_name)
    creator_id = f"{slug}-{secrets.token_hex(2)}"
    if db.query(CreatorORM).filter(CreatorORM.id == creator_id).first():
        creator_id = f"{slug}-{secrets.token_hex(2)}"

    # Generate api_key: "ta-" + 32 random hex chars
    api_key = f"ta-{secrets.token_hex(16)}"
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    now = datetime.now(UTC)
    creator = CreatorORM(
        id=creator_id,
        display_name=body.display_name,
        division=body.division,
        email=body.email,
        strategy_description=body.strategy_description,
        api_key_hash=api_key_hash,
        created_at=now,
    )
    db.add(creator)
    db.commit()

    return JSONResponse(
        status_code=201,
        content={
            "creator_id": creator_id,
            "api_key": api_key,
            "display_name": body.display_name,
            "division": body.division,
            "created_at": now.isoformat(),
        },
    )


@router.get(
    "/creator/{creator_id}",
    response_model=CreatorProfileResponse,
    summary="Get creator profile",
    responses={
        404: {"description": "Creator not found"},
    },
)
async def get_creator(
    creator_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return creator profile and current scores."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )
    score = creator.score
    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "created_at": creator.created_at.isoformat(),
        "scores": {
            "composite": round(score.composite_score, 4) if score else 0.0,
            "win_rate": round(score.win_rate, 4) if score else 0.0,
            "risk_adjusted_return": round(score.risk_adjusted_return, 4) if score else 0.0,
            "consistency": round(score.consistency, 4) if score else 0.0,
            "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
            "total_signals": score.total_signals if score else 0,
            "updated_at": score.updated_at.isoformat() if score and score.updated_at else None,
        },
    }


@router.get(
    "/creator/{creator_id}/signals",
    response_model=CreatorSignalsResponse,
    summary="Get creator signal history",
    responses={
        404: {"description": "Creator not found"},
    },
)
async def get_creator_signals(
    creator_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return paginated signal history for a creator."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )

    signals = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator_id)
        .order_by(SignalORM.committed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(SignalORM).filter(SignalORM.creator_id == creator_id).count()

    return {
        "creator_id": creator_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "signals": [
            {
                "signal_id": s.signal_id,
                "asset": s.asset,
                "action": s.action,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
                "supporting_data": s.supporting_data,
                "target_price": s.target_price,
                "stop_loss": s.stop_loss,
                "timeframe": s.timeframe,
                "commitment_hash": s.commitment_hash,
                "committed_at": s.committed_at.isoformat(),
                "outcome": s.outcome,
                "outcome_price": s.outcome_price,
                "outcome_at": s.outcome_at.isoformat() if s.outcome_at else None,
            }
            for s in signals
        ],
    }


_VALID_RANGES = sorted(TIME_RANGES)


@router.get(
    "/creator/{creator_id}/analytics",
    response_model=AnalyticsResponse,
    summary="Get creator performance analytics",
    responses={
        404: {"description": "Creator not found"},
        422: {"description": "Invalid time range"},
    },
)
async def get_creator_analytics(
    creator_id: str,
    range: str = Query("all", description="Time range: 7d, 30d, 90d, or all"),
    db: Session = Depends(get_db),
) -> dict:
    """Return performance analytics for a creator: equity curve, drawdowns,
    streaks, action distribution, and confidence calibration curve."""
    if range not in TIME_RANGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"range must be one of {_VALID_RANGES}",
        )
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )
    signals = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator_id)
        .order_by(SignalORM.committed_at.asc())
        .all()
    )
    return compute_analytics(signals, range)
