"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from tradearena.api.rate_limit import RateLimitMiddleware
from tradearena.api.routes import (
    admin,
    auth,
    battles,
    creators,
    export,
    leaderboard,
    oracle,
    signals,
    tournaments,
)
from tradearena.api.ws import PING_INTERVAL_SECONDS, manager
from tradearena.db.database import (
    BattleORM,
    CreatorScoreORM,
    SessionLocal,
    SignalORM,
    create_tables,
)

logger = logging.getLogger(__name__)

# Resolve arena.html relative to this file's project root
# src/tradearena/api/main.py -> project root is 3 levels up -> scripts/arena.html
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_ARENA_HTML = _SCRIPTS_DIR / "arena.html"
_LANDING_HTML = _SCRIPTS_DIR / "landing.html"
_ADMIN_HTML = _SCRIPTS_DIR / "admin.html"
_QUICKSTART_HTML = _SCRIPTS_DIR / "quickstart.html"
_DEV_GUIDE_HTML = _SCRIPTS_DIR / "developer-guide.html"
_LEADERBOARD_HTML = _SCRIPTS_DIR / "leaderboard.html"

ORACLE_INTERVAL_SECONDS = 300  # 5 minutes
MATCHMAKING_INTERVAL_SECONDS = 7 * 24 * 3600  # 1 week
BOT_INTERVAL_SECONDS = 3600  # 1 hour

# Track last run times (in-memory, resets on restart)
_last_matchmaking: float = 0.0
_last_bot_run: float = 0.0


def _recompute_scores(db, creator_ids):
    """Recompute CreatorScoreORM for a set of creator IDs."""
    from datetime import UTC, datetime

    from tradearena.core.leveling import XP_SIGNAL_SUBMITTED, level_from_xp, xp_for_outcome
    from tradearena.core.scoring import compute_score

    now = datetime.now(UTC)
    for cid in creator_ids:
        sigs = db.query(SignalORM).filter(SignalORM.creator_id == cid).all()
        dims = compute_score(
            [s.outcome for s in sigs],
            [s.confidence for s in sigs],
        )
        # XP: base per signal + bonus per resolved outcome
        xp = len(sigs) * XP_SIGNAL_SUBMITTED
        for s in sigs:
            xp += xp_for_outcome(s.outcome)
        level = level_from_xp(xp)

        existing = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == cid).first()
        if existing:
            existing.win_rate = dims.win_rate
            existing.risk_adjusted_return = dims.risk_adjusted_return
            existing.consistency = dims.consistency
            existing.confidence_calibration = dims.confidence_calibration
            existing.composite_score = dims.composite
            existing.total_signals = len(sigs)
            existing.xp = max(existing.xp, xp)  # never decrease
            existing.level = level_from_xp(existing.xp)
            existing.updated_at = now
        else:
            db.add(
                CreatorScoreORM(
                    creator_id=cid,
                    win_rate=dims.win_rate,
                    risk_adjusted_return=dims.risk_adjusted_return,
                    consistency=dims.consistency,
                    confidence_calibration=dims.confidence_calibration,
                    composite_score=dims.composite,
                    total_signals=len(sigs),
                    xp=xp,
                    level=level,
                    updated_at=now,
                )
            )
    db.commit()


