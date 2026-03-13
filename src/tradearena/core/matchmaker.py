"""Auto-matchmaking — pairs creators by score tier for battles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from tradearena.db.database import BattleORM, CreatorORM, CreatorScoreORM

DEFAULT_WINDOW_DAYS = 7


def run_matchmaking(db: Session) -> list[BattleORM]:
    """Match creators into battles by score tier.

    1. Query all creators with scores, sorted by composite_score
    2. Split into 3 tiers (top/mid/bottom 33%)
    3. Within each tier, pair creators who don't already have an active battle
    4. Create ACTIVE battles with window_days=7

    Returns the list of newly created battles.
    """
    creators = (
        db.query(CreatorORM)
        .join(CreatorScoreORM, CreatorORM.id == CreatorScoreORM.creator_id)
        .order_by(CreatorScoreORM.composite_score.desc())
        .all()
    )

    if len(creators) < 2:
        return []

    # Split into tiers
    tiers = _split_into_tiers(creators)

    # Get all active battle pairs to avoid duplicates
    active_pairs = _get_active_pairs(db)

    now = datetime.now(UTC)
    new_battles = []

    for tier in tiers:
        if len(tier) < 2:
            continue
        unpaired = list(tier)
        while len(unpaired) >= 2:
            c1 = unpaired.pop(0)
            matched = False
            for i, c2 in enumerate(unpaired):
                pair = _normalize_pair(c1.id, c2.id)
                if pair not in active_pairs:
                    unpaired.pop(i)
                    battle = BattleORM(
                        battle_id=uuid.uuid4().hex,
                        creator1_id=c1.id,
                        creator2_id=c2.id,
                        status="ACTIVE",
                        window_days=DEFAULT_WINDOW_DAYS,
                        created_at=now,
                        battle_type="AUTO",
                    )
                    db.add(battle)
                    new_battles.append(battle)
                    active_pairs.add(pair)
                    matched = True
                    break
            if not matched:
                break

    db.commit()
    return new_battles


def _split_into_tiers(creators: list[CreatorORM]) -> list[list[CreatorORM]]:
    """Split creators into 3 roughly equal tiers."""
    n = len(creators)
    if n <= 3:
        return [creators]
    third = n // 3
    return [
        creators[:third],
        creators[third : 2 * third],
        creators[2 * third :],
    ]


def _normalize_pair(id1: str, id2: str) -> tuple[str, str]:
    """Return a sorted tuple so (a,b) and (b,a) are the same pair."""
    return (min(id1, id2), max(id1, id2))


def _get_active_pairs(db: Session) -> set[tuple[str, str]]:
    """Return set of normalized (creator1, creator2) pairs with active battles."""
    active = db.query(BattleORM).filter(BattleORM.status == "ACTIVE").all()
    return {_normalize_pair(b.creator1_id, b.creator2_id) for b in active}
