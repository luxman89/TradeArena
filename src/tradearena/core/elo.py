"""ELO rating system for bot/creator battles.

Standard ELO with variable K-factor:
- K=32 for new bots/creators (< 30 matches)
- K=16 for established bots/creators (>= 30 matches)

Starting rating: 1200
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_RATING = 1200
K_FACTOR_NEW = 32
K_FACTOR_ESTABLISHED = 16
ESTABLISHED_THRESHOLD = 30  # matches before K-factor drops


@dataclass
class EloResult:
    """Result of an ELO calculation for one player."""

    old_rating: float
    new_rating: float
    change: float


def k_factor(matches_played: int) -> int:
    """Return K-factor based on experience level."""
    return K_FACTOR_NEW if matches_played < ESTABLISHED_THRESHOLD else K_FACTOR_ESTABLISHED


def expected_score(rating_a: float, rating_b: float) -> float:
    """Expected score for player A against player B (0.0 to 1.0)."""
    return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400))


def calculate_elo_change(
    rating_a: float,
    rating_b: float,
    score_a: float,
    matches_a: int,
    matches_b: int,
) -> tuple[EloResult, EloResult]:
    """Calculate new ELO ratings after a match.

    Args:
        rating_a: Current ELO of player A.
        rating_b: Current ELO of player B.
        score_a: Actual score for player A (1.0=win, 0.5=draw, 0.0=loss).
        matches_a: Total matches played by A (determines K-factor).
        matches_b: Total matches played by B (determines K-factor).

    Returns:
        Tuple of (EloResult for A, EloResult for B).
    """
    ea = expected_score(rating_a, rating_b)
    eb = 1.0 - ea
    score_b = 1.0 - score_a

    ka = k_factor(matches_a)
    kb = k_factor(matches_b)

    change_a = ka * (score_a - ea)
    change_b = kb * (score_b - eb)

    new_a = round(rating_a + change_a, 2)
    new_b = round(rating_b + change_b, 2)

    return (
        EloResult(old_rating=rating_a, new_rating=new_a, change=round(change_a, 2)),
        EloResult(old_rating=rating_b, new_rating=new_b, change=round(change_b, 2)),
    )
