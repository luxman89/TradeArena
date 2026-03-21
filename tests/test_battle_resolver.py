"""Tests for the battle resolver — scoring + draw conditions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.core.battle_resolver import DRAW_THRESHOLD, resolve_battle
from tradearena.db.database import Base, BattleORM, CreatorORM, SignalORM

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


def _make_battle(
    db, c1_id: str, c2_id: str, window_days: int = 7, battle_type: str = "MANUAL"
) -> BattleORM:
    b = BattleORM(
        battle_id=uuid.uuid4().hex,
        creator1_id=c1_id,
        creator2_id=c2_id,
        status="ACTIVE",
        window_days=window_days,
        created_at=datetime.now(UTC),
        battle_type=battle_type,
    )
    db.add(b)
    db.commit()
    return b


class TestResolveBattle:
    def test_resolves_with_clear_winner(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        # Alice: all wins
        for i in range(5):
            _make_signal(db, "alice", outcome="WIN", confidence=0.8, days_ago=i + 1)

        # Bob: all losses
        for i in range(5):
            _make_signal(db, "bob", outcome="LOSS", confidence=0.3, days_ago=i + 1)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)

        assert result is not None
        assert result.status == "RESOLVED"
        assert result.winner_id == "alice"
        assert result.creator1_score > result.creator2_score
        assert result.margin > 0
        assert result.resolved_at is not None

    def test_returns_none_if_too_few_signals(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        _make_signal(db, "alice", outcome="WIN", days_ago=2)
        _make_signal(db, "alice", outcome="WIN", days_ago=3)
        # Bob only has 1 resolved signal
        _make_signal(db, "bob", outcome="WIN", days_ago=2)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)
        assert result is None

    def test_pending_signals_dont_count_for_minimum(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        _make_signal(db, "alice", outcome="WIN", days_ago=2)
        _make_signal(db, "alice", outcome="WIN", days_ago=3)
        # Bob has 2 signals but only 1 resolved
        _make_signal(db, "bob", outcome="WIN", days_ago=2)
        _make_signal(db, "bob", outcome=None, days_ago=3)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)
        assert result is None

    def test_draw_when_scores_very_close(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        # Same signals for both → identical scores → draw
        for cid in ("alice", "bob"):
            for i in range(5):
                _make_signal(db, cid, outcome="WIN", confidence=0.7, days_ago=i + 1)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)

        assert result is not None
        assert result.status == "RESOLVED"
        assert result.winner_id is None  # draw
        assert result.margin < DRAW_THRESHOLD

    def test_details_contain_all_dimensions(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        for cid in ("alice", "bob"):
            for i in range(3):
                _make_signal(db, cid, outcome="WIN", days_ago=i + 1)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)

        assert result is not None
        expected_keys = {
            "win_rate",
            "risk_adjusted_return",
            "consistency",
            "confidence_calibration",
            "composite",
        }
        assert set(result.creator1_details.keys()) == expected_keys
        assert set(result.creator2_details.keys()) == expected_keys

    def test_window_excludes_old_signals(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        # Alice has wins but all outside the 7-day window
        for i in range(5):
            _make_signal(db, "alice", outcome="WIN", days_ago=10 + i)
        # Plus 2 recent losses
        _make_signal(db, "alice", outcome="LOSS", days_ago=1)
        _make_signal(db, "alice", outcome="LOSS", days_ago=2)

        # Bob has recent wins
        for i in range(5):
            _make_signal(db, "bob", outcome="WIN", days_ago=i + 1)

        battle = _make_battle(db, "alice", "bob", window_days=7)
        result = resolve_battle(battle, db)

        assert result is not None
        assert result.winner_id == "bob"

    def test_second_creator_wins(self, db):
        _make_creator(db, "alice")
        _make_creator(db, "bob")

        for i in range(3):
            _make_signal(db, "alice", outcome="LOSS", confidence=0.3, days_ago=i + 1)
        for i in range(3):
            _make_signal(db, "bob", outcome="WIN", confidence=0.9, days_ago=i + 1)

        battle = _make_battle(db, "alice", "bob")
        result = resolve_battle(battle, db)

        assert result is not None
        assert result.winner_id == "bob"
        assert result.creator2_score > result.creator1_score
