"""Tests for Google OAuth signup/login flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, get_db

# --- In-memory SQLite DB for tests ---

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
    """Drop and recreate all tables before each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def client():
    """TestClient that clears rate limiter state to avoid 429s between tests."""
    from tradearena.api.rate_limit import RateLimitMiddleware

    obj = app.middleware_stack
    while obj is not None:
        if isinstance(obj, RateLimitMiddleware):
            obj._auth_hits.clear()
            break
        obj = getattr(obj, "app", None)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _set_google_config():
    """Set Google OAuth config for all tests by default."""
    import tradearena.api.routes.auth as auth_mod

    old_id = auth_mod.GOOGLE_CLIENT_ID
    old_secret = auth_mod.GOOGLE_CLIENT_SECRET
    auth_mod.GOOGLE_CLIENT_ID = "test-google-client-id"
    auth_mod.GOOGLE_CLIENT_SECRET = "test-google-secret"
    yield
    auth_mod.GOOGLE_CLIENT_ID = old_id
    auth_mod.GOOGLE_CLIENT_SECRET = old_secret


# --- Mock helpers ---

MOCK_GOOGLE_USER = {
    "id": "112233445566778899",
    "email": "alice@gmail.com",
    "verified_email": True,
    "name": "Alice Trader",
    "given_name": "Alice",
    "family_name": "Trader",
    "picture": "https://lh3.googleusercontent.com/photo.jpg",
}


def _make_resp(status_code, json_data):
    """Create a MagicMock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _google_mock_client(
    token_data=None,
    token_status=200,
    user_data=None,
    user_status=200,
):
    """Build a mock httpx.AsyncClient that handles Google token + userinfo calls."""
    if token_data is None:
        token_data = {"access_token": "ya29.test_token_123"}
    if user_data is None:
        user_data = MOCK_GOOGLE_USER

    token_resp = _make_resp(token_status, token_data)
    user_resp = _make_resp(user_status, user_data)

    # Google OAuth creates two AsyncClient context managers:
    # 1st: client.post (token exchange)
    # 2nd: client.get (userinfo)
    client1 = AsyncMock()
    client1.post = AsyncMock(return_value=token_resp)
    client1.__aenter__ = AsyncMock(return_value=client1)
    client1.__aexit__ = AsyncMock(return_value=False)

    client2 = AsyncMock()
    client2.get = AsyncMock(return_value=user_resp)
    client2.__aenter__ = AsyncMock(return_value=client2)
    client2.__aexit__ = AsyncMock(return_value=False)

    call_count = {"n": 0}

    def _factory(*args, **kwargs):
        call_count["n"] += 1
        return client1 if call_count["n"] == 1 else client2

    return _factory


# ---------------------------------------------------------------------------
# Tests: GET /auth/google (initiate flow)
# ---------------------------------------------------------------------------


def test_google_redirect_returns_authorization_url(client):
    """GET /auth/google should return a Google authorization URL."""
    resp = client.get("/auth/google")
    assert resp.status_code == 200
    data = resp.json()
    assert "authorization_url" in data
    assert "accounts.google.com/o/oauth2/v2/auth" in data["authorization_url"]
    assert "client_id=test-google-client-id" in data["authorization_url"]
    assert "scope=openid" in data["authorization_url"]


def test_google_redirect_503_when_not_configured(client):
    """GET /auth/google returns 503 when Google OAuth is not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.GOOGLE_CLIENT_ID = ""
    auth_mod.GOOGLE_CLIENT_SECRET = ""

    resp = client.get("/auth/google")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: POST /auth/google/callback (new account creation)
# ---------------------------------------------------------------------------


def test_google_callback_creates_new_account(client):
    """First-time Google login should create a new account with API key."""
    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is True
    assert data["api_key"] is not None
    assert data["api_key"].startswith("ta-")
    assert data["token"] is not None
    assert data["level"] == 1
    assert data["xp"] == 0
    assert data["division"] == "crypto"
    assert len(data["creator_id"]) > 0


def test_google_callback_custom_division(client):
    """Google signup should respect the division parameter."""
    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post(
            "/auth/google/callback",
            json={"code": "test-code", "division": "polymarket"},
        )

    assert resp.status_code == 200
    assert resp.json()["division"] == "polymarket"


