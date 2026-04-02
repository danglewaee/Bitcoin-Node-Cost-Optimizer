from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineDecision:
    direction: str
    probability_up: float
    probability_down: float
    confidence_score: float


class BaseSignalEngine(ABC):
    engine_name: str
    model_version: str

    @abstractmethod
    def score(self, features: dict[str, float], forecast_horizon: int) -> EngineDecision:
        raise NotImplementedError
