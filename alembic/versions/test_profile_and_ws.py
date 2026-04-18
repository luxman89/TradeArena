"""Tests for PATCH /auth/profile and WebSocket message queue."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, get_db

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


def _register_and_get_token(client: TestClient) -> tuple[str, str]:
    """Register a user via /auth/register and return (creator_id, token)."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "securepass123",
            "display_name": "Test Trader",
            "division": "crypto",
            "strategy_description": "Momentum strategy based on RSI and volume analysis.",
            "avatar_index": 0,
            "tos_hash": "79cf6fb69a652cf01c58210084de60e10da3790d23dfcdb1a2e804ec7339aa91",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["creator_id"], data["token"]


class TestProfileUpdate:
    def test_update_display_name(self, client):
        creator_id, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"display_name": "New Name Here"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "New Name Here"
        assert resp.json()["creator_id"] == creator_id

    def test_update_division(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"division": "polymarket"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["division"] == "polymarket"

    def test_update_strategy_description(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"strategy_description": "New long strategy description here for testing."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["strategy_description"] == (
            "New long strategy description here for testing."
        )

    def test_update_multiple_fields(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"display_name": "Updated Name", "division": "multi"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Updated Name"
        assert data["division"] == "multi"

    def test_invalid_division_rejected(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"division": "stocks"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_display_name_too_short_rejected(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"display_name": "AB"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_strategy_too_short_rejected(self, client):
        _, token = _register_and_get_token(client)
        resp = client.patch(
            "/auth/profile",
            json={"strategy_description": "Too short"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_rejected(self, client):
        resp = client.patch("/auth/profile", json={"display_name": "Hacker"})
        assert resp.status_code in (401, 403)

    def test_persists_after_update(self, client):
        _, token = _register_and_get_token(client)
        client.patch(
            "/auth/profile",
            json={"display_name": "Persisted Name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["display_name"] == "Persisted Name"


class TestWebSocketQueue:
    def test_broadcast_includes_seq(self, client):
        import asyncio

        from tradearena.api.ws import manager

        loop = asyncio.new_event_loop()
        loop.run_until_complete(manager.broadcast("test_event", {"key": "val"}))
        loop.close()
        assert manager.current_seq > 0

    def test_queue_bounded(self):
        import asyncio

        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        loop = asyncio.new_event_loop()
        for i in range(60):
            loop.run_until_complete(mgr.broadcast(f"evt_{i}"))
        loop.close()
        # Queue is capped at 50
        assert len(mgr._queue) == 50
        # Oldest should be evt_10 (0-9 evicted)
        assert mgr._queue[0]["event"] == "evt_10"


class TestWebSocketHeartbeat:
    def test_record_pong_updates_last_pong(self):
        import time

        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        # Simulate a fake websocket object
        fake_ws = object()
        mgr._connections.append(fake_ws)
        mgr._last_pong[fake_ws] = time.monotonic() - 100
        old_val = mgr._last_pong[fake_ws]
        mgr.record_pong(fake_ws)
        assert mgr._last_pong[fake_ws] > old_val

    def test_record_pong_ignores_unknown_ws(self):
        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        fake_ws = object()
        # Should not raise
        mgr.record_pong(fake_ws)
        assert fake_ws not in mgr._last_pong

    def test_disconnect_cleans_up_last_pong(self):
        import time

        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        fake_ws = object()
        mgr._connections.append(fake_ws)
        mgr._last_pong[fake_ws] = time.monotonic()
        mgr.disconnect(fake_ws)
        assert fake_ws not in mgr._connections
        assert fake_ws not in mgr._last_pong

    def test_ping_all_removes_stale_connections(self):
        import asyncio
        import time

        from tradearena.api.ws import PONG_TIMEOUT_SECONDS, ConnectionManager

        mgr = ConnectionManager()
        fake_ws = object()
        mgr._connections.append(fake_ws)
        # Set last_pong far in the past to trigger stale cleanup
        mgr._last_pong[fake_ws] = time.monotonic() - PONG_TIMEOUT_SECONDS - 10

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr.ping_all())
        loop.close()

        assert fake_ws not in mgr._connections
        assert fake_ws not in mgr._last_pong

    def test_ping_all_keeps_fresh_connections(self):
        import asyncio
        import json
        import time
        from unittest.mock import AsyncMock

        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        mgr._connections.append(mock_ws)
        mgr._last_pong[mock_ws] = time.monotonic()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(mgr.ping_all())
        loop.close()

        assert mock_ws in mgr._connections
        # Verify ping was sent
        mock_ws.send_text.assert_called_once()
        sent = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent["event"] == "ping"
        assert "ts" in sent

    def test_connect_initializes_last_pong(self):
        import asyncio
        import time
        from unittest.mock import AsyncMock

        from tradearena.api.ws import ConnectionManager

        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        mock_ws.query_params = {}

        loop = asyncio.new_event_loop()
        before = time.monotonic()
        loop.run_until_complete(mgr.connect(mock_ws))
        after = time.monotonic()
        loop.close()

        assert mock_ws in mgr._last_pong
        assert before <= mgr._last_pong[mock_ws] <= after
