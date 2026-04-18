"""Shared test fixtures."""

from __future__ import annotations

import importlib

import pytest

from tradearena.api.rate_limit import RateLimitMiddleware, _signup_hits, signal_rate_limiter

# Skip discord test files when discord.py is not installed (it's an optional dep)
collect_ignore_glob = []
if importlib.util.find_spec("discord") is None:
    collect_ignore_glob.append("test_discord_*.py")


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Clear all rate-limiter state before each test.

    The middleware and signal limiter are module-level singletons.  Without this
    fixture, running the full suite in one process causes later tests to hit
    429s from requests accumulated in earlier tests.
    """
    # Find the RateLimitMiddleware instance on the app
    from tradearena.api.main import app

    for mw in app.user_middleware:
        if mw.cls is RateLimitMiddleware:
            # Can't access the instance directly from user_middleware,
            # so we walk the middleware stack instead.
            break

    # Walk the ASGI middleware stack to find the live instance
    obj = app.middleware_stack
    while obj is not None:
        if isinstance(obj, RateLimitMiddleware):
            obj._hits.clear()
            obj._key_hits.clear()
            obj._auth_hits.clear()
            break
        obj = getattr(obj, "app", None)

    # Also reset the signal rate limiter singleton
    signal_rate_limiter._hits.clear()

    # Reset per-IP signup cap
    _signup_hits.clear()

    yield
