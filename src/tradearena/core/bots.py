"""In-process trading bots that auto-submit signals on a recurring schedule.

Three strategy bots run as part of the background loop:
  - RSI Ranger  (mean-reversion, RSI 14)
  - EMA Crossover (trend-following, EMA 9/21)
  - BB Squeeze    (volatility-breakout, Bollinger Bands 20/2σ)

Each bot generates at most one signal per run cycle. Signals are committed
and stored directly in the DB without going through HTTP.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import UTC, datetime
from typing import Any

from tradearena.core.commitment import build_committed_signal
from tradearena.db.database import CreatorORM, SignalORM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot creator definitions
# ---------------------------------------------------------------------------

BOTS = [
    {
        "id": "rsi-ranger-b0t1",
        "display_name": "RSI Ranger",
        "division": "crypto",
        "api_key_dev": "ta-rsi-ranger-bot-key",
        "api_key_hash": hashlib.sha256(b"ta-rsi-ranger-bot-key").hexdigest(),
    },
    {
        "id": "ema-cross-b0t2",
        "display_name": "EMA Crossover",
        "division": "crypto",
        "api_key_dev": "ta-ema-cross-bot-key",
        "api_key_hash": hashlib.sha256(b"ta-ema-cross-bot-key").hexdigest(),
    },
    {
        "id": "bb-squeeze-b0t3",
        "display_name": "BB Squeeze",
        "division": "crypto",
        "api_key_dev": "ta-bb-squeeze-bot-key",
        "api_key_hash": hashlib.sha256(b"ta-bb-squeeze-bot-key").hexdigest(),
    },
]

_ASSETS_MAJOR = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
_ASSETS_ALL = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT", "LINK/USDT"]
_TIMEFRAMES = ["1h", "4h", "1d"]


# ---------------------------------------------------------------------------
# Strategy generators  (return a signal dict or None when no setup fires)
# ---------------------------------------------------------------------------


def _rsi_ranger_signal(rng: random.Random) -> dict[str, Any] | None:
    """RSI mean-reversion: fire on RSI < 30 (buy) or RSI > 70 (sell)."""
    asset = rng.choice(_ASSETS_ALL)
    rsi = rng.uniform(15, 85)

    if rsi < 30:
        action = "buy"
        confidence = round(rng.uniform(0.60, 0.82), 2)
        reasoning = (
            f"RSI(14) on {asset} has dropped to {rsi:.1f}, deeply oversold territory. "
            "Historical mean-reversion patterns show a high bounce probability from "
            "this zone. Volume profile confirms visible institutional accumulation. "
            "Risk is defined with a tight stop below the recent swing low."
        )
    elif rsi > 70:
        action = "sell"
        confidence = round(rng.uniform(0.60, 0.82), 2)
        reasoning = (
            f"RSI(14) on {asset} has surged to {rsi:.1f}, entering overbought territory. "
            "Mean-reversion signals are active after the extended rally without consolidation. "
            "Bearish divergence on the hourly chart confirms weakening upside momentum. "
            "Invalidation level is the recent swing high above current price."
        )
    else:
        return None  # No extreme reading — no signal

    timeframe = rng.choice(_TIMEFRAMES)
    return {
        "creator_id": "rsi-ranger-b0t1",
        "asset": asset,
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_data": {
            "rsi_14": round(rsi, 2),
            "strategy": "mean_reversion",
            "signal_type": "rsi_extreme",
            "timeframe_context": timeframe,
        },
        "timeframe": timeframe,
    }


def _ema_cross_signal(rng: random.Random) -> dict[str, Any] | None:
    """EMA 9/21 crossover trend-following: fire on golden or death cross."""
    asset = rng.choice(_ASSETS_MAJOR)
    # Simulate normalised EMA values around 100
    ema9 = rng.uniform(94, 106)
    ema21 = 100.0
    diff_pct = (ema9 - ema21) / ema21 * 100

    if abs(diff_pct) < 0.5:
        return None  # Too close — no clean crossover signal

    if ema9 > ema21:
        action = "long"
        confidence = round(min(0.85, 0.52 + abs(diff_pct) * 0.06), 2)
        reasoning = (
            f"EMA 9 crossed above EMA 21 on {asset} — golden cross confirmed. "
            "Trend momentum is accelerating with price holding above both moving averages. "
            "Volume confirmation on the breakout candle adds conviction to the bullish bias. "
            "Target is the next key resistance; stop is placed below the 21 EMA."
        )
    else:
        action = "short"
        confidence = round(min(0.85, 0.52 + abs(diff_pct) * 0.06), 2)
        reasoning = (
            f"EMA 9 crossed below EMA 21 on {asset} — death cross signal active. "
            "Bearish momentum confirmed with price trading under both exponential averages. "
            "The crossover zone has acted as resistance on multiple retests this session. "
            "Stop above the 9 EMA invalidation level protects the short position."
        )

    timeframe = rng.choice(["1h", "4h"])
    return {
        "creator_id": "ema-cross-b0t2",
        "asset": asset,
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_data": {
            "ema_9_normalised": round(ema9, 4),
            "ema_21_normalised": round(ema21, 4),
            "crossover_pct": round(diff_pct, 3),
            "strategy": "trend_following",
        },
        "timeframe": timeframe,
    }


def _bb_squeeze_signal(rng: random.Random) -> dict[str, Any] | None:
    """Bollinger Band squeeze + touch breakout."""
    asset = rng.choice(["BTC/USDT", "ETH/USDT", "BNB/USDT"])
    bb_width = rng.uniform(0.3, 6.0)  # % bandwidth
    price_pos = rng.uniform(0, 100)  # % position within band (0=lower, 100=upper)

    if bb_width > 2.5:
        return None  # Bands too wide — no squeeze setup

    if price_pos < 20:
        action = "buy"
        confidence = round(rng.uniform(0.58, 0.76), 2)
        reasoning = (
            f"Bollinger Band squeeze on {asset}: bandwidth compressed to {bb_width:.2f}%. "
            "Price is touching the lower band after a prolonged volatility contraction phase. "
            "Squeeze breakouts from compressed bands typically produce strong directional moves. "
            "Long bias targets the midline first, then upper band extension zone."
        )
    elif price_pos > 80:
        action = "sell"
        confidence = round(rng.uniform(0.58, 0.76), 2)
        reasoning = (
            f"Bollinger Band squeeze on {asset}: bandwidth at {bb_width:.2f}%, historically tight. "
            "Price is pinned at the upper band after the volatility contraction sequence. "
            "Upper band rejection after a squeeze phase is a high-probability setup. "
            "Short targets the midline and lower band support with stop above the squeeze high."
        )
    else:
        return None  # Mid-band — no edge

    timeframe = rng.choice(["1h", "4h"])
    return {
        "creator_id": "bb-squeeze-b0t3",
        "asset": asset,
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_data": {
            "bb_width_pct": round(bb_width, 2),
            "price_position_pct": round(price_pos, 1),
            "strategy": "volatility_breakout",
            "squeeze_active": True,
        },
        "timeframe": timeframe,
    }


_BOT_GENERATORS = [
    ("rsi-ranger-b0t1", _rsi_ranger_signal),
    ("ema-cross-b0t2", _ema_cross_signal),
    ("bb-squeeze-b0t3", _bb_squeeze_signal),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def ensure_bots_registered(db) -> None:
    """Create bot creator rows if they don't already exist."""
    now = datetime.now(UTC)
    for bot in BOTS:
        if not db.query(CreatorORM).filter(CreatorORM.id == bot["id"]).first():
            db.add(
                CreatorORM(
                    id=bot["id"],
                    display_name=bot["display_name"],
                    division=bot["division"],
                    api_key_dev=bot["api_key_dev"],
                    api_key_hash=bot["api_key_hash"],
                    created_at=now,
                )
            )
            logger.info("Registered bot creator: %s", bot["display_name"])
    db.commit()


