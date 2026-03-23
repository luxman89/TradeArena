"""Pytest-based performance benchmarks for TradeArena.

These tests run against a real in-memory database (no mocks) and measure
response times, throughput, and concurrency behavior. They produce pass/fail
results based on documented performance thresholds.

Run:
    uv run pytest loadtests/test_benchmarks.py -v -s

The tests use FastAPI's TestClient, so no running server is needed.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tradearena.api.main import app
from tradearena.core.commitment import build_committed_signal
from tradearena.core.scoring import compute_score
from tradearena.db.database import (
    Base,
    BattleORM,
    CreatorORM,
    CreatorScoreORM,
    SignalORM,
    get_db,
)

# ---------------------------------------------------------------------------
# Performance thresholds (milliseconds unless noted)
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "signal_submit_p95_ms": 500,
    "leaderboard_p95_ms": 200,
    "leaderboard_division_p95_ms": 200,
    "battle_create_p95_ms": 300,
    "battle_list_active_p95_ms": 150,
    "battle_history_p95_ms": 200,
    "health_check_p95_ms": 50,
    "concurrent_signals_total_s": 10,  # 20 concurrent signals within 10s
    "concurrent_leaderboard_total_s": 5,  # 50 concurrent reads within 5s
}

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

NUM_CREATORS = 20
SIGNALS_PER_CREATOR = 10


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_creators_and_signals():
    """Seed test creators with resolved signals and scores."""
    db = TestingSessionLocal()
    now = datetime.now(UTC)
    outcomes = ["WIN", "LOSS", "NEUTRAL"]
    divisions = ["crypto", "polymarket", "multi"]
    assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    actions = ["buy", "sell", "long", "short"]

    creators = []
    for i in range(NUM_CREATORS):
        creator_id = f"bench-creator-{i:04d}"
        api_key = f"ta-bench-{i:04d}-{'b' * 24}"
        creator = CreatorORM(
            id=creator_id,
            display_name=f"Benchmark Bot {i}",
            division=divisions[i % len(divisions)],
            api_key_dev=api_key,
            created_at=now - timedelta(days=30),
        )
        db.add(creator)
        creators.append({"id": creator_id, "api_key": api_key})

        for j in range(SIGNALS_PER_CREATOR):
            reasoning = (
                "Benchmark signal with detailed technical analysis covering RSI divergence "
                "and volume confirmation across multiple timeframes showing clear momentum "
                "shift above the key resistance breakout level for performance testing."
            )
            raw = {
                "creator_id": creator_id,
                "asset": assets[j % len(assets)],
                "action": actions[j % len(actions)],
                "confidence": round(0.3 + (j % 6) * 0.1, 2),
                "reasoning": reasoning,
                "supporting_data": {"rsi": 55.0, "volume": "$10B"},
                "timeframe": "1h",
            }
            committed = build_committed_signal(raw)
            db.add(
                SignalORM(
                    signal_id=committed["signal_id"],
                    creator_id=creator_id,
                    asset=raw["asset"],
                    action=raw["action"],
                    confidence=raw["confidence"],
                    reasoning=reasoning,
                    supporting_data=raw["supporting_data"],
                    timeframe=raw["timeframe"],
                    commitment_hash=committed["commitment_hash"],
                    committed_at=now - timedelta(hours=48 + j),
                    outcome=outcomes[j % len(outcomes)],
                    outcome_price=round(40000 + j * 100, 2),
                    outcome_at=now - timedelta(hours=24 + j),
                )
            )

        db.flush()
        signal_outcomes = [outcomes[j % len(outcomes)] for j in range(SIGNALS_PER_CREATOR)]
        signal_confidences = [round(0.3 + (j % 6) * 0.1, 2) for j in range(SIGNALS_PER_CREATOR)]
        dims = compute_score(signal_outcomes, signal_confidences)
        db.add(
            CreatorScoreORM(
                creator_id=creator_id,
                win_rate=dims.win_rate,
                risk_adjusted_return=dims.risk_adjusted_return,
                consistency=dims.consistency,
                confidence_calibration=dims.confidence_calibration,
                composite_score=dims.composite,
                total_signals=SIGNALS_PER_CREATOR,
                updated_at=now,
            )
        )

    db.commit()
    db.close()
    return creators


def _clear_rate_limiters():
    """Reset in-memory rate limiter state between test runs."""
    from starlette.middleware.base import BaseHTTPMiddleware

    from tradearena.api.rate_limit import RateLimitMiddleware

    # Walk the middleware stack to find and reset rate limiter
    middleware = app.middleware_stack
    while middleware is not None:
        if isinstance(middleware, RateLimitMiddleware):
            middleware._hits.clear()
            middleware._key_hits.clear()
            middleware._auth_hits.clear()
            break
        middleware = getattr(middleware, "app", None)


@pytest.fixture(autouse=True, scope="module")
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    creators = _seed_creators_and_signals()
    yield creators
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Clear rate limiter state before each test."""
    _clear_rate_limiters()
    yield


