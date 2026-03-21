"""Tests for per-creator signal rate limiting."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from tradearena.api.rate_limit import (
    SIGNAL_RATE,
    SIGNAL_WINDOW,
    SignalRateLimiter,
)


class TestSignalRateLimiter:
    def test_allows_requests_under_limit(self):
        limiter = SignalRateLimiter(rate=5, window=60)
        for _ in range(5):
            limiter.check("creator-a")  # should not raise

    def test_blocks_at_limit(self):
        limiter = SignalRateLimiter(rate=3, window=60)
        for _ in range(3):
            limiter.check("creator-a")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("creator-a")
        assert exc_info.value.status_code == 429
        assert "rate limit exceeded" in exc_info.value.detail.lower()

    def test_different_creators_independent(self):
        limiter = SignalRateLimiter(rate=2, window=60)
        limiter.check("creator-a")
        limiter.check("creator-a")
        # creator-a is at limit, but creator-b should be fine
        limiter.check("creator-b")

    def test_window_expiry_resets_count(self):
        limiter = SignalRateLimiter(rate=2, window=10)
        base = time.monotonic()
        with patch("tradearena.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = base
            limiter.check("creator-a")
            limiter.check("creator-a")

            # Still within window — should block
            mock_time.monotonic.return_value = base + 5
            with pytest.raises(HTTPException) as exc_info:
                limiter.check("creator-a")
            assert exc_info.value.status_code == 429

            # After window expires — should allow again
            mock_time.monotonic.return_value = base + 11
            limiter.check("creator-a")  # should not raise

    def test_retry_after_header(self):
        limiter = SignalRateLimiter(rate=1, window=3600)
        limiter.check("creator-a")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("creator-a")
        assert exc_info.value.headers["Retry-After"] == "3600"

    def test_error_message_includes_limits(self):
        limiter = SignalRateLimiter(rate=10, window=3600)
        for _ in range(10):
            limiter.check("creator-a")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("creator-a")
        assert "10 signals" in exc_info.value.detail
        assert "60 minute" in exc_info.value.detail

    def test_default_config(self):
        limiter = SignalRateLimiter()
        assert limiter.rate == SIGNAL_RATE == 10
        assert limiter.window == SIGNAL_WINDOW == 3600