def run_bot_signals(db) -> int:
    """Generate and store one signal per bot (when strategy fires).

    Uses the current UTC minute as the RNG seed so each hourly cycle
    produces a different (but deterministic) set of signals.

    Returns the number of signals submitted.
    """
    # Seed changes every minute so re-runs within the same minute are idempotent
    seed = int(datetime.now(UTC).timestamp() // 60)
    submitted = 0

    for bot_id, generator in _BOT_GENERATORS:
        rng = random.Random(seed + hash(bot_id) % (2**31))
        signal_data = generator(rng)
        if signal_data is None:
            continue

        try:
            committed = build_committed_signal(signal_data)

            # Skip exact duplicates (same hash = same nonce, shouldn't happen but guard anyway)
            exists = (
                db.query(SignalORM)
                .filter(SignalORM.commitment_hash == committed["commitment_hash"])
                .first()
            )
            if exists:
                continue

            db.add(
                SignalORM(
                    signal_id=committed["signal_id"],
                    creator_id=committed["creator_id"],
                    asset=committed["asset"],
                    action=committed["action"],
                    confidence=committed["confidence"],
                    reasoning=committed["reasoning"],
                    supporting_data=committed["supporting_data"],
                    target_price=committed.get("target_price"),
                    stop_loss=committed.get("stop_loss"),
                    timeframe=committed.get("timeframe"),
                    commitment_hash=committed["commitment_hash"],
                    committed_at=datetime.now(UTC),
                    outcome=None,
                )
            )
            submitted += 1
            logger.info("Bot %s: %s %s", bot_id, signal_data["action"], signal_data["asset"])

        except Exception:
            logger.exception("Bot %s signal generation failed", bot_id)

    if submitted:
        db.commit()

    return submitted
