"""Rate limiter middleware — Redis-backed sliding window, in-memory fallback."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Defaults: 200 requests per 60-second window (global, per-IP)
DEFAULT_RATE = 200
DEFAULT_WINDOW = 60  # seconds

# Per-API-key limits
KEY_RATE = 60
KEY_WINDOW = 60  # 60 requests per minute per key

# Tighter limits for auth endpoints (brute-force protection)
AUTH_RATE = 10
AUTH_WINDOW = 60  # 10 attempts per minute

# Per-creator signal submission limits
SIGNAL_RATE = 10
SIGNAL_WINDOW = 3600  # 10 signals per hour

_AUTH_PATHS = {"/auth/register", "/auth/login", "/auth/github/callback"}
_SKIP_PATHS = {"/ws"}

# ---------------------------------------------------------------------------
# Redis backend — optional, with in-memory fallback
# ---------------------------------------------------------------------------

_redis_client = None
_redis_available = False


def _init_redis() -> None:
    global _redis_client, _redis_available  # noqa: PLW0603
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return
    try:
        import redis as _redis

        client = _redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("Rate limiter: Redis backend active (%s)", redis_url)
    except Exception as exc:
        logger.warning("Rate limiter: Redis unavailable (%s) — using in-memory fallback", exc)


_init_redis()


def _redis_check(key: str, rate: int, window: int, now: float) -> tuple[bool, int]:
    """Sliding-window check using Redis sorted set. Returns (allowed, remaining)."""
    cutoff = now - window
    pipe = _redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.expire(key, window + 1)
    results = pipe.execute()
    current_count: int = results[1]
    if current_count >= rate:
        return False, 0
    _redis_client.zadd(key, {f"{now}:{secrets.token_hex(4)}": now})
    return True, rate - current_count - 1


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _prune(hits: list[float], cutoff: float) -> None:
    while hits and hits[0] < cutoff:
        hits.pop(0)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter — Redis-backed when available, in-memory otherwise.

    Three layers:
    1. Per-IP global limit (200/min) — catches broad abuse.
    2. Per-API-key limit (60/min) — prevents individual key abuse.
    3. Auth endpoint limit (10/min per IP) — mitigates credential brute-forcing.
    """

    def __init__(
        self,
        app,
        rate: int = DEFAULT_RATE,
        window: int = DEFAULT_WINDOW,
        key_rate: int = KEY_RATE,
        key_window: int = KEY_WINDOW,
        auth_rate: int = AUTH_RATE,
        auth_window: int = AUTH_WINDOW,
    ):
        super().__init__(app)
        self.rate = rate
        self.window = window
        self.key_rate = key_rate
        self.key_window = key_window
        self.auth_rate = auth_rate
        self.auth_window = auth_window
        # In-memory fallback state
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._key_hits: dict[str, list[float]] = defaultdict(list)
        self._auth_hits: dict[str, list[float]] = defaultdict(list)

    def _check(
        self,
        namespace: str,
        key: str,
        rate: int,
        window: int,
        mem_store: dict[str, list[float]],
        now: float,
    ) -> tuple[bool, int]:
        """Check rate limit; returns (allowed, remaining)."""
        if _redis_available:
            try:
                return _redis_check(f"rl:{namespace}:{key}", rate, window, now)
            except Exception as exc:
                logger.warning("Redis rate-limit check failed (%s), using in-memory", exc)

        hits = mem_store[key]
        _prune(hits, now - window)
        if len(hits) >= rate:
            return False, 0
        hits.append(now)
        return True, rate - len(hits)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        ip = _client_ip(request)
        now = time.monotonic()

        # --- auth-specific rate limit ---
        if request.url.path in _AUTH_PATHS and request.method == "POST":
            allowed, _ = self._check(
                "auth", ip, self.auth_rate, self.auth_window, self._auth_hits, now
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many auth attempts. Try again later."},
                    headers={"Retry-After": str(self.auth_window)},
                )

        # --- per-API-key rate limit ---
        api_key = request.headers.get("x-api-key")
        key_remaining = None
        if api_key:
            key_id = _hash_api_key(api_key)
            allowed, key_remaining = self._check(
                "key", key_id, self.key_rate, self.key_window, self._key_hits, now
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "API key rate limit exceeded. Try again later."},
                    headers={
                        "Retry-After": str(self.key_window),
                        "X-RateLimit-Key-Limit": str(self.key_rate),
                        "X-RateLimit-Key-Remaining": "0",
                    },
                )

        # --- global per-IP rate limit ---
        allowed, remaining = self._check("ip", ip, self.rate, self.window, self._hits, now)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(self.window)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rate)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        if key_remaining is not None:
            response.headers["X-RateLimit-Key-Limit"] = str(self.key_rate)
            response.headers["X-RateLimit-Key-Remaining"] = str(key_remaining)
        return response


class SignalRateLimiter:
    """Per-creator sliding-window rate limiter for signal submissions."""

    def __init__(self, rate: int = SIGNAL_RATE, window: int = SIGNAL_WINDOW):
        self.rate = rate
        self.window = window
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, creator_id: str) -> None:
        now = time.monotonic()
        if _redis_available:
            try:
                allowed, _ = _redis_check(
                    f"rl:signal:{creator_id}", self.rate, self.window, now
                )
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            f"Signal rate limit exceeded: {self.rate} signals per "
                            f"{self.window // 60} minute(s). Try again later."
                        ),
                        headers={"Retry-After": str(self.window)},
                    )
                return
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Redis signal rate-limit check failed (%s), using in-memory", exc)

        hits = self._hits[creator_id]
        _prune(hits, now - self.window)
        if len(hits) >= self.rate:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Signal rate limit exceeded: {self.rate} signals per "
                    f"{self.window // 60} minute(s). Try again later."
                ),
                headers={"Retry-After": str(self.window)},
            )
        hits.append(now)

    @property
    def remaining(self) -> dict[str, int]:
        now = time.monotonic()
        result = {}
        for cid, hits in self._hits.items():
            _prune(hits, now - self.window)
            result[cid] = max(0, self.rate - len(hits))
        return result


# Module-level singleton so all requests share the same window state.
signal_rate_limiter = SignalRateLimiter()
