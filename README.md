# TradeArena

A signal-tracking platform where traders submit cryptographically committed predictions that are scored across five dimensions. Features an interactive NYSE trading floor UI built with Phaser 3.

## Features

- **Signal submission** — traders submit buy/sell/yes/no/long/short predictions with confidence levels and reasoning
- **Cryptographic commitment** — SHA-256 hash of signal fields + nonce for tamper-proof audit trail
- **Five-dimension scoring** — Win Rate (25%), Risk-Adjusted Return (25%), Reasoning Quality (20%), Consistency (20%), Confidence Calibration (10%)
- **Interactive trading floor** — Phaser 3 rendered NYSE-style environment with animated traders, leaderboard screens, battle mode, day/night cycle
- **Python SDK** — validate and submit signals programmatically, with optional Claude Haiku-powered reasoning generation
- **CLI tool** — `pip install tradearena` for terminal-based signal submission, status tracking, and battle viewing

## CLI Quickstart

```bash
# Install
pip install tradearena

# Configure with your API key
tradearena init --api-key ta-your-key-here

# Submit a signal
tradearena submit \
  --asset BTC/USDT \
  --action buy \
  --confidence 0.75 \
  --reasoning "Bitcoin showing strong momentum with RSI crossing above 70 on the 4h chart and increasing volume suggesting continued bullish pressure toward resistance levels" \
  --data rsi=72.5 \
  --data volume_change=+15%

# Check your scores and recent signals
tradearena status

# View active battles
tradearena battles
```

## Quick Start

```bash
# Install dependencies
uv sync

# Seed demo data (3 creators, 20 signals)
uv run python scripts/seed_demo.py

# Start dev server
uv run python scripts/server.py
```

Open [http://localhost:8000](http://localhost:8000) to see the trading floor.

## Project Structure

```
src/tradearena/
  api/          FastAPI app — routes, auth, static file serving
  core/         Validation, commitment hashing, scoring engine
  db/           SQLAlchemy ORM (SQLite dev, Postgres-compatible)
sdk/            Python SDK client
scripts/
  arena.html    Phaser 3 trading floor UI (single-file)
  assets/       Spritesheets, tilesets, phaser.min.js
  server.py     Dev server entry point
  seed_demo.py  Demo data seeder
tests/          Pytest test suite
```

## Development

```bash
# Run tests
uv run pytest tests/ -v --tb=short

# Lint + format
uv run ruff check src/ sdk/ tests/
uv run ruff format src/ sdk/ tests/
```

## Environment Variables

Set in `.env` (see `.env.example`):

| Variable | Purpose |
|---|---|
| `TRADEARENA_SECRET_KEY` | App secret key |
| `DATABASE_URL` | Database connection string |
| `ANTHROPIC_API_KEY` | For SDK reasoning generation |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/signal` | Submit a new signal |
| `GET` | `/leaderboard` | Get ranked creators |
| `GET` | `/creator/{id}` | Get creator profile |
| `GET` | `/creator/{id}/signals` | Get creator's signals |
| `GET` | `/` | Trading floor UI |

Auth via `X-API-Key` header (prefix `ta-`).
