import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


PROFILES = {
    "bull": {"drift_pct": 0.45, "volatility_pct": 0.55, "expected_direction": "up"},
    "bear": {"drift_pct": -0.45, "volatility_pct": 0.55, "expected_direction": "down"},
    "sideways": {"drift_pct": 0.02, "volatility_pct": 0.28, "expected_direction": "sideways"},
}


def build_candle_series(profile: dict, samples: int, seed: int) -> list[dict]:
    random.seed(seed)
    candles: list[dict] = []
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
            {
                "open_price": round(open_price, 2),
                "high_price": round(high_price, 2),
                "low_price": round(low_price, 2),
                "close_price": round(close_price, 2),
                "volume_btc": round(volume_btc, 2),
                "source": "benchmark",
                "timestamp": timestamp.isoformat(),
            }
        )
        timestamp += timedelta(hours=1)

    return candles


def run_profile(
    api_url: str,
    name: str,
    profile: dict,
    samples: int,
    seed: int,
    read_headers: dict[str, str],
    write_headers: dict[str, str],
) -> dict:
    requests.delete(f"{api_url}/prices/reset", headers=write_headers, timeout=10).raise_for_status()
    for candle in build_candle_series(profile, samples=samples, seed=seed):
        requests.post(f"{api_url}/prices", json=candle, headers=write_headers, timeout=10).raise_for_status()

    summary = requests.get(f"{api_url}/trend/summary?lookback={samples}", headers=read_headers, timeout=15)
    summary.raise_for_status()
    prediction = requests.post(
        f"{api_url}/predict",
        json={"lookback": samples, "forecast_horizon": 6},
        headers=read_headers,
        timeout=15,
    )
    prediction.raise_for_status()

    summary_json = summary.json()
    prediction_json = prediction.json()
    predicted_direction = prediction_json["direction"]

    return {
        "expected_direction": profile["expected_direction"],
        "predicted_direction": predicted_direction,
        "matched": predicted_direction == profile["expected_direction"],
        "probability_up": prediction_json["probability_up"],
        "probability_down": prediction_json["probability_down"],
        "confidence_score": prediction_json["confidence_score"],
        "trend_strength_score": summary_json["trend_strength_score"],
        "recent_change_pct": summary_json["recent_change_pct"],
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# Benchmark Report - Bitcoin Trend Direction Predictor",
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
    parser = argparse.ArgumentParser(description="Run API benchmarks for the bitcoin trend predictor")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--samples", type=int, default=48, help="Candles per profile")
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed")
    parser.add_argument("--output-dir", default="benchmarks/output", help="Output directory")
    parser.add_argument("--read-key", default=os.getenv("API_READ_KEY", ""), help="Read API key")
    parser.add_argument("--write-key", default=os.getenv("API_WRITE_KEY", ""), help="Write API key")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    read_headers = {"X-API-Key": args.read_key} if args.read_key else {}
    write_headers = {"X-API-Key": args.write_key} if args.write_key else {}

    results: dict[str, dict] = {}
    for idx, (name, profile) in enumerate(PROFILES.items()):
        results[name] = run_profile(
            api_url=args.api_url,
            name=name,
            profile=profile,
            samples=args.samples,
            seed=args.seed + idx,
            read_headers=read_headers,
            write_headers=write_headers,
        )

    matched = sum(1 for row in results.values() if row["matched"])
    summary = f"Directional benchmark matched {matched}/{len(results)} synthetic regimes."
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "samples_per_profile": args.samples,
        "profiles": results,
        "summary": summary,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(summary)


if __name__ == "__main__":
    main()
