from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CandleCreate(BaseModel):
    open_price: float = Field(gt=0)
    high_price: float = Field(gt=0)
    low_price: float = Field(gt=0)
    close_price: float = Field(gt=0)
    volume_btc: float = Field(ge=0)
    source: str = Field(default="mock", min_length=1, max_length=64)
    timestamp: datetime | None = None

    @model_validator(mode="after")
    def validate_ohlc(self) -> "CandleCreate":
        price_floor = min(self.open_price, self.close_price)
        price_ceiling = max(self.open_price, self.close_price)
        if self.low_price > price_floor:
            raise ValueError("low_price must be <= open_price and close_price")
        if self.high_price < price_ceiling:
            raise ValueError("high_price must be >= open_price and close_price")
        return self


class CandleOut(CandleCreate):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class TrendSummaryOut(BaseModel):
    latest_close_price: float
    recent_change_pct: float
    short_sma: float
    long_sma: float
    momentum_pct: float
    volatility_pct: float
    trend_direction: Literal["up", "down", "sideways"]
    trend_strength_score: float
    support_level: float
    resistance_level: float
    narrative: str
    market_read: str
    what_to_watch: str


class PredictionRequest(BaseModel):
    lookback: int = Field(default=48, ge=12, le=500)
    forecast_horizon: int = Field(default=6, ge=1, le=72)


class PredictionOut(BaseModel):
    generated_at: datetime
    lookback: int
    forecast_horizon: int
    direction: Literal["up", "down", "sideways"]
    bias: Literal["long", "short", "neutral"]
    probability_up: float
    probability_down: float
    confidence_score: float
    setup_quality: Literal["A", "B", "C"]
    risk_level: Literal["low", "medium", "high"]
    summary: str
    guidance: str
    what_to_watch: str
    entry_plan: str
    entry_level: float | None = None
    invalidation_plan: str
    invalidation_level: float | None = None
    target_plan: str
    target_level: float | None = None
    risk_reward_ratio: float | None = None
    factors: list[str]


class SignalHistoryOut(BaseModel):
    id: int
    generated_at: datetime
    source: str
    reference_timestamp: datetime
    reference_price: float
    target_timestamp: datetime
    lookback: int
    forecast_horizon: int
    direction: Literal["up", "down", "sideways"]
    bias: Literal["long", "short", "neutral"]
    probability_up: float
    probability_down: float
    confidence_score: float
    setup_quality: Literal["A", "B", "C"]
    risk_level: Literal["low", "medium", "high"]
    summary: str
    guidance: str
    what_to_watch: str
    entry_plan: str | None = None
    entry_level: float | None = None
    invalidation_plan: str | None = None
    invalidation_level: float | None = None
    target_plan: str | None = None
    target_level: float | None = None
    risk_reward_ratio: float | None = None
    outcome_status: Literal["pending", "right", "wrong", "flat"]
    resolved_direction: Literal["up", "down", "sideways"] | None = None
    resolved_price: float | None = None
    realized_change_pct: float | None = None
    resolved_at: datetime | None = None

    class Config:
        from_attributes = True


class SignalStatsOut(BaseModel):
    sample_size: int
    resolved_signals: int
    pending_signals: int
    right_signals: int
    wrong_signals: int
    flat_signals: int
    hit_rate: float
    avg_resolved_change_pct: float
    avg_right_change_pct: float | None = None
    avg_wrong_change_pct: float | None = None
    summary: str


class ActionReadOut(BaseModel):
    label: str
    lookback: int
    forecast_horizon: int
    direction: Literal["up", "down", "sideways"]
    bias: Literal["long", "short", "neutral"]
    setup_quality: Literal["A", "B", "C"]
    risk_level: Literal["low", "medium", "high"]
    probability_up: float
    probability_down: float
    summary: str
    guidance: str
    what_to_watch: str
    entry_plan: str
    entry_level: float | None = None
    invalidation_plan: str
    invalidation_level: float | None = None
    target_plan: str
    target_level: float | None = None
    risk_reward_ratio: float | None = None


class MultiReadOut(BaseModel):
    generated_at: datetime
    reads: list[ActionReadOut]


class PerformanceBucketOut(BaseModel):
    key: str
    total_signals: int
    resolved_signals: int
    hit_rate: float
    avg_change_pct: float


class SignalPerformanceOut(BaseModel):
    sample_size: int
    bias_breakdown: list[PerformanceBucketOut]
    setup_breakdown: list[PerformanceBucketOut]
    best_bias: str | None = None
    best_setup_quality: str | None = None
