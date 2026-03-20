"""Tests for per-creator performance analytics computation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tradearena.core.analytics import (
    compute_action_distribution,
    compute_analytics,
    compute_confidence_calibration_curve,
    compute_drawdown_series,
    compute_equity_curve,
    compute_streaks,
)


def _sig(
    outcome=None,
    confidence=0.5,
    action="buy",
    committed_at=None,
    **kwargs,
):
    """Create a lightweight signal-like object for analytics tests."""
    if committed_at is None:
        committed_at = datetime.now(UTC)
    return SimpleNamespace(
        outcome=outcome,
        confidence=confidence,
        action=action,
        committed_at=committed_at,
        **kwargs,
    )


# ── Equity curve ──────────────────────────────────────────────────────────


class TestEquityCurve:
    def test_empty_signals(self):
        assert compute_equity_curve([]) == []

    def test_only_pending(self):
        sigs = [_sig(outcome=None), _sig(outcome=None)]
        assert compute_equity_curve(sigs) == []

    def test_cumulative_wins(self):
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, tzinfo=UTC)
        sigs = [_sig(outcome="WIN", committed_at=t1), _sig(outcome="WIN", committed_at=t2)]
        curve = compute_equity_curve(sigs)
        assert len(curve) == 2
        assert curve[0]["value"] == 1.0
        assert curve[1]["value"] == 2.0

    def test_win_then_loss(self):
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, tzinfo=UTC)
        sigs = [_sig(outcome="WIN", committed_at=t1), _sig(outcome="LOSS", committed_at=t2)]
        curve = compute_equity_curve(sigs)
        assert curve[-1]["value"] == 0.0

    def test_neutral_no_change(self):
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, tzinfo=UTC)
        sigs = [
            _sig(outcome="WIN", committed_at=t1),
            _sig(outcome="NEUTRAL", committed_at=t2),
        ]
        curve = compute_equity_curve(sigs)
        assert curve[0]["value"] == 1.0
        assert curve[1]["value"] == 1.0

    def test_sorted_by_time(self):
        t1 = datetime(2025, 1, 2, tzinfo=UTC)
        t2 = datetime(2025, 1, 1, tzinfo=UTC)
        sigs = [_sig(outcome="WIN", committed_at=t1), _sig(outcome="LOSS", committed_at=t2)]
        curve = compute_equity_curve(sigs)
        # t2 (loss) comes first chronologically
        assert curve[0]["value"] == -1.0
        assert curve[1]["value"] == 0.0


# ── Drawdown ──────────────────────────────────────────────────────────────


class TestDrawdownSeries:
    def test_empty(self):
        assert compute_drawdown_series([]) == []

    def test_monotone_up(self):
        equity = [
            {"timestamp": "2025-01-01", "value": 1.0},
            {"timestamp": "2025-01-02", "value": 2.0},
        ]
        dd = compute_drawdown_series(equity)
        assert all(p["value"] == 0.0 for p in dd)

    def test_drawdown_after_peak(self):
        equity = [
            {"timestamp": "2025-01-01", "value": 3.0},
            {"timestamp": "2025-01-02", "value": 1.0},
        ]
        dd = compute_drawdown_series(equity)
        assert dd[0]["value"] == 0.0
        assert dd[1]["value"] == -2.0


# ── Streaks ───────────────────────────────────────────────────────────────


class TestStreaks:
    def test_empty(self):
        result = compute_streaks([])
        assert result["max_win_streak"] == 0
        assert result["max_loss_streak"] == 0

    def test_all_wins(self):
        t = datetime(2025, 1, 1, tzinfo=UTC)
        sigs = [_sig(outcome="WIN", committed_at=t + timedelta(days=i)) for i in range(5)]
        result = compute_streaks(sigs)
        assert result["max_win_streak"] == 5
        assert result["current_win_streak"] == 5
        assert result["current_loss_streak"] == 0

    def test_all_losses(self):
        t = datetime(2025, 1, 1, tzinfo=UTC)
        sigs = [_sig(outcome="LOSS", committed_at=t + timedelta(days=i)) for i in range(3)]
        result = compute_streaks(sigs)
        assert result["max_loss_streak"] == 3
        assert result["current_loss_streak"] == 3
        assert result["current_win_streak"] == 0

    def test_mixed(self):
        t = datetime(2025, 1, 1, tzinfo=UTC)
        outcomes = ["WIN", "WIN", "WIN", "LOSS", "LOSS", "WIN"]
        sigs = [_sig(outcome=o, committed_at=t + timedelta(days=i)) for i, o in enumerate(outcomes)]
        result = compute_streaks(sigs)
        assert result["max_win_streak"] == 3
        assert result["max_loss_streak"] == 2
        assert result["current_win_streak"] == 1

    def test_pending_and_neutral_ignored(self):
        t = datetime(2025, 1, 1, tzinfo=UTC)
        sigs = [
            _sig(outcome="WIN", committed_at=t),
            _sig(outcome=None, committed_at=t + timedelta(days=1)),
            _sig(outcome="NEUTRAL", committed_at=t + timedelta(days=2)),
        ]
        result = compute_streaks(sigs)
        assert result["max_win_streak"] == 1


# ── Action distribution ──────────────────────────────────────────────────


class TestActionDistribution:
    def test_empty(self):
        assert compute_action_distribution([]) == {}

    def test_counts(self):
        sigs = [_sig(action="buy"), _sig(action="buy"), _sig(action="sell")]
        dist = compute_action_distribution(sigs)
        assert dist == {"buy": 2, "sell": 1}


# ── Confidence calibration ───────────────────────────────────────────────


class TestConfidenceCalibrationCurve:
    def test_empty(self):
        assert compute_confidence_calibration_curve([]) == []

    def test_only_pending(self):
        sigs = [_sig(outcome=None, confidence=0.8)]
        assert compute_confidence_calibration_curve(sigs) == []

    def test_single_bucket(self):
        sigs = [
            _sig(outcome="WIN", confidence=0.85),
            _sig(outcome="LOSS", confidence=0.82),
        ]
        curve = compute_confidence_calibration_curve(sigs)
        assert len(curve) == 1
        assert curve[0]["predicted_confidence"] == 0.85  # bucket 8 midpoint
        assert curve[0]["actual_win_rate"] == 0.5
        assert curve[0]["sample_count"] == 2

    def test_multiple_buckets(self):
        sigs = [
            _sig(outcome="WIN", confidence=0.15),
            _sig(outcome="WIN", confidence=0.75),
            _sig(outcome="WIN", confidence=0.76),
        ]
        curve = compute_confidence_calibration_curve(sigs)
        assert len(curve) == 2  # bucket 1 and bucket 7


# ── Full analytics pipeline ──────────────────────────────────────────────


class TestComputeAnalytics:
    def test_all_range(self):
        t = datetime(2025, 1, 1, tzinfo=UTC)
        sigs = [
            _sig(outcome="WIN", confidence=0.7, action="buy", committed_at=t),
            _sig(outcome="LOSS", confidence=0.3, action="sell", committed_at=t + timedelta(days=1)),
        ]
        result = compute_analytics(sigs, "all")
        assert result["range"] == "all"
        assert result["total_signals"] == 2
        assert result["resolved_signals"] == 2
        assert len(result["equity_curve"]) == 2
        assert len(result["drawdown_series"]) == 2
        assert result["streaks"]["max_win_streak"] == 1
        assert result["action_distribution"] == {"buy": 1, "sell": 1}
        assert len(result["confidence_calibration_curve"]) >= 1

    def test_time_range_filter(self):
        old = datetime.now(UTC) - timedelta(days=60)
        recent = datetime.now(UTC) - timedelta(days=1)
        sigs = [
            _sig(outcome="WIN", committed_at=old),
            _sig(outcome="LOSS", committed_at=recent),
        ]
        result_30d = compute_analytics(sigs, "30d")
        assert result_30d["total_signals"] == 1  # only recent

        result_all = compute_analytics(sigs, "all")
        assert result_all["total_signals"] == 2

    def test_empty_signals(self):
        result = compute_analytics([], "all")
        assert result["total_signals"] == 0
        assert result["equity_curve"] == []
        assert result["streaks"]["max_win_streak"] == 0
