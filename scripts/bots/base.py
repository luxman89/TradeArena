"""Base class for all TradeArena signal bots."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

# Allow importing the SDK from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sdk.client import TradeArenaClient  # noqa: E402


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


class BaseBot:
    """Base class for TradeArena signal bots.

    Subclasses must set class attributes:
        name, email, division, strategy_description, assets, timeframe
    and implement generate_signal(symbol, candles) -> dict | None.
    """

    name: str
    email: str
    division: str = "crypto"
    strategy_description: str
    assets: list[str]
    timeframe: str = "1h"

    # Path to persisted credentials (one JSON file shared by all bots)
    _CREDS_FILE = Path(__file__).resolve().parents[2] / ".bot_credentials.json"

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url
        self.api_key: str | None = None
        self.creator_id: str | None = None
        self._client: TradeArenaClient | None = None

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self) -> None:
        """Register this bot as a new creator, or reuse saved credentials on 409."""
        # Try to load existing credentials first
        creds = self._load_creds()
        if self.email in creds:
            saved = creds[self.email]
            self.creator_id = saved["creator_id"]
            self.api_key = saved["api_key"]
            self._client = TradeArenaClient(api_key=self.api_key, base_url=self.base_url)
            return

        resp = httpx.post(
            f"{self.base_url}/creator/register",
            json={
                "display_name": self.name,
                "division": self.division,
                "strategy_description": self.strategy_description,
                "email": self.email,
            },
            timeout=10,
        )
        if resp.status_code == 409:
            raise RuntimeError(
                f"Creator with email '{self.email}' already exists but no saved "
                f"credentials found. Delete .bot_credentials.json and re-run."
            )
        resp.raise_for_status()
        data = resp.json()
        self.creator_id = data["creator_id"]
        self.api_key = data["api_key"]
        self._client = TradeArenaClient(api_key=self.api_key, base_url=self.base_url)
        self._save_creds(creds)

    def _load_creds(self) -> dict:
        if self._CREDS_FILE.exists():
            try:
                return json.loads(self._CREDS_FILE.read_text())
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save_creds(self, existing: dict) -> None:
        existing[self.email] = {"creator_id": self.creator_id, "api_key": self.api_key}
        self._CREDS_FILE.write_text(json.dumps(existing, indent=2))

    # ── Market data ───────────────────────────────────────────────────────────

    def fetch_ohlcv(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> list[dict]:
        """Fetch OHLCV candles from Binance public API.

        symbol: 'BTC/USDT' or 'BTCUSDT' both accepted.
        Returns list of dicts with keys: open, high, low, close, volume.
        """
        binance_symbol = symbol.replace("/", "").upper()
        resp = httpx.get(
            BINANCE_KLINES,
            params={"symbol": binance_symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        candles = []
        for k in resp.json():
            candles.append(
                {
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )
        return candles

    # ── Strategy (override) ───────────────────────────────────────────────────

    def generate_signal(self, symbol: str, candles: list[dict]) -> dict | None:
        """Return a signal payload dict or None if no trade is warranted."""
        raise NotImplementedError

    def forced_signal(self, symbol: str, candles: list[dict]) -> dict:
        """Fallback signal based on price vs SMA(20) — always fires.

        Used with --force to guarantee at least one submission per asset,
        useful for live testing when market conditions are neutral.
        """
        closes = [c["close"] for c in candles]
        close = closes[-1]
        sma = sum(closes[-20:]) / min(20, len(closes))
        action = "buy" if close > sma else "sell"
        pct = abs(close - sma) / sma
        confidence = round(min(0.80, max(0.30, pct * 20)), 4)
        return {
            "asset": symbol,
            "action": action,
            "confidence": confidence,
            "timeframe": self.timeframe,
            "reasoning": (
                f"[FORCED] Price of {symbol} ({close:.4f}) is {'above' if action == 'buy' else 'below'} "
                f"the 20-period SMA ({sma:.4f}) by {pct*100:.2f}%. This directional bias "
                f"combined with the {self.__class__.__name__} strategy context suggests a "
                f"{action.upper()} signal. Market structure supports a continuation move "
                f"in the direction of the prevailing trend."
            ),
            "supporting_data": {
                "sma_20": round(sma, 4),
                "close": close,
                "pct_from_sma": round(pct * 100, 4),
            },
        }

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, force: bool = False) -> list[dict]:
        """Fetch data for each asset, generate signals, and emit them.

        If force=True, falls back to forced_signal when generate_signal returns None.
        """
        if self._client is None:
            raise RuntimeError("Call register() before run()")
        results = []
        for symbol in self.assets:
            try:
                candles = self.fetch_ohlcv(symbol, interval=self.timeframe)
                signal = self.generate_signal(symbol, candles)
                if signal is None:
                    if force:
                        signal = self.forced_signal(symbol, candles)
                        print(f"  [{self.name}] {symbol}: no signal (using forced fallback)")
                    else:
                        print(f"  [{self.name}] {symbol}: no signal")
                        continue
                resp = self._client.emit(signal)
                results.append(resp)
                print(
                    f"  [{self.name}] {symbol}: {signal['action'].upper()} "
                    f"conf={signal['confidence']:.2f} -> {resp.get('signal_id', '?')[:8]}..."
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  [{self.name}] {symbol}: ERROR — {exc}")
        return results
