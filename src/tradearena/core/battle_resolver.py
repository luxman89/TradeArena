"""Battle resolver — scores two creators over a time window and determines the winner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tradearena.core.elo import DEFAULT_RATING, calculate_elo_change
from tradearena.core.scoring import compute_score
from tradearena.db.database import BattleORM, BotRatingORM, RatingHistoryORM, SignalORM

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

    # Update ELO ratings after battle resolution
    update_elo_after_battle(battle, db)

    db.commit()
    return battle


def _get_or_create_rating(db: Session, bot_id: str) -> BotRatingORM:
    """Get existing rating or create a default one."""
    rating = db.query(BotRatingORM).filter(BotRatingORM.bot_id == bot_id).first()
    if not rating:
        rating = BotRatingORM(
            bot_id=bot_id,
            elo=DEFAULT_RATING,
            matches_played=0,
            wins=0,
            losses=0,
            draws=0,
        )
        db.add(rating)
        db.flush()
    return rating


def update_elo_after_battle(battle: BattleORM, db: Session) -> None:
    """Update ELO ratings for both creators after a battle resolves."""
    now = datetime.now(UTC)

    r1 = _get_or_create_rating(db, battle.creator1_id)
    r2 = _get_or_create_rating(db, battle.creator2_id)

    # Determine score_a (for creator1): 1.0=win, 0.5=draw, 0.0=loss
    if battle.winner_id is None:
        score_a = 0.5
    elif battle.winner_id == battle.creator1_id:
        score_a = 1.0
    else:
        score_a = 0.0

    result1, result2 = calculate_elo_change(
        r1.elo, r2.elo, score_a, r1.matches_played, r2.matches_played
    )

    # Update ratings
    r1.elo = result1.new_rating
    r1.matches_played += 1
    r2.elo = result2.new_rating
    r2.matches_played += 1

    if score_a == 1.0:
        r1.wins += 1
        r2.losses += 1
    elif score_a == 0.0:
        r1.losses += 1
        r2.wins += 1
    else:
        r1.draws += 1
        r2.draws += 1

    r1.updated_at = now
    r2.updated_at = now

    # Record history
    for bot_id, elo in [
        (battle.creator1_id, result1.new_rating),
        (battle.creator2_id, result2.new_rating),
    ]:
        db.add(
            RatingHistoryORM(
                bot_id=bot_id,
                elo=elo,
                match_id=battle.battle_id,
                timestamp=now,
            )
        )


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