def test_google_callback_stores_google_id(client):
    """New account should have google_id stored."""
    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    creator_id = resp.json()["creator_id"]
    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    assert creator.google_id == "112233445566778899"
    assert creator.email == "alice@gmail.com"
    db.close()


def test_google_callback_generates_api_key_hash(client):
    """New account should have api_key_hash set (not plaintext)."""
    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    data = resp.json()
    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.id == data["creator_id"]).first()
    assert creator.api_key_hash is not None
    assert len(creator.api_key_hash) == 64  # SHA-256 hex
    assert creator.api_key_dev is None
    db.close()


# ---------------------------------------------------------------------------
# Tests: POST /auth/google/callback (existing account login)
# ---------------------------------------------------------------------------


def test_google_callback_login_existing_google_account(client):
    """Returning Google user should login without creating new account."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    creator = CreatorORM(
        id="alice-trader-ab12",
        display_name="Alice Trader",
        division="crypto",
        google_id="112233445566778899",
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is False
    assert data["api_key"] is None
    assert data["creator_id"] == "alice-trader-ab12"
    assert data["token"] is not None


# ---------------------------------------------------------------------------
# Tests: POST /auth/google/callback (email-based account linking)
# ---------------------------------------------------------------------------


def test_google_callback_links_existing_email_account(client):
    """Google login should link to existing account if email matches."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    creator = CreatorORM(
        id="existing-user-cd34",
        display_name="Existing User",
        division="multi",
        email="alice@gmail.com",
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    factory = _google_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is False
    assert data["creator_id"] == "existing-user-cd34"

    # Verify google_id was linked
    db = TestingSessionLocal()
    linked = db.query(CreatorORM).filter(CreatorORM.id == "existing-user-cd34").first()
    assert linked.google_id == "112233445566778899"
    db.close()


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


def test_google_callback_bad_code(client):
    """Invalid OAuth code should return 400."""
    factory = _google_mock_client(
        token_data={"error": "invalid_grant", "error_description": "Bad code"},
    )
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "invalid-code"})

    assert resp.status_code == 400
    assert "Bad code" in resp.json()["detail"]


def test_google_callback_token_exchange_failure(client):
    """Failed token exchange (non-200) should return 400."""
    factory = _google_mock_client(token_status=500, token_data={"error": "server_error"})
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 400
    assert "exchange" in resp.json()["detail"].lower()


def test_google_callback_user_fetch_failure(client):
    """Failed user profile fetch should return 400."""
    factory = _google_mock_client(user_status=401, user_data={"error": "invalid_token"})
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 400
    assert "profile" in resp.json()["detail"].lower()


def test_google_callback_503_when_not_configured(client):
    """POST /auth/google/callback returns 503 when not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.GOOGLE_CLIENT_ID = ""
    auth_mod.GOOGLE_CLIENT_SECRET = ""

    resp = client.post("/auth/google/callback", json={"code": "test-code"})
    assert resp.status_code == 503


def test_google_callback_invalid_division(client):
    """Invalid division should return 422."""
    resp = client.post(
        "/auth/google/callback",
        json={"code": "test-code", "division": "invalid"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


def test_google_callback_no_email(client):
    """When Google user has no email, should create account without email."""
    user_no_email = {**MOCK_GOOGLE_USER, "email": None}
    factory = _google_mock_client(user_data=user_no_email)
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is True

    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.google_id == "112233445566778899").first()
    assert creator.email is None
    db.close()


def test_google_callback_short_display_name_fallback(client):
    """Short Google name should fall back to generated name."""
    user_short_name = {**MOCK_GOOGLE_USER, "name": "Ab"}
    factory = _google_mock_client(user_data=user_short_name)
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    assert len(resp.json()["display_name"]) >= 3


def test_google_callback_missing_user_id(client):
    """Missing Google user ID should return 400."""
    user_no_id = {**MOCK_GOOGLE_USER, "id": ""}
    factory = _google_mock_client(user_data=user_no_id)
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/google/callback", json={"code": "test-code"})

    assert resp.status_code == 400
    assert "missing" in resp.json()["detail"].lower()


def test_existing_email_password_registration_still_works(client):
    """Email/password registration still functions after Google OAuth additions."""
    reg_resp = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "securepass123",
            "display_name": "Test User",
            "division": "crypto",
            "strategy_description": "Testing that legacy auth still works correctly",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert "token" in data
    assert "api_key" in data
    assert data["api_key"].startswith("ta-")
