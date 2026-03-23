"""Tests for Twitter/X OAuth signup/login flow (OAuth 2.0 PKCE)."""

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
def _set_twitter_config():
    """Set Twitter OAuth config for all tests."""
    import tradearena.api.routes.auth as auth_mod

    old_id = auth_mod.TWITTER_CLIENT_ID
    old_secret = auth_mod.TWITTER_CLIENT_SECRET
    auth_mod.TWITTER_CLIENT_ID = "test-twitter-client-id"
    auth_mod.TWITTER_CLIENT_SECRET = "test-twitter-secret"
    yield
    auth_mod.TWITTER_CLIENT_ID = old_id
    auth_mod.TWITTER_CLIENT_SECRET = old_secret


# --- Mock helpers ---

MOCK_TW_USER = {
    "data": {
        "id": "987654321",
        "username": "traderbot",
        "name": "Trader Bot",
    }
}


def _make_resp(status_code, json_data):
    """Create a MagicMock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _twitter_mock_client(
    token_data=None,
    token_status=200,
    user_data=None,
    user_status=200,
):
    """Build a mock httpx.AsyncClient for Twitter token + user calls."""
    if token_data is None:
        token_data = {"access_token": "tw_test_token_123"}
    if user_data is None:
        user_data = MOCK_TW_USER

    token_resp = _make_resp(token_status, token_data)
    user_resp = _make_resp(user_status, user_data)

    # 1st context manager: token exchange (POST)
    client1 = AsyncMock()
    client1.post = AsyncMock(return_value=token_resp)
    client1.__aenter__ = AsyncMock(return_value=client1)
    client1.__aexit__ = AsyncMock(return_value=False)

    # 2nd context manager: user profile (GET)
    client2 = AsyncMock()
    client2.get = AsyncMock(return_value=user_resp)
    client2.__aenter__ = AsyncMock(return_value=client2)
    client2.__aexit__ = AsyncMock(return_value=False)

    call_count = {"n": 0}

    def _factory(*args, **kwargs):
        call_count["n"] += 1
        return client1 if call_count["n"] == 1 else client2

    return _factory


def _inject_pkce_state(state: str):
    """Inject a PKCE verifier into the in-memory store for testing."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod._pkce_store[state] = "test-verifier-12345"


# ---------------------------------------------------------------------------
# Tests: GET /auth/twitter (initiate flow)
# ---------------------------------------------------------------------------


def test_twitter_redirect_returns_authorization_url(client):
    """GET /auth/twitter should return a Twitter authorization URL with PKCE params."""
    resp = client.get("/auth/twitter")
    assert resp.status_code == 200
    data = resp.json()
    assert "authorization_url" in data
    url = data["authorization_url"]
    assert "twitter.com/i/oauth2/authorize" in url
    assert "client_id=test-twitter-client-id" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=" in url
    assert "state=" in url
    assert "scope=" in url


