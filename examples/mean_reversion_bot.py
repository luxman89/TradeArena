#!/usr/bin/env python3
"""TradeArena Mean Reversion Bot — Bollinger Bands strategy.

Generates buy signals when price drops below the lower Bollinger Band (oversold)
and sell signals when price rises above the upper Bollinger Band (overbought).

Usage:
    1. pip install tradearena httpx
    2. export TRADEARENA_API_KEY="ta-your-key-here"
    3. python mean_reversion_bot.py

Customize:
    - ASSET: Change the trading pair
    - BB_PERIOD: Bollinger Band lookback window (default 20)
    - BB_STD_DEV: Number of standard deviations for bands (default 2.0)
    - INTERVAL_SECONDS: Check frequency
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# Configuration — edit these to customize the bot
# ---------------------------------------------------------------------------

ASSET = "ETH/USDT"
BB_PERIOD = 20  # Bollinger Band lookback period
BB_STD_DEV = 2.0  # Standard deviation multiplier
INTERVAL_SECONDS = 300  # Check every 5 minutes
BASE_URL = os.getenv("TRADEARENA_BASE_URL", "https://tradearena.duckdns.org")
API_KEY = os.getenv("TRADEARENA_API_KEY", "")

# ---------------------------------------------------------------------------
# Bollinger Bands calculation
# ---------------------------------------------------------------------------


def bollinger_bands(prices: list[float], period: int, num_std: float) -> tuple[float, float, float]:
    """Calculate Bollinger Bands. Returns (upper, middle, lower)."""
    if len(prices) < period:
        raise ValueError(f"Need at least {period} prices, got {len(prices)}")

    window = prices[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = math.sqrt(variance)

    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def percent_b(price: float, upper: float, lower: float) -> float:
    """Calculate %B indicator: where price sits relative to the bands.

    %B < 0 = below lower band (oversold)
    %B > 1 = above upper band (overbought)
    %B = 0.5 = at middle band
    """
    band_width = upper - lower
    if band_width == 0:
        return 0.5
    return (price - lower) / band_width


# ---------------------------------------------------------------------------
# Price simulation (replace with real data source)
# ---------------------------------------------------------------------------

_sim_price = 3200.0
_price_history: list[float] = []


def fetch_latest_price() -> float:
    """Fetch the latest price. Replace with your real data source."""
    global _sim_price
    # Mean-reverting simulation — tends to oscillate around initial price
    _sim_price *= 1 + random.gauss(0, 0.003)
    _price_history.append(_sim_price)
    return _sim_price


def get_price_history() -> list[float]:
    """Return accumulated price history."""
    return _price_history


# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------

# Track last signal to avoid spamming the same direction
_last_signal: str | None = None


def check_bands(prices: list[float]) -> str | None:
    """Check if price is outside Bollinger Bands. Returns 'buy', 'sell', or None."""
    global _last_signal

    if len(prices) < BB_PERIOD:
        return None

    upper, middle, lower = bollinger_bands(prices, BB_PERIOD, BB_STD_DEV)
    price = prices[-1]
    pct_b = percent_b(price, upper, lower)

    # Buy when price drops below lower band (oversold)
    if pct_b < 0 and _last_signal != "buy":
        _last_signal = "buy"
        return "buy"

    # Sell when price rises above upper band (overbought)
    if pct_b > 1 and _last_signal != "sell":
        _last_signal = "sell"
        return "sell"

    # Reset when price returns to middle zone
    if 0.3 < pct_b < 0.7:
        _last_signal = None

    return None


def build_signal(action: str, prices: list[float]) -> dict:
    """Build a TradeArena signal from current Bollinger Band state."""
    price = prices[-1]
    upper, middle, lower = bollinger_bands(prices, BB_PERIOD, BB_STD_DEV)
    pct_b = percent_b(price, upper, lower)
    band_width = (upper - lower) / middle * 100  # as percentage

    # Confidence: further outside the bands = higher confidence in reversion
    deviation = abs(pct_b - 0.5)
    confidence = min(0.90, max(0.30, deviation * 1.2))

    if action == "buy":
        target_price = round(middle, 2)  # Revert to middle
        stop_loss = round(lower * 0.99, 2)  # Just below lower band
    else:
        target_price = round(middle, 2)  # Revert to middle
        stop_loss = round(upper * 1.01, 2)  # Just above upper band

    condition = "oversold" if action == "buy" else "overbought"

    return {
        "asset": ASSET,
        "action": action,
        "confidence": round(confidence, 4),
        "reasoning": (
            f"Mean reversion signal on {ASSET}. Price is {condition} — "
            f"currently at {price:.2f} which is "
            f"{'below the lower' if action == 'buy' else 'above the upper'} "
            f"Bollinger Band ({BB_PERIOD}-period, {BB_STD_DEV} std dev). "
            f"The %B indicator reads {pct_b:.3f}, confirming the {condition} "
            f"condition. Band width is {band_width:.2f}%, suggesting "
            f"{'high' if band_width > 5 else 'moderate'} volatility. "
            f"Targeting mean reversion back to the middle band at {middle:.2f}."
        ),
        "supporting_data": {
            "bb_upper": round(upper, 2),
            "bb_middle": round(middle, 2),
            "bb_lower": round(lower, 2),
            "percent_b": round(pct_b, 4),
            "band_width_pct": round(band_width, 4),
        },
        "target_price": target_price,
        "stop_loss": stop_loss,
        "timeframe": "1h",
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
    print(f"Mean Reversion Bot started — {ASSET} | BB({BB_PERIOD}, {BB_STD_DEV}x)")
    print(f"Server: {BASE_URL}")
    print(f"Checking every {INTERVAL_SECONDS}s. Press Ctrl+C to stop.\n")

    # Seed price history
    print("Seeding price history...")
    for _ in range(BB_PERIOD + 5):
        fetch_latest_price()
        time.sleep(0.01)
    print(f"  Collected {len(get_price_history())} prices. Ready.\n")

    try:
        while True:
            fetch_latest_price()
            prices = get_price_history()

            action = check_bands(prices)
            if action:
                signal = build_signal(action, prices)

                errors = client.validate(signal)
                if errors:
                    print(f"  Validation errors: {errors}")
                else:
                    try:
                        result = client.emit(signal)
                        upper, middle, lower = bollinger_bands(prices, BB_PERIOD, BB_STD_DEV)
                        print(
                            f"  SIGNAL: {action.upper()} {ASSET} @ {prices[-1]:.2f} "
                            f"| conf={signal['confidence']:.2f} "
                            f"| bands=[{lower:.2f}, {middle:.2f}, {upper:.2f}] "
                            f"| id={result.get('signal_id', '?')[:8]}..."
                        )
                    except Exception as e:
                        print(f"  Emit error: {e}")
            else:
                if len(prices) >= BB_PERIOD:
                    upper, middle, lower = bollinger_bands(prices, BB_PERIOD, BB_STD_DEV)
                    pct_b = percent_b(prices[-1], upper, lower)
                    print(
                        f"  In range | price={prices[-1]:.2f} "
                        f"%B={pct_b:.3f} "
                        f"bands=[{lower:.2f}, {middle:.2f}, {upper:.2f}]"
                    )

            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nBot stopped.")


if __name__ == "__main__":
    main()
