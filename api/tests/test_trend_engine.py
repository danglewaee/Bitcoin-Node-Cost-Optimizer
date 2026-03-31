import unittest
from datetime import datetime, timedelta, timezone

from models import PriceCandle
from trend_engine import build_prediction, build_trend_summary


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


if __name__ == "__main__":
    unittest.main()
