"""Cryptographic commitment for signals.

Every signal receives a SHA-256 hash of its canonical fields before
being written to the append-only log. The hash proves the signal content
was fixed at submission time.

Design invariant: this module NEVER issues UPDATE or DELETE against the
signals table. All writes go through _append_signal() only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime


def compute_commitment_hash(
    creator_id: str,
    asset: str,
    action: str,
    confidence: float,
    reasoning: str,
    supporting_data: dict,
    target_price: float | None,
    stop_loss: float | None,
    timeframe: str | None,
    nonce: str,
) -> str:
    """Return a deterministic SHA-256 hex digest of the signal fields.

    Fields are serialised as canonical JSON (sorted keys, no whitespace)
    so the hash is reproducible by any verifier with the same inputs.
    """
    payload = {
        "creator_id": creator_id,
        "asset": asset,
        "action": action,
        "confidence": round(float(confidence), 4),
        "reasoning": reasoning,
        "supporting_data": supporting_data,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "timeframe": timeframe,
        "nonce": nonce,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def generate_signal_id() -> str:
    """Return a unique signal ID (UUID4 hex, no hyphens)."""
    return uuid.uuid4().hex


def build_committed_signal(signal_data: dict) -> dict:
    """Attach signal_id, nonce, commitment_hash, and committed_at to signal_data.

    Returns the enriched dict ready for DB insertion. Input dict must
    contain all required SignalCreate fields plus creator_id injected by auth.
    """
    nonce = uuid.uuid4().hex
    signal_id = generate_signal_id()
    committed_at = datetime.now(UTC)

    commitment_hash = compute_commitment_hash(
        creator_id=signal_data["creator_id"],
        asset=signal_data["asset"],
        action=(
            signal_data["action"]
            if isinstance(signal_data["action"], str)
            else signal_data["action"].value
        ),
        confidence=signal_data["confidence"],
        reasoning=signal_data["reasoning"],
        supporting_data=signal_data["supporting_data"],
        target_price=signal_data.get("target_price"),
        stop_loss=signal_data.get("stop_loss"),
        timeframe=signal_data.get("timeframe"),
        nonce=nonce,
    )

    return {
        **signal_data,
        "signal_id": signal_id,
        "nonce": nonce,
        "commitment_hash": commitment_hash,
        "committed_at": committed_at,
    }


def verify_commitment(signal_row: dict) -> bool:
    """Re-compute the hash and compare against the stored value."""
    expected = compute_commitment_hash(
        creator_id=signal_row["creator_id"],
        asset=signal_row["asset"],
        action=signal_row["action"],
        confidence=signal_row["confidence"],
        reasoning=signal_row["reasoning"],
        supporting_data=signal_row["supporting_data"],
        target_price=signal_row.get("target_price"),
        stop_loss=signal_row.get("stop_loss"),
        timeframe=signal_row.get("timeframe"),
        nonce=signal_row["nonce"],
    )
    return expected == signal_row["commitment_hash"]
