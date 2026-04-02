from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from decision_layer import (
    build_factors,
    build_guidance,
    build_market_read,
    build_risk_level,
    build_risk_reward_ratio,
    build_setup_quality,
    build_trade_plan,
    build_watch_text,
    direction_to_bias,
)
from engines.registry import get_signal_engine
from feature_builder import build_feature_snapshot, pct_change
from models import PriceCandle
from schemas import PredictionOut, TrendSummaryOut

ACTIVE_SIGNAL_ENGINE = get_signal_engine()
TREND_ENGINE_MODEL_VERSION = ACTIVE_SIGNAL_ENGINE.model_version


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
    change_pct = pct_change(realized_price, reference_price)
    if change_pct >= flat_threshold_pct:
        return "up"
    if change_pct <= -flat_threshold_pct:
        return "down"
    return "sideways"


def build_trend_summary(candles: list[PriceCandle], lookback: int | None = None) -> TrendSummaryOut:
    if len(candles) < 12:
        raise ValueError("At least 12 candles are required to analyze a trend.")

    features = build_feature_snapshot(candles, lookback)
    market_read = build_market_read(features)
    what_to_watch = build_watch_text(features)

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

    features = build_feature_snapshot(candles, lookback)
    engine_decision = ACTIVE_SIGNAL_ENGINE.score(features, forecast_horizon)
    direction = engine_decision.direction
    confidence_score = engine_decision.confidence_score
    bias = direction_to_bias(direction)
    setup_quality = build_setup_quality(direction, confidence_score, features["volatility_pct"])
    risk_level = build_risk_level(direction, confidence_score, features["volatility_pct"], features["recent_change_pct"])
    guidance = build_guidance(direction, setup_quality, risk_level)
    what_to_watch = build_watch_text(features)
    trade_plan = build_trade_plan(direction, risk_level, features)
    risk_reward_ratio = build_risk_reward_ratio(
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
        model_version=ACTIVE_SIGNAL_ENGINE.model_version,
        lookback=lookback,
        forecast_horizon=forecast_horizon,
        direction=direction,
        bias=bias,
        probability_up=engine_decision.probability_up,
        probability_down=engine_decision.probability_down,
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
        factors=build_factors(features),
    )
