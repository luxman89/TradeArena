"""ELO-based matchmaking — pairs queued bots/creators by similar ELO rating."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from tradearena.core.elo import DEFAULT_RATING
from tradearena.db.database import BattleORM, BotRatingORM, MatchmakingQueueORM

DEFAULT_WINDOW_DAYS = 7
MAX_ELO_GAP = 200  # only match bots within this ELO range


def join_queue(db: Session, bot_id: str) -> MatchmakingQueueORM:
    """Add a bot/creator to the matchmaking queue. Idempotent."""
    existing = db.query(MatchmakingQueueORM).filter(MatchmakingQueueORM.bot_id == bot_id).first()
    if existing:
        return existing

    entry = MatchmakingQueueORM(bot_id=bot_id, queued_at=datetime.now(UTC))
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def leave_queue(db: Session, bot_id: str) -> bool:
    """Remove a bot/creator from the matchmaking queue. Returns True if removed."""
    entry = db.query(MatchmakingQueueORM).filter(MatchmakingQueueORM.bot_id == bot_id).first()
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


def _get_elo(db: Session, bot_id: str) -> float:
    """Get ELO for a bot, defaulting to 1200 if no rating exists."""
    rating = db.query(BotRatingORM).filter(BotRatingORM.bot_id == bot_id).first()
    return rating.elo if rating else DEFAULT_RATING


def _get_active_pairs(db: Session) -> set[tuple[str, str]]:
    """Return set of normalized (c1, c2) pairs with active battles."""
    active = db.query(BattleORM).filter(BattleORM.status == "ACTIVE").all()
    return {_normalize_pair(b.creator1_id, b.creator2_id) for b in active}


def _normalize_pair(id1: str, id2: str) -> tuple[str, str]:
    """Return a sorted tuple so (a,b) and (b,a) are the same pair."""
    return (min(id1, id2), max(id1, id2))


def run_matchmaking(db: Session) -> list[BattleORM]:
    """Match queued bots by similar ELO rating.

    1. Pull all bots from the matchmaking queue
    2. Fetch their ELO ratings (default 1200 for unrated)
    3. Sort by ELO, pair adjacent bots within MAX_ELO_GAP
    4. Skip pairs that already have an active battle
    5. Create AUTO battles, remove matched bots from queue

    Returns the list of newly created battles.
    """
    queue_entries = db.query(MatchmakingQueueORM).order_by(MatchmakingQueueORM.queued_at).all()

    if len(queue_entries) < 2:
        return []

    # Build (bot_id, elo) list sorted by ELO
    bots_with_elo = []
    for entry in queue_entries:
        elo = _get_elo(db, entry.bot_id)
        bots_with_elo.append((entry.bot_id, elo, entry))

    bots_with_elo.sort(key=lambda x: x[1])

    active_pairs = _get_active_pairs(db)
    now = datetime.now(UTC)
    new_battles = []
    matched_ids = set()

    for i in range(len(bots_with_elo)):
        bot_a_id, elo_a, entry_a = bots_with_elo[i]
        if bot_a_id in matched_ids:
            continue

        for j in range(i + 1, len(bots_with_elo)):
            bot_b_id, elo_b, entry_b = bots_with_elo[j]
            if bot_b_id in matched_ids:
                continue

            if abs(elo_a - elo_b) > MAX_ELO_GAP:
                break  # sorted by ELO, no point checking further

            pair = _normalize_pair(bot_a_id, bot_b_id)
            if pair in active_pairs:
                continue

            # Match found
            battle = BattleORM(
                battle_id=uuid.uuid4().hex,
                creator1_id=bot_a_id,
                creator2_id=bot_b_id,
                status="ACTIVE",
                window_days=DEFAULT_WINDOW_DAYS,
                created_at=now,
                battle_type="AUTO",
            )
            db.add(battle)
            new_battles.append(battle)
            active_pairs.add(pair)
            matched_ids.add(bot_a_id)
            matched_ids.add(bot_b_id)

            # Remove matched bots from queue
            db.delete(entry_a)
            db.delete(entry_b)
            break

    if new_battles:
        db.commit()
    return new_battles
