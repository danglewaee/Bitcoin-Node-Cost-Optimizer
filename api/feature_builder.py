from __future__ import annotations

from math import exp
from statistics import pstdev

from models import PriceCandle


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pct_change(new_value: float, old_value: float) -> float:
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100.0


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + exp(-value))


def rolling_window(values: list[float], size: int) -> list[float]:
    return values[-size:] if len(values) >= size else values


def build_feature_snapshot(candles: list[PriceCandle], lookback: int | None = None) -> dict[str, float]:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    closes = [float(candle.close_price) for candle in ordered]
    volumes = [float(candle.volume_btc) for candle in ordered]
    active_lookback = min(lookback or len(closes), len(closes))

    closes = closes[-active_lookback:]
    volumes = volumes[-active_lookback:]

    short_window = max(5, min(12, len(closes)))
    long_window = max(short_window, min(24, len(closes)))
    momentum_window = max(3, min(12, len(closes)))
    recent_window = max(2, min(24, len(closes)))

    short_sma = average(rolling_window(closes, short_window))
    long_sma = average(rolling_window(closes, long_window))
    momentum_pct = pct_change(closes[-1], closes[-momentum_window])
    recent_change_pct = pct_change(closes[-1], closes[-recent_window])

    returns = [pct_change(closes[idx], closes[idx - 1]) for idx in range(1, len(closes))]
    volatility_pct = pstdev(returns) if len(returns) >= 2 else 0.0

    short_volume = average(rolling_window(volumes, short_window))
    long_volume = average(rolling_window(volumes, long_window))
    volume_ratio_pct = pct_change(short_volume, long_volume) if long_volume else 0.0

    support_level = min(rolling_window(closes, long_window))
    resistance_level = max(rolling_window(closes, long_window))

    raw_score = (
        (pct_change(short_sma, long_sma) * 1.4)
        + (momentum_pct * 0.9)
        + (recent_change_pct * 0.7)
        + (volume_ratio_pct * 0.2)
        - (volatility_pct * 0.25)
    )

    probability_up = sigmoid(raw_score / 6.0)
    trend_strength_score = round(abs(probability_up - 0.5) * 200.0, 2)

    if probability_up >= 0.55:
        trend_direction = "up"
    elif probability_up <= 0.45:
        trend_direction = "down"
    else:
        trend_direction = "sideways"

    return {
        "latest_close_price": round(closes[-1], 2),
        "recent_change_pct": round(recent_change_pct, 2),
        "short_sma": round(short_sma, 2),
        "long_sma": round(long_sma, 2),
        "momentum_pct": round(momentum_pct, 2),
        "volatility_pct": round(volatility_pct, 2),
        "support_level": round(support_level, 2),
        "resistance_level": round(resistance_level, 2),
        "probability_up": probability_up,
        "trend_strength_score": trend_strength_score,
        "trend_direction": trend_direction,
        "volume_ratio_pct": round(volume_ratio_pct, 2),
    }
