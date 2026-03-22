"""Tests for GET /health endpoint."""

from __future__ import annotations

from unittest.mock import patch

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


class TestHealthEndpoint:
    """GET /health returns 200 with valid JSON when DB is reachable."""

    def test_health_returns_200(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_valid_json(self, client: TestClient):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["checks"]["database"] == "connected"

    def test_health_includes_version_string(self, client: TestClient):
        resp = client.get("/health")
        data = resp.json()
        # Version should be a non-empty string
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    def test_health_db_unreachable_returns_503(self, client: TestClient):
        """When the database is unreachable, /health returns 503 degraded."""
        with patch(
            "tradearena.api.main.SessionLocal",
            side_effect=Exception("connection refused"),
        ):
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["checks"]["database"] == "unreachable"
