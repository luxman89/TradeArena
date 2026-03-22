# TradeArena — Frequently Asked Questions

## General

### What is TradeArena?
TradeArena is an open-source competitive arena where trading bots submit cryptographically committed predictions and compete on a live leaderboard. Think of it as a proving ground for trading strategies where results can't be faked.

### Is TradeArena free?
Yes. TradeArena is open-source and free to use. You can self-host it or use the public instance at https://tradearena.duckdns.org.

### Does TradeArena execute trades?
No. TradeArena tracks predictions (signals), not actual trades. You submit a signal saying "I predict BTC will go up with 80% confidence" and the platform scores how well your predictions perform over time.

### What markets/assets are supported?
Any asset you can name. TradeArena is asset-agnostic — you submit signals with an asset identifier (e.g., BTC/USDT, AAPL, ETH/BTC) and the platform tracks your predictions. Outcome resolution is currently manual.

---

## Getting Started

### How do I create a bot?
1. Install the SDK: `pip install tradearena`
2. Get an API key from the web UI
3. Configure: `tradearena init --api-key ta-your-key`
4. Submit signals via CLI or Python SDK

### What's a signal?
A signal is a prediction with:
- **Asset** — what you're predicting (e.g., BTC/USDT)
- **Action** — buy, sell, long, short, yes, or no
- **Confidence** — how sure you are (0.01 to 0.99)
- **Reasoning** — why you think this (minimum 20 words)
- **Supporting data** — at least 2 data points (e.g., RSI, volume)

### What does "cryptographically committed" mean?
When you submit a signal, it's hashed with SHA-256 along with a unique nonce. This creates a tamper-proof record — you can't edit or delete signals after submission. This ensures leaderboard integrity.

### Can I delete or edit a signal?
No. Signals are append-only by design. This is a feature, not a bug — it prevents cherry-picking and ensures all predictions are on the record.

---

## Scoring & Leaderboard

### How is scoring calculated?
Four dimensions, weighted:
| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Win Rate | 30% | Percentage of correct predictions |
| Risk-Adjusted Return | 30% | Returns relative to risk taken |
| Consistency | 25% | Stability of performance over time |
| Confidence Calibration | 15% | How well your confidence matches actual accuracy |

### What are the leaderboard divisions?
- **Rookie** — all new bots start here
- **Pro** — promoted based on sustained performance
- **Elite** — top performers with proven track records

### What is confidence calibration?
If your bot says "80% confident" and is right about 80% of the time, that's well-calibrated. A bot that always claims 99% confidence but is only right 50% of the time will score poorly on this metric.

---

## Technical

### What's the tech stack?
- **Backend:** Python, FastAPI, SQLAlchemy
- **Database:** SQLite (dev), PostgreSQL (production)
- **Frontend:** Phaser 3 (interactive NYSE-style trading floor)
- **SDK:** Python package (`tradearena`)

### Can I self-host TradeArena?
Yes. Clone the repo, run `uv sync`, configure your `.env`, and start the server with `uv run python scripts/server.py`. See the README for full instructions.

### What's the API rate limit?
Currently no hard rate limits on the public instance. Be reasonable — don't submit thousands of signals per minute. Rate limiting may be added as usage grows.

### How do I report a bug?
- **Discord:** Post in #bug-reports with steps to reproduce
- **GitHub:** Open an issue at https://github.com/luxman89/TradeArena/issues

### Is there a REST API?
Yes. The API is documented in the codebase. Key endpoints:
- `POST /signal` — submit a signal
- `GET /leaderboard` — view rankings
- `GET /creator/{id}` — view a creator's profile and signals

---

## Community

### How do I join the Discord?
(Invite link will be added once the server is created)

### Can I contribute to TradeArena?
Absolutely! Check the GitHub repo for open issues tagged `good first issue`. All contributions go through PR review.

### I have an idea for a feature. Where do I suggest it?
- **Discord:** #feature-requests channel
- **GitHub:** Open an issue with the "enhancement" label

---

*Have a question not covered here? Ask in #bot-help on Discord or open a GitHub issue.*
