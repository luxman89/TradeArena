"""Battle endpoints — create, view, list, resolve."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from tradearena.core.battle_resolver import resolve_battle
from tradearena.db.database import BattleORM, CreatorORM, get_db
from tradearena.models.battle import BattleCreate

router = APIRouter(tags=["battles"])


def _battle_to_response(b: BattleORM) -> dict:
    return {
        "battle_id": b.battle_id,
        "creator1_id": b.creator1_id,
        "creator2_id": b.creator2_id,
        "status": b.status,
        "window_days": b.window_days,
        "created_at": b.created_at,
        "resolved_at": b.resolved_at,
        "creator1_score": b.creator1_score,
        "creator2_score": b.creator2_score,
        "creator1_details": b.creator1_details,
        "creator2_details": b.creator2_details,
        "winner_id": b.winner_id,
        "margin": b.margin,
        "battle_type": b.battle_type,
    }


@router.post("/battle/create", status_code=status.HTTP_201_CREATED)
async def create_battle(
    payload: BattleCreate,
    db: Session = Depends(get_db),
) -> dict:
    """Create a new battle between two creators."""
    if payload.creator1_id == payload.creator2_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot battle against yourself.",
        )

    for cid in (payload.creator1_id, payload.creator2_id):
        if not db.query(CreatorORM).filter(CreatorORM.id == cid).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Creator '{cid}' not found.",
            )

    # Check for existing active battle between these two
    existing = (
        db.query(BattleORM)
        .filter(
            BattleORM.status == "ACTIVE",
            or_(
                (BattleORM.creator1_id == payload.creator1_id)
                & (BattleORM.creator2_id == payload.creator2_id),
                (BattleORM.creator1_id == payload.creator2_id)
                & (BattleORM.creator2_id == payload.creator1_id),
            ),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active battle already exists between these creators.",
        )

    battle = BattleORM(
        battle_id=uuid.uuid4().hex,
        creator1_id=payload.creator1_id,
        creator2_id=payload.creator2_id,
        status="ACTIVE",
        window_days=payload.window_days,
        created_at=datetime.now(UTC),
        battle_type="MANUAL",
    )
    db.add(battle)
    db.commit()
    db.refresh(battle)

    return _battle_to_response(battle)


@router.get("/battle/{battle_id}")
async def get_battle(
    battle_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Get full battle state including scores."""
    battle = db.query(BattleORM).filter(BattleORM.battle_id == battle_id).first()
    if not battle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Battle not found.",
        )
    return _battle_to_response(battle)


@router.get("/battles/active")
async def list_active_battles(
    db: Session = Depends(get_db),
) -> dict:
    """List all active battles."""
    battles = db.query(BattleORM).filter(BattleORM.status == "ACTIVE").all()
    return {
        "total": len(battles),
        "battles": [_battle_to_response(b) for b in battles],
    }


@router.get("/battles/history")
async def battle_history(
    creator_id: str | None = Query(None),
    battle_status: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Paginated battle history, filterable by creator_id and status."""
    query = db.query(BattleORM)

    if creator_id:
        query = query.filter(
            or_(
                BattleORM.creator1_id == creator_id,
                BattleORM.creator2_id == creator_id,
            )
        )
    if battle_status:
        query = query.filter(BattleORM.status == battle_status.upper())

    total = query.count()
    battles = query.order_by(BattleORM.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "battles": [_battle_to_response(b) for b in battles],
    }


@router.post("/battle/{battle_id}/resolve")
async def force_resolve_battle(
    battle_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Force-resolve a battle (admin/dev)."""
    battle = db.query(BattleORM).filter(BattleORM.battle_id == battle_id).first()
    if not battle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Battle not found.",
        )
    if battle.status == "RESOLVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Battle already resolved.",
        )

    result = resolve_battle(battle, db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot resolve — one or both creators have fewer than 2 resolved signals.",
        )

    return _battle_to_response(result)
