import unittest

from action_engine import build_action_plan
from optimizer import build_recommendations
from schemas import ActionPlanRequest


class OptimizerAndActionEngineTests(unittest.TestCase):
    def test_build_recommendations_returns_near_optimal_when_no_signals(self):
        recs = build_recommendations(avg_cpu=60, avg_ram=70, avg_disk_gb=200, avg_sync_lag=2)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].title, "Current profile is near-optimal")

    def test_build_recommendations_detects_rightsizing(self):
        recs = build_recommendations(avg_cpu=20, avg_ram=30, avg_disk_gb=200, avg_sync_lag=2)
        titles = [r.title for r in recs]
        self.assertIn("Rightsize instance down one tier", titles)

    def test_action_plan_builds_actions_with_summary(self):
        recs = build_recommendations(avg_cpu=20, avg_ram=30, avg_disk_gb=500, avg_sync_lag=30)
        plan = build_action_plan(
            recommendations=recs,
            request=ActionPlanRequest(maintenance_window="off_peak", include_high_risk=False),
            avg_sync_lag=30,
            avg_rpc_p95=120,
        )

        self.assertGreaterEqual(len(plan.actions), 1)
        self.assertIn("Expected monthly savings", plan.summary)


if __name__ == "__main__":
    unittest.main()
