# Reddit Post — r/algotrading

**Title:** I built a competitive arena where trading bots submit cryptographically committed predictions and get ranked — here's what I learned

---

Hey r/algotrading,

I've been working on something I wish existed when I started building trading bots: a platform where you can submit signals and actually see how your strategy stacks up against others — with cryptographic proof that nobody's faking their results.

**What is it?**

[TradeArena](https://tradearena.duckdns.org) is an open-source signal-tracking platform. You submit predictions (buy/sell/long/short with a confidence level and reasoning), and each signal gets SHA-256 committed so it can't be edited after the fact. Your signals are scored across multiple dimensions — win rate, risk-adjusted return, consistency, and confidence calibration — then ranked on a live leaderboard.

There's a visual NYSE-style trading floor (built with Phaser 3) where you can watch the bots compete in real time.

**Quickstart (< 5 min):**

```bash
pip install tradearena

tradearena init --api-key ta-your-key-here

tradearena submit \
  --asset BTC/USDT \
  --action buy \
  --confidence 0.8 \
  --reasoning "Strong bullish momentum with increasing volume and RSI divergence on 4h chart" \
  --data rsi=72.5 \
  --data volume_24h=1.2B
```

That's it. Check your ranking with `tradearena status`.

**Why I built it:**

Most signal-tracking is either private (no accountability) or on social platforms where people delete bad calls. The cryptographic commitment means once you submit, it's locked in. No take-backs.

The scoring is multi-dimensional on purpose — high win rate with random confidence isn't as impressive as consistent, well-calibrated calls with solid reasoning.

**What's next:**

- Battle mode (head-to-head on the same asset)
- More asset classes
- Community tournaments

Would love feedback from this community. The leaderboard is live at [tradearena.duckdns.org](https://tradearena.duckdns.org) and the quickstart walks you through getting your first signal submitted.

What dimensions would you want to see in scoring? Anything missing?
