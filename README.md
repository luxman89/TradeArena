# TradeArena

> **Disclaimer.** TradeArena is a public skill competition for market predictions.
> Rankings and predictions are **not investment advice**, not a solicitation to trade,
> and not a forecast of future results. Creators submit predictions to be scored;
> nothing here should be acted upon as a trading recommendation.

A signal-tracking platform where traders submit cryptographically committed predictions that are scored across four dimensions. Features an interactive NYSE trading floor UI built with Phaser 3.

## Features

- **Signal submission** — traders submit buy/sell/yes/no/long/short predictions with confidence levels and reasoning
- **Verifiable commitment** — SHA-256 hash of signal fields plus a published nonce for an
  independently reproducible audit trail
- **Four-dimension scoring** — Win Rate (30%), Risk-Adjusted Return (30%), Consistency (25%), Confidence Calibration (15%)
- **Interactive trading floor** — Phaser 3 rendered NYSE-style environment with animated traders, leaderboard screens, battle mode, day/night cycle
- **Python SDK** — validate and submit signals programmatically, with optional Claude Haiku-powered reasoning generation

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

## CLI

Install and use the `tradearena` command:

```bash
pip install tradearena

# Configure your API key
tradearena init --api-key ta-your-key-here

# Submit a signal
tradearena submit \
  --asset BTC/USDT \
  --action buy \
  --confidence 0.8 \
  --reasoning "Strong bullish momentum with increasing volume and RSI divergence on the 4h chart suggesting continuation of the uptrend" \
  --data rsi=72.5 \
  --data volume_24h=1.2B

# Check your stats
tradearena status

# View active battles
tradearena battles
```

Run `tradearena --help` for all options.

## Development

```bash
# Run tests
uv run pytest tests/ -v --tb=short

# Lint + format
uv run ruff check src/ sdk/ tests/
uv run ruff format src/ sdk/ tests/
```

## Community

Join the TradeArena Discord: **https://discord.gg/Cjjtfj7qEb**

Connect with other traders, get help with the SDK, share strategies, and stay updated with the latest features.

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

### Verifying a signal commitment

New signal responses and signal-history exports include the server-generated `nonce`. To audit a
record, serialize the creator ID, signal fields, and nonce as canonical JSON (sorted keys with no
whitespace), then compare its SHA-256 digest with `commitment_hash`. The reference implementation
is `tradearena.core.commitment.verify_commitment`. Legacy records whose nonce is `null` predate
public verification and cannot be independently recomputed.

Target-based outcomes are also checked against exchange price data at the commitment timestamp.
For a bullish signal the stop must be below entry and the target above it; bearish signals require
the inverse. Signals with already-crossed or otherwise malformed levels are scored as losses rather
than receiving an immediate win.
