"""Five-dimension composite score engine.

Weights:
    win_rate                25%
    risk_adjusted_return    25%
    reasoning_quality       20%
    consistency             20%
    confidence_calibration  10%

Each dimension is normalised to [0.0, 1.0] before weighting.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

WEIGHTS = {
    "win_rate": 0.25,
    "risk_adjusted_return": 0.25,
    "reasoning_quality": 0.20,
    "consistency": 0.20,
    "confidence_calibration": 0.10,
}


@dataclass
class ScoreDimensions:
    win_rate: float = 0.0
    risk_adjusted_return: float = 0.0
    reasoning_quality: float = 0.0
    consistency: float = 0.0
    confidence_calibration: float = 0.0

    @property
    def composite(self) -> float:
        return (
            self.win_rate * WEIGHTS["win_rate"]
            + self.risk_adjusted_return * WEIGHTS["risk_adjusted_return"]
            + self.reasoning_quality * WEIGHTS["reasoning_quality"]
            + self.consistency * WEIGHTS["consistency"]
            + self.confidence_calibration * WEIGHTS["confidence_calibration"]
        )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Win Rate (25%)
# ---------------------------------------------------------------------------


def score_win_rate(outcomes: Sequence[str | None]) -> float:
    """Fraction of resolved signals that are 'WIN'.

    Pending signals (None) are excluded from the denominator.
    """
    resolved = [o for o in outcomes if o is not None]
    if not resolved:
        return 0.0
    wins = sum(1 for o in resolved if o == "WIN")
    return _clamp(wins / len(resolved))


# ---------------------------------------------------------------------------
# Risk-Adjusted Return (25%)
# ---------------------------------------------------------------------------


def score_risk_adjusted_return(
    outcomes: Sequence[str | None],
    confidences: Sequence[float],
) -> float:
    """Simplified Sharpe-like score based on confidence-weighted outcomes.

    Returns are modelled as +confidence for WIN, -confidence for LOSS,
    0 for NEUTRAL. The ratio of mean return to std-dev is then normalised
    to [0, 1] via a sigmoid.
    """
    paired = [(o, c) for o, c in zip(outcomes, confidences) if o is not None]
    if len(paired) < 2:
        return 0.0

    returns = []
    for outcome, conf in paired:
        if outcome == "WIN":
            returns.append(conf)
        elif outcome == "LOSS":
            returns.append(-conf)
        else:
            returns.append(0.0)

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(variance) if variance > 0 else 1e-9
    sharpe = mean_r / std_r
    # Sigmoid normalisation: sigmoid(sharpe) maps (-inf,+inf) -> (0,1)
    sharpe_clamped = max(-500.0, min(500.0, sharpe))
    normalised = 1.0 / (1.0 + math.exp(-sharpe_clamped))
    return _clamp(normalised)


# ---------------------------------------------------------------------------
# Reasoning Quality (20%)
# ---------------------------------------------------------------------------

_QUALITY_KEYWORDS = {
    "support",
    "resistance",
    "volume",
    "trend",
    "momentum",
    "divergence",
    "rsi",
    "macd",
    "ema",
    "sma",
    "bollinger",
    "fibonacci",
    "breakout",
    "pattern",
    "fundamental",
    "earnings",
    "revenue",
    "margin",
    "volatility",
    "correlation",
    "beta",
    "alpha",
    "liquidity",
    "spread",
    "orderbook",
}


def score_reasoning_quality(reasoning_texts: Sequence[str]) -> float:
    """Heuristic quality score for a creator's reasoning corpus.

    Factors:
    - Average word count per signal (more words → higher quality, up to 150)
    - Keyword density (technical terms from a curated set)
    - Average sentence count (structured multi-sentence reasoning is better)
    """
    if not reasoning_texts:
        return 0.0

    word_counts = []
    keyword_densities = []
    sentence_counts = []

    for text in reasoning_texts:
        words = [w.lower() for w in re.split(r"\s+", text.strip()) if w]
        word_count = len(words)
        keyword_hits = sum(1 for w in words if w.rstrip(".,;:") in _QUALITY_KEYWORDS)
        sentences = len([s for s in re.split(r"[.!?]+", text) if s.strip()])

        word_counts.append(word_count)
        keyword_densities.append(keyword_hits / max(word_count, 1))
        sentence_counts.append(sentences)

    avg_words = sum(word_counts) / len(word_counts)
    avg_kd = sum(keyword_densities) / len(keyword_densities)
    avg_sentences = sum(sentence_counts) / len(sentence_counts)

    # Normalise each sub-score
    word_score = _clamp(avg_words / 150.0)  # 150 words = perfect word score
    kd_score = _clamp(avg_kd / 0.10)  # 10% keyword density = perfect
    sentence_score = _clamp(avg_sentences / 5.0)  # 5 sentences = perfect

    return _clamp(0.4 * word_score + 0.4 * kd_score + 0.2 * sentence_score)


# ---------------------------------------------------------------------------
# Consistency (20%)
# ---------------------------------------------------------------------------


def score_consistency(
    outcomes: Sequence[str | None],
    window: int = 10,
) -> float:
    """Measures stability of win-rate across rolling windows.

    A creator who wins consistently across different market periods scores
    higher than one with a single hot streak. Returns 0 if fewer than
    window resolved signals exist.
    """
    resolved = [o for o in outcomes if o is not None]
    if len(resolved) < window:
        return _clamp(len(resolved) / window * 0.5)  # partial credit

    window_rates = []
    for i in range(len(resolved) - window + 1):
        chunk = resolved[i : i + window]
        rate = sum(1 for o in chunk if o == "WIN") / window
        window_rates.append(rate)

    mean_wr = sum(window_rates) / len(window_rates)
    variance = sum((r - mean_wr) ** 2 for r in window_rates) / len(window_rates)
    std_wr = math.sqrt(variance)

    # Low std_dev → high consistency. Map std in [0, 0.5] to score [1, 0].
    consistency = _clamp(1.0 - (std_wr / 0.5))
    # Blend with mean win-rate so low performers can't score high on consistency alone
    return _clamp(consistency * 0.6 + mean_wr * 0.4)


# ---------------------------------------------------------------------------
# Confidence Calibration (10%)
# ---------------------------------------------------------------------------


def score_confidence_calibration(
    outcomes: Sequence[str | None],
    confidences: Sequence[float],
) -> float:
    """Brier-score-based calibration: how well confidence predicts outcomes.

    Perfect calibration (stated confidence matches win probability) scores 1.0.
    Brier score = mean((confidence - outcome_binary)^2), range [0, 1].
    We invert and normalise: calibration = 1 - 2 * brier_score.
    """
    paired = [(o, c) for o, c in zip(outcomes, confidences) if o is not None]
    if not paired:
        return 0.0

    brier = sum((conf - (1.0 if outcome == "WIN" else 0.0)) ** 2 for outcome, conf in paired) / len(
        paired
    )

    # Brier score 0 = perfect, 1 = worst. 1 - 2*brier maps [0,0.5] -> [1,0].
    calibration = 1.0 - 2.0 * brier
    return _clamp(calibration)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_score(
    outcomes: list[str | None],
    confidences: list[float],
    reasoning_texts: list[str],
) -> ScoreDimensions:
    """Compute all five dimensions and return a ScoreDimensions instance."""
    return ScoreDimensions(
        win_rate=score_win_rate(outcomes),
        risk_adjusted_return=score_risk_adjusted_return(outcomes, confidences),
        reasoning_quality=score_reasoning_quality(reasoning_texts),
        consistency=score_consistency(outcomes),
        confidence_calibration=score_confidence_calibration(outcomes, confidences),
    )
