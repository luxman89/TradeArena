"""Tests for tournament system: create, join, get, advance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, CreatorScoreORM, get_db

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


def _seed_creator(creator_id: str, score: float = 0.5):
    """Insert a creator and score directly into the test DB."""
    from datetime import UTC, datetime

    db = TestingSessionLocal()
    db.add(
        CreatorORM(
            id=creator_id,
            display_name=creator_id,
            division="crypto",
            created_at=datetime.now(UTC),
        )
    )
    db.add(
        CreatorScoreORM(
            creator_id=creator_id,
            composite_score=score,
            win_rate=score,
            risk_adjusted_return=score,
            consistency=score,
            confidence_calibration=score,
            total_signals=10,
            updated_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


class TestCreateTournament:
    def test_create_returns_201(self, client):
        resp = client.post("/tournament", json={"name": "Weekly Cup"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Weekly Cup"
        assert data["status"] == "registering"
        assert data["format"] == "single_elimination"
        assert data["max_participants"] == 8

    def test_create_round_robin(self, client):
        resp = client.post(
            "/tournament",
            json={"name": "RR League", "format": "round_robin", "max_participants": 4},
        )
        assert resp.status_code == 201
        assert resp.json()["format"] == "round_robin"

    def test_create_invalid_format(self, client):
        resp = client.post("/tournament", json={"name": "Bad", "format": "invalid"})
        assert resp.status_code == 422


class TestJoinTournament:
    def test_join_success(self, client):
        _seed_creator("alice-a1b2")
        t = client.post("/tournament", json={"name": "Cup"}).json()
        resp = client.post(
            f"/tournament/{t['id']}/join",
            json={"creator_id": "alice-a1b2"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 1
        assert resp.json()["entries"][0]["seed"] == 1

    def test_join_duplicate_rejected(self, client):
        _seed_creator("alice-a1b2")
        t = client.post("/tournament", json={"name": "Cup"}).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "alice-a1b2"})
        resp = client.post(
            f"/tournament/{t['id']}/join",
            json={"creator_id": "alice-a1b2"},
        )
        assert resp.status_code == 409

    def test_join_full_tournament_rejected(self, client):
        _seed_creator("c1")
        _seed_creator("c2")
        _seed_creator("c3")
        t = client.post(
            "/tournament",
            json={"name": "Tiny", "max_participants": 2},
        ).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "c1"})
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "c2"})
        resp = client.post(
            f"/tournament/{t['id']}/join",
            json={"creator_id": "c3"},
        )
        assert resp.status_code == 409
        assert "full" in resp.json()["detail"]

    def test_join_nonexistent_tournament(self, client):
        _seed_creator("alice-a1b2")
        resp = client.post(
            "/tournament/nonexistent/join",
            json={"creator_id": "alice-a1b2"},
        )
        assert resp.status_code == 404

    def test_join_nonexistent_creator(self, client):
        t = client.post("/tournament", json={"name": "Cup"}).json()
        resp = client.post(
            f"/tournament/{t['id']}/join",
            json={"creator_id": "nobody"},
        )
        assert resp.status_code == 404


class TestGetTournament:
    def test_get_existing(self, client):
        t = client.post("/tournament", json={"name": "Cup"}).json()
        resp = client.get(f"/tournament/{t['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Cup"

    def test_get_nonexistent(self, client):
        resp = client.get("/tournament/nope")
        assert resp.status_code == 404


class TestAdvanceTournament:
    def test_advance_needs_at_least_2(self, client):
        _seed_creator("solo")
        t = client.post("/tournament", json={"name": "Cup"}).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "solo"})
        resp = client.post(f"/tournament/{t['id']}/advance")
        assert resp.status_code == 422

    def test_single_elimination_full_run(self, client):
        _seed_creator("p1", score=0.9)
        _seed_creator("p2", score=0.3)
        _seed_creator("p3", score=0.7)
        _seed_creator("p4", score=0.1)

        t = client.post(
            "/tournament",
            json={"name": "Bracket", "max_participants": 4},
        ).json()
        for pid in ["p1", "p2", "p3", "p4"]:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": pid})

        # Round 1
        resp = client.post(f"/tournament/{t['id']}/advance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_round"] == 1
        assert data["status"] == "in_progress"

        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 2

        # Round 2 (final)
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["status"] == "completed"
        assert data["current_round"] == 2

        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 3

    def test_round_robin_full_run(self, client):
        _seed_creator("rr1", score=0.8)
        _seed_creator("rr2", score=0.5)
        _seed_creator("rr3", score=0.3)

        t = client.post(
            "/tournament",
            json={"name": "RR League", "format": "round_robin", "max_participants": 4},
        ).json()
        for pid in ["rr1", "rr2", "rr3"]:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": pid})

        # Run all rounds (n-1 = 2 rounds for 3 participants)
        for _ in range(2):
            resp = client.post(f"/tournament/{t['id']}/advance")
            assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "completed"

        total_points = sum(e["points"] for e in data["entries"])
        assert total_points > 0

    def test_advance_completed_tournament_rejected(self, client):
        _seed_creator("a1", score=0.9)
        _seed_creator("a2", score=0.1)

        t = client.post(
            "/tournament",
            json={"name": "Mini", "max_participants": 2},
        ).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "a1"})
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "a2"})

        client.post(f"/tournament/{t['id']}/advance")

        resp = client.post(f"/tournament/{t['id']}/advance")
        assert resp.status_code == 409
