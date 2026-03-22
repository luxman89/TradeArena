#!/usr/bin/env python3
"""TradeArena Sentiment Bot — Fear & Greed / Funding Rate strategy.

Generates contrarian signals based on market sentiment extremes.
When sentiment is extremely fearful (low), emit buy signals (be greedy).
When sentiment is extremely greedy (high), emit sell signals (be fearful).

Uses the Alternative.me Crypto Fear & Greed Index as the primary signal source.
Falls back to simulated data if the API is unavailable.

Usage:
    1. pip install tradearena httpx
    2. export TRADEARENA_API_KEY="ta-your-key-here"
    3. python sentiment_bot.py

Customize:
    - ASSET: Change the trading pair
    - FEAR_THRESHOLD: Buy when sentiment drops below this (0-100, default 25)
    - GREED_THRESHOLD: Sell when sentiment rises above this (0-100, default 75)
    - INTERVAL_SECONDS: Check frequency (default 600 = 10 min)
"""

from __future__ import annotations

import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# Configuration — edit these to customize the bot
# ---------------------------------------------------------------------------

ASSET = "BTC/USDT"
FEAR_THRESHOLD = 25  # Buy below this (extreme fear)
GREED_THRESHOLD = 75  # Sell above this (extreme greed)
INTERVAL_SECONDS = 600  # Check every 10 minutes
BASE_URL = os.getenv("TRADEARENA_BASE_URL", "https://tradearena.duckdns.org")
API_KEY = os.getenv("TRADEARENA_API_KEY", "")

# Fear & Greed API (free, no auth required)
FEAR_GREED_API = "https://api.alternative.me/fng/?limit=1"

# ---------------------------------------------------------------------------
# Sentiment data fetching
# ---------------------------------------------------------------------------


