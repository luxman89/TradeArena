"""Freqtrade adapter — converts Freqtrade strategy signals into TradeArena format."""

from __future__ import annotations

from typing import Any


class FreqtradeAdapter:
    """Converts Freqtrade dataframe rows into TradeArena signal dicts.

    Usage inside a Freqtrade strategy
    ----------------------------------
    ::

        from sdk.adapters.freqtrade_adapter import FreqtradeAdapter
        from sdk import TradeArenaClient

        client = TradeArenaClient(api_key="...")
        adapter = FreqtradeAdapter(creator_id="mybot")

        # Inside confirm_trade_entry():
        signal = adapter.from_dataframe_row(
            row=dataframe.iloc[-1],
            symbol=pair,
            action="BUY",
            confidence=0.65,
            reasoning="EMA crossover with volume confirmation above 20-period average...",
        )
        client.emit(signal)
    """

    def __init__(self, creator_id: str) -> None:
        self.creator_id = creator_id

    def from_dataframe_row(
        self,
        row: Any,
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str,
        target_price: float | None = None,
        stop_loss: float | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        """Build a signal dict from a single Freqtrade OHLCV dataframe row.

        Parameters
        ----------
        row:
            A pandas Series (single row) from Freqtrade's analyzed dataframe.
        """
        # Extract common indicators if present (graceful fallback to None)
        def _get(key: str) -> Any:
            try:
                val = row[key]
                return float(val) if val is not None else None
            except (KeyError, TypeError, ValueError):
                return None

        supporting_data: dict[str, Any] = {
            "close": _get("close"),
            "volume": _get("volume"),
        }

        # Add common indicators if available
        for indicator in ("rsi", "macd", "macdsignal", "ema_short", "ema_long", "bb_upperband", "bb_lowerband"):
            val = _get(indicator)
            if val is not None:
                supporting_data[indicator] = val

        # Ensure at least 2 keys
        if len(supporting_data) < 2:
            supporting_data["open"] = _get("open")
            supporting_data["high"] = _get("high")

        return {
            "creator_id": self.creator_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "supporting_data": supporting_data,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "timeframe": timeframe,
        }

    def from_dict(
        self,
        indicators: dict[str, Any],
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str,
        target_price: float | None = None,
        stop_loss: float | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        """Build a signal from a plain indicators dict (no pandas dependency)."""
        return {
            "creator_id": self.creator_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "supporting_data": indicators,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "timeframe": timeframe,
        }
