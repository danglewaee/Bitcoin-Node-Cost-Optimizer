import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trend.db")
os.environ.setdefault("READ_API_KEY", "")
os.environ.setdefault("WRITE_API_KEY", "")
os.environ.setdefault("ALLOWED_ORIGINS", "http://127.0.0.1:8899")

from fastapi import HTTPException

import main


class ApiConfigAndAuthTests(unittest.TestCase):
    def _make_backtest_report(
        self,
        *,
        engine_name: str,
        model_version: str,
        sample_size: int,
        hit_rate: float,
        cumulative_edge: float,
        max_drawdown: float,
        window_edge: float | None = None,
        window_edges: list[float] | None = None,
        regimes: list[str] | None = None,
    ):
        runs = []
        base_time = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        for idx in range(sample_size):
            reference_timestamp = base_time + timedelta(hours=idx)
            target_timestamp = reference_timestamp + timedelta(hours=1)
            strategy_return_pct = window_edges[idx] if window_edges is not None else (window_edge or 0.0)
            market_regime = regimes[idx] if regimes is not None else "trend"
            runs.append(
                main.BacktestRunOut(
                    model_version=model_version,
                    run_id=f"{engine_name}-{idx}",
                    reference_timestamp=reference_timestamp,
                    target_timestamp=target_timestamp,
                    market_regime=market_regime,
                    direction="up",
                    bias="long",
                    setup_quality="A",
                    risk_level="low",
                    confidence_score=70.0,
                    entry_level=100.0,
                    invalidation_level=95.0,
                    target_level=110.0,
                    risk_reward_ratio=2.0,
                    realized_direction="up",
                    realized_change_pct=1.2,
                    strategy_return_pct=strategy_return_pct,
                    outcome_status="right",
                )
            )

        return main.BacktestReportOut(
            engine_name=engine_name,
            model_version=model_version,
            source="coinbase-exchange:BTC-USD",
            lookback=48,
            forecast_horizon=6,
            sample_size=sample_size,
            hit_rate=hit_rate,
            wrong_rate=round(max(0.0, 100.0 - hit_rate), 2),
            flat_rate=0.0,
            avg_realized_change_pct=1.2,
            avg_strategy_return_pct=round(sum(run.strategy_return_pct for run in runs) / sample_size, 2),
            cumulative_strategy_return_pct=cumulative_edge,
            max_drawdown_pct=max_drawdown,
            avg_confidence_score=70.0,
            avg_risk_reward_ratio=2.0,
            long_hit_rate=hit_rate,
            short_hit_rate=0.0,
            summary="test",
            runs=runs,
        )

    def test_parse_allowed_origins(self):
        parsed = main.parse_allowed_origins("http://a.test, http://b.test")
        self.assertEqual(parsed, ["http://a.test", "http://b.test"])

    def test_parse_allowed_origins_rejects_mixed_wildcard(self):
        with self.assertRaises(RuntimeError):
            main.parse_allowed_origins("*,http://a.test")

    def test_validate_environment_rejects_invalid_env(self):
        old_env = main.APP_ENV
        try:
            main.APP_ENV = "invalid"
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env

    def test_validate_environment_rejects_production_without_keys(self):
        old_env = main.APP_ENV
        old_read_key = main.READ_API_KEY
        old_write_key = main.WRITE_API_KEY
        old_db = main.DATABASE_URL
        old_origins = main.ALLOWED_ORIGINS
        try:
            main.APP_ENV = "production"
            main.READ_API_KEY = ""
            main.WRITE_API_KEY = ""
            main.DATABASE_URL = "postgresql+psycopg2://x:y@localhost:5432/z"
            main.ALLOWED_ORIGINS = ["https://app.example.com"]
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env
            main.READ_API_KEY = old_read_key
            main.WRITE_API_KEY = old_write_key
            main.DATABASE_URL = old_db
            main.ALLOWED_ORIGINS = old_origins

    def test_validate_environment_rejects_production_wildcard_cors(self):
        old_env = main.APP_ENV
        old_read_key = main.READ_API_KEY
        old_write_key = main.WRITE_API_KEY
        old_db = main.DATABASE_URL
        old_origins = main.ALLOWED_ORIGINS
        try:
            main.APP_ENV = "production"
            main.READ_API_KEY = "read-key-long-enough"
            main.WRITE_API_KEY = "write-key-long-enough"
            main.DATABASE_URL = "postgresql+psycopg2://x:y@localhost:5432/z"
            main.ALLOWED_ORIGINS = ["*"]
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env
            main.READ_API_KEY = old_read_key
            main.WRITE_API_KEY = old_write_key
            main.DATABASE_URL = old_db
            main.ALLOWED_ORIGINS = old_origins

    def test_require_read_api_key_rejects_missing_or_invalid_key(self):
        old_key = main.READ_API_KEY
        try:
            main.READ_API_KEY = "read-test-key"
            with self.assertRaises(HTTPException):
                main.require_read_api_key(None)
            with self.assertRaises(HTTPException):
                main.require_read_api_key("wrong")
            main.require_read_api_key("read-test-key")
        finally:
            main.READ_API_KEY = old_key

    def test_require_write_api_key_rejects_missing_or_invalid_key(self):
        old_key = main.WRITE_API_KEY
        try:
            main.WRITE_API_KEY = "write-test-key"
            with self.assertRaises(HTTPException):
                main.require_write_api_key(None)
            with self.assertRaises(HTTPException):
                main.require_write_api_key("wrong")
            main.require_write_api_key("write-test-key")
        finally:
            main.WRITE_API_KEY = old_key

    def test_build_run_id_is_stable_for_same_context(self):
        reference_timestamp = datetime(2026, 4, 1, 4, 45, tzinfo=timezone.utc)
        run_id_1 = main.build_run_id("coinbase-exchange:BTC-USD", reference_timestamp, 48, 6)
        run_id_2 = main.build_run_id("coinbase-exchange:BTC-USD", reference_timestamp, 48, 6)

        self.assertEqual(run_id_1, run_id_2)
        self.assertTrue(run_id_1.startswith("bttrend-"))

    def test_shadow_comparison_promotes_only_when_all_gates_pass(self):
        regimes = (["trend"] * 18) + (["sideways"] * 6)
        champion = self._make_backtest_report(
            engine_name="heuristic",
            model_version="heuristic-v1",
            sample_size=24,
            hit_rate=55.0,
            cumulative_edge=3.0,
            max_drawdown=2.0,
            window_edges=([0.2] * 18) + ([0.1] * 6),
            regimes=regimes,
        )
        challenger = self._make_backtest_report(
            engine_name="ml_challenger",
            model_version="ml-v1",
            sample_size=24,
            hit_rate=59.0,
            cumulative_edge=4.4,
            max_drawdown=2.3,
            window_edges=([0.6] * 18) + ([0.15] * 6),
            regimes=regimes,
        )

        comparison = main.build_shadow_comparison(champion, challenger)

        self.assertEqual(comparison.recommendation, "promote_challenger")
        self.assertTrue(comparison.promotion_ready)
        self.assertEqual(comparison.winner, "challenger")
        self.assertEqual(len(comparison.threshold_checks), 7)
        self.assertTrue(all(gate.passed for gate in comparison.threshold_checks))

    def test_shadow_comparison_collects_more_data_below_sample_floor(self):
        champion = self._make_backtest_report(
            engine_name="heuristic",
            model_version="heuristic-v1",
            sample_size=12,
            hit_rate=55.0,
            cumulative_edge=3.0,
            max_drawdown=2.0,
            window_edge=0.2,
        )
        challenger = self._make_backtest_report(
            engine_name="ml_challenger",
            model_version="ml-v1",
            sample_size=12,
            hit_rate=64.0,
            cumulative_edge=5.2,
            max_drawdown=2.1,
            window_edge=0.7,
        )

        comparison = main.build_shadow_comparison(champion, challenger)

        self.assertEqual(comparison.recommendation, "collect_more_data")
        self.assertFalse(comparison.promotion_ready)
        self.assertEqual(comparison.threshold_checks[0].key, "sample_size")
        self.assertFalse(comparison.threshold_checks[0].passed)

    def test_shadow_comparison_holds_champion_when_sideways_regime_is_weak(self):
        regimes = (["trend"] * 18) + (["sideways"] * 6)
        champion = self._make_backtest_report(
            engine_name="heuristic",
            model_version="heuristic-v1",
            sample_size=24,
            hit_rate=55.0,
            cumulative_edge=3.0,
            max_drawdown=2.0,
            window_edges=([0.2] * 18) + ([0.0] * 6),
            regimes=regimes,
        )
        challenger = self._make_backtest_report(
            engine_name="ml_challenger",
            model_version="ml-v1",
            sample_size=24,
            hit_rate=60.0,
            cumulative_edge=4.2,
            max_drawdown=2.3,
            window_edges=([0.45] * 18) + ([-0.4] * 6),
            regimes=regimes,
        )

        comparison = main.build_shadow_comparison(champion, challenger)

        self.assertEqual(comparison.recommendation, "hold_champion")
        self.assertFalse(comparison.promotion_ready)
        sideways_gate = next(gate for gate in comparison.threshold_checks if gate.key == "sideways_regime")
        self.assertEqual(sideways_gate.status, "fail")
        self.assertFalse(sideways_gate.passed)

    def test_routes_protected_in_p15_scope(self):
        read_routes = {
            "/prices/latest",
            "/prices/recent",
            "/summary",
            "/trend/summary",
            "/predict",
            "/signals/recent",
            "/signals/stats",
            "/signals/performance",
            "/reads/multi",
            "/backtest/report",
            "/backtest/export.csv",
        }
        write_routes = {"/prices", "/prices/reset"}

        route_deps = {}
        for route in main.app.routes:
            path = getattr(route, "path", None)
            if path in read_routes | write_routes:
                route_deps[path] = {dep.call.__name__ for dep in route.dependant.dependencies if dep.call is not None}

        for path in read_routes:
            self.assertIn("require_read_api_key", route_deps[path])

        for path in write_routes:
            self.assertIn("require_write_api_key", route_deps[path])


if __name__ == "__main__":
    unittest.main()
