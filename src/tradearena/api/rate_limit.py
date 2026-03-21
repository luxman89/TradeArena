"""In-memory sliding-window rate limiter middleware for FastAPI."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Defaults: 200 requests per 60-second window (global)
DEFAULT_RATE = 200
DEFAULT_WINDOW = 60  # seconds

# Tighter limits for auth endpoints (brute-force protection)
AUTH_RATE = 10
AUTH_WINDOW = 60  # 10 attempts per minute

_AUTH_PATHS = {"/auth/register", "/auth/login"}
_SKIP_PATHS = {"/ws", "/health"}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(hits: list[float], cutoff: float) -> None:
    while hits and hits[0] < cutoff:
        hits.pop(0)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by client IP.

    Applies a tighter limit to auth endpoints (/auth/register, /auth/login)
    to mitigate credential brute-forcing. Skips WebSocket and health checks.
    """

    def __init__(
        self,
        app,
        rate: int = DEFAULT_RATE,
        window: int = DEFAULT_WINDOW,
        auth_rate: int = AUTH_RATE,
        auth_window: int = AUTH_WINDOW,
    ):
        super().__init__(app)
        self.rate = rate
        self.window = window
        self.auth_rate = auth_rate
        self.auth_window = auth_window
        self._hits: dict[str, list[float]] = defaultdict(list)
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

        # --- global rate limit ---
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
        return response
