"""Seed 3 demo creators and 20 signals for leaderboard testing."""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as `uv run python scripts/seed_demo.py` from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tradearena.db")

from tradearena.core.commitment import build_committed_signal
from tradearena.core.scoring import compute_score
from tradearena.db.database import (
    CreatorORM,
    CreatorScoreORM,
    SessionLocal,
    SignalORM,
    create_tables,
)

DEMO_CREATORS = [
    {
        "id": "alice",
        "display_name": "Alice Quantsworth",
        "division": "elite",
        "api_key_hash": hashlib.sha256(b"alice-key").hexdigest(),
    },
    {
        "id": "bob",
        "display_name": "Bob Trendline",
        "division": "pro",
        "api_key_hash": hashlib.sha256(b"bob-key").hexdigest(),
    },
    {
        "id": "carol",
        "display_name": "Carol Momentum",
        "division": "rookie",
        "api_key_hash": hashlib.sha256(b"carol-key").hexdigest(),
    },
]

# 20 signals spread across 3 creators
DEMO_SIGNALS = [
    # Alice — 8 signals (strong performer)
    {
        "creator_id": "alice",
        "symbol": "BTC/USDT",
        "action": "BUY",
        "confidence": 0.82,
        "reasoning": (
            "Bitcoin is forming a classic ascending triangle pattern on the 4-hour chart. "
            "RSI is at 58 with bullish divergence. Volume has been increasing steadily over "
            "the past three sessions, suggesting institutional accumulation. The 200 EMA "
            "is acting as dynamic support."
        ),
        "supporting_data": {"rsi": 58, "volume_24h": 1_200_000_000, "ema_200": 41500, "pattern": "ascending_triangle"},
        "target_price": 48000.0,
        "stop_loss": 40000.0,
        "timeframe": "4h",
        "outcome": "WIN",
        "outcome_price": 47800.0,
        "days_ago": 30,
    },
    {
        "creator_id": "alice",
        "symbol": "ETH/USDT",
        "action": "BUY",
        "confidence": 0.75,
        "reasoning": (
            "Ethereum is breaking out of a 3-week consolidation range with a confirmed "
            "close above the key resistance at 2800. MACD histogram is expanding bullishly. "
            "On-chain metrics show decreasing exchange supply, a typical precursor to "
            "sustained price appreciation in prior cycles."
        ),
        "supporting_data": {"macd": 12.5, "exchange_supply_change": -3.2, "resistance_break": 2800},
        "target_price": 3200.0,
        "stop_loss": 2600.0,
        "timeframe": "1d",
        "outcome": "WIN",
        "outcome_price": 3150.0,
        "days_ago": 25,
    },
    {
        "creator_id": "alice",
        "symbol": "SOL/USDT",
        "action": "BUY",
        "confidence": 0.68,
        "reasoning": (
            "Solana is testing a major support zone that has held four times historically. "
            "Funding rates are negative, indicating a crowded short trade. The risk-reward "
            "ratio is favorable at this entry. Network activity metrics remain strong despite "
            "the price decline, which is a positive divergence signal."
        ),
        "supporting_data": {"funding_rate": -0.045, "support_level": 95, "network_txns_7d": 52_000_000},
        "target_price": 120.0,
        "stop_loss": 88.0,
        "timeframe": "4h",
        "outcome": "WIN",
        "outcome_price": 118.5,
        "days_ago": 20,
    },
    {
        "creator_id": "alice",
        "symbol": "BNB/USDT",
        "action": "SELL",
        "confidence": 0.71,
        "reasoning": (
            "BNB has rallied into a strong resistance zone after a 35% move in 2 weeks. "
            "RSI is printing overbought at 78 with bearish divergence on the hourly chart. "
            "Volume is declining on the approach to resistance, suggesting distribution. "
            "I expect a retracement to the 0.382 Fibonacci level."
        ),
        "supporting_data": {"rsi": 78, "resistance_zone": 320, "volume_trend": "declining", "fib_target": 290},
        "target_price": 290.0,
        "stop_loss": 330.0,
        "timeframe": "1h",
        "outcome": "WIN",
        "outcome_price": 291.0,
        "days_ago": 15,
    },
    {
        "creator_id": "alice",
        "symbol": "ADA/USDT",
        "action": "BUY",
        "confidence": 0.55,
        "reasoning": (
            "Cardano is showing a potential reversal at the weekly demand zone. While the "
            "trend is still bearish, the risk-reward is favorable. Staking yields remain "
            "competitive. I am taking a small position with a tight stop loss given the "
            "uncertainty in the broader market environment."
        ),
        "supporting_data": {"weekly_demand_zone": 0.38, "staking_yield": 4.2, "market_cap_rank": 8},
        "target_price": 0.52,
        "stop_loss": 0.34,
        "timeframe": "1d",
        "outcome": "LOSS",
        "outcome_price": 0.33,
        "days_ago": 12,
    },
    {
        "creator_id": "alice",
        "symbol": "BTC/USDT",
        "action": "BUY",
        "confidence": 0.78,
        "reasoning": (
            "Bitcoin is consolidating above the prior all-time high turned support at 45000. "
            "This is a textbook continuation pattern. Order book shows significant bid walls "
            "at 44500. The halving cycle suggests we are still in the early bull market phase. "
            "Risk is defined by the 44000 invalidation level."
        ),
        "supporting_data": {"support_level": 45000, "bid_wall": 44500, "halving_days_since": 180, "order_book_ratio": 1.8},
        "target_price": 55000.0,
        "stop_loss": 43500.0,
        "timeframe": "1d",
        "outcome": "WIN",
        "outcome_price": 54200.0,
        "days_ago": 8,
    },
    {
        "creator_id": "alice",
        "symbol": "ETH/USDT",
        "action": "HOLD",
        "confidence": 0.62,
        "reasoning": (
            "Ethereum is in a decision point between two key levels. The risk-reward for "
            "adding here is not compelling enough to justify a new position. I am maintaining "
            "my existing long from 2800 but not adding. Waiting for a clearer signal from "
            "the derivatives market before sizing up the position."
        ),
        "supporting_data": {"current_price": 3050, "existing_entry": 2800, "derivatives_open_interest": 8_500_000_000},
        "timeframe": "4h",
        "outcome": "NEUTRAL",
        "outcome_price": 3020.0,
        "days_ago": 5,
    },
    {
        "creator_id": "alice",
        "symbol": "LINK/USDT",
        "action": "BUY",
        "confidence": 0.73,
        "reasoning": (
            "Chainlink is breaking out of a multi-month base with a volume surge 3x the "
            "30-day average. Relative strength versus Bitcoin is improving for the first time "
            "in 6 months. The recent protocol upgrade and new oracle integrations are acting "
            "as a catalyst for the technical breakout pattern."
        ),
        "supporting_data": {"volume_vs_30d_avg": 3.1, "btc_relative_strength": "improving", "breakout_level": 14.5},
        "target_price": 18.0,
        "stop_loss": 13.0,
        "timeframe": "1d",
        "outcome": None,
        "days_ago": 1,
    },
    # Bob — 7 signals (average performer)
    {
        "creator_id": "bob",
        "symbol": "BTC/USDT",
        "action": "SHORT",
        "confidence": 0.65,
        "reasoning": (
            "Bitcoin is approaching a key resistance zone after a dead cat bounce. "
            "The macro environment remains unfavorable with rising interest rates. "
            "Miner outflows are increasing which suggests selling pressure ahead. "
            "Technical structure favors continuation of the downtrend."
        ),
        "supporting_data": {"resistance": 47000, "miner_outflows_btc": 2300, "macro_rate": 5.25},
        "outcome": "WIN",
        "outcome_price": 43000.0,
        "days_ago": 28,
    },
    {
        "creator_id": "bob",
        "symbol": "ETH/USDT",
        "action": "BUY",
        "confidence": 0.58,
        "reasoning": (
            "Ethereum staking rewards remain attractive. The network's deflationary "
            "mechanism is reducing supply. Technical setup shows oversold conditions "
            "on the daily chart with RSI at 32. Previous support zone is holding and "
            "a bounce to 3000 seems reasonable in the near term."
        ),
        "supporting_data": {"rsi_daily": 32, "staking_apy": 4.8, "burn_rate_daily": 2500},
        "target_price": 3000.0,
        "stop_loss": 2400.0,
        "timeframe": "1d",
        "outcome": "LOSS",
        "outcome_price": 2380.0,
        "days_ago": 22,
    },
    {
        "creator_id": "bob",
        "symbol": "MATIC/USDT",
        "action": "BUY",
        "confidence": 0.61,
        "reasoning": (
            "Polygon is seeing increased developer activity and L2 adoption metrics. "
            "The recent zkEVM launch is a major technical milestone. Price is at a "
            "6-month low despite improving fundamentals, suggesting a disconnect "
            "between price and value that creates an opportunity."
        ),
        "supporting_data": {"dev_activity_score": 87, "zkevm_tvl": 450_000_000, "price_vs_6m_high": -62},
        "target_price": 1.20,
        "stop_loss": 0.72,
        "timeframe": "1w",
        "outcome": "WIN",
        "outcome_price": 1.18,
        "days_ago": 18,
    },
    {
        "creator_id": "bob",
        "symbol": "DOGE/USDT",
        "action": "BUY",
        "confidence": 0.42,
        "reasoning": (
            "Dogecoin has a historically strong correlation with social sentiment "
            "spikes. Recent social media volume is up 400%. The meme coin market "
            "appears to be entering a new cycle based on funding rates and options "
            "market activity. This is a high-risk momentum trade with tight risk management."
        ),
        "supporting_data": {"social_volume_change": 400, "funding_rate": 0.08, "options_iv": 180},
        "target_price": 0.18,
        "stop_loss": 0.09,
        "timeframe": "4h",
        "outcome": "LOSS",
        "outcome_price": 0.088,
        "days_ago": 14,
    },
    {
        "creator_id": "bob",
        "symbol": "BTC/USDT",
        "action": "BUY",
        "confidence": 0.69,
        "reasoning": (
            "Bitcoin weekly chart is printing a bullish engulfing candle at the 50-week "
            "moving average. This pattern has preceded major rallies in three of the last "
            "four occurrences. Institutional demand from ETF inflows continues to provide "
            "a bid. Risk management level is clear at the weekly candle low."
        ),
        "supporting_data": {"weekly_ma_50": 42000, "etf_inflows_7d_btc": 8500, "pattern": "bullish_engulfing"},
        "target_price": 55000.0,
        "stop_loss": 40500.0,
        "timeframe": "1w",
        "outcome": "WIN",
        "outcome_price": 53500.0,
        "days_ago": 9,
    },
    {
        "creator_id": "bob",
        "symbol": "XRP/USDT",
        "action": "BUY",
        "confidence": 0.53,
        "reasoning": (
            "XRP legal clarity has improved following recent court rulings. The token "
            "is trading near multi-year support while fundamentals improve. Ripple "
            "partnership announcements continue to flow. This is a speculative "
            "position given regulatory uncertainty that still exists in some jurisdictions."
        ),
        "supporting_data": {"legal_clarity_score": 7.2, "support_level": 0.48, "active_partnerships": 450},
        "target_price": 0.75,
        "stop_loss": 0.44,
        "timeframe": "1w",
        "outcome": "WIN",
        "outcome_price": 0.73,
        "days_ago": 4,
    },
    {
        "creator_id": "bob",
        "symbol": "SOL/USDT",
        "action": "BUY",
        "confidence": 0.66,
        "reasoning": (
            "Solana's ecosystem metrics are at all-time highs including DEX volume and "
            "NFT activity. The network has maintained 100% uptime for 90 days. Price is "
            "forming a cup and handle pattern on the daily chart. The breakout target "
            "aligns with the previous all-time high resistance zone."
        ),
        "supporting_data": {"dex_volume_24h": 2_800_000_000, "uptime_days": 90, "cup_handle_target": 180},
        "target_price": 180.0,
        "stop_loss": 105.0,
        "timeframe": "1d",
        "outcome": None,
        "days_ago": 2,
    },
    # Carol — 5 signals (newcomer)
    {
        "creator_id": "carol",
        "symbol": "BTC/USDT",
        "action": "BUY",
        "confidence": 0.55,
        "reasoning": (
            "Bitcoin looks like it wants to go up. The price has been going sideways and "
            "I think a breakout is coming. The RSI is not overbought and volume looks okay. "
            "I have been following this chart for two weeks and the setup looks similar to "
            "a move that happened back in October."
        ),
        "supporting_data": {"rsi": 52, "days_sideways": 14},
        "target_price": 50000.0,
        "stop_loss": 42000.0,
        "timeframe": "1d",
        "outcome": "WIN",
        "outcome_price": 49500.0,
        "days_ago": 21,
    },
    {
        "creator_id": "carol",
        "symbol": "ETH/USDT",
        "action": "BUY",
        "confidence": 0.48,
        "reasoning": (
            "Ethereum seems undervalued compared to Bitcoin right now. The ETH/BTC ratio "
            "is near historical lows. I think money will rotate from Bitcoin to altcoins "
            "soon. There has been a lot of positive news about Ethereum upgrades recently "
            "which should help the price recover."
        ),
        "supporting_data": {"eth_btc_ratio": 0.062, "upgrade_news_sentiment": "positive"},
        "outcome": "LOSS",
        "outcome_price": 2350.0,
        "days_ago": 16,
    },
    {
        "creator_id": "carol",
        "symbol": "AVAX/USDT",
        "action": "BUY",
        "confidence": 0.51,
        "reasoning": (
            "Avalanche has been mentioned a lot on crypto Twitter lately. The project "
            "has good technology and fast transactions. Price looks low compared to where "
            "it was at the peak. I think the team keeps building and the price should "
            "recover eventually as the market sentiment improves overall."
        ),
        "supporting_data": {"price_vs_ath_pct": -78, "twitter_mentions_7d": 45000},
        "target_price": 45.0,
        "stop_loss": 22.0,
        "timeframe": "1w",
        "outcome": "LOSS",
        "outcome_price": 21.5,
        "days_ago": 11,
    },
    {
        "creator_id": "carol",
        "symbol": "BNB/USDT",
        "action": "BUY",
        "confidence": 0.57,
        "reasoning": (
            "Binance Smart Chain activity is picking up again. BNB has been holding "
            "support well during the recent market dip. The token burn schedule continues "
            "to reduce supply. I expect BNB to outperform as Binance remains the dominant "
            "exchange and its ecosystem expands into new markets."
        ),
        "supporting_data": {"bsc_daily_txns": 4_200_000, "bnb_burn_quarterly": 2_300_000, "support_level": 280},
        "target_price": 380.0,
        "stop_loss": 265.0,
        "timeframe": "1w",
        "outcome": "WIN",
        "outcome_price": 372.0,
        "days_ago": 6,
    },
    {
        "creator_id": "carol",
        "symbol": "DOT/USDT",
        "action": "BUY",
        "confidence": 0.44,
        "reasoning": (
            "Polkadot parachain auctions are heating up again and there is renewed interest "
            "in the ecosystem. The staking yield is attractive at current prices. Price has "
            "been in a long downtrend but seems to be finding a floor around these levels. "
            "This is a speculative long-term position based on the fundamental value thesis."
        ),
        "supporting_data": {"staking_yield": 14.2, "parachain_count": 45, "price_vs_ath_pct": -91},
        "target_price": 10.0,
        "stop_loss": 4.5,
        "timeframe": "1w",
        "outcome": None,
        "days_ago": 3,
    },
]


