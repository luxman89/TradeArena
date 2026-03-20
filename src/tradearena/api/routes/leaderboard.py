"""GET /leaderboard and GET /leaderboard/{division} — public endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tradearena.db.database import CreatorORM, CreatorScoreORM, get_db
from tradearena.models.responses import LeaderboardDivisionResponse, LeaderboardResponse

router = APIRouter()

VALID_DIVISIONS = {"crypto", "polymarket", "multi"}


def _format_entry(creator: CreatorORM) -> dict:
    score = creator.score
    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "composite_score": round(score.composite_score, 4) if score else 0.0,
        "win_rate": round(score.win_rate, 4) if score else 0.0,
        "risk_adjusted_return": round(score.risk_adjusted_return, 4) if score else 0.0,
        "consistency": round(score.consistency, 4) if score else 0.0,
        "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
        "total_signals": score.total_signals if score else 0,
    }


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    summary="Get global leaderboard",
)
async def get_leaderboard(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return all creators sorted by composite score descending."""
    creators = (
        db.query(CreatorORM)
        .outerjoin(CreatorScoreORM, CreatorORM.id == CreatorScoreORM.creator_id)
        .order_by(CreatorScoreORM.composite_score.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(CreatorORM).count()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [_format_entry(c) for c in creators],
    }


@router.get(
    "/leaderboard/{division}",
    response_model=LeaderboardDivisionResponse,
    summary="Get division leaderboard",
    responses={
        422: {"description": "Invalid division — must be crypto, polymarket, or multi"},
    },
)
async def get_leaderboard_division(
    division: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return creators in a specific division sorted by composite score."""
    division = division.lower()
    if division not in VALID_DIVISIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"division must be one of {sorted(VALID_DIVISIONS)}",
        )
    creators = (
        db.query(CreatorORM)
        .filter(CreatorORM.division == division)
        .outerjoin(CreatorScoreORM, CreatorORM.id == CreatorScoreORM.creator_id)
        .order_by(CreatorScoreORM.composite_score.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(CreatorORM).filter(CreatorORM.division == division).count()
    return {
        "division": division,
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [_format_entry(c) for c in creators],
    }
