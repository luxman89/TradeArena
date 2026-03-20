"""Tests for the kline cache module."""

from __future__ import annotations

import time

from tradearena.core import cache


class TestCache:
    def setup_method(self):
        cache.clear()

    def test_miss_returns_none(self):
        assert cache.get("BTCUSDT", "1h", 1000, 2000) is None

    def test_put_and_get(self):
        data = [[0, "100", "110", "90", "105"]]
        cache.put("BTCUSDT", "1h", 1000, 2000, data)
        result = cache.get("BTCUSDT", "1h", 1000, 2000)
        assert result == data

    def test_different_keys_are_independent(self):
        data = [[0, "100", "110", "90", "105"]]
        cache.put("BTCUSDT", "1h", 1000, 2000, data)
        assert cache.get("ETHUSDT", "1h", 1000, 2000) is None
        assert cache.get("BTCUSDT", "5m", 1000, 2000) is None
        assert cache.get("BTCUSDT", "1h", 1000, 3000) is None

    def test_historical_data_never_expires(self):
        # end_ms far in the past -> permanent cache
        old_end = int(time.time() * 1000) - 300_000  # 5 min ago
        old_start = old_end - 3_600_000
        data = [[0, "100", "110", "90", "105"]]
        cache.put("BTCUSDT", "1h", old_start, old_end, data)
        assert cache.get("BTCUSDT", "1h", old_start, old_end) == data

    def test_recent_data_expires(self):
        # end_ms in the future -> short TTL
        future_end = int(time.time() * 1000) + 60_000
        start = future_end - 60_000
        data = [[0, "100", "110", "90", "105"]]
        cache.put("BTCUSDT", "1m", start, future_end, data)

        # Should be available immediately
        assert cache.get("BTCUSDT", "1m", start, future_end) == data

    def test_clear(self):
        data = [[0, "100", "110", "90", "105"]]
        cache.put("BTCUSDT", "1h", 1000, 2000, data)
        cache.clear()
        assert cache.get("BTCUSDT", "1h", 1000, 2000) is None

    def test_stats(self):
        cache.put("BTCUSDT", "1h", 1000, 2000, [])
        cache.put("ETHUSDT", "1h", 1000, 2000, [])
        s = cache.stats()
        assert s["total"] == 2
        assert s["active"] >= 2
