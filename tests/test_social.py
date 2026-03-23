"""Tests for social features: follow/unfollow, signal comments, following feed."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.deps import require_jwt_token
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


_CURRENT_USER = "alice-a1b2"


def override_jwt():
    return _CURRENT_USER


@pytest.fixture(autouse=True)
def reset_db():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_jwt_token] = override_jwt
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed_creator(creator_id: str, display_name: str | None = None) -> None:
    db = TestingSessionLocal()
    db.add(
        CreatorORM(
            id=creator_id,
            display_name=display_name or creator_id.replace("-", " ").title(),
            division="crypto",
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


def _seed_signal(creator_id: str, signal_id: str | None = None) -> str:
    sid = signal_id or secrets.token_hex(16)
    db = TestingSessionLocal()
    db.add(
        SignalORM(
            signal_id=sid,
            creator_id=creator_id,
            asset="BTCUSDT",
            action="long",
            confidence=0.75,
            reasoning="Test reasoning with more than twenty words to pass validation check ok",
            supporting_data={"rsi": 55, "volume": "+30%"},
            commitment_hash=secrets.token_hex(32),
            committed_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()
    return sid


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------


class TestFollow:
    def test_follow_creator(self, client):
        _seed_creator(_CURRENT_USER)
        _seed_creator("bob-c3d4")
        resp = client.post("/creator/bob-c3d4/follow")
        assert resp.status_code == 201
        data = resp.json()
        assert data["follower_id"] == _CURRENT_USER
        assert data["followed_id"] == "bob-c3d4"
        assert "created_at" in data

    def test_follow_self_rejected(self, client):
        _seed_creator(_CURRENT_USER)
        resp = client.post(f"/creator/{_CURRENT_USER}/follow")
        assert resp.status_code == 422
        assert "yourself" in resp.json()["detail"].lower()

    def test_follow_nonexistent_creator(self, client):
        _seed_creator(_CURRENT_USER)
        resp = client.post("/creator/nobody-0000/follow")
        assert resp.status_code == 404

    def test_follow_duplicate_rejected(self, client):
        _seed_creator(_CURRENT_USER)
        _seed_creator("bob-c3d4")
        client.post("/creator/bob-c3d4/follow")
        resp = client.post("/creator/bob-c3d4/follow")
        assert resp.status_code == 409

    def test_unfollow_creator(self, client):
        _seed_creator(_CURRENT_USER)
        _seed_creator("bob-c3d4")
        client.post("/creator/bob-c3d4/follow")
        resp = client.delete("/creator/bob-c3d4/follow")
        assert resp.status_code == 200

    def test_unfollow_not_following(self, client):
        _seed_creator(_CURRENT_USER)
        resp = client.delete("/creator/bob-c3d4/follow")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Followers / Following lists
# ---------------------------------------------------------------------------


class TestFollowersList:
    def test_list_followers(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        client.post("/creator/bob-c3d4/follow")
        resp = client.get("/creator/bob-c3d4/followers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["followers"][0]["creator_id"] == _CURRENT_USER

    def test_list_following(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        _seed_creator("carol-e5f6", "Carol")
        client.post("/creator/bob-c3d4/follow")
        client.post("/creator/carol-e5f6/follow")
        resp = client.get(f"/creator/{_CURRENT_USER}/following")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_list_followers_empty(self, client):
        _seed_creator("bob-c3d4", "Bob")
        resp = client.get("/creator/bob-c3d4/followers")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["followers"] == []

    def test_list_followers_not_found(self, client):
        resp = client.get("/creator/nobody-0000/followers")
        assert resp.status_code == 404

    def test_list_following_not_found(self, client):
        resp = client.get("/creator/nobody-0000/following")
        assert resp.status_code == 404

    def test_list_followers_pagination(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        client.post("/creator/bob-c3d4/follow")
        resp = client.get("/creator/bob-c3d4/followers?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 1
        assert len(data["followers"]) == 1


# ---------------------------------------------------------------------------
# Following Feed
# ---------------------------------------------------------------------------


class TestFollowingFeed:
    def test_feed_empty_when_not_following(self, client):
        _seed_creator(_CURRENT_USER)
        resp = client.get("/feed/following")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_feed_shows_followed_signals(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        _seed_signal("bob-c3d4")
        client.post("/creator/bob-c3d4/follow")
        resp = client.get("/feed/following")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["signals"][0]["creator_id"] == "bob-c3d4"
        assert data["signals"][0]["display_name"] == "Bob"

    def test_feed_excludes_unfollowed_signals(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        _seed_creator("carol-e5f6", "Carol")
        _seed_signal("bob-c3d4")
        _seed_signal("carol-e5f6")
        client.post("/creator/bob-c3d4/follow")
        resp = client.get("/feed/following")
        data = resp.json()
        assert data["total"] == 1
        assert all(s["creator_id"] == "bob-c3d4" for s in data["signals"])

    def test_feed_pagination(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        for _ in range(5):
            _seed_signal("bob-c3d4")
        client.post("/creator/bob-c3d4/follow")
        resp = client.get("/feed/following?limit=2&offset=0")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["signals"]) == 2


# ---------------------------------------------------------------------------
# Signal Comments
# ---------------------------------------------------------------------------


class TestSignalComments:
    def test_create_comment(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        sid = _seed_signal("bob-c3d4")
        resp = client.post(f"/signal/{sid}/comments", json={"body": "Great call!"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["signal_id"] == sid
        assert data["creator_id"] == _CURRENT_USER
        assert data["body"] == "Great call!"
        assert data["display_name"] == "Alice"

    def test_create_comment_on_nonexistent_signal(self, client):
        _seed_creator(_CURRENT_USER)
        resp = client.post("/signal/fakeid000/comments", json={"body": "test"})
        assert resp.status_code == 404

    def test_create_comment_empty_body(self, client):
        _seed_creator(_CURRENT_USER)
        _seed_creator("bob-c3d4")
        sid = _seed_signal("bob-c3d4")
        resp = client.post(f"/signal/{sid}/comments", json={"body": ""})
        assert resp.status_code == 422

    def test_create_comment_too_long(self, client):
        _seed_creator(_CURRENT_USER)
        _seed_creator("bob-c3d4")
        sid = _seed_signal("bob-c3d4")
        resp = client.post(f"/signal/{sid}/comments", json={"body": "x" * 1001})
        assert resp.status_code == 422

    def test_list_comments(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        sid = _seed_signal("bob-c3d4")
        client.post(f"/signal/{sid}/comments", json={"body": "First!"})
        client.post(f"/signal/{sid}/comments", json={"body": "Second!"})
        resp = client.get(f"/signal/{sid}/comments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["comments"][0]["body"] == "First!"
        assert data["comments"][1]["body"] == "Second!"

    def test_list_comments_empty(self, client):
        _seed_creator("bob-c3d4")
        sid = _seed_signal("bob-c3d4")
        resp = client.get(f"/signal/{sid}/comments")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_comments_signal_not_found(self, client):
        resp = client.get("/signal/fakeid000/comments")
        assert resp.status_code == 404

    def test_list_comments_pagination(self, client):
        _seed_creator(_CURRENT_USER, "Alice")
        _seed_creator("bob-c3d4", "Bob")
        sid = _seed_signal("bob-c3d4")
        for i in range(5):
            client.post(f"/signal/{sid}/comments", json={"body": f"Comment {i}"})
        resp = client.get(f"/signal/{sid}/comments?limit=2&offset=1")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["comments"]) == 2
        assert data["comments"][0]["body"] == "Comment 1"
