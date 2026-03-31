from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp
from statistics import median, pstdev

from models import PriceCandle
from schemas import PredictionOut, TrendSummaryOut


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct_change(new_value: float, old_value: float) -> float:
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100.0


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + exp(-value))


def _rolling_window(values: list[float], size: int) -> list[float]:
    return values[-size:] if len(values) >= size else values


def estimate_candle_interval(candles: list[PriceCandle]) -> timedelta:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    deltas = [
        (ordered[idx].timestamp - ordered[idx - 1].timestamp).total_seconds()
        for idx in range(1, len(ordered))
        if (ordered[idx].timestamp - ordered[idx - 1].timestamp).total_seconds() > 0
    ]
    if not deltas:
        return timedelta(hours=1)
    return timedelta(seconds=max(60, int(median(deltas))))


def classify_realized_direction(reference_price: float, realized_price: float, flat_threshold_pct: float = 0.25) -> str:
    change_pct = _pct_change(realized_price, reference_price)
    if change_pct >= flat_threshold_pct:
        return "up"
    if change_pct <= -flat_threshold_pct:
        return "down"
    return "sideways"


def _build_features(candles: list[PriceCandle], lookback: int | None = None) -> dict[str, float]:
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

    short_sma = _average(_rolling_window(closes, short_window))
    long_sma = _average(_rolling_window(closes, long_window))
    momentum_pct = _pct_change(closes[-1], closes[-momentum_window])
    recent_change_pct = _pct_change(closes[-1], closes[-recent_window])

    returns = [_pct_change(closes[idx], closes[idx - 1]) for idx in range(1, len(closes))]
    volatility_pct = pstdev(returns) if len(returns) >= 2 else 0.0

    short_volume = _average(_rolling_window(volumes, short_window))
    long_volume = _average(_rolling_window(volumes, long_window))
    volume_ratio_pct = _pct_change(short_volume, long_volume) if long_volume else 0.0

    support_level = min(_rolling_window(closes, long_window))
    resistance_level = max(_rolling_window(closes, long_window))

    raw_score = (
        (_pct_change(short_sma, long_sma) * 1.4)
        + (momentum_pct * 0.9)
        + (recent_change_pct * 0.7)
        + (volume_ratio_pct * 0.2)
        - (volatility_pct * 0.25)
    )

    probability_up = _sigmoid(raw_score / 6.0)
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


def _build_factors(features: dict[str, float]) -> list[str]:
    factors: list[str] = []
    if features["short_sma"] > features["long_sma"]:
        factors.append("Short-term price action is still trading above the base trend.")
    elif features["short_sma"] < features["long_sma"]:
        factors.append("Short-term price action is still sitting below the base trend.")

    if features["momentum_pct"] > 0:
        factors.append("Recent candles are still pushing upward.")
    elif features["momentum_pct"] < 0:
        factors.append("Recent candles are still losing ground.")

    if features["recent_change_pct"] > 0:
        factors.append("Price has been climbing across the current read.")
    elif features["recent_change_pct"] < 0:
        factors.append("Price has been weakening across the current read.")

    if features["volatility_pct"] >= 2.5:
        factors.append("The move is noisy right now, so conviction is lower.")

    if features["volume_ratio_pct"] > 10:
        factors.append("Volume is backing the move instead of fading.")
    elif features["volume_ratio_pct"] < -10:
        factors.append("Volume is fading, so the move has less support behind it.")

    if not factors:
        factors.append("Signals are mixed, so patience matters more than speed here.")
    return factors


def _build_market_read(features: dict[str, float]) -> str:
    if features["trend_direction"] == "up":
        return "Buyers still have control, but cleaner entries usually come on pullbacks rather than chasing straight into strength."
    if features["trend_direction"] == "down":
        return "Sellers still have control, so weak bounces can fade fast unless price starts reclaiming lost ground."
    return "This market is chopping sideways, so waiting for a cleaner break is better than forcing a trade."


def _build_watch_text(features: dict[str, float]) -> str:
    support_level = f"${features['support_level']:,.2f}"
    resistance_level = f"${features['resistance_level']:,.2f}"
    if features["trend_direction"] == "up":
        return f"Watch whether BTC can keep holding above {support_level} and press into {resistance_level} without losing momentum."
    if features["trend_direction"] == "down":
        return f"Watch whether BTC loses {support_level} again or gets rejected before it can reclaim {resistance_level}."
    return f"Watch for a clean break outside the {support_level} to {resistance_level} range before taking fresh risk."


