"""TradeArena SDK client.

Works standalone for validate() — no server required.
Requires a network connection only for emit().
"""

from __future__ import annotations

import re
import sys
from typing import Any

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

# Validation is vendored here so the SDK has zero dependency on the server package.
# Keep in sync with src/tradearena/core/validation.py.
ALLOWED_ACTIONS = {"BUY", "SELL", "HOLD", "SHORT", "COVER"}


def _validate_local(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    action = data.get("action")
    if action is None:
        errors.append("action is required")
    elif action not in ALLOWED_ACTIONS:
        errors.append(f"action must be one of {sorted(ALLOWED_ACTIONS)}, got '{action}'")

    confidence = data.get("confidence")
    if confidence is None:
        errors.append("confidence is required")
    else:
        try:
            conf_f = float(confidence)
        except (TypeError, ValueError):
            errors.append("confidence must be a number")
            conf_f = None
        if conf_f is not None and (conf_f <= 0.0 or conf_f >= 1.0):
            errors.append(
                f"confidence must be strictly between 0 and 1 (exclusive), got {conf_f}"
            )

    reasoning = data.get("reasoning", "")
    if not reasoning:
        errors.append("reasoning is required")
    else:
        words = [w for w in re.split(r"\s+", str(reasoning).strip()) if w]
        if len(words) < 20:
            errors.append(f"reasoning must be at least 20 words (got {len(words)})")

    supporting_data = data.get("supporting_data")
    if supporting_data is None:
        errors.append("supporting_data is required")
    elif not isinstance(supporting_data, dict):
        errors.append("supporting_data must be a JSON object")
    elif len(supporting_data) < 2:
        errors.append(f"supporting_data must have at least 2 keys (got {len(supporting_data)})")

    if not data.get("symbol"):
        errors.append("symbol is required")
    if not data.get("creator_id"):
        errors.append("creator_id is required")

    return errors


class TradeArenaClient:
    """High-level client for the TradeArena API.

    Parameters
    ----------
    api_key:
        Your TradeArena API key. Required for emit().
    base_url:
        Base URL of the TradeArena server.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Validate — no network, works standalone
    # ------------------------------------------------------------------

    def validate(self, signal_data: dict[str, Any]) -> list[str]:
        """Validate signal_data locally. Returns a list of error strings.

        An empty list means the signal is valid and ready to emit.
        No network call is made.

        Example
        -------
        >>> errors = client.validate({"action": "BUY", ...})
        >>> if errors:
        ...     print(errors)
        """
        return _validate_local(signal_data)

    # ------------------------------------------------------------------
    # Emit — requires server
    # ------------------------------------------------------------------

    def emit(self, signal_data: dict[str, Any]) -> dict:
        """Validate and emit a signal to the TradeArena server.

        Runs local validation first. Raises ValueError if invalid.
        Raises RuntimeError if httpx is not installed.
        Returns the server response dict including signal_id and committed_at.
        """
        if not _HTTPX_AVAILABLE:
            raise RuntimeError(
                "httpx is required for emit(). Install it: pip install httpx"
            )

        errors = self.validate(signal_data)
        if errors:
            raise ValueError(f"Signal validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/signal",
                json=signal_data,
                headers={"X-API-Key": self.api_key},
            )
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # generate_reasoning — uses Anthropic Claude
    # ------------------------------------------------------------------

    def generate_reasoning(
        self,
        symbol: str,
        action: str,
        supporting_data: dict[str, Any],
        model: str = "claude-haiku-4-5-20251001",
    ) -> str:
        """Use Claude to generate high-quality reasoning for a signal.

        Requires ANTHROPIC_API_KEY in the environment.
        Returns a reasoning string guaranteed to be >= 20 words.
        """
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package required. Install: pip install anthropic"
            )

        client = anthropic.Anthropic()
        data_summary = "\n".join(f"  {k}: {v}" for k, v in supporting_data.items())
        prompt = (
            f"You are a trading analyst. Generate concise, factual reasoning for the "
            f"following signal. Be specific and reference the provided data.\n\n"
            f"Symbol: {symbol}\n"
            f"Action: {action}\n"
            f"Supporting data:\n{data_summary}\n\n"
            f"Write 2-4 sentences of reasoning. Do not use bullet points."
        )
        message = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    # ------------------------------------------------------------------
    # calculate_confidence — heuristic
    # ------------------------------------------------------------------

    def calculate_confidence(
        self,
        signal_strength: float,
        data_quality: float,
        market_clarity: float,
    ) -> float:
        """Compute a calibrated confidence score from three input factors.

        All inputs should be in [0, 1]. Output is in [0.01, 0.99].

        Parameters
        ----------
        signal_strength:
            How strong the technical or fundamental signal is (0–1).
        data_quality:
            Quality/completeness of the supporting data (0–1).
        market_clarity:
            How clear/low-noise the market conditions are (0–1).
        """
        raw = 0.4 * signal_strength + 0.35 * data_quality + 0.25 * market_clarity
        # Squeeze to [0.01, 0.99] to never hit the extremes
        return round(max(0.01, min(0.99, raw)), 4)
