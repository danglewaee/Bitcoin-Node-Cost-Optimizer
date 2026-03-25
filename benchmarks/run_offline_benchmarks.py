import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from models import PriceCandle
from trend_engine import build_prediction, build_trend_summary


PROFILES = {
    "bull": {"drift_pct": 0.45, "volatility_pct": 0.55, "expected_direction": "up"},
    "bear": {"drift_pct": -0.45, "volatility_pct": 0.55, "expected_direction": "down"},
    "sideways": {"drift_pct": 0.02, "volatility_pct": 0.28, "expected_direction": "sideways"},
}


def build_series(profile: dict, samples: int, seed: int) -> list[PriceCandle]:
    random.seed(seed)
    candles: list[PriceCandle] = []
    close_price = 65000.0
    timestamp = datetime.now(timezone.utc) - timedelta(hours=samples)

    for _ in range(samples):
        move_pct = profile["drift_pct"] + random.gauss(0, profile["volatility_pct"])
        open_price = close_price
        close_price = max(1000.0, open_price * (1 + move_pct / 100.0))
        wick_pct = abs(random.gauss(0.2, 0.07))
        high_price = max(open_price, close_price) * (1 + wick_pct / 100.0)
        low_price = min(open_price, close_price) * (1 - wick_pct / 100.0)
        volume_btc = 900 + (abs(move_pct) * 250) + random.uniform(0, 180)

        candles.append(
            PriceCandle(
                open_price=round(open_price, 2),
                high_price=round(high_price, 2),
                low_price=round(low_price, 2),
                close_price=round(close_price, 2),
                volume_btc=round(volume_btc, 2),
                source="offline-benchmark",
                timestamp=timestamp,
            )
        )
        timestamp += timedelta(hours=1)

    return candles


def run_profile(profile: dict, samples: int, seed: int) -> dict:
    candles = build_series(profile, samples=samples, seed=seed)
    summary = build_trend_summary(candles, lookback=samples)
    prediction = build_prediction(candles, lookback=samples, forecast_horizon=6)

    return {
        "expected_direction": profile["expected_direction"],
        "predicted_direction": prediction.direction,
        "matched": prediction.direction == profile["expected_direction"],
        "probability_up": prediction.probability_up,
        "probability_down": prediction.probability_down,
        "confidence_score": prediction.confidence_score,
        "trend_strength_score": summary.trend_strength_score,
        "recent_change_pct": summary.recent_change_pct,
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# Offline Benchmark Report - Bitcoin Trend Direction Predictor",
        "",
        f"Generated at: `{report['generated_at_utc']}`",
        "",
        "| Profile | Expected | Predicted | Match | Prob Up | Prob Down | Confidence | Recent Change |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for name, row in report["profiles"].items():
        lines.append(
            f"| {name} | {row['expected_direction']} | {row['predicted_direction']} | {row['matched']} | "
            f"{row['probability_up']:.2f}% | {row['probability_down']:.2f}% | {row['confidence_score']:.2f} | "
            f"{row['recent_change_pct']:.2f}% |"
        )

    lines.extend(["", "## Summary", report["summary"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run offline benchmarks for the bitcoin trend predictor")
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="benchmarks/output")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for idx, (name, profile) in enumerate(PROFILES.items()):
        results[name] = run_profile(profile=profile, samples=args.samples, seed=args.seed + idx)

    matched = sum(1 for row in results.values() if row["matched"])
    summary = f"Offline directional benchmark matched {matched}/{len(results)} synthetic regimes."

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "samples_per_profile": args.samples,
        "profiles": results,
        "summary": summary,
    }

    json_path = output_dir / "offline_report.json"
    md_path = output_dir / "offline_report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(summary)


if __name__ == "__main__":
    main()
