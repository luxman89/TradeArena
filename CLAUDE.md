# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/ -v --tb=short

# Run a single test file
uv run pytest tests/test_scoring.py -v

# Run a single test by name
uv run pytest tests/ -k "test_name" -v

# Lint
uv run ruff check src/ sdk/ tests/

# Format check / fix
uv run ruff format --check src/ sdk/ tests/
uv run ruff format src/ sdk/ tests/

# Start dev server
uv run python scripts/server.py

# Seed demo data (3 creators, 20 signals)
uv run python scripts/seed_demo.py
```

## Architecture

TradeArena is a signal-tracking platform where traders submit cryptographically committed predictions that are scored across five dimensions.

### Core pipeline: Signal submission flow

1. **SDK** (`sdk/client.py`) — validates locally, then POSTs to API. Also offers Claude Haiku-powered reasoning generation.
2. **API** (`src/tradearena/api/`) — FastAPI app. Auth via `X-API-Key` header resolved in `deps.py`. Routes: `/signal`, `/leaderboard`, `/creator/*`.
3. **Validation** (`src/tradearena/core/validation.py`) — shared between SDK and API (side-effect-free). Enforces: action enum (buy/sell/yes/no/long/short), confidence (0.01–0.99), reasoning ≥20 words, supporting_data ≥2 keys.
4. **Commitment** (`src/tradearena/core/commitment.py`) — SHA-256 hash of signal fields + nonce for tamper-proof audit trail. Generates signal_id (UUID4 hex) and committed_at timestamp.
5. **Storage** (`src/tradearena/db/database.py`) — SQLAlchemy ORM. Three tables: CreatorORM, SignalORM (append-only), CreatorScoreORM. SQLite for dev, Postgres-compatible.
6. **Scoring** (`src/tradearena/core/scoring.py`) — five-dimension composite: Win Rate (25%), Risk-Adjusted Return (25%), Reasoning Quality (20%), Consistency (20%), Confidence Calibration (10%). All normalized [0,1].

### Key conventions

- **Signal IDs**: UUID4 hex (32 chars). **Hashes**: SHA-256 hex (64 chars).
- **Creator IDs**: slug + "-" + 4 random hex (e.g., "alice-quantsworth-a1b2").
- **API keys**: "ta-" prefix + 32 hex chars; stored as SHA-256 hash in production, plaintext in dev seed.
- **Signals are append-only** — no UPDATE/DELETE by design.
- **Outcome values**: WIN, LOSS, NEUTRAL, or NULL (pending).
- **Leaderboard divisions**: rookie, pro, elite.

### Ruff config

Line length 100. Rules: E, F, I, UP. CI enforces both `ruff check` and `ruff format --check`.

### Environment variables

Set in `.env` (see `.env.example`): `TRADEARENA_SECRET_KEY`, `DATABASE_URL`, `ANTHROPIC_API_KEY`.

### Web UI

`scripts/arena.html` — NYSE trading floor themed UI served at root by FastAPI. Static assets in `scripts/assets/`.

**Rendering**: Phaser 3.60.0 (loaded from `/assets/phaser.min.js`). Single `GameScene` class handles all rendering.

- **Environment**: Phaser Graphics — `_buildTradingFloor()` draws charcoal floor, 7 desks (`_buildDesk()`), 3 NYSE-style circular trading posts (`_buildTradingPost()`)
- **Characters**: Spritesheet `char3` (64×64 frames, `FRAMES_PER_ROW=13`, `DIR_TO_ROW=[3,1,2,0]`). Sprites created lazily in `_createSprites()` with shadow, nametag, score bar, selection ring, focus ring, popup text
- **Animation**: Direct `setFrame()` per tick from agent state machine — no Phaser animation system
- **Interaction**: Phaser sprite `pointerdown` for selection, `pointerover/out` for DOM tooltip, background `pointerdown` for deselection/ripple/desk clicks
- **Effects**: Phaser-native particles (tweened rectangles), floating text (tweened Text objects), camera shake, signal glow (sprite tint)
- **Overlays**: Day/night rectangle (depth 999), vignette (depth 998), scanlines (depth 997)
- **Wall screens**: 3 leaderboard screens at top of room, updated via `gameScene.updateScreens(leaderboard)` on data refresh
- **Texture bridge**: `img['char3'] = textures.get('char3').getSourceImage()` — panel/battle canvases still use direct `drawImage()`
- **Scale**: `Phaser.Scale.FIT` + `CENTER_BOTH`. `resize()` adjusts container when panel toggles
- **Old canvas**: Dummy offscreen `canvas`/`ctx` kept for battle overlay and panel sprite drawing (`drawPanelSprite`)
