"""Tests for multi-exchange fallback logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from tradearena.core.exchanges import (
    ExchangeError,
    SymbolNotFound,
    _kraken_symbol,
    _okx_symbol,
    check_gap,
    check_halt,
    fetch_klines_with_fallback,
    fetch_price_with_fallback,
)

# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------


class TestSymbolMapping:
    def test_okx_symbol(self):
        assert _okx_symbol("BTCUSDT") == "BTC-USDT"
        assert _okx_symbol("ETHUSDT") == "ETH-USDT"
        assert _okx_symbol("SOLUSDT") == "SOL-USDT"

    def test_kraken_symbol_remap(self):
        assert _kraken_symbol("BTCUSDT") == "XBTUSDT"
        assert _kraken_symbol("DOGEUSDT") == "XDGUSDT"

    def test_kraken_symbol_passthrough(self):
        assert _kraken_symbol("ETHUSDT") == "ETHUSDT"
        assert _kraken_symbol("SOLUSDT") == "SOLUSDT"


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------


def _candle(o, h, lo, c, ts=0):
    return [ts, str(o), str(h), str(lo), str(c), "0", 0, "0", 0, "0", "0", "0"]


class TestCheckHalt:
    def test_not_halted(self):
        klines = [_candle(100, 102, 99, 101) for _ in range(10)]
        assert check_halt(klines) is False

    def test_halted(self):
        klines = [_candle(100, 100, 100, 100) for _ in range(6)]
        assert check_halt(klines) is True

    def test_too_few_candles(self):
        klines = [_candle(100, 100, 100, 100) for _ in range(3)]
        assert check_halt(klines) is False

    def test_streak_broken(self):
        klines = [_candle(100, 100, 100, 100) for _ in range(4)]
        klines.append(_candle(100, 101, 99, 100))
        klines.extend(_candle(100, 100, 100, 100) for _ in range(4))
        assert check_halt(klines) is False


class TestCheckGap:
    def test_no_gap(self):
        klines = [_candle(100, 101, 99, 100, ts=i * 300_000) for i in range(5)]
        assert check_gap(klines, "5m") is False

    def test_has_gap(self):
        klines = [
            _candle(100, 101, 99, 100, ts=0),
            _candle(100, 101, 99, 100, ts=300_000),
            _candle(100, 101, 99, 100, ts=3_000_000),  # big gap
        ]
        assert check_gap(klines, "5m") is True

    def test_single_candle(self):
        klines = [_candle(100, 101, 99, 100)]
        assert check_gap(klines, "5m") is False


# ---------------------------------------------------------------------------
# Fallback klines
# ---------------------------------------------------------------------------


class TestFetchKlinesWithFallback:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        provider = AsyncMock()
        provider.name = "test-primary"
        provider.fetch_klines = AsyncMock(
            return_value=[_candle(100, 102, 99, 101, ts=i * 300_000) for i in range(3)]
        )
        backup = AsyncMock()
        backup.name = "test-backup"

        result = await fetch_klines_with_fallback(
            AsyncMock(), "BTCUSDT", "5m", 0, 900_000, providers=[provider, backup]
        )
        assert len(result) == 3
        backup.fetch_klines.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        primary = AsyncMock()
        primary.name = "failing"
        primary.fetch_klines = AsyncMock(side_effect=httpx.ConnectError("down"))

        backup = AsyncMock()
        backup.name = "backup"
        backup.fetch_klines = AsyncMock(
            return_value=[_candle(100, 102, 99, 101, ts=i * 300_000) for i in range(3)]
        )

        result = await fetch_klines_with_fallback(
            AsyncMock(), "BTCUSDT", "5m", 0, 900_000, providers=[primary, backup]
        )
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fallback_on_empty_data(self):
        primary = AsyncMock()
        primary.name = "empty"
        primary.fetch_klines = AsyncMock(return_value=[])

        backup = AsyncMock()
        backup.name = "backup"
        backup.fetch_klines = AsyncMock(
            return_value=[_candle(100, 102, 99, 101, ts=i * 300_000) for i in range(3)]
        )

        result = await fetch_klines_with_fallback(
            AsyncMock(), "BTCUSDT", "5m", 0, 900_000, providers=[primary, backup]
        )
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fallback_on_halt(self):
        halted_data = [_candle(100, 100, 100, 100, ts=i * 300_000) for i in range(6)]
        primary = AsyncMock()
        primary.name = "halted"
        primary.fetch_klines = AsyncMock(return_value=halted_data)

        good_data = [_candle(100, 102, 99, 101, ts=i * 300_000) for i in range(6)]
        backup = AsyncMock()
        backup.name = "good"
        backup.fetch_klines = AsyncMock(return_value=good_data)

        result = await fetch_klines_with_fallback(
            AsyncMock(), "BTCUSDT", "5m", 0, 1_800_000, providers=[primary, backup]
        )
        assert result == good_data

    @pytest.mark.asyncio
    async def test_all_delisted_raises(self):
        p1 = AsyncMock()
        p1.name = "ex1"
        p1.fetch_klines = AsyncMock(side_effect=SymbolNotFound("nope"))

        p2 = AsyncMock()
        p2.name = "ex2"
        p2.fetch_klines = AsyncMock(side_effect=SymbolNotFound("nope"))

        with pytest.raises(SymbolNotFound, match="delisted"):
            await fetch_klines_with_fallback(
                AsyncMock(), "XYZUSDT", "5m", 0, 900_000, providers=[p1, p2]
            )

    @pytest.mark.asyncio
    async def test_all_failed_raises(self):
        p1 = AsyncMock()
        p1.name = "ex1"
        p1.fetch_klines = AsyncMock(side_effect=httpx.ConnectError("down"))

        p2 = AsyncMock()
        p2.name = "ex2"
        p2.fetch_klines = AsyncMock(side_effect=httpx.ReadTimeout("slow"))

        with pytest.raises(ExchangeError, match="All exchanges failed"):
            await fetch_klines_with_fallback(
                AsyncMock(), "BTCUSDT", "5m", 0, 900_000, providers=[p1, p2]
            )


# ---------------------------------------------------------------------------
# Fallback price
# ---------------------------------------------------------------------------


class TestFetchPriceWithFallback:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        provider = AsyncMock()
        provider.name = "primary"
        provider.fetch_price_at_ms = AsyncMock(return_value=50000.0)

        result = await fetch_price_with_fallback(
            AsyncMock(), "BTCUSDT", 1000000, providers=[provider]
        )
        assert result == 50000.0

    @pytest.mark.asyncio
    async def test_fallback_on_none(self):
        primary = AsyncMock()
        primary.name = "empty"
        primary.fetch_price_at_ms = AsyncMock(return_value=None)

        backup = AsyncMock()
        backup.name = "backup"
        backup.fetch_price_at_ms = AsyncMock(return_value=49500.0)

        result = await fetch_price_with_fallback(
            AsyncMock(), "BTCUSDT", 1000000, providers=[primary, backup]
        )
        assert result == 49500.0

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        primary = AsyncMock()
        primary.name = "broken"
        primary.fetch_price_at_ms = AsyncMock(side_effect=httpx.ConnectError("down"))

        backup = AsyncMock()
        backup.name = "backup"
        backup.fetch_price_at_ms = AsyncMock(return_value=49500.0)

        result = await fetch_price_with_fallback(
            AsyncMock(), "BTCUSDT", 1000000, providers=[primary, backup]
        )
        assert result == 49500.0

    @pytest.mark.asyncio
    async def test_all_delisted_raises(self):
        p1 = AsyncMock()
        p1.name = "ex1"
        p1.fetch_price_at_ms = AsyncMock(side_effect=SymbolNotFound("nope"))

        with pytest.raises(SymbolNotFound, match="delisted"):
            await fetch_price_with_fallback(AsyncMock(), "XYZUSDT", 1000000, providers=[p1])
