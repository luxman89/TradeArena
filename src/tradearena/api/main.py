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
    auth,
    battles,
    creators,
    leaderboard,
    oracle,
    signals,
    tournaments,
)
from tradearena.api.ws import manager
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
    from tradearena.core.oracle import resolve_pending_signals

    global _last_matchmaking, _last_bot_run  # noqa: PLW0603

    while True:
        await asyncio.sleep(ORACLE_INTERVAL_SECONDS)
        try:
            db = SessionLocal()
            try:
                # 1. Resolve pending signals (oracle)
                stats = await resolve_pending_signals(db)
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
        except Exception:
            logger.exception("Background loop error")


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
    yield
    task.cancel()


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

app = FastAPI(
    title="TradeArena",
    description=(
        "Trustless trading signal competition platform. "
        "Traders submit cryptographically committed predictions scored across "
        "four dimensions: Win Rate, Risk-Adjusted Return, Consistency, and "
        "Confidence Calibration."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)

# ---------------------------------------------------------------------------
# CORS — restrict origins in production, allow all in dev
# Set CORS_ORIGINS="https://tradearena.app,https://www.tradearena.app" in prod
# ---------------------------------------------------------------------------
_cors_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    allow_credentials=True,
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

app.include_router(auth.router)
app.include_router(signals.router, tags=["signals"])
app.include_router(leaderboard.router, tags=["leaderboard"])
app.include_router(creators.router, tags=["creators"])
app.include_router(oracle.router)
app.include_router(battles.router)
app.include_router(tournaments.router)

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
  <url><loc>{base}/leaderboard</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
</urlset>"""
    return PlainTextResponse(content=xml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Real-time event stream for the trading floor UI.

    Clients can pass ?last_seq=N to replay missed messages on reconnect.
    """
    last_seq = 0
    try:
        last_seq = int(ws.query_params.get("last_seq", "0"))
    except (TypeError, ValueError):
        pass
    await manager.connect(ws, last_seq=last_seq)
    try:
        while True:
            await ws.receive_text()  # keep alive; ignore client messages
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/health", tags=["meta"], summary="Health check")
async def health() -> dict:
    """Returns service health status and version."""
    return {"status": "ok", "version": "0.1.0"}
