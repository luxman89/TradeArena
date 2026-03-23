"""Exchange providers for price data with fallback support.

Each provider normalises kline data to the Binance format:
  [open_time_ms, open, high, low, close, volume, close_time_ms, ...]

Providers: Binance (primary), OKX, Kraken.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kline format helpers
# ---------------------------------------------------------------------------

# Binance kline has 12 fields. We only need indices 0-5 for resolution.
# Pad extra fields so downstream code expecting 12 elements doesn't break.
_PAD = ["0", 0, "0", 0, "0", "0"]


def _binance_kline(ts_ms: int, o: str, h: str, lo: str, c: str, v: str) -> list:
    return [ts_ms, o, h, lo, c, v] + _PAD


# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------


def _okx_symbol(binance_symbol: str) -> str:
    """BTCUSDT -> BTC-USDT"""
    s = binance_symbol.upper()
    for quote in ("USDT", "BUSD", "USDC"):
        if s.endswith(quote):
            base = s[: -len(quote)]
            return f"{base}-{quote}"
    return s


_KRAKEN_REMAP = {"BTC": "XBT", "DOGE": "XDG"}


def _kraken_symbol(binance_symbol: str) -> str:
    """BTCUSDT -> XBTUSDT"""
    s = binance_symbol.upper()
    for quote in ("USDT", "BUSD", "USDC"):
        if s.endswith(quote):
            base = s[: -len(quote)]
            base = _KRAKEN_REMAP.get(base, base)
            return f"{base}{quote}"
    return s


_KRAKEN_INTERVAL_MAP = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExchangeError(Exception):
    """Base error for exchange operations."""


class SymbolNotFound(ExchangeError):
    """Asset is delisted or not traded on this exchange."""


class DataGap(ExchangeError):
    """Exchange returned data but it contains significant gaps."""


class ExchangeHalted(ExchangeError):
    """Trading appears halted (all candles identical)."""


# ---------------------------------------------------------------------------
# Provider dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExchangeProvider:
    name: str
    base_url: str

    async def fetch_klines(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list]:
        raise NotImplementedError

    async def fetch_price_at_ms(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        ts_ms: int,
    ) -> float | None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Binance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BinanceProvider(ExchangeProvider):
    name: str = "binance"
    base_url: str = "https://api.binance.com"

    async def fetch_klines(self, client, symbol, interval, start_ms, end_ms) -> list[list]:
        resp = await client.get(
            f"{self.base_url}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=10.0,
        )
        if resp.status_code == 400:
            body = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            code = body.get("code")
            msg = body.get("msg", "")
            if code == -1121 or "Invalid symbol" in msg:
                raise SymbolNotFound(f"Binance: {symbol} not found")
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    async def fetch_price_at_ms(self, client, symbol, ts_ms) -> float | None:
        resp = await client.get(
            f"{self.base_url}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": "1m",
                "startTime": ts_ms,
                "limit": 1,
            },
            timeout=10.0,
        )
        if resp.status_code == 400:
            body = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if body.get("code") == -1121 or "Invalid symbol" in body.get("msg", ""):
                raise SymbolNotFound(f"Binance: {symbol} not found")
            resp.raise_for_status()
        resp.raise_for_status()
        klines = resp.json()
        if not klines:
            return None
        return float(klines[0][4])


# ---------------------------------------------------------------------------
# OKX
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OKXProvider(ExchangeProvider):
    name: str = "okx"
    base_url: str = "https://www.okx.com"

    async def fetch_klines(self, client, symbol, interval, start_ms, end_ms) -> list[list]:
        okx_sym = _okx_symbol(symbol)
        # OKX bar intervals: 1m, 5m, 15m, 1H, 4H
        okx_interval = interval
        if interval == "1h":
            okx_interval = "1H"
        elif interval == "4h":
            okx_interval = "4H"

        all_candles: list[list] = []
        after = str(end_ms)

        # OKX returns max 100 candles per request, paginate backwards
        for _ in range(10):  # safety limit
            resp = await client.get(
                f"{self.base_url}/api/v5/market/history-candles",
                params={
                    "instId": okx_sym,
                    "bar": okx_interval,
                    "before": str(start_ms - 1),
                    "after": after,
                    "limit": "100",
                },
                timeout=10.0,
            )
            if resp.status_code in (400, 404):
                raise SymbolNotFound(f"OKX: {okx_sym} not found")
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != "0":
                raise SymbolNotFound(f"OKX: {okx_sym} error: {body.get('msg', '')}")
            data = body.get("data", [])
            if not data:
                break
            for c in data:
                # OKX format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                ts = int(c[0])
                if ts < start_ms:
                    continue
                all_candles.append(_binance_kline(ts, c[1], c[2], c[3], c[4], c[5]))
            # OKX returns newest first; paginate using oldest ts
            oldest_ts = data[-1][0]
            after = oldest_ts
            if int(oldest_ts) <= start_ms:
                break

        # Sort chronologically (OKX returns newest-first)
        all_candles.sort(key=lambda x: x[0])
        return all_candles

    async def fetch_price_at_ms(self, client, symbol, ts_ms) -> float | None:
        okx_sym = _okx_symbol(symbol)
        resp = await client.get(
            f"{self.base_url}/api/v5/market/history-candles",
            params={
                "instId": okx_sym,
                "bar": "1m",
                "after": str(ts_ms + 60_000),
                "before": str(ts_ms - 1),
                "limit": "1",
            },
            timeout=10.0,
        )
        if resp.status_code in (400, 404):
            raise SymbolNotFound(f"OKX: {okx_sym} not found")
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0":
            raise SymbolNotFound(f"OKX: {okx_sym} error: {body.get('msg', '')}")
        data = body.get("data", [])
        if not data:
            return None
        return float(data[0][4])


# ---------------------------------------------------------------------------
# Kraken
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KrakenProvider(ExchangeProvider):
    name: str = "kraken"
    base_url: str = "https://api.kraken.com"

    async def fetch_klines(self, client, symbol, interval, start_ms, end_ms) -> list[list]:
        kraken_sym = _kraken_symbol(symbol)
        kraken_interval = _KRAKEN_INTERVAL_MAP.get(interval, 60)

        resp = await client.get(
            f"{self.base_url}/0/public/OHLC",
            params={
                "pair": kraken_sym,
                "interval": kraken_interval,
                "since": start_ms // 1000,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            errors = body["error"]
            for err in errors:
                if "Unknown asset pair" in str(err):
                    raise SymbolNotFound(f"Kraken: {kraken_sym} not found")
            raise ExchangeError(f"Kraken error: {errors}")

        # Result key is the pair name (varies), grab first key
        result = body.get("result", {})
        result.pop("last", None)
        if not result:
            return []

        pair_key = next(iter(result))
        candles: list[list] = []
        for c in result[pair_key]:
            # Kraken format: [time, open, high, low, close, vwap, volume, count]
            ts_ms_val = int(c[0]) * 1000
            if ts_ms_val > end_ms:
                break
            candles.append(
                _binance_kline(ts_ms_val, str(c[1]), str(c[2]), str(c[3]), str(c[4]), str(c[6]))
            )
        return candles

    async def fetch_price_at_ms(self, client, symbol, ts_ms) -> float | None:
        kraken_sym = _kraken_symbol(symbol)
        resp = await client.get(
            f"{self.base_url}/0/public/OHLC",
            params={
                "pair": kraken_sym,
                "interval": 1,  # 1 minute
                "since": ts_ms // 1000,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            for err in body["error"]:
                if "Unknown asset pair" in str(err):
                    raise SymbolNotFound(f"Kraken: {kraken_sym} not found")
            raise ExchangeError(f"Kraken error: {body['error']}")

        result = body.get("result", {})
        result.pop("last", None)
        if not result:
            return None
        pair_key = next(iter(result))
        data = result[pair_key]
        if not data:
            return None
        return float(data[0][4])  # close price


# ---------------------------------------------------------------------------
# Yahoo Finance (stocks and forex)
# ---------------------------------------------------------------------------

_YF_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "1h",  # YF doesn't have 4h; fetch 1h and let caller aggregate
}


def _yf_symbol(asset: str) -> str:
    """Normalise asset to Yahoo Finance ticker.

    Stocks: 'AAPL' -> 'AAPL', 'AAPL.US' -> 'AAPL'
    Forex: 'EURUSD' -> 'EURUSD=X', 'EUR/USD' -> 'EURUSD=X'
    """
    s = asset.upper().replace("/", "").replace("-", "").replace(" ", "")
    # Strip exchange suffixes
    for suffix in (".US", ".NYSE", ".NASDAQ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


@dataclass(frozen=True)
class YahooFinanceProvider(ExchangeProvider):
    """Price data from Yahoo Finance chart API (stocks, ETFs, forex)."""

    name: str = "yahoo"
    base_url: str = "https://query1.finance.yahoo.com"

    async def fetch_klines(self, client, symbol, interval, start_ms, end_ms) -> list[list]:
        yf_sym = _yf_symbol(symbol)
        yf_interval = _YF_INTERVAL_MAP.get(interval, "1h")
        period1 = start_ms // 1000
        period2 = end_ms // 1000

        resp = await client.get(
            f"{self.base_url}/v8/finance/chart/{yf_sym}",
            params={
                "period1": period1,
                "period2": period2,
                "interval": yf_interval,
                "includePrePost": "false",
            },
            headers={"User-Agent": "TradeArena/1.0"},
            timeout=15.0,
        )
        if resp.status_code == 404:
            raise SymbolNotFound(f"Yahoo: {yf_sym} not found")
        if resp.status_code == 422:
            raise SymbolNotFound(f"Yahoo: {yf_sym} invalid symbol")
        resp.raise_for_status()

        body = resp.json()
        chart = body.get("chart", {})
        if chart.get("error"):
            err_desc = chart["error"].get("description", "")
            if "No data found" in err_desc or "not found" in err_desc.lower():
                raise SymbolNotFound(f"Yahoo: {yf_sym} — {err_desc}")
            raise ExchangeError(f"Yahoo: {err_desc}")

        results = chart.get("result")
        if not results:
            return []

        result = results[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        candles: list[list] = []
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue
            ts_ms_val = ts * 1000
            candles.append(
                _binance_kline(
                    ts_ms_val,
                    str(opens[i] or 0),
                    str(highs[i] or 0),
                    str(lows[i] or 0),
                    str(closes[i]),
                    str(volumes[i] or 0),
                )
            )
        return candles

    async def fetch_price_at_ms(self, client, symbol, ts_ms) -> float | None:
        yf_sym = _yf_symbol(symbol)
        period1 = ts_ms // 1000
        period2 = period1 + 120  # 2-minute window

        resp = await client.get(
            f"{self.base_url}/v8/finance/chart/{yf_sym}",
            params={
                "period1": period1,
                "period2": period2,
                "interval": "1m",
                "includePrePost": "false",
            },
            headers={"User-Agent": "TradeArena/1.0"},
            timeout=15.0,
        )
        if resp.status_code in (404, 422):
            raise SymbolNotFound(f"Yahoo: {yf_sym} not found")
        resp.raise_for_status()

        body = resp.json()
        chart = body.get("chart", {})
        if chart.get("error"):
            err_desc = chart["error"].get("description", "")
            if "No data found" in err_desc or "not found" in err_desc.lower():
                raise SymbolNotFound(f"Yahoo: {yf_sym} — {err_desc}")
            raise ExchangeError(f"Yahoo: {err_desc}")

        results = chart.get("result")
        if not results:
            return None

        quote = results[0].get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close", [])
        for c in closes:
            if c is not None:
                return float(c)
        return None


# ---------------------------------------------------------------------------
# Default provider chains by asset type
# ---------------------------------------------------------------------------

CRYPTO_PROVIDERS: list[ExchangeProvider] = [
    BinanceProvider(),
    OKXProvider(),
    KrakenProvider(),
]

STOCK_PROVIDERS: list[ExchangeProvider] = [
    YahooFinanceProvider(),
]

FOREX_PROVIDERS: list[ExchangeProvider] = [
    YahooFinanceProvider(),
]

# Backwards-compatible alias
DEFAULT_PROVIDERS: list[ExchangeProvider] = CRYPTO_PROVIDERS


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------


def check_halt(klines: list[list], threshold: int = 5) -> bool:
    """Return True if trading appears halted (many consecutive identical candles)."""
    if len(klines) < threshold:
        return False
    streak = 0
    for candle in klines:
        o, h, lo, c = candle[1], candle[2], candle[3], candle[4]
        if o == h == lo == c:
            streak += 1
            if streak >= threshold:
                return True
        else:
            streak = 0
    return False


def check_gap(klines: list[list], interval: str, tolerance: float = 3.0) -> bool:
    """Return True if klines contain a gap larger than tolerance * interval."""
    if len(klines) < 2:
        return False
    interval_ms_map = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
    }
    expected_ms = interval_ms_map.get(interval, 3_600_000)
    max_gap = expected_ms * tolerance

    for i in range(1, len(klines)):
        gap = int(klines[i][0]) - int(klines[i - 1][0])
        if gap > max_gap:
            return True
    return False


# ---------------------------------------------------------------------------
# Fetch with fallback
# ---------------------------------------------------------------------------


async def fetch_klines_with_fallback(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    providers: list[ExchangeProvider] | None = None,
) -> list[list]:
    """Try each exchange provider in order until one returns valid data.

    Raises ExchangeError if all providers fail.
    Returns empty list only if symbol is valid but no data exists in range.
    """
    providers = providers or DEFAULT_PROVIDERS
    last_error: Exception | None = None
    delisted_count = 0

    for provider in providers:
        try:
            klines = await provider.fetch_klines(client, symbol, interval, start_ms, end_ms)
            if not klines:
                logger.info(
                    "Exchange %s returned no klines for %s, trying next",
                    provider.name,
                    symbol,
                )
                continue

            if check_halt(klines):
                logger.warning(
                    "Exchange %s shows halted trading for %s, trying next",
                    provider.name,
                    symbol,
                )
                continue

            if check_gap(klines, interval):
                logger.warning(
                    "Exchange %s has data gaps for %s, trying next",
                    provider.name,
                    symbol,
                )
                continue

            logger.info(
                "Resolved %s klines from %s (%d candles)",
                symbol,
                provider.name,
                len(klines),
            )
            return klines

        except SymbolNotFound:
            delisted_count += 1
            logger.info("Symbol %s not found on %s", symbol, provider.name)
            continue
        except (httpx.HTTPError, ExchangeError) as exc:
            last_error = exc
            logger.warning("Exchange %s failed for %s: %s", provider.name, symbol, exc)
            continue

    if delisted_count == len(providers):
        raise SymbolNotFound(f"Symbol {symbol} not found on any exchange (likely delisted)")
    if last_error:
        raise ExchangeError(f"All exchanges failed for {symbol}: {last_error}")
    return []


async def fetch_price_with_fallback(
    client: httpx.AsyncClient,
    symbol: str,
    ts_ms: int,
    providers: list[ExchangeProvider] | None = None,
) -> float | None:
    """Fetch price at a specific timestamp, trying each provider in order."""
    providers = providers or DEFAULT_PROVIDERS
    delisted_count = 0

    for provider in providers:
        try:
            price = await provider.fetch_price_at_ms(client, symbol, ts_ms)
            if price is not None:
                logger.info(
                    "Got price for %s from %s: %s",
                    symbol,
                    provider.name,
                    price,
                )
                return price
            logger.info(
                "Exchange %s returned no price for %s at %d, trying next",
                provider.name,
                symbol,
                ts_ms,
            )
        except SymbolNotFound:
            delisted_count += 1
            logger.info("Symbol %s not found on %s", symbol, provider.name)
            continue
        except (httpx.HTTPError, ExchangeError) as exc:
            logger.warning(
                "Exchange %s price lookup failed for %s: %s",
                provider.name,
                symbol,
                exc,
            )
            continue

    if delisted_count == len(providers):
        raise SymbolNotFound(f"Symbol {symbol} not found on any exchange (likely delisted)")
    return None
