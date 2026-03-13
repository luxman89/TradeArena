"""Tests for the price oracle resolution logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradearena.core.oracle import (
    _resolve_by_direction,
    _resolve_with_targets,
    asset_to_symbol,
    parse_timeframe,
    resolve_signal,
)

# ---------------------------------------------------------------------------
# parse_timeframe
# ---------------------------------------------------------------------------


class TestParseTimeframe:
    def test_hours(self):
        assert parse_timeframe("1h") == timedelta(hours=1)
        assert parse_timeframe("4h") == timedelta(hours=4)

    def test_days(self):
        assert parse_timeframe("1d") == timedelta(days=1)
        assert parse_timeframe("3d") == timedelta(days=3)

    def test_weeks(self):
        assert parse_timeframe("1w") == timedelta(weeks=1)

    def test_none_defaults_to_1d(self):
        assert parse_timeframe(None) == timedelta(days=1)

    def test_invalid_defaults_to_1d(self):
        assert parse_timeframe("abc") == timedelta(days=1)
        assert parse_timeframe("") == timedelta(days=1)


# ---------------------------------------------------------------------------
# asset_to_symbol
# ---------------------------------------------------------------------------


class TestAssetToSymbol:
    def test_pair_with_slash(self):
        assert asset_to_symbol("BTC/USDT") == "BTCUSDT"

    def test_pair_without_slash(self):
        assert asset_to_symbol("ETHUSDT") == "ETHUSDT"

    def test_bare_asset_appends_usdt(self):
        assert asset_to_symbol("BTC") == "BTCUSDT"
        assert asset_to_symbol("sol") == "SOLUSDT"

    def test_dash_separator(self):
        assert asset_to_symbol("BTC-USDT") == "BTCUSDT"


# ---------------------------------------------------------------------------
# _resolve_with_targets (kline walking)
# ---------------------------------------------------------------------------


def _make_candle(open_p, high, low, close):
    """Minimal kline list matching Binance format (indices 1-4 are OHLC)."""
    return [0, str(open_p), str(high), str(low), str(close), "0", 0, "0", 0, "0", "0", "0"]


class TestResolveWithTargets:
    def test_bullish_target_hit(self):
        klines = [
            _make_candle(100, 105, 99, 104),
            _make_candle(104, 112, 103, 110),  # high >= target (110)
        ]
        outcome, price = _resolve_with_targets(klines, "buy", target_price=110.0, stop_loss=95.0)
        assert outcome == "WIN"
        assert price == 110.0

    def test_bullish_stop_hit(self):
        klines = [
            _make_candle(100, 102, 94, 95),  # low <= stop (95)
        ]
        outcome, price = _resolve_with_targets(klines, "long", target_price=120.0, stop_loss=95.0)
        assert outcome == "LOSS"
        assert price == 95.0

    def test_both_hit_same_candle_is_neutral(self):
        klines = [
            _make_candle(100, 120, 90, 105),  # both target and stop hit
        ]
        outcome, price = _resolve_with_targets(klines, "buy", target_price=115.0, stop_loss=92.0)
        assert outcome == "NEUTRAL"
        assert price == 105.0  # close price

    def test_neither_hit_is_neutral(self):
        klines = [
            _make_candle(100, 104, 98, 102),
            _make_candle(102, 106, 99, 103),
        ]
        outcome, price = _resolve_with_targets(klines, "buy", target_price=120.0, stop_loss=90.0)
        assert outcome == "NEUTRAL"
        assert price == 103.0  # last close

    def test_bearish_target_hit(self):
        klines = [
            _make_candle(100, 101, 88, 90),  # low <= target (90) for sell
        ]
        outcome, price = _resolve_with_targets(klines, "sell", target_price=90.0, stop_loss=110.0)
        assert outcome == "WIN"
        assert price == 90.0

    def test_bearish_stop_hit(self):
        klines = [
            _make_candle(100, 112, 99, 111),  # high >= stop (110) for sell
        ]
        outcome, price = _resolve_with_targets(klines, "short", target_price=85.0, stop_loss=110.0)
        assert outcome == "LOSS"
        assert price == 110.0


# ---------------------------------------------------------------------------
# _resolve_by_direction (no target/stop)
# ---------------------------------------------------------------------------


class TestResolveByDirection:
    def test_bullish_win(self):
        # Price up by more than 0.5%
        open_p = 100.0
        close_p = 100.6  # +0.6%
        outcome, price = _resolve_by_direction(open_p, close_p, "buy")
        assert outcome == "WIN"

    def test_bullish_loss(self):
        open_p = 100.0
        close_p = 99.0  # -1%
        outcome, price = _resolve_by_direction(open_p, close_p, "long")
        assert outcome == "LOSS"

    def test_bullish_neutral_small_move(self):
        open_p = 100.0
        close_p = 100.3  # +0.3% < threshold
        outcome, price = _resolve_by_direction(open_p, close_p, "yes")
        assert outcome == "NEUTRAL"

    def test_bearish_win(self):
        open_p = 100.0
        close_p = 99.0  # -1%
        outcome, price = _resolve_by_direction(open_p, close_p, "sell")
        assert outcome == "WIN"

    def test_bearish_loss(self):
        open_p = 100.0
        close_p = 101.0  # +1%
        outcome, price = _resolve_by_direction(open_p, close_p, "short")
        assert outcome == "LOSS"

    def test_bearish_neutral(self):
        open_p = 100.0
        close_p = 99.8  # -0.2% < threshold
        outcome, price = _resolve_by_direction(open_p, close_p, "no")
        assert outcome == "NEUTRAL"

    def test_zero_open_is_neutral(self):
        outcome, price = _resolve_by_direction(0.0, 100.0, "buy")
        assert outcome == "NEUTRAL"

    def test_threshold_boundary(self):
        open_p = 100.0
        close_p = 100.51  # just above 0.5% threshold
        outcome, _ = _resolve_by_direction(open_p, close_p, "buy")
        assert outcome == "WIN"

    def test_below_threshold_is_neutral(self):
        open_p = 100.0
        close_p = 100.49  # just below 0.5% threshold
        outcome, _ = _resolve_by_direction(open_p, close_p, "buy")
        assert outcome == "NEUTRAL"


# ---------------------------------------------------------------------------
# resolve_signal (async, with mocked Binance)
# ---------------------------------------------------------------------------


class TestResolveSignal:
    @pytest.mark.asyncio
    async def test_skips_if_not_yet_eligible(self):
        signal = MagicMock()
        signal.committed_at = datetime.now(UTC) - timedelta(hours=1)
        signal.timeframe = "1d"  # eligible in 23 more hours

        client = AsyncMock()
        result = await resolve_signal(signal, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolves_with_targets(self):
        signal = MagicMock()
        signal.committed_at = datetime.now(UTC) - timedelta(days=2)
        signal.timeframe = "1d"
        signal.asset = "BTC/USDT"
        signal.action = "buy"
        signal.target_price = 50000.0
        signal.stop_loss = 45000.0

        klines = [_make_candle(47000, 51000, 46000, 50500)]

        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = klines
        mock_resp.raise_for_status = MagicMock()
        client.get.return_value = mock_resp

        result = await resolve_signal(signal, client)
        assert result is not None
        outcome, price, at = result
        assert outcome == "WIN"
        assert price == 50000.0

    @pytest.mark.asyncio
    async def test_resolves_by_direction(self):
        signal = MagicMock()
        signal.committed_at = datetime.now(UTC) - timedelta(days=2)
        signal.timeframe = "1d"
        signal.asset = "ETH/USDT"
        signal.action = "sell"
        signal.target_price = None
        signal.stop_loss = None

        client = AsyncMock()

        # First call: open price, second call: close price
        resp1 = MagicMock()
        resp1.json.return_value = [[0, "0", "0", "0", "3000", "0", 0, "0", 0, "0", "0", "0"]]
        resp1.raise_for_status = MagicMock()

        resp2 = MagicMock()
        resp2.json.return_value = [[0, "0", "0", "0", "2900", "0", 0, "0", 0, "0", "0", "0"]]
        resp2.raise_for_status = MagicMock()

        client.get.side_effect = [resp1, resp2]

        result = await resolve_signal(signal, client)
        assert result is not None
        outcome, price, at = result
        assert outcome == "WIN"  # sell + price went down
        assert price == 2900.0