def _build_setup_quality(direction: str, confidence_score: float, volatility_pct: float) -> str:
    score = 0
    if direction != "sideways":
        score += 1
    if confidence_score >= 75:
        score += 2
    elif confidence_score >= 60:
        score += 1
    if volatility_pct <= 1.8:
        score += 1
    elif volatility_pct >= 3.0:
        score -= 1

    if score >= 3:
        return "A"
    if score >= 1:
        return "B"
    return "C"


def _build_risk_level(direction: str, confidence_score: float, volatility_pct: float, recent_change_pct: float) -> str:
    risk_points = 0
    if direction == "sideways":
        risk_points += 1
    if confidence_score < 60:
        risk_points += 1
    if volatility_pct >= 2.5:
        risk_points += 1
    if abs(recent_change_pct) >= 6:
        risk_points += 1

    if risk_points >= 3:
        return "high"
    if risk_points >= 1:
        return "medium"
    return "low"


def _build_guidance(direction: str, setup_quality: str, risk_level: str) -> str:
    if direction == "up":
        if setup_quality == "A" and risk_level == "low":
            return "Long bias stays intact. Pullbacks are cleaner than chasing extended green candles."
        if risk_level == "high":
            return "Bias still leans long, but this is a messy spot. Wait for a calmer pullback or stronger reclaim."
        return "Long bias is still on, but entries look cleaner on patience than on impulse."
    if direction == "down":
        if setup_quality == "A" and risk_level == "low":
            return "Short bias stays intact. Failed bounces are cleaner than forcing entries after a heavy flush."
        if risk_level == "high":
            return "Bias still leans short, but the move is unstable. Wait for a cleaner rejection or fresh weakness."
        return "Short bias is still on, but the better trade usually comes after a weak bounce, not panic selling."
    return "Best read is to stay patient. Let price break the range cleanly before taking fresh risk."


def _direction_to_bias(direction: str) -> str:
    if direction == "up":
        return "long"
    if direction == "down":
        return "short"
    return "neutral"


def _build_risk_reward_ratio(
    direction: str,
    entry_level: float | None,
    invalidation_level: float | None,
    target_level: float | None,
) -> float | None:
    if entry_level is None or invalidation_level is None or target_level is None:
        return None

    if direction == "up":
        risk = entry_level - invalidation_level
        reward = target_level - entry_level
    elif direction == "down":
        risk = invalidation_level - entry_level
        reward = entry_level - target_level
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def _build_trade_plan(direction: str, risk_level: str, features: dict[str, float]) -> dict[str, float | str | None]:
    latest_close = float(features["latest_close_price"])
    short_sma = float(features["short_sma"])
    support_level = float(features["support_level"])
    resistance_level = float(features["resistance_level"])
    volatility_pct = max(0.5, float(features["volatility_pct"]) * 0.6)
    buffer_multiplier = 1.15 if risk_level == "high" else 1.0
    stop_buffer_pct = volatility_pct * buffer_multiplier

    if direction == "up":
        entry_level = support_level if risk_level == "high" else max(support_level, min(latest_close, short_sma))
        invalidation_level = min(support_level, entry_level) * (1.0 - (stop_buffer_pct / 100.0))
        stop_distance = max(entry_level - invalidation_level, latest_close * 0.005)
        target_level = resistance_level if resistance_level > latest_close else entry_level + (stop_distance * 1.8)
        return {
            "entry_plan": f"Prefer long entries on a pullback near ${entry_level:,.2f} instead of chasing straight strength.",
            "entry_level": round(entry_level, 2),
            "invalidation_plan": f"If BTC loses ${invalidation_level:,.2f}, the long read is no longer clean.",
            "invalidation_level": round(invalidation_level, 2),
            "target_plan": f"First upside target sits near ${target_level:,.2f} if buyers keep control.",
            "target_level": round(target_level, 2),
        }

    if direction == "down":
        entry_level = resistance_level if risk_level == "high" else min(resistance_level, max(latest_close, short_sma))
        invalidation_level = max(resistance_level, entry_level) * (1.0 + (stop_buffer_pct / 100.0))
        stop_distance = max(invalidation_level - entry_level, latest_close * 0.005)
        target_level = support_level if support_level < latest_close else entry_level - (stop_distance * 1.8)
        return {
            "entry_plan": f"Prefer short entries on a weak bounce toward ${entry_level:,.2f} instead of selling the flush.",
            "entry_level": round(entry_level, 2),
            "invalidation_plan": f"If BTC reclaims ${invalidation_level:,.2f}, the short read weakens fast.",
            "invalidation_level": round(invalidation_level, 2),
            "target_plan": f"First downside target sits near ${target_level:,.2f} if sellers stay in control.",
            "target_level": round(target_level, 2),
        }

    return {
        "entry_plan": (
            f"Wait for BTC to break above ${resistance_level:,.2f} or below ${support_level:,.2f} before taking fresh directional risk."
        ),
        "entry_level": None,
        "invalidation_plan": (
            f"If price snaps back inside the ${support_level:,.2f} to ${resistance_level:,.2f} range, step back and wait again."
        ),
        "invalidation_level": None,
        "target_plan": "No clean target yet while BTC is still range-bound.",
        "target_level": None,
    }


