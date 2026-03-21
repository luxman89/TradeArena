"""Tests for GitHub OAuth signup/login flow."""

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
def _set_github_config():
    """Set GitHub OAuth config for all tests by default."""
    import tradearena.api.routes.auth as auth_mod

    old_id = auth_mod.GITHUB_CLIENT_ID
    old_secret = auth_mod.GITHUB_CLIENT_SECRET
    auth_mod.GITHUB_CLIENT_ID = "test-client-id"
    auth_mod.GITHUB_CLIENT_SECRET = "test-secret"
    yield
    auth_mod.GITHUB_CLIENT_ID = old_id
    auth_mod.GITHUB_CLIENT_SECRET = old_secret


# --- Mock helpers ---

MOCK_GH_USER = {
    "id": 12345678,
    "login": "octocat",
    "name": "Octo Cat",
    "email": "octocat@github.com",
}

MOCK_GH_EMAILS = [
    {"email": "octocat@github.com", "primary": True, "verified": True},
    {"email": "octocat-alt@example.com", "primary": False, "verified": True},
]


def _make_resp(status_code, json_data):
    """Create a MagicMock httpx response (json/status_code are synchronous)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _github_mock_client(
    token_data=None,
    token_status=200,
    user_data=None,
    user_status=200,
    emails_data=None,
    emails_status=200,
):
    """Build a mock httpx.AsyncClient that handles GitHub token + user + emails calls."""
    if token_data is None:
        token_data = {"access_token": "gho_test_token_123"}
    if user_data is None:
        user_data = MOCK_GH_USER
    if emails_data is None:
        emails_data = MOCK_GH_EMAILS

    token_resp = _make_resp(token_status, token_data)
    user_resp = _make_resp(user_status, user_data)
    emails_resp = _make_resp(emails_status, emails_data)

    # The auth code creates two AsyncClient context managers:
    # 1st: client.post (token exchange)
    # 2nd: client.get (user + emails)
    client1 = AsyncMock()
    client1.post = AsyncMock(return_value=token_resp)
    client1.__aenter__ = AsyncMock(return_value=client1)
    client1.__aexit__ = AsyncMock(return_value=False)

    client2 = AsyncMock()

    async def _get_side_effect(url, **kwargs):
        if "/user/emails" in url:
            return emails_resp
        return user_resp

    client2.get = AsyncMock(side_effect=_get_side_effect)
    client2.__aenter__ = AsyncMock(return_value=client2)
    client2.__aexit__ = AsyncMock(return_value=False)

    call_count = {"n": 0}

    def _factory(*args, **kwargs):
        call_count["n"] += 1
        return client1 if call_count["n"] == 1 else client2

    return _factory


# ---------------------------------------------------------------------------
# Tests: GET /auth/github (initiate flow)
# ---------------------------------------------------------------------------


def test_github_redirect_returns_authorization_url(client):
    """GET /auth/github should return a GitHub authorization URL."""
    resp = client.get("/auth/github")
    assert resp.status_code == 200
    data = resp.json()
    assert "authorization_url" in data
    assert "github.com/login/oauth/authorize" in data["authorization_url"]
    assert "client_id=test-client-id" in data["authorization_url"]
    assert "scope=read%3Auser" in data["authorization_url"]
    assert "user%3Aemail" in data["authorization_url"]


def test_github_redirect_503_when_not_configured(client):
    """GET /auth/github returns 503 when GitHub OAuth is not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.GITHUB_CLIENT_ID = ""
    auth_mod.GITHUB_CLIENT_SECRET = ""

    resp = client.get("/auth/github")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: POST /auth/github/callback (new account creation)
# ---------------------------------------------------------------------------


def test_github_callback_creates_new_account(client):
    """First-time GitHub login should create a new account with API key."""
    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

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


def test_github_callback_custom_division(client):
    """GitHub signup should respect the division parameter."""
    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post(
            "/auth/github/callback",
            json={"code": "test-code", "division": "polymarket"},
        )

    assert resp.status_code == 200
    assert resp.json()["division"] == "polymarket"


def test_github_callback_stores_github_id_and_username(client):
    """New account should have github_id and github_username stored."""
    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    creator_id = resp.json()["creator_id"]
    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    assert creator.github_id == "12345678"
    assert creator.github_username == "octocat"
    assert creator.email == "octocat@github.com"
    db.close()


