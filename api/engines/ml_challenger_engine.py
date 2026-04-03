from __future__ import annotations

from math import exp

from engines.base import BaseSignalEngine, EngineContext, EngineDecision
from engines.heuristic_engine import HeuristicSignalEngine
from feature_builder import build_feature_snapshot, pct_change


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp_value = exp(-value)
        return 1.0 / (1.0 + exp_value)
    exp_value = exp(value)
    return exp_value / (1.0 + exp_value)


def _softmax(scores: list[float]) -> list[float]:
    peak = max(scores)
    weights = [exp(score - peak) for score in scores]
    total = sum(weights) or 1.0
    return [weight / total for weight in weights]


def _classify_direction(reference_price: float, realized_price: float, flat_threshold_pct: float = 0.25) -> str:
    change_pct = pct_change(realized_price, reference_price)
    if change_pct >= flat_threshold_pct:
        return "up"
    if change_pct <= -flat_threshold_pct:
        return "down"
    return "sideways"


class MLChallengerSignalEngine(BaseSignalEngine):
    engine_name = "ml_challenger"
    model_version = "logistic-challenger@2026.04.02"

    def __init__(
        self,
        training_samples: int = 96,
        epochs: int = 160,
        learning_rate: float = 0.06,
        l2_penalty: float = 0.0005,
    ) -> None:
        self.training_samples = training_samples
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2_penalty = l2_penalty
        self.fallback_engine = HeuristicSignalEngine()
        self.feature_order = [
            "sma_gap_pct",
            "momentum_pct",
            "recent_change_pct",
            "volatility_pct",
            "volume_ratio_pct",
            "support_distance_pct",
            "resistance_distance_pct",
        ]

    def required_history(self, lookback: int, forecast_horizon: int) -> int:
        return max(lookback, lookback + forecast_horizon + self.training_samples)

    def score(self, context: EngineContext) -> EngineDecision:
        training_rows = self._build_training_rows(context.candles, context.lookback, context.forecast_horizon)
        if len(training_rows) < 24:
            return self.fallback_engine.score(context)

        class_labels = sorted({row["label"] for row in training_rows})
        if len(class_labels) < 2:
            return self.fallback_engine.score(context)

        normalized_rows, stats = self._normalize_rows(training_rows)
        normalized_active = self._normalize_vector(self._vectorize_features(context.features), stats)

        label_scores: dict[str, float] = {}
        for label in ("up", "down", "sideways"):
            weights = self._fit_binary_classifier(normalized_rows, label)
            label_scores[label] = self._score_vector(weights, normalized_active)

        class_probabilities = _softmax([label_scores["up"], label_scores["down"], label_scores["sideways"]])
        probability_map = {
            "up": class_probabilities[0],
            "down": class_probabilities[1],
            "sideways": class_probabilities[2],
        }

        best_label = max(probability_map, key=probability_map.get)
        up_probability = probability_map["up"]
        down_probability = probability_map["down"]
        sideways_probability = probability_map["sideways"]

        if sideways_probability >= 0.34 or abs(up_probability - down_probability) <= 0.08:
            direction = "sideways"
        else:
            direction = "up" if up_probability > down_probability else "down"

        confidence_score = round(abs(up_probability - down_probability) * 100.0, 2)
        return EngineDecision(
            direction=direction,
            probability_up=round(up_probability * 100.0, 2),
            probability_down=round(down_probability * 100.0, 2),
            confidence_score=confidence_score,
        )

    def _build_training_rows(self, candles, lookback: int, forecast_horizon: int) -> list[dict[str, object]]:
        eligible_end_indexes = list(range(lookback - 1, len(candles) - forecast_horizon))
        active_indexes = eligible_end_indexes[-self.training_samples :]
        rows: list[dict[str, object]] = []

        for end_index in active_indexes:
            history = candles[end_index - lookback + 1 : end_index + 1]
            reference_candle = history[-1]
            outcome_candle = candles[end_index + forecast_horizon]
            label = _classify_direction(reference_candle.close_price, outcome_candle.close_price)
            features = build_feature_snapshot(history, lookback)
            rows.append({"features": self._vectorize_features(features), "label": label})

        return rows

    def _vectorize_features(self, features: dict[str, float]) -> list[float]:
        latest_close = max(float(features["latest_close_price"]), 1.0)
        support_level = max(float(features["support_level"]), 1.0)
        resistance_level = max(float(features["resistance_level"]), latest_close)
        engineered = {
            "sma_gap_pct": pct_change(features["short_sma"], features["long_sma"]),
            "momentum_pct": float(features["momentum_pct"]),
            "recent_change_pct": float(features["recent_change_pct"]),
            "volatility_pct": float(features["volatility_pct"]),
            "volume_ratio_pct": float(features["volume_ratio_pct"]),
            "support_distance_pct": pct_change(latest_close, support_level),
            "resistance_distance_pct": pct_change(resistance_level, latest_close),
        }
        return [engineered[key] for key in self.feature_order]

    def _normalize_rows(self, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[tuple[float, float]]]:
        feature_count = len(self.feature_order)
        stats: list[tuple[float, float]] = []
        for feature_index in range(feature_count):
            values = [float(row["features"][feature_index]) for row in rows]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
            std = variance ** 0.5 or 1.0
            stats.append((mean, std))

        normalized_rows = []
        for row in rows:
            normalized_rows.append(
                {
                    "features": self._normalize_vector([float(value) for value in row["features"]], stats),
                    "label": row["label"],
                }
            )
        return normalized_rows, stats

    def _normalize_vector(self, values: list[float], stats: list[tuple[float, float]]) -> list[float]:
        return [(value - mean) / std for value, (mean, std) in zip(values, stats, strict=False)]

    def _fit_binary_classifier(self, rows: list[dict[str, object]], positive_label: str) -> list[float]:
        feature_count = len(self.feature_order)
        weights = [0.0] * (feature_count + 1)

        for _ in range(self.epochs):
            for row in rows:
                vector = row["features"]
                target = 1.0 if row["label"] == positive_label else 0.0
                prediction = _sigmoid(self._score_vector(weights, vector))
                error = prediction - target
                weights[0] -= self.learning_rate * error
                for index, value in enumerate(vector, start=1):
                    gradient = (error * value) + (self.l2_penalty * weights[index])
                    weights[index] -= self.learning_rate * gradient

        return weights

    def _score_vector(self, weights: list[float], vector: list[float]) -> float:
        return weights[0] + sum(weight * value for weight, value in zip(weights[1:], vector))
