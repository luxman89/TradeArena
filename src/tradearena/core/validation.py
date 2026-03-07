"""Signal validation rules — reusable by both the API and SDK.

All functions return a list of error strings (empty = valid).
"""

from __future__ import annotations

import re
from typing import Any

ALLOWED_ACTIONS = {"buy", "sell", "yes", "no", "long", "short"}


def validate_signal(data: dict[str, Any]) -> list[str]:
    """Run all validation rules against a raw signal dict.

    Returns a list of human-readable error strings. An empty list means
    the signal is valid. This function is intentionally side-effect-free
    so it can be used in the SDK without any server connection.
    """
    errors: list[str] = []

    # --- action ---
    action = data.get("action")
    if action is None:
        errors.append("action is required")
    elif str(action).lower() not in ALLOWED_ACTIONS:
        errors.append(f"action must be one of {sorted(ALLOWED_ACTIONS)}, got '{action}'")

    # --- confidence ---
    confidence = data.get("confidence")
    if confidence is None:
        errors.append("confidence is required")
    else:
        try:
            conf_f = float(confidence)
        except (TypeError, ValueError):
            errors.append("confidence must be a number")
            conf_f = None
        if conf_f is not None:
            if conf_f <= 0.0 or conf_f >= 1.0:
                errors.append(
                    f"confidence must be strictly between 0 and 1 (exclusive), got {conf_f}"
                )

    # --- reasoning ---
    reasoning = data.get("reasoning", "")
    if not reasoning:
        errors.append("reasoning is required")
    else:
        words = [w for w in re.split(r"\s+", str(reasoning).strip()) if w]
        if len(words) < 20:
            errors.append(f"reasoning must be at least 20 words (got {len(words)})")

    # --- supporting_data ---
    supporting_data = data.get("supporting_data")
    if supporting_data is None:
        errors.append("supporting_data is required")
    elif not isinstance(supporting_data, dict):
        errors.append("supporting_data must be a JSON object")
    elif len(supporting_data) < 2:
        errors.append(f"supporting_data must have at least 2 keys (got {len(supporting_data)})")

    # --- asset ---
    if not data.get("asset"):
        errors.append("asset is required")

    # --- optional numeric fields ---
    for field in ("target_price", "stop_loss"):
        val = data.get(field)
        if val is not None:
            try:
                fval = float(val)
                if fval <= 0:
                    errors.append(f"{field} must be greater than 0")
            except (TypeError, ValueError):
                errors.append(f"{field} must be a number")

    return errors
