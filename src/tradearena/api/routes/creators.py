"""GET /creator/{id} and GET /creator/{id}/signals — public endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tradearena.db.database import CreatorORM, SignalORM, get_db

router = APIRouter()


@router.get("/creator/{creator_id}")
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
            "reasoning_quality": round(score.reasoning_quality, 4) if score else 0.0,
            "consistency": round(score.consistency, 4) if score else 0.0,
            "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
            "total_signals": score.total_signals if score else 0,
            "updated_at": score.updated_at.isoformat() if score and score.updated_at else None,
        },
    }


@router.get("/creator/{creator_id}/signals")
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
