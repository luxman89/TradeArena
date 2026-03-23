"""Seed the test database with creators for load testing.

Run before the locust tests:
    uv run python loadtests/seed.py

This creates NUM_CREATORS test creators with known API keys, plus
pre-resolved signals so battles and leaderboard queries have data to work with.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tradearena.db")

from tradearena.core.commitment import build_committed_signal
from tradearena.core.scoring import compute_score
from tradearena.db.database import (
    Base,
    CreatorORM,
    CreatorScoreORM,
    SessionLocal,
    SignalORM,
    create_tables,
)

from common import (
    ACTIONS,
    ASSETS,
    DIVISIONS,
    NUM_CREATORS,
    TIMEFRAMES,
    make_api_key,
    make_api_key_hash,
    make_creator_id,
)

SIGNALS_PER_CREATOR = 10  # enough for battles (need >= 2 resolved)


def seed() -> None:
    create_tables()
    db = SessionLocal()

    # Clean up any previous loadtest creators
    db.query(SignalORM).filter(SignalORM.creator_id.like("loadtest-%")).delete(
        synchronize_session=False
    )
    db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id.like("loadtest-%")).delete(
        synchronize_session=False
    )
    db.query(CreatorORM).filter(CreatorORM.id.like("loadtest-%")).delete(
        synchronize_session=False
    )
    db.commit()

    now = datetime.now(UTC)
    outcomes = ["WIN", "LOSS", "NEUTRAL"]

    for i in range(NUM_CREATORS):
        creator_id = make_creator_id(i)
        api_key = make_api_key(i)

        creator = CreatorORM(
            id=creator_id,
            display_name=f"LoadTest Bot {i}",
            division=DIVISIONS[i % len(DIVISIONS)],
            api_key_dev=api_key,
            api_key_hash=make_api_key_hash(i),
            created_at=now - timedelta(days=30),
        )
        db.add(creator)

        # Seed resolved signals for scoring and battle resolution
        for j in range(SIGNALS_PER_CREATOR):
            asset = ASSETS[j % len(ASSETS)]
            action = ACTIONS[j % len(ACTIONS)]
            reasoning = (
                "Load test signal with detailed technical analysis covering RSI divergence "
                "and volume confirmation across multiple timeframes showing clear momentum "
                "shift above the key resistance breakout level for stress testing purposes."
            )
            raw = {
                "creator_id": creator_id,
                "asset": asset,
                "action": action,
                "confidence": round(0.3 + (j % 6) * 0.1, 2),
                "reasoning": reasoning,
                "supporting_data": {"rsi": 55.0, "volume": "$10B"},
                "timeframe": TIMEFRAMES[j % len(TIMEFRAMES)],
            }
            committed = build_committed_signal(raw)

            sig = SignalORM(
                signal_id=committed["signal_id"],
                creator_id=creator_id,
                asset=asset,
                action=action,
                confidence=raw["confidence"],
                reasoning=reasoning,
                supporting_data=raw["supporting_data"],
                timeframe=raw["timeframe"],
                commitment_hash=committed["commitment_hash"],
                committed_at=now - timedelta(hours=48 + j),
                outcome=outcomes[j % len(outcomes)],
                outcome_price=round(40000 + j * 100, 2),
                outcome_at=now - timedelta(hours=24 + j),
            )
            db.add(sig)

        db.flush()

        # Compute and store score
        signal_outcomes = [outcomes[j % len(outcomes)] for j in range(SIGNALS_PER_CREATOR)]
        signal_confidences = [round(0.3 + (j % 6) * 0.1, 2) for j in range(SIGNALS_PER_CREATOR)]
        dims = compute_score(signal_outcomes, signal_confidences)
        existing = db.query(CreatorScoreORM).filter(
            CreatorScoreORM.creator_id == creator_id
        ).first()
        score_fields = {
            "win_rate": dims.win_rate,
            "risk_adjusted_return": dims.risk_adjusted_return,
            "consistency": dims.consistency,
            "confidence_calibration": dims.confidence_calibration,
            "composite_score": dims.composite,
            "total_signals": SIGNALS_PER_CREATOR,
        }
        if existing:
            for k, v in score_fields.items():
                setattr(existing, k, v)
            existing.updated_at = now
        else:
            db.add(CreatorScoreORM(creator_id=creator_id, **score_fields, updated_at=now))

    db.commit()
    db.close()
    print(f"Seeded {NUM_CREATORS} loadtest creators with {SIGNALS_PER_CREATOR} signals each.")


if __name__ == "__main__":
    seed()
