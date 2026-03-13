"""Battle resolver — scores two creators over a time window and determines the winner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tradearena.core.scoring import compute_score
from tradearena.db.database import BattleORM, SignalORM

DRAW_THRESHOLD = 0.01  # score difference below this = draw


def resolve_battle(battle: BattleORM, db: Session) -> BattleORM | None:
    """Resolve a single battle by scoring both creators over the battle window.

    Returns the updated BattleORM, or None if either creator has <2 resolved
    signals in the window (can't produce meaningful scores yet).
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(days=battle.window_days)

    c1_signals = _get_windowed_signals(db, battle.creator1_id, window_start, now)
    c2_signals = _get_windowed_signals(db, battle.creator2_id, window_start, now)

    c1_resolved = [s for s in c1_signals if s.outcome is not None]
    c2_resolved = [s for s in c2_signals if s.outcome is not None]

    if len(c1_resolved) < 2 or len(c2_resolved) < 2:
        return None

    c1_dims = compute_score(
        [s.outcome for s in c1_signals],
        [s.confidence for s in c1_signals],
    )
    c2_dims = compute_score(
        [s.outcome for s in c2_signals],
        [s.confidence for s in c2_signals],
    )

    c1_composite = c1_dims.composite
    c2_composite = c2_dims.composite
    margin = abs(c1_composite - c2_composite)

    def _dims_to_dict(dims):
        return {
            "win_rate": round(dims.win_rate, 4),
            "risk_adjusted_return": round(dims.risk_adjusted_return, 4),
            "consistency": round(dims.consistency, 4),
            "confidence_calibration": round(dims.confidence_calibration, 4),
            "composite": round(dims.composite, 4),
        }

    battle.creator1_score = round(c1_composite, 4)
    battle.creator2_score = round(c2_composite, 4)
    battle.creator1_details = _dims_to_dict(c1_dims)
    battle.creator2_details = _dims_to_dict(c2_dims)
    battle.margin = round(margin, 4)
    battle.resolved_at = now
    battle.status = "RESOLVED"

    if margin < DRAW_THRESHOLD:
        battle.winner_id = None
    elif c1_composite > c2_composite:
        battle.winner_id = battle.creator1_id
    else:
        battle.winner_id = battle.creator2_id

    db.commit()
    return battle


def _get_windowed_signals(
    db: Session,
    creator_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[SignalORM]:
    """Query signals for a creator within the time window."""
    return (
        db.query(SignalORM)
        .filter(
            SignalORM.creator_id == creator_id,
            SignalORM.committed_at >= window_start,
            SignalORM.committed_at <= window_end,
        )
        .order_by(SignalORM.committed_at)
        .all()
    )
