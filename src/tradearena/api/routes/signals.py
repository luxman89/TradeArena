"""POST /signal — emit a committed signal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.core.commitment import build_committed_signal
from tradearena.db.database import CreatorORM, SignalORM, get_db
from tradearena.models.signal import SignalCreate

router = APIRouter()


@router.post("/signal", status_code=status.HTTP_201_CREATED)
async def emit_signal(
    payload: SignalCreate,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    """Commit and store a new trading signal.

    creator_id is derived from the authenticated API key — not accepted from
    the request body. Returns signal_id and committed_at.
    """
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

    signal_orm = SignalORM(
        signal_id=committed["signal_id"],
        creator_id=committed["creator_id"],
        asset=committed["asset"],
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

    return {
        "signal_id": signal_orm.signal_id,
        "committed_at": signal_orm.committed_at.isoformat(),
        "commitment_hash": signal_orm.commitment_hash,
        "creator_id": signal_orm.creator_id,
        "asset": signal_orm.asset,
        "action": signal_orm.action,
    }
