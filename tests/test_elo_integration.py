"""Integration test: queue → match → battle → resolve → ELO update."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.core.battle_resolver import resolve_battle
from tradearena.core.elo import DEFAULT_RATING
from tradearena.core.matchmaker import join_queue, run_matchmaking
from tradearena.db.database import (
    Base,
    BattleORM,
    BotRatingORM,
    CreatorORM,
    RatingHistoryORM,
    SignalORM,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _make_creator(db, creator_id: str) -> CreatorORM:
    c = CreatorORM(
        id=creator_id,
        display_name=creator_id.title(),
        created_at=datetime.now(UTC) - timedelta(days=60),
        division="crypto",
    )
    db.add(c)
    db.commit()
    return c


def _make_signal(
    db,
    creator_id: str,
    outcome: str | None = "WIN",
    confidence: float = 0.7,
    days_ago: int = 3,
) -> SignalORM:
    sig_id = uuid.uuid4().hex
    reasoning = (
        "This is a detailed technical analysis signal with RSI divergence and "
        "volume confirmation across multiple timeframes showing clear momentum "
        "shift above the key resistance breakout level."
    )
    s = SignalORM(
        signal_id=sig_id,
        creator_id=creator_id,
        asset="BTC/USDT",
        action="BUY",
        confidence=confidence,
        reasoning=reasoning,
        supporting_data={"rsi": 55, "volume": 1000000},
        commitment_hash=uuid.uuid4().hex + uuid.uuid4().hex[:32],
        committed_at=datetime.now(UTC) - timedelta(days=days_ago),
        outcome=outcome,
        outcome_price=50000.0 if outcome else None,
        outcome_at=datetime.now(UTC) - timedelta(days=days_ago - 1) if outcome else None,
    )
    db.add(s)
    db.commit()
    return s


class TestFullEloFlow:
    def test_queue_match_resolve_elo_update(self, db):
        """Full integration: two bots queue → matched → battle resolves → ELO updates."""
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        # 1. Both join queue
        join_queue(db, "alice")
        join_queue(db, "bob")

        # 2. Matchmaking creates a battle
        battles = run_matchmaking(db)
        assert len(battles) == 1
        battle = battles[0]
        assert battle.status == "ACTIVE"

        # 3. Add signals so battle can resolve
        # Alice: all wins
        for i in range(5):
            _make_signal(db, "alice", outcome="WIN", confidence=0.8, days_ago=i + 1)
        # Bob: all losses
        for i in range(5):
            _make_signal(db, "bob", outcome="LOSS", confidence=0.3, days_ago=i + 1)

        # 4. Resolve the battle
        result = resolve_battle(battle, db)
        assert result is not None
        assert result.status == "RESOLVED"
        assert result.winner_id == "alice"

        # 5. Verify ELO was updated
        alice_rating = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "alice").first()
        bob_rating = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "bob").first()

        assert alice_rating is not None
        assert bob_rating is not None
        assert alice_rating.elo > DEFAULT_RATING  # winner gained
        assert bob_rating.elo < DEFAULT_RATING  # loser dropped
        assert alice_rating.wins == 1
        assert alice_rating.losses == 0
        assert bob_rating.wins == 0
        assert bob_rating.losses == 1
        assert alice_rating.matches_played == 1
        assert bob_rating.matches_played == 1

        # 6. Verify rating history was recorded
        history = db.query(RatingHistoryORM).all()
        assert len(history) == 2
        alice_hist = [h for h in history if h.bot_id == "alice"]
        bob_hist = [h for h in history if h.bot_id == "bob"]
        assert len(alice_hist) == 1
        assert len(bob_hist) == 1
        assert alice_hist[0].elo == alice_rating.elo
        assert bob_hist[0].elo == bob_rating.elo
        assert alice_hist[0].match_id == battle.battle_id

    def test_draw_both_stay_near_default(self, db):
        """Draw: both bots have identical signals → ELO barely changes."""
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        # Same signals for both
        for cid in ("alice", "bob"):
            for i in range(5):
                _make_signal(db, cid, outcome="WIN", confidence=0.7, days_ago=i + 1)

        # Create battle directly
        battle = BattleORM(
            battle_id=uuid.uuid4().hex,
            creator1_id="alice",
            creator2_id="bob",
            status="ACTIVE",
            window_days=7,
            created_at=datetime.now(UTC),
            battle_type="AUTO",
        )
        db.add(battle)
        db.commit()

        result = resolve_battle(battle, db)
        assert result is not None
        assert result.winner_id is None  # draw

        alice_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "alice").first()
        bob_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "bob").first()

        assert alice_r.draws == 1
        assert bob_r.draws == 1
        # ELO should stay very close to default for equal ratings + draw
        assert abs(alice_r.elo - DEFAULT_RATING) < 1.0
        assert abs(bob_r.elo - DEFAULT_RATING) < 1.0

    def test_new_bot_vs_established_bot(self, db):
        """New bot (few matches) has higher K-factor than established bot."""
        _make_creator(db, "newbie")
        _make_creator(db, "veteran")

        # Give veteran an existing rating with many matches
        vet_rating = BotRatingORM(
            bot_id="veteran",
            elo=1200,
            matches_played=50,
            wins=25,
            losses=25,
            draws=0,
            updated_at=datetime.now(UTC),
        )
        db.add(vet_rating)
        db.commit()

        # Newbie wins
        for i in range(5):
            _make_signal(db, "newbie", outcome="WIN", confidence=0.8, days_ago=i + 1)
        for i in range(5):
            _make_signal(db, "veteran", outcome="LOSS", confidence=0.3, days_ago=i + 1)

        battle = BattleORM(
            battle_id=uuid.uuid4().hex,
            creator1_id="newbie",
            creator2_id="veteran",
            status="ACTIVE",
            window_days=7,
            created_at=datetime.now(UTC),
            battle_type="AUTO",
        )
        db.add(battle)
        db.commit()

        resolve_battle(battle, db)

        newbie_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "newbie").first()
        vet_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "veteran").first()

        # Newbie gains more (K=32) than veteran loses (K=16)
        newbie_gain = newbie_r.elo - DEFAULT_RATING
        vet_loss = 1200 - vet_r.elo
        assert newbie_gain > vet_loss

    def test_large_elo_gap_battle(self, db):
        """High-rated bot beats low-rated bot — minimal ELO change."""
        _make_creator(db, "strong")
        _make_creator(db, "weak")

        db.add(
            BotRatingORM(
                bot_id="strong",
                elo=1500,
                matches_played=0,
                wins=0,
                losses=0,
                draws=0,
            )
        )
        db.add(
            BotRatingORM(
                bot_id="weak",
                elo=1100,
                matches_played=0,
                wins=0,
                losses=0,
                draws=0,
            )
        )
        db.commit()

        for i in range(5):
            _make_signal(db, "strong", outcome="WIN", confidence=0.8, days_ago=i + 1)
        for i in range(5):
            _make_signal(db, "weak", outcome="LOSS", confidence=0.3, days_ago=i + 1)

        battle = BattleORM(
            battle_id=uuid.uuid4().hex,
            creator1_id="strong",
            creator2_id="weak",
            status="ACTIVE",
            window_days=7,
            created_at=datetime.now(UTC),
            battle_type="AUTO",
        )
        db.add(battle)
        db.commit()

        resolve_battle(battle, db)

        strong_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "strong").first()
        weak_r = db.query(BotRatingORM).filter(BotRatingORM.bot_id == "weak").first()

        # Expected win = small change
        assert strong_r.elo - 1500 < 5
        assert 1100 - weak_r.elo < 5
