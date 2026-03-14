"""EMA Crossover Bot — golden/death cross trend follower.

Strategy inspired by jesse's EMA Cross strategy:
https://github.com/jesse-ai/jesse
"""

from __future__ import annotations

from .base import BaseBot


def _ema(closes: list[float], period: int) -> list[float]:
    """Exponential moving average. Returns EMA series of same length as closes."""
    if not closes:
        return []
    k = 2.0 / (period + 1)
    result = [closes[0]]
    for price in closes[1:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


class EMACrossBot(BaseBot):
    """Trend-following bot: long on EMA9 cross above EMA21, short on cross below."""

    name = "EMA Cross"
    email = "ema-cross@bots.tradearena.io"
    division = "crypto"
    strategy_description = (
        "Trend-following strategy using a fast EMA(9) and slow EMA(21) crossover. "
        "Goes long on a golden cross (EMA9 crosses above EMA21) signalling upward "
        "momentum, and short on a death cross (EMA9 crosses below EMA21). Confidence "
        "scales with the percentage spread between the two EMAs. Inspired by the "
        "jesse algo-trading framework's EMA Cross strategy."
    )
    assets = ["BTC/USDT", "ETH/USDT"]
    timeframe = "1h"

    FAST = 9
    SLOW = 21

    def generate_signal(self, symbol: str, candles: list[dict]) -> dict | None:
        if len(candles) < self.SLOW + 2:
            return None

        closes = [c["close"] for c in candles]
        fast = _ema(closes, self.FAST)
        slow = _ema(closes, self.SLOW)

        # Compare last two bars to detect a fresh crossover
        prev_fast, prev_slow = fast[-2], slow[-2]
        curr_fast, curr_slow = fast[-1], slow[-1]
        close = closes[-1]

        golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
        death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

        spread_pct = abs(curr_fast - curr_slow) / curr_slow
        confidence = round(min(0.95, max(0.20, spread_pct * 50)), 4)

        if golden_cross:
            return {
                "asset": symbol,
                "action": "long",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"EMA(9) has crossed above EMA(21) on {symbol}, forming a golden cross. "
                    f"The fast EMA ({curr_fast:.2f}) is now above the slow EMA ({curr_slow:.2f}), "
                    f"confirming a shift to bullish momentum. The spread of "
                    f"{spread_pct*100:.3f}% between the two EMAs indicates the strength of the "
                    f"trend. Current price is {close:.4f}. This classic signal suggests "
                    f"sustained upward price movement ahead."
                ),
                "supporting_data": {
                    "ema_fast": round(curr_fast, 4),
                    "ema_slow": round(curr_slow, 4),
                    "cross_direction": "up",
                    "spread_pct": round(spread_pct * 100, 4),
                },
            }

        if death_cross:
            return {
                "asset": symbol,
                "action": "short",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"EMA(9) has crossed below EMA(21) on {symbol}, forming a death cross. "
                    f"The fast EMA ({curr_fast:.2f}) is now below the slow EMA ({curr_slow:.2f}), "
                    f"confirming a shift to bearish momentum. The spread of "
                    f"{spread_pct*100:.3f}% between the two EMAs reflects the downward pressure. "
                    f"Current price is {close:.4f}. This bearish crossover historically "
                    f"precedes further price declines."
                ),
                "supporting_data": {
                    "ema_fast": round(curr_fast, 4),
                    "ema_slow": round(curr_slow, 4),
                    "cross_direction": "down",
                    "spread_pct": round(spread_pct * 100, 4),
                },
            }

        return None
