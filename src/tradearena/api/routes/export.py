"""Export endpoints: CSV and JSON data export for creators."""

from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.core.analytics import TIME_RANGES, compute_analytics
from tradearena.db.database import CreatorORM, CreatorScoreORM, SignalORM, get_db

router = APIRouter(prefix="/export", tags=["export"])

_SIGNAL_CSV_COLUMNS = [
    "signal_id",
    "asset",
    "action",
    "confidence",
    "reasoning",
    "target_price",
    "stop_loss",
    "timeframe",
    "commitment_hash",
    "committed_at",
    "outcome",
    "outcome_price",
    "outcome_at",
]


def _signal_to_row(s: SignalORM) -> dict:
    return {
        "signal_id": s.signal_id,
        "asset": s.asset,
        "action": s.action,
        "confidence": s.confidence,
        "reasoning": s.reasoning,
        "target_price": s.target_price,
        "stop_loss": s.stop_loss,
        "timeframe": s.timeframe,
        "commitment_hash": s.commitment_hash,
        "committed_at": s.committed_at.isoformat(),
        "outcome": s.outcome,
        "outcome_price": s.outcome_price,
        "outcome_at": s.outcome_at.isoformat() if s.outcome_at else None,
    }


def _signals_to_csv(signals: list[SignalORM]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SIGNAL_CSV_COLUMNS)
    writer.writeheader()
    for s in signals:
        writer.writerow(_signal_to_row(s))
    return buf.getvalue()


@router.get(
    "/signals",
    summary="Export signal history as CSV or JSON",
    responses={
        200: {"description": "Signal data in requested format"},
        401: {"description": "Missing or invalid API key"},
    },
)
async def export_signals(
    format: Literal["csv", "json"] = Query("json", description="Export format: csv or json"),
    creator_id: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Export all signals for the authenticated creator."""
    signals = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator_id)
        .order_by(SignalORM.committed_at.desc())
        .all()
    )

    if format == "csv":
        csv_content = _signals_to_csv(signals)
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{creator_id}_signals.csv"'},
        )

    return JSONResponse(
        content={
            "creator_id": creator_id,
            "total": len(signals),
            "signals": [_signal_to_row(s) for s in signals],
        }
    )


@router.get(
    "/analytics",
    summary="Export performance analytics as JSON",
    responses={
        200: {"description": "Analytics data"},
        401: {"description": "Missing or invalid API key"},
        422: {"description": "Invalid time range"},
    },
)
async def export_analytics(
    range: str = Query("all", description="Time range: 7d, 30d, 90d, or all"),
    creator_id: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Export performance analytics for the authenticated creator."""
    if range not in TIME_RANGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"range must be one of {sorted(TIME_RANGES)}",
        )

    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found",
        )

    score = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator_id).first()

    signals = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator_id)
        .order_by(SignalORM.committed_at.asc())
        .all()
    )

    analytics = compute_analytics(signals, range)
    analytics["creator_id"] = creator_id
    analytics["scores"] = {
        "composite": round(score.composite_score, 4) if score else 0.0,
        "win_rate": round(score.win_rate, 4) if score else 0.0,
        "risk_adjusted_return": round(score.risk_adjusted_return, 4) if score else 0.0,
        "consistency": round(score.consistency, 4) if score else 0.0,
        "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
        "total_signals": score.total_signals if score else 0,
    }

    return JSONResponse(content=analytics)
