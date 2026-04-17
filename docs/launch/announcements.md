# TradeArena — Launch Announcement Copy

Post these after the Sprint 3 gating checkpoint passes. Stagger: HN → Reddit (same day, 2h apart) → Indie Hackers (next day) → X (same day as IH).

---

## Hacker News — Show HN

**Title:**
> Show HN: TradeArena — cryptographically committed market predictions, ranked as a skill sport

**Body:**

TradeArena is an open leaderboard for market prediction accuracy. Think Kaggle for trading signals, not a financial marketplace — no money changes hands, ever.

**How it works:**

- You submit a prediction (buy/sell/long/short/yes/no) with a confidence score and reasoning
- Every submission is SHA-256 committed before the outcome is known — no retroactive editing
- After the timeframe closes, the oracle resolves the outcome against Binance price data
- You're scored across four dimensions: Win Rate (30%), Risk-Adjusted Return (30%), Consistency (25%), Confidence Calibration (15%)

**Why I built it:**

I kept seeing people claim trading edge without any verifiable track record. TradeArena makes the commitment tamper-proof. The cryptographic hash means you can't change your reasoning after the fact.

**For algo traders:** Python SDK + REST API. Submit signals programmatically, backtest your strategy against the live leaderboard. Three built-in bot templates (RSI, EMA, BB Squeeze) to get started.

**For humans:** Submit directly from the arena UI — no terminal required.

**Tech stack:** FastAPI + PostgreSQL + Redis + Phaser 3 trading floor UI. All open source on GitHub.

**Not investment advice.** Rankings reflect past prediction accuracy only.

https://tradearena.duckdns.org

---

## Reddit — r/algotrading

**Title:**
> I built a cryptographically committed signal leaderboard — submit your strategy, track its accuracy, prove your edge

**Body:**

Hey r/algotrading,

I built TradeArena — a platform where you submit market predictions (asset, direction, confidence, reasoning) and they get SHA-256 committed *before* the outcome is known. No retroactive edits. Outcomes resolve against Binance kline data.

**Why this is different from "I made X% this month":**
The commitment hash is generated at submission time and is verifiable. If you claim "I called BTC long at 0.85 confidence," we can prove when you said it and what the outcome was.

**Scoring:**
- Win Rate (30%)
- Risk-Adjusted Return / Sharpe-like (30%)
- Consistency across rolling windows (25%)
- Confidence Calibration / Brier score (15%)

**For algos:** REST API + Python SDK. `pip install tradearena`. Submit signals programmatically, watch your bot's calibration improve over time.

**Current leaderboard:** Three built-in bots running RSI, EMA crossover, and BB Squeeze strategies. Beat them.

It's free, always free. No tipping, no subscriptions. The only currency is leaderboard rank.

https://tradearena.duckdns.org · SDK: `pip install tradearena`

*Not investment advice. Rankings reflect prediction accuracy only.*

---

## Reddit — r/SideProject

**Title:**
> TradeArena — I built a market prediction leaderboard with cryptographic commitments so no one can fake their track record

**Body:**

Six weeks of side-project work, launching today.

**The problem I wanted to solve:** Everyone on finance Twitter claims trading edge. There's no way to verify. Most "track records" are cherry-picked.

**What I built:** A public leaderboard where predictions are cryptographically committed before outcomes are known. SHA-256 hash of your signal + a server nonce = tamper-proof. You literally can't edit your reasoning after the fact.

**Stack:**
- FastAPI + PostgreSQL + Redis (backend)
- Alembic migrations, bcrypt auth, rate limiting
- Phaser 3 for the NYSE trading floor UI (the fun part)
- Python SDK on PyPI (`pip install tradearena`)

**What I'm proud of:**
- The commitment system is genuinely novel for this space
- Four-dimension scoring (win rate, risk-adjusted return, consistency, calibration)
- The arena UI — animated pixel-art traders walking around a NYSE floor, submitting signals in real-time

**What I'm still building:** Better mobile, seasonal leaderboards, tournament mode.

Always free — this is a skill sport, not a financial product.

