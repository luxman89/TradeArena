"""Tests for battle API endpoints: create, get, list active, history, force-resolve."""

from __future__ import annotations

import uuid

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


def _seed_creator(creator_id: str) -> None:
    """Insert a creator directly into the test DB."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    db.add(
        CreatorORM(
            id=creator_id,
            display_name=creator_id.title(),
            division="crypto",
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


def _seed_signals(creator_id: str, count: int = 5, outcome: str = "WIN") -> None:
    """Insert resolved signals for a creator."""
    from datetime import UTC, datetime, timedelta

    db = TestingSessionLocal()
    reasoning = (
        "This is a detailed technical analysis signal with RSI divergence and "
        "volume confirmation across multiple timeframes showing clear momentum "
        "shift above the key resistance breakout level."
    )
    for i in range(count):
        db.add(
            SignalORM(
                signal_id=uuid.uuid4().hex,
                creator_id=creator_id,
                asset="BTC/USDT",
                action="BUY",
                confidence=0.7,
                reasoning=reasoning,
                supporting_data={"rsi": 55, "volume": 1000000},
                commitment_hash=uuid.uuid4().hex + uuid.uuid4().hex[:32],
                committed_at=datetime.now(UTC) - timedelta(days=i + 1),
                outcome=outcome,
                outcome_price=50000.0,
                outcome_at=datetime.now(UTC) - timedelta(days=i),
            )
        )
    db.commit()
    db.close()


class TestCreateBattle:
    def test_create_returns_201(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob", "window_days": 7},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["creator1_id"] == "alice"
        assert data["creator2_id"] == "bob"
        assert data["status"] == "ACTIVE"
        assert data["window_days"] == 7
        assert data["battle_type"] == "MANUAL"
        assert data["battle_id"]
        assert data["created_at"]

    def test_create_default_window(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        assert resp.status_code == 201
        assert resp.json()["window_days"] == 7

    def test_cannot_battle_yourself(self, client):
        _seed_creator("alice")
        resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "alice"},
        )
        assert resp.status_code == 422
        assert "yourself" in resp.json()["detail"].lower()

    def test_creator_not_found(self, client):
        _seed_creator("alice")
        resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "ghost"},
        )
        assert resp.status_code == 404
        assert "ghost" in resp.json()["detail"]

    def test_duplicate_active_battle_rejected(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        resp1 = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        assert resp2.status_code == 409

    def test_duplicate_reversed_order_also_rejected(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        resp = client.post(
            "/battle/create",
            json={"creator1_id": "bob", "creator2_id": "alice"},
        )
        assert resp.status_code == 409


class TestGetBattle:
    def test_get_existing_battle(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        create_resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        battle_id = create_resp.json()["battle_id"]

        resp = client.get(f"/battle/{battle_id}")
        assert resp.status_code == 200
        assert resp.json()["battle_id"] == battle_id
        assert resp.json()["status"] == "ACTIVE"

    def test_get_nonexistent_battle(self, client):
        resp = client.get("/battle/nonexistent")
        assert resp.status_code == 404


class TestListActiveBattles:
    def test_empty_list(self, client):
        resp = client.get("/battles/active")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["battles"] == []

    def test_lists_active_only(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_creator("charlie")

        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "charlie"},
        )

        resp = client.get("/battles/active")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2


class TestBattleHistory:
    def test_empty_history(self, client):
        resp = client.get("/battles/history")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_returns_all_battles(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )

        resp = client.get("/battles/history")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_filter_by_creator(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_creator("charlie")
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        client.post(
            "/battle/create",
            json={"creator1_id": "bob", "creator2_id": "charlie"},
        )

        resp = client.get("/battles/history?creator_id=alice")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/battles/history?creator_id=bob")
        assert resp.json()["total"] == 2

    def test_filter_by_status(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )

        resp = client.get("/battles/history?status=ACTIVE")
        assert resp.json()["total"] == 1

        resp = client.get("/battles/history?status=RESOLVED")
        assert resp.json()["total"] == 0

    def test_pagination(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_creator("c1")
        _seed_creator("c2")
        _seed_creator("c3")
        client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        client.post(
            "/battle/create",
            json={"creator1_id": "c1", "creator2_id": "c2"},
        )
        client.post(
            "/battle/create",
            json={"creator1_id": "c2", "creator2_id": "c3"},
        )

        resp = client.get("/battles/history?limit=2&offset=0")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["battles"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

        resp2 = client.get("/battles/history?limit=2&offset=2")
        assert len(resp2.json()["battles"]) == 1


class TestForceResolveBattle:
    def test_resolve_with_signals(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_signals("alice", count=5, outcome="WIN")
        _seed_signals("bob", count=5, outcome="LOSS")

        create_resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        battle_id = create_resp.json()["battle_id"]

        resp = client.post(f"/battle/{battle_id}/resolve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESOLVED"
        assert data["winner_id"] == "alice"
        assert data["creator1_score"] is not None
        assert data["creator2_score"] is not None
        assert data["creator1_details"] is not None
        assert data["creator2_details"] is not None
        assert data["margin"] is not None
        assert data["resolved_at"] is not None

    def test_resolve_nonexistent_battle(self, client):
        resp = client.post("/battle/nonexistent/resolve")
        assert resp.status_code == 404

    def test_resolve_already_resolved(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_signals("alice", count=5, outcome="WIN")
        _seed_signals("bob", count=5, outcome="LOSS")

        create_resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        battle_id = create_resp.json()["battle_id"]

        client.post(f"/battle/{battle_id}/resolve")
        resp = client.post(f"/battle/{battle_id}/resolve")
        assert resp.status_code == 409

    def test_resolve_insufficient_signals(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_signals("alice", count=3, outcome="WIN")
        # Bob has no signals

        create_resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        battle_id = create_resp.json()["battle_id"]

        resp = client.post(f"/battle/{battle_id}/resolve")
        assert resp.status_code == 422

    def test_resolved_battle_not_in_active_list(self, client):
        _seed_creator("alice")
        _seed_creator("bob")
        _seed_signals("alice", count=5, outcome="WIN")
        _seed_signals("bob", count=5, outcome="LOSS")

        create_resp = client.post(
            "/battle/create",
            json={"creator1_id": "alice", "creator2_id": "bob"},
        )
        battle_id = create_resp.json()["battle_id"]

        # Before resolve: in active list
        resp = client.get("/battles/active")
        assert resp.json()["total"] == 1

        client.post(f"/battle/{battle_id}/resolve")

        # After resolve: not in active list
        resp = client.get("/battles/active")
        assert resp.json()["total"] == 0
