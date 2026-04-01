import os
import unittest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trend.db")
os.environ.setdefault("READ_API_KEY", "")
os.environ.setdefault("WRITE_API_KEY", "")
os.environ.setdefault("ALLOWED_ORIGINS", "http://127.0.0.1:8899")

import main
from fastapi.testclient import TestClient


def sample_candle(close_price: float = 65000.0, timestamp: str | None = None, source: str = "integration-test") -> dict:
    return {
        "open_price": round(close_price * 0.998, 2),
        "high_price": round(close_price * 1.004, 2),
        "low_price": round(close_price * 0.994, 2),
        "close_price": round(close_price, 2),
        "volume_btc": 1200.0,
        "source": source,
        "timestamp": timestamp,
    }


class ApiHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        main.READ_API_KEY = "read-integration-key"
        main.WRITE_API_KEY = "write-integration-key"

    def setUp(self):
        self.client.delete("/prices/reset", headers={"X-API-Key": "write-integration-key"})

    def _seed_series(
        self,
        total: int = 18,
        source: str = "integration-test",
        base_price: float = 62000,
        step: float = 350,
        day: int = 1,
    ) -> None:
        for idx in range(total):
            close_price = base_price + (idx * step)
            response = self.client.post(
                "/prices",
                json=sample_candle(
                    close_price=close_price,
                    source=source,
                    timestamp=f"2026-03-{day:02d}T{idx:02d}:00:00Z",
                ),
                headers={"X-API-Key": "write-integration-key"},
            )
            self.assertEqual(response.status_code, 200)

    def test_write_endpoint_requires_write_key(self):
        unauthorized = self.client.post("/prices", json=sample_candle())
        self.assertEqual(unauthorized.status_code, 401)

        authorized = self.client.post("/prices", json=sample_candle(), headers={"X-API-Key": "write-integration-key"})
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("id", authorized.json())

    def test_read_endpoints_require_read_key(self):
        self._seed_series()

        unauthorized = self.client.get("/prices/latest")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = self.client.get("/prices/latest", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("close_price", authorized.json())

    def test_summary_and_predict_return_trend_outputs(self):
        self._seed_series()

        summary = self.client.get("/trend/summary?lookback=18", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["trend_direction"], "up")
        self.assertIn("market_read", summary.json())
        self.assertIn("what_to_watch", summary.json())

        prediction = self.client.post(
            "/predict",
            json={"lookback": 18, "forecast_horizon": 6},
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(prediction.status_code, 200)
        self.assertIn(prediction.json()["direction"], {"up", "down", "sideways"})
        self.assertIn(prediction.json()["bias"], {"long", "short", "neutral"})
        self.assertIn(prediction.json()["setup_quality"], {"A", "B", "C"})
        self.assertIn(prediction.json()["risk_level"], {"low", "medium", "high"})
        self.assertIn("probability_up", prediction.json())
        self.assertIn("entry_plan", prediction.json())
        self.assertIn("invalidation_plan", prediction.json())
        self.assertIn("target_plan", prediction.json())
        self.assertIn("risk_reward_ratio", prediction.json())

    def test_signal_history_tracks_and_resolves_predictions(self):
        self._seed_series()

        prediction = self.client.post(
            "/predict",
            json={"lookback": 18, "forecast_horizon": 3},
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(prediction.status_code, 200)

        pending_history = self.client.get("/signals/recent?limit=5", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(pending_history.status_code, 200)
        self.assertEqual(pending_history.json()[0]["outcome_status"], "pending")
        self.assertIn("entry_plan", pending_history.json()[0])
        self.assertIn("invalidation_plan", pending_history.json()[0])
        self.assertIn("target_plan", pending_history.json()[0])
        self.assertIn("risk_reward_ratio", pending_history.json()[0])

        for idx in range(18, 22):
            close_price = 62000 + (idx * 350)
            response = self.client.post(
                "/prices",
                json=sample_candle(close_price=close_price, timestamp=f"2026-03-01T{idx:02d}:00:00Z"),
                headers={"X-API-Key": "write-integration-key"},
            )
            self.assertEqual(response.status_code, 200)

        resolved_history = self.client.get("/signals/recent?limit=5", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(resolved_history.status_code, 200)
        self.assertIn(resolved_history.json()[0]["outcome_status"], {"right", "wrong", "flat"})
        self.assertIsNotNone(resolved_history.json()[0]["resolved_direction"])

        stats = self.client.get("/signals/stats?limit=10", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(stats.status_code, 200)
        self.assertIn("hit_rate", stats.json())
        self.assertGreaterEqual(stats.json()["sample_size"], 1)
        self.assertGreaterEqual(stats.json()["resolved_signals"], 1)

        performance = self.client.get("/signals/performance?limit=10", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(performance.status_code, 200)
        self.assertIn("bias_breakdown", performance.json())
        self.assertIn("setup_breakdown", performance.json())

    def test_multi_reads_returns_fast_core_and_bigger_picture(self):
        self._seed_series()

        response = self.client.get("/reads/multi", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["reads"]), 3)
        self.assertEqual([item["label"] for item in payload["reads"]], ["Fast", "Core", "Bigger Picture"])
        self.assertIn(payload["reads"][0]["bias"], {"long", "short", "neutral"})
        self.assertIn("entry_plan", payload["reads"][0])
        self.assertIn("invalidation_plan", payload["reads"][0])
        self.assertIn("target_plan", payload["reads"][0])
        self.assertIn("risk_reward_ratio", payload["reads"][0])

    def test_source_filter_scopes_reads_and_backtest_to_one_feed(self):
        self._seed_series(total=24, source="integration-test", base_price=62000, step=350, day=1)
        self._seed_series(total=18, source="integration-alt", base_price=88000, step=-225, day=2)

        latest_default = self.client.get("/prices/latest", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(latest_default.status_code, 200)
        self.assertEqual(latest_default.json()["source"], "integration-alt")

        latest_filtered = self.client.get(
            "/prices/latest?source=integration-test",
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(latest_filtered.status_code, 200)
        self.assertEqual(latest_filtered.json()["source"], "integration-test")

        prediction = self.client.post(
            "/predict?source=integration-alt",
            json={"lookback": 18, "forecast_horizon": 3},
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(prediction.status_code, 200)
        self.assertEqual(prediction.json()["direction"], "down")

        history = self.client.get(
            "/signals/recent?limit=5&source=integration-alt",
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(history.status_code, 200)
        self.assertTrue(all(row["source"] == "integration-alt" for row in history.json()))

        backtest = self.client.get(
            "/backtest/report?lookback=12&forecast_horizon=3&sample_size=10&source=integration-alt",
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(backtest.status_code, 200)
        self.assertEqual(backtest.json()["sample_size"], 4)

    def test_backtest_report_returns_walk_forward_metrics(self):
        self._seed_series(total=24)

        response = self.client.get(
            "/backtest/report?lookback=12&forecast_horizon=3&sample_size=6",
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertGreaterEqual(payload["sample_size"], 1)
        self.assertIn("hit_rate", payload)
        self.assertIn("cumulative_strategy_return_pct", payload)
        self.assertIn("avg_risk_reward_ratio", payload)
        self.assertTrue(payload["summary"])
        self.assertGreaterEqual(len(payload["runs"]), 1)
        self.assertIn("strategy_return_pct", payload["runs"][0])
        self.assertIn("outcome_status", payload["runs"][0])

    def test_backtest_export_csv_returns_scoped_rows(self):
        self._seed_series(total=24, source="integration-test", day=1)
        self._seed_series(total=24, source="integration-alt", base_price=91000, step=-175, day=2)

        response = self.client.get(
            "/backtest/export.csv?lookback=12&forecast_horizon=3&sample_size=6&source=integration-test",
            headers={"X-API-Key": "read-integration-key"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment; filename=", response.headers["content-disposition"])

        lines = response.text.strip().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("source,lookback,forecast_horizon"))
        self.assertIn("integration-test", response.text)
        self.assertNotIn("integration-alt,", response.text)

    def test_ingest_upserts_same_source_and_timestamp(self):
        timestamp = "2026-03-01T00:00:00Z"
        first = sample_candle(close_price=61000, timestamp=timestamp)
        second = sample_candle(close_price=62000, timestamp=timestamp)

        response_1 = self.client.post("/prices", json=first, headers={"X-API-Key": "write-integration-key"})
        response_2 = self.client.post("/prices", json=second, headers={"X-API-Key": "write-integration-key"})

        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 200)
        self.assertEqual(response_1.json()["id"], response_2.json()["id"])

        recent = self.client.get("/prices/recent?limit=12", headers={"X-API-Key": "read-integration-key"})
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(len(recent.json()), 1)
        self.assertEqual(recent.json()[0]["close_price"], second["close_price"])


if __name__ == "__main__":
    unittest.main()