async def _background_loop():
    """Background loop: oracle resolution, score recompute, battle resolution, matchmaking, bots."""
    import time

    from tradearena.core.battle_resolver import resolve_battle
    from tradearena.core.bots import run_bot_signals
    from tradearena.core.matchmaker import run_matchmaking
    from tradearena.core.metrics import collector
    from tradearena.core.oracle import resolve_pending_signals

    global _last_matchmaking, _last_bot_run  # noqa: PLW0603

    while True:
        await asyncio.sleep(ORACLE_INTERVAL_SECONDS)
        collector.record_loop_iteration()
        try:
            db = SessionLocal()
            try:
                # 1. Resolve pending signals (oracle)
                t0 = time.monotonic()
                stats = await resolve_pending_signals(db)
                duration_ms = (time.monotonic() - t0) * 1000
                collector.record_resolver_run(
                    resolved=stats["resolved"],
                    errors=stats["errors"],
                    skipped=stats["skipped"],
                    duration_ms=duration_ms,
                )
                if stats["resolved"] > 0:
                    logger.info("Oracle resolved %d signals", stats["resolved"])
                    await manager.broadcast("signals_resolved", stats)

                # 2. Recompute scores for all creators with signals
                creator_ids = {
                    s.creator_id
                    for s in db.query(SignalORM).filter(SignalORM.outcome.isnot(None)).all()
                }
                if creator_ids:
                    _recompute_scores(db, creator_ids)
                    await manager.broadcast("leaderboard_updated")

                # 3. Resolve active battles past their window
                from datetime import UTC, datetime, timedelta

                now = datetime.now(UTC)
                active_battles = db.query(BattleORM).filter(BattleORM.status == "ACTIVE").all()
                resolved_count = 0
                for battle in active_battles:
                    deadline = battle.created_at.replace(tzinfo=UTC) + timedelta(
                        days=battle.window_days
                    )
                    if now >= deadline:
                        result = resolve_battle(battle, db)
                        if result:
                            resolved_count += 1
                if resolved_count:
                    logger.info("Resolved %d battles", resolved_count)
                    await manager.broadcast("battles_resolved", {"count": resolved_count})

                # 4. Weekly matchmaking
                if time.time() - _last_matchmaking >= MATCHMAKING_INTERVAL_SECONDS:
                    new_battles = run_matchmaking(db)
                    _last_matchmaking = time.time()
                    if new_battles:
                        logger.info("Matchmaking created %d battles", len(new_battles))
                        await manager.broadcast("matchmaking_complete", {"count": len(new_battles)})

                # 5. Hourly bot signal generation
                if time.time() - _last_bot_run >= BOT_INTERVAL_SECONDS:
                    n = run_bot_signals(db)
                    _last_bot_run = time.time()
                    if n:
                        logger.info("Bots submitted %d new signals", n)
                        await manager.broadcast("bots_submitted", {"count": n})

            finally:
                db.close()
        except Exception as exc:
            collector.record_error("background_loop", str(exc))
            logger.exception("Background loop error")


