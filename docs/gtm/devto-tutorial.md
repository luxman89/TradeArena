# Dev.to Tutorial

**Title:** Build Your First Trading Bot on TradeArena in 5 Minutes
**Tags:** python, trading, opensource, tutorial

---

Trading bots are fun to build. Proving they actually work? That's the hard part.

[TradeArena](https://tradearena.duckdns.org) is an open-source platform where bots submit cryptographically committed predictions and compete on a live leaderboard. Every signal is SHA-256 hashed at submission time — no editing, no deleting, no faking results.

In this tutorial, you'll go from zero to your first ranked signal in under 5 minutes.

## Step 1: Install the CLI

```bash
pip install tradearena
```

## Step 2: Get your API key

Head to [tradearena.duckdns.org](https://tradearena.duckdns.org) and grab an API key, then configure the CLI:

```bash
tradearena init --api-key ta-your-key-here
```

## Step 3: Submit your first signal

```bash
tradearena submit \
  --asset BTC/USDT \
  --action buy \
  --confidence 0.8 \
  --reasoning "Strong bullish momentum with increasing volume and RSI divergence on the 4h chart suggesting continuation of the uptrend" \
  --data rsi=72.5 \
  --data volume_24h=1.2B
```

That's it. Your signal is now cryptographically committed and visible on the leaderboard.

## Step 4: Check your ranking

```bash
tradearena status
```

You'll see your scores across four dimensions:
- **Win Rate** (30%) — are your calls correct?
- **Risk-Adjusted Return** (30%) — are you making smart bets?
- **Consistency** (25%) — do you show up reliably?
- **Confidence Calibration** (15%) — when you say 80% confident, are you right ~80% of the time?

## Going further: Python SDK

For automated bots, use the SDK directly:

```python
from tradearena import TradeArenaClient

client = TradeArenaClient(
    api_key="ta-your-key-here",
    base_url="https://tradearena.duckdns.org"
)

# Validate locally before submitting
errors = client.validate({
    "asset": "ETH/USDT",
    "action": "sell",
    "confidence": 0.65,
    "reasoning": "Bearish head and shoulders forming on daily chart with declining volume and MACD crossover confirming the reversal pattern",
    "supporting_data": {
        "pattern": "head_and_shoulders",
        "macd_signal": "bearish_crossover"
    }
})

if not errors:
    result = client.emit({
        "asset": "ETH/USDT",
        "action": "sell",
        "confidence": 0.65,
        "reasoning": "Bearish head and shoulders forming on daily chart with declining volume and MACD crossover confirming the reversal pattern",
        "supporting_data": {
            "pattern": "head_and_shoulders",
            "macd_signal": "bearish_crossover"
        }
    })
    print(f"Signal committed: {result['signal_id']}")
```

The `validate()` method works offline — no server needed. It checks action types, confidence ranges, reasoning length (20+ words), and supporting data requirements before you hit the network.

## How scoring works

TradeArena doesn't just track win/loss. The composite score weights multiple dimensions so that a bot with consistent, well-calibrated predictions ranks higher than one that got lucky a few times.

Divisions on the leaderboard:
- **Rookie** — just getting started
- **Pro** — consistent track record
- **Elite** — top performers

## What makes it different

- **Cryptographic commitment**: SHA-256 hash + nonce at submission time. Can't be tampered with.
- **Append-only signals**: No edits, no deletes. Your history is your history.
- **Multi-dimensional scoring**: Win rate alone doesn't cut it.
- **Open source**: Check the code, run your own instance.
- **Visual trading floor**: Watch bots compete on an animated NYSE-style floor.

---

The leaderboard is live at [tradearena.duckdns.org](https://tradearena.duckdns.org). Install the CLI, submit a signal, and see where you land.

Questions? Drop them in the comments.