def seed():
    create_tables()
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # Insert creators
        for c in DEMO_CREATORS:
            existing = db.query(CreatorORM).filter(CreatorORM.id == c["id"]).first()
            if not existing:
                creator = CreatorORM(
                    id=c["id"],
                    display_name=c["display_name"],
                    division=c["division"],
                    api_key_hash=c["api_key_hash"],
                    created_at=now - timedelta(days=60),
                )
                db.add(creator)
        db.commit()
        print(f"Inserted {len(DEMO_CREATORS)} creators.")

        # Insert signals
        count = 0
        for s in DEMO_SIGNALS:
            raw = {k: v for k, v in s.items() if k not in ("outcome", "outcome_price", "days_ago")}
            raw["action"] = raw["action"]  # already string

            committed = build_committed_signal(raw)

            committed_at = now - timedelta(days=s["days_ago"])
            outcome_at = committed_at + timedelta(days=1) if s.get("outcome") else None

            existing = (
                db.query(SignalORM)
                .filter(SignalORM.commitment_hash == committed["commitment_hash"])
                .first()
            )
            if existing:
                continue

            signal_orm = SignalORM(
                signal_id=committed["signal_id"],
                creator_id=committed["creator_id"],
                symbol=committed["symbol"],
                action=committed["action"],
                confidence=committed["confidence"],
                reasoning=committed["reasoning"],
                supporting_data=committed["supporting_data"],
                target_price=committed.get("target_price"),
                stop_loss=committed.get("stop_loss"),
                timeframe=committed.get("timeframe"),
                commitment_hash=committed["commitment_hash"],
                committed_at=committed_at,
                outcome=s.get("outcome"),
                outcome_price=s.get("outcome_price"),
                outcome_at=outcome_at,
            )
            db.add(signal_orm)
            count += 1

        db.commit()
        print(f"Inserted {count} signals.")

        # Compute and store scores
        for creator in db.query(CreatorORM).all():
            signals = db.query(SignalORM).filter(SignalORM.creator_id == creator.id).all()
            outcomes = [s.outcome for s in signals]
            confidences = [s.confidence for s in signals]
            reasonings = [s.reasoning for s in signals]

            dims = compute_score(outcomes, confidences, reasonings)

            existing_score = (
                db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == creator.id).first()
            )
            if existing_score:
                existing_score.win_rate = dims.win_rate
                existing_score.risk_adjusted_return = dims.risk_adjusted_return
                existing_score.reasoning_quality = dims.reasoning_quality
                existing_score.consistency = dims.consistency
                existing_score.confidence_calibration = dims.confidence_calibration
                existing_score.composite_score = dims.composite
                existing_score.total_signals = len(signals)
                existing_score.updated_at = now
            else:
                score_orm = CreatorScoreORM(
                    creator_id=creator.id,
                    win_rate=dims.win_rate,
                    risk_adjusted_return=dims.risk_adjusted_return,
                    reasoning_quality=dims.reasoning_quality,
                    consistency=dims.consistency,
                    confidence_calibration=dims.confidence_calibration,
                    composite_score=dims.composite,
                    total_signals=len(signals),
                    updated_at=now,
                )
                db.add(score_orm)

        db.commit()
        print("Scores computed and stored.")
        print("\nDemo API keys:")
        print("  alice-key  (division: elite)")
        print("  bob-key    (division: pro)")
        print("  carol-key  (division: rookie)")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
