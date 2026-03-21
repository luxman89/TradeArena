"""Admin monitoring endpoints — signal volume, resolver latency, error rates."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from tradearena.api.ws import manager
from tradearena.core.metrics import collector
from tradearena.db.database import (
    BattleORM,
    CreatorORM,
    CreatorScoreORM,
    SignalORM,
    get_db,
)

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _check_admin(token: str = Query(alias="token", default="")) -> None:
    """Simple token-based admin auth. Set ADMIN_TOKEN env var in production."""
    if ADMIN_TOKEN and token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")


@router.get("/metrics", summary="Full monitoring metrics")
def get_metrics(
    _: None = Depends(_check_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated metrics: signal volume, resolver stats, error rates, system health."""
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)

    # --- Signal volume ---
    total_signals = db.query(func.count(SignalORM.signal_id)).scalar() or 0
    pending_signals = (
        db.query(func.count(SignalORM.signal_id))
        .filter(SignalORM.outcome.is_(None))
        .scalar()
        or 0
    )
    resolved_signals = total_signals - pending_signals

    # Outcome breakdown
    outcomes = (
        db.query(SignalORM.outcome, func.count(SignalORM.signal_id))
        .filter(SignalORM.outcome.isnot(None))
        .group_by(SignalORM.outcome)
        .all()
    )
    outcome_counts = {row[0]: row[1] for row in outcomes}

    # Signals in last 24h
    signals_24h = (
        db.query(func.count(SignalORM.signal_id))
        .filter(SignalORM.committed_at >= one_day_ago)
        .scalar()
        or 0
    )

    # Signals in last 1h
    signals_1h = (
        db.query(func.count(SignalORM.signal_id))
        .filter(SignalORM.committed_at >= one_hour_ago)
        .scalar()
        or 0
    )

    # Resolved in last 24h
    resolved_24h = (
        db.query(func.count(SignalORM.signal_id))
        .filter(SignalORM.outcome_at >= one_day_ago)
        .scalar()
        or 0
    )

    # --- Asset distribution ---
    asset_dist = (
        db.query(SignalORM.asset, func.count(SignalORM.signal_id))
        .group_by(SignalORM.asset)
        .order_by(func.count(SignalORM.signal_id).desc())
        .limit(10)
        .all()
    )

    # --- Creators ---
    total_creators = db.query(func.count(CreatorORM.id)).scalar() or 0
    active_creators_24h = (
        db.query(func.count(func.distinct(SignalORM.creator_id)))
        .filter(SignalORM.committed_at >= one_day_ago)
        .scalar()
        or 0
    )

    # --- Battles ---
    active_battles = (
        db.query(func.count(BattleORM.battle_id))
        .filter(BattleORM.status == "ACTIVE")
        .scalar()
        or 0
    )
    resolved_battles = (
        db.query(func.count(BattleORM.battle_id))
        .filter(BattleORM.status == "RESOLVED")
        .scalar()
        or 0
    )

    # --- WebSocket ---
    ws_connections = len(manager._connections)

    # --- Resolver & system metrics (from in-memory collector) ---
    resolver_stats = collector.get_resolver_stats()
    system_summary = collector.get_summary()
    error_log = collector.get_error_log(limit=30)

    return {
        "timestamp": now.isoformat(),
        "system": system_summary,
        "signals": {
            "total": total_signals,
            "pending": pending_signals,
            "resolved": resolved_signals,
            "outcomes": outcome_counts,
            "last_24h": signals_24h,
            "last_1h": signals_1h,
            "resolved_24h": resolved_24h,
            "asset_distribution": [
                {"asset": row[0], "count": row[1]} for row in asset_dist
            ],
        },
        "creators": {
            "total": total_creators,
            "active_24h": active_creators_24h,
        },
        "battles": {
            "active": active_battles,
            "resolved": resolved_battles,
        },
        "websocket": {
            "connections": ws_connections,
        },
        "resolver": resolver_stats,
        "errors": error_log,
    }
