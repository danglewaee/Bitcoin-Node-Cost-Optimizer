from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from models import PriceCandle


@dataclass(frozen=True)
class EngineDecision:
    direction: str
    probability_up: float
    probability_down: float
    confidence_score: float


@dataclass(frozen=True)
class EngineContext:
    candles: list[PriceCandle]
    features: dict[str, float]
    lookback: int
    forecast_horizon: int


class BaseSignalEngine(ABC):
    engine_name: str
    model_version: str

    def required_history(self, lookback: int, forecast_horizon: int) -> int:
        return lookback

    @abstractmethod
    def score(self, context: EngineContext) -> EngineDecision:
        raise NotImplementedError
