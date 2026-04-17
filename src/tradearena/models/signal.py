"""Signal dataclass and validation models."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalAction(StrEnum):
    buy = "buy"
    sell = "sell"
    yes = "yes"
    no = "no"
    long = "long"
    short = "short"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None


class Outcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    NEUTRAL = "NEUTRAL"


class SignalCreate(BaseModel):
    """Input model for creating a new signal.

    Submit a cryptographically committed trading prediction. The signal is
    hashed with SHA-256 on the server to create a tamper-proof commitment.
    Outcomes are resolved automatically by the oracle after the timeframe expires.
    """

    asset: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Trading pair or asset symbol, e.g. BTCUSDT, ETHUSDT",
    )
    action: SignalAction = Field(
        ...,
        description="Directional prediction: buy, sell, long, short, yes, no",
    )
    confidence: float = Field(
        ...,
        ge=0.01,
        le=0.99,
        description="Prediction confidence between 0.01 and 0.99 (exclusive)",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Analysis justifying the signal — minimum 20 words, maximum 10,000 characters",
    )
    supporting_data: dict[str, Any] = Field(
        ...,
        description="Evidence backing the signal — minimum 2 keys, maximum 20 keys",
    )
    target_price: float | None = Field(
        None,
        gt=0,
        description="Expected price target (must be > 0)",
    )
    stop_loss: float | None = Field(
        None,
        gt=0,
        description="Stop-loss price level (must be > 0)",
    )
    timeframe: str | None = Field(
        None,
        description="Resolution window: 1h, 4h, 1d, or 1w",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "asset": "BTCUSDT",
                    "action": "long",
                    "confidence": 0.75,
                    "reasoning": (
                        "BTC showing strong momentum with a clear breakout above"
                        " the 50-day moving average on high volume. RSI at 62"
                        " indicates bullish momentum without being overbought."
                        " On-chain metrics show accumulation by large holders."
                    ),
                    "supporting_data": {
                        "rsi_14": 62.3,
                        "volume_change_24h": "+45%",
                        "ma_50_crossover": True,
                    },
                    "target_price": 72000.0,
                    "stop_loss": 65000.0,
                    "timeframe": "1d",
                }
            ]
        },
    )

    @field_validator("confidence")
    @classmethod
    def confidence_not_extremes(cls, v: float) -> float:
        if v <= 0.0 or v >= 1.0:
            raise ValueError("confidence must be strictly between 0 and 1 (exclusive)")
        return round(v, 4)

    @field_validator("reasoning")
    @classmethod
    def reasoning_min_words(cls, v: str) -> str:
        words = [w for w in re.split(r"\s+", v.strip()) if w]
        if len(words) < 20:
            raise ValueError(f"reasoning must be at least 20 words (got {len(words)})")
        return v

    @field_validator("asset")
    @classmethod
    def asset_format(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9/.\-]{1,20}$", v):
            raise ValueError(
                "asset must contain only uppercase letters, digits, /, ., or - (e.g. BTC/USDT)"
            )
        return v

    @field_validator("timeframe")
    @classmethod
    def timeframe_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in {"1h", "4h", "1d", "1w"}:
            raise ValueError(f"timeframe must be one of: 1h, 4h, 1d, 1w (got {v!r})")
        return v

    @field_validator("supporting_data")
    @classmethod
    def supporting_data_min_keys(cls, v: dict) -> dict:
        if len(v) < 2:
            raise ValueError(f"supporting_data must have at least 2 keys (got {len(v)})")
        if len(v) > 20:
            raise ValueError(f"supporting_data must have at most 20 keys (got {len(v)})")
        return v

    @model_validator(mode="after")
    def stop_loss_below_target(self) -> SignalCreate:
        if (
            self.action in (SignalAction.buy, SignalAction.long, SignalAction.yes)
            and self.target_price is not None
            and self.stop_loss is not None
        ):
            if self.stop_loss >= self.target_price:
                raise ValueError("stop_loss must be below target_price for buy/long/yes signals")
        if (
            self.action in (SignalAction.sell, SignalAction.short, SignalAction.no)
            and self.target_price is not None
            and self.stop_loss is not None
        ):
            if self.stop_loss <= self.target_price:
                raise ValueError("stop_loss must be above target_price for sell/short/no signals")
        return self


class Signal(BaseModel):
    """Full signal model as stored and returned by the API."""

    signal_id: str
    creator_id: str
    asset: str
    asset_type: str | None = None  # crypto, stock, forex
    action: SignalAction
    confidence: float
    reasoning: str
    supporting_data: dict[str, Any]
    target_price: float | None
    stop_loss: float | None
    timeframe: str | None
    commitment_hash: str
    committed_at: datetime
    outcome: str | None = None  # "WIN" | "LOSS" | "NEUTRAL" | None (pending)
    outcome_price: float | None = None
    outcome_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SignalEmitResponse(BaseModel):
    """Response from POST /signal.

    Contains the signal ID, commitment hash (SHA-256), and timestamp
    proving the signal was committed at this exact moment.
    """

    signal_id: str = Field(..., description="UUID4 hex identifier (32 chars)")
    committed_at: str = Field(..., description="ISO 8601 UTC timestamp")
    commitment_hash: str = Field(..., description="SHA-256 hex digest (64 chars)")
    creator_id: str = Field(..., description="Creator who submitted the signal")
    asset: str = Field(..., description="Asset symbol from the signal")
    action: str = Field(..., description="Action from the signal")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "signal_id": "a1b2c3d4e5f6789012345678abcdef01",
                    "committed_at": "2026-03-21T14:30:00.000000",
                    "commitment_hash": "e3b0c44298fc1c14"
                    "9afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "creator_id": "alice-quantsworth-a1b2",
                    "asset": "BTCUSDT",
                    "action": "long",
                }
            ]
        },
    )
