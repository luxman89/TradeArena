"""In-memory TTL cache for Binance kline data.

Completed candles are immutable and cached indefinitely.
Current/recent candles use a short TTL (60s).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Cache storage: key -> (data, expires_at)
# expires_at = 0 means never expires
_cache: dict[str, tuple[object, float]] = {}

SHORT_TTL = 60.0  # seconds for current-candle data


def _make_key(symbol: str, interval: str, start_ms: int, end_ms: int) -> str:
    return f"{symbol}:{interval}:{start_ms}:{end_ms}"


def _is_historical(end_ms: int) -> bool:
    """Return True if the candle period has fully closed (end is in the past)."""
    now_ms = int(time.time() * 1000)
    # Consider historical if end_ms is more than 2 minutes in the past
    return end_ms < (now_ms - 120_000)


def get(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list] | None:
    """Look up cached kline data. Returns None on miss."""
    key = _make_key(symbol, interval, start_ms, end_ms)
    entry = _cache.get(key)
    if entry is None:
        logger.debug("Cache MISS: %s", key)
        return None

    data, expires_at = entry
    if expires_at and time.time() > expires_at:
        logger.debug("Cache EXPIRED: %s", key)
        del _cache[key]
        return None

    logger.debug("Cache HIT: %s", key)
    return data  # type: ignore[return-value]


def put(symbol: str, interval: str, start_ms: int, end_ms: int, data: list[list]) -> None:
    """Store kline data. Historical data is cached forever; recent data gets short TTL."""
    key = _make_key(symbol, interval, start_ms, end_ms)
    if _is_historical(end_ms):
        expires_at = 0.0  # never expires
        logger.debug("Cache PUT (permanent): %s", key)
    else:
        expires_at = time.time() + SHORT_TTL
        logger.debug("Cache PUT (TTL=%ss): %s", SHORT_TTL, key)
    _cache[key] = (data, expires_at)


def clear() -> None:
    """Clear all cached data. Useful for testing."""
    _cache.clear()


def stats() -> dict[str, int]:
    """Return cache size info."""
    now = time.time()
    total = len(_cache)
    expired = sum(1 for _, (__, exp) in _cache.items() if exp and now > exp)
    return {"total": total, "expired": expired, "active": total - expired}
