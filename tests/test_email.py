"""Tests for the onboarding email drip system."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.core.email import (
    EmailStep,
    generate_unsubscribe_token,
    get_due_emails,
    render_email,
)
from tradearena.db.database import Base, CreatorORM, EmailEventORM, get_db

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
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Unit tests: email core module
# ---------------------------------------------------------------------------


class TestGenerateUnsubscribeToken:
    def test_returns_64_char_hex(self):
        token = generate_unsubscribe_token()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_tokens_are_unique(self):
        tokens = {generate_unsubscribe_token() for _ in range(100)}
        assert len(tokens) == 100


class TestGetDueEmails:
    def test_welcome_due_immediately(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        registered = now
        due = get_due_emails(registered, set(), now)
        assert EmailStep.WELCOME in due

    def test_first_score_due_after_1_day(self):
        now = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        due = get_due_emails(registered, set(), now)
        assert EmailStep.FIRST_SCORE in due

    def test_first_score_not_due_before_1_day(self):
        now = datetime(2026, 3, 21, 18, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        due = get_due_emails(registered, set(), now)
        assert EmailStep.FIRST_SCORE not in due

    def test_battle_invite_due_after_3_days(self):
        now = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        due = get_due_emails(registered, set(), now)
        assert EmailStep.BATTLE_INVITE in due

    def test_weekly_recap_due_after_7_days(self):
        now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        due = get_due_emails(registered, set(), now)
        assert EmailStep.WEEKLY_RECAP in due

    def test_skips_already_sent(self):
        now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        sent = {"welcome", "first_score"}
        due = get_due_emails(registered, sent, now)
        assert EmailStep.WELCOME not in due
        assert EmailStep.FIRST_SCORE not in due
        assert EmailStep.BATTLE_INVITE in due
        assert EmailStep.WEEKLY_RECAP in due

    def test_all_sent_returns_empty(self):
        now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
        registered = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        sent = {"welcome", "first_score", "battle_invite", "weekly_recap"}
        due = get_due_emails(registered, sent, now)
        assert due == []

    def test_no_emails_due_for_new_user_except_welcome(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
        registered = now
        due = get_due_emails(registered, set(), now)
        assert due == [EmailStep.WELCOME]


class TestRenderEmail:
    def test_welcome_email_contains_display_name(self):
        subject, plain, html = render_email(EmailStep.WELCOME, "TestTrader", "a" * 64, "evt123")
        assert "TestTrader" in subject
        assert "TestTrader" in plain
        assert "TestTrader" in html

    def test_all_steps_render_without_error(self):
        for step in EmailStep:
            subject, plain, html = render_email(step, "Alice", "b" * 64, "evt456")
            assert subject
            assert plain
            assert "<!DOCTYPE html>" in html

    def test_unsubscribe_link_in_html(self):
        token = "c" * 64
        _, _, html = render_email(EmailStep.WELCOME, "Bob", token, "evt789")
        assert f"token={token}" in html
        assert "Unsubscribe" in html

    def test_tracking_pixel_in_html(self):
        _, _, html = render_email(EmailStep.WELCOME, "Charlie", "d" * 64, "evt_track")
        assert "email/open/evt_track" in html

    def test_click_tracking_urls_in_html(self):
        _, _, html = render_email(EmailStep.WELCOME, "Dave", "e" * 64, "evt_click")
        assert "email/click/evt_click" in html


# ---------------------------------------------------------------------------
# Integration tests: email endpoints
# ---------------------------------------------------------------------------


def _create_creator(db, *, email_opted_out=False, unsub_token=None):
    """Helper to create a test creator in the DB."""
    token = unsub_token or generate_unsubscribe_token()
    creator = CreatorORM(
        id="test-creator-aa11",
        display_name="Test Creator",
        division="crypto",
        email="test@example.com",
        api_key_hash="a" * 64,
        unsubscribe_token=token,
        email_opted_out=email_opted_out,
        created_at=datetime.now(UTC),
    )
    db.add(creator)
    db.commit()
    return creator, token


class TestUnsubscribeEndpoint:
    def test_unsubscribe_success(self, client, db_session):
        creator, token = _create_creator(db_session)
        resp = client.get(f"/email/unsubscribe?token={token}")
        assert resp.status_code == 200
        assert "Unsubscribed" in resp.text

        # Verify DB state
        db_session.expire_all()
        updated = db_session.query(CreatorORM).filter(CreatorORM.id == creator.id).first()
        assert updated.email_opted_out is True

    def test_unsubscribe_invalid_token(self, client):
        resp = client.get(f"/email/unsubscribe?token={'f' * 64}")
        assert resp.status_code == 404

    def test_unsubscribe_post_rfc8058(self, client, db_session):
        creator, token = _create_creator(db_session)
        resp = client.post(f"/email/unsubscribe?token={token}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"


class TestOpenTracking:
    def test_open_tracking_returns_pixel(self, client, db_session):
        creator, token = _create_creator(db_session)
        event = EmailEventORM(
            id="track-open-001",
            creator_id=creator.id,
            step="welcome",
            status="sent",
            sent_at=datetime.now(UTC),
        )
        db_session.add(event)
        db_session.commit()

        resp = client.get("/email/open/track-open-001")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/gif"

        db_session.expire_all()
        updated = (
            db_session.query(EmailEventORM).filter(EmailEventORM.id == "track-open-001").first()
        )
        assert updated.opened_at is not None

    def test_open_tracking_unknown_event(self, client):
        resp = client.get("/email/open/nonexistent")
        assert resp.status_code == 200  # still returns pixel


class TestClickTracking:
    def test_click_tracking_redirects(self, client, db_session):
        creator, token = _create_creator(db_session)
        event = EmailEventORM(
            id="track-click-001",
            creator_id=creator.id,
            step="welcome",
            status="sent",
            sent_at=datetime.now(UTC),
        )
        db_session.add(event)
        db_session.commit()

        resp = client.get(
            "/email/click/track-click-001?url=https://tradearena.app/arena",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://tradearena.app/arena"

        db_session.expire_all()
        updated = (
            db_session.query(EmailEventORM).filter(EmailEventORM.id == "track-click-001").first()
        )
        assert updated.clicked_at is not None


# ---------------------------------------------------------------------------
# Integration tests: registration sets unsubscribe_token
# ---------------------------------------------------------------------------


class TestRegistrationSetsUnsubToken:
    def test_auth_register_sets_unsubscribe_token(self, client, db_session):
        resp = client.post(
            "/auth/register",
            json={
                "email": "drip@example.com",
                "password": "securepass123",
                "display_name": "DripTester",
                "division": "crypto",
                "strategy_description": "Testing the drip email integration system thoroughly",
                "avatar_index": 0,
            },
        )
        assert resp.status_code == 201
        creator_id = resp.json()["creator_id"]

        creator = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
        assert creator.unsubscribe_token is not None
        assert len(creator.unsubscribe_token) == 64
        assert creator.email_opted_out is False

    def test_creator_register_sets_unsubscribe_token(self, client, db_session):
        resp = client.post(
            "/creator/register",
            json={
                "email": "sdk-drip@example.com",
                "display_name": "SDKDripTester",
                "division": "crypto",
                "strategy_description": "Testing the SDK registration drip integration",
            },
        )
        assert resp.status_code == 201
        creator_id = resp.json()["creator_id"]

        creator = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
        assert creator.unsubscribe_token is not None
        assert len(creator.unsubscribe_token) == 64
        assert creator.email_opted_out is False


# ---------------------------------------------------------------------------
# Unit tests: send_email (mocked)
# ---------------------------------------------------------------------------


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_send_email_no_api_key(self):
        """Without SENDGRID_API_KEY, send_email returns False."""
        from tradearena.core.email import send_email

        result = await send_email("test@example.com", "Subject", "plain", "<html></html>", "a" * 64)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """With API key, send_email calls SendGrid and returns True on 202."""
        from tradearena.core import email as email_mod

        mock_resp = AsyncMock()
        mock_resp.status_code = 202
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(email_mod, "SENDGRID_API_KEY", "test-key"),
            patch("tradearena.core.email.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await email_mod.send_email(
                "test@example.com", "Subject", "plain", "<html></html>", "a" * 64
            )
            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_failure(self):
        """send_email returns False on non-2xx response."""
        from tradearena.core import email as email_mod

        mock_resp = AsyncMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(email_mod, "SENDGRID_API_KEY", "test-key"),
            patch("tradearena.core.email.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await email_mod.send_email(
                "test@example.com", "Subject", "plain", "<html></html>", "a" * 64
            )
            assert result is False
