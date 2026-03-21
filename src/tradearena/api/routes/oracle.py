"""Oracle endpoints — manual trigger and status."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from tradearena.core.oracle import parse_timeframe, resolve_pending_signals
from tradearena.db.database import SignalORM, get_db
from tradearena.models.responses import OracleResolveResponse, OracleStatusResponse

router = APIRouter(prefix="/oracle", tags=["oracle"])


@router.post(
    "/resolve",
    response_model=OracleResolveResponse,
    summary="Trigger oracle resolution",
)
async def trigger_resolve(db: Session = Depends(get_db)) -> dict:
    """Manually trigger oracle resolution of pending signals."""
    stats = await resolve_pending_signals(db)
    return stats


@router.get(
    "/status",
    response_model=OracleStatusResponse,
    summary="Get oracle status",
)
async def oracle_status(db: Session = Depends(get_db)) -> dict:
    """Show pending signal count and next eligible resolution times."""
    now = datetime.now(UTC)
    pending = db.query(SignalORM).filter(SignalORM.outcome.is_(None)).all()

    eligible_now = 0
    next_eligible_times = []
    for sig in pending:
        tf_delta = parse_timeframe(sig.timeframe)
        eligible_at = sig.committed_at.replace(tzinfo=UTC) + tf_delta
        if eligible_at <= now:
            eligible_now += 1
        else:
            next_eligible_times.append(eligible_at.isoformat())

    next_eligible_times.sort()

    return {
        "pending_total": len(pending),
        "eligible_now": eligible_now,
        "next_eligible": next_eligible_times[:10],
    }
