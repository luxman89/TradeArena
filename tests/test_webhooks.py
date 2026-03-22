"""Tests for webhook system: API endpoints, delivery engine, HMAC signing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.core.webhooks import _compute_signature, deliver_webhook
from tradearena.db.database import Base, CreatorORM, get_db

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


API_KEY = "ta-" + "a1" * 16
API_KEY_HASH = hashlib.sha256(API_KEY.encode()).hexdigest()


def _seed_creator(creator_id: str = "test-creator-0001", webhook_url: str | None = None) -> None:
    """Insert a creator with known API key hash."""
    db = TestingSessionLocal()
    try:
        db.add(
            CreatorORM(
                id=creator_id,
                display_name="Test Creator",
                created_at=datetime.now(UTC),
                division="crypto",
                api_key_hash=API_KEY_HASH,
                webhook_url=webhook_url,
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# HMAC signature tests
# ---------------------------------------------------------------------------


class TestHMACSignature:
    def test_compute_signature_deterministic(self):
        payload = b'{"event":"test","data":{}}'
        secret = "my-secret"
        sig1 = _compute_signature(payload, secret)
        sig2 = _compute_signature(payload, secret)
        assert sig1 == sig2

    def test_compute_signature_matches_hmac(self):
        payload = b'{"key":"value"}'
        secret = "test-secret"
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _compute_signature(payload, secret) == expected

    def test_different_secrets_produce_different_signatures(self):
        payload = b'{"event":"test"}'
        sig1 = _compute_signature(payload, "secret-1")
        sig2 = _compute_signature(payload, "secret-2")
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestWebhookSetEndpoint:
    def test_set_webhook_url(self, client):
        _seed_creator()
        resp = client.post(
            "/creator/webhook",
            json={"url": "https://example.com/webhook"},
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["webhook_url"] == "https://example.com/webhook"
        assert data["creator_id"] == "test-creator-0001"

    def test_clear_webhook_url(self, client):
        _seed_creator(webhook_url="https://example.com/hook")
        resp = client.post(
            "/creator/webhook",
            json={"url": None},
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["webhook_url"] is None
        assert "cleared" in data["message"].lower()

    def test_set_webhook_requires_auth(self, client):
        resp = client.post(
            "/creator/webhook",
            json={"url": "https://example.com/webhook"},
        )
        assert resp.status_code == 401

    def test_set_webhook_invalid_url(self, client):
        _seed_creator()
        resp = client.post(
            "/creator/webhook",
            json={"url": "not-a-url"},
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 422

    def test_set_webhook_empty_string_clears(self, client):
        _seed_creator(webhook_url="https://example.com/hook")
        resp = client.post(
            "/creator/webhook",
            json={"url": ""},
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["webhook_url"] is None


class TestWebhookTestEndpoint:
    def test_test_webhook_no_url_configured(self, client):
        _seed_creator()
        resp = client.post(
            "/creator/webhook/test",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 400

    def test_test_webhook_requires_auth(self, client):
        resp = client.post("/creator/webhook/test")
        assert resp.status_code == 401

    @patch("httpx.AsyncClient")
    def test_test_webhook_success(self, mock_client_cls, client):
        _seed_creator(webhook_url="https://example.com/webhook")

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        resp = client.post(
            "/creator/webhook/test",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status_code"] == 200


# ---------------------------------------------------------------------------
# Delivery engine tests
# ---------------------------------------------------------------------------


class TestDeliverWebhook:
    def test_deliver_webhook_success(self):
        """Test successful webhook delivery doesn't retry."""
        with patch("tradearena.core.webhooks._deliver", new_callable=AsyncMock) as mock_deliver:
            mock_deliver.return_value = True
            asyncio.get_event_loop().run_until_complete(
                deliver_webhook("https://example.com/hook", "signal.resolved", {}, "secret")
            )
            assert mock_deliver.call_count == 1

    def test_deliver_webhook_retry_on_failure(self):
        """Test webhook retries once after failure."""
        with (
            patch("tradearena.core.webhooks._deliver", new_callable=AsyncMock) as mock_deliver,
            patch("tradearena.core.webhooks.RETRY_DELAY_SECONDS", 0),
        ):
            mock_deliver.side_effect = [False, True]
            asyncio.get_event_loop().run_until_complete(
                deliver_webhook("https://example.com/hook", "signal.resolved", {}, "secret")
            )
            assert mock_deliver.call_count == 2

    def test_deliver_webhook_max_two_attempts(self):
        """Test webhook gives up after one retry."""
        with (
            patch("tradearena.core.webhooks._deliver", new_callable=AsyncMock) as mock_deliver,
            patch("tradearena.core.webhooks.RETRY_DELAY_SECONDS", 0),
        ):
            mock_deliver.return_value = False
            asyncio.get_event_loop().run_until_complete(
                deliver_webhook("https://example.com/hook", "signal.resolved", {}, "secret")
            )
            assert mock_deliver.call_count == 2


# ---------------------------------------------------------------------------
# Database column test
# ---------------------------------------------------------------------------


class TestWebhookColumn:
    def test_webhook_url_stored_on_creator(self):
        _seed_creator(webhook_url="https://hooks.example.com/ta")
        db = TestingSessionLocal()
        try:
            creator = db.query(CreatorORM).filter(CreatorORM.id == "test-creator-0001").first()
            assert creator.webhook_url == "https://hooks.example.com/ta"
        finally:
            db.close()

    def test_webhook_url_nullable(self):
        _seed_creator()
        db = TestingSessionLocal()
        try:
            creator = db.query(CreatorORM).filter(CreatorORM.id == "test-creator-0001").first()
            assert creator.webhook_url is None
        finally:
            db.close()
