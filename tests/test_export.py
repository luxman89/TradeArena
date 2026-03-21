"""Tests for GET /export/signals and GET /export/analytics endpoints."""

from __future__ import annotations

import csv
import hashlib
import io
import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, CreatorScoreORM, SignalORM, get_db

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
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


API_KEY = f"ta-{secrets.token_hex(16)}"
API_KEY_HASH = hashlib.sha256(API_KEY.encode()).hexdigest()
CREATOR_ID = "test-export-a1b2"


@pytest.fixture()
def seeded_creator():
    """Create a creator with an API key and some signals."""
    db = TestingSessionLocal()
    creator = CreatorORM(
        id=CREATOR_ID,
        display_name="Test Exporter",
        division="crypto",
        email="export@test.com",
        api_key_hash=API_KEY_HASH,
        created_at=datetime.now(UTC),
    )
    db.add(creator)

    # Add two signals
    for i, outcome in enumerate(["WIN", "LOSS"]):
        sig = SignalORM(
            signal_id=secrets.token_hex(16),
            creator_id=CREATOR_ID,
            asset="BTC/USDT",
            action="buy",
            confidence=0.75,
            reasoning=(
                "A reasonably long reasoning string that exceeds"
                " the minimum word count for validation purposes here."
            ),
            supporting_data={"rsi": 55, "volume": 1200000},
            target_price=50000.0,
            stop_loss=44000.0,
            timeframe="4h",
            commitment_hash=secrets.token_hex(32),
            committed_at=datetime(2026, 1, 1 + i, tzinfo=UTC),
            outcome=outcome,
            outcome_price=51000.0 if outcome == "WIN" else 43000.0,
            outcome_at=datetime(2026, 1, 2 + i, tzinfo=UTC),
        )
        db.add(sig)

    db.commit()
    db.close()
    return CREATOR_ID


class TestExportSignalsJSON:
    def test_returns_200_with_signals(self, client, seeded_creator):
        resp = client.get("/export/signals", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        data = resp.json()
        assert data["creator_id"] == CREATOR_ID
        assert data["total"] == 2
        assert len(data["signals"]) == 2

    def test_signal_fields_present(self, client, seeded_creator):
        resp = client.get("/export/signals", headers={"X-API-Key": API_KEY})
        sig = resp.json()["signals"][0]
        for field in [
            "signal_id",
            "asset",
            "action",
            "confidence",
            "reasoning",
            "target_price",
            "stop_loss",
            "timeframe",
            "commitment_hash",
            "committed_at",
            "outcome",
            "outcome_price",
            "outcome_at",
        ]:
            assert field in sig

    def test_empty_signals(self, client):
        # Register a creator with no signals
        db = TestingSessionLocal()
        key = f"ta-{secrets.token_hex(16)}"
        db.add(
            CreatorORM(
                id="empty-creator-0000",
                display_name="Empty",
                division="crypto",
                email="empty@test.com",
                api_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        db.close()
        resp = client.get("/export/signals", headers={"X-API-Key": key})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["signals"] == []

    def test_no_api_key_returns_401(self, client):
        resp = client.get("/export/signals")
        assert resp.status_code == 401

    def test_bad_api_key_returns_403(self, client):
        resp = client.get("/export/signals", headers={"X-API-Key": "ta-invalid"})
        assert resp.status_code == 403


class TestExportSignalsCSV:
    def test_returns_csv(self, client, seeded_creator):
        resp = client.get("/export/signals?format=csv", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_csv_has_correct_rows(self, client, seeded_creator):
        resp = client.get("/export/signals?format=csv", headers={"X-API-Key": API_KEY})
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["asset"] == "BTC/USDT"

    def test_csv_header_columns(self, client, seeded_creator):
        resp = client.get("/export/signals?format=csv", headers={"X-API-Key": API_KEY})
        reader = csv.DictReader(io.StringIO(resp.text))
        assert set(reader.fieldnames) == {
            "signal_id",
            "asset",
            "action",
            "confidence",
            "reasoning",
            "target_price",
            "stop_loss",
            "timeframe",
            "commitment_hash",
            "committed_at",
            "outcome",
            "outcome_price",
            "outcome_at",
        }

    def test_empty_csv(self, client):
        db = TestingSessionLocal()
        key = f"ta-{secrets.token_hex(16)}"
        db.add(
            CreatorORM(
                id="empty-csv-0000",
                display_name="Empty CSV",
                division="crypto",
                email="emptycsv@test.com",
                api_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        db.close()
        resp = client.get("/export/signals?format=csv", headers={"X-API-Key": key})
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.text))
        assert list(reader) == []


class TestExportAnalytics:
    def test_returns_200(self, client, seeded_creator):
        resp = client.get("/export/analytics", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200

    def test_contains_analytics_and_scores(self, client, seeded_creator):
        resp = client.get("/export/analytics", headers={"X-API-Key": API_KEY})
        data = resp.json()
        assert data["creator_id"] == CREATOR_ID
        assert "equity_curve" in data
        assert "streaks" in data
        assert "scores" in data
        assert "composite" in data["scores"]

    def test_scores_default_zero_without_score_record(self, client, seeded_creator):
        resp = client.get("/export/analytics", headers={"X-API-Key": API_KEY})
        scores = resp.json()["scores"]
        assert scores["composite"] == 0.0
        assert scores["total_signals"] == 0

    def test_with_score_record(self, client, seeded_creator):
        db = TestingSessionLocal()
        db.add(
            CreatorScoreORM(
                creator_id=CREATOR_ID,
                win_rate=0.6,
                risk_adjusted_return=0.5,
                consistency=0.7,
                confidence_calibration=0.8,
                composite_score=0.65,
                total_signals=2,
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
        db.close()
        resp = client.get("/export/analytics", headers={"X-API-Key": API_KEY})
        scores = resp.json()["scores"]
        assert scores["composite"] == 0.65
        assert scores["total_signals"] == 2

    def test_range_filter(self, client, seeded_creator):
        resp = client.get("/export/analytics?range=7d", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert resp.json()["range"] == "7d"

    def test_invalid_range(self, client, seeded_creator):
        resp = client.get("/export/analytics?range=999d", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 422

    def test_no_api_key_returns_401(self, client):
        resp = client.get("/export/analytics")
        assert resp.status_code == 401
