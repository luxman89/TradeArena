"""Tests for tournament scheduling: CRUD, auto-creation, league standings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.core.scheduler import compute_next_run, run_scheduled_tournaments
from tradearena.db.database import (
    Base,
    CreatorORM,
    CreatorScoreORM,
    TournamentORM,
    TournamentScheduleORM,
    get_db,
)

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


CREATOR_A = "admin-test-a1b2"
API_KEY_A = "ta-admin-test-key-00000000000000000000"
CREATOR_B = "bob-test-b3c4"
CREATOR_C = "carol-test-d5e6"


def _seed_creator(creator_id: str, api_key: str | None = None, division: str = "crypto"):
    db = TestingSessionLocal()
    db.add(
        CreatorORM(
            id=creator_id,
            display_name=creator_id.replace("-", " ").title(),
            division=division,
            api_key_dev=api_key,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


def _seed_score(creator_id: str, total_signals: int = 10, composite: float = 0.5):
    db = TestingSessionLocal()
    db.add(
        CreatorScoreORM(
            creator_id=creator_id,
            total_signals=total_signals,
            composite_score=composite,
            updated_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.close()


def _schedule_payload(**overrides) -> dict:
    base = {
        "name": "Daily Crypto League",
        "format": "round_robin",
        "recurrence": "daily",
        "hour": 14,
        "max_participants": 8,
        "division": "crypto",
        "min_signals": 5,
    }
    base.update(overrides)
    return base


# ── Schedule CRUD ────────────────────────────────────────────────────────


class TestScheduleCRUD:
    def test_create_schedule(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Daily Crypto League"
        assert data["recurrence"] == "daily"
        assert data["hour"] == 14
        assert data["is_active"] is True
        assert data["created_by"] == CREATOR_A
        assert len(data["id"]) == 32

    def test_create_weekly_requires_day_of_week(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/schedules",
            json=_schedule_payload(recurrence="weekly"),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 400
        assert "day_of_week" in resp.json()["detail"]

    def test_create_weekly_with_day(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        resp = client.post(
            "/schedules",
            json=_schedule_payload(recurrence="weekly", day_of_week=4),
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 201
        assert resp.json()["day_of_week"] == 4

    def test_list_schedules(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        client.post(
            "/schedules",
            json=_schedule_payload(name="League A"),
            headers={"X-API-Key": API_KEY_A},
        )
        client.post(
            "/schedules",
            json=_schedule_payload(name="League B"),
            headers={"X-API-Key": API_KEY_A},
        )

        resp = client.get("/schedules")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_get_schedule(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.get(f"/schedules/{sid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == sid

    def test_update_schedule(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.patch(
            f"/schedules/{sid}",
            json={"name": "Updated League", "hour": 18},
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated League"
        assert resp.json()["hour"] == 18

    def test_update_forbidden_non_owner(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B, "ta-bob-key-000000000000000000000000")
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.patch(
            f"/schedules/{sid}",
            json={"name": "Hacked"},
            headers={"X-API-Key": "ta-bob-key-000000000000000000000000"},
        )
        assert resp.status_code == 403

    def test_delete_schedule(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.delete(f"/schedules/{sid}", headers={"X-API-Key": API_KEY_A})
        assert resp.status_code == 204

        resp = client.get(f"/schedules/{sid}")
        assert resp.status_code == 404

    def test_deactivate_schedule(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.patch(
            f"/schedules/{sid}",
            json={"is_active": False},
            headers={"X-API-Key": API_KEY_A},
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # Inactive schedules hidden from default list
        resp = client.get("/schedules")
        assert resp.json()["total"] == 0

        # But visible with active_only=false
        resp = client.get("/schedules?active_only=false")
        assert resp.json()["total"] == 1


# ── Compute Next Run ─────────────────────────────────────────────────────


class TestComputeNextRun:
    def test_daily_next_run(self):
        s = TournamentScheduleORM(recurrence="daily", hour=14, day_of_week=None)
        now = datetime(2026, 3, 23, 10, 0, tzinfo=UTC)
        nxt = compute_next_run(s, now)
        assert nxt == datetime(2026, 3, 23, 14, 0, tzinfo=UTC)

    def test_daily_next_run_past_hour(self):
        s = TournamentScheduleORM(recurrence="daily", hour=8, day_of_week=None)
        now = datetime(2026, 3, 23, 10, 0, tzinfo=UTC)
        nxt = compute_next_run(s, now)
        assert nxt == datetime(2026, 3, 24, 8, 0, tzinfo=UTC)

    def test_weekly_next_run(self):
        s = TournamentScheduleORM(recurrence="weekly", hour=12, day_of_week=4)  # Friday
        # March 23 2026 is Monday (weekday=0)
        now = datetime(2026, 3, 23, 10, 0, tzinfo=UTC)
        nxt = compute_next_run(s, now)
        assert nxt.weekday() == 4  # Friday
        assert nxt == datetime(2026, 3, 27, 12, 0, tzinfo=UTC)


# ── Scheduler Logic ──────────────────────────────────────────────────────


class TestSchedulerLogic:
    def test_creates_tournament_from_due_schedule(self):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B)
        _seed_creator(CREATOR_C)
        _seed_score(CREATOR_A, total_signals=10, composite=0.7)
        _seed_score(CREATOR_B, total_signals=8, composite=0.5)
        _seed_score(CREATOR_C, total_signals=6, composite=0.3)

        db = TestingSessionLocal()
        now = datetime.now(UTC)
        schedule = TournamentScheduleORM(
            id="sched-test-001",
            name="Test Daily",
            format="round_robin",
            recurrence="daily",
            hour=now.hour,
            max_participants=8,
            division="crypto",
            min_signals=5,
            is_active=True,
            created_by=CREATOR_A,
            created_at=now - timedelta(days=1),
            next_run_at=now - timedelta(minutes=1),  # due
            last_run_at=None,
        )
        db.add(schedule)
        db.commit()

        created = run_scheduled_tournaments(db)
        assert created == 1

        # Verify tournament was created
        tournaments = db.query(TournamentORM).all()
        assert len(tournaments) == 1
        assert "Test Daily" in tournaments[0].name
        assert tournaments[0].status == "registering"

        # Verify next_run_at was advanced (compare naive to naive)
        db.refresh(schedule)
        assert schedule.next_run_at > now.replace(tzinfo=None)
        assert schedule.last_run_at is not None
        db.close()

    def test_skips_inactive_schedules(self):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B)
        _seed_score(CREATOR_A, total_signals=10)
        _seed_score(CREATOR_B, total_signals=10)

        db = TestingSessionLocal()
        now = datetime.now(UTC)
        schedule = TournamentScheduleORM(
            id="sched-inactive",
            name="Inactive",
            format="round_robin",
            recurrence="daily",
            hour=now.hour,
            max_participants=8,
            division="crypto",
            min_signals=5,
            is_active=False,  # inactive
            created_by=CREATOR_A,
            created_at=now,
            next_run_at=now - timedelta(minutes=1),
        )
        db.add(schedule)
        db.commit()

        created = run_scheduled_tournaments(db)
        assert created == 0
        db.close()

    def test_skips_when_not_enough_eligible(self):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_score(CREATOR_A, total_signals=10)
        # Only 1 creator eligible — need at least 2

        db = TestingSessionLocal()
        now = datetime.now(UTC)
        schedule = TournamentScheduleORM(
            id="sched-not-enough",
            name="Not Enough",
            format="round_robin",
            recurrence="daily",
            hour=now.hour,
            max_participants=8,
            division="crypto",
            min_signals=5,
            is_active=True,
            created_by=CREATOR_A,
            created_at=now,
            next_run_at=now - timedelta(minutes=1),
        )
        db.add(schedule)
        db.commit()

        created = run_scheduled_tournaments(db)
        assert created == 0

        # next_run_at still advanced
        db.refresh(schedule)
        assert schedule.next_run_at > now.replace(tzinfo=None)
        db.close()

    def test_respects_division_filter(self):
        _seed_creator(CREATOR_A, API_KEY_A, division="crypto")
        _seed_creator(CREATOR_B, division="polymarket")
        _seed_creator(CREATOR_C, division="crypto")
        _seed_score(CREATOR_A, total_signals=10)
        _seed_score(CREATOR_B, total_signals=10)
        _seed_score(CREATOR_C, total_signals=10)

        db = TestingSessionLocal()
        now = datetime.now(UTC)
        schedule = TournamentScheduleORM(
            id="sched-div",
            name="Crypto Only",
            format="round_robin",
            recurrence="daily",
            hour=now.hour,
            max_participants=8,
            division="crypto",  # only crypto creators
            min_signals=5,
            is_active=True,
            created_by=CREATOR_A,
            created_at=now,
            next_run_at=now - timedelta(minutes=1),
        )
        db.add(schedule)
        db.commit()

        created = run_scheduled_tournaments(db)
        assert created == 1

        from tradearena.db.database import TournamentEntryORM

        entries = db.query(TournamentEntryORM).all()
        entry_ids = {e.creator_id for e in entries}
        assert CREATOR_B not in entry_ids  # polymarket excluded
        assert CREATOR_A in entry_ids
        assert CREATOR_C in entry_ids
        db.close()


# ── Standings ────────────────────────────────────────────────────────────


class TestStandings:
    def test_get_standings_empty(self, client):
        _seed_creator(CREATOR_A, API_KEY_A)
        create = client.post(
            "/schedules",
            json=_schedule_payload(),
            headers={"X-API-Key": API_KEY_A},
        )
        sid = create.json()["id"]

        resp = client.get(f"/schedules/{sid}/standings")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["standings"] == []

    def test_standings_after_update(self):
        _seed_creator(CREATOR_A, API_KEY_A)
        _seed_creator(CREATOR_B)

        db = TestingSessionLocal()
        now = datetime.now(UTC)

        from tradearena.db.database import LeagueStandingORM

        schedule = TournamentScheduleORM(
            id="sched-standings",
            name="Standings Test",
            format="round_robin",
            recurrence="daily",
            hour=12,
            max_participants=8,
            division="crypto",
            min_signals=5,
            is_active=True,
            created_by=CREATOR_A,
            created_at=now,
            next_run_at=now + timedelta(days=1),
        )
        db.add(schedule)
        db.add(
            LeagueStandingORM(
                schedule_id="sched-standings",
                creator_id=CREATOR_A,
                tournaments_played=3,
                tournaments_won=2,
                total_points=15,
                updated_at=now,
            )
        )
        db.add(
            LeagueStandingORM(
                schedule_id="sched-standings",
                creator_id=CREATOR_B,
                tournaments_played=3,
                tournaments_won=1,
                total_points=10,
                updated_at=now,
            )
        )
        db.commit()
        db.close()

        with TestClient(app) as client:
            resp = client.get("/schedules/sched-standings/standings")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            # Sorted by wins desc
            assert data["standings"][0]["creator_id"] == CREATOR_A
            assert data["standings"][0]["tournaments_won"] == 2
