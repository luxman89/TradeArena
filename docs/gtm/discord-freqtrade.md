# Discord Post — Freqtrade Community

**Channel:** #general or #showcase

---

Hey everyone! Sharing a project that pairs nicely with Freqtrade bots.

**TradeArena** is an open-source competitive platform where trading bots submit predictions and get ranked on a live leaderboard. Every signal is cryptographically committed (SHA-256) — no editing or deleting after submission.

Your bot gets scored on:
- Win rate
- Risk-adjusted returns
- Consistency
- Confidence calibration

Think of it as a public proving ground for your strategy — without exposing the strategy itself. You submit the *what* (asset, direction, confidence), not the *how*.

**Getting started:**

```bash
pip install tradearena
tradearena init --api-key ta-your-key-here
tradearena submit --asset BTC/USDT --action buy --confidence 0.75 \
  --reasoning "your analysis here (20+ words)" \
  --data rsi=65 --data volume=high
```

Or use the Python SDK directly in your Freqtrade callbacks:

```python
from tradearena import TradeArenaClient

client = TradeArenaClient(api_key="ta-your-key", base_url="https://tradearena.duckdns.org")
result = client.emit({
    "asset": "BTC/USDT",
    "action": "buy",
    "confidence": 0.8,
    "reasoning": "RSI divergence on 4h with volume confirmation...",
    "supporting_data": {"rsi": 72.5, "volume_24h": "1.2B"}
})
```

Live leaderboard + interactive trading floor: https://tradearena.duckdns.org

The quickstart page walks through everything. Would love to see some Freqtrade bots on the leaderboard!
