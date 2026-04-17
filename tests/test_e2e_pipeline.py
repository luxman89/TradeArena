"""End-to-end integration tests for the full signal pipeline.

Exercises: Registration → Auth → Signal Submission → Commitment → Storage →
Score tracking → Leaderboard. Uses a real in-memory SQLite database (no mocks).
"""

from __future__ import annotations

import hashlib
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.api.rate_limit import signal_rate_limiter
from tradearena.db.database import Base, CreatorScoreORM, SignalORM, get_db

# ---------------------------------------------------------------------------
# Test DB setup — in-memory SQLite, isolated per test
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_db():
    """Drop/recreate tables and clear rate limiter state before each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    signal_rate_limiter._hits.clear()
    yield
    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTRATION_PAYLOAD = {
    "display_name": "Integration Tester",
    "division": "crypto",
    "strategy_description": "Momentum strategy based on RSI divergence and volume analysis.",
    "email": "integration@example.com",
}

VALID_SIGNAL = {
    "asset": "BTCUSDT",
    "action": "long",
    "confidence": 0.75,
    "reasoning": (
        "Bitcoin is showing strong bullish momentum with RSI divergence "
        "confirmed by increasing volume across major exchanges and breakout "
        "above key resistance levels on the daily chart"
    ),
    "supporting_data": {
        "rsi": 62.5,
        "volume_change": 1.35,
        "resistance_level": 67000,
    },
    "target_price": 72000.0,
    "stop_loss": 64000.0,
    "timeframe": "1d",
}


def register_creator(client: TestClient, **overrides) -> dict:
    """Register a creator and return the full response body."""
    payload = {**REGISTRATION_PAYLOAD, **overrides}
    resp = client.post("/creator/register", json=payload)
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    return resp.json()


def submit_signal(client: TestClient, api_key: str, **overrides) -> dict:
    """Submit a signal and return the full response body."""
    payload = {**VALID_SIGNAL, **overrides}
    resp = client.post("/signal", json=payload, headers={"X-API-Key": api_key})
    return resp.json() if resp.status_code == 201 else {"_status": resp.status_code, **resp.json()}


def _seed_resolved_signals(creator_id: str, count: int = 20) -> None:
    """Directly insert resolved WIN signals to meet the leaderboard minimum floor."""
    import uuid
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    db = TestingSessionLocal()
    try:
        for i in range(count):
            db.add(
                SignalORM(
                    signal_id=uuid.uuid4().hex,
                    creator_id=creator_id,
                    asset="BTCUSDT",
                    action="long",
                    confidence=0.75,
                    reasoning=(
                        "Test resolved prediction with sufficient word count for validation seed "
                        + str(i)
                    ),
                    supporting_data={"rsi": 62.0, "volume": "high"},
                    commitment_hash=hashlib.sha256(
                        f"{creator_id}-resolved-{i}".encode()
                    ).hexdigest(),
                    committed_at=now,
                    outcome="WIN",
                    outcome_price=50000.0,
                    outcome_at=now,
                )
            )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Happy-path: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Register → submit signal → verify storage → check leaderboard."""

    def test_register_and_submit_signal(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json=VALID_SIGNAL,
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "signal_id" in data
        assert "commitment_hash" in data
        assert "committed_at" in data
        assert data["creator_id"] == creator["creator_id"]
        assert data["asset"] == "BTCUSDT"
        assert data["action"] == "long"

    def test_signal_id_format(self, client):
        creator = register_creator(client)
        data = submit_signal(client, creator["api_key"])
        # UUID4 hex — 32 lowercase hex chars
        assert re.match(r"^[0-9a-f]{32}$", data["signal_id"])

    def test_commitment_hash_format(self, client):
        creator = register_creator(client)
        data = submit_signal(client, creator["api_key"])
        # SHA-256 hex — 64 lowercase hex chars
        assert re.match(r"^[0-9a-f]{64}$", data["commitment_hash"])

    def test_signal_stored_in_db(self, client):
        creator = register_creator(client)
        data = submit_signal(client, creator["api_key"])
        db = TestingSessionLocal()
        try:
            signal = db.query(SignalORM).filter(SignalORM.signal_id == data["signal_id"]).first()
            assert signal is not None
            assert signal.creator_id == creator["creator_id"]
            assert signal.asset == "BTCUSDT"
            assert signal.action == "long"
            assert signal.confidence == 0.75
            assert signal.target_price == 72000.0
            assert signal.stop_loss == 64000.0
            assert signal.timeframe == "1d"
            assert signal.commitment_hash == data["commitment_hash"]
            # New signal — outcome pending
            assert signal.outcome is None
        finally:
            db.close()

    def test_commitment_hash_is_unique_per_signal(self, client):
        creator = register_creator(client)
        d1 = submit_signal(client, creator["api_key"])
        d2 = submit_signal(client, creator["api_key"])
        assert d1["signal_id"] != d2["signal_id"]
        assert d1["commitment_hash"] != d2["commitment_hash"]

    def test_total_signals_incremented(self, client):
        creator = register_creator(client)
        submit_signal(client, creator["api_key"])
        submit_signal(client, creator["api_key"])
        db = TestingSessionLocal()
        try:
            score = (
                db.query(CreatorScoreORM)
                .filter(CreatorScoreORM.creator_id == creator["creator_id"])
                .first()
            )
            assert score is not None
            assert score.total_signals == 2
        finally:
            db.close()

    def test_creator_appears_on_leaderboard(self, client):
        creator = register_creator(client)
        _seed_resolved_signals(creator["creator_id"], count=20)
        submit_signal(client, creator["api_key"])
        resp = client.get("/leaderboard")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        ids = [e["creator_id"] for e in entries]
        assert creator["creator_id"] in ids

    def test_creator_appears_on_division_leaderboard(self, client):
        creator = register_creator(client)
        _seed_resolved_signals(creator["creator_id"], count=20)
        submit_signal(client, creator["api_key"])
        resp = client.get("/leaderboard/crypto")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        ids = [e["creator_id"] for e in entries]
        assert creator["creator_id"] in ids

    def test_multiple_creators_on_leaderboard(self, client):
        c1 = register_creator(client, email="a@example.com", display_name="Creator Alpha")
        c2 = register_creator(client, email="b@example.com", display_name="Creator Bravo")
        _seed_resolved_signals(c1["creator_id"], count=20)
        _seed_resolved_signals(c2["creator_id"], count=20)
        submit_signal(client, c1["api_key"])
        submit_signal(client, c2["api_key"])
        resp = client.get("/leaderboard")
        assert resp.status_code == 200
        ids = [e["creator_id"] for e in resp.json()["entries"]]
        assert c1["creator_id"] in ids
        assert c2["creator_id"] in ids


# ---------------------------------------------------------------------------
# Auth error cases
# ---------------------------------------------------------------------------


class TestAuthErrors:
    def test_missing_api_key_returns_401(self, client):
        resp = client.post("/signal", json=VALID_SIGNAL)
        assert resp.status_code == 401

    def test_invalid_api_key_returns_403(self, client):
        resp = client.post(
            "/signal",
            json=VALID_SIGNAL,
            headers={"X-API-Key": "ta-0000000000000000deadbeefcafebabe"},
        )
        assert resp.status_code == 403

    def test_malformed_api_key_returns_403(self, client):
        resp = client.post(
            "/signal",
            json=VALID_SIGNAL,
            headers={"X-API-Key": "not-a-valid-key"},
        )
        assert resp.status_code == 403

    def test_api_key_stored_as_hash(self, client):
        """The returned API key authenticates, but only its hash is in the DB."""
        creator = register_creator(client)
        from tradearena.db.database import CreatorORM

        db = TestingSessionLocal()
        try:
            row = db.query(CreatorORM).filter(CreatorORM.id == creator["creator_id"]).first()
            expected_hash = hashlib.sha256(creator["api_key"].encode()).hexdigest()
            assert row.api_key_hash == expected_hash
            assert row.api_key_dev is None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Validation error cases
# ---------------------------------------------------------------------------


class TestValidationErrors:
    def test_invalid_action_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "action": "hodl"},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_confidence_too_low_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "confidence": 0.0},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_confidence_too_high_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "confidence": 1.0},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_reasoning_too_short_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "reasoning": "Too short"},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_supporting_data_too_few_keys_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "supporting_data": {"only_one": 1}},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_missing_required_field_returns_422(self, client):
        creator = register_creator(client)
        incomplete = {k: v for k, v in VALID_SIGNAL.items() if k != "asset"}
        resp = client.post(
            "/signal",
            json=incomplete,
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_stop_loss_above_target_for_long_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "action": "long", "target_price": 70000, "stop_loss": 75000},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422

    def test_stop_loss_below_target_for_short_returns_422(self, client):
        creator = register_creator(client)
        resp = client.post(
            "/signal",
            json={**VALID_SIGNAL, "action": "short", "target_price": 60000, "stop_loss": 55000},
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestSignalRateLimit:
    def test_rate_limit_after_10_signals(self, client):
        creator = register_creator(client)
        for i in range(10):
            resp = client.post(
                "/signal",
                json=VALID_SIGNAL,
                headers={"X-API-Key": creator["api_key"]},
            )
            assert resp.status_code == 201, f"Signal {i + 1} failed: {resp.text}"

        # 11th signal should be rate-limited
        resp = client.post(
            "/signal",
            json=VALID_SIGNAL,
            headers={"X-API-Key": creator["api_key"]},
        )
        assert resp.status_code == 429

    def test_rate_limit_is_per_creator(self, client):
        c1 = register_creator(client, email="c1@example.com", display_name="Rate Limit Alpha")
        c2 = register_creator(client, email="c2@example.com", display_name="Rate Limit Bravo")

        # Exhaust c1's quota
        for _ in range(10):
            resp = client.post(
                "/signal",
                json=VALID_SIGNAL,
                headers={"X-API-Key": c1["api_key"]},
            )
            assert resp.status_code == 201

        # c2 should still be able to submit
        resp = client.post(
            "/signal",
            json=VALID_SIGNAL,
            headers={"X-API-Key": c2["api_key"]},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Append-only integrity
# ---------------------------------------------------------------------------


class TestAppendOnlyIntegrity:
    def test_signals_accumulate_not_replace(self, client):
        creator = register_creator(client)
        ids = set()
        for _ in range(3):
            data = submit_signal(client, creator["api_key"])
            ids.add(data["signal_id"])
        assert len(ids) == 3

        db = TestingSessionLocal()
        try:
            count = (
                db.query(SignalORM).filter(SignalORM.creator_id == creator["creator_id"]).count()
            )
            assert count == 3
        finally:
            db.close()

    def test_different_assets_stored_independently(self, client):
        creator = register_creator(client)
        submit_signal(client, creator["api_key"], asset="BTCUSDT")
        submit_signal(client, creator["api_key"], asset="ETHUSDT")
        db = TestingSessionLocal()
        try:
            signals = (
                db.query(SignalORM).filter(SignalORM.creator_id == creator["creator_id"]).all()
            )
            assets = {s.asset for s in signals}
            assert assets == {"BTCUSDT", "ETHUSDT"}
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Leaderboard edge cases
# ---------------------------------------------------------------------------


class TestLeaderboardEdgeCases:
    def test_empty_leaderboard(self, client):
        resp = client.get("/leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["entries"] == []

    def test_invalid_division_returns_422(self, client):
        resp = client.get("/leaderboard/stocks")
        assert resp.status_code == 422

    def test_leaderboard_total_signals_reflects_submissions(self, client):
        creator = register_creator(client)
        _seed_resolved_signals(creator["creator_id"], count=20)
        submit_signal(client, creator["api_key"])
        submit_signal(client, creator["api_key"])
        submit_signal(client, creator["api_key"])
        resp = client.get("/leaderboard")
        entries = resp.json()["entries"]
        entry = next(e for e in entries if e["creator_id"] == creator["creator_id"])
        assert entry["total_signals"] == 3  # score row tracks API-submitted signals only

    def test_creator_without_signals_on_leaderboard(self, client):
        """A creator with fewer than 20 resolved signals does NOT appear on the leaderboard."""
        creator = register_creator(client)
        resp = client.get("/leaderboard")
        assert resp.status_code == 200
        ids = [e["creator_id"] for e in resp.json()["entries"]]
        assert creator["creator_id"] not in ids