def build_trend_summary(candles: list[PriceCandle], lookback: int | None = None) -> TrendSummaryOut:
    if len(candles) < 12:
        raise ValueError("At least 12 candles are required to analyze a trend.")

    features = _build_features(candles, lookback)
    market_read = _build_market_read(features)
    what_to_watch = _build_watch_text(features)

    return TrendSummaryOut(
        latest_close_price=features["latest_close_price"],
        recent_change_pct=features["recent_change_pct"],
        short_sma=features["short_sma"],
        long_sma=features["long_sma"],
        momentum_pct=features["momentum_pct"],
        volatility_pct=features["volatility_pct"],
        trend_direction=features["trend_direction"],
        trend_strength_score=features["trend_strength_score"],
        support_level=features["support_level"],
        resistance_level=features["resistance_level"],
        narrative=market_read,
        market_read=market_read,
        what_to_watch=what_to_watch,
    )


def build_prediction(candles: list[PriceCandle], lookback: int, forecast_horizon: int) -> PredictionOut:
    if len(candles) < 12:
        raise ValueError("At least 12 candles are required to generate a prediction.")

    features = _build_features(candles, lookback)
    horizon_decay = max(0.6, 1.0 - (forecast_horizon * 0.03))
    adjusted_probability_up = _sigmoid(((features["probability_up"] - 0.5) * 10.0) * horizon_decay)
    probability_up = round(adjusted_probability_up * 100.0, 2)
    probability_down = round((1.0 - adjusted_probability_up) * 100.0, 2)
    confidence_score = round(abs(adjusted_probability_up - 0.5) * 200.0, 2)

    if adjusted_probability_up >= 0.55:
        direction = "up"
    elif adjusted_probability_up <= 0.45:
        direction = "down"
    else:
        direction = "sideways"

    bias = _direction_to_bias(direction)
    setup_quality = _build_setup_quality(direction, confidence_score, features["volatility_pct"])
    risk_level = _build_risk_level(direction, confidence_score, features["volatility_pct"], features["recent_change_pct"])
    guidance = _build_guidance(direction, setup_quality, risk_level)
    what_to_watch = _build_watch_text(features)
    trade_plan = _build_trade_plan(direction, risk_level, features)
    risk_reward_ratio = _build_risk_reward_ratio(
        direction,
        trade_plan["entry_level"],
        trade_plan["invalidation_level"],
        trade_plan["target_level"],
    )
    summary_map = {
        "up": "Bias stays long for now.",
        "down": "Bias stays short for now.",
        "sideways": "Best read is to stay patient for now.",
    }

    return PredictionOut(
        generated_at=datetime.now(timezone.utc),
        lookback=lookback,
        forecast_horizon=forecast_horizon,
        direction=direction,
        bias=bias,
        probability_up=probability_up,
        probability_down=probability_down,
        confidence_score=confidence_score,
        setup_quality=setup_quality,
        risk_level=risk_level,
        summary=summary_map[direction],
        guidance=guidance,
        what_to_watch=what_to_watch,
        entry_plan=str(trade_plan["entry_plan"]),
        entry_level=trade_plan["entry_level"],
        invalidation_plan=str(trade_plan["invalidation_plan"]),
        invalidation_level=trade_plan["invalidation_level"],
        target_plan=str(trade_plan["target_plan"]),
        target_level=trade_plan["target_level"],
        risk_reward_ratio=risk_reward_ratio,
        factors=_build_factors(features),
    )