async def _ws_ping_loop():
    """Periodically ping all WebSocket clients and clean up stale connections."""
    while True:
        await asyncio.sleep(PING_INTERVAL_SECONDS)
        try:
            await manager.ping_all()
        except Exception:
            logger.exception("WS ping loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup, register bots, launch background loop."""
    from tradearena.core.bots import ensure_bots_registered

    create_tables()
    db = SessionLocal()
    try:
        ensure_bots_registered(db)
    finally:
        db.close()
    task = asyncio.create_task(_background_loop())
    ping_task = asyncio.create_task(_ws_ping_loop())
    yield
    task.cancel()
    ping_task.cancel()


_OPENAPI_TAGS = [
    {"name": "auth", "description": "Registration, login, profile, and avatar management"},
    {"name": "signals", "description": "Submit and query committed trading signals"},
    {"name": "leaderboard", "description": "Global and per-division leaderboard rankings"},
    {"name": "creators", "description": "Creator profiles and signal history"},
    {"name": "battles", "description": "Head-to-head creator battles"},
    {"name": "tournaments", "description": "Bracket-style tournament system"},
    {"name": "oracle", "description": "Signal outcome resolution and status"},
    {"name": "meta", "description": "Health checks and service metadata"},
]

_APP_DESCRIPTION = """\
Trustless trading signal competition platform. Traders submit cryptographically
committed predictions scored across four dimensions.

## Quick Start

**1. Register** — create an account and get your API key:

```bash
curl -X POST /auth/register \\
  -H "Content-Type: application/json" \\
  -d '{"email":"you@example.com","password":"securepass123",
       "display_name":"AlphaTrader","division":"crypto",
       "strategy_description":"Momentum-based strategy using RSI and volume analysis"}'
```

**2. Submit a signal** — commit a trading prediction:

```bash
curl -X POST /signal \\
  -H "X-API-Key: ta-your-api-key-here" \\
  -H "Content-Type: application/json" \\
  -d '{"asset":"BTCUSDT","action":"long","confidence":0.75,
       "reasoning":"BTC breakout above 50-day MA on high volume...(20+ words)",
       "supporting_data":{"rsi_14":62.3,"volume_change":"+45%"},
       "target_price":72000,"stop_loss":65000,"timeframe":"1d"}'
```

**3. Check the leaderboard** — see how you rank:

```bash
curl /leaderboard
```

## Python SDK

```python
from sdk.client import TradeArenaClient

client = TradeArenaClient(api_key="ta-...", base_url="https://tradearena.app")

# Validate locally before submitting
errors = client.validate({
    "asset": "BTCUSDT", "action": "long", "confidence": 0.75,
    "reasoning": "Strong breakout above resistance with volume confirmation...",
    "supporting_data": {"rsi_14": 62.3, "volume": "+45%"},
})

# Submit the signal
result = client.emit({
    "asset": "BTCUSDT", "action": "long", "confidence": 0.75,
    "reasoning": "Strong breakout above resistance with volume confirmation...",
    "supporting_data": {"rsi_14": 62.3, "volume": "+45%"},
    "target_price": 72000, "stop_loss": 65000, "timeframe": "1d",
})
print(result["signal_id"], result["commitment_hash"])
```

## Scoring System

Every creator is scored across four dimensions, each normalised to [0, 1]:

| Dimension | Weight | Formula |
|---|---|---|
| **Win Rate** | 30% | `wins / resolved_signals` |
| **Risk-Adjusted Return** | 30% | Sharpe-like ratio: `sigmoid(mean_return / std_dev)` |
| **Consistency** | 25% | Stability of win-rate across 10-signal rolling windows |
| **Confidence Calibration** | 15% | Brier score: `1 - 2 * mean((confidence - outcome)²)` |

**Composite Score** = `0.30 × win_rate + 0.30 × risk_adjusted + 0.25 × consistency \
+ 0.15 × calibration`

Returns are modelled as: WIN → `+confidence`, LOSS → `−confidence`, NEUTRAL → `0`.

## Authentication

- **JWT Bearer** — for profile/avatar endpoints (`Authorization: Bearer <token>`)
- **API Key** — for signal submission (`X-API-Key: ta-...`)

API keys are SHA-256 hashed before storage. Never share your raw API key.

## Commitment System

Every signal is cryptographically committed using SHA-256. The commitment hash covers
all signal fields plus a server-generated nonce, making signals tamper-proof and
independently verifiable. Signals are **append-only** — no edits or deletes.

## Common Patterns

**Momentum Bot** — submit long signals when RSI crosses above 50 with increasing volume:
```python
signal = {
    "asset": "ETHUSDT", "action": "long", "confidence": 0.65,
    "reasoning": "ETH RSI crossed above 50 with 30% volume increase...",
    "supporting_data": {"rsi_14": 55.2, "volume_spike": True},
    "target_price": 4000, "stop_loss": 3600, "timeframe": "4h",
}
```

**Mean Reversion** — sell when price deviates significantly from moving average:
```python
signal = {
    "asset": "BTCUSDT", "action": "short", "confidence": 0.60,
    "reasoning": "BTC 15% above 200-day MA, historically mean-reverts...",
    "supporting_data": {"deviation_pct": 15.2, "ma_200": 58000},
    "target_price": 62000, "stop_loss": 72000, "timeframe": "1d",
}
```

## Error Codes

| Code | Meaning |
|---|---|
| 401 | Invalid credentials or missing/invalid API key |
| 403 | Avatar locked (requires higher level) |
| 404 | Resource not found (creator, battle, tournament) |
| 409 | Conflict (duplicate email, active battle exists) |
| 422 | Validation error (invalid input, insufficient signals) |
| 429 | Rate limit exceeded |

## WebSocket

Connect to `ws://host/ws` for real-time events. Pass `?last_seq=N` to replay
missed messages. Events: `signal_new`, `signals_resolved`, `leaderboard_updated`,
`battle_created`, `battle_resolved`, `matchmaking_complete`.

## Outcome Values

| Value | Meaning |
|---|---|
| `null` | Pending — not yet resolved |
| `WIN` | Target price reached within timeframe |
| `LOSS` | Stop-loss hit or moved against prediction |
| `NEUTRAL` | Neither target nor stop-loss reached |
"""

app = FastAPI(
    title="TradeArena",
    description=_APP_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

# ---------------------------------------------------------------------------
# CORS — restrict to explicit origins. Wildcard (*) only for local dev.
# Default: production domains. Set CORS_ORIGINS="*" only for local development.
# ---------------------------------------------------------------------------
_PRODUCTION_ORIGINS = [
    "https://tradearena.app",
    "https://www.tradearena.app",
]

_cors_env = os.getenv("CORS_ORIGINS", "").strip()
if _cors_env == "*":
    _cors_origins = ["*"]
    _cors_credentials = False  # credentials not allowed with wildcard
elif _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    _cors_credentials = True
else:
    _cors_origins = _PRODUCTION_ORIGINS
    _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    allow_credentials=_cors_credentials,
)

# ---------------------------------------------------------------------------
# HTTPS redirect — enabled when ENFORCE_HTTPS=1 (e.g. behind Fly/Railway proxy)
# ---------------------------------------------------------------------------
if os.getenv("ENFORCE_HTTPS", "").strip() == "1":

    class _HTTPSRedirectMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto == "http":
                url = request.url.replace(scheme="https")
                return RedirectResponse(url, status_code=301)
            return await call_next(request)

    app.add_middleware(_HTTPSRedirectMiddleware)


# ---------------------------------------------------------------------------
# Security headers (OWASP)
# ---------------------------------------------------------------------------
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if os.getenv("ENFORCE_HTTPS", "").strip() == "1":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(signals.router, tags=["signals"])
app.include_router(leaderboard.router, tags=["leaderboard"])
app.include_router(creators.router, tags=["creators"])
app.include_router(oracle.router)
app.include_router(battles.router)
app.include_router(tournaments.router)
app.include_router(export.router)

# Serve static assets (sprites, tilesets, etc.)
_ASSETS_DIR = _SCRIPTS_DIR / "assets"
if _ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")


_RULES_HTML = _SCRIPTS_DIR / "rules.html"


@app.get("/rules", include_in_schema=False)
async def rules_page() -> FileResponse:
    """Serve the TradeArena rules page."""
    return FileResponse(
        _RULES_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/", include_in_schema=False)
async def landing_page() -> FileResponse:
    """Serve the TradeArena landing page."""
    return FileResponse(
        _LANDING_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/arena", include_in_schema=False)
async def arena_ui() -> FileResponse:
    """Serve the TradeArena arena UI."""
    return FileResponse(
        _ARENA_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/developer-guide", include_in_schema=False)
async def developer_guide() -> FileResponse:
    """Serve the developer guide with API examples and quickstart."""
    return FileResponse(
        _DEV_GUIDE_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/quickstart", include_in_schema=False)
async def quickstart_page() -> FileResponse:
    """Serve the interactive quickstart tutorial (post-signup)."""
    return FileResponse(
        _QUICKSTART_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/admin/dashboard", include_in_schema=False)
async def admin_dashboard() -> FileResponse:
    """Serve the admin monitoring dashboard."""
    return FileResponse(
        _ADMIN_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/leaderboard-live", include_in_schema=False)
async def leaderboard_page() -> FileResponse:
    """Serve the public leaderboard page (no auth required)."""
    return FileResponse(
        _LEADERBOARD_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap() -> PlainTextResponse:
    """Serve sitemap.xml for search engines."""
    base = os.getenv("BASE_URL", "https://tradearena.app")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>{base}/arena</loc><changefreq>daily</changefreq><priority>0.8</priority></url>
  <url><loc>{base}/rules</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
  <url><loc>{base}/docs</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>
  <url><loc>{base}/developer-guide</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>
  <url><loc>{base}/leaderboard-live</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
</urlset>"""
    return PlainTextResponse(content=xml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Real-time event stream for the trading floor UI.

    Clients can pass ?last_seq=N to replay missed messages on reconnect.
    Any message from the client (including "pong") counts as activity
    for stale-connection detection.
    """
    last_seq = 0
    try:
        last_seq = int(ws.query_params.get("last_seq", "0"))
    except (TypeError, ValueError):
        pass
    await manager.connect(ws, last_seq=last_seq)
    try:
        while True:
            await ws.receive_text()
            manager.record_pong(ws)
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/health", tags=["meta"], summary="Health check")
async def health() -> dict:
    """Returns service health status and version."""
    return {"status": "ok", "version": "0.1.0"}
