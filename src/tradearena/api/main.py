"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tradearena.api.routes import battles, creators, leaderboard, oracle, signals
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

ORACLE_INTERVAL_SECONDS = 300  # 5 minutes
MATCHMAKING_INTERVAL_SECONDS = 7 * 24 * 3600  # 1 week
BOT_INTERVAL_SECONDS = 3600  # 1 hour

# Track last run times (in-memory, resets on restart)
_last_matchmaking: float = 0.0
_last_bot_run: float = 0.0


def _recompute_scores(db, creator_ids):
    """Recompute CreatorScoreORM for a set of creator IDs."""
    from datetime import UTC, datetime

    from tradearena.core.scoring import compute_score

    now = datetime.now(UTC)
    for cid in creator_ids:
        sigs = db.query(SignalORM).filter(SignalORM.creator_id == cid).all()
        dims = compute_score(
            [s.outcome for s in sigs],
            [s.confidence for s in sigs],
        )
        existing = db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == cid).first()
        if existing:
            existing.win_rate = dims.win_rate
            existing.risk_adjusted_return = dims.risk_adjusted_return
            existing.consistency = dims.consistency
            existing.confidence_calibration = dims.confidence_calibration
            existing.composite_score = dims.composite
            existing.total_signals = len(sigs)
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

                # 2. Recompute scores for all creators with signals
                creator_ids = {
                    s.creator_id
                    for s in db.query(SignalORM).filter(SignalORM.outcome.isnot(None)).all()
                }
                if creator_ids:
                    _recompute_scores(db, creator_ids)

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

                # 4. Weekly matchmaking
                if time.time() - _last_matchmaking >= MATCHMAKING_INTERVAL_SECONDS:
                    new_battles = run_matchmaking(db)
                    _last_matchmaking = time.time()
                    if new_battles:
                        logger.info("Matchmaking created %d battles", len(new_battles))

                # 5. Hourly bot signal generation
                if time.time() - _last_bot_run >= BOT_INTERVAL_SECONDS:
                    n = run_bot_signals(db)
                    _last_bot_run = time.time()
                    if n:
                        logger.info("Bots submitted %d new signals", n)

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


app = FastAPI(
    title="TradeArena",
    description="Trustless trading signal competition platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router, tags=["signals"])
app.include_router(leaderboard.router, tags=["leaderboard"])
app.include_router(creators.router, tags=["creators"])
app.include_router(oracle.router)
app.include_router(battles.router)

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
async def arena_ui() -> FileResponse:
    """Serve the TradeArena arena UI."""
    return FileResponse(
        _ARENA_HTML,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
