"""Tests for POST /creator/register endpoint."""

from __future__ import annotations

import hashlib
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, get_db

# --- In-memory SQLite DB for tests ---
# StaticPool ensures all connections share the same in-memory DB instance.

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


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


VALID_PAYLOAD = {
    "display_name": "Test Trader",
    "division": "crypto",
    "strategy_description": "Momentum strategy based on RSI and volume analysis.",
    "email": "trader@example.com",
}


def post_register(client: TestClient, payload: dict):
    return client.post("/creator/register", json=payload)


# --- Tests ---


class TestSuccessfulRegistration:
    def test_returns_201(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        assert resp.status_code == 201

    def test_response_fields_complete(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        data = resp.json()
        assert "creator_id" in data
        assert "api_key" in data
        assert "display_name" in data
        assert "division" in data
        assert "created_at" in data

    def test_api_key_format(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        api_key = resp.json()["api_key"]
        # "ta-" + 32 hex chars
        assert re.match(r"^ta-[0-9a-f]{32}$", api_key), f"Unexpected api_key format: {api_key}"

    def test_creator_id_format(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        creator_id = resp.json()["creator_id"]
        # slug + "-" + 4 hex chars
        assert re.match(r"^[a-z0-9\-]+-[0-9a-f]{4}$", creator_id), (
            f"Unexpected creator_id: {creator_id}"
        )

    def test_creator_id_slugified(self, client):
        payload = {**VALID_PAYLOAD, "display_name": "Alice Quantsworth!"}
        resp = post_register(client, payload)
        creator_id = resp.json()["creator_id"]
        # Should be lowercase, no special chars except hyphens
        assert re.match(r"^[a-z0-9\-]+$", creator_id)
        assert "alice" in creator_id
        assert "quantsworth" in creator_id

    def test_response_display_name_matches(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        assert resp.json()["display_name"] == VALID_PAYLOAD["display_name"]

    def test_response_division_matches(self, client):
        resp = post_register(client, VALID_PAYLOAD)
        assert resp.json()["division"] == VALID_PAYLOAD["division"]

    def test_api_key_stored_as_hash_not_plaintext(self, client):
        """Verify that plaintext api_key is NOT stored in DB (only hash is)."""
        from tradearena.db.database import CreatorORM

        resp = post_register(client, VALID_PAYLOAD)
        data = resp.json()
        db = TestingSessionLocal()
        try:
            creator = db.query(CreatorORM).filter(CreatorORM.id == data["creator_id"]).first()
            assert creator is not None
            # api_key_dev must be null (not a seed creator)
            assert creator.api_key_dev is None
            # api_key_hash must be sha256 of the returned api_key
            expected_hash = hashlib.sha256(data["api_key"].encode()).hexdigest()
            assert creator.api_key_hash == expected_hash
        finally:
            db.close()


class TestDuplicateEmail:
    def test_duplicate_email_returns_409(self, client):
        post_register(client, VALID_PAYLOAD)
        resp = post_register(client, VALID_PAYLOAD)
        assert resp.status_code == 409

    def test_duplicate_email_error_message(self, client):
        post_register(client, VALID_PAYLOAD)
        resp = post_register(client, VALID_PAYLOAD)
        assert "already registered" in resp.json()["detail"].lower()

    def test_different_email_succeeds(self, client):
        post_register(client, VALID_PAYLOAD)
        payload2 = {**VALID_PAYLOAD, "email": "other@example.com"}
        resp = post_register(client, payload2)
        assert resp.status_code == 201


class TestDivisionValidation:
    def test_invalid_division_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "division": "stocks"}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_valid_division_crypto(self, client):
        payload = {**VALID_PAYLOAD, "division": "crypto"}
        assert post_register(client, payload).status_code == 201

    def test_valid_division_polymarket(self, client):
        payload = {**VALID_PAYLOAD, "division": "polymarket", "email": "poly@example.com"}
        assert post_register(client, payload).status_code == 201

    def test_valid_division_multi(self, client):
        payload = {**VALID_PAYLOAD, "division": "multi", "email": "multi@example.com"}
        assert post_register(client, payload).status_code == 201


class TestDisplayNameValidation:
    def test_display_name_too_short_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "display_name": "AB"}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_display_name_too_long_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "display_name": "A" * 51}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_display_name_min_length_succeeds(self, client):
        payload = {**VALID_PAYLOAD, "display_name": "ABC", "email": "abc@example.com"}
        assert post_register(client, payload).status_code == 201

    def test_display_name_max_length_succeeds(self, client):
        payload = {**VALID_PAYLOAD, "display_name": "A" * 50, "email": "long@example.com"}
        assert post_register(client, payload).status_code == 201


class TestStrategyDescriptionValidation:
    def test_strategy_too_short_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "strategy_description": "Too short."}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_strategy_too_long_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "strategy_description": "A" * 501}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_strategy_min_length_succeeds(self, client):
        payload = {**VALID_PAYLOAD, "strategy_description": "A" * 20, "email": "min@example.com"}
        assert post_register(client, payload).status_code == 201

    def test_strategy_max_length_succeeds(self, client):
        payload = {**VALID_PAYLOAD, "strategy_description": "A" * 500, "email": "max@example.com"}
        assert post_register(client, payload).status_code == 201


class TestEmailValidation:
    def test_invalid_email_no_at_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "email": "notanemail"}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_invalid_email_no_domain_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "email": "user@"}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_invalid_email_no_tld_returns_422(self, client):
        payload = {**VALID_PAYLOAD, "email": "user@domain"}
        resp = post_register(client, payload)
        assert resp.status_code == 422

    def test_valid_email_accepted(self, client):
        payload = {**VALID_PAYLOAD, "email": "valid.user+tag@sub.domain.com"}
        assert post_register(client, payload).status_code == 201
