"""Tests for the ELO rating system — calculation, K-factor, edge cases."""

from __future__ import annotations

import pytest

from tradearena.core.elo import (
    ESTABLISHED_THRESHOLD,
    K_FACTOR_ESTABLISHED,
    K_FACTOR_NEW,
    EloResult,
    calculate_elo_change,
    expected_score,
    k_factor,
)


class TestKFactor:
    def test_new_bot_gets_high_k(self):
        assert k_factor(0) == K_FACTOR_NEW
        assert k_factor(29) == K_FACTOR_NEW

    def test_established_bot_gets_low_k(self):
        assert k_factor(30) == K_FACTOR_ESTABLISHED
        assert k_factor(100) == K_FACTOR_ESTABLISHED

    def test_threshold_boundary(self):
        assert k_factor(ESTABLISHED_THRESHOLD - 1) == K_FACTOR_NEW
        assert k_factor(ESTABLISHED_THRESHOLD) == K_FACTOR_ESTABLISHED


class TestExpectedScore:
    def test_equal_ratings(self):
        assert expected_score(1200, 1200) == pytest.approx(0.5)

    def test_higher_rated_favored(self):
        es = expected_score(1400, 1200)
        assert es > 0.5
        assert es < 1.0

    def test_lower_rated_underdog(self):
        es = expected_score(1200, 1400)
        assert es < 0.5
        assert es > 0.0

    def test_symmetry(self):
        ea = expected_score(1200, 1400)
        eb = expected_score(1400, 1200)
        assert ea + eb == pytest.approx(1.0)

    def test_400_point_gap(self):
        # 400 points difference = ~91% expected for the higher rated
        es = expected_score(1600, 1200)
        assert es == pytest.approx(0.9091, abs=0.01)


class TestCalculateEloChange:
    def test_equal_ratings_winner_gains(self):
        r1, r2 = calculate_elo_change(1200, 1200, 1.0, 0, 0)

        assert r1.new_rating > 1200
        assert r2.new_rating < 1200
        assert r1.change > 0
        assert r2.change < 0

    def test_equal_ratings_draw_no_change(self):
        r1, r2 = calculate_elo_change(1200, 1200, 0.5, 0, 0)

        assert r1.new_rating == pytest.approx(1200, abs=0.01)
        assert r2.new_rating == pytest.approx(1200, abs=0.01)

    def test_upset_gives_bigger_gain(self):
        # Low-rated player (1000) beats high-rated player (1400)
        r1_upset, _ = calculate_elo_change(1000, 1400, 1.0, 0, 0)
        # High-rated player (1400) beats low-rated player (1000) — expected
        r1_expected, _ = calculate_elo_change(1400, 1000, 1.0, 0, 0)

        assert r1_upset.change > r1_expected.change

    def test_established_players_change_less(self):
        # New players (K=32)
        r1_new, _ = calculate_elo_change(1200, 1200, 1.0, 0, 0)
        # Established players (K=16)
        r1_est, _ = calculate_elo_change(1200, 1200, 1.0, 50, 50)

        assert abs(r1_new.change) > abs(r1_est.change)

    def test_new_vs_established_asymmetric_k(self):
        # New bot (K=32) vs established (K=16) — both at 1200, new bot wins
        r1, r2 = calculate_elo_change(1200, 1200, 1.0, 5, 50)

        # New bot gains more than established bot loses (different K-factors)
        assert r1.change == pytest.approx(16.0, abs=0.01)  # K=32 * 0.5
        assert r2.change == pytest.approx(-8.0, abs=0.01)  # K=16 * -0.5

    def test_returns_elo_result_dataclass(self):
        r1, r2 = calculate_elo_change(1200, 1200, 1.0, 0, 0)

        assert isinstance(r1, EloResult)
        assert isinstance(r2, EloResult)
        assert r1.old_rating == 1200
        assert r2.old_rating == 1200

    def test_large_elo_gap_minimal_change_for_expected_win(self):
        # 1600 beats 800 — expected, so minimal ELO change
        r1, r2 = calculate_elo_change(1600, 800, 1.0, 0, 0)

        assert r1.change < 3  # almost no gain for expected win
        assert r2.change > -3

    def test_loss_decreases_rating(self):
        r1, r2 = calculate_elo_change(1200, 1200, 0.0, 0, 0)

        assert r1.new_rating < 1200
        assert r2.new_rating > 1200
