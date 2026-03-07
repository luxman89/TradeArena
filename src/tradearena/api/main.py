"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from tradearena.api.routes import creators, leaderboard, signals
from tradearena.db.database import create_tables

# Resolve arena.html relative to this file's project root
# src/tradearena/api/main.py -> project root is 3 levels up -> scripts/arena.html
_ARENA_HTML = Path(__file__).resolve().parents[3] / "scripts" / "arena.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    create_tables()
    yield


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


@app.get("/", include_in_schema=False)
async def arena_ui() -> FileResponse:
    """Serve the TradeArena arena UI."""
    return FileResponse(_ARENA_HTML, media_type="text/html")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
