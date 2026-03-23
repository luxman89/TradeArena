"""Tests for bot marketplace: publish, browse, fork, update, delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
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


CREATOR_A = "alice-test-a1b2"
CREATOR_B = "bob-test-c3d4"
API_KEY_A = "ta-alice-test-key-00000000000000000000"
API_KEY_B = "ta-bob-test-key-000000000000000000000"


def _seed_creator(creator_id: str, api_key: str) -> None:
    db = TestingSessionLocal()
    db.add(
        CreatorORM(
            id=creator_id,
            display_name=creator_id.title(),
            division="crypto",
            api_key_dev=api_key,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


def _template_payload(**overrides) -> dict:
    base = {
        "name": "My RSI Bot",
        "description": "A mean-reversion bot using RSI(14) signals.",
        "strategy_type": "mean_reversion",
        "code": "import tradearena\n# RSI strategy bot\nprint('hello')",
        "tags": ["rsi", "crypto"],
        "config": {"rsi_period": 14, "threshold": 30},
        "is_public": True,
    }
    base.update(overrides)
    return base


# ── Publish ──────────────────────────────────────────────────────────────


class TestPublish:
    def test_publish_template(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My RSI Bot"
        assert data["strategy_type"] == "mean_reversion"
        assert data["creator_id"] == CREATOR_A
        assert data["version"] == 1
        assert data["fork_count"] == 0
        assert data["forked_from_id"] is None
        assert data["code"] == "import tradearena\n# RSI strategy bot\nprint('hello')"
        assert len(data["id"]) == 32

    def test_publish_requires_auth(self, client):
        resp = client.post("/marketplace/templates", json=_template_payload())
        assert resp.status_code == 401

    def test_publish_missing_name(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/marketplace/templates",
            json=_template_payload(name=""),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 400

    def test_publish_missing_code(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/marketplace/templates",
            json=_template_payload(code=""),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 400

    def test_publish_invalid_strategy_type(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/marketplace/templates",
            json=_template_payload(strategy_type="invalid"),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 400

    def test_publish_too_many_tags(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/marketplace/templates",
            json=_template_payload(tags=[f"tag{i}" for i in range(11)]),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 400


# ── Browse ───────────────────────────────────────────────────────────────


class TestBrowse:
    def _publish(self, client, api_key, **overrides):
        return client.post(
            "/marketplace/templates",
            json=_template_payload(**overrides),
            headers={"X-API-Key": api_key},
        )

    def test_list_public_templates(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        self._publish(client, API_KEY_A, name="Bot A")
        self._publish(client, API_KEY_A, name="Bot B")
        self._publish(client, API_KEY_A, name="Private Bot", is_public=False)

        resp = client.get("/marketplace/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["templates"]) == 2
        names = {t["name"] for t in data["templates"]}
        assert "Private Bot" not in names

    def test_filter_by_strategy_type(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        self._publish(client, API_KEY_A, name="Momentum", strategy_type="momentum")
        self._publish(client, API_KEY_A, name="Sentiment", strategy_type="sentiment")

        resp = client.get("/marketplace/templates?strategy_type=momentum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["templates"][0]["name"] == "Momentum"

    def test_search_by_name(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        self._publish(client, API_KEY_A, name="Unique Zebra Strategy")
        self._publish(client, API_KEY_A, name="EMA Cross Bot")

        resp = client.get("/marketplace/templates?q=Zebra")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["templates"][0]["name"] == "Unique Zebra Strategy"

    def test_filter_by_creator(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)
        self._publish(client, API_KEY_A, name="Alice Bot")
        self._publish(client, API_KEY_B, name="Bob Bot")

        resp = client.get(f"/marketplace/templates?creator_id={CREATOR_A}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["templates"][0]["name"] == "Alice Bot"

    def test_sort_recent(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        self._publish(client, API_KEY_A, name="First")
        self._publish(client, API_KEY_A, name="Second")

        resp = client.get("/marketplace/templates?sort=recent")
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["templates"]]
        assert names[0] == "Second"

    def test_pagination(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        for i in range(5):
            self._publish(client, API_KEY_A, name=f"Bot {i}")

        resp = client.get("/marketplace/templates?limit=2&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()["templates"]) == 2
        assert resp.json()["total"] == 5

    def test_invalid_strategy_type_filter(self, client):
        resp = client.get("/marketplace/templates?strategy_type=invalid")
        assert resp.status_code == 400


# ── Get Detail ───────────────────────────────────────────────────────────


class TestGetDetail:
    def test_get_public_template(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.get(f"/marketplace/templates/{tid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == tid
        assert "code" in resp.json()  # detail includes code

    def test_get_private_template_returns_404(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(is_public=False),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.get(f"/marketplace/templates/{tid}")
        assert resp.status_code == 404

    def test_get_nonexistent(self, client):
        resp = client.get(f"/marketplace/templates/{uuid.uuid4().hex}")
        assert resp.status_code == 404


# ── Update ───────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_name(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.patch(
            f"/marketplace/templates/{tid}",
            json={"name": "Updated Bot Name"},
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Bot Name"
        assert resp.json()["version"] == 1  # name change doesn't bump version

    def test_update_code_bumps_version(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.patch(
            f"/marketplace/templates/{tid}",
            json={"code": "# version 2\nprint('updated')"},
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2

    def test_update_forbidden_for_non_owner(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.patch(
            f"/marketplace/templates/{tid}",
            json={"name": "Hacked"},
            headers={"X-API-Key": API_KEY_B},
        )
        assert resp.status_code == 403


# ── Delete ───────────────────────────────────────────────────────────────


class TestDelete:
    def test_delete_template(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.delete(
            f"/marketplace/templates/{tid}",
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 204

        # Confirm deleted
        resp = client.get(f"/marketplace/templates/{tid}")
        assert resp.status_code == 404

    def test_delete_forbidden_for_non_owner(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.delete(
            f"/marketplace/templates/{tid}",
            headers={"X-API-Key": API_KEY_B},
        )
        assert resp.status_code == 403

    def test_delete_nullifies_forks(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)

        # Publish and fork
        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]
        fork = client.post(
            f"/marketplace/templates/{tid}/fork",
            json={},
            headers={"X-API-Key": API_KEY_B},
        )
        fork_id = fork.json()["id"]

        # Delete original
        client.delete(
            f"/marketplace/templates/{tid}",
            headers={"X-API-Key": API_KEY_A},
        )

        # Fork still exists with nullified forked_from_id
        resp = client.get(f"/marketplace/templates/{fork_id}")
        assert resp.status_code == 200
        assert resp.json()["forked_from_id"] is None


# ── Fork ─────────────────────────────────────────────────────────────────


class TestFork:
    def test_fork_template(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)

        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.post(
            f"/marketplace/templates/{tid}/fork",
            json={"name": "My Fork"},
            headers={"X-API-Key": API_KEY_B},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Fork"
        assert data["creator_id"] == CREATOR_B
        assert data["forked_from_id"] == tid
        assert data["version"] == 1
        assert data["code"] == pub.json()["code"]

        # Source fork_count incremented
        source = client.get(f"/marketplace/templates/{tid}")
        assert source.json()["fork_count"] == 1

    def test_fork_default_name(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)

        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(name="Original"),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.post(
            f"/marketplace/templates/{tid}/fork",
            json={},
            headers={"X-API-Key": API_KEY_B},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Original (fork)"

    def test_fork_nonexistent(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            f"/marketplace/templates/{uuid.uuid4().hex}/fork",
            json={},
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 404

    def test_fork_private_by_non_owner(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, API_KEY_B)

        pub = client.post(
            "/marketplace/templates",
            json=_template_payload(is_public=False),
            headers={"X-API-Key": API_KEY_A},
        )
        tid = pub.json()["id"]

        resp = client.post(
            f"/marketplace/templates/{tid}/fork",
            json={},
            headers={"X-API-Key": API_KEY_B},
        )
        assert resp.status_code == 404


# ── My Templates ─────────────────────────────────────────────────────────


class TestMyTemplates:
    def test_lists_own_templates_including_private(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        client.post(
            "/marketplace/templates",
            json=_template_payload(name="Public"),
            headers={"X-API-Key": API_KEY_A},
        )
        client.post(
            "/marketplace/templates",
            json=_template_payload(name="Private", is_public=False),
            headers={"X-API-Key": API_KEY_A},
        )

        resp = client.get(
            "/marketplace/my-templates",
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        names = {t["name"] for t in resp.json()["templates"]}
        assert names == {"Public", "Private"}

    def test_requires_auth(self, client):
        resp = client.get("/marketplace/my-templates")
        assert resp.status_code == 401