def test_github_callback_generates_api_key_hash(client):
    """New account should have api_key_hash set (not plaintext)."""
    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    data = resp.json()
    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.id == data["creator_id"]).first()
    assert creator.api_key_hash is not None
    assert len(creator.api_key_hash) == 64  # SHA-256 hex
    assert creator.api_key_dev is None  # Not stored in plaintext
    db.close()


# ---------------------------------------------------------------------------
# Tests: POST /auth/github/callback (existing account login)
# ---------------------------------------------------------------------------


def test_github_callback_login_existing_github_account(client):
    """Returning GitHub user should login without creating new account."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    creator = CreatorORM(
        id="octo-cat-ab12",
        display_name="Octo Cat",
        division="crypto",
        github_id="12345678",
        github_username="octocat",
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is False
    assert data["api_key"] is None
    assert data["creator_id"] == "octo-cat-ab12"
    assert data["token"] is not None


# ---------------------------------------------------------------------------
# Tests: POST /auth/github/callback (email-based account linking)
# ---------------------------------------------------------------------------


def test_github_callback_links_existing_email_account(client):
    """GitHub login should link to existing account if email matches."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    creator = CreatorORM(
        id="existing-user-cd34",
        display_name="Existing User",
        division="multi",
        email="octocat@github.com",
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is False
    assert data["creator_id"] == "existing-user-cd34"

    # Verify github_id was linked
    db = TestingSessionLocal()
    linked = db.query(CreatorORM).filter(CreatorORM.id == "existing-user-cd34").first()
    assert linked.github_id == "12345678"
    assert linked.github_username == "octocat"
    db.close()


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


def test_github_callback_bad_code(client):
    """Invalid OAuth code should return 400."""
    factory = _github_mock_client(
        token_data={"error": "bad_verification_code", "error_description": "Bad code"},
    )
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "invalid-code"})

    assert resp.status_code == 400
    assert "Bad code" in resp.json()["detail"]


def test_github_callback_token_exchange_failure(client):
    """Failed token exchange (non-200) should return 400."""
    factory = _github_mock_client(token_status=500, token_data={"error": "server_error"})
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 400
    assert "exchange" in resp.json()["detail"].lower()


def test_github_callback_user_fetch_failure(client):
    """Failed user profile fetch should return 400."""
    factory = _github_mock_client(user_status=401, user_data={"message": "Unauthorized"})
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 400
    assert "profile" in resp.json()["detail"].lower()


def test_github_callback_503_when_not_configured(client):
    """POST /auth/github/callback returns 503 when not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.GITHUB_CLIENT_ID = ""
    auth_mod.GITHUB_CLIENT_SECRET = ""

    resp = client.post("/auth/github/callback", json={"code": "test-code"})
    assert resp.status_code == 503


def test_github_callback_invalid_division(client):
    """Invalid division should return 422."""
    resp = client.post(
        "/auth/github/callback",
        json={"code": "test-code", "division": "invalid"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


def test_github_callback_no_public_email_uses_emails_api(client):
    """When GitHub user has no public email, should use /user/emails API."""
    user_no_email = {**MOCK_GH_USER, "email": None}
    factory = _github_mock_client(user_data=user_no_email)
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is True

    db = TestingSessionLocal()
    creator = db.query(CreatorORM).filter(CreatorORM.github_id == "12345678").first()
    assert creator.email == "octocat@github.com"
    db.close()


def test_github_callback_short_display_name_fallback(client):
    """Short GitHub name should fall back to username."""
    user_short_name = {**MOCK_GH_USER, "name": "Ab"}
    factory = _github_mock_client(user_data=user_short_name)
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 200
    assert len(resp.json()["display_name"]) >= 3


def test_github_callback_updates_username_on_login(client):
    """Re-login should update github_username if it changed."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    creator = CreatorORM(
        id="octo-cat-ab12",
        display_name="Octo Cat",
        division="crypto",
        github_id="12345678",
        github_username="old-username",
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    factory = _github_mock_client()
    with patch("tradearena.api.routes.auth.httpx.AsyncClient", side_effect=factory):
        resp = client.post("/auth/github/callback", json={"code": "test-code"})

    assert resp.status_code == 200

    db = TestingSessionLocal()
    updated = db.query(CreatorORM).filter(CreatorORM.id == "octo-cat-ab12").first()
    assert updated.github_username == "octocat"
    db.close()


def test_existing_email_password_registration_still_works(client):
    """Email/password registration still functions after OAuth additions."""
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
