#!/usr/bin/env python3
"""TradeArena Momentum Bot — EMA crossover strategy.

Generates buy/sell signals based on exponential moving average crossovers.
When the fast EMA crosses above the slow EMA, emit a buy signal.
When the fast EMA crosses below the slow EMA, emit a sell signal.

Usage:
    1. pip install tradearena httpx
    2. export TRADEARENA_API_KEY="ta-your-key-here"
    3. python momentum_bot.py

Customize:
    - ASSET: Change the trading pair (e.g. "ETH/USDT", "SOL/USDT")
    - EMA_FAST / EMA_SLOW: Adjust crossover sensitivity (shorter = more signals)
    - INTERVAL_SECONDS: How often to check for crossovers
    - BASE_URL: Point to your own TradeArena server
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
EMA_FAST = 12  # Fast EMA period
EMA_SLOW = 26  # Slow EMA period
INTERVAL_SECONDS = 300  # Check every 5 minutes
BASE_URL = os.getenv("TRADEARENA_BASE_URL", "https://tradearena.duckdns.org")
API_KEY = os.getenv("TRADEARENA_API_KEY", "")

# ---------------------------------------------------------------------------
# EMA calculation
# ---------------------------------------------------------------------------


def ema(prices: list[float], period: int) -> float:
    """Calculate the exponential moving average of the last `period` prices."""
    if len(prices) < period:
        raise ValueError(f"Need at least {period} prices, got {len(prices)}")
    k = 2.0 / (period + 1)
    result = prices[0]
    for price in prices[1:]:
        result = price * k + result * (1 - k)
    return result


# ---------------------------------------------------------------------------
# Price simulation (replace with real data source)
# ---------------------------------------------------------------------------

# In production, replace this with a real price feed (CCXT, websocket, REST API).
# This simulation generates random-walk prices for demonstration purposes.

_sim_price = 65000.0
_price_history: list[float] = []


def fetch_latest_price() -> float:
    """Fetch the latest price. Replace with your real data source."""
    global _sim_price
    # Simulated random walk — replace with real API call
    _sim_price *= 1 + random.gauss(0, 0.002)
    _price_history.append(_sim_price)
    return _sim_price


def get_price_history() -> list[float]:
    """Return accumulated price history."""
    return _price_history


# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------


def check_crossover(prices: list[float]) -> str | None:
    """Detect EMA crossover. Returns 'buy', 'sell', or None."""
    if len(prices) < EMA_SLOW + 2:
        return None

    # Current EMAs
    fast_now = ema(prices, EMA_FAST)
    slow_now = ema(prices, EMA_SLOW)

    # Previous EMAs (one step back)
    fast_prev = ema(prices[:-1], EMA_FAST)
    slow_prev = ema(prices[:-1], EMA_SLOW)

    # Bullish crossover: fast crosses above slow
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "buy"

    # Bearish crossover: fast crosses below slow
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "sell"

    return None


def build_signal(action: str, prices: list[float]) -> dict:
    """Build a TradeArena signal from the current state."""
    current_price = prices[-1]
    fast = ema(prices, EMA_FAST)
    slow = ema(prices, EMA_SLOW)
    spread = abs(fast - slow) / slow

    # Confidence scales with the EMA spread — wider crossover = stronger signal
    confidence = min(0.85, max(0.35, spread * 100))

    # Set target and stop loss based on direction
    if action == "buy":
        target_price = round(current_price * 1.03, 2)  # +3%
        stop_loss = round(current_price * 0.985, 2)  # -1.5%
    else:
        target_price = round(current_price * 0.97, 2)  # -3%
        stop_loss = round(current_price * 1.015, 2)  # +1.5%

    return {
        "asset": ASSET,
        "action": action,
        "confidence": round(confidence, 4),
        "reasoning": (
            f"EMA crossover detected on {ASSET}. The {EMA_FAST}-period EMA "
            f"({'crossed above' if action == 'buy' else 'crossed below'}) "
            f"the {EMA_SLOW}-period EMA, signaling "
            f"{'bullish' if action == 'buy' else 'bearish'} momentum. "
            f"Current price is {current_price:.2f} with fast EMA at {fast:.2f} "
            f"and slow EMA at {slow:.2f}. The crossover spread is "
            f"{spread:.4%}, indicating {'strong' if spread > 0.005 else 'moderate'} "
            f"conviction in the directional move."
        ),
        "supporting_data": {
            "ema_fast": round(fast, 2),
            "ema_slow": round(slow, 2),
            "ema_spread_pct": round(spread * 100, 4),
            "current_price": round(current_price, 2),
        },
        "target_price": target_price,
        "stop_loss": stop_loss,
        "timeframe": "4h",
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    if not API_KEY:
        print("Error: set TRADEARENA_API_KEY environment variable.")
        print("  export TRADEARENA_API_KEY='ta-your-key-here'")
        sys.exit(1)

    # Import SDK
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from sdk import TradeArenaClient
    except ImportError:
        print("Error: TradeArena SDK not found. Install with: pip install tradearena")
        sys.exit(1)

    client = TradeArenaClient(api_key=API_KEY, base_url=BASE_URL)
    print(f"Momentum Bot started — {ASSET} | EMA({EMA_FAST}/{EMA_SLOW})")
    print(f"Server: {BASE_URL}")
    print(f"Checking every {INTERVAL_SECONDS}s. Press Ctrl+C to stop.\n")

    # Seed price history
    print("Seeding price history...")
    for _ in range(EMA_SLOW + 5):
        fetch_latest_price()
        time.sleep(0.01)
    print(f"  Collected {len(get_price_history())} prices. Ready.\n")

    try:
        while True:
            fetch_latest_price()
            prices = get_price_history()

            action = check_crossover(prices)
            if action:
                signal = build_signal(action, prices)

                # Validate locally first
                errors = client.validate(signal)
                if errors:
                    print(f"  Validation errors: {errors}")
                else:
                    try:
                        result = client.emit(signal)
                        print(
                            f"  SIGNAL: {action.upper()} {ASSET} @ {prices[-1]:.2f} "
                            f"| conf={signal['confidence']:.2f} "
                            f"| id={result.get('signal_id', '?')[:8]}..."
                        )
                    except Exception as e:
                        print(f"  Emit error: {e}")
            else:
                fast = ema(prices, EMA_FAST)
                slow = ema(prices, EMA_SLOW)
                print(f"  No crossover | price={prices[-1]:.2f} fast={fast:.2f} slow={slow:.2f}")

            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nBot stopped.")


if __name__ == "__main__":
    main()