https://tradearena.duckdns.org

Not investment advice.

---

## Indie Hackers

**Title:**
> How I built a cryptographic commitment system to make fake trading track records impossible

**Body:**

I'm launching TradeArena today. Here's what I built and the technical decisions behind it.

### The core insight

Market prediction is a legitimate skill — but there's no way to verify it publicly. You can't audit someone's Telegram channel for their actual track record. You can backtest, but live markets are different. I wanted a platform where accuracy is *provable*.

The solution: cryptographic commitment. Before any outcome is known, the server hashes your signal fields (asset, action, confidence, reasoning, target price, stop loss, timeframe) with a random nonce → SHA-256 → `signal_id`. You can't change a signal after submission without the hash changing. Anyone can verify.

### The scoring system

Four dimensions, each normalized [0,1]:

| Dimension | Weight | What it measures |
|---|---|---|
| Win Rate | 30% | Simple accuracy |
| Risk-Adjusted Return | 30% | Sharpe-like: consistency of returns vs variance |
| Consistency | 25% | Stability of win rate across 10-signal rolling windows |
| Confidence Calibration | 15% | Brier score — are your 80% confidence calls right 80% of the time? |

### What worked

The Phaser 3 trading floor UI got way more engagement than I expected. People spend time *watching* the arena even when they're not submitting signals. The visual representation of the leaderboard makes it feel like a game.

### What's hard

Positioning. Is this a dev tool? A trading game? A research platform? Currently: all three, which means mixed messaging. I'm leaning into "skill sport" framing to avoid regulatory grey areas.

### Numbers

- Sprint 1 (2 weeks): security, auth, legal pages
- Sprint 2 (2 weeks): UI signal submission, streaks, seasonal leaderboard
- Sprint 3 (this week): Redis rate limiting, JWT revocation, backup strategy, follow/comments
- Total: ~6 weeks solo

Free forever. No revenue model yet — focus is 100 active users first.

https://tradearena.duckdns.org

---

## X (Twitter/𝕏)

**Thread:**

1/ I spent 6 weeks building a platform where you can't fake your trading track record.

Every prediction is SHA-256 committed before the market moves. No retroactive edits. Outcomes resolve automatically against Binance data.

tradearena.duckdns.org 🧵

2/ The commitment system: you submit an asset, direction, confidence (0–100%), and reasoning. The server hashes everything with a random nonce → SHA-256. That hash is your signal ID. Change one character and the hash doesn't match.

You literally cannot lie about when you called something.

3/ You're scored on 4 dimensions:
- Win Rate (30%)
- Risk-Adjusted Return (30%) — Sharpe-like
- Consistency (25%)
- Confidence Calibration (15%) — are your 80% calls right 80% of the time?

The leaderboard is a skill ranking, not a PnL contest.

4/ For algo traders: Python SDK on PyPI. `pip install tradearena`. Submit signals from your bot, watch your calibration over time. Three built-in strategies (RSI, EMA, BB Squeeze) to benchmark against.

5/ For humans: submit directly from the trading floor UI. No terminal, no code.

Free forever. No tipping, no subs. The only currency is leaderboard rank.

Not investment advice — this is a skill sport.

tradearena.duckdns.org

---

## Discord Announcement (for TradeArena server)

> @everyone
>
> **TradeArena is live! 🎉**
>
> After 6 weeks of building, we're officially open.
>
> **What's new in this release:**
> - Submit predictions directly from the arena UI (no SDK needed)
> - 🔥 Daily streaks — log in and predict every day to maintain yours
> - Weekly seasonal leaderboard — fresh start every Monday at midnight UTC
> - XP + level progression — earn XP for every prediction
> - Follow other predictors + read their signal comments on their profile
>
> **For algo traders:**
> `pip install tradearena` — Python SDK with REST API. Three built-in bot templates to get started.
>
> **Rules:** Predictions are not investment advice. Rankings measure accuracy only. Full rules at /rules.
>
> Drop a 👋 if you just signed up and let us know what asset you're predicting first.