def test_twitter_redirect_503_when_not_configured(client):
    """GET /auth/twitter should 503 when Twitter OAuth is not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.TWITTER_CLIENT_ID = ""
    auth_mod.TWITTER_CLIENT_SECRET = ""
    resp = client.get("/auth/twitter")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: POST /auth/twitter/callback (complete flow)
# ---------------------------------------------------------------------------


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_creates_new_account(mock_client_cls, client):
    """Callback with new Twitter user should create a new account."""
    mock_client_cls.side_effect = _twitter_mock_client()
    _inject_pkce_state("test-state-1")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-1", "division": "crypto"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is True
    assert data["api_key"] is not None
    assert data["api_key"].startswith("ta-")
    assert data["token"]
    assert data["display_name"] == "Trader Bot"
    assert data["division"] == "crypto"
    assert data["level"] == 1
    assert data["xp"] == 0


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_login_existing_user(mock_client_cls, client):
    """Callback with existing twitter_id should login without creating new account."""
    # Pre-create a user with this twitter_id
    from datetime import UTC, datetime

    db = next(override_get_db())
    creator = CreatorORM(
        id="existing-user-01",
        display_name="Existing User",
        division="crypto",
        twitter_id="987654321",
        twitter_handle="traderbot",
        avatar_index=2,
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    mock_client_cls.side_effect = _twitter_mock_client()
    _inject_pkce_state("test-state-2")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-2"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is False
    assert data["api_key"] is None
    assert data["creator_id"] == "existing-user-01"
    assert data["display_name"] == "Existing User"
    assert data["avatar_index"] == 2


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_updates_handle_on_login(mock_client_cls, client):
    """If Twitter handle changed, it should be updated on login."""
    from datetime import UTC, datetime

    db = next(override_get_db())
    creator = CreatorORM(
        id="handle-user-01",
        display_name="Handle User",
        division="crypto",
        twitter_id="987654321",
        twitter_handle="old_handle",
        avatar_index=0,
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    db.close()

    mock_client_cls.side_effect = _twitter_mock_client()
    _inject_pkce_state("test-state-3")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-3"},
    )
    assert resp.status_code == 200

    # Verify handle was updated in DB
    db2 = next(override_get_db())
    updated = db2.query(CreatorORM).filter(CreatorORM.id == "handle-user-01").first()
    assert updated.twitter_handle == "traderbot"
    db2.close()


def test_twitter_callback_invalid_state(client):
    """Callback with invalid/expired state should return 400."""
    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "bogus-state"},
    )
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_token_exchange_failure(mock_client_cls, client):
    """Token exchange failure should return 400."""
    mock_client_cls.side_effect = _twitter_mock_client(token_status=401)
    _inject_pkce_state("test-state-4")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "bad_code", "state": "test-state-4"},
    )
    assert resp.status_code == 400
    assert "Failed to exchange" in resp.json()["detail"]


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_no_access_token(mock_client_cls, client):
    """Token response without access_token should return 400."""
    mock_client_cls.side_effect = _twitter_mock_client(
        token_data={"error": "invalid_grant", "error_description": "Code expired"}
    )
    _inject_pkce_state("test-state-5")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "expired_code", "state": "test-state-5"},
    )
    assert resp.status_code == 400
    assert "Code expired" in resp.json()["detail"]


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_user_profile_failure(mock_client_cls, client):
    """Failed user profile fetch should return 400."""
    mock_client_cls.side_effect = _twitter_mock_client(user_status=401)
    _inject_pkce_state("test-state-6")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-6"},
    )
    assert resp.status_code == 400
    assert "Failed to fetch" in resp.json()["detail"]


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_callback_short_display_name_uses_handle(mock_client_cls, client):
    """If Twitter name is too short, use username instead."""
    short_name_user = {"data": {"id": "111222333", "username": "longusername", "name": "AB"}}
    mock_client_cls.side_effect = _twitter_mock_client(user_data=short_name_user)
    _inject_pkce_state("test-state-7")

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-7"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new_account"] is True
    assert data["display_name"] == "longusername"


def test_twitter_callback_503_when_not_configured(client):
    """POST /auth/twitter/callback should 503 when not configured."""
    import tradearena.api.routes.auth as auth_mod

    auth_mod.TWITTER_CLIENT_ID = ""
    auth_mod.TWITTER_CLIENT_SECRET = ""

    resp = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "any"},
    )
    assert resp.status_code == 503


@patch("tradearena.api.routes.auth.httpx.AsyncClient")
def test_twitter_pkce_verifier_consumed_after_use(mock_client_cls, client):
    """PKCE state should be consumed (one-time use)."""
    mock_client_cls.side_effect = _twitter_mock_client()
    _inject_pkce_state("test-state-8")

    # First call succeeds
    resp1 = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-8"},
    )
    assert resp1.status_code == 200

    # Second call with same state should fail
    resp2 = client.post(
        "/auth/twitter/callback",
        json={"code": "tw_auth_code", "state": "test-state-8"},
    )
    assert resp2.status_code == 400
    assert "Invalid or expired" in resp2.json()["detail"]
