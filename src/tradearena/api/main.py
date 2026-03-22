"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from tradearena.api.rate_limit import RateLimitMiddleware
from tradearena.api.routes import (
    admin,
    auth,
    battles,
    creators,
    email,
    export,
    leaderboard,
    matchmaking,
    oracle,
    profiles,
    signals,
    tournaments,
    webhooks,
)
from tradearena.api.ws import PING_INTERVAL_SECONDS, manager
from tradearena.db.database import (
    BattleORM,
    CreatorORM,
    CreatorScoreORM,
    EmailEventORM,
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
_PROFILE_HTML = _SCRIPTS_DIR / "profile.html"

DRIP_EMAIL_INTERVAL_SECONDS = 600  # 10 minutes
ORACLE_INTERVAL_SECONDS = 300  # 5 minutes
MATCHMAKING_INTERVAL_SECONDS = 7 * 24 * 3600  # 1 week
BOT_INTERVAL_SECONDS = 3600  # 1 hour

# Track last run times (in-memory, resets on restart)
_last_matchmaking: float = 0.0
_last_bot_run: float = 0.0
_last_drip_run: float = 0.0


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


async def _process_drip_emails(db) -> None:
    """Send due onboarding drip emails to all eligible creators."""
    import secrets
    from datetime import UTC, datetime

    from tradearena.core.email import (
        get_due_emails,
        render_email,
        send_email,
    )

    now = datetime.now(UTC)
    creators = (
        db.query(CreatorORM)
        .filter(
            CreatorORM.email.isnot(None),
            CreatorORM.email_opted_out.is_(False),
            CreatorORM.unsubscribe_token.isnot(None),
        )
        .all()
    )

    for creator in creators:
        sent_steps = {
            ev.step
            for ev in db.query(EmailEventORM)
            .filter(
                EmailEventORM.creator_id == creator.id,
                EmailEventORM.status == "sent",
            )
            .all()
        }
        due = get_due_emails(creator.created_at, sent_steps, now)
        for step in due:
            event_id = secrets.token_hex(16)
            subject, plain, html = render_email(
                step, creator.display_name, creator.unsubscribe_token, event_id
            )
            success = await send_email(
                creator.email, subject, plain, html, creator.unsubscribe_token
            )
            ev = EmailEventORM(
                id=event_id,
                creator_id=creator.id,
                step=step.value,
                status="sent" if success else "failed",
                sent_at=now,
            )
            db.add(ev)
            db.commit()
            if success:
                logger.info("Drip email [%s] sent to %s", step.value, creator.id)


async def _background_loop():
    """Background loop: oracle resolution, score recompute, battle resolution, matchmaking, bots."""
    import time

    from tradearena.core.battle_resolver import resolve_battle
    from tradearena.core.bots import run_bot_signals
    from tradearena.core.matchmaker import run_matchmaking
    from tradearena.core.metrics import collector
    from tradearena.core.oracle import resolve_pending_signals
    from tradearena.core.webhooks import fire_webhook_for_creator

    global _last_matchmaking, _last_bot_run, _last_drip_run  # noqa: PLW0603

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

                    # Fire signal.resolved webhooks for each resolved signal
                    resolved_signals = (
                        db.query(SignalORM)
                        .filter(SignalORM.outcome.isnot(None), SignalORM.outcome != "NULL")
                        .order_by(SignalORM.outcome_at.desc())
                        .limit(stats["resolved"])
                        .all()
                    )
                    for sig in resolved_signals:
                        await fire_webhook_for_creator(
                            db,
                            sig.creator_id,
                            "signal.resolved",
                            {
                                "signal_id": sig.signal_id,
                                "asset": sig.asset,
                                "action": sig.action,
                                "outcome": sig.outcome,
                                "outcome_price": sig.outcome_price,
                                "confidence": sig.confidence,
                            },
                        )

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
                            # Fire battle.ended webhooks for both participants
                            battle_data = {
                                "battle_id": battle.battle_id,
                                "winner_id": battle.winner_id,
                                "creator1_id": battle.creator1_id,
                                "creator2_id": battle.creator2_id,
                                "creator1_score": battle.creator1_score,
                                "creator2_score": battle.creator2_score,
                                "margin": battle.margin,
                            }
                            await fire_webhook_for_creator(
                                db, battle.creator1_id, "battle.ended", battle_data
                            )
                            await fire_webhook_for_creator(
                                db, battle.creator2_id, "battle.ended", battle_data
                            )
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
                        # Fire matchmaking.matched webhooks
                        for mb in new_battles:
                            match_data = {
                                "battle_id": mb.battle_id,
                                "creator1_id": mb.creator1_id,
                                "creator2_id": mb.creator2_id,
                                "window_days": mb.window_days,
                            }
                            await fire_webhook_for_creator(
                                db, mb.creator1_id, "matchmaking.matched", match_data
                            )
                            await fire_webhook_for_creator(
                                db, mb.creator2_id, "matchmaking.matched", match_data
                            )

                # 5. Hourly bot signal generation
                if time.time() - _last_bot_run >= BOT_INTERVAL_SECONDS:
                    n = run_bot_signals(db)
                    _last_bot_run = time.time()
                    if n:
                        logger.info("Bots submitted %d new signals", n)
                        await manager.broadcast("bots_submitted", {"count": n})

                # 6. Drip email processing
                if time.time() - _last_drip_run >= DRIP_EMAIL_INTERVAL_SECONDS:
                    _last_drip_run = time.time()
                    await _process_drip_emails(db)

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

client = TradeArenaClient(api_key="ta-...", base_url="https://tradearena.duckdns.org")

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
    "https://tradearena.duckdns.org",
    "https://www.tradearena.duckdns.org",
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


# ---------------------------------------------------------------------------
# 5xx error rate tracking — logs and alerts on server error spikes
# ---------------------------------------------------------------------------
class _ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Track 5xx error rates and log alerts when they spike."""

    _window_seconds = 300  # 5-minute rolling window
    _alert_threshold = 10  # alert after 10 5xx errors in the window

    def __init__(self, app):
        super().__init__(app)
        self._errors: list[float] = []
        self._alerted = False

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        self._errors = [t for t in self._errors if t > cutoff]

    async def dispatch(self, request: Request, call_next):
        import time

        response = await call_next(request)
        if response.status_code >= 500:
            now = time.time()
            self._errors.append(now)
            self._prune(now)
            count = len(self._errors)
            logger.error(
                "5xx response: %s %s -> %d (count in window: %d)",
                request.method,
                request.url.path,
                response.status_code,
                count,
            )
            from tradearena.core.metrics import collector

            collector.record_error(
                "http_5xx",
                f"{request.method} {request.url.path} -> {response.status_code}",
            )
            if count >= self._alert_threshold and not self._alerted:
                logger.critical(
                    "ALERT: 5xx error rate spike — %d server errors in last %d seconds",
                    count,
                    self._window_seconds,
                )
                self._alerted = True
            elif count < self._alert_threshold:
                self._alerted = False
        return response


app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_ErrorTrackingMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(signals.router, tags=["signals"])
app.include_router(leaderboard.router, tags=["leaderboard"])
app.include_router(creators.router, tags=["creators"])
app.include_router(oracle.router)
app.include_router(battles.router)
app.include_router(tournaments.router)
app.include_router(profiles.router)
app.include_router(email.router)
app.include_router(export.router)
app.include_router(matchmaking.router)
app.include_router(webhooks.router)

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


@app.get("/register", include_in_schema=False)
async def register_redirect() -> RedirectResponse:
    """Redirect /register to the landing page (GitHub OAuth signup is on the homepage)."""
    return RedirectResponse(url="/", status_code=302)


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


@app.get("/profile/{username}", include_in_schema=False)
async def profile_page(username: str) -> HTMLResponse:
    """Serve the profile page with server-rendered OG meta tags for social sharing.

    Crawlers see proper og:title, og:description, og:image tags.
    Browsers get the full interactive profile page.
    """
    # Read the base template
    html = _PROFILE_HTML.read_text()

    # Try to inject OG tags for the specific user
    base_url = os.getenv("BASE_URL", "https://tradearena.duckdns.org")
    try:
        db = SessionLocal()
        try:
            creator = db.query(CreatorORM).filter(CreatorORM.id == username).first()
            if not creator:
                creator = (
                    db.query(CreatorORM).filter(CreatorORM.github_username == username).first()
                )
            if creator:
                score = creator.score
                composite = round(score.composite_score, 4) if score else 0.0
                win_rate = round((score.win_rate if score else 0.0) * 100, 1)
                total_signals = score.total_signals if score else 0
                level = score.level if score else 1

                og_title = f"{creator.display_name} — TradeArena"
                og_desc = (
                    f"Level {level} · Score {composite:.2f} · "
                    f"{win_rate}% win rate · {total_signals} signals"
                )
                og_image = f"{base_url}/api/v1/users/{creator.id}/og-image.png"
                profile_url = f"{base_url}/profile/{creator.id}"

                og_tags = (
                    f'<meta property="og:title" content="{og_title}">\n'
                    f'<meta property="og:description" content="{og_desc}">\n'
                    f'<meta property="og:image" content="{og_image}">\n'
                    f'<meta property="og:image:width" content="1200">\n'
                    f'<meta property="og:image:height" content="630">\n'
                    f'<meta property="og:url" content="{profile_url}">\n'
                    f'<meta name="twitter:title" content="{og_title}">\n'
                    f'<meta name="twitter:description" content="{og_desc}">\n'
                    f'<meta name="twitter:image" content="{og_image}">\n'
                    f'<meta name="description" content="{og_desc}">\n'
                )
                # Inject after the existing twitter:site meta tag
                html = html.replace(
                    '<meta name="twitter:site" content="@tradearena">',
                    '<meta name="twitter:site" content="@tradearena">\n' + og_tags,
                )
                html = html.replace(
                    '<title id="page-title">Creator Profile — TradeArena</title>',
                    f'<title id="page-title">{og_title}</title>',
                )
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to inject OG tags for profile/%s", username)

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap() -> PlainTextResponse:
    """Serve sitemap.xml for search engines."""
    base = os.getenv("BASE_URL", "https://tradearena.duckdns.org")
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
    """Returns service health status, version, and DB connectivity."""
    from importlib.metadata import version as pkg_version

    from sqlalchemy import text

    # Read version from installed package metadata (falls back to hardcoded)
    try:
        app_version = pkg_version("tradearena")
    except Exception:
        app_version = "0.1.0"

    # Verify database connectivity
    db_ok = False
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        finally:
            db.close()
    except Exception:
        logger.exception("Health check: DB connection failed")

    status_val = "ok" if db_ok else "degraded"
    response = {
        "status": status_val,
        "version": app_version,
        "checks": {
            "database": "connected" if db_ok else "unreachable",
        },
    }

    if not db_ok:
        from fastapi.responses import JSONResponse as _JSONResponse

        return _JSONResponse(content=response, status_code=503)

    return response
