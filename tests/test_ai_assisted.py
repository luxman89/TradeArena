"""Tests for ai_assisted signal column and leaderboard field."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, SignalORM, get_db

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


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app, raise_server_exceptions=True)

_SIGNAL_BODY = {
    "asset": "BTCUSDT",
    "action": "buy",
    "confidence": 0.75,
    "reasoning": (
        "Strong momentum breakout with volume confirmation and trend alignment "
        "showing RSI at sixty two bullish crossover on the daily chart timeframe"
    ),
    "supporting_data": {"rsi": 62, "macd": "bullish"},
}

_TOS_HASH = "79cf6fb69a652cf01c58210084de60e10da3790d23dfcdb1a2e804ec7339aa91"


@pytest.fixture(autouse=True)
def reset_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed_verified_creator() -> str:
    """Return an API key for a creator that is email-verified."""
    api_key = f"ta-{secrets.token_hex(16)}"
    db = TestingSessionLocal()
    creator = CreatorORM(
        id="ai-tester-aaaa",
        display_name="AI Tester",
        division="crypto",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        created_at=datetime.now(UTC),
        email_verified_at=datetime.now(UTC),
        tos_hash=_TOS_HASH,
        tos_accepted_at=datetime.now(UTC),
        password_hash=None,
    )
    db.add(creator)
    db.commit()
    db.close()
    return api_key


class TestAiAssistedColumn:
    def test_signal_defaults_not_ai_assisted(self):
        """Signals submitted without ai_assisted=True default to False."""
        api_key = _seed_verified_creator()
        resp = client.post("/signal", json=_SIGNAL_BODY, headers={"X-API-Key": api_key})
        assert resp.status_code == 201
        assert resp.json()["ai_assisted"] is False

        db = TestingSessionLocal()
        sig = db.query(SignalORM).first()
        assert sig.ai_assisted is False
        db.close()

    def test_signal_with_ai_assisted_true(self):
        """Signal submitted with ai_assisted=True is persisted correctly."""
        api_key = _seed_verified_creator()
        body = {**_SIGNAL_BODY, "ai_assisted": True}
        resp = client.post("/signal", json=body, headers={"X-API-Key": api_key})
        assert resp.status_code == 201
        assert resp.json()["ai_assisted"] is True

        db = TestingSessionLocal()
        sig = db.query(SignalORM).first()
        assert sig.ai_assisted is True
        db.close()

    def test_creator_signals_endpoint_includes_ai_assisted(self):
        """GET /creator/{id}/signals returns ai_assisted per signal."""
        api_key = _seed_verified_creator()
        body_ai = {**_SIGNAL_BODY, "ai_assisted": True}
        client.post("/signal", json=body_ai, headers={"X-API-Key": api_key})

        resp = client.get("/creator/ai-tester-aaaa/signals")
        assert resp.status_code == 200
        signals = resp.json()["signals"]
        assert len(signals) == 1
        assert signals[0]["ai_assisted"] is True

    def test_non_ai_signal_in_feed(self):
        """Non-AI signals return ai_assisted=False in the signal feed."""
        api_key = _seed_verified_creator()
        client.post("/signal", json=_SIGNAL_BODY, headers={"X-API-Key": api_key})

        resp = client.get("/creator/ai-tester-aaaa/signals")
        assert resp.status_code == 200
        signals = resp.json()["signals"]
        assert signals[0]["ai_assisted"] is False
