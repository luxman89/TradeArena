"""Tests for signup hardening: ToS consent, email verification, hCaptcha, per-IP cap."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, get_db

# ---------------------------------------------------------------------------
# Test DB setup
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


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app, raise_server_exceptions=True)

_VALID_BODY = {
    "email": "test@example.com",
    "password": "securepass123",
    "display_name": "Test Trader",
    "division": "crypto",
    "strategy_description": "A well-defined trading strategy with momentum signals",
    "avatar_index": 0,
    "hcaptcha_token": "",
    "tos_hash": "79cf6fb69a652cf01c58210084de60e10da3790d23dfcdb1a2e804ec7339aa91",
}


def _reset_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Clear in-memory rate limit state so tests don't bleed into each other
    from tradearena.api import rate_limit

    rate_limit._signup_hits.clear()


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


class TestEmailVerification:
    def setup_method(self):
        _reset_db()

    def test_register_sets_verify_token(self):
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            resp = client.post("/auth/register", json=_VALID_BODY)
        assert resp.status_code == 201
        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        assert creator.email_verify_token is not None
        assert creator.email_verified_at is None
        db.close()

    def test_verify_email_happy_path(self):
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            client.post("/auth/register", json=_VALID_BODY)
        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        token = creator.email_verify_token
        db.close()

        resp = client.get(f"/auth/verify-email?token={token}")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Email verified successfully"

        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        assert creator.email_verified_at is not None
        assert creator.email_verify_token is None
        db.close()

    def test_verify_email_invalid_token(self):
        resp = client.get("/auth/verify-email?token=badtoken")
        assert resp.status_code == 400

    def test_verify_email_idempotent(self):
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            client.post("/auth/register", json=_VALID_BODY)
        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        token = creator.email_verify_token
        db.close()

        client.get(f"/auth/verify-email?token={token}")
        # Already verified — token is gone, so invalid now
        resp = client.get(f"/auth/verify-email?token={token}")
        assert resp.status_code == 400

    def test_unverified_user_cannot_submit_signal(self):
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            reg = client.post("/auth/register", json=_VALID_BODY)
        assert reg.status_code == 201
        api_key = reg.json()["api_key"]

        signal_payload = {
            "asset": "BTCUSDT",
            "action": "buy",
            "confidence": 0.8,
            "reasoning": (
                "Strong momentum breakout with volume confirmation and trend alignment "
                "showing RSI at sixty two bullish crossover on the daily chart timeframe"
            ),
            "supporting_data": {"rsi": 65, "macd": "bullish"},
        }
        resp = client.post(
            "/signal",
            json=signal_payload,
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 403
        assert "not verified" in resp.json()["detail"].lower()

    def test_verified_user_can_submit_signal(self):
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            reg = client.post("/auth/register", json=_VALID_BODY)
        api_key = reg.json()["api_key"]

        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        token = creator.email_verify_token
        db.close()

        client.get(f"/auth/verify-email?token={token}")

        signal_payload = {
            "asset": "BTCUSDT",
            "action": "buy",
            "confidence": 0.8,
            "reasoning": (
                "Strong momentum breakout with volume confirmation and trend alignment "
                "showing RSI at sixty two bullish crossover on the daily chart timeframe"
            ),
            "supporting_data": {"rsi": 65, "macd": "bullish"},
        }
        resp = client.post(
            "/signal",
            json=signal_payload,
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201

    def test_oauth_user_auto_verified_can_submit(self):
        """Bots and OAuth users (no password_hash) are not gated by email verification."""
        _reset_db()
        import hashlib

        db = TestingSessionLocal()
        now = datetime.now(UTC)
        api_key = f"ta-{secrets.token_hex(16)}"
        creator = CreatorORM(
            id="bot-tester-aaaa",
            display_name="Bot Tester",
            division="crypto",
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
            created_at=now,
            email_verified_at=None,
            password_hash=None,
        )
        db.add(creator)
        db.commit()
        db.close()

        signal_payload = {
            "asset": "ETHUSDT",
            "action": "buy",
            "confidence": 0.75,
            "reasoning": (
                "Technical analysis showing strong support levels with significant volume "
                "and momentum bullish crossover on multiple distinct timeframes daily and weekly"
            ),
            "supporting_data": {"rsi": 55, "support": 3000},
        }
        resp = client.post(
            "/signal",
            json=signal_payload,
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# hCaptcha
# ---------------------------------------------------------------------------


class TestHCaptcha:
    def setup_method(self):
        _reset_db()

    def test_hcaptcha_bypass_when_secret_unset(self):
        """No HCAPTCHA_SECRET → registration succeeds even with empty token."""
        with (
            patch("tradearena.api.routes.auth.HCAPTCHA_SECRET", ""),
            patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock),
        ):
            resp = client.post("/auth/register", json={**_VALID_BODY, "hcaptcha_token": ""})
        assert resp.status_code == 201

    def test_hcaptcha_empty_token_rejected_when_secret_set(self):
        with patch("tradearena.api.routes.auth.HCAPTCHA_SECRET", "real-secret"):
            resp = client.post("/auth/register", json={**_VALID_BODY, "hcaptcha_token": ""})
        assert resp.status_code == 422

    def test_hcaptcha_invalid_token_rejected(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": False}

        with (
            patch("tradearena.api.routes.auth.HCAPTCHA_SECRET", "real-secret"),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = client.post(
                "/auth/register",
                json={**_VALID_BODY, "hcaptcha_token": "bad-token"},
            )
        assert resp.status_code == 422

    def test_hcaptcha_valid_token_passes(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}

        with (
            patch("tradearena.api.routes.auth.HCAPTCHA_SECRET", "real-secret"),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = client.post(
                "/auth/register",
                json={**_VALID_BODY, "hcaptcha_token": "valid-token"},
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Per-IP registration cap
# ---------------------------------------------------------------------------


class TestPerIpCap:
    def setup_method(self):
        _reset_db()

    def test_per_ip_cap_blocks_after_limit(self):
        """After SIGNUP_IP_RATE registrations, subsequent ones from same IP get 429."""
        from tradearena.api import rate_limit

        # Patch SIGNUP_IP_RATE to a low value for the test
        original_rate = rate_limit.SIGNUP_IP_RATE
        rate_limit.SIGNUP_IP_RATE = 2
        # Clear state
        rate_limit._signup_hits.clear()

        try:
            with patch(
                "tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock
            ):
                for i in range(2):
                    body = {**_VALID_BODY, "email": f"user{i}@example.com"}
                    resp = client.post("/auth/register", json=body)
                    assert resp.status_code == 201, f"Expected 201 on attempt {i}"

                # 3rd attempt should be blocked
                resp = client.post(
                    "/auth/register", json={**_VALID_BODY, "email": "overflow@example.com"}
                )
                assert resp.status_code == 429
        finally:
            rate_limit.SIGNUP_IP_RATE = original_rate
            rate_limit._signup_hits.clear()


# ---------------------------------------------------------------------------
# ToS consent
# ---------------------------------------------------------------------------

CURRENT_TOS_HASH = "79cf6fb69a652cf01c58210084de60e10da3790d23dfcdb1a2e804ec7339aa91"


class TestTosConsent:
    def setup_method(self):
        _reset_db()

    def test_no_tos_hash_rejected(self):
        """Empty tos_hash must be rejected with 422."""
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            resp = client.post("/auth/register", json={**_VALID_BODY, "tos_hash": ""})
        assert resp.status_code == 422
        assert "Terms of Service" in resp.json()["detail"]

    def test_outdated_tos_hash_rejected(self):
        """A hash that doesn't match the current ToS must be rejected."""
        stale_hash = "a" * 64
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            resp = client.post("/auth/register", json={**_VALID_BODY, "tos_hash": stale_hash})
        assert resp.status_code == 422
        assert "Terms of Service" in resp.json()["detail"]

    def test_correct_tos_hash_accepted(self):
        """Correct ToS hash allows registration and is persisted."""
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            resp = client.post("/auth/register", json=_VALID_BODY)
        assert resp.status_code == 201

        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        assert creator.tos_hash == CURRENT_TOS_HASH
        assert creator.tos_accepted_at is not None
        db.close()

    def test_tos_hash_persisted_matches_accepted_version(self):
        """DB row proves exactly which ToS version was accepted."""
        with patch("tradearena.api.routes.auth._send_verification_email", new_callable=AsyncMock):
            client.post("/auth/register", json=_VALID_BODY)

        db = TestingSessionLocal()
        creator = db.query(CreatorORM).filter(CreatorORM.email == "test@example.com").first()
        assert creator.tos_hash == CURRENT_TOS_HASH
        assert creator.tos_accepted_at is not None
        db.close()
