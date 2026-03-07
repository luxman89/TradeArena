"""Signal dataclass and validation models."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalAction(str, Enum):
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


class SignalCreate(BaseModel):
    """Input model for creating a new signal."""

    asset: str = Field(..., min_length=1, max_length=20, description="e.g. BTC, ETH/USDT")
    action: SignalAction
    confidence: float = Field(..., ge=0.01, le=0.99, description="Must be strictly between 0 and 1")
    reasoning: str = Field(..., min_length=1, description="Minimum 20 words required")
    supporting_data: dict[str, Any] = Field(..., description="Minimum 2 keys required")
    target_price: float | None = Field(None, gt=0)
    stop_loss: float | None = Field(None, gt=0)
    timeframe: str | None = Field(None, description="e.g. 1h, 4h, 1d")

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

    @field_validator("supporting_data")
    @classmethod
    def supporting_data_min_keys(cls, v: dict) -> dict:
        if len(v) < 2:
            raise ValueError(f"supporting_data must have at least 2 keys (got {len(v)})")
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
