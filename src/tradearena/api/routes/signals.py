"""POST /signal — emit a committed signal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.api.rate_limit import signal_rate_limiter
from tradearena.api.ws import manager
from tradearena.core.asset_types import classify_asset
from tradearena.core.commitment import build_committed_signal
from tradearena.db.database import CreatorORM, CreatorScoreORM, SignalORM, get_db
from tradearena.models.signal import SignalCreate, SignalEmitResponse

router = APIRouter()


@router.post(
    "/signal",
    status_code=status.HTTP_201_CREATED,
    response_model=SignalEmitResponse,
    summary="Emit a trading signal",
    responses={
        404: {"description": "Creator not found — register first"},
        429: {"description": "Signal rate limit exceeded"},
    },
)
async def emit_signal(
    payload: SignalCreate,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    """Commit and store a new trading signal.

    creator_id is derived from the authenticated API key — not accepted from
    the request body. Returns signal_id and committed_at.
    """
    # Per-creator rate limit: 10 signals/hour (checked before DB work)
    signal_rate_limiter.check(creator_id)

    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found. Register first.",
        )

    raw = payload.model_dump()
    raw["creator_id"] = creator_id
    raw["action"] = raw["action"].value  # enum → string for hashing

    committed = build_committed_signal(raw)

    asset_type = classify_asset(committed["asset"])

    signal_orm = SignalORM(
        signal_id=committed["signal_id"],
        creator_id=committed["creator_id"],
        asset=committed["asset"],
        asset_type=asset_type.value,
        action=committed["action"],
        confidence=committed["confidence"],
        reasoning=committed["reasoning"],
        supporting_data=committed["supporting_data"],
        target_price=committed.get("target_price"),
        stop_loss=committed.get("stop_loss"),
        timeframe=committed.get("timeframe"),
        commitment_hash=committed["commitment_hash"],
        committed_at=committed["committed_at"],
    )
    db.add(signal_orm)
    db.commit()
    db.refresh(signal_orm)

    # Increment total_signals only — new signals have outcome=None so they
    # don't affect score dimensions.  The background loop handles full
    # recomputation when outcomes are resolved, avoiding the O(n) query here
    # and the race condition between concurrent submissions and the loop.
    now = datetime.now(UTC)
    existing_score = (
        db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator_id).first()
    )
    if existing_score:
        existing_score.total_signals = (existing_score.total_signals or 0) + 1
        existing_score.updated_at = now
    else:
        db.add(
            CreatorScoreORM(
                creator_id=creator_id,
                total_signals=1,
                updated_at=now,
            )
        )
    db.commit()

    # Maintain daily streak
    today = datetime.now(UTC).date()
    prev_day = creator.last_signal_day
    if prev_day != today:
        if prev_day == today - timedelta(days=1):
            creator.streak_days = (creator.streak_days or 0) + 1
        else:
            creator.streak_days = 1
        creator.last_signal_day = today
        db.commit()

    result = {
        "signal_id": signal_orm.signal_id,
        "committed_at": signal_orm.committed_at.isoformat(),
        "commitment_hash": signal_orm.commitment_hash,
        "creator_id": signal_orm.creator_id,
        "asset": signal_orm.asset,
        "action": signal_orm.action,
        "streak_days": creator.streak_days,
    }
    await manager.broadcast("signal_new", result)
    return result
