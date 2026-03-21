"""Tests for per-API-key rate limiting in RateLimitMiddleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradearena.api.rate_limit import KEY_RATE, KEY_WINDOW, RateLimitMiddleware


def _make_app(key_rate: int = 5, key_window: int = 60, rate: int = 200) -> FastAPI:
    """Create a minimal FastAPI app with the rate limiter for testing."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, key_rate=key_rate, key_window=key_window, rate=rate)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.post("/signal")
    async def signal_endpoint():
        return {"submitted": True}

    return app


class TestPerApiKeyRateLimit:
    def test_allows_requests_under_limit(self):
        client = TestClient(_make_app(key_rate=5))
        for i in range(5):
            resp = client.get("/test", headers={"X-API-Key": "ta-abc123"})
            assert resp.status_code == 200
            assert resp.headers["X-RateLimit-Key-Limit"] == "5"
            assert resp.headers["X-RateLimit-Key-Remaining"] == str(4 - i)

    def test_blocks_at_limit(self):
        client = TestClient(_make_app(key_rate=3))
        for _ in range(3):
            resp = client.get("/test", headers={"X-API-Key": "ta-abc123"})
            assert resp.status_code == 200
        resp = client.get("/test", headers={"X-API-Key": "ta-abc123"})
        assert resp.status_code == 429
        assert "API key rate limit" in resp.json()["detail"]
        assert resp.headers["Retry-After"] == "60"
        assert resp.headers["X-RateLimit-Key-Remaining"] == "0"

    def test_different_keys_independent(self):
        client = TestClient(_make_app(key_rate=2))
        # Exhaust key A
        for _ in range(2):
            client.get("/test", headers={"X-API-Key": "ta-key-a"})
        resp = client.get("/test", headers={"X-API-Key": "ta-key-a"})
        assert resp.status_code == 429
        # Key B should still be fine
        resp = client.get("/test", headers={"X-API-Key": "ta-key-b"})
        assert resp.status_code == 200

    def test_no_key_skips_key_limit(self):
        client = TestClient(_make_app(key_rate=1))
        # Without API key header, per-key limit should not apply
        for _ in range(5):
            resp = client.get("/test")
            assert resp.status_code == 200
            assert "X-RateLimit-Key-Limit" not in resp.headers

    def test_key_limit_checked_before_global(self):
        """Per-key limit (3) is tighter than global (200), so key limit fires first."""
        client = TestClient(_make_app(key_rate=3, rate=200))
        for _ in range(3):
            client.get("/test", headers={"X-API-Key": "ta-tight"})
        resp = client.get("/test", headers={"X-API-Key": "ta-tight"})
        assert resp.status_code == 429
        assert "API key" in resp.json()["detail"]

    def test_global_limit_still_applies_with_key(self):
        """Even with a valid key, IP-based global limit is enforced."""
        client = TestClient(_make_app(key_rate=200, rate=3))
        for _ in range(3):
            resp = client.get("/test", headers={"X-API-Key": "ta-generous"})
            assert resp.status_code == 200
        resp = client.get("/test", headers={"X-API-Key": "ta-generous"})
        assert resp.status_code == 429
        # This should be the global limit message, not the key limit
        assert "Rate limit exceeded" in resp.json()["detail"]

    def test_same_key_different_endpoints(self):
        """Key rate limit counts across all endpoints for the same key."""
        client = TestClient(_make_app(key_rate=3))
        client.get("/test", headers={"X-API-Key": "ta-multi"})
        client.post("/signal", headers={"X-API-Key": "ta-multi"})
        client.get("/test", headers={"X-API-Key": "ta-multi"})
        resp = client.get("/test", headers={"X-API-Key": "ta-multi"})
        assert resp.status_code == 429

    def test_default_config(self):
        assert KEY_RATE == 60
        assert KEY_WINDOW == 60
