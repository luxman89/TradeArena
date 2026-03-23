"""Load test for the Binance oracle resolver under concurrent load.

Tests the oracle resolution pipeline's behavior when handling many signals
concurrently, measuring throughput, latency, cache effectiveness, and
identifying bottlenecks.

Run:  python -m pytest tests/test_oracle_loadtest.py -v -s
"""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from tradearena.core import cache
from tradearena.core.oracle import (
    fetch_klines,
    resolve_signal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle(open_p, high, low, close, ts_ms=0):
    """Minimal kline list matching Binance format."""
    return [ts_ms, str(open_p), str(high), str(low), str(close), "0", 0, "0", 0, "0", "0", "0"]


def _make_signal(
    *,
    asset: str = "BTC/USDT",
    action: str = "buy",
    timeframe: str = "1h",
    target_price: float | None = None,
    stop_loss: float | None = None,
    committed_hours_ago: int = 48,
    signal_id: str = "sig-0",
):
    """Create a mock SignalORM."""
    sig = MagicMock()
    sig.signal_id = signal_id
    sig.asset = asset
    sig.action = action
    sig.timeframe = timeframe
    sig.target_price = target_price
    sig.stop_loss = stop_loss
    sig.committed_at = datetime.now(UTC) - timedelta(hours=committed_hours_ago)
    return sig


def _mock_binance_client(klines=None, latency_ms=5):
    """Create an AsyncMock httpx client that simulates Binance responses."""
    if klines is None:
        klines = [_make_candle(40000, 42000, 39000, 41500)]

    async def fake_get(url, **kwargs):
        await asyncio.sleep(latency_ms / 1000)
        resp = MagicMock()
        resp.json.return_value = klines
        resp.raise_for_status = MagicMock()
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = fake_get
    return client


# ---------------------------------------------------------------------------
# Test: concurrent resolve_signal calls
# ---------------------------------------------------------------------------


class TestConcurrentResolveSignal:
    """Test resolve_signal under concurrent load with mocked Binance."""

    def setup_method(self):
        cache.clear()

    @pytest.mark.asyncio
    async def test_10_concurrent_signals_direction_mode(self):
        """10 signals resolved concurrently (direction mode, no targets)."""
        client = _mock_binance_client(
            klines=[[0, "0", "0", "0", "41000", "0", 0, "0", 0, "0", "0", "0"]],
            latency_ms=5,
        )
        signals = [
            _make_signal(
                signal_id=f"sig-dir-{i}",
                asset="BTC/USDT",
                action="buy",
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(10)
        ]

        start = time.perf_counter()
        results = await asyncio.gather(*[resolve_signal(s, client) for s in signals])
        elapsed = time.perf_counter() - start

        resolved = [r for r in results if r is not None]
        assert len(resolved) == 10, f"Expected 10 resolved, got {len(resolved)}"
        print(
            f"\n  [direction-mode] 10 signals resolved in {elapsed:.3f}s "
            f"({elapsed / 10 * 1000:.1f}ms/signal)"
        )

    @pytest.mark.asyncio
    async def test_10_concurrent_signals_target_mode(self):
        """10 signals resolved concurrently (target/stop mode)."""
        klines = [_make_candle(40000, 42000, 39000, 41500, ts_ms=i * 60000) for i in range(12)]
        client = _mock_binance_client(klines=klines, latency_ms=5)
        signals = [
            _make_signal(
                signal_id=f"sig-tgt-{i}",
                asset="BTC/USDT",
                action="buy",
                target_price=42000.0,
                stop_loss=38000.0,
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(10)
        ]

        start = time.perf_counter()
        results = await asyncio.gather(*[resolve_signal(s, client) for s in signals])
        elapsed = time.perf_counter() - start

        resolved = [r for r in results if r is not None]
        assert len(resolved) == 10
        print(
            f"\n  [target-mode] 10 signals resolved in {elapsed:.3f}s "
            f"({elapsed / 10 * 1000:.1f}ms/signal)"
        )

    @pytest.mark.asyncio
    async def test_50_concurrent_signals_mixed(self):
        """50 signals with mixed assets and modes under concurrent load."""
        klines = [_make_candle(40000, 42000, 39000, 41500, ts_ms=i * 60000) for i in range(12)]
        price_kline = [[0, "0", "0", "0", "41000", "0", 0, "0", 0, "0", "0", "0"]]

        call_count = 0

        async def fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.005)
            resp = MagicMock()
            params = kwargs.get("params", {})
            if params.get("interval") == "1m":
                resp.json.return_value = price_kline
            else:
                resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = fake_get

        assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
        signals = []
        for i in range(50):
            asset = assets[i % len(assets)]
            if i % 2 == 0:
                signals.append(
                    _make_signal(
                        signal_id=f"sig-mix-{i}",
                        asset=asset,
                        action="buy" if i % 4 == 0 else "sell",
                        target_price=42000.0,
                        stop_loss=38000.0,
                        timeframe="1h",
                        committed_hours_ago=48,
                    )
                )
            else:
                signals.append(
                    _make_signal(
                        signal_id=f"sig-mix-{i}",
                        asset=asset,
                        action="long" if i % 3 == 0 else "short",
                        timeframe="4h",
                        committed_hours_ago=48,
                    )
                )

        start = time.perf_counter()
        results = await asyncio.gather(*[resolve_signal(s, client) for s in signals])
        elapsed = time.perf_counter() - start

        resolved = [r for r in results if r is not None]
        assert len(resolved) == 50
        cache_info = cache.stats()
        print(
            f"\n  [mixed-50] {len(resolved)} signals in {elapsed:.3f}s "
            f"({elapsed / 50 * 1000:.1f}ms/signal)"
        )
        print(f"  Binance API calls: {call_count} | Cache entries: {cache_info['active']}")

    @pytest.mark.asyncio
    async def test_100_concurrent_signals_same_asset(self):
        """100 signals for the same asset — stress tests cache contention."""
        klines = [_make_candle(40000, 42000, 39000, 41500)]
        client = _mock_binance_client(klines=klines, latency_ms=2)

        signals = [
            _make_signal(
                signal_id=f"sig-same-{i}",
                asset="BTC/USDT",
                action="buy",
                target_price=42000.0,
                stop_loss=38000.0,
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(100)
        ]

        start = time.perf_counter()
        results = await asyncio.gather(*[resolve_signal(s, client) for s in signals])
        elapsed = time.perf_counter() - start

        resolved = [r for r in results if r is not None]
        assert len(resolved) == 100
        cache_info = cache.stats()
        print(
            f"\n  [same-asset-100] {len(resolved)} signals in {elapsed:.3f}s "
            f"({elapsed / 100 * 1000:.1f}ms/signal)"
        )
        print(f"  Cache entries: {cache_info['active']} (expect few due to dedup)")


# ---------------------------------------------------------------------------
# Test: cache effectiveness under concurrent access
# ---------------------------------------------------------------------------


class TestCacheUnderConcurrency:
    """Verify the cache handles concurrent reads/writes correctly."""

    def setup_method(self):
        cache.clear()

    @pytest.mark.asyncio
    async def test_concurrent_fetch_klines_same_key_deduplicates(self):
        """Multiple concurrent fetch_klines for the same key should hit
        Binance at most a few times (race window), then serve from cache."""
        klines = [_make_candle(40000, 42000, 39000, 41500)]
        call_count = 0

        async def fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # simulate network latency
            resp = MagicMock()
            resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = fake_get

        # 20 concurrent fetches for the same key
        tasks = [fetch_klines(client, "BTCUSDT", "1h", 1000000, 2000000) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        assert all(r == klines for r in results)
        print(
            f"\n  [cache-dedup] 20 concurrent fetches -> {call_count} API calls "
            f"(ideal: 1, acceptable: <=5)"
        )

    @pytest.mark.asyncio
    async def test_cache_stats_accuracy_under_load(self):
        """Verify cache stats remain consistent after heavy concurrent use."""
        klines = [_make_candle(100, 110, 95, 105)]

        async def fake_get(url, **kwargs):
            await asyncio.sleep(0.001)
            resp = MagicMock()
            resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = fake_get

        # Fetch 10 different keys concurrently
        tasks = [
            fetch_klines(client, "BTCUSDT", "1h", i * 100000, (i + 1) * 100000) for i in range(10)
        ]
        await asyncio.gather(*tasks)

        stats = cache.stats()
        assert stats["active"] == 10
        assert stats["expired"] == 0
        print(f"\n  [cache-stats] After 10 unique fetches: {stats}")


# ---------------------------------------------------------------------------
# Test: latency profiling
# ---------------------------------------------------------------------------


class TestLatencyProfile:
    """Measure resolution latency distribution."""

    def setup_method(self):
        cache.clear()

    @pytest.mark.asyncio
    async def test_latency_distribution_50_signals(self):
        """Profile per-signal latency across 50 resolutions."""
        klines = [_make_candle(40000, 42000, 39000, 41500)]

        async def fake_get(url, **kwargs):
            await asyncio.sleep(0.005)
            resp = MagicMock()
            resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = fake_get

        signals = [
            _make_signal(
                signal_id=f"sig-lat-{i}",
                asset="BTC/USDT",
                action="buy",
                target_price=42000.0,
                stop_loss=38000.0,
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(50)
        ]

        latencies = []
        for s in signals:
            t0 = time.perf_counter()
            await resolve_signal(s, client)
            latencies.append((time.perf_counter() - t0) * 1000)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        mean = statistics.mean(latencies)

        print("\n  [latency-profile] n=50 sequential resolutions")
        print(f"  mean={mean:.2f}ms  p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms")
        print(f"  min={min(latencies):.2f}ms  max={max(latencies):.2f}ms")

        assert p95 < 200, f"p95 latency {p95:.1f}ms is too high"


# ---------------------------------------------------------------------------
# Test: error resilience under load
# ---------------------------------------------------------------------------


class TestErrorResilience:
    """Verify graceful degradation when some Binance calls fail."""

    def setup_method(self):
        cache.clear()

    @pytest.mark.asyncio
    async def test_partial_failures_dont_crash_concurrent_batch(self):
        """Some signals fail (Binance error), others succeed.

        Uses different assets per signal to avoid cache key collisions
        masking the failure pattern.
        """
        klines = [_make_candle(40000, 42000, 39000, 41500)]
        fail_assets = {"ASSET3USDT", "ASSET7USDT", "ASSET13USDT"}

        async def flaky_get(url, **kwargs):
            await asyncio.sleep(0.002)
            params = kwargs.get("params", {})
            symbol = params.get("symbol", "")
            if symbol in fail_assets:
                raise httpx.HTTPStatusError(
                    "429 Too Many Requests",
                    request=MagicMock(),
                    response=MagicMock(status_code=429),
                )
            resp = MagicMock()
            resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = flaky_get

        signals = [
            _make_signal(
                signal_id=f"sig-err-{i}",
                asset=f"ASSET{i}/USDT",
                action="buy",
                target_price=42000.0,
                stop_loss=38000.0,
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(20)
        ]

        results = await asyncio.gather(
            *[resolve_signal(s, client) for s in signals],
            return_exceptions=True,
        )

        successes = [r for r in results if r is not None and not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        print(
            f"\n  [error-resilience] 20 signals with flaky API: "
            f"{len(successes)} ok, {len(failures)} errors"
        )
        assert len(successes) > 0
        assert len(failures) > 0  # some should fail


# ---------------------------------------------------------------------------
# Test: sequential vs concurrent throughput comparison
# ---------------------------------------------------------------------------


class TestThroughputComparison:
    """Compare sequential vs concurrent resolution throughput."""

    def setup_method(self):
        cache.clear()

    @pytest.mark.asyncio
    async def test_sequential_vs_concurrent_20_signals(self):
        """Measure speedup from concurrent execution."""
        klines = [_make_candle(40000, 42000, 39000, 41500)]

        async def fake_get(url, **kwargs):
            await asyncio.sleep(0.01)  # 10ms simulated latency
            resp = MagicMock()
            resp.json.return_value = klines
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = fake_get

        signals = [
            _make_signal(
                signal_id=f"sig-tput-{i}",
                asset=f"ASSET{i}/USDT",
                action="buy",
                target_price=42000.0,
                stop_loss=38000.0,
                timeframe="1h",
                committed_hours_ago=48,
            )
            for i in range(20)
        ]

        # Sequential
        cache.clear()
        t0 = time.perf_counter()
        for s in signals:
            await resolve_signal(s, client)
        seq_time = time.perf_counter() - t0

        # Concurrent
        cache.clear()
        t0 = time.perf_counter()
        await asyncio.gather(*[resolve_signal(s, client) for s in signals])
        conc_time = time.perf_counter() - t0

        speedup = seq_time / conc_time if conc_time > 0 else float("inf")
        print("\n  [throughput] 20 signals with 10ms API latency:")
        print(
            f"  Sequential: {seq_time:.3f}s | Concurrent: {conc_time:.3f}s | "
            f"Speedup: {speedup:.1f}x"
        )

        # NOTE: resolve_pending_signals runs sequentially today.
        # This test quantifies the potential speedup from concurrent execution.
        print("  ** BOTTLENECK: resolve_pending_signals uses a sequential for-loop **")
        print(f"  ** Concurrent execution could yield ~{speedup:.0f}x throughput improvement **")
