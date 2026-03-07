"""CCXT adapter — converts CCXT ticker/OHLCV data into TradeArena signal format."""

from __future__ import annotations

from typing import Any


class CCXTAdapter:
    """Wraps a CCXT exchange instance to produce TradeArena-compatible signal dicts.

    Usage
    -----
    ::

        import ccxt
        from sdk.adapters.ccxt_adapter import CCXTAdapter
        from sdk import TradeArenaClient

        exchange = ccxt.binance({"apiKey": "...", "secret": "..."})
        adapter = CCXTAdapter(exchange)
        client = TradeArenaClient(api_key="...")

        signal = adapter.build_signal(
            creator_id="alice",
            symbol="BTC/USDT",
            action="BUY",
            confidence=0.72,
            reasoning="RSI oversold with strong volume spike...",
        )
        result = client.emit(signal)
    """

    def __init__(self, exchange: Any) -> None:
        """
        Parameters
        ----------
        exchange:
            An initialised ccxt exchange object (e.g. ccxt.binance()).
        """
        self.exchange = exchange

    def fetch_supporting_data(self, symbol: str) -> dict[str, Any]:
        """Fetch ticker and 24h stats to populate supporting_data."""
        ticker = self.exchange.fetch_ticker(symbol)
        return {
            "last_price": ticker.get("last"),
            "volume_24h": ticker.get("quoteVolume"),
            "change_24h_pct": ticker.get("percentage"),
            "high_24h": ticker.get("high"),
            "low_24h": ticker.get("low"),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
        }

    def build_signal(
        self,
        creator_id: str,
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str,
        target_price: float | None = None,
        stop_loss: float | None = None,
        timeframe: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a complete signal dict ready for TradeArenaClient.emit().

        Fetches live market data via CCXT to populate supporting_data.
        """
        supporting_data = self.fetch_supporting_data(symbol)
        if extra_data:
            supporting_data.update(extra_data)

        return {
            "creator_id": creator_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "supporting_data": supporting_data,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "timeframe": timeframe,
        }
