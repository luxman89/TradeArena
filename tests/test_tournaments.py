"""Tests for tournament system: create, join, get, advance, seeding, matches."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.db.database import Base, BotRatingORM, CreatorORM, CreatorScoreORM, get_db

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


def _reset_rate_limiter():
    """Walk the ASGI middleware stack and clear RateLimitMiddleware state."""
    from tradearena.api.rate_limit import RateLimitMiddleware

    obj = app.middleware_stack
    for _ in range(20):  # walk up to 20 layers deep
        if isinstance(obj, RateLimitMiddleware):
            obj._hits.clear()
            obj._key_hits.clear()
            obj._auth_hits.clear()
            return
        obj = getattr(obj, "app", None)
        if obj is None:
            break


@pytest.fixture(autouse=True)
def reset_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _reset_rate_limiter()
    yield
    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed_creator(creator_id: str, score: float = 0.5, elo: float = 1200.0):
    """Insert a creator, score, and ELO rating directly into the test DB."""
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
    db.add(
        BotRatingORM(
            bot_id=creator_id,
            elo=elo,
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
        assert data["start_time"] is None
        assert data["created_by"] is None
        assert data["matches"] == []

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

    def test_create_with_start_time(self, client):
        resp = client.post(
            "/tournament",
            json={
                "name": "Scheduled Cup",
                "start_time": "2026-04-01T18:00:00Z",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["start_time"] is not None

    def test_create_with_created_by(self, client):
        _seed_creator("organizer-01")
        resp = client.post(
            "/tournament",
            json={"name": "My Cup", "created_by": "organizer-01"},
        )
        assert resp.status_code == 201
        assert resp.json()["created_by"] == "organizer-01"

    def test_create_with_invalid_created_by(self, client):
        resp = client.post(
            "/tournament",
            json={"name": "Bad Cup", "created_by": "nonexistent"},
        )
        assert resp.status_code == 404


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


class TestListTournaments:
    def test_list_all(self, client):
        client.post("/tournament", json={"name": "Cup 1"})
        client.post("/tournament", json={"name": "Cup 2"})
        resp = client.get("/tournaments")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_list_by_status(self, client):
        client.post("/tournament", json={"name": "Cup 1"})
        resp = client.get("/tournaments", params={"tournament_status": "registering"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/tournaments", params={"tournament_status": "completed"})
        assert resp.json()["total"] == 0


class TestAdvanceTournament:
    def test_advance_needs_at_least_2(self, client):
        _seed_creator("solo")
        t = client.post("/tournament", json={"name": "Cup"}).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "solo"})
        resp = client.post(f"/tournament/{t['id']}/advance")
        assert resp.status_code == 422

    def test_single_elimination_full_run(self, client):
        _seed_creator("p1", score=0.9, elo=1600)
        _seed_creator("p2", score=0.3, elo=1300)
        _seed_creator("p3", score=0.7, elo=1500)
        _seed_creator("p4", score=0.1, elo=1100)

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

        # Verify matches are recorded
        assert len(data["matches"]) == 2
        for m in data["matches"]:
            assert m["round"] == 1
            assert m["battle_id"] is not None
            assert m["winner_bot_id"] is not None

        # Round 2 (final)
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["status"] == "completed"
        assert data["current_round"] == 2

        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 3

        # Total matches = 3 (2 from round 1 + 1 from round 2)
        assert len(data["matches"]) == 3

    def test_round_robin_full_run(self, client):
        _seed_creator("rr1", score=0.8, elo=1500)
        _seed_creator("rr2", score=0.5, elo=1300)
        _seed_creator("rr3", score=0.3, elo=1100)

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

        # Matches should be recorded
        assert len(data["matches"]) > 0

    def test_advance_completed_tournament_rejected(self, client):
        _seed_creator("a1", score=0.9, elo=1500)
        _seed_creator("a2", score=0.1, elo=1100)

        t = client.post(
            "/tournament",
            json={"name": "Mini", "max_participants": 2},
        ).json()
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "a1"})
        client.post(f"/tournament/{t['id']}/join", json={"creator_id": "a2"})

        client.post(f"/tournament/{t['id']}/advance")

        resp = client.post(f"/tournament/{t['id']}/advance")
        assert resp.status_code == 409


class TestEloSeeding:
    def test_seeding_by_elo(self, client):
        """Participants are re-seeded by ELO when tournament starts."""
        _seed_creator("low-elo", score=0.5, elo=1000)
        _seed_creator("high-elo", score=0.5, elo=1800)
        _seed_creator("mid-elo", score=0.5, elo=1400)

        t = client.post(
            "/tournament",
            json={"name": "ELO Cup", "max_participants": 4},
        ).json()

        # Join in order: low, high, mid
        for pid in ["low-elo", "high-elo", "mid-elo"]:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": pid})

        # Before advance, seeds are registration order
        data = client.get(f"/tournament/{t['id']}").json()
        seeds_before = {e["creator_id"]: e["seed"] for e in data["entries"]}
        assert seeds_before["low-elo"] == 1  # first to register
        assert seeds_before["high-elo"] == 2

        # Advance triggers ELO seeding
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        seeds_after = {e["creator_id"]: e["seed"] for e in data["entries"]}

        # highest ELO should get seed 1
        assert seeds_after["high-elo"] == 1
        assert seeds_after["mid-elo"] == 2
        assert seeds_after["low-elo"] == 3

    def test_seeding_default_elo_for_unrated(self, client):
        """Creators without ELO ratings get default 1200."""
        _seed_creator("rated", score=0.5, elo=1500)
        # Create unrated creator (no BotRatingORM)
        from datetime import UTC, datetime

        db = TestingSessionLocal()
        db.add(
            CreatorORM(
                id="unrated",
                display_name="unrated",
                division="crypto",
                created_at=datetime.now(UTC),
            )
        )
        db.add(
            CreatorScoreORM(
                creator_id="unrated",
                composite_score=0.5,
                win_rate=0.5,
                risk_adjusted_return=0.5,
                consistency=0.5,
                confidence_calibration=0.5,
                total_signals=10,
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
        db.close()

        t = client.post(
            "/tournament",
            json={"name": "Mixed Cup", "max_participants": 4},
        ).json()
        for pid in ["unrated", "rated"]:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": pid})

        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        seeds = {e["creator_id"]: e["seed"] for e in data["entries"]}

        # rated (1500) > unrated (default 1200)
        assert seeds["rated"] == 1
        assert seeds["unrated"] == 2


class TestEightBotElimination:
    def test_8_bot_single_elimination(self, client):
        """Full 8-bot single elimination: 3 rounds, 7 matches total."""
        creators = []
        for i in range(8):
            cid = f"bot-{i}"
            _seed_creator(cid, score=0.1 * (i + 1), elo=1000 + i * 100)
            creators.append(cid)

        t = client.post(
            "/tournament",
            json={"name": "Grand Tournament", "max_participants": 8},
        ).json()
        for cid in creators:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": cid})

        # Round 1: 4 matches, 4 eliminated
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["current_round"] == 1
        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 4
        round_1_matches = [m for m in data["matches"] if m["round"] == 1]
        assert len(round_1_matches) == 4

        # Round 2: 2 matches, 2 more eliminated
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["current_round"] == 2
        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 6
        round_2_matches = [m for m in data["matches"] if m["round"] == 2]
        assert len(round_2_matches) == 2

        # Round 3 (final): 1 match, champion decided
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["status"] == "completed"
        assert data["current_round"] == 3
        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 7  # only champion survives

        # Total matches = 7
        assert len(data["matches"]) == 7


class TestOddParticipantsBye:
    def test_3_participants_bye(self, client):
        """With 3 participants, one gets a bye in round 1."""
        _seed_creator("bye-1", score=0.9, elo=1600)
        _seed_creator("bye-2", score=0.5, elo=1300)
        _seed_creator("bye-3", score=0.1, elo=1000)

        t = client.post(
            "/tournament",
            json={"name": "Odd Cup", "max_participants": 4},
        ).json()
        for pid in ["bye-1", "bye-2", "bye-3"]:
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": pid})

        # Round 1: 1 match (seed 1 vs seed 3), seed 2 gets bye
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["current_round"] == 1
        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 1  # only 1 eliminated, 2 remain
        round_1_matches = [m for m in data["matches"] if m["round"] == 1]
        assert len(round_1_matches) == 1

        # Round 2 (final)
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["status"] == "completed"

    def test_5_participants_bye(self, client):
        """With 5 participants, one gets a bye in round 1."""
        for i in range(5):
            _seed_creator(f"five-{i}", score=0.1 * (i + 1), elo=1000 + i * 100)

        t = client.post(
            "/tournament",
            json={"name": "Five Cup", "max_participants": 8},
        ).json()
        for i in range(5):
            client.post(f"/tournament/{t['id']}/join", json={"creator_id": f"five-{i}"})

        # Round 1: 2 matches (pairs: seed1 vs seed5, seed2 vs seed4), seed3 bye
        resp = client.post(f"/tournament/{t['id']}/advance")
        data = resp.json()
        assert data["current_round"] == 1
        eliminated = [e for e in data["entries"] if e["eliminated_at"] is not None]
        assert len(eliminated) == 2  # 2 eliminated, 3 remain
        round_1_matches = [m for m in data["matches"] if m["round"] == 1]
        assert len(round_1_matches) == 2