def fetch_fear_greed_index() -> dict | None:
    """Fetch the current Crypto Fear & Greed Index.

    Returns dict with 'value' (0-100), 'classification' (str), and 'timestamp'.
    Returns None if the API is unavailable.
    """
    try:
        import httpx

        resp = httpx.get(FEAR_GREED_API, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                entry = data[0]
                return {
                    "value": int(entry["value"]),
                    "classification": entry["value_classification"],
                    "timestamp": entry["timestamp"],
                }
    except Exception:
        pass
    return None


def simulate_sentiment() -> dict:
    """Generate simulated sentiment data for demo/testing.

    Replace this with a real data source in production.
    """
    # Random walk around 50, with occasional extremes
    value = int(max(0, min(100, random.gauss(50, 20))))
    if value <= 25:
        classification = "Extreme Fear"
    elif value <= 40:
        classification = "Fear"
    elif value <= 60:
        classification = "Neutral"
    elif value <= 75:
        classification = "Greed"
    else:
        classification = "Extreme Greed"

    return {
        "value": value,
        "classification": classification,
        "timestamp": str(int(time.time())),
    }


# ---------------------------------------------------------------------------
# Funding rate (optional secondary signal)
# ---------------------------------------------------------------------------


def fetch_funding_rate() -> float | None:
    """Fetch perpetual funding rate as a secondary sentiment indicator.

    Positive funding = longs pay shorts (bullish crowd) -> contrarian sell
    Negative funding = shorts pay longs (bearish crowd) -> contrarian buy

    Returns None if unavailable. Replace the URL with your exchange API.
    """
    # Stub — replace with real exchange API call
    # Example for Binance: GET /fapi/v1/fundingRate?symbol=BTCUSDT&limit=1
    return None


# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------

_last_signal: str | None = None
_sentiment_history: list[int] = []


def check_sentiment(sentiment: dict) -> str | None:
    """Check if sentiment is at an extreme. Returns 'buy', 'sell', or None."""
    global _last_signal

    value = sentiment["value"]
    _sentiment_history.append(value)

    # Buy on extreme fear (contrarian: "be greedy when others are fearful")
    if value < FEAR_THRESHOLD and _last_signal != "buy":
        _last_signal = "buy"
        return "buy"

    # Sell on extreme greed (contrarian: "be fearful when others are greedy")
    if value > GREED_THRESHOLD and _last_signal != "sell":
        _last_signal = "sell"
        return "sell"

    # Reset when sentiment returns to neutral zone
    if 40 <= value <= 60:
        _last_signal = None

    return None


def build_signal(action: str, sentiment: dict, funding_rate: float | None) -> dict:
    """Build a TradeArena signal from sentiment data."""
    value = sentiment["value"]
    classification = sentiment["classification"]

    # Confidence: more extreme sentiment = higher confidence in reversion
    if action == "buy":
        extremeness = (FEAR_THRESHOLD - value) / FEAR_THRESHOLD
    else:
        extremeness = (value - GREED_THRESHOLD) / (100 - GREED_THRESHOLD)
    confidence = min(0.85, max(0.30, 0.4 + extremeness * 0.5))

    # Calculate sentiment trend from history
    trend = "stable"
    if len(_sentiment_history) >= 3:
        recent_avg = sum(_sentiment_history[-3:]) / 3
        older_avg = (
            sum(_sentiment_history[-6:-3]) / 3 if len(_sentiment_history) >= 6 else recent_avg
        )
        if recent_avg - older_avg > 5:
            trend = "rising"
        elif older_avg - recent_avg > 5:
            trend = "falling"

    supporting_data: dict = {
        "fear_greed_index": value,
        "fear_greed_class": classification,
        "sentiment_trend": trend,
    }
    if funding_rate is not None:
        supporting_data["funding_rate"] = funding_rate

    condition = "extreme fear" if action == "buy" else "extreme greed"
    contrarian = "bullish" if action == "buy" else "bearish"

    reasoning = (
        f"Contrarian sentiment signal on {ASSET}. The Crypto Fear & Greed Index "
        f"is at {value}/100 ({classification}), indicating {condition}. "
        f"Historically, {condition} conditions precede reversals as the crowd "
        f"tends to be wrong at extremes. Taking a {contrarian} position as a "
        f"contrarian bet on mean reversion. Sentiment trend is {trend} over "
        f"recent readings, "
        f"{'reinforcing' if trend == ('falling' if action == 'buy' else 'rising') else 'noting'} "
        f"the signal."
    )

    if funding_rate is not None:
        if funding_rate > 0:
            fr_direction = "positive (longs pay shorts)"
        else:
            fr_direction = "negative (shorts pay longs)"
        reasoning += (
            f" Funding rate is {fr_direction} at {funding_rate:.4%}, providing additional context."
        )

    return {
        "asset": ASSET,
        "action": action,
        "confidence": round(confidence, 4),
        "reasoning": reasoning,
        "supporting_data": supporting_data,
        "timeframe": "1d",
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    if not API_KEY:
        print("Error: set TRADEARENA_API_KEY environment variable.")
        print("  export TRADEARENA_API_KEY='ta-your-key-here'")
        sys.exit(1)

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from sdk import TradeArenaClient
    except ImportError:
        print("Error: TradeArena SDK not found. Install with: pip install tradearena")
        sys.exit(1)

    client = TradeArenaClient(api_key=API_KEY, base_url=BASE_URL)
    print(f"Sentiment Bot started — {ASSET}")
    print(f"  Fear threshold:  < {FEAR_THRESHOLD} (buy)")
    print(f"  Greed threshold: > {GREED_THRESHOLD} (sell)")
    print(f"  Server: {BASE_URL}")
    print(f"  Checking every {INTERVAL_SECONDS}s. Press Ctrl+C to stop.\n")

    try:
        while True:
            # Fetch real sentiment data, fall back to simulation
            sentiment = fetch_fear_greed_index()
            data_source = "API"
            if sentiment is None:
                sentiment = simulate_sentiment()
                data_source = "simulated"

            funding_rate = fetch_funding_rate()

            action = check_sentiment(sentiment)
            if action:
                signal = build_signal(action, sentiment, funding_rate)

                errors = client.validate(signal)
                if errors:
                    print(f"  Validation errors: {errors}")
                else:
                    try:
                        result = client.emit(signal)
                        print(
                            f"  SIGNAL: {action.upper()} {ASSET} "
                            f"| F&G={sentiment['value']} ({sentiment['classification']}) "
                            f"| conf={signal['confidence']:.2f} "
                            f"| source={data_source} "
                            f"| id={result.get('signal_id', '?')[:8]}..."
                        )
                    except Exception as e:
                        print(f"  Emit error: {e}")
            else:
                print(
                    f"  Neutral | F&G={sentiment['value']} "
                    f"({sentiment['classification']}) | source={data_source}"
                )

            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nBot stopped.")


if __name__ == "__main__":
    main()
