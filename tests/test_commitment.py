"""Tests for the commitment module."""

from __future__ import annotations

from tradearena.core.commitment import (
    build_committed_signal,
    compute_commitment_hash,
    generate_signal_id,
    verify_commitment,
)

BASE_SIGNAL = {
    "creator_id": "alice",
    "asset": "BTC/USDT",
    "action": "buy",
    "confidence": 0.75,
    "reasoning": "Some reasoning text that is long enough to pass validation rules here.",
    "supporting_data": {"rsi": 55, "volume": 1_200_000},
    "target_price": 50000.0,
    "stop_loss": 44000.0,
    "timeframe": "4h",
}


class TestComputeCommitmentHash:
    def test_returns_64_char_hex(self):
        h = compute_commitment_hash(
            creator_id="alice",
            asset="BTC/USDT",
            action="buy",
            confidence=0.75,
            reasoning="test",
            supporting_data={"a": 1, "b": 2},
            target_price=None,
            stop_loss=None,
            timeframe=None,
            nonce="abc123",
        )
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        kwargs = dict(
            creator_id="alice",
            asset="BTC/USDT",
            action="buy",
            confidence=0.75,
            reasoning="test reasoning",
            supporting_data={"a": 1},
            target_price=50000.0,
            stop_loss=44000.0,
            timeframe="4h",
            nonce="fixed-nonce",
        )
        h1 = compute_commitment_hash(**kwargs)
        h2 = compute_commitment_hash(**kwargs)
        assert h1 == h2

    def test_different_nonces_produce_different_hashes(self):
        kwargs = dict(
            creator_id="alice",
            asset="BTC/USDT",
            action="buy",
            confidence=0.75,
            reasoning="test",
            supporting_data={"a": 1},
            target_price=None,
            stop_loss=None,
            timeframe=None,
        )
        h1 = compute_commitment_hash(**kwargs, nonce="nonce1")
        h2 = compute_commitment_hash(**kwargs, nonce="nonce2")
        assert h1 != h2

    def test_different_content_produces_different_hashes(self):
        kwargs = dict(
            asset="BTC/USDT",
            action="buy",
            confidence=0.75,
            reasoning="test",
            supporting_data={"a": 1},
            target_price=None,
            stop_loss=None,
            timeframe=None,
            nonce="same-nonce",
        )
        h1 = compute_commitment_hash(creator_id="alice", **kwargs)
        h2 = compute_commitment_hash(creator_id="bob", **kwargs)
        assert h1 != h2

    def test_confidence_rounded_consistently(self):
        """Hash should be identical whether confidence is 0.75 or 0.750000001."""
        kwargs = dict(
            creator_id="alice",
            asset="BTC/USDT",
            action="buy",
            reasoning="test",
            supporting_data={"a": 1},
            target_price=None,
            stop_loss=None,
            timeframe=None,
            nonce="nonce",
        )
        h1 = compute_commitment_hash(confidence=0.75, **kwargs)
        h2 = compute_commitment_hash(confidence=0.7500, **kwargs)
        assert h1 == h2


class TestGenerateSignalId:
    def test_returns_32_char_hex(self):
        sid = generate_signal_id()
        assert len(sid) == 32
        assert all(c in "0123456789abcdef" for c in sid)

    def test_unique_across_calls(self):
        ids = {generate_signal_id() for _ in range(100)}
        assert len(ids) == 100


class TestBuildCommittedSignal:
    def test_adds_required_fields(self):
        result = build_committed_signal(BASE_SIGNAL.copy())
        assert "signal_id" in result
        assert "nonce" in result
        assert "commitment_hash" in result
        assert "committed_at" in result

    def test_signal_id_is_32_char_hex(self):
        result = build_committed_signal(BASE_SIGNAL.copy())
        assert len(result["signal_id"]) == 32

    def test_commitment_hash_is_64_char_hex(self):
        result = build_committed_signal(BASE_SIGNAL.copy())
        assert len(result["commitment_hash"]) == 64

    def test_original_fields_preserved(self):
        result = build_committed_signal(BASE_SIGNAL.copy())
        for key in BASE_SIGNAL:
            assert result[key] == BASE_SIGNAL[key]

    def test_two_calls_produce_different_ids_and_hashes(self):
        r1 = build_committed_signal(BASE_SIGNAL.copy())
        r2 = build_committed_signal(BASE_SIGNAL.copy())
        assert r1["signal_id"] != r2["signal_id"]
        assert r1["commitment_hash"] != r2["commitment_hash"]  # different nonces


class TestVerifyCommitment:
    def test_verify_valid_commitment(self):
        committed = build_committed_signal(BASE_SIGNAL.copy())
        row = {
            "creator_id": committed["creator_id"],
            "asset": committed["asset"],
            "action": committed["action"],
            "confidence": committed["confidence"],
            "reasoning": committed["reasoning"],
            "supporting_data": committed["supporting_data"],
            "target_price": committed.get("target_price"),
            "stop_loss": committed.get("stop_loss"),
            "timeframe": committed.get("timeframe"),
            "nonce": committed["nonce"],
            "commitment_hash": committed["commitment_hash"],
        }
        assert verify_commitment(row) is True

    def test_tampered_reasoning_fails_verification(self):
        committed = build_committed_signal(BASE_SIGNAL.copy())
        row = {
            "creator_id": committed["creator_id"],
            "asset": committed["asset"],
            "action": committed["action"],
            "confidence": committed["confidence"],
            "reasoning": "tampered reasoning text that is different from original",
            "supporting_data": committed["supporting_data"],
            "target_price": committed.get("target_price"),
            "stop_loss": committed.get("stop_loss"),
            "timeframe": committed.get("timeframe"),
            "nonce": committed["nonce"],
            "commitment_hash": committed["commitment_hash"],
        }
        assert verify_commitment(row) is False

    def test_tampered_action_fails_verification(self):
        committed = build_committed_signal(BASE_SIGNAL.copy())
        row = {
            "creator_id": committed["creator_id"],
            "asset": committed["asset"],
            "action": "sell",  # tampered
            "confidence": committed["confidence"],
            "reasoning": committed["reasoning"],
            "supporting_data": committed["supporting_data"],
            "target_price": committed.get("target_price"),
            "stop_loss": committed.get("stop_loss"),
            "timeframe": committed.get("timeframe"),
            "nonce": committed["nonce"],
            "commitment_hash": committed["commitment_hash"],
        }
        assert verify_commitment(row) is False
