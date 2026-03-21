"""Tests for signal validation rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tradearena.core.validation import validate_signal
from tradearena.models.signal import SignalAction, SignalCreate

VALID_SIGNAL = {
    "asset": "BTC/USDT",
    "action": "buy",
    "confidence": 0.75,
    "reasoning": (
        "Bitcoin is forming a bullish pattern with strong volume support. "
        "The RSI is in the neutral zone and the MACD is crossing bullish. "
        "This setup has historically preceded significant upward moves."
    ),
    "supporting_data": {"rsi": 55, "volume": 1_200_000},
    "target_price": 50000.0,
    "stop_loss": 44000.0,
    "timeframe": "4h",
}


class TestValidateSignalFunction:
    def test_valid_signal_returns_no_errors(self):
        errors = validate_signal(VALID_SIGNAL)
        assert errors == []

    def test_missing_action(self):
        data = {**VALID_SIGNAL}
        del data["action"]
        errors = validate_signal(data)
        assert any("action" in e for e in errors)

    def test_invalid_action(self):
        errors = validate_signal({**VALID_SIGNAL, "action": "MOON"})
        assert any("action" in e for e in errors)

    def test_confidence_zero(self):
        errors = validate_signal({**VALID_SIGNAL, "confidence": 0.0})
        assert any("confidence" in e for e in errors)

    def test_confidence_one(self):
        errors = validate_signal({**VALID_SIGNAL, "confidence": 1.0})
        assert any("confidence" in e for e in errors)

    def test_confidence_exactly_min(self):
        errors = validate_signal({**VALID_SIGNAL, "confidence": 0.01})
        assert errors == []

    def test_confidence_exactly_max(self):
        errors = validate_signal({**VALID_SIGNAL, "confidence": 0.99})
        assert errors == []

    def test_reasoning_too_short(self):
        errors = validate_signal({**VALID_SIGNAL, "reasoning": "Too short"})
        assert any("reasoning" in e for e in errors)

    def test_reasoning_exactly_20_words(self):
        reasoning = " ".join(["word"] * 20)
        errors = validate_signal({**VALID_SIGNAL, "reasoning": reasoning})
        assert errors == []

    def test_reasoning_19_words_fails(self):
        reasoning = " ".join(["word"] * 19)
        errors = validate_signal({**VALID_SIGNAL, "reasoning": reasoning})
        assert any("reasoning" in e for e in errors)

    def test_supporting_data_one_key_fails(self):
        errors = validate_signal({**VALID_SIGNAL, "supporting_data": {"rsi": 55}})
        assert any("supporting_data" in e for e in errors)

    def test_supporting_data_two_keys_passes(self):
        errors = validate_signal({**VALID_SIGNAL, "supporting_data": {"a": 1, "b": 2}})
        assert errors == []

    def test_missing_asset(self):
        data = {**VALID_SIGNAL}
        del data["asset"]
        errors = validate_signal(data)
        assert any("asset" in e for e in errors)

    def test_negative_target_price(self):
        errors = validate_signal({**VALID_SIGNAL, "target_price": -100.0})
        assert any("target_price" in e for e in errors)


class TestSignalCreateModel:
    def test_valid_signal_parses(self):
        signal = SignalCreate(**VALID_SIGNAL)
        assert signal.action == SignalAction.buy
        assert signal.confidence == 0.75

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(**{**VALID_SIGNAL, "confidence": -0.1})

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(**{**VALID_SIGNAL, "confidence": 1.1})

    def test_confidence_zero_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(**{**VALID_SIGNAL, "confidence": 0.0})

    def test_confidence_one_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(**{**VALID_SIGNAL, "confidence": 1.0})

    def test_all_valid_actions(self):
        for action in ("buy", "sell", "yes", "no", "long", "short"):
            data = {**VALID_SIGNAL, "action": action}
            if action in ("sell", "short", "no"):
                data["stop_loss"] = 56000.0  # stop above target for short-side actions
                data["target_price"] = 44000.0
            elif action in ("buy", "long", "yes"):
                data["stop_loss"] = 44000.0
                data["target_price"] = 50000.0
            signal = SignalCreate(**data)
            assert signal.action.value == action

    def test_buy_stop_above_target_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(
                **{**VALID_SIGNAL, "action": "buy", "target_price": 44000.0, "stop_loss": 50000.0}
            )

    def test_sell_stop_below_target_raises(self):
        with pytest.raises(ValidationError):
            SignalCreate(
                **{
                    **VALID_SIGNAL,
                    "action": "sell",
                    "target_price": 50000.0,
                    "stop_loss": 44000.0,
                }
            )

    def test_confidence_is_rounded_to_4dp(self):
        signal = SignalCreate(**{**VALID_SIGNAL, "confidence": 0.123456789})
        assert signal.confidence == 0.1235
