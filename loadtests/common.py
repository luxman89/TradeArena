"""Shared helpers for load tests — seed data, payloads, and config."""

from __future__ import annotations

import hashlib
import os
import random
import uuid

# ---------------------------------------------------------------------------
# Configuration — override via env vars when running against real infra
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("LOADTEST_BASE_URL", "http://localhost:8000")
WS_URL = os.getenv("LOADTEST_WS_URL", "ws://localhost:8000/ws")

# Number of test creators to seed (each gets an API key)
NUM_CREATORS = int(os.getenv("LOADTEST_NUM_CREATORS", "20"))

# ---------------------------------------------------------------------------
# Test creator pool
# ---------------------------------------------------------------------------

DIVISIONS = ["crypto", "polymarket", "multi"]
ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT",
          "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT"]
ACTIONS = ["buy", "sell", "long", "short"]
TIMEFRAMES = ["1h", "4h", "1d", "1w"]


def make_creator_id(index: int) -> str:
    return f"loadtest-creator-{index:04d}"


def make_api_key(index: int) -> str:
    return f"ta-loadtest-{index:04d}-{'a' * 24}"


def make_api_key_hash(index: int) -> str:
    return hashlib.sha256(make_api_key(index).encode()).hexdigest()


def creator_pool() -> list[dict]:
    """Return list of {id, api_key, division} for all test creators."""
    return [
        {
            "id": make_creator_id(i),
            "api_key": make_api_key(i),
            "division": DIVISIONS[i % len(DIVISIONS)],
        }
        for i in range(NUM_CREATORS)
    ]


# ---------------------------------------------------------------------------
# Payload generators
# ---------------------------------------------------------------------------

_REASONING_TEMPLATES = [
    (
        "Technical analysis shows a clear {pattern} pattern forming on the {tf} chart. "
        "RSI indicates {rsi_state} with volume confirming the move. Key support at "
        "{support} and resistance at {resistance}. Multiple indicators align for this trade."
    ),
    (
        "Fundamental catalyst: {catalyst}. On-chain metrics show {onchain}. "
        "Combined with the {pattern} setup on {tf} timeframe, risk-reward ratio "
        "is favorable at current levels. Position sizing accounts for volatility."
    ),
    (
        "Market structure analysis reveals {pattern} on the {tf} chart with "
        "increasing volume divergence. Momentum oscillators confirm the bias. "
        "Institutional flow data supports this directional thesis with clear levels."
    ),
]

_PATTERNS = ["ascending triangle", "bull flag", "head and shoulders inverse",
             "double bottom", "cup and handle", "falling wedge"]
_RSI_STATES = ["oversold bounce", "bullish divergence", "momentum building"]
_CATALYSTS = ["protocol upgrade", "ETF approval rumor", "whale accumulation",
              "exchange listing", "partnership announcement"]
_ONCHAIN = ["increasing active addresses", "declining exchange reserves",
            "growing TVL", "rising staking participation"]


def random_signal_payload() -> dict:
    """Generate a random valid signal submission payload."""
    template = random.choice(_REASONING_TEMPLATES)
    reasoning = template.format(
        pattern=random.choice(_PATTERNS),
        tf=random.choice(TIMEFRAMES),
        rsi_state=random.choice(_RSI_STATES),
        catalyst=random.choice(_CATALYSTS),
        onchain=random.choice(_ONCHAIN),
        support=f"${random.randint(20000, 60000):,}",
        resistance=f"${random.randint(61000, 100000):,}",
    )
    asset = random.choice(ASSETS)
    action = random.choice(ACTIONS)
    confidence = round(random.uniform(0.1, 0.9), 2)
    target_price = round(random.uniform(30000, 100000), 2) if random.random() > 0.3 else None
    stop_loss = round(random.uniform(20000, 29999), 2) if target_price else None

    payload = {
        "asset": asset,
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_data": {
            "rsi": round(random.uniform(20, 80), 1),
            "volume_24h": f"${random.randint(1, 50)}B",
            "trend": random.choice(["bullish", "bearish", "neutral"]),
        },
    }
    if target_price:
        payload["target_price"] = target_price
    if stop_loss:
        payload["stop_loss"] = stop_loss
    payload["timeframe"] = random.choice(TIMEFRAMES)
    return payload


def random_battle_pair(pool: list[dict]) -> tuple[str, str]:
    """Pick two distinct creator IDs from the pool."""
    a, b = random.sample(pool, 2)
    return a["id"], b["id"]
