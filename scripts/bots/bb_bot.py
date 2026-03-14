"""Bollinger Bands Bot — buys lower band touch, sells upper band touch.

Strategy inspired by freqtrade's BollingerBands strategy:
https://github.com/freqtrade/freqtrade-strategies
"""

from __future__ import annotations

import math

from .base import BaseBot


def _bollinger_bands(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float]:
    """Returns (upper, middle, lower) bands for the latest bar."""
    window = closes[-period:]
    if len(window) < period:
        return closes[-1], closes[-1], closes[-1]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = math.sqrt(variance)
    return mean + num_std * std, mean, mean - num_std * std


class BollingerBot(BaseBot):
    """Mean-reversion bot: buy on lower band touch, sell on upper band touch."""

    name = "BB Squeeze"
    email = "bb-squeeze@bots.tradearena.io"
    division = "crypto"
    strategy_description = (
        "Mean-reversion strategy using Bollinger Bands (20, 2σ). Buys when price "
        "touches or breaches the lower band (statistical oversell) and sells when "
        "price reaches the upper band (statistical overbuy). Confidence scales with "
        "how far price has moved beyond the band relative to band width. Inspired by "
        "freqtrade's Bollinger Bands strategy."
    )
    assets = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
    timeframe = "1h"

    BB_PERIOD = 20
    BB_STD = 2.0

    def generate_signal(self, symbol: str, candles: list[dict]) -> dict | None:
        if len(candles) < self.BB_PERIOD:
            return None

        closes = [c["close"] for c in candles]
        close = closes[-1]
        upper, middle, lower = _bollinger_bands(closes, self.BB_PERIOD, self.BB_STD)
        band_width = upper - lower
        if band_width == 0:
            return None

        below_lower = close <= lower
        above_upper = close >= upper

        if below_lower:
            # Distance below lower band as fraction of band width
            depth = (lower - close) / band_width
            confidence = round(min(0.95, max(0.25, 0.40 + depth * 2.0)), 4)
            return {
                "asset": symbol,
                "action": "buy",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"Price of {symbol} ({close:.4f}) has touched the lower Bollinger Band "
                    f"({lower:.4f}), indicating the asset is statistically oversold. The "
                    f"20-period middle band sits at {middle:.4f} with a band width of "
                    f"{band_width:.4f}. A mean-reversion back toward the middle band is "
                    f"expected. The Bollinger Band squeeze suggests reduced volatility "
                    f"followed by a directional breakout to the upside."
                ),
                "supporting_data": {
                    "bb_upper": round(upper, 4),
                    "bb_middle": round(middle, 4),
                    "bb_lower": round(lower, 4),
                    "close": close,
                },
            }

        if above_upper:
            depth = (close - upper) / band_width
            confidence = round(min(0.95, max(0.25, 0.40 + depth * 2.0)), 4)
            return {
                "asset": symbol,
                "action": "sell",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"Price of {symbol} ({close:.4f}) has reached the upper Bollinger Band "
                    f"({upper:.4f}), indicating the asset is statistically overbought. The "
                    f"20-period middle band sits at {middle:.4f} with a band width of "
                    f"{band_width:.4f}. A mean-reversion pullback toward the middle band is "
                    f"anticipated. Extreme upper band touches historically precede short-term "
                    f"corrections in crypto markets."
                ),
                "supporting_data": {
                    "bb_upper": round(upper, 4),
                    "bb_middle": round(middle, 4),
                    "bb_lower": round(lower, 4),
                    "close": close,
                },
            }

        return None
