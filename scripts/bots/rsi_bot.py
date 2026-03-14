"""RSI Ranger Bot — buys oversold, sells overbought.

Strategy inspired by freqtrade's RSI strategy:
https://github.com/freqtrade/freqtrade-strategies
"""

from __future__ import annotations

from .base import BaseBot


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI. Returns the most recent RSI value."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    # Seed with simple average of first `period` values
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder smoothing for the rest
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


class RSIRangerBot(BaseBot):
    """Mean-reversion bot: buy on RSI < 30, sell on RSI > 70."""

    name = "RSI Ranger"
    email = "rsi-ranger@bots.tradearena.io"
    division = "crypto"
    strategy_description = (
        "Mean-reversion strategy using RSI(14). Buys when the market is oversold "
        "(RSI below 30) and sells when overbought (RSI above 70). Confidence scales "
        "with the magnitude of the RSI deviation from the threshold. Inspired by "
        "the freqtrade RSIStrategy open-source framework."
    )
    assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    timeframe = "1h"

    OVERSOLD = 30.0
    OVERBOUGHT = 70.0
    RSI_PERIOD = 14

    def generate_signal(self, symbol: str, candles: list[dict]) -> dict | None:
        closes = [c["close"] for c in candles]
        rsi = _rsi(closes, self.RSI_PERIOD)
        close = closes[-1]

        if rsi < self.OVERSOLD:
            # Confidence: deeper into oversold → higher confidence (0.45–0.95)
            depth = (self.OVERSOLD - rsi) / self.OVERSOLD
            confidence = round(min(0.95, 0.45 + depth * 0.50), 4)
            return {
                "asset": symbol,
                "action": "buy",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"RSI(14) on {symbol} has dropped to {rsi:.1f}, entering oversold territory "
                    f"below the 30 threshold. This indicates excessive selling pressure and a "
                    f"likely mean-reversion bounce. Current price is {close:.4f}. Historical "
                    f"analysis shows strong reversal probability when RSI falls this far below 30."
                ),
                "supporting_data": {
                    "rsi": round(rsi, 2),
                    "rsi_period": self.RSI_PERIOD,
                    "rsi_threshold": self.OVERSOLD,
                    "close": close,
                },
            }

        if rsi > self.OVERBOUGHT:
            depth = (rsi - self.OVERBOUGHT) / (100.0 - self.OVERBOUGHT)
            confidence = round(min(0.95, 0.45 + depth * 0.50), 4)
            return {
                "asset": symbol,
                "action": "sell",
                "confidence": confidence,
                "timeframe": self.timeframe,
                "reasoning": (
                    f"RSI(14) on {symbol} has climbed to {rsi:.1f}, entering overbought territory "
                    f"above the 70 threshold. This signals excessive buying pressure and a "
                    f"likely mean-reversion pullback. Current price is {close:.4f}. The strategy "
                    f"targets a reversion to the mean when momentum reaches extreme levels."
                ),
                "supporting_data": {
                    "rsi": round(rsi, 2),
                    "rsi_period": self.RSI_PERIOD,
                    "rsi_threshold": self.OVERBOUGHT,
                    "close": close,
                },
            }

        return None
