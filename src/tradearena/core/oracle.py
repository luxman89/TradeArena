"""Price oracle — resolves signal outcomes using multi-exchange price data.

Fetches historical kline data to determine whether signals hit their
target_price, stop_loss, or moved in the predicted direction.

Uses a fallback chain: Binance -> OKX -> Kraken. Handles delistings,
trading halts, and data gaps by trying the next exchange automatically.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from tradearena.core import cache
from tradearena.core.asset_types import AssetType, classify_asset
from tradearena.core.exchanges import (
    CRYPTO_PROVIDERS,
    FOREX_PROVIDERS,
    STOCK_PROVIDERS,
    ExchangeProvider,
    SymbolNotFound,
    fetch_klines_with_fallback,
    fetch_price_with_fallback,
)
from tradearena.db.database import SignalORM
from tradearena.models.signal import Outcome

logger = logging.getLogger(__name__)

DIRECTION_THRESHOLD = 0.005  # 0.5% minimum move for no-target signals
BULLISH_ACTIONS = {"buy", "long", "yes"}
BEARISH_ACTIONS = {"sell", "short", "no"}


def parse_timeframe(tf: str | None) -> timedelta:
    """Convert timeframe string to timedelta. Default '1d' if None."""
    if not tf:
        return timedelta(days=1)
    match = re.match(r"^(\d+)([hdw])$", tf.lower())
    if not match:
        return timedelta(days=1)
    value, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    return timedelta(days=1)


def asset_to_symbol(asset: str, asset_type: AssetType | None = None) -> str:
    """Convert asset string to the appropriate exchange symbol.

    Crypto: 'BTC/USDT' -> 'BTCUSDT', 'BTC' -> 'BTCUSDT'
    Stock:  'AAPL' -> 'AAPL', 'AAPL.US' -> 'AAPL'
    Forex:  'EUR/USD' -> 'EURUSD=X', 'EURUSD' -> 'EURUSD=X'
    """
    if asset_type is None:
        asset_type = classify_asset(asset)

    symbol = asset.upper().replace(" ", "")

    if asset_type == AssetType.CRYPTO:
        symbol = symbol.replace("/", "").replace("-", "")
        if not symbol.endswith("USDT") and not symbol.endswith("BUSD"):
            symbol += "USDT"
        return symbol

    if asset_type == AssetType.FOREX:
        symbol = symbol.replace("/", "").replace("-", "")
        if not symbol.endswith("=X"):
            symbol += "=X"
        return symbol

    # Stock: strip common suffixes, keep ticker clean
    symbol = symbol.replace("/", "").replace("-", "")
    for suffix in (".US", ".NYSE", ".NASDAQ"):
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    return symbol


def _providers_for_asset(asset_type: AssetType) -> list[ExchangeProvider]:
    """Return the provider chain appropriate for this asset type."""
    if asset_type == AssetType.STOCK:
        return STOCK_PROVIDERS
    if asset_type == AssetType.FOREX:
        return FOREX_PROVIDERS
    return CRYPTO_PROVIDERS


def _pick_interval(delta: timedelta) -> str:
    """Choose a kline interval that gives a reasonable number of candles."""
    hours = delta.total_seconds() / 3600
    if hours <= 4:
        return "5m"
    if hours <= 24:
        return "15m"
    if hours <= 168:  # 7 days
        return "1h"
    return "4h"


async def fetch_klines(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    providers: list[ExchangeProvider] | None = None,
) -> list[list]:
    """Fetch kline/candlestick data with caching and multi-exchange fallback."""
    cached = cache.get(symbol, interval, start_ms, end_ms)
    if cached is not None:
        return cached

    data = await fetch_klines_with_fallback(
        client, symbol, interval, start_ms, end_ms, providers=providers
    )
    if data:
        cache.put(symbol, interval, start_ms, end_ms, data)
    return data


async def fetch_price_at(
    client: httpx.AsyncClient,
    symbol: str,
    at_time: datetime,
    providers: list[ExchangeProvider] | None = None,
) -> float | None:
    """Get the closing price of the 1m candle nearest to at_time."""
    ts_ms = int(at_time.timestamp() * 1000)
    # Use cache with a synthetic end_ms (start + 1 minute)
    end_ms = ts_ms + 60_000
    cached = cache.get(symbol, "1m", ts_ms, end_ms)
    if cached is not None:
        if not cached:
            return None
        return float(cached[0][4])

    price = await fetch_price_with_fallback(client, symbol, ts_ms, providers=providers)
    # Cache the result (store as single-element kline list for cache compat)
    if price is not None:
        kline = [ts_ms, "0", "0", "0", str(price), "0", end_ms, "0", 0, "0", "0", "0"]
        cache.put(symbol, "1m", ts_ms, end_ms, [kline])
    else:
        cache.put(symbol, "1m", ts_ms, end_ms, [])
    return price


def _resolve_with_targets(
    klines: list[list],
    action: str,
    target_price: float,
    stop_loss: float,
) -> tuple[str, float]:
    """Walk klines to check if target or stop was hit first.

    Returns (outcome, outcome_price).
    """
    is_bullish = action.lower() in BULLISH_ACTIONS
    for candle in klines:
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])

        if is_bullish:
            target_hit = high >= target_price
            stop_hit = low <= stop_loss
        else:
            target_hit = low <= target_price
            stop_hit = high >= stop_loss

        if target_hit and stop_hit:
            return Outcome.NEUTRAL, close
        if target_hit:
            return Outcome.WIN, target_price
        if stop_hit:
            return Outcome.LOSS, stop_loss

    # Neither hit during the timeframe
    close = float(klines[-1][4]) if klines else 0.0
    return Outcome.NEUTRAL, close


def _resolve_by_direction(
    open_price: float,
    close_price: float,
    action: str,
) -> tuple[str, float]:
    """Compare open vs close price with 0.5% threshold.

    Returns (outcome, outcome_price).
    """
    if open_price == 0:
        return Outcome.NEUTRAL, close_price

    pct_change = (close_price - open_price) / open_price
    is_bullish = action.lower() in BULLISH_ACTIONS

    if is_bullish:
        if pct_change >= DIRECTION_THRESHOLD:
            return Outcome.WIN, close_price
        if pct_change <= -DIRECTION_THRESHOLD:
            return Outcome.LOSS, close_price
    else:
        if pct_change <= -DIRECTION_THRESHOLD:
            return Outcome.WIN, close_price
        if pct_change >= DIRECTION_THRESHOLD:
            return Outcome.LOSS, close_price

    return Outcome.NEUTRAL, close_price


async def resolve_signal(
    signal: SignalORM,
    client: httpx.AsyncClient,
) -> tuple[str, float, datetime] | None:
    """Resolve a single signal's outcome using multi-exchange price data.

    Routes to the correct provider chain based on asset type (crypto, stock, forex).
    Returns (outcome, outcome_price, outcome_at) or None if not yet eligible.
    """
    now = datetime.now(UTC)
    tf_delta = parse_timeframe(signal.timeframe)
    eligible_at = signal.committed_at.replace(tzinfo=UTC) + tf_delta

    if eligible_at > now:
        return None

    # Determine asset type and route to correct providers
    raw_type = getattr(signal, "asset_type", None)
    if isinstance(raw_type, str) and raw_type in AssetType._value2member_map_:
        asset_type = AssetType(raw_type)
    else:
        asset_type = classify_asset(signal.asset)
    symbol = asset_to_symbol(signal.asset, asset_type)
    providers = _providers_for_asset(asset_type)

    start_ms = int(signal.committed_at.replace(tzinfo=UTC).timestamp() * 1000)
    end_ms = int(eligible_at.timestamp() * 1000)

    if signal.target_price is not None and signal.stop_loss is not None:
        interval = _pick_interval(tf_delta)
        klines = await fetch_klines(client, symbol, interval, start_ms, end_ms, providers=providers)
        if not klines:
            return None
        outcome, outcome_price = _resolve_with_targets(
            klines, signal.action, signal.target_price, signal.stop_loss
        )
    else:
        open_price = await fetch_price_at(
            client, symbol, signal.committed_at.replace(tzinfo=UTC), providers=providers
        )
        close_price = await fetch_price_at(client, symbol, eligible_at, providers=providers)
        if open_price is None or close_price is None:
            return None
        outcome, outcome_price = _resolve_by_direction(open_price, close_price, signal.action)

    return outcome, outcome_price, now


async def resolve_pending_signals(db: Session) -> dict[str, int]:
    """Resolve all pending signals whose timeframe has elapsed.

    Returns counts: {resolved, errors, skipped, delisted}.
    """
    pending = db.query(SignalORM).filter(SignalORM.outcome.is_(None)).all()

    stats = {"resolved": 0, "errors": 0, "skipped": 0, "delisted": 0}
    if not pending:
        return stats

    async with httpx.AsyncClient() as client:
        for signal in pending:
            try:
                result = await resolve_signal(signal, client)
                if result is None:
                    stats["skipped"] += 1
                    continue

                outcome, outcome_price, outcome_at = result
                signal.outcome = outcome
                signal.outcome_price = outcome_price
                signal.outcome_at = outcome_at
                stats["resolved"] += 1

                # Courtesy throttle between exchange requests
                await asyncio.sleep(0.05)

            except SymbolNotFound:
                logger.warning(
                    "Signal %s asset %s delisted from all exchanges",
                    signal.signal_id,
                    signal.asset,
                )
                signal.outcome = Outcome.NEUTRAL
                signal.outcome_price = 0.0
                signal.outcome_at = datetime.now(UTC)
                stats["delisted"] += 1

            except Exception:
                logger.exception("Failed to resolve signal %s", signal.signal_id)
                stats["errors"] += 1

    db.commit()
    return stats
