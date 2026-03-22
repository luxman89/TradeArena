"""Tests for ELO-based matchmaking — queue, pairing, integration with battles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.core.matchmaker import (
    join_queue,
    leave_queue,
    run_matchmaking,
)
from tradearena.db.database import (
    Base,
    BattleORM,
    BotRatingORM,
    CreatorORM,
    MatchmakingQueueORM,
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


def _set_elo(db, bot_id: str, elo: float) -> BotRatingORM:
    rating = BotRatingORM(
        bot_id=bot_id,
        elo=elo,
        matches_played=0,
        wins=0,
        losses=0,
        draws=0,
        updated_at=datetime.now(UTC),
    )
    db.add(rating)
    db.commit()
    return rating


class TestJoinQueue:
    def test_join_adds_to_queue(self, db):
        _make_creator(db, "alice")
        entry = join_queue(db, "alice")

        assert entry.bot_id == "alice"
        assert entry.queued_at is not None

        queued = db.query(MatchmakingQueueORM).all()
        assert len(queued) == 1

    def test_join_idempotent(self, db):
        _make_creator(db, "alice")
        entry1 = join_queue(db, "alice")
        entry2 = join_queue(db, "alice")

        assert entry1.id == entry2.id
        assert db.query(MatchmakingQueueORM).count() == 1


class TestLeaveQueue:
    def test_leave_removes_from_queue(self, db):
        _make_creator(db, "alice")
        join_queue(db, "alice")

        result = leave_queue(db, "alice")
        assert result is True
        assert db.query(MatchmakingQueueORM).count() == 0

    def test_leave_not_in_queue(self, db):
        _make_creator(db, "alice")
        result = leave_queue(db, "alice")
        assert result is False


class TestRunMatchmaking:
    def test_pairs_two_queued_bots(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")
        join_queue(db, "alice")
        join_queue(db, "bob")

        battles = run_matchmaking(db)

        assert len(battles) == 1
        assert battles[0].battle_type == "AUTO"
        assert battles[0].status == "ACTIVE"
        # Both removed from queue
        assert db.query(MatchmakingQueueORM).count() == 0

    def test_no_match_if_fewer_than_two(self, db):
        _make_creator(db, "alice")
        join_queue(db, "alice")

        battles = run_matchmaking(db)
        assert len(battles) == 0
        assert db.query(MatchmakingQueueORM).count() == 1

    def test_pairs_by_similar_elo(self, db):
        """Three bots: alice=1200, bob=1250, charlie=1500. Alice-Bob should pair."""
        _make_creator(db, "alice")
        _make_creator(db, "bob")
        _make_creator(db, "charlie")
        _set_elo(db, "alice", 1200)
        _set_elo(db, "bob", 1250)
        _set_elo(db, "charlie", 1500)
        join_queue(db, "alice")
        join_queue(db, "bob")
        join_queue(db, "charlie")

        battles = run_matchmaking(db)

        assert len(battles) == 1
        paired_ids = {battles[0].creator1_id, battles[0].creator2_id}
        assert paired_ids == {"alice", "bob"}
        # Charlie stays in queue (too far from both)
        remaining = db.query(MatchmakingQueueORM).all()
        assert len(remaining) == 1
        assert remaining[0].bot_id == "charlie"

    def test_no_match_if_elo_gap_too_large(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")
        _set_elo(db, "alice", 1000)
        _set_elo(db, "bob", 1300)  # gap = 300 > MAX_ELO_GAP (200)
        join_queue(db, "alice")
        join_queue(db, "bob")

        battles = run_matchmaking(db)
        assert len(battles) == 0

    def test_skips_active_battle_pair(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")
        join_queue(db, "alice")
        join_queue(db, "bob")

        # Create an active battle between them
        db.add(
            BattleORM(
                battle_id=uuid.uuid4().hex,
                creator1_id="alice",
                creator2_id="bob",
                status="ACTIVE",
                window_days=7,
                created_at=datetime.now(UTC),
                battle_type="MANUAL",
            )
        )
        db.commit()

        battles = run_matchmaking(db)
        assert len(battles) == 0

    def test_multiple_pairs(self, db):
        """Four bots all at similar ELO → two battles."""
        for name in ["a", "b", "c", "d"]:
            _make_creator(db, name)
            join_queue(db, name)

        battles = run_matchmaking(db)
        assert len(battles) == 2
        assert db.query(MatchmakingQueueORM).count() == 0

    def test_default_elo_for_unrated_bots(self, db):
        """Bots without a BotRatingORM row get DEFAULT_RATING (1200)."""
        _make_creator(db, "alice")
        _make_creator(db, "bob")
        join_queue(db, "alice")
        join_queue(db, "bob")

        # Neither has a rating row — should still match at 1200 vs 1200
        battles = run_matchmaking(db)
        assert len(battles) == 1
