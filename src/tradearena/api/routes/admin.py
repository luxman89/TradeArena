"""Admin monitoring endpoints — signal volume, resolver latency, error rates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from tradearena.api.deps import require_admin_token
from tradearena.api.ws import manager
from tradearena.core.metrics import collector
from tradearena.db.database import (
    AuditLogORM,
    BattleORM,
    CreatorORM,
    SignalORM,
    get_db,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics", summary="Full monitoring metrics")
def get_metrics(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated metrics: signal volume, resolver stats, error rates, system health."""
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)

    # --- Signal volume ---
    total_signals = db.query(func.count(SignalORM.signal_id)).scalar() or 0
    pending_signals = (
        db.query(func.count(SignalORM.signal_id)).filter(SignalORM.outcome.is_(None)).scalar() or 0
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
        db.query(func.count(BattleORM.battle_id)).filter(BattleORM.status == "ACTIVE").scalar() or 0
    )
    resolved_battles = (
        db.query(func.count(BattleORM.battle_id)).filter(BattleORM.status == "RESOLVED").scalar()
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
            "asset_distribution": [{"asset": row[0], "count": row[1]} for row in asset_dist],
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


@router.get("/audit-log", summary="Query audit log")
def get_audit_log(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
    actor: str | None = Query(None, description="Filter by actor"),
    action: str | None = Query(None, description="Filter by action type"),
    target: str | None = Query(None, description="Filter by target entity"),
    since: str | None = Query(None, description="ISO datetime lower bound"),
    until: str | None = Query(None, description="ISO datetime upper bound"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated audit log with filtering by actor, action, target, and time range."""
    query = db.query(AuditLogORM)

    if actor:
        query = query.filter(AuditLogORM.actor == actor)
    if action:
        query = query.filter(AuditLogORM.action == action)
    if target:
        query = query.filter(AuditLogORM.target == target)
    if since:
        query = query.filter(AuditLogORM.timestamp >= datetime.fromisoformat(since))
    if until:
        query = query.filter(AuditLogORM.timestamp <= datetime.fromisoformat(until))

    total = query.count()
    entries = query.order_by(AuditLogORM.timestamp.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [
            {
                "id": e.id,
                "actor": e.actor,
                "action": e.action,
                "target": e.target,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "metadata": e.metadata_,
            }
            for e in entries
        ],
    }
