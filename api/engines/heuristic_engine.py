from __future__ import annotations

from feature_builder import sigmoid


def build_heuristic_decision(features: dict[str, float], forecast_horizon: int) -> dict[str, float | str]:
    horizon_decay = max(0.6, 1.0 - (forecast_horizon * 0.03))
    adjusted_probability_up = sigmoid(((features["probability_up"] - 0.5) * 10.0) * horizon_decay)
    probability_up = round(adjusted_probability_up * 100.0, 2)
    probability_down = round((1.0 - adjusted_probability_up) * 100.0, 2)
    confidence_score = round(abs(adjusted_probability_up - 0.5) * 200.0, 2)

    if adjusted_probability_up >= 0.55:
        direction = "up"
    elif adjusted_probability_up <= 0.45:
        direction = "down"
    else:
        direction = "sideways"

    return {
        "direction": direction,
        "probability_up": probability_up,
        "probability_down": probability_down,
        "confidence_score": confidence_score,
    }