@pytest.fixture(scope="module")
def creators(setup_db):
    return setup_db


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Return the pct-th percentile of a sorted list."""
    s = sorted(values)
    idx = int(len(s) * pct / 100)
    return s[min(idx, len(s) - 1)]


def _print_stats(name: str, latencies_ms: list[float]):
    p50 = _percentile(latencies_ms, 50)
    p95 = _percentile(latencies_ms, 95)
    p99 = _percentile(latencies_ms, 99)
    mean = statistics.mean(latencies_ms)
    print(f"\n  [{name}] n={len(latencies_ms)}")
    print(f"  mean={mean:.1f}ms  p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms")
    print(f"  min={min(latencies_ms):.1f}ms  max={max(latencies_ms):.1f}ms")
    return p95


def _make_signal_payload() -> dict:
    return {
        "asset": "BTC/USDT",
        "action": "buy",
        "confidence": 0.75,
        "reasoning": (
            "Technical analysis shows ascending triangle forming on the four-hour chart "
            "with RSI indicating bullish divergence and volume confirming the breakout "
            "above key resistance level at the current price zone."
        ),
        "supporting_data": {
            "rsi": 62.5,
            "volume_24h": "$15B",
            "trend": "bullish",
        },
        "timeframe": "4h",
    }


# ---------------------------------------------------------------------------
# Signal submission benchmarks
# ---------------------------------------------------------------------------


class TestSignalBenchmarks:
    """Measure signal submission latency and throughput."""

    def test_signal_submit_latency(self, client, creators):
        """Sequential signal submissions — measure per-request latency."""
        latencies = []
        # Use different creators to avoid rate limits
        for i in range(min(20, len(creators))):
            creator = creators[i]
            payload = _make_signal_payload()
            t0 = time.perf_counter()
            resp = client.post(
                "/signal",
                json=payload,
                headers={"X-API-Key": creator["api_key"]},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code in (201, 429), f"Unexpected {resp.status_code}: {resp.text}"
            if resp.status_code == 201:
                latencies.append(elapsed_ms)

        assert len(latencies) >= 10, f"Too few successful submissions: {len(latencies)}"
        p95 = _print_stats("signal-submit", latencies)
        assert p95 < THRESHOLDS["signal_submit_p95_ms"], (
            f"Signal submit p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['signal_submit_p95_ms']}ms)"
        )

    def test_concurrent_signal_submissions(self, client, creators):
        """20 sequential rapid signal submissions measuring total throughput.

        Uses sequential requests to avoid SQLite thread-safety issues in test mode.
        The locust suite tests true concurrency against a live server.
        """
        latencies = []
        ok_count = 0
        start = time.perf_counter()
        for i in range(20):
            creator = creators[i % len(creators)]
            payload = _make_signal_payload()
            t0 = time.perf_counter()
            resp = client.post(
                "/signal",
                json=payload,
                headers={"X-API-Key": creator["api_key"]},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code in (201, 429):
                ok_count += 1
            latencies.append(elapsed_ms)
        total = time.perf_counter() - start

        print(f"\n  [rapid-signals] 20 requests in {total:.2f}s")
        print(f"  Success/rate-limited: {ok_count}/20")
        assert total < THRESHOLDS["concurrent_signals_total_s"], (
            f"Rapid signals took {total:.1f}s (threshold: "
            f"{THRESHOLDS['concurrent_signals_total_s']}s)"
        )


# ---------------------------------------------------------------------------
# Leaderboard benchmarks
# ---------------------------------------------------------------------------


class TestLeaderboardBenchmarks:
    """Measure leaderboard query latency under load."""

    def test_leaderboard_latency(self, client):
        """50 sequential leaderboard reads."""
        latencies = []
        for i in range(50):
            limit = [10, 20, 50, 100][i % 4]
            t0 = time.perf_counter()
            resp = client.get(f"/leaderboard?limit={limit}&offset=0")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200
            latencies.append(elapsed_ms)

        p95 = _print_stats("leaderboard-global", latencies)
        assert p95 < THRESHOLDS["leaderboard_p95_ms"], (
            f"Leaderboard p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['leaderboard_p95_ms']}ms)"
        )

    def test_division_leaderboard_latency(self, client):
        """30 sequential division leaderboard reads."""
        divisions = ["crypto", "polymarket", "multi"]
        latencies = []
        for i in range(30):
            div = divisions[i % 3]
            t0 = time.perf_counter()
            resp = client.get(f"/leaderboard/{div}?limit=50")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200
            latencies.append(elapsed_ms)

        p95 = _print_stats("leaderboard-division", latencies)
        assert p95 < THRESHOLDS["leaderboard_division_p95_ms"], (
            f"Division leaderboard p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['leaderboard_division_p95_ms']}ms)"
        )

    def test_cursor_pagination_consistency(self, client):
        """Verify cursor pagination returns consistent, non-overlapping pages."""
        # Page 1
        resp1 = client.get("/leaderboard?limit=5")
        assert resp1.status_code == 200
        data1 = resp1.json()
        cursor = data1.get("next_cursor")
        ids_page1 = [e["creator_id"] for e in data1["entries"]]

        if cursor:
            # Page 2
            resp2 = client.get(f"/leaderboard?limit=5&cursor={cursor}")
            assert resp2.status_code == 200
            data2 = resp2.json()
            ids_page2 = [e["creator_id"] for e in data2["entries"]]

            overlap = set(ids_page1) & set(ids_page2)
            assert not overlap, f"Cursor pagination overlap: {overlap}"

    def test_concurrent_leaderboard_reads(self, client):
        """50 concurrent leaderboard reads."""
        import concurrent.futures

        def read_leaderboard(i):
            t0 = time.perf_counter()
            resp = client.get(f"/leaderboard?limit=50&offset={i * 5}")
            elapsed = time.perf_counter() - t0
            return resp.status_code, elapsed

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(read_leaderboard, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        total = time.perf_counter() - start

        ok = sum(1 for code, _ in results if code == 200)
        print(f"\n  [concurrent-leaderboard] 50 requests in {total:.2f}s ({ok}/50 OK)")
        assert total < THRESHOLDS["concurrent_leaderboard_total_s"], (
            f"Concurrent leaderboard took {total:.1f}s (threshold: "
            f"{THRESHOLDS['concurrent_leaderboard_total_s']}s)"
        )


# ---------------------------------------------------------------------------
# Battle benchmarks
# ---------------------------------------------------------------------------


class TestBattleBenchmarks:
    """Measure battle API latency and contention behavior."""

    def test_battle_create_latency(self, client, creators):
        """Create battles between different creator pairs."""
        latencies = []
        for i in range(0, min(20, len(creators)), 2):
            c1 = creators[i]["id"]
            c2 = creators[i + 1]["id"]
            t0 = time.perf_counter()
            resp = client.post(
                "/battle/create",
                json={"creator1_id": c1, "creator2_id": c2, "window_days": 3},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code in (201, 409), f"Unexpected {resp.status_code}: {resp.text}"
            latencies.append(elapsed_ms)

        p95 = _print_stats("battle-create", latencies)
        assert p95 < THRESHOLDS["battle_create_p95_ms"], (
            f"Battle create p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['battle_create_p95_ms']}ms)"
        )

    def test_active_battles_latency(self, client):
        """Query active battles list."""
        latencies = []
        for _ in range(30):
            t0 = time.perf_counter()
            resp = client.get("/battles/active")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 429:
                continue  # rate limited — skip this sample
            assert resp.status_code == 200
            latencies.append(elapsed_ms)

        assert len(latencies) >= 5, f"Too few successful requests: {len(latencies)}"
        p95 = _print_stats("battles-active", latencies)
        assert p95 < THRESHOLDS["battle_list_active_p95_ms"], (
            f"Active battles p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['battle_list_active_p95_ms']}ms)"
        )

    def test_battle_history_latency(self, client, creators):
        """Query battle history with filters."""
        latencies = []
        for i in range(20):
            creator = creators[i % len(creators)]
            t0 = time.perf_counter()
            resp = client.get(
                f"/battles/history?creator_id={creator['id']}&limit=20"
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 429:
                continue  # rate limited — skip this sample
            assert resp.status_code == 200
            latencies.append(elapsed_ms)

        assert len(latencies) >= 5, f"Too few successful requests: {len(latencies)}"
        p95 = _print_stats("battle-history", latencies)
        assert p95 < THRESHOLDS["battle_history_p95_ms"], (
            f"Battle history p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['battle_history_p95_ms']}ms)"
        )

    def test_battle_resolve_under_contention(self, client, creators):
        """Create and resolve battles, measuring contention behavior."""
        # Get active battles and try to resolve one
        resp = client.get("/battles/active")
        if resp.status_code == 429:
            pytest.skip("Rate limited — cannot test battle resolution")
        assert resp.status_code == 200
        battles = resp.json().get("battles", [])

        if battles:
            battle_id = battles[0]["battle_id"]
            t0 = time.perf_counter()
            resp = client.post(f"/battle/{battle_id}/resolve")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            # 200, 409 (already resolved), or 422 (not enough signals) are all valid
            assert resp.status_code in (200, 409, 422), (
                f"Unexpected {resp.status_code}: {resp.text}"
            )
            print(f"\n  [battle-resolve] {elapsed_ms:.1f}ms (status={resp.status_code})")


# ---------------------------------------------------------------------------
# Health check baseline
# ---------------------------------------------------------------------------


class TestHealthBenchmark:
    """Establish the health endpoint as a performance baseline."""

    def test_health_latency(self, client):
        """100 health checks — establishes baseline overhead."""
        latencies = []
        for _ in range(100):
            t0 = time.perf_counter()
            resp = client.get("/health")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200
            latencies.append(elapsed_ms)

        p95 = _print_stats("health", latencies)
        assert p95 < THRESHOLDS["health_check_p95_ms"], (
            f"Health check p95 ({p95:.1f}ms) exceeds threshold "
            f"({THRESHOLDS['health_check_p95_ms']}ms)"
        )
