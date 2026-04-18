"""Tests for bcrypt API key migration: verify v2 path, lazy upgrade, and rotation script."""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

import bcrypt as _bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, CreatorORM, get_db

# ---------------------------------------------------------------------------
# Test DB setup
# ---------------------------------------------------------------------------

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


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_creator(db, *, has_v2: bool = True, dev_key: str | None = None) -> tuple[CreatorORM, str]:
    """Insert a test creator; returns (orm, plaintext_key)."""
    raw = f"ta-{secrets.token_hex(16)}"
    sha = hashlib.sha256(raw.encode()).hexdigest()
    v2 = _bcrypt.hashpw(raw.encode(), _bcrypt.gensalt()).decode() if has_v2 else None
    creator = CreatorORM(
        id=f"test-creator-{secrets.token_hex(2)}",
        display_name="Test Creator",
        division="crypto",
        api_key_dev=dev_key,
        api_key_hash=sha,
        api_key_hash_v2=v2,
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    return creator, raw


# ---------------------------------------------------------------------------
# Auth via bcrypt (v2 present)
# ---------------------------------------------------------------------------


def test_auth_succeeds_with_valid_key_and_v2(client, db_session):
    creator, raw_key = _make_creator(db_session, has_v2=True)
    resp = client.post(
        "/signal",
        json={
            "asset": "BTC",
            "action": "buy",
            "confidence": 0.7,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 30, "volume": "high"},
        },
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code in (200, 201)


def test_auth_rejects_wrong_key_even_when_sha256_matches_different_entry(client, db_session):
    """Ensure a tampered key rejected after SHA-256 lookup finds no row."""
    resp = client.post(
        "/signal",
        json={
            "asset": "BTC",
            "action": "buy",
            "confidence": 0.7,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 30, "volume": "high"},
        },
        headers={"X-API-Key": f"ta-{secrets.token_hex(16)}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Lazy upgrade: v2 written on first SHA-256 auth
# ---------------------------------------------------------------------------


def test_lazy_upgrade_writes_v2_on_first_sha256_auth(client, db_session):
    creator, raw_key = _make_creator(db_session, has_v2=False)
    assert creator.api_key_hash_v2 is None

    resp = client.post(
        "/signal",
        json={
            "asset": "BTC",
            "action": "buy",
            "confidence": 0.7,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 30, "volume": "high"},
        },
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code in (200, 201)

    db_session.refresh(creator)
    assert creator.api_key_hash_v2 is not None
    assert _bcrypt.checkpw(raw_key.encode(), creator.api_key_hash_v2.encode())


def test_after_lazy_upgrade_subsequent_auth_uses_bcrypt(client, db_session):
    creator, raw_key = _make_creator(db_session, has_v2=False)

    # First call triggers lazy upgrade
    client.post(
        "/signal",
        json={
            "asset": "BTC",
            "action": "buy",
            "confidence": 0.7,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 30, "volume": "high"},
        },
        headers={"X-API-Key": raw_key},
    )
    db_session.refresh(creator)
    v2_hash = creator.api_key_hash_v2
    assert v2_hash is not None

    # Second call should succeed via bcrypt path
    resp = client.post(
        "/signal",
        json={
            "asset": "BTC",
            "action": "buy",
            "confidence": 0.71,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 31, "volume": "high"},
        },
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code in (200, 201)
    # v2 hash must not change on subsequent calls
    db_session.refresh(creator)
    assert creator.api_key_hash_v2 == v2_hash


# ---------------------------------------------------------------------------
# Registration writes bcrypt from day one
# ---------------------------------------------------------------------------


def test_registration_writes_api_key_hash_v2(client, db_session):
    resp = client.post(
        "/auth/register",
        json={
            "email": "bcrypt@example.com",
            "password": "securepass123",
            "display_name": "Bcrypt Tester",
            "division": "crypto",
            "strategy_description": "Testing bcrypt migration for API keys here.",
            "avatar_index": 0,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    creator_id = data["creator_id"]
    raw_key = data["api_key"]

    row = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    assert row is not None
    assert row.api_key_hash_v2 is not None
    assert _bcrypt.checkpw(raw_key.encode(), row.api_key_hash_v2.encode())


# ---------------------------------------------------------------------------
# Dev plaintext path (seed data)
# ---------------------------------------------------------------------------


def test_dev_plaintext_key_still_works(client, db_session):
    dev_key = "ta-devkeyplaintext1234"
    creator = CreatorORM(
        id=f"dev-creator-{secrets.token_hex(2)}",
        display_name="Dev Creator",
        division="crypto",
        api_key_dev=dev_key,
        api_key_hash=None,
        api_key_hash_v2=None,
        created_at=datetime.now(UTC),
    )
    db_session.add(creator)
    db_session.commit()

    resp = client.post(
        "/signal",
        json={
            "asset": "ETH",
            "action": "buy",
            "confidence": 0.6,
            "reasoning": " ".join(["word"] * 20),
            "supporting_data": {"rsi": 40, "volume": "low"},
        },
        headers={"X-API-Key": dev_key},
    )
    assert resp.status_code in (200, 201)


# ---------------------------------------------------------------------------
# Rotation script
# ---------------------------------------------------------------------------


def test_rotation_script_dry_run(db_session):
    creator, _ = _make_creator(db_session, has_v2=False)
    creator_id = creator.id
    original_sha = creator.api_key_hash
    original_v2 = creator.api_key_hash_v2

    sys.path.insert(0, "scripts")
    from scripts import rotate_api_keys  # noqa: PLC0415

    # Rotation script opens its own session; supply the same engine so it hits the same DB
    with patch("scripts.rotate_api_keys.SessionLocal", TestingSessionLocal):
        buf = StringIO()
        with patch("sys.stdout", buf):
            rotate_api_keys.rotate(dry_run=True)

    output = buf.getvalue()
    manifest = json.loads(output)
    assert len(manifest) >= 1
    assert any(r["creator_id"] == creator_id for r in manifest)

    # Dry run must not mutate the DB
    row = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    assert row.api_key_hash == original_sha
    assert row.api_key_hash_v2 == original_v2


def test_rotation_script_writes_new_keys(db_session):
    creator, _old_key = _make_creator(db_session, has_v2=False)
    creator_id = creator.id
    old_sha = creator.api_key_hash

    sys.path.insert(0, "scripts")
    from scripts import rotate_api_keys  # noqa: PLC0415

    with patch("scripts.rotate_api_keys.SessionLocal", TestingSessionLocal):
        buf = StringIO()
        with patch("sys.stdout", buf):
            rotate_api_keys.rotate(dry_run=False, creator_id=creator_id)

    output = buf.getvalue()
    manifest = json.loads(output)
    assert len(manifest) == 1
    new_key = manifest[0]["new_api_key"]

    row = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    db_session.refresh(row)
    # SHA-256 updated to new key
    assert row.api_key_hash == hashlib.sha256(new_key.encode()).hexdigest()
    assert row.api_key_hash != old_sha
    # bcrypt v2 updated
    assert row.api_key_hash_v2 is not None
    assert _bcrypt.checkpw(new_key.encode(), row.api_key_hash_v2.encode())
    # dev key cleared
    assert row.api_key_dev is None
