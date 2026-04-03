import unittest
from datetime import datetime, timedelta, timezone

from engines.ml_challenger_engine import MLChallengerSignalEngine
from engines.registry import get_signal_engine
from models import PriceCandle
from trend_engine import (
    TREND_ENGINE_MODEL_VERSION,
    build_prediction,
    build_prediction_with_engine,
    build_trend_summary,
    get_required_history_for_prediction,
)


def build_candle(index: int, close_price: float, volume_btc: float = 1000.0) -> PriceCandle:
    return PriceCandle(
        open_price=close_price * 0.998,
        high_price=close_price * 1.004,
        low_price=close_price * 0.994,
        close_price=close_price,
        volume_btc=volume_btc,
        source="unit-test",
        timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(hours=index),
    )


class TrendEngineTests(unittest.TestCase):
    def test_registry_defaults_to_heuristic_engine(self):
        engine = get_signal_engine()

        self.assertEqual(engine.engine_name, "heuristic")
        self.assertEqual(engine.model_version, TREND_ENGINE_MODEL_VERSION)

    def test_registry_can_return_ml_challenger_engine(self):
        engine = get_signal_engine("ml_challenger")

        self.assertEqual(engine.engine_name, "ml_challenger")
        self.assertTrue(engine.model_version.startswith("logistic-challenger@"))
        self.assertGreater(get_required_history_for_prediction(48, 6, engine), 48)

    def test_build_trend_summary_detects_bullish_series(self):
        candles = [build_candle(idx, 60000 + (idx * 500)) for idx in range(24)]
        summary = build_trend_summary(candles, lookback=24)

        self.assertEqual(summary.trend_direction, "up")
        self.assertGreater(summary.trend_strength_score, 0)
        self.assertGreater(summary.short_sma, summary.long_sma)
        self.assertTrue(summary.market_read)
        self.assertTrue(summary.what_to_watch)

    def test_build_prediction_can_return_bearish_bias(self):
        candles = [build_candle(idx, 70000 - (idx * 450), volume_btc=1400) for idx in range(24)]
        prediction = build_prediction(candles, lookback=24, forecast_horizon=6)

        self.assertEqual(prediction.direction, "down")
        self.assertEqual(prediction.model_version, TREND_ENGINE_MODEL_VERSION)
        self.assertEqual(prediction.bias, "short")
        self.assertGreater(prediction.probability_down, prediction.probability_up)
        self.assertGreaterEqual(prediction.confidence_score, 0)
        self.assertIn(prediction.setup_quality, {"A", "B", "C"})
        self.assertIn(prediction.risk_level, {"low", "medium", "high"})
        self.assertTrue(prediction.guidance)
        self.assertTrue(prediction.what_to_watch)
        self.assertTrue(prediction.entry_plan)
        self.assertTrue(prediction.invalidation_plan)
        self.assertTrue(prediction.target_plan)
        self.assertIsNotNone(prediction.entry_level)
        self.assertIsNotNone(prediction.invalidation_level)
        self.assertIsNotNone(prediction.target_level)
        self.assertGreater(prediction.invalidation_level, prediction.entry_level)
        self.assertLess(prediction.target_level, prediction.entry_level)
        self.assertIsNotNone(prediction.risk_reward_ratio)
        self.assertGreater(prediction.risk_reward_ratio, 0)

    def test_build_prediction_includes_trade_levels_for_bullish_bias(self):
        candles = [build_candle(idx, 60000 + (idx * 500), volume_btc=1200) for idx in range(24)]
        prediction = build_prediction(candles, lookback=24, forecast_horizon=6)

        self.assertEqual(prediction.direction, "up")
        self.assertIsNotNone(prediction.entry_level)
        self.assertIsNotNone(prediction.invalidation_level)
        self.assertIsNotNone(prediction.target_level)
        self.assertGreater(prediction.entry_level, prediction.invalidation_level)
        self.assertGreater(prediction.target_level, prediction.entry_level)
        self.assertIsNotNone(prediction.risk_reward_ratio)
        self.assertGreater(prediction.risk_reward_ratio, 0)

    def test_build_prediction_rejects_insufficient_history(self):
        candles = [build_candle(idx, 60000 + idx) for idx in range(6)]
        with self.assertRaises(ValueError):
            build_prediction(candles, lookback=6, forecast_horizon=4)

    def test_ml_challenger_engine_returns_same_prediction_contract(self):
        candles = [build_candle(idx, 60000 + (idx * 120), volume_btc=1000 + ((idx % 5) * 75)) for idx in range(180)]
        challenger = MLChallengerSignalEngine(training_samples=48, epochs=80)
        prediction = build_prediction_with_engine(challenger, candles, lookback=48, forecast_horizon=6)

        self.assertIn(prediction.direction, {"up", "down", "sideways"})
        self.assertIn(prediction.bias, {"long", "short", "neutral"})
        self.assertGreaterEqual(prediction.probability_up, 0.0)
        self.assertGreaterEqual(prediction.probability_down, 0.0)
        self.assertLessEqual(prediction.probability_up, 100.0)
        self.assertLessEqual(prediction.probability_down, 100.0)
        self.assertEqual(prediction.model_version, challenger.model_version)
        self.assertTrue(prediction.guidance)
        self.assertTrue(prediction.what_to_watch)
        self.assertTrue(prediction.factors)

    def test_summary_regression_for_bullish_series(self):
        candles = [build_candle(idx, 60000 + (idx * 500), volume_btc=1200) for idx in range(24)]
        summary = build_trend_summary(candles, lookback=24)

        self.assertEqual(summary.latest_close_price, 71500.0)
        self.assertEqual(summary.recent_change_pct, 19.17)
        self.assertEqual(summary.short_sma, 68750.0)
        self.assertEqual(summary.long_sma, 65750.0)
        self.assertEqual(summary.momentum_pct, 8.33)
        self.assertEqual(summary.volatility_pct, 0.04)
        self.assertEqual(summary.trend_direction, "up")
        self.assertEqual(summary.trend_strength_score, 97.91)
        self.assertEqual(summary.support_level, 60000.0)
        self.assertEqual(summary.resistance_level, 71500.0)
        self.assertEqual(
            summary.market_read,
            "Buyers still have control, but cleaner entries usually come on pullbacks rather than chasing straight into strength.",
        )
        self.assertEqual(
            summary.what_to_watch,
            "Watch whether BTC can keep holding above $60,000.00 and press into $71,500.00 without losing momentum.",
        )

    def test_prediction_regression_for_bearish_series(self):
        candles = [build_candle(idx, 70000 - (idx * 450), volume_btc=1400) for idx in range(24)]
        prediction = build_prediction(candles, lookback=24, forecast_horizon=6)

        self.assertEqual(prediction.direction, "down")
        self.assertEqual(prediction.bias, "short")
        self.assertEqual(prediction.probability_up, 1.93)
        self.assertEqual(prediction.probability_down, 98.07)
        self.assertEqual(prediction.confidence_score, 96.14)
        self.assertEqual(prediction.setup_quality, "A")
        self.assertEqual(prediction.risk_level, "medium")
        self.assertEqual(prediction.summary, "Bias stays short for now.")
        self.assertEqual(
            prediction.guidance,
            "Short bias is still on, but the better trade usually comes after a weak bounce, not panic selling.",
        )
        self.assertEqual(
            prediction.what_to_watch,
            "Watch whether BTC loses $59,650.00 again or gets rejected before it can reclaim $70,000.00.",
        )
        self.assertEqual(
            prediction.entry_plan,
            "Prefer short entries on a weak bounce toward $62,125.00 instead of selling the flush.",
        )
        self.assertEqual(prediction.entry_level, 62125.0)
        self.assertEqual(
            prediction.invalidation_plan,
            "If BTC reclaims $70,350.00, the short read weakens fast.",
        )
        self.assertEqual(prediction.invalidation_level, 70350.0)
        self.assertEqual(
            prediction.target_plan,
            "First downside target sits near $47,320.00 if sellers stay in control.",
        )
        self.assertEqual(prediction.target_level, 47320.0)
        self.assertEqual(prediction.risk_reward_ratio, 1.8)
        self.assertEqual(
            prediction.factors,
            [
                "Short-term price action is still sitting below the base trend.",
                "Recent candles are still losing ground.",
                "Price has been weakening across the current read.",
            ],
        )

    def test_prediction_regression_for_sideways_series(self):
        candles = [
            build_candle(idx, 65000 + ((-1) ** idx) * 80 + idx * 5, volume_btc=1100 + (idx % 3) * 20)
            for idx in range(24)
        ]
        prediction = build_prediction(candles, lookback=24, forecast_horizon=6)

        self.assertEqual(prediction.direction, "sideways")
        self.assertEqual(prediction.bias, "neutral")
        self.assertEqual(prediction.probability_up, 48.37)
        self.assertEqual(prediction.probability_down, 51.63)
        self.assertEqual(prediction.confidence_score, 3.25)
        self.assertEqual(prediction.setup_quality, "B")
        self.assertEqual(prediction.risk_level, "medium")
        self.assertEqual(prediction.summary, "Best read is to stay patient for now.")
        self.assertEqual(
            prediction.guidance,
            "Best read is to stay patient. Let price break the range cleanly before taking fresh risk.",
        )
        self.assertEqual(
            prediction.what_to_watch,
            "Watch for a clean break outside the $64,925.00 to $65,190.00 range before taking fresh risk.",
        )
        self.assertIsNone(prediction.entry_level)
        self.assertIsNone(prediction.invalidation_level)
        self.assertIsNone(prediction.target_level)
        self.assertIsNone(prediction.risk_reward_ratio)
        self.assertEqual(
            prediction.factors,
            [
                "Short-term price action is still trading above the base trend.",
                "Recent candles are still losing ground.",
                "Price has been weakening across the current read.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
