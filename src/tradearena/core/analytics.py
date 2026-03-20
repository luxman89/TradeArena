"""Per-creator performance analytics computed from signal history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradearena.db.database import SignalORM

# Time range presets (in days). "all" is handled as None.
TIME_RANGES: dict[str, int | None] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}


def _filter_signals(signals: list[SignalORM], range_key: str) -> list[SignalORM]:
    """Filter signals to those within the given time range."""
    days = TIME_RANGES.get(range_key)
    if days is None:
        return signals
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return [s for s in signals if s.committed_at.replace(tzinfo=UTC) >= cutoff]


def compute_equity_curve(signals: list[SignalORM]) -> list[dict]:
    """Cumulative score over time: +1 for WIN, -1 for LOSS, 0 for NEUTRAL/pending."""
    resolved = sorted(
        [s for s in signals if s.outcome is not None],
        key=lambda s: s.committed_at,
    )
    curve = []
    cumulative = 0.0
    for s in resolved:
        if s.outcome == "WIN":
            cumulative += 1.0
        elif s.outcome == "LOSS":
            cumulative -= 1.0
        curve.append(
            {
                "timestamp": s.committed_at.isoformat(),
                "value": cumulative,
            }
        )
    return curve


def compute_drawdown_series(equity_curve: list[dict]) -> list[dict]:
    """Drawdown from peak at each point in the equity curve."""
    if not equity_curve:
        return []
    peak = equity_curve[0]["value"]
    series = []
    for point in equity_curve:
        peak = max(peak, point["value"])
        dd = point["value"] - peak  # <= 0
        series.append({"timestamp": point["timestamp"], "value": dd})
    return series


def compute_streaks(signals: list[SignalORM]) -> dict:
    """Current and max win/loss streaks."""
    resolved = sorted(
        [s for s in signals if s.outcome in ("WIN", "LOSS")],
        key=lambda s: s.committed_at,
    )
    max_win = max_loss = cur_win = cur_loss = 0
    for s in resolved:
        if s.outcome == "WIN":
            cur_win += 1
            cur_loss = 0
            max_win = max(max_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_loss = max(max_loss, cur_loss)
    return {
        "current_win_streak": cur_win,
        "current_loss_streak": cur_loss,
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
    }


def compute_action_distribution(signals: list[SignalORM]) -> dict[str, int]:
    """Count of signals by action type."""
    dist: dict[str, int] = {}
    for s in signals:
        dist[s.action] = dist.get(s.action, 0) + 1
    return dist


def compute_confidence_calibration_curve(
    signals: list[SignalORM],
) -> list[dict]:
    """Bin resolved signals by confidence decile, compute actual win rate per bin."""
    resolved = [s for s in signals if s.outcome in ("WIN", "LOSS")]
    if not resolved:
        return []
    bins: dict[int, list[bool]] = {}
    for s in resolved:
        bucket = min(int(s.confidence * 10), 9)  # 0-9
        bins.setdefault(bucket, []).append(s.outcome == "WIN")
    curve = []
    for bucket in sorted(bins):
        wins = bins[bucket]
        mid = (bucket + 0.5) / 10  # midpoint of decile
        curve.append(
            {
                "predicted_confidence": round(mid, 2),
                "actual_win_rate": round(sum(wins) / len(wins), 4),
                "sample_count": len(wins),
            }
        )
    return curve


def compute_analytics(
    signals: list[SignalORM],
    range_key: str = "all",
) -> dict:
    """Compute full analytics payload for a creator."""
    filtered = _filter_signals(signals, range_key)
    equity = compute_equity_curve(filtered)
    return {
        "range": range_key,
        "total_signals": len(filtered),
        "resolved_signals": len([s for s in filtered if s.outcome is not None]),
        "equity_curve": equity,
        "drawdown_series": compute_drawdown_series(equity),
        "streaks": compute_streaks(filtered),
        "action_distribution": compute_action_distribution(filtered),
        "confidence_calibration_curve": compute_confidence_calibration_curve(filtered),
    }
