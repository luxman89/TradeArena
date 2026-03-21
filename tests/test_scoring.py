"""Tests for the 4-dimension scoring engine."""

from __future__ import annotations

from tradearena.core.scoring import (
    WEIGHTS,
    ScoreDimensions,
    compute_score,
    score_confidence_calibration,
    score_consistency,
    score_risk_adjusted_return,
    score_win_rate,
)


class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_expected_dimensions_present(self):
        expected = {
            "win_rate",
            "risk_adjusted_return",
            "consistency",
            "confidence_calibration",
        }
        assert set(WEIGHTS.keys()) == expected


class TestScoreWinRate:
    def test_all_wins(self):
        assert score_win_rate(["WIN"] * 10) == 1.0

    def test_all_losses(self):
        assert score_win_rate(["LOSS"] * 10) == 0.0

    def test_half_wins(self):
        result = score_win_rate(["WIN", "LOSS"] * 5)
        assert abs(result - 0.5) < 1e-9

    def test_pending_signals_excluded(self):
        # 5 wins, 5 pending — should score as 5/5 = 1.0
        result = score_win_rate(["WIN"] * 5 + [None] * 5)
        assert result == 1.0

    def test_all_pending_returns_zero(self):
        assert score_win_rate([None, None, None]) == 0.0

    def test_empty_returns_zero(self):
        assert score_win_rate([]) == 0.0

    def test_neutral_counts_as_loss(self):
        result = score_win_rate(["WIN", "NEUTRAL"])
        assert result == 0.5

    def test_output_clamped_0_to_1(self):
        result = score_win_rate(["WIN"] * 100)
        assert 0.0 <= result <= 1.0


class TestScoreRiskAdjustedReturn:
    def test_all_wins_high_confidence_scores_well(self):
        outcomes = ["WIN"] * 20
        confidences = [0.9] * 20
        result = score_risk_adjusted_return(outcomes, confidences)
        assert result > 0.9

    def test_all_losses_scores_low(self):
        outcomes = ["LOSS"] * 20
        confidences = [0.9] * 20
        result = score_risk_adjusted_return(outcomes, confidences)
        assert result < 0.1

    def test_mixed_outcomes(self):
        outcomes = ["WIN", "LOSS"] * 5
        confidences = [0.6] * 10
        result = score_risk_adjusted_return(outcomes, confidences)
        assert 0.0 <= result <= 1.0

    def test_single_resolved_returns_zero(self):
        assert score_risk_adjusted_return(["WIN"], [0.8]) == 0.0

    def test_output_clamped_0_to_1(self):
        result = score_risk_adjusted_return(["WIN"] * 50, [0.95] * 50)
        assert 0.0 <= result <= 1.0


class TestScoreConsistency:
    def test_perfectly_consistent_winner_scores_high(self):
        outcomes = ["WIN"] * 20
        result = score_consistency(outcomes)
        assert result > 0.8

    def test_alternating_win_loss_scores_lower(self):
        outcomes = ["WIN", "LOSS"] * 10
        result = score_consistency(outcomes)
        consistent = score_consistency(["WIN"] * 20)
        assert result < consistent

    def test_fewer_than_window_gives_partial_credit(self):
        result = score_consistency(["WIN"] * 5, window=10)
        assert 0.0 < result < 0.6

    def test_empty_returns_zero(self):
        assert score_consistency([]) == 0.0

    def test_output_clamped_0_to_1(self):
        result = score_consistency(["WIN"] * 100)
        assert 0.0 <= result <= 1.0


class TestScoreConfidenceCalibration:
    def test_perfect_calibration(self):
        # Always WIN with confidence 1.0 would be perfect but confidence can't be 1
        # Use high confidence with all wins → good calibration
        outcomes = ["WIN"] * 20
        confidences = [0.85] * 20
        result = score_confidence_calibration(outcomes, confidences)
        assert result > 0.5

    def test_overconfident_loser_scores_low(self):
        outcomes = ["LOSS"] * 20
        confidences = [0.95] * 20
        result = score_confidence_calibration(outcomes, confidences)
        assert result < 0.1

    def test_no_resolved_returns_zero(self):
        assert score_confidence_calibration([None] * 10, [0.5] * 10) == 0.0

    def test_output_clamped_0_to_1(self):
        result = score_confidence_calibration(["WIN"] * 20, [0.8] * 20)
        assert 0.0 <= result <= 1.0


class TestComputeScore:
    def test_returns_score_dimensions_instance(self):
        result = compute_score(
            outcomes=["WIN", "LOSS", "WIN"],
            confidences=[0.7, 0.6, 0.8],
        )
        assert isinstance(result, ScoreDimensions)

    def test_composite_weighted_correctly(self):
        dims = ScoreDimensions(
            win_rate=1.0,
            risk_adjusted_return=1.0,
            consistency=1.0,
            confidence_calibration=1.0,
        )
        assert abs(dims.composite - 1.0) < 1e-9

    def test_composite_zero_dimensions(self):
        dims = ScoreDimensions()
        assert dims.composite == 0.0

    def test_composite_partial(self):
        dims = ScoreDimensions(win_rate=1.0)
        assert abs(dims.composite - WEIGHTS["win_rate"]) < 1e-9

    def test_full_pipeline_produces_valid_scores(self):
        outcomes = ["WIN", "WIN", "LOSS", "WIN", "NEUTRAL", None, "WIN"]
        confidences = [0.75, 0.80, 0.60, 0.70, 0.55, 0.65, 0.85]
        result = compute_score(outcomes, confidences)
        assert 0.0 <= result.win_rate <= 1.0
        assert 0.0 <= result.risk_adjusted_return <= 1.0
        assert 0.0 <= result.consistency <= 1.0
        assert 0.0 <= result.confidence_calibration <= 1.0
        assert 0.0 <= result.composite <= 1.0
