"""In-memory sliding-window rate limiter middleware for FastAPI."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Defaults: 200 requests per 60-second window (global, per-IP)
DEFAULT_RATE = 200
DEFAULT_WINDOW = 60  # seconds

# Per-API-key limits (prevents individual key abuse across IPs)
KEY_RATE = 60
KEY_WINDOW = 60  # 60 requests per minute per key

# Tighter limits for auth endpoints (brute-force protection)
AUTH_RATE = 10
AUTH_WINDOW = 60  # 10 attempts per minute

# Per-creator signal submission limits
SIGNAL_RATE = 10
SIGNAL_WINDOW = 3600  # 10 signals per hour

_AUTH_PATHS = {"/auth/register", "/auth/login"}
_SKIP_PATHS = {"/ws", "/health"}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_api_key(raw_key: str) -> str:
    """Hash API key for use as rate-limit tracking key (never store raw keys)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _prune(hits: list[float], cutoff: float) -> None:
    while hits and hits[0] < cutoff:
        hits.pop(0)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by client IP and API key.

    Three layers:
    1. Per-IP global limit (200/min default) — catches broad abuse.
    2. Per-API-key limit (60/min default) — prevents individual key abuse.
    3. Auth endpoint limit (10/min per IP) — mitigates credential brute-forcing.

    Skips WebSocket and health checks.
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
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._key_hits: dict[str, list[float]] = defaultdict(list)
        self._auth_hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        ip = _client_ip(request)
        now = time.monotonic()

        # --- auth-specific rate limit (tighter) ---
        if request.url.path in _AUTH_PATHS and request.method == "POST":
            auth_hits = self._auth_hits[ip]
            _prune(auth_hits, now - self.auth_window)
            if len(auth_hits) >= self.auth_rate:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many auth attempts. Try again later."},
                    headers={"Retry-After": str(self.auth_window)},
                )
            auth_hits.append(now)

        # --- per-API-key rate limit ---
        api_key = request.headers.get("x-api-key")
        key_remaining = None
        if api_key:
            key_id = _hash_api_key(api_key)
            key_hits = self._key_hits[key_id]
            _prune(key_hits, now - self.key_window)
            if len(key_hits) >= self.key_rate:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "API key rate limit exceeded. Try again later."},
                    headers={
                        "Retry-After": str(self.key_window),
                        "X-RateLimit-Key-Limit": str(self.key_rate),
                        "X-RateLimit-Key-Remaining": "0",
                    },
                )
            key_hits.append(now)
            key_remaining = max(0, self.key_rate - len(key_hits))

        # --- global per-IP rate limit ---
        hits = self._hits[ip]
        _prune(hits, now - self.window)
        if len(hits) >= self.rate:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(self.window)},
            )

        hits.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rate)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.rate - len(hits)))
        if key_remaining is not None:
            response.headers["X-RateLimit-Key-Limit"] = str(self.key_rate)
            response.headers["X-RateLimit-Key-Remaining"] = str(key_remaining)
        return response


class SignalRateLimiter:
    """Per-creator sliding-window rate limiter for signal submissions.

    Keyed by creator_id (resolved after auth), not IP. This prevents a single
    creator from flooding the append-only signal store.
    """

    def __init__(
        self,
        rate: int = SIGNAL_RATE,
        window: int = SIGNAL_WINDOW,
    ):
        self.rate = rate
        self.window = window
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, creator_id: str) -> None:
        """Raise HTTP 429 if the creator has exceeded the signal submission limit."""
        now = time.monotonic()
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
        """Return remaining quota per creator (for debugging/monitoring)."""
        now = time.monotonic()
        result = {}
        for cid, hits in self._hits.items():
            _prune(hits, now - self.window)
            result[cid] = max(0, self.rate - len(hits))
        return result


# Module-level singleton so all requests share the same window state.
signal_rate_limiter = SignalRateLimiter()
