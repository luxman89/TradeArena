"""Locust load testing suite for TradeArena.

Covers four scenarios:
  1. Concurrent signal submissions (POST /signal)
  2. Leaderboard queries under load (GET /leaderboard*)
  3. WebSocket connections at scale (ws://host/ws)
  4. Battle creation/resolution under contention (POST /battle/*)

Run:
    # First seed the test database
    uv run python loadtests/seed.py

    # Run the full suite (headless, 60s, 50 users)
    uv run locust -f loadtests/locustfile.py --headless \
        -u 50 -r 10 --run-time 60s \
        --host http://localhost:8000

    # Or with the web UI
    uv run locust -f loadtests/locustfile.py --host http://localhost:8000

Environment variables:
    LOADTEST_BASE_URL   — API base URL (default: http://localhost:8000)
    LOADTEST_WS_URL     — WebSocket URL (default: ws://localhost:8000/ws)
    LOADTEST_NUM_CREATORS — Number of test creators (default: 20)
"""

from __future__ import annotations

import json
import random
import time

import websocket
from locust import HttpUser, between, events, tag, task
from locust.exception import StopUser

from common import creator_pool, random_battle_pair, random_signal_payload

# Pre-compute the creator pool once
_POOL = creator_pool()


# ---------------------------------------------------------------------------
# Custom WebSocket client for Locust metrics integration
# ---------------------------------------------------------------------------


def _ws_connect(environment, url: str, timeout: float = 10.0) -> websocket.WebSocket:
    """Open a WebSocket and record the timing in Locust stats."""
    start = time.perf_counter()
    try:
        ws = websocket.create_connection(url, timeout=timeout)
        elapsed_ms = (time.perf_counter() - start) * 1000
        environment.events.request.fire(
            request_type="WSConnect",
            name="/ws",
            response_time=elapsed_ms,
            response_length=0,
            exception=None,
            context={},
        )
        return ws
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        environment.events.request.fire(
            request_type="WSConnect",
            name="/ws",
            response_time=elapsed_ms,
            response_length=0,
            exception=exc,
            context={},
        )
        raise


def _ws_recv(environment, ws: websocket.WebSocket, name: str = "/ws recv") -> str | None:
    """Receive a message and record timing."""
    start = time.perf_counter()
    try:
        msg = ws.recv()
        elapsed_ms = (time.perf_counter() - start) * 1000
        environment.events.request.fire(
            request_type="WSRecv",
            name=name,
            response_time=elapsed_ms,
            response_length=len(msg) if msg else 0,
            exception=None,
            context={},
        )
        return msg
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        environment.events.request.fire(
            request_type="WSRecv",
            name=name,
            response_time=elapsed_ms,
            response_length=0,
            exception=exc,
            context={},
        )
        return None


# ---------------------------------------------------------------------------
# Signal submission user
# ---------------------------------------------------------------------------


class SignalUser(HttpUser):
    """Simulates traders submitting signals concurrently.

    Each user picks a random creator identity and submits signals.
    Rate-limited to ~1 signal every 6 seconds to stay well within the
    per-creator 10/hour limit (distributing across 20 creators).
    """

    wait_time = between(3, 8)
    weight = 3  # 30% of users

    def on_start(self):
        self._creator = random.choice(_POOL)

    @tag("signals")
    @task
    def submit_signal(self):
        payload = random_signal_payload()
        with self.client.post(
            "/signal",
            json=payload,
            headers={"X-API-Key": self._creator["api_key"]},
            name="/signal",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            elif resp.status_code == 429:
                # Rate limited — expected under load, mark as success
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# Leaderboard reader user
# ---------------------------------------------------------------------------


class LeaderboardUser(HttpUser):
    """Simulates users browsing the leaderboard with pagination."""

    wait_time = between(1, 3)
    weight = 4  # 40% of users — most common read path

    @tag("leaderboard")
    @task(5)
    def get_global_leaderboard(self):
        limit = random.choice([10, 20, 50, 100])
        offset = random.randint(0, 50)
        self.client.get(
            f"/leaderboard?limit={limit}&offset={offset}",
            name="/leaderboard",
        )

    @tag("leaderboard")
    @task(3)
    def get_division_leaderboard(self):
        division = random.choice(["crypto", "polymarket", "multi"])
        self.client.get(
            f"/leaderboard/{division}?limit=50",
            name="/leaderboard/{division}",
        )

    @tag("leaderboard")
    @task(2)
    def get_leaderboard_with_cursor(self):
        """Simulate cursor-based pagination — fetch page 1 then page 2."""
        resp = self.client.get("/leaderboard?limit=10", name="/leaderboard (cursor p1)")
        if resp.status_code == 200:
            data = resp.json()
            cursor = data.get("next_cursor")
            if cursor:
                self.client.get(
                    f"/leaderboard?limit=10&cursor={cursor}",
                    name="/leaderboard (cursor p2)",
                )

    @tag("leaderboard", "health")
    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")


# ---------------------------------------------------------------------------
# WebSocket user
# ---------------------------------------------------------------------------


class WebSocketUser(HttpUser):
    """Simulates WebSocket clients connecting and listening for events.

    Each user connects, listens for a few messages or a timeout,
    then disconnects and reconnects (simulating page refreshes).
    """

    wait_time = between(5, 15)
    weight = 2  # 20% of users

    @tag("websocket")
    @task
    def connect_and_listen(self):
        ws_url = f"ws://{self.host.replace('http://', '').replace('https://', '')}/ws"
        try:
            ws = _ws_connect(self.environment, ws_url, timeout=10)
        except Exception:
            return

        # Listen for up to 5 messages or 10 seconds
        ws.settimeout(3.0)
        messages_received = 0
        for _ in range(5):
            msg = _ws_recv(self.environment, ws, name="/ws recv")
            if msg is None:
                break
            messages_received += 1
            # Respond to pings
            try:
                data = json.loads(msg)
                if data.get("event") == "ping":
                    ws.send("pong")
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Battle user
# ---------------------------------------------------------------------------


class BattleUser(HttpUser):
    """Simulates battle creation and queries under contention.

    Creates battles between random creator pairs, queries active battles,
    and browses battle history.
    """

    wait_time = between(2, 6)
    weight = 1  # 10% of users

    @tag("battles")
    @task(3)
    def create_battle(self):
        c1, c2 = random_battle_pair(_POOL)
        with self.client.post(
            "/battle/create",
            json={
                "creator1_id": c1,
                "creator2_id": c2,
                "window_days": random.randint(1, 7),
            },
            name="/battle/create",
            catch_response=True,
        ) as resp:
            if resp.status_code in (201, 409):
                # 409 = active battle exists, expected under contention
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")

    @tag("battles")
    @task(4)
    def list_active_battles(self):
        self.client.get("/battles/active", name="/battles/active")

    @tag("battles")
    @task(3)
    def battle_history(self):
        creator = random.choice(_POOL)
        self.client.get(
            f"/battles/history?creator_id={creator['id']}&limit=20",
            name="/battles/history",
        )

    @tag("battles")
    @task(1)
    def resolve_battle(self):
        """Try to resolve an active battle — exercises contention path."""
        resp = self.client.get("/battles/active", name="/battles/active (for resolve)")
        if resp.status_code != 200:
            return
        data = resp.json()
        battles = data.get("battles", [])
        if not battles:
            return
        battle = random.choice(battles)
        with self.client.post(
            f"/battle/{battle['battle_id']}/resolve",
            name="/battle/{id}/resolve",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 409, 422):
                # 409 = already resolved, 422 = not enough signals
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")
