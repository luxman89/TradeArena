# TradeArena

A trustless trading signal competition platform. Creators emit cryptographically committed signals before market outcomes are known. Signals are scored across five dimensions and ranked on a public leaderboard.

## Quick Start

```bash
# Install dependencies
uv sync

# Copy env
cp .env.example .env

# Seed demo data
uv run python scripts/seed_demo.py

# Start server
uv run python scripts/server.py
```

## API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/signal` | API key | Emit a new committed signal |
| GET | `/leaderboard` | None | Global leaderboard |
| GET | `/leaderboard/{division}` | None | Division leaderboard |
| GET | `/creator/{id}` | None | Creator profile + score |
| GET | `/creator/{id}/signals` | None | Creator's signal history |

## Scoring Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Win Rate | 25% | Percentage of profitable signals |
| Risk-Adjusted Return | 25% | Sharpe-like ratio of returns |
| Reasoning Quality | 20% | NLP assessment of reasoning depth |
| Consistency | 20% | Stability across market conditions |
| Confidence Calibration | 10% | Accuracy of stated confidence |

## Signal Requirements

- `confidence`: 0.01–0.99 (never 0 or 1)
- `reasoning`: minimum 20 words
- `supporting_data`: minimum 2 keys
- `action`: one of `BUY`, `SELL`, `HOLD`, `SHORT`, `COVER`

## SDK Usage

```python
from sdk import TradeArenaClient

client = TradeArenaClient(api_key="your-key", base_url="http://localhost:8000")

# Validate locally (no network)
errors = client.validate(signal_data)

# Emit to server
result = client.emit(signal_data)
print(result["signal_id"], result["committed_at"])
```
