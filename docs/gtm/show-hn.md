# Show HN Post

**Title:** Show HN: TradeArena – Open-source competitive arena for trading bots with cryptographic signal commitment

**URL:** https://tradearena.duckdns.org

---

TradeArena is an open-source platform where trading bots submit predictions that are cryptographically committed and scored on a live leaderboard.

Each signal (buy/sell/long/short + confidence + reasoning) gets SHA-256 hashed at submission time with a nonce, creating a tamper-proof record. Signals are append-only — no edits, no deletes.

Scoring is multi-dimensional: win rate, risk-adjusted return, consistency, and confidence calibration. A bot that says "80% confident" and is right ~80% of the time scores higher than one that always says 90% and gets it wrong half the time.

The frontend is an interactive NYSE-style trading floor built with Phaser 3 where you can watch bots compete in real time.

Stack: Python (FastAPI + SQLAlchemy), Phaser 3 for the visual floor, SQLite for dev / Postgres for prod. CLI + Python SDK for bot integration.

```bash
pip install tradearena
tradearena init --api-key ta-your-key
tradearena submit --asset BTC/USDT --action buy --confidence 0.8 \
  --reasoning "your analysis" --data rsi=72.5 --data volume=1.2B
```

Repo: https://github.com/luxman89/TradeArena

Would love feedback on the scoring model and what other dimensions you'd want to see.
